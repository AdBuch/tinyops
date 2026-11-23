"""Coding-Agenten (Claude Code, Codex, Mistral Vibe, eigene Befehle), lokal oder per SSH in tmux, direkt an Tickets zugewiesen.

Wie es läuft
* Eine Verbindung ist «lokal» (dieser Rechner, losgelöster Prozess, auch unter Windows) oder ein SSH-Ziel.
* Remote startet tinyops pro Aufgabe eine tmux-Sitzung `tinyops-<Nr>` auf dem Zielhost. Prompt, Befehl und Log liegen unter
  `~/.tinyops/runs/` auf dem Zielhost. Der Stand wird aus der Exit-Datei und `tmux has-session` gelesen, das Log mit `tail`.
  Man kann jederzeit selbst mit `tmux attach -t tinyops-<Nr>` hineinschauen.
* Der Prompt enthält nur, was auf der Karte steht (Key, Titel, Projekt, Branch) plus das, was du im Dialog änderst. Er wird als Datei
  übertragen, nie als Teil eines Shell-Befehls.
* Cloud-Agenten (Claude, Codex, Vibe) schicken Prompt und Code an den Anbieter. Deshalb startet nichts, solange beim Projekt nicht
  ausdrücklich «Cloud-Agent erlaubt» steht (Standard: aus).
* Der Befehl eines Agenten kommt aus fest eingebauten Vorlagen. Nur bei «custom» steht er in der config.json, und die Oberfläche kann ihn nicht ändern.
"""
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

import briefing
import secretscan
import secretstore as store
import tlog
import audit as _audit

from agent_rules import (  # noqa: F401  (0.40: aus agents.py gelöst, hier weiter erreichbar)
    AgentError, CLASSES, CLASS_LABEL, CLONE_URL_RE, CLOUD_MODEL_RE, CODE_EXT,
    COMMENT_WARN, DEFAULT_MAX_MINUTES, DIR_RE, EXTRA_RE, GATES, GUARD_DEFAULTS,
    HOST_RE, ID_RE, ISOLATION, MAX_PROMPT, MODEL_RE, PATH_RE,
    PHASES, PHASE_LABEL, PHASE_TEMPLATE, PROVIDERS, PROVIDER_RE, QUOTAS,
    QUOTA_DEFAULT, ROLE_CMD_RE, ROLE_DEFAULTS, ROLE_PHASES, STATUS_ACTIVE, STATUS_ALL,
    USER_RE, _COMMENT, agent_roles, clean_agents, clean_connections, clean_paths,
    clone_hint, data_class, diff_counts, guard_warnings, guards_cfg, guards_text,
    looks_cloud, parse_manual, parse_roles, path_allowed, review_items, slug,
    valid_agent_dir)
from agent_cmd import (  # noqa: F401  (0.40: aus agents.py gelöst, hier weiter erreichbar)
    ANSI, KINDS, MODEL, PROMPT, PROMPT_FILE, PROVIDER,
    _extra, _first, _sh_path, _short, _sub_model, _tool_line,
    agent_args, agent_env, local_spec, provider_of, remote_cmdline, render_stream,
    stream_line, clean_text)
from agent_cmd import SESSIONS, can_resume, find_session, last_reply, new_session  # noqa: F401  (0.40)
from agent_scripts import SESSION_GREP, resume_prep_script  # noqa: F401  (0.40)
from agent_talk import ConversationMixin
from agent_ssh import TOKEN_RE, _friendly, probe, run_remote, ssh_args  # noqa: F401  (0.40: Verbindung in eigenem Modul)
from agent_scripts import (  # noqa: F401  (0.40: aus agents.py gelöst, hier weiter erreichbar)
    HELPERS, ISO_ERR, RUNNER, _HELPER_HEAD, _delim, _resolve_base,
    answer_script, apply_script, changes_script, cleanup_script, helpers_script, parse_checks,
    parse_question, parse_result, prepare_script, remote_kill_script, remote_report_script, remote_start_script,
    remote_status_script, result_script, write_helpers)

log = tlog.get("agents")


# ------------------------------------------------------------------ Dienst: Läufe an Tickets
class Service(ConversationMixin):
    def __init__(self, cfg, store_, run_dir, base_dir):
        self.cfg, self.store = cfg, store_
        self.run_dir, self.base = Path(run_dir), Path(base_dir)
        self.lock = threading.RLock()
        self._access, self._clones = {}, {}       # Zugriff je Agent (kurz gemerkt) und laufende Klone
        self.poll_t = 0.0
        self.audit = lambda *a, **k: None          # setzt die App: audit(action, target, ok, actor, **detail)

    def _ev(self, action, r, ok=True, actor="du", **kw):
        """Audit-Eintrag zu einem Lauf: wer, wo, welche Datenklasse, welcher Modus. Der Prompt nur als Hash."""
        try:
            a = self.agent(r["agent"])
        except AgentError:
            a = None
        p = self.project(r.get("project_id")) if r.get("project_id") is not None else None
        det = {"run": r["id"], "agent": r["agent"], "kind": a["kind"] if a else "?", "cloud": bool(a.get("cloud", True)) if a else None,
               "where": ("lokal" if a["connection"] == "local" else a["connection"]) if a else "?",
               "project_id": r.get("project_id"), "data_class": data_class(p) if p else None}
        if r.get("mode"):
            det["mode"] = r["mode"]
        det.update(kw)
        try:
            self.audit(action, r.get("ticket") or "", ok, actor, **det)
        except Exception as e:      # Audit darf einen Lauf nie aufhalten
            log.error("Audit %s für Lauf %s: %s", action, r.get("id"), e)

    # -- Konfiguration
    def agent_list(self):
        return list(self.cfg.get("agents") or [])

    def conns(self):
        return {c["id"]: c for c in self.cfg.get("connections") or []}

    def agent(self, aid):
        for a in self.agent_list():
            if a["id"] == aid:
                return a
        raise AgentError("Diesen Agenten gibt es nicht (mehr).")

    def conn_of(self, agent):
        if agent["connection"] == "local":
            return None
        c = self.conns().get(agent["connection"])
        if not c:
            raise AgentError("Die Verbindung «%s» dieses Agenten gibt es nicht." % agent["connection"])
        return c

    def projects(self):
        """GitLab-Projekte und GitHub-Repos (Projektnummer 10**12 + Repo-ID)."""
        out = list(self.cfg.get("projects") or [])
        for r in (self.cfg.get("github") or {}).get("repos") or []:
            if r.get("id") and r.get("full"):
                out.append({"id": 10 ** 12 + int(r["id"]), "name": r["full"].split("/")[-1], "agent_dir": r.get("agent_dir", ""),
                            "allow_cloud_agents": bool(r.get("allow_cloud_agents")), "data_class": r.get("data_class"), "cloud_paths": r.get("cloud_paths") or []})
        return out

    def project(self, pid):
        for p in self.projects():
            if p["id"] == pid:
                return p
        return None

    def workdir(self, agent, pid):
        p = self.project(pid)
        if p is None:
            raise AgentError("Bitte ein Projekt wählen (der Agent braucht ein Repository).")
        sub = (p.get("agent_dir") or "").strip() or re.sub(r"[^A-Za-z0-9._-]+", "-", p.get("name") or str(pid)).strip("-") or str(pid)
        root = agent["workspace_root"].rstrip("/\\") if agent["connection"] != "local" else agent["workspace_root"]
        return (root + "/" + sub) if agent["connection"] != "local" else os.path.join(os.path.expanduser(root), *sub.split("/"))

    def allowed(self, agent, pid):
        """(erlaubt, Grund). Datenklasse restricted: nur Agenten ohne Cloud. internal und public: auch Cloud-Agenten."""
        p = self.project(pid)
        if p is None:
            return False, "Projekt fehlt."
        cls = data_class(p)
        if agent.get("cloud", True) and cls == "restricted":
            prov = KINDS[agent["kind"]]["provider"]
            return False, ("Projekt «%s» ist restricted: nur lokale Agenten. %s sendet Prompt und Code an %s. "
                           "Ändern unter Einstellungen → Projekte → Datenklasse (internal oder public)." % (p.get("name"), KINDS[agent["kind"]]["label"], prov))
        if cls == "restricted" and looks_cloud(agent.get("model", "")):
            return False, ("Projekt «%s» ist restricted, und das Modell «%s» sieht nach einem Cloud-Modell aus, obwohl der Agent als lokal eingetragen ist. "
                           "Laufen alle Modelle über denselben Proxy, erkennt tinyops den Unterschied nur am Eintrag: Für ein wirklich lokales Modell dem "
                           "Proxy-Alias einen eindeutigen Namen geben (z. B. qwen-lokal)." % (p.get("name"), agent.get("model")))
        return True, ""

    def mode(self, agent, pid):
        """Wie der Agent arbeitet: export (nur freigegebene Pfade, eigenes Git), worktree (eigener Branch) oder shared (alter gemeinsamer Ordner)."""
        p = self.project(pid) or {}
        if agent.get("cloud", True) and data_class(p) == "internal" and p.get("cloud_paths"):
            return "export"
        return "shared" if agent.get("isolation") == "shared" else "worktree"

    # -- Zugriff: Welche Projekte liegen beim Agenten? (0.27)
    def access(self, aid, fresh=False):
        """Je Projekt: liegt das Repository im Arbeitsordner des Agenten? {pid: {"state": git|dir|missing, "remote": …, "path": …}}. Eine Minute gemerkt."""
        a = self.agent(aid)
        hit = self._access.get(aid)
        if hit and not fresh and time.time() - hit[0] < 60:
            return hit[1]
        conn = self.conn_of(a)
        rows = []
        for p in self.projects():
            try:
                rows.append((p["id"], self.workdir(a, p["id"])))
            except AgentError:
                pass
        parts = ['export GIT_OPTIONAL_LOCKS=0']
        for pid, wd in rows:
            q = _sh_path(wd) if conn is not None else shlex.quote(wd)
            parts.append('if [ -d %s/.git ] || [ -f %s/.git ]; then echo "%d|git|$(git -C %s config --get remote.origin.url 2>/dev/null)"; '
                         'elif [ -e %s ]; then echo "%d|dir|"; else echo "%d|missing|"; fi' % (q, q, pid, q, q, pid, pid))
        rc, out, err = self._sh(a, conn, "; ".join(parts), 0, timeout=25)
        if rc != 0 and not out.strip():
            raise AgentError("Der Arbeitsordner des Agenten ist nicht lesbar: %s" % (clean_text(err, 300).strip() or "Exit %s" % rc))
        paths, res = dict(rows), {}
        for line in out.splitlines():
            f = line.split("|", 2)
            if len(f) == 3 and f[0].isdigit() and f[1] in ("git", "dir", "missing"):
                res[int(f[0])] = {"state": f[1], "remote": re.sub(r"//[^/@\s]+@", "//", clean_text(f[2], 300).strip()), "path": paths.get(int(f[0]), "")}
        self._access[aid] = (time.time(), res)
        return res

    def clone_state(self, aid, pid):
        return dict(self._clones.get((aid, pid)) or {"state": ""})

    def clone(self, aid, pid, url):
        """Das Projekt im Arbeitsordner des Agenten klonen (im Hintergrund). Nur lesend gegenüber dem Server; Zugangsdaten sind die des Zielrechners."""
        a = self.agent(aid)
        p = self.project(pid)
        if p is None:
            raise AgentError("Projekt fehlt.")
        ok, why = self.allowed(a, pid)
        if not ok:
            raise AgentError(why)
        if not CLONE_URL_RE.fullmatch(url or "") or ".." in url:
            raise AgentError("Die Adresse zum Klonen ist ungültig.")
        st = self.access(aid, fresh=True).get(pid) or {}
        if st.get("state") != "missing":
            raise AgentError("Unter %s liegt schon etwas. tinyops überschreibt nichts." % (st.get("path") or "dem Zielpfad"))
        with self.lock:
            if (self._clones.get((aid, pid)) or {}).get("state") == "läuft":
                raise AgentError("Dieses Projekt wird gerade geklont.")
            self._clones[(aid, pid)] = {"state": "läuft", "msg": "", "ts": time.time(), "url": url}
        conn, wd = self.conn_of(a), self.workdir(a, pid)
        q = _sh_path(wd) if conn is not None else shlex.quote(wd)
        script = ('D=%s; [ -e "$D" ] && { echo "Zielordner existiert schon" >&2; exit 3; }; mkdir -p "$(dirname "$D")" || exit 4; '
                  'GIT_TERMINAL_PROMPT=0 GIT_SSH_COMMAND="ssh -o BatchMode=yes" git clone --quiet -- %s "$D" 2>&1 | tail -n 6; '
                  '[ -d "$D/.git" ] || exit 5') % (q, shlex.quote(url))
        self.audit("agent.clone.start", "%s → %s" % (p.get("name"), a["id"]), agent=a["id"], project=pid, url=url, path=wd)

        def work():
            t0 = time.time()
            try:
                rc, out, err = self._sh(a, conn, script, 0, timeout=1200)
                msg = clean_text((out or "") + (err or ""), 1500).strip()
            except AgentError as e:
                rc, msg = 1, str(e)
            msg = re.sub(r"//[^/@\s]+@", "//", msg)
            ok_ = rc == 0
            self._clones[(aid, pid)] = {"state": "fertig" if ok_ else "fehler", "msg": "" if ok_ else (clone_hint(msg, url) or "Exit %s" % rc), "ts": time.time(), "url": url}
            self._access.pop(aid, None)
            self.audit("agent.clone", "%s → %s" % (p.get("name"), a["id"]), ok=ok_, agent=a["id"], project=pid, url=url, path=wd, seconds=int(time.time() - t0),
                       error="" if ok_ else msg[:300])
        threading.Thread(target=work, name="tinyops-clone", daemon=True).start()
        return self.clone_state(aid, pid)

    def out_branch(self, ticket, rid):
        return "agent/%s-%d" % (slug(ticket).replace("_", "-") or "lauf", int(rid))

    def _paths(self, agent, pid):
        """(Repo, Wurzel) als Shell-Ausdruck bzw. Pfad, je nach Ziel."""
        wd = self.workdir(agent, pid)
        if agent["connection"] == "local":
            return wd, os.path.expanduser(agent["workspace_root"])
        return wd, agent["workspace_root"].rstrip("/") or "/"

    def _sh(self, agent, conn, script, rid, timeout=60):
        """Ein Shell-Skript mit R und ID im Run-Ordner ausführen: remote per SSH, lokal mit sh (unter Windows aus Git for Windows)."""
        if conn is not None:
            return run_remote(conn, 'R="$HOME/.tinyops/runs"; ID=%d; mkdir -p "$R"; ' % int(rid) + script, timeout=timeout)
        shx = shutil.which("sh")
        if not shx:
            raise AgentError("Für die Isolation braucht tinyops «sh» (Windows: den Ordner Git\\bin von Git for Windows in den PATH) oder beim Agenten «gemeinsamer Ordner».")
        self.run_dir.mkdir(parents=True, exist_ok=True)
        try:
            r = subprocess.run([shx, "-c", script], capture_output=True, timeout=timeout, stdin=subprocess.DEVNULL,
                               env=dict(os.environ, R=str(self.run_dir), ID=str(int(rid))))
        except subprocess.TimeoutExpired:
            raise AgentError("Zeitüberschreitung bei der Vorbereitung.")
        return r.returncode, r.stdout.decode("utf-8", "replace"), r.stderr.decode("utf-8", "replace")

    def _q(self, agent, path):
        return shlex.quote(path) if agent["connection"] == "local" else _sh_path(path)

    WORKSPACE_LINES = {
        "worktree": "Du arbeitest in einem eigenen Worktree auf dem Branch agent/<key>-<nr> (abgezweigt von {branch}). Committe dort; {pusher}.",
        "export": "Du siehst nur einen Ausschnitt des Repositorys: {paths}. Ändere nur Dateien darin. tinyops übernimmt die Änderungen nach Prüfung als Branch.",
        "shared": "Arbeite im aktuellen Repository. Lege den Branch an, falls er fehlt (vom Hauptbranch aus), und arbeite nur dort.",
    }

    PUSH_LINES = {
        False: "- Kein Merge, kein Push, kein Force-Push, keine Änderungen an CI-Zugangsdaten oder Secrets.",
        True: "- Kein Merge, kein Force-Push, keine Änderungen an CI-Zugangsdaten oder Secrets.\n"
              "- **Pushen:** Am Ende pushst du genau deinen Arbeits-Branch: `git push -u origin HEAD`. Nie main, master, develop oder release/*.",
    }

    def default_prompt(self, title, key, project, branch, url="", mode="shared", paths=(), template="agent-task", extra=None, agent=None):
        """Prompt aus prompts/<template>.md plus die Werkzeug-Hinweise aus prompts/agent-tools.md."""
        f = self.base / "prompts" / ("%s.md" % template)
        try:
            tpl = f.read_text(encoding="utf-8")
        except OSError:
            tpl = "Aufgabe {key}: {title}\nProjekt: {project}\nBranch: {branch}\n{url_line}"
        try:
            tools = (self.base / "prompts" / "agent-tools.md").read_text(encoding="utf-8").strip()
        except OSError:
            tools = ""

        class D(dict):
            def __missing__(self, k):
                return ""
        push = bool((agent or {}).get("push"))
        ws = (self.WORKSPACE_LINES.get(mode, self.WORKSPACE_LINES["shared"]).replace("{branch}", branch or "dem Hauptbranch").replace("{paths}", ", ".join(paths) or "-")
              .replace("{pusher}", "am Ende pushst du diesen Branch" if push else "den Branch pusht der Mensch"))
        phase = {v: k for k, v in PHASE_TEMPLATE.items()}.get(template, "review" if template == "agent-prereview" else "develop")
        vals = D(key=key or "(ohne Key)", title=title or "", project=project or "", branch=branch or "(noch keiner)",
                 url_line=("Link: %s\n" % url) if url else "", workspace_line=ws, push_line=self.PUSH_LINES[push],
                 guards=guards_text(guards_cfg(self.cfg), phase))
        vals.update(extra or {})
        out = re.sub(r"\n{3,}", "\n\n", tpl.format_map(vals)).strip() + "\n"
        if "{guards}" not in tpl:                      # eigene Vorlagen ohne Platzhalter bekommen die Leitplanken trotzdem
            out += "\n" + vals["guards"]
        out += ("\n" + tools + "\n" if tools else "")
        role = ((agent or {}).get("roles") or {}).get(phase)
        return ("%s\n\n%s" % (role, out)) if role else out      # 0.36: Rolle als erster Befehl (z. B. /developer)

    def prompt_info(self, aid, ticket, pid, branch, title, key, url="", template="agent-task", extra=None):
        a = self.agent(aid)
        conn = self.conn_of(a)
        ok, why = self.allowed(a, pid)
        try:
            wd = self.workdir(a, pid)
        except AgentError as e:
            wd, ok, why = "", False, str(e)
        p = self.project(pid) or {}
        mode = self.mode(a, pid) if p else "shared"
        hints = []
        spec = KINDS[a["kind"]]
        if spec.get("write_flags") and not any(x.split("=")[0] in spec["write_flags"] for x in _extra(a)):
            hints.append("%s läuft hier ohne Rückfrage-Fenster. Ohne «%s» in den zusätzlichen Argumenten (Einstellungen → Agenten) darf es laut Dokumentation "
                         "der CLI keine Dateien ändern und endet dann ohne Ergebnis." % (spec["label"], spec["write_hint"]))
        if KINDS[a["kind"]].get("local") and not a.get("cloud", True) and looks_cloud(a.get("model", "")):
            hints.append("Das Modell «%s» sieht nach einem Cloud-Modell aus, der Agent ist aber als lokal eingetragen. Stimmt das nicht, unter "
                         "Einstellungen → Agenten «sendet Daten an einen Cloud-Anbieter» anhaken." % a.get("model"))
        return {"prompt": self.default_prompt(title, key, p.get("name", ""), branch, url, mode, p.get("cloud_paths") or [], template, extra, agent=a), "workdir": wd,
                "hints": hints, "model": a.get("model", ""),
                "where": "lokal auf diesem Rechner" if conn is None else "%s (%s)" % (conn["name"], ("%s@%s" % (conn["user"], conn["host"])) if conn["user"] else conn["host"]),
                "cloud": bool(a.get("cloud", True)), "provider": KINDS[a["kind"]]["provider"], "kind": KINDS[a["kind"]]["label"],
                "allowed": ok, "reason": why, "data_class": data_class(p), "mode": self.mode(a, pid) if p else "",
                "cloud_paths": p.get("cloud_paths") or [] if self.mode(a, pid) == "export" else []}

    # -- Ansichten
    def run_view(self, r):
        a = next((x for x in self.agent_list() if x["id"] == r["agent"]), None)
        conn = None
        try:
            conn = self.conn_of(a) if a else None
        except AgentError:
            pass
        end = r["finished"] or time.time()
        v = dict(r)
        v["prompt_text"] = v.pop("prompt", "")
        for k, empty in (("question", None), ("qa", []), ("checks", []), ("criteria", []), ("ak", []), ("result", None)):
            try:
                v[k] = json.loads(r[k]) if r.get(k) else empty
            except ValueError:
                v[k] = empty
        v["criteria"] = briefing.merge(v["criteria"] or [], v.pop("ak") or [])
        v["ak"] = briefing.counts(v["criteria"])
        v["phase"] = r.get("phase") or "develop"
        v["phase_label"] = PHASE_LABEL.get(v["phase"], v["phase"])
        try:
            steps = json.loads(r.get("msteps") or "[]")
            checks_ = json.loads(r.get("mchecks") or "{}")
        except ValueError:
            steps, checks_ = [], {}
        items = []
        if v["phase"] in ("develop", "review"):
            items += review_items(v)
        if v["phase"] in ("develop", "test"):
            items += [dict(x, kind="test") for x in steps]
            if v["phase"] == "test" or steps:
                items.append({"kind": "test", "step": "Im laufenden System ausprobiert", "expect": "Das Ticket-Ziel ist aus Sicht eines Nutzers erreicht"})
        for i, it in enumerate(items):
            c = checks_.get(str(i)) or {}
            it.update(i=i, done=bool(c.get("done")), note=c.get("note", ""))
        v["manual"] = items
        v["manual_done"] = sum(1 for x in items if x["done"])
        v["gate"], v["gate_note"] = r.get("gate") or "", r.get("gate_note") or ""
        v["guard_warnings"] = guard_warnings(v.get("result"), guards_cfg(self.cfg)) if v["phase"] in ("develop", "test") else []
        v["ack"] = bool(r.get("ack"))
        v["review_brief"] = briefing.review_brief(v) if v["phase"] != "plan" and v.get("result") and r["status"] not in ("zugewiesen", "läuft") else None
        v["checks_ok"] = all(c["exit"] == 0 for c in v["checks"]) if v["checks"] else None
        v["decisions"] = briefing.decisions(v)                                                       # 0.36: mit tinyops-ask -d entschieden
        th = self.thread(r)                                                                            # 0.40: Gespräch und Sitzung
        v["thread"], v["round"] = th["messages"], th["round"]
        ok, why = self.can_continue(r) if r["status"] not in ("zugewiesen",) + STATUS_ACTIVE else (False, "")
        v["same_session"], v["session_why"] = ok, why
        v["open_decisions"] = briefing.open_decisions(briefing.report_sections(r.get("summary") or "").get("decide")) if r["status"] not in STATUS_ACTIVE else []
        v.update(agent_name=a["name"] if a else r["agent"] + " (entfernt)", kind=a["kind"] if a else "custom",
                 where=("lokal" if a and a["connection"] == "local" else conn["name"] if conn else "?"),
                 active=r["status"] in STATUS_ACTIVE, secs=int(end - r["started"]) if r["started"] else 0,
                 attach=("ssh -t -p %s %s tmux attach -t tinyops-%d" % (conn["port"], (("%s@%s" % (conn["user"], conn["host"])) if conn["user"] else conn["host"]), r["id"])) if conn else "")
        return v

    def view(self):
        agents = [{"id": a["id"], "name": a["name"], "kind": a["kind"], "label": KINDS[a["kind"]]["label"], "cloud": a.get("cloud", True),
                   "isolation": a.get("isolation", "worktree"), "model": a.get("model", ""),
                   "roles": agent_roles(a), "role_cmds": a.get("roles") or {}, "push": bool(a.get("push")), "quota": a.get("quota", QUOTA_DEFAULT.get(a["kind"], "")),
                   "where": "lokal" if a["connection"] == "local" else (self.conns().get(a["connection"]) or {}).get("name", "?"),
                   "workspace_root": a["workspace_root"]} for a in self.agent_list()]
        projects = [{"id": p["id"], "name": p.get("name") or str(p["id"]), "data_class": data_class(p)} for p in self.projects()]
        return {"enabled": bool(agents), "agents": agents, "projects": projects, "runs": [self.run_view(r) for r in self.store.agent_runs(limit=200)]}

    # -- Zuweisen, Starten, Stoppen
    def assign(self, aid, ticket, pid, branch, title):
        self.agent(aid)
        ticket = str(ticket or "").strip()
        if not ticket or len(ticket) > 120:
            raise AgentError("Die Karte hat keine Kennung.")
        for r in self.store.agent_runs(ticket=ticket):
            if r["agent"] == aid and r["status"] in ("zugewiesen", "läuft"):
                raise AgentError("Dieser Agent ist dem Ticket schon zugewiesen.")
        if pid is not None:
            ok, why = self.allowed(self.agent(aid), pid)
            if not ok:
                self._ev("agent.assign", {"id": None, "agent": aid, "ticket": ticket, "project_id": pid}, ok=False, error=why)
                raise AgentError(why)
        rid = self.store.agent_run_add(aid, ticket, pid, str(branch or "")[:200], str(title or "")[:300])
        self._ev("agent.assign", self.store.agent_run(rid), branch=str(branch or "")[:200])
        return rid

    def start(self, run_id, prompt, pid=None, branch=None, phase="develop", parent=None, resume=None, ask="", sync=""):
        """resume: alter Lauf, dessen Sitzung weitergeht (0.40): derselbe Arbeitsordner, derselbe Branch, der Agent behält den Kontext."""
        with self.lock:
            r = self.store.agent_run(run_id)
            if not r:
                raise AgentError("Diese Zuweisung gibt es nicht (mehr).")
            if r["status"] != "zugewiesen":
                raise AgentError("Nur zugewiesene Läufe lassen sich starten (Status: %s)." % r["status"])
            a = self.agent(r["agent"])
            conn = self.conn_of(a)
            pid = pid if pid is not None else r["project_id"]
            ok, why = self.allowed(a, pid)
            if not ok:
                self._ev("agent.start", dict(r, project_id=pid), ok=False, error=why)
                raise AgentError(why)
            prompt = str(prompt or "").replace("\r\n", "\n").strip()
            if not prompt or len(prompt) > MAX_PROMPT or "\0" in prompt:
                raise AgentError("Der Prompt fehlt oder ist länger als %d Zeichen." % MAX_PROMPT)
            wd = self.workdir(a, pid)
            mode = self.mode(a, pid) if not resume else (resume.get("mode") or "shared")
            if mode == "shared" and not resume:
                for o in self.store.agent_runs(status="läuft"):
                    if o["agent"] == a["id"] and o["workdir"] == wd and (o.get("mode") or "shared") == "shared":
                        raise AgentError("Auf diesem Agenten läuft in %s schon eine Aufgabe (%s). Erst beenden." % (wd, o["ticket"]))
            branch = str(branch if branch is not None else r["branch"])[:200]
            outb = self.out_branch(r["ticket"], run_id) if mode != "shared" else ""
            repo, root = self._paths(a, pid)
            if resume:
                outb = resume.get("out_branch") or ""
                prep = resume_prep_script(self._q(a, resume.get("wt") or resume.get("workdir") or wd), resume["id"], sync)
                sid = resume.get("session") or ""
                sess = {"id": sid, "resume": True}
            else:
                prep = prepare_script(mode, self._q(a, repo), self._q(a, root), run_id, outb, branch, (self.project(pid) or {}).get("cloud_paths") or [])
                sid = new_session(a, run_id) if can_resume(a) else ""
                sess = {"id": sid, "resume": False} if sid else None
            crit = briefing.parse_prompt(prompt)
            if not crit and resume:                 # eine Nachfrage hat keine Kriterien: die des alten Laufs gelten weiter
                try:
                    crit = json.loads(resume.get("criteria") or "[]")
                except ValueError:
                    crit = []
            self.store.agent_run_update(run_id, project_id=pid, branch=branch, workdir=wd, prompt=prompt, mode=mode, out_branch=outb,
                                        criteria=json.dumps(crit, ensure_ascii=False), ak="", result="", msteps="", mchecks="", gate="", gate_note="",
                                        phase=phase if phase in PHASES else "develop", parent=str(parent or ""),
                                        session=sid, resume_of=str(resume["id"]) if resume else "", ask=str(ask or "")[:4000], reply="", next_run="")
            try:
                if conn is None:
                    run_wd = self._local_prepare(a, run_id, prep) if (mode != "shared" or resume) else wd
                    self._local_start(a, run_id, run_wd, prompt, sess)
                else:
                    rc, out, err = run_remote(conn, remote_start_script(a, run_id, wd, prompt, prep, sess), timeout=60)
                    if rc in ISO_ERR:
                        raise AgentError(ISO_ERR[rc] % wd)
                    if rc == 42:
                        raise AgentError("Auf dem Zielhost ist tmux nicht installiert.")
                    if rc != 0 or "started" not in out:
                        raise AgentError("Start fehlgeschlagen (Exit %d): %s" % (rc, clean_text(err or out, 300).strip()))
                    run_wd = out.split("started", 1)[1].strip().splitlines()[0] if "started" in out else wd
                self.store.agent_run_update(run_id, wt=run_wd if mode != "shared" else "")
                if resume:                         # der Arbeitsordner gehört jetzt dem neuen Lauf: Entfernen des alten lässt ihn stehen
                    self.store.agent_run_update(resume["id"], wt="", next_run=str(run_id))
            except AgentError as e:
                self.store.agent_run_update(run_id, status="fehlgeschlagen", note=str(e)[:300], finished=time.time())
                log.warning("Start von Lauf %d (%s) fehlgeschlagen: %s", run_id, a["id"], e)
                self._ev("agent.start", self.store.agent_run(run_id), ok=False, error=str(e)[:300], prompt_hash=_audit.prompt_hash(prompt))
                raise
            self.store.agent_run_update(run_id, status="läuft", started=time.time(), note="")
            self._ev("agent.start", self.store.agent_run(run_id), prompt_hash=_audit.prompt_hash(prompt), prompt_chars=len(prompt), session=bool(resume),
                     workdir=wd, branch=branch, out_branch=outb, criteria=len(crit), max_minutes=int(a.get("max_minutes", DEFAULT_MAX_MINUTES) or 0))
            log.info("Lauf %d gestartet: Agent %s, Ticket %s, %s", run_id, a["id"], r["ticket"], wd)
            return run_id

    def _local_prepare(self, a, rid, prep):
        rc, out, err = self._sh(a, None, prep + 'echo "WD=$WD"\n', rid)
        if rc in ISO_ERR:
            raise AgentError(ISO_ERR[rc] % self.workdir(a, self.store.agent_run(rid)["project_id"]))
        if rc != 0:
            raise AgentError("Vorbereitung fehlgeschlagen (Exit %d): %s" % (rc, clean_text(err or out, 300).strip()))
        line = [x for x in out.splitlines() if x.startswith("WD=")]
        return line[-1][3:] if line else ""

    def _local_start(self, a, rid, wd, prompt, sess=None):
        if not os.path.isdir(wd):
            raise AgentError("Das Arbeitsverzeichnis %s gibt es auf diesem Rechner nicht." % wd)
        d = self.run_dir
        d.mkdir(parents=True, exist_ok=True)
        for ext in ("exit", "exit.tmp", "log", "hb", "pid"):
            try:
                (d / ("%d.%s" % (rid, ext))).unlink()
            except OSError:
                pass
        for f in list(d.glob("%d.answer.*" % rid)) + [d / ("%d.%s" % (rid, x)) for x in ("question.json", "qn", "checks", "ak", "manual", "summary.md")]:
            try:
                f.unlink()
            except OSError:
                pass
        pf = d / ("%d.prompt" % rid)
        pf.write_text(prompt, encoding="utf-8")
        spec = local_spec(a, prompt, pf, wd, sess)
        hb = write_helpers(d)
        spec["env"] = dict(spec.get("env") or {}, TINYOPS_RUN_DIR=str(d), TINYOPS_RUN_ID=str(rid), PYTHONUNBUFFERED="1",
                           PATH=str(hb) + os.pathsep + os.environ.get("PATH", ""))
        (d / ("%d.spec.json" % rid)).write_text(json.dumps(spec), encoding="utf-8")
        kw = {"stdin": subprocess.DEVNULL, "stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL, "cwd": str(d), "close_fds": True}
        if os.name == "nt":
            kw["creationflags"] = 0x00000008 | 0x00000200      # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
        else:
            kw["start_new_session"] = True
        try:
            subprocess.Popen([sys.executable, str(self.base / "agentwrap.py"), str(d), str(rid)], **kw)
        except OSError as e:
            raise AgentError("Start fehlgeschlagen: %s" % e)

    def _local_status(self, r):
        d = self.run_dir
        ex = d / ("%d.exit" % r["id"])
        if ex.exists():
            try:
                return "exit", int(ex.read_text().strip() or "1")
            except (OSError, ValueError):
                return "exit", 1
        hb = d / ("%d.hb" % r["id"])
        try:
            age = time.time() - hb.stat().st_mtime
        except OSError:
            age = time.time() - (r["started"] or time.time())
        return ("running", 0) if age < 30 else ("gone", 0)

    def _local_question(self, r):
        try:
            return (self.run_dir / ("%d.question.json" % r["id"])).read_text(encoding="utf-8", errors="replace")[:4000]
        except OSError:
            return ""

    # -- Rückfragen (0.18)
    def _note_question(self, r, raw):
        """Neue Frage merken (genau einmal je Nummer), beantwortete oder verschwundene vergessen."""
        q = parse_question(raw) if raw else None
        answered = int(r.get("answered") or 0)
        cur = json.loads(r["question"]) if r.get("question") else None
        if q and q["id"] > answered:
            if not cur or cur.get("id") != q["id"]:
                q["ts"] = time.time()
                self.store.agent_run_update(r["id"], question=json.dumps(q, ensure_ascii=False))
                self._ev("agent.question", r, actor="agent", question=q["question"][:300], options=q["options"], blocking=q["blocking"], qid=q["id"])
                log.info("Lauf %d fragt (%d): %s", r["id"], q["id"], q["question"][:120])
        elif cur:
            self.store.agent_run_update(r["id"], question="")

    def answer(self, run_id, qid, text):
        text = str(text or "").replace("\r\n", "\n").strip()
        if not text or len(text) > 4000 or "\0" in text:
            raise AgentError("Die Antwort fehlt oder ist länger als 4000 Zeichen.")
        with self.lock:
            r = self.store.agent_run(run_id)
            if not r or r["status"] != "läuft":
                raise AgentError("Der Lauf läuft nicht mehr; die Antwort kommt nicht mehr an.")
            cur = json.loads(r["question"]) if r.get("question") else None
            try:
                qid = int(qid)
            except (TypeError, ValueError):
                raise AgentError("Fragenummer fehlt.")
            if not cur or cur.get("id") != qid:
                raise AgentError("Diese Frage ist nicht (mehr) offen.")
            a = self.agent(r["agent"])
            conn = self.conn_of(a)
            if conn is None:
                d = self.run_dir
                tmp = d / ("%d.answer.%d.tmp" % (run_id, qid))
                tmp.write_text(text + "\n", encoding="utf-8")
                os.replace(tmp, d / ("%d.answer.%d" % (run_id, qid)))
                try:
                    (d / ("%d.question.json" % run_id)).unlink()
                except OSError:
                    pass
            else:
                rc, out, err = run_remote(conn, answer_script(run_id, qid, text), timeout=20)
                if rc != 0 or "ok" not in out:
                    raise AgentError("Antwort nicht zugestellt (Exit %d): %s" % (rc, clean_text(err or out, 200).strip()))
            qa = json.loads(r["qa"]) if r.get("qa") else []
            qa.append({"id": qid, "q": cur.get("question", ""), "options": cur.get("options") or [], "a": text[:2000], "ts_q": cur.get("ts"), "ts_a": time.time(),
                       "decision": bool(cur.get("decision"))})
            self.store.agent_run_update(run_id, question="", answered=str(qid), qa=json.dumps(qa[-20:], ensure_ascii=False))
            self._ev("agent.answer", r, qid=qid, question=cur.get("question", "")[:300], answer=text[:300])
            return {"ok": True}

    # -- Ergebnisbericht und Belege (0.18)
    def collect(self, r):
        """Bericht (<nr>.summary.md) und Belege (<nr>.checks) einsammeln. Fehler sind still: Der Bericht ist eine Zugabe."""
        try:
            a = self.agent(r["agent"])
            conn = self.conn_of(a)
            if conn is None:
                d = self.run_dir
                rd = lambda ext: (d / ("%d.%s" % (r["id"], ext))).read_text(encoding="utf-8", errors="replace") if (d / ("%d.%s" % (r["id"], ext))).exists() else ""
                summary, checks, ak, manual = rd("summary.md")[:20000], rd("checks"), rd("ak"), rd("manual")
                logt = rd("log")
                sess_line, tail = logt[:400000], logt[-48000:]
            else:
                rc, out, _ = run_remote(conn, remote_report_script(r["id"]), timeout=20)
                if rc != 0 or "@@CHECKS" not in out:
                    return False
                head, _, checks = out.partition("@@CHECKS")
                checks, _, ak = checks.partition("@@AK")
                ak, _, manual = ak.partition("@@MANUAL")
                manual, _, sess_line = manual.partition("@@SESSION")
                sess_line, _, tail = sess_line.partition("@@TAIL")
                summary = head.split("@@SUMMARY", 1)[-1].strip("\n")
            self.store.agent_run_update(r["id"], summary=clean_text(summary, 20000).strip(), checks=json.dumps(parse_checks(checks), ensure_ascii=False),
                                        ak=json.dumps(briefing.parse_ak(clean_text(ak, 60000)), ensure_ascii=False),
                                        msteps=json.dumps(parse_manual(clean_text(manual, 20000)), ensure_ascii=False), reply=last_reply(tail))
            if not r.get("session") and find_session(a, sess_line):      # 0.40: Codex und Vibe vergeben die Kennung selbst
                self.store.agent_run_update(r["id"], session=find_session(a, sess_line))
            cur = self.store.agent_run(r["id"]) or r
            if cur.get("wt") and cur.get("mode") in ("worktree", "export"):      # was am Code geändert wurde; fehlt der Ordner schon, bleibt der alte Stand
                rc, out, _ = self._sh(a, conn, result_script(cur["wt"], cur["mode"]), r["id"], timeout=25)
                res = parse_result(out) if rc == 0 else None
                if res is not None:
                    self.store.agent_run_update(r["id"], result=json.dumps(res, ensure_ascii=False))
            return True
        except (AgentError, OSError) as e:
            log.debug("Bericht von Lauf %s nicht lesbar: %s", r.get("id"), e)
            return False

    def gate(self, run_id, gate, note=""):
        """Deine Freigabe am Ende einer Phase: ok (weiter) oder back (zurück, mit Grund)."""
        r = self.store.agent_run(run_id)
        if not r or r["status"] in ("zugewiesen", "läuft"):
            raise AgentError("Freigeben geht erst, wenn der Lauf beendet ist.")
        if gate not in GATES + ("",):
            raise AgentError("Unbekannte Freigabe.")
        v = self.run_view(r)
        if gate == "ok" and r["status"] != "fertig":
            raise AgentError("Ein Lauf mit Status «%s» lässt sich nicht freigeben. Zurückgeben oder neu starten." % r["status"])
        if gate == "ok" and v["manual"] and v["manual_done"] < len(v["manual"]):
            raise AgentError("Erst alle Prüfpunkte abhaken (%d von %d). Was nicht zutrifft: mit Notiz abhaken." % (v["manual_done"], len(v["manual"])))
        note = " ".join(str(note or "").split())[:1000]
        if gate == "back" and not note:
            raise AgentError("Was soll anders werden? Ein Satz reicht; er geht in den nächsten Auftrag.")
        self.store.agent_run_update(run_id, gate=gate, gate_note=note, ack="1")
        self._ev("agent.gate", r, phase=v["phase"], gate=gate or "(zurückgesetzt)", note=note[:120])
        return self.run_view(self.store.agent_run(run_id))

    def manual_check(self, run_id, i, done, note=""):
        r = self.store.agent_run(run_id)
        if not r:
            raise AgentError("Diesen Lauf gibt es nicht.")
        try:
            cur = json.loads(r.get("mchecks") or "{}")
        except ValueError:
            cur = {}
        cur[str(int(i))] = {"done": bool(done), "note": " ".join(str(note or "").split())[:500]}
        self.store.agent_run_update(run_id, mchecks=json.dumps(cur, ensure_ascii=False))
        return self.run_view(self.store.agent_run(run_id))

    def ack(self, run_id):
        r = self.store.agent_run(run_id)
        if r and r["status"] not in ("zugewiesen", "läuft"):
            self.store.agent_run_update(run_id, ack="1")

    def poll(self, force=False):
        """Stand aller laufenden Läufe ablesen (ein SSH-Aufruf je Zielhost). Fehler bei der Abfrage lassen den Lauf auf «läuft» und stehen im Hinweis."""
        with self.lock:
            if not force and time.time() - self.poll_t < 2.0:
                return
            self.poll_t = time.time()
            active = self.store.agent_runs(status="läuft")
            if not active:
                return
            active = [r for r in active if not self._expire(r)]
            if not active:
                return
            by_conn = {}
            for r in active:
                try:
                    a = self.agent(r["agent"])
                    by_conn.setdefault(a["connection"], []).append(r)
                except AgentError:
                    self.store.agent_run_update(r["id"], status="verloren", note="Der Agent wurde aus der Konfiguration entfernt.", finished=time.time())
            for cid, runs in by_conn.items():
                qs = {}
                if cid == "local":
                    res = {r["id"]: self._local_status(r) for r in runs}
                    qs = {r["id"]: self._local_question(r) for r in runs}
                else:
                    conn = self.conns().get(cid)
                    if not conn:
                        for r in runs:
                            self.store.agent_run_update(r["id"], status="verloren", note="Die Verbindung wurde entfernt.", finished=time.time())
                        continue
                    try:
                        rc, out, err = run_remote(conn, remote_status_script([r["id"] for r in runs]), timeout=20)
                    except AgentError as e:
                        for r in runs:
                            self.store.agent_run_update(r["id"], note="Status unbekannt: %s" % str(e)[:200])
                        continue
                    res = {}
                    for line in out.splitlines():
                        p = line.split()
                        if len(p) >= 2 and p[0].isdigit() and p[1] == "q":
                            qs[int(p[0])] = line.split(" q ", 1)[1] if " q " in line else ""
                            continue
                        if len(p) >= 2 and p[0].isdigit():
                            res[int(p[0])] = ("exit", int(p[2]) if len(p) > 2 and p[2].lstrip("-").isdigit() else 1) if p[1] == "exit" else (p[1], 0)
                for r in runs:
                    st = res.get(r["id"])
                    if st is None:
                        continue
                    if st[0] == "exit":
                        self.store.agent_run_update(r["id"], status="fertig" if st[1] == 0 else "fehlgeschlagen", exit_code=st[1], finished=time.time(), note="",
                                                    question="")
                        self.collect(r)
                        self._ev("agent.finish", r, ok=st[1] == 0, actor="agent", status="fertig" if st[1] == 0 else "fehlgeschlagen", exit_code=st[1],
                                 minutes=int((time.time() - (r["started"] or time.time())) // 60))
                    elif st[0] == "gone":
                        self.store.agent_run_update(r["id"], status="verloren", finished=time.time(), question="",
                                                    note="Weder Exit-Datei noch Sitzung gefunden (Zielhost neu gestartet, tmux beendet?).")
                        self.collect(r)
                        self._ev("agent.finish", r, ok=False, actor="agent", status="verloren")
                    else:
                        if r["note"]:
                            self.store.agent_run_update(r["id"], note="")
                        self._note_question(self.store.agent_run(r["id"]), qs.get(r["id"], ""))

    def _expire(self, r):
        """Zeitlimit des Agenten überschritten? Dann beenden und als «abgelaufen» markieren. Gibt True zurück, wenn beendet."""
        try:
            a = self.agent(r["agent"])
        except AgentError:
            return False
        mx = int(a.get("max_minutes", DEFAULT_MAX_MINUTES) or 0)
        if not mx or not r["started"] or time.time() - r["started"] < mx * 60:
            return False
        try:
            conn = self.conn_of(a)
            if conn is None:
                self._local_kill(r)
            else:
                run_remote(conn, remote_kill_script(r["id"]), timeout=20)
        except AgentError as e:
            log.warning("Lauf %d: Zeitlimit erreicht, Beenden fehlgeschlagen: %s", r["id"], e)
            self.store.agent_run_update(r["id"], note="Zeitlimit erreicht, Beenden fehlgeschlagen: %s" % str(e)[:200])
            if "Beenden fehlgeschlagen" not in (r.get("note") or ""):
                self._ev("agent.expire", r, ok=False, actor="watchdog", max_minutes=mx, error=str(e)[:200])
            return False
        self.store.agent_run_update(r["id"], status="abgelaufen", finished=time.time(), question="",
                                    note="Zeitlimit von %d min erreicht und beendet." % mx + (" Eine Frage war noch offen." if r.get("question") else ""))
        self.collect(r)
        self._ev("agent.expire", r, actor="watchdog", max_minutes=mx)
        log.warning("Lauf %d (%s, Ticket %s) nach %d min beendet (Zeitlimit)", r["id"], a["id"], r["ticket"], mx)
        return True

    def stop(self, run_id):
        with self.lock:
            r = self.store.agent_run(run_id)
            if not r or r["status"] != "läuft":
                raise AgentError("Dieser Lauf läuft nicht.")
            a = self.agent(r["agent"])
            conn = self.conn_of(a)
            if conn is None:
                self._local_kill(r)
            else:
                run_remote(conn, remote_kill_script(run_id), timeout=20)
            self.store.agent_run_update(run_id, status="abgebrochen", finished=time.time(), note="Von dir gestoppt.", question="")
            self.collect(r)
            self._ev("agent.stop", r, minutes=int((time.time() - (r["started"] or time.time())) // 60))

    def _local_kill(self, r):
        pidf = self.run_dir / ("%d.pid" % r["id"])
        try:
            pid = int(pidf.read_text().strip())
        except (OSError, ValueError):
            return
        try:
            if os.name == "nt":
                subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True, timeout=10)
            else:
                import signal
                os.killpg(pid, signal.SIGTERM)
        except (OSError, subprocess.SubprocessError):
            pass

    def changes(self, run_id):
        """Export: geänderte Dateien seit dem Export (committet die offenen Änderungen im Export-Repo)."""
        r = self.store.agent_run(run_id)
        if not r or r.get("mode") != "export" or not r.get("wt"):
            raise AgentError("Nur Läufe im Export-Modus haben Änderungen zum Übernehmen.")
        a = self.agent(r["agent"])
        rc, out, err = self._sh(a, self.conn_of(a), changes_script(r["wt"]), run_id)
        if rc != 0:
            raise AgentError("Änderungen nicht lesbar (Exit %d): %s" % (rc, clean_text(err or out, 300).strip()))
        return [x for x in out.splitlines() if x.strip()]

    def takeover(self, run_id):
        """Export: Änderungen als Branch agent/<key>-<nr> ins echte Repo übernehmen. Nur Dateien innerhalb der freigegebenen Pfade."""
        with self.lock:
            r = self.store.agent_run(run_id)
            if not r:
                raise AgentError("Diesen Lauf gibt es nicht (mehr).")
            if r["status"] in ("zugewiesen", "läuft"):
                raise AgentError("Erst wenn der Lauf beendet ist.")
            if r.get("taken"):
                raise AgentError("Schon übernommen: Branch %s." % r["taken"])
            files = self.changes(run_id)
            if not files:
                raise AgentError("Der Agent hat nichts geändert.")
            a = self.agent(r["agent"])
            paths = (self.project(r["project_id"]) or {}).get("cloud_paths") or []
            bad = [f for f in files if not path_allowed(f, paths)]
            if bad:
                self._ev("agent.takeover", r, ok=False, error="Pfade ausserhalb der Freigabe", blocked=bad[:20])
                raise AgentError("Änderungen ausserhalb der freigegebenen Pfade, nichts übernommen: %s" % ", ".join(bad[:8]))
            repo, root = self._paths(a, r["project_id"])
            outb = r.get("out_branch") or self.out_branch(r["ticket"], run_id)
            msg = "%s: Ergebnis von Agent %s (Lauf %d)" % (r["ticket"], a["name"], run_id)
            rc, out, err = self._sh(a, self.conn_of(a), apply_script(self._q(a, repo), self._q(a, root), run_id, outb, msg), run_id)
            if rc != 0 or "applied" not in out:
                raise AgentError((ISO_ERR.get(rc, "Übernehmen fehlgeschlagen (Exit %d)." % rc) % repo if rc in ISO_ERR else "Übernehmen fehlgeschlagen (Exit %d)." % rc)
                                 + " " + clean_text(err, 300).strip())
            self.store.agent_run_update(run_id, taken=outb, out_branch=outb, note="Übernommen als Branch %s (%d Dateien). Pushen und MR erstellen machst du." % (outb, len(files)))
            log.info("Lauf %d übernommen: %s, %d Dateien", run_id, outb, len(files))
            self._ev("agent.takeover", r, branch=outb, files=len(files), file_list=files[:40])
            return {"branch": outb, "files": files}

    def remove(self, run_id, force=False):
        with self.lock:
            r = self.store.agent_run(run_id)
            if not r:
                return
            if r["status"] == "läuft":
                raise AgentError("Der Lauf läuft noch. Erst stoppen.")
            if r.get("mode") == "export" and r.get("wt") and not r.get("taken") and not force:
                try:
                    files = self.changes(run_id)
                except AgentError:
                    files = []
                if files:
                    raise AgentError("Die Änderungen des Agenten (%d Dateien) sind noch nicht übernommen. Erst «Übernehmen», oder «Trotzdem entfernen»." % len(files))
            try:
                a = self.agent(r["agent"])
                conn = self.conn_of(a)
                if r.get("mode") in ("worktree", "export") and r.get("wt"):
                    repo, _root = self._paths(a, r["project_id"])
                    self._sh(a, conn, cleanup_script(r["mode"], self._q(a, repo), r["wt"], run_id), run_id)
                if conn is None:
                    for f in self.run_dir.glob("%d.*" % run_id) if self.run_dir.is_dir() else []:
                        try:
                            f.unlink()
                        except OSError:
                            pass
                elif r["status"] != "zugewiesen":
                    run_remote(conn, 'R="$HOME/.tinyops/runs"; rm -f "$R/%d."*; true' % int(run_id), timeout=15)
            except AgentError:
                pass     # Aufräumen ist Beiwerk; der Eintrag verschwindet trotzdem
            self._ev("agent.remove", r, status=r["status"], force=bool(force), taken=r.get("taken") or "")
            self.store.agent_run_delete(run_id)

    # -- Aufbewahrung: alte Logs, Prompts und Patches auf allen Rechnern löschen. Die Läufe in der Liste bleiben, nur ihre Dateien gehen.
    def retention(self, days, now=None):
        days = int(days or 0)
        if days <= 0:
            return None
        now = now or time.time()
        cut = now - days * 86400
        active = {r["id"] for r in self.store.agent_runs(status="läuft")}
        local = 0
        if self.run_dir.is_dir():
            for f in self.run_dir.iterdir():
                m = re.match(r"(\d+)\.", f.name)
                if not m or int(m.group(1)) in active:
                    continue
                try:
                    if f.is_file() and f.stat().st_mtime < cut:
                        f.unlink()
                        local += 1
                except OSError:
                    pass
        remote, failed = {}, []
        used = {a["connection"] for a in self.agent_list() if a["connection"] != "local"}
        for cid in sorted(used):
            conn = self.conns().get(cid)
            if not conn:
                continue
            keep = " ".join("! -name '%d.*'" % i for i in sorted(active))
            script = ('R="$HOME/.tinyops/runs"; [ -d "$R" ] || { echo 0; exit 0; }\n'
                      'find "$R" -maxdepth 1 -type f -mtime +%d %s -print -delete 2>/dev/null | wc -l\n' % (max(0, days - 1), keep))
            try:
                rc, out, err = run_remote(conn, script, timeout=30)
                remote[conn.get("name") or cid] = int((out.strip().splitlines() or ["0"])[-1]) if rc == 0 else 0
                if rc != 0:
                    failed.append(conn.get("name") or cid)
            except (AgentError, ValueError) as e:
                failed.append(conn.get("name") or cid)
                log.warning("Aufbewahrung auf %s: %s", cid, e)
        res = {"days": days, "local": local, "remote": remote, "failed": failed}
        if local or any(remote.values()) or failed:
            try:
                self.audit("agent.retention", "", not failed, "watchdog", **res)
            except Exception as e:
                log.error("Audit agent.retention: %s", e)
            log.info("Aufbewahrung %d Tage: %d lokale, %s entfernte Dateien gelöscht", days, local, remote)
        return res

    def tail(self, run_id, lines=80):
        r = self.store.agent_run(run_id)
        if not r:
            raise AgentError("Diesen Lauf gibt es nicht (mehr).")
        if r["status"] == "zugewiesen":
            return "(noch nicht gestartet)"
        a = self.agent(r["agent"])
        conn = self.conn_of(a)
        n = max(1, min(int(lines), 400))
        if conn is None:
            try:
                data = (self.run_dir / ("%d.log" % run_id)).read_bytes()[-400000:].decode("utf-8", "replace")
            except OSError:
                return "(noch keine Ausgabe)"
            return clean_text("\n".join(render_stream("\n".join(data.splitlines()[-n * 3:])).splitlines()[-n:]))
        # Stream-Zeilen sind lang und werden zu wenigen Anzeigezeilen: mehr Rohzeilen holen, lesbar machen, dann kürzen
        rc, out, err = run_remote(conn, 'tail -n %d "$HOME/.tinyops/runs/%d.log" 2>/dev/null | tail -c 400000 || echo "(noch keine Ausgabe)"' % (n * 3, int(run_id)), timeout=20)
        return clean_text("\n".join(render_stream(out).splitlines()[-n:]))
