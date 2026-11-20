"""IntelliJ und Review-Umgebung: Auschecken, in IntelliJ öffnen, Review-Umgebung starten und stoppen.

Bereich von App (0.38 aus server.py gelöst). Gemeinsames (cfg, store, Audit, Cache) kommt von App;
Aufrufe in andere Bereiche stehen in USES und werden von tests/test_areas.py geprüft."""

import json
import os
import re
import shlex
import shutil
import subprocess
import threading
import time
from pathlib import Path

import agents
import github
import links
import reviewenv
import tlog
from common import UserError
from secretstore import scrub

log = tlog.get("app")


class IdeArea:
    # Aufrufe in andere Bereiche (tests/test_areas.py prüft, dass genau diese benutzt werden)
    USES = {"area_agents": ("_find_mr",), "area_workspaces": ("_ws_repo_for",)}

    # -- IntelliJ auf dem MR-Commit (0.20)
    def _repo_of(self, host, pid):
        if host == "github":
            r = next((x for x in (self.ghc.get("repos") or []) if github.pid_of(x.get("id") or 0) == pid), None)
        else:
            r = self.proj_cfg.get(pid)
        path = (r or {}).get("repo_path") or ""
        if path:
            return str(Path(path).expanduser())
        return self._ws_repo_for(host, pid)

    def settings_hints(self):
        """Vorschläge für die Einstellungen (0.34): Checkout aus Workspaces, Compose-Dateien und Dockerfile je Projekt,
        Repos mit Dockerfile als Umsysteme. Nur aus dem letzten Workspace-Scan, kein neuer Scan."""
        out = {"projects": {}, "repos": [], "infra": [{"id": k, "label": v["label"]} for k, v in reviewenv.INFRA.items()]}
        for pid, p in self.proj_cfg.items():
            own = os.path.expanduser(p.get("repo_path") or "")
            ws = "" if own else self._ws_repo_for("gitlab", pid)
            path = own or ws
            out["projects"][str(pid)] = {"ws_path": ws, "compose": reviewenv.compose_files_in(path) if path else [],
                                         "dockerfile": bool(path) and reviewenv.has_dockerfile(path)}
        for r in (self.ws_cache or {}).get("repos") or []:
            if r.get("ok") and Path(r["path"], ".git").is_dir() and reviewenv.has_dockerfile(r["path"]):
                out["repos"].append({"name": r["name"], "path": r["path"]})
        out["repos"] = sorted(out["repos"], key=lambda x: x["name"].lower())[:60]
        return out

    def ide_open(self, b, launch=True):
        """Detached Worktree genau auf dem Head-Commit des MR und `idea <pfad>`. Nur lesend gegenüber GitLab (fetch, kein push)."""
        host = "github" if b.get("host") == "github" else "gitlab"
        try:
            pid, iid = int(b.get("project_id")), int(b.get("iid"))
        except (TypeError, ValueError):
            raise UserError("project_id und iid müssen Zahlen sein.")
        it = self._find_mr(host, pid, iid)
        if not it or not it.get("sha"):
            raise UserError("Diesen MR (mit Commit) kenne ich nicht (mehr). Einmal «Neu laden».")
        sha = it["sha"]
        repo = self._repo_of(host, pid)
        if self.demo and not repo:          # Demo: nichts anlegen, nur zeigen, wie es aussähe
            path = "/home/demo/work/.tinyops-wt/%s-mr%d-%s" % (it.get("project", "repo"), iid, sha[:8])
            ref_key = it.get("ref") or links.ref_of(pid, it.get("branch", ""))
            self.store.ide_set(ref_key, host, pid, iid, sha, path, "/home/demo/work/%s" % it.get("project", "repo"))
            self.audit("ide.open", ref_key, sha=sha[:12], path=path, launched=False, demo=True)
            return {"path": path, "sha": sha, "launched": False, "hint": "Demo: Worktree und IntelliJ nur angedeutet. Pfad kopiert.", "ref": ref_key}
        if not repo:
            raise UserError("Für %s fehlt der lokale Checkout (Einstellungen → IntelliJ → Pfad zum Repository)." % it.get("project", pid))
        rc, _, err = self._git(repo, "rev-parse", "--git-dir")
        if rc:
            raise UserError("%s ist kein Git-Repository: %s" % (repo, err[:200]))
        ref = ("refs/pull/%d/head" % iid) if host == "github" else ("refs/merge-requests/%d/head" % iid)
        rc, _, _ = self._git(repo, "cat-file", "-e", sha + "^{commit}")
        if rc:
            rc2, remotes, _ = self._git(repo, "remote")
            remote = "origin" if "origin" in remotes.split() else (remotes.split() or ["origin"])[0]
            rc, _, err = self._git(repo, "fetch", "--no-tags", remote, ref, timeout=180)
            if rc:
                raise UserError("Holen von %s fehlgeschlagen: %s" % (ref, err[:300]))
            rc, _, _ = self._git(repo, "cat-file", "-e", sha + "^{commit}")
            if rc:
                raise UserError("Commit %s ist nach dem Holen nicht da (MR inzwischen neu gepusht? Einmal «Neu laden»)." % sha[:10])
        path = str(Path(repo).parent / ".tinyops-wt" / ("%s-%s%d-%s" % (Path(repo).name, "pr" if host == "github" else "mr", iid, sha[:8])))
        if not Path(path).exists():
            Path(path).parent.mkdir(parents=True, exist_ok=True)
            rc, _, err = self._git(repo, "worktree", "add", "--detach", path, sha, timeout=180)
            if rc:
                raise UserError("Worktree nicht angelegt: %s" % err[:300])
        ref_key = it.get("ref") or links.ref_of(pid, it.get("branch", ""))
        self.store.ide_set(ref_key, host, pid, iid, sha, path, repo)
        launched, hint = self._launch_ide(path) if launch else (False, "")
        self.audit("ide.open", ref_key, sha=sha[:12], path=path, launched=launched)
        return {"path": path, "sha": sha, "launched": launched, "hint": hint, "ref": ref_key}

    # -- Ergebnis eines Agenten ausprobieren (0.32): auschecken, IntelliJ, Review-Umgebung
    def _run_src(self, r):
        """(Lauf, Branch, Quelle, Umgebung für git): woher der Branch des Laufs kommt."""
        svc = self.agents
        a = svc.agent(r["agent"])
        conn = svc.conn_of(a)
        repo, _ = svc._paths(a, r["project_id"])
        branch = r.get("taken") or (r.get("out_branch") if r.get("mode") == "worktree" else "") or ""
        env = None
        if conn is not None:
            argv = agents.ssh_args(conn)[:-2]
            env = {"GIT_SSH_COMMAND": " ".join(shlex.quote(x) for x in argv), "GIT_TERMINAL_PROMPT": "0"}
        return branch, reviewenv.source_url(a, conn, repo), env, conn is None

    def run_try(self, rid):
        """Was du zum Ausprobieren brauchst: Branch, Befehle zum Kopieren, Worktree, Review-Umgebung."""
        r = self.store.agent_run(rid)
        if not r:
            raise UserError("Diesen Lauf gibt es nicht (mehr).")
        try:
            branch, src, _, local = self._run_src(r)
        except agents.AgentError as e:
            branch, src, local = "", "", True
            log.info("Lauf %s: Quelle unbekannt: %s", rid, e)
        clone = self._repo_of("gitlab", r["project_id"]) if r.get("project_id") is not None else ""
        w = self.store.ide_get("run:%d" % rid)
        pe = (self.proj_cfg.get(r["project_id"]) or {}).get("review_env") if r.get("project_id") is not None else None
        st = self._renv_state("run:%d" % rid, r.get("renv"))
        vals = reviewenv.values(r, (w or {}).get("path") or "", (w or {}).get("sha") or "")
        if pe:
            vals, _ = self._renv_vals(pe, "run:%d" % rid, vals, vals["path"])
        return {"branch": branch, "src": src, "commands": reviewenv.checkout_commands(src, branch, local), "clone": clone,
                "worktree": (w or {}).get("path") or "", "sha": ((w or {}).get("sha") or "")[:10],
                "env": {"kind": pe["kind"], "label": reviewenv.KINDS[pe["kind"]]["label"], "name": vals["name"], "port": vals["port"],
                        "url": reviewenv.fill(pe.get("url"), vals, quote=False),
                        "up": reviewenv.fill(pe.get("up"), vals), "down": reviewenv.fill(pe.get("down"), vals)} if pe else None,
                "env_state": st, "push": "git push -u origin %s" % shlex.quote(branch) if branch else ""}

    def run_checkout(self, rid, launch=True):
        """Branch des Laufs in deinen lokalen Checkout holen, eigener Worktree daneben, optional IntelliJ öffnen. Pusht nichts."""
        r = self.store.agent_run(rid)
        if not r or r["status"] in ("zugewiesen", "läuft"):
            raise UserError("Auschecken geht, wenn der Lauf beendet ist.")
        try:
            branch, src, env, _ = self._run_src(r)
        except agents.AgentError as e:
            raise UserError(str(e))
        if not branch:
            raise UserError("Dieser Lauf hat keinen eigenen Branch (gemeinsamer Ordner, oder Export noch nicht übernommen).")
        clone = self._repo_of("gitlab", r["project_id"]) if r.get("project_id") is not None else ""
        name = Path(clone).name if clone else "repo"
        if self.demo and not clone:
            path, sha = "/home/demo/work/.tinyops-wt/dlp-core-run%d" % rid, "d3m0%06d" % rid
            self.store.ide_set("run:%d" % rid, "agent", r["project_id"] or 0, rid, sha, path, "/home/demo/work/dlp-core")
            self.audit("agent.checkout", r["ticket"], run=rid, branch=branch, path=path, demo=True)
            return {"path": path, "sha": sha, "launched": False, "hint": "Demo: Worktree und IntelliJ nur angedeutet."}
        if not clone:
            raise UserError("Für dieses Projekt fehlt dein lokaler Checkout (Einstellungen → IntelliJ und Review-Umgebung → Pfad).")
        rc, _, err = self._git(clone, "rev-parse", "--git-dir")
        if rc:
            raise UserError("%s ist kein Git-Repository: %s" % (clone, err[:200]))
        ref = "refs/tinyops/run-%d" % rid
        rc, _, err = self._git(clone, "fetch", "--no-tags", src, "+%s:%s" % (branch, ref), timeout=180, env=env)
        if rc:
            raise UserError("Branch %s nicht geholt: %s" % (branch, err[:300]))
        _, sha, _ = self._git(clone, "rev-parse", ref)
        path = str(Path(clone).parent / ".tinyops-wt" / ("%s-run%d" % (name, rid)))
        note = ""
        if not Path(path).exists():
            Path(path).parent.mkdir(parents=True, exist_ok=True)
            rc, _, err = self._git(clone, "worktree", "add", "--detach", path, sha, timeout=180)
            if rc:
                raise UserError("Worktree nicht angelegt: %s" % err[:300])
        else:
            _, dirty, _ = self._git(path, "status", "--porcelain")
            if dirty:
                note = "Im Worktree gibt es geänderte Dateien. Nicht aktualisiert."
            else:
                self._git(path, "checkout", "-q", "--detach", sha)
        self.store.ide_set("run:%d" % rid, "agent", r["project_id"] or 0, rid, sha, path, clone)
        launched, hint = self._launch_ide(path) if launch else (False, "")
        self.audit("agent.checkout", r["ticket"], run=rid, branch=branch, sha=sha[:12], path=path, launched=launched)
        return {"path": path, "sha": sha, "launched": launched, "hint": " ".join(x for x in (note, hint) if x)}

    def run_env(self, rid, action):
        """Review-Umgebung starten oder stoppen: nur die Befehle aus den Einstellungen, nur auf Klick, im Worktree des Laufs."""
        r = self.store.agent_run(rid)
        if not r:
            raise UserError("Diesen Lauf gibt es nicht (mehr).")
        pe = (self.proj_cfg.get(r["project_id"]) or {}).get("review_env") if r.get("project_id") is not None else None
        if not pe:
            raise UserError("Für dieses Projekt ist keine Review-Umgebung eingetragen (Einstellungen → IntelliJ und Review-Umgebung).")
        w = self.store.ide_get("run:%d" % rid)
        if action == "up" and (not w or not (self.demo or Path(w["path"]).exists())):
            self.run_checkout(rid, launch=False)
            w = self.store.ide_get("run:%d" % rid)
        if not w:
            raise UserError("Kein Worktree für diesen Lauf.")
        return self._renv_start("run:%d" % rid, r["ticket"], pe, w["path"], reviewenv.values(r, w["path"], w["sha"]), action, run=rid)

    def mr_env(self, b):
        """Review-Umgebung für einen MR (0.34, E2): Worktree auf dem MR-Commit, dann die Befehle aus den Einstellungen. Nur auf Klick."""
        host = "github" if b.get("host") == "github" else "gitlab"
        try:
            pid, iid = int(b.get("project_id")), int(b.get("iid"))
        except (TypeError, ValueError):
            raise UserError("project_id und iid müssen Zahlen sein.")
        it = self._find_mr(host, pid, iid)
        if not it:
            raise UserError("Diesen MR kenne ich nicht (mehr). Einmal «Neu laden».")
        key = "mr:%s:%d:%d" % (host, pid, iid)
        pe = (self.proj_cfg.get(pid) or {}).get("review_env")
        do = b.get("do") or "state"
        if do == "state":
            w = self.store.ide_get(it.get("ref") or links.ref_of(pid, it.get("branch", "")))
            vals = reviewenv.mr_values(it.get("project") or str(pid), iid, it.get("branch"), (w or {}).get("path") or "", (w or {}).get("sha") or "")
            if pe:
                vals, _ = self._renv_vals(pe, key, vals, vals["path"])
            return {"env": {"kind": pe["kind"], "label": reviewenv.KINDS[pe["kind"]]["label"], "name": vals["name"], "port": vals["port"],
                            "url": reviewenv.fill(pe.get("url"), vals, quote=False),
                            "up": reviewenv.fill(pe.get("up"), vals), "down": reviewenv.fill(pe.get("down"), vals)} if pe else None,
                    "state": self._renv_state(key), "worktree": (w or {}).get("path") or ""}
        if do not in ("up", "down"):
            raise UserError("Starten oder stoppen?")
        if not pe:
            raise UserError("Für dieses Projekt ist keine Review-Umgebung eingetragen (Einstellungen → IntelliJ und Review-Umgebung).")
        w = self.store.ide_get(it.get("ref") or links.ref_of(pid, it.get("branch", "")))
        if do == "up" and (not w or w["sha"] != it.get("sha") or not (self.demo or Path(w["path"]).exists())):
            o = self.ide_open({"host": host, "project_id": pid, "iid": iid}, launch=False)
            w = {"path": o["path"], "sha": o["sha"]}
        if not w:
            raise UserError("Kein Worktree für diesen MR. Erst starten.")
        vals = reviewenv.mr_values(it.get("project") or str(pid), iid, it.get("branch"), w["path"], w["sha"])
        return self._renv_start(key, "%s!%d" % (it.get("project") or pid, iid), pe, w["path"], vals, do)

    def _renv_state(self, key, legacy=None):
        st = self.store.renv_get(key)
        if st is None and legacy:                       # Läufe aus 0.32/0.33: Zustand stand am Lauf
            try:
                st = json.loads(legacy)
            except ValueError:
                st = None
        st = st or {}
        if st.get("state") in ("startet", "stoppt") and key not in self._renv_live:
            st["state"] = "unklar"                      # tinyops wurde neu gestartet, während der Befehl lief
        return st

    def _renv_vals(self, pe, key, vals, path):
        """Docker Compose: Compose-Dateien des Repos plus erzeugte Datei für Umsysteme (liegt im Datenordner, nie im Repo).
        Gibt (vals, fehler) zurück."""
        vals = dict(vals, compose_files="")
        if pe.get("kind") != "compose" or not path:
            return vals, ""
        if self.demo and not Path(path).exists():
            return dict(vals, compose_files="-f docker-compose.yml"), ""
        gen = Path(self.data_dir()) / "review-env" / (re.sub(r"[^A-Za-z0-9_.-]+", "_", key) + ".yml")
        files, yaml, err = reviewenv.compose_plan(pe, path, str(gen))
        if err:
            return vals, err
        if yaml:
            gen.parent.mkdir(parents=True, exist_ok=True)
            gen.write_text(yaml, encoding="utf-8")
        return dict(vals, compose_files=reviewenv.compose_arg(files)), ""

    def _renv_start(self, key, target, pe, path, vals, action, run=None):
        if key in self._renv_live:
            raise UserError("Dafür läuft schon ein Befehl. Kurz warten.")
        vals, err = self._renv_vals(pe, key, vals, path)
        if err and action == "up":
            raise UserError(err)
        tmpl = pe.get("up" if action == "up" else "down") or ""
        if not tmpl:
            raise UserError("Für «Stoppen» ist kein Befehl eingetragen.")
        cmd = reviewenv.fill(tmpl, vals)
        url = reviewenv.fill(pe.get("url"), vals, quote=False)
        st = {"state": "startet" if action == "up" else "stoppt", "action": action, "cmd": cmd, "url": url, "ts": time.time(), "log": ""}
        self.store.renv_set(key, st)
        self.audit("review.env." + action, target, run=run, key=key, kind=pe["kind"], name=vals["name"], cmd=cmd[:300])
        self._renv_live.add(key)
        threading.Thread(target=self._env_worker, args=(key, cmd, path, vals, st), daemon=True, name="renv-" + key).start()
        return st

    def _env_worker(self, key, cmd, path, vals, st):
        try:
            if self.demo:
                time.sleep(0.3)
                rc, out = 0, "Demo: Befehl nicht ausgeführt:\n%s" % cmd
            else:
                shx = shutil.which("sh")
                if not shx:
                    rc, out = 127, "Für die Review-Umgebung braucht tinyops «sh» (Windows: Git\\bin von Git for Windows im PATH)."
                else:
                    try:
                        p = subprocess.run([shx, "-c", cmd], cwd=path, capture_output=True, text=True, timeout=1800, stdin=subprocess.DEVNULL,
                                           env=dict(os.environ, REVIEW_NAME=vals["name"], REVIEW_PORT=vals["port"], COMPOSE_PROJECT_NAME=vals["name"]))
                        rc, out = p.returncode, (p.stdout or "") + (p.stderr or "")
                    except subprocess.TimeoutExpired:
                        rc, out = 124, "Nach 30 Minuten abgebrochen."
                    except OSError as e:
                        rc, out = 126, str(e)
            ok = rc == 0
            st.update(state=("läuft" if ok else "fehler") if st["action"] == "up" else ("gestoppt" if ok else "fehler"), rc=rc,
                      log=scrub("\n".join(out.splitlines()[-40:]))[-4000:], done=time.time())
            self.store.renv_set(key, st)
            self.audit("review.env." + st["action"], key, ok=ok, rc=rc)
        finally:
            self._renv_live.discard(key)

    def _launch_ide(self, path):
        cmd = self.cfg.get("ide_command") or "idea {path}"
        try:
            argv = [a.replace("{path}", path) for a in shlex.split(cmd)]
        except ValueError:
            return False, "ide_command lässt sich nicht lesen."
        if "{path}" not in cmd:
            argv.append(path)
        if self.demo:
            return False, "Demo: IntelliJ wird nicht gestartet. Befehl wäre: %s" % " ".join(shlex.quote(a) for a in argv)
        kw = {"stdin": subprocess.DEVNULL, "stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL, "close_fds": True}
        if os.name == "nt":
            kw["creationflags"] = 0x00000008 | 0x00000200
        else:
            kw["start_new_session"] = True
        try:
            subprocess.Popen(argv, **kw)
            return True, ""
        except OSError as e:
            return False, "«%s» liess sich nicht starten (%s). In IntelliJ «File → Open» mit dem Pfad, oder unter Einstellungen → IntelliJ den Befehl anpassen (z. B. den Launcher aus «Tools → Create Command-line Launcher»)." % (argv[0], e.strerror or e)

    def ide_close(self, b, force=False):
        w = self.store.ide_get(str(b.get("ref") or ""))
        if not w:
            raise UserError("Kein IntelliJ-Worktree für diesen MR.")
        p = Path(w["path"])
        if p.parent.name != ".tinyops-wt":
            raise UserError("Unerwarteter Pfad, nichts gelöscht: %s" % w["path"])
        if p.exists():
            rc, out, _ = self._git(str(p), "status", "--porcelain")
            if out and not (force or b.get("force")):
                err = UserError("Im Worktree gibt es %d geänderte Dateien (vom Testen?). Trotzdem entfernen?" % len(out.splitlines()))
                err.data = {"dirty": len(out.splitlines())}
                raise err
            rc, _, e = self._git(w["repo"], "worktree", "remove", "--force", str(p))
            if rc:
                raise UserError("Worktree nicht entfernt: %s" % e[:300])
        self.store.ide_delete(w["ref"])
        self.audit("ide.close", w["ref"], sha=w["sha"][:12], forced=bool(force or b.get("force")))
        return {"ok": True}

    def _ide_cleanup(self, card_key):
        """Beim Abschliessen: saubere IntelliJ-Worktrees der Karte entfernen, geänderte stehen lassen."""
        card = self._cards.get(card_key) or {}
        for x in card.get("items") or []:
            ref = x.get("ref") or (links.ref_of(x["project_id"], x["branch"]) if x.get("project_id") is not None and x.get("branch") else "")
            if ref and self.store.ide_get(ref):
                try:
                    self.ide_close({"ref": ref})
                except UserError as e:
                    log.info("IntelliJ-Worktree %s bleibt: %s", ref, e)
