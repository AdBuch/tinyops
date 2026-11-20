"""Workspaces: lokale Repos und Worktrees einlesen, abholen, aufräumen.

Bereich von App (0.38 aus server.py gelöst). Gemeinsames (cfg, store, Audit, Cache) kommt von App;
Aufrufe in andere Bereiche stehen in USES und werden von tests/test_areas.py geprüft."""

import threading
import time
import urllib.parse
from pathlib import Path

import github
import tlog
import workspaces
from common import UserError
from demo import demo_workspaces
from secretstore import scrub

log = tlog.get("app")


class WorkspaceArea:
    # Aufrufe in andere Bereiche (tests/test_areas.py prüft, dass genau diese benutzt werden)
    USES = {"area_tickets": ("board_action",)}

    # -- Workspaces (0.25): lokale Repos, ungepushte Arbeit, Worktrees der Agenten
    def _ws_projects(self):
        out = [{"pid": p["id"], "name": p.get("name") or str(p["id"]), "host": "gitlab", "full": p.get("path") or "", "repo_path": p.get("repo_path") or "",
                "agent_dir": p.get("agent_dir") or ""} for p in self.cfg.get("projects") or []]
        for r in (self.ghc.get("repos") or []):
            if r.get("id") and r.get("full"):
                out.append({"pid": github.pid_of(r["id"]), "name": r["full"].split("/")[-1], "host": "github", "full": r["full"],
                            "repo_path": r.get("repo_path") or "", "agent_dir": r.get("agent_dir") or ""})
        return out

    def _ws_hosts(self):
        gl = urllib.parse.urlparse(self.cfg.get("gitlab_url") or "").hostname or ""
        gh = urllib.parse.urlparse(self.ghc.get("api_url") or "").hostname or ""
        return {"gitlab": [gl.lower()] if gl else [], "github": [h for h in (gh.lower(), gh.lower().replace("api.", "", 1)) if h]}

    def _ws_scan(self):
        if self.demo:
            return demo_workspaces()
        roots = workspaces.roots_of(self.cfg)
        return workspaces.scan(roots, self._ws_hosts(), self._ws_projects(), int(self.wsc["depth"]), int(self.wsc["max_repos"]))

    def workspaces_state(self, fresh=False):
        """Stand der Workspaces. Der Scan läuft höchstens alle scan_minutes; fresh erzwingt ihn."""
        if not self.wsc["enabled"]:
            return {"enabled": False}
        with self.ws_lock:
            c = self.ws_cache
            if fresh or c is None or time.time() - c["ts"] > float(self.wsc["scan_minutes"]) * 60:
                c = self.ws_cache = self._ws_scan()
        ag = self.agents.view() if self.agents else {"agents": [], "projects": [], "runs": []}
        runs = {}
        for r in ag.get("runs") or []:
            if r.get("out_branch"):
                runs[r["out_branch"]] = {"id": r["id"], "status": r["status"], "agent": r.get("agent_name") or r.get("agent"), "ticket": r.get("ticket")}
        return dict(c, enabled=True, totals=workspaces.totals(c, float(self.wsc["stale_days"])), stale_days=self.wsc["stale_days"], runs=runs,
                    agents=[{"id": a["id"], "name": a["name"], "cloud": a["cloud"], "where": a.get("where", "")} for a in ag.get("agents") or []],
                    classes={p["id"]: p.get("data_class") for p in ag.get("projects") or []})

    def _ws_summary(self):
        """Für die Übersicht: Zahlen aus dem letzten Scan. Ist er alt, läuft im Hintergrund ein neuer."""
        if not self.wsc["enabled"]:
            return None
        c = self.ws_cache
        if (c is None or time.time() - c["ts"] > float(self.wsc["scan_minutes"]) * 60) and not self.ws_busy:
            self.ws_busy = True

            def run():
                try:
                    self.workspaces_state()
                except Exception as e:      # noqa: BLE001 - der Scan ist Zugabe
                    log.warning("Workspaces: %s", scrub(e))
                finally:
                    self.ws_busy = False
            threading.Thread(target=run, name="workspaces", daemon=True).start()
        return dict(workspaces.totals(c, float(self.wsc["stale_days"])), scanning=c is None) if c else {"scanning": True, "repos": 0, "todo": 0, "stale": []}

    def _ws_repo(self, path):
        def find():
            return next((x for x in (self.ws_cache or {}).get("repos") or [] if x["path"] == str(path or "")), None)
        r = find()
        if r is None:                       # 0.36: Scan gerade verworfen oder veraltet (7× im Bericht): einmal selbst neu einlesen
            self.workspaces_state(True)
            r = find()
        if r is None:
            raise UserError("Dieses Repo liegt nicht (mehr) unter deinen Workspace-Ordnern. Pfad verschoben oder gelöscht?")
        return r

    def workspaces_action(self, action, b):
        if not self.wsc["enabled"]:
            raise UserError("Workspaces sind ausgeschaltet.")
        r = self._ws_repo(b.get("path"))
        if action == "fetch":
            if self.demo:
                ok, err = True, ""
            else:
                ok, err = workspaces.fetch(r["path"])
            self.audit("workspace.fetch", r["name"], ok=ok, path=r["path"], error=err or None)
            if not ok:
                raise UserError(workspaces.fetch_hint(err))
            return self.workspaces_state(True)
        if action == "task":
            # Arbeit direkt aus dem Workspace vergeben: eine lokale Aufgabe anlegen, die der Agenten-Dialog dann zuweist
            if not r.get("project"):
                raise UserError("«%s» ist in tinyops kein eingerichtetes Projekt. Erst unter Einstellungen → Projekte aufnehmen, damit Datenklasse und Agenten-Regeln gelten." % r["name"])
            title = " ".join(str(b.get("title") or "").split())[:200]
            if not title:
                raise UserError("Was soll der Agent tun? Ein Satz genügt.")
            branch = str(b.get("branch") or r.get("head") or "")[:200]
            if branch and not any(x["name"] == branch for x in r["branches"]):
                raise UserError("Den Branch «%s» gibt es in diesem Repo nicht." % branch)
            key = self.board_action("add", {"title": title, "stage": "idea", "pool_id": None})["key"]
            self.audit("workspace.task", key, repo=r["name"], branch=branch, project_id=r["project"]["pid"])
            self.cache_t = 0.0
            return {"key": key, "title": title, "project_id": r["project"]["pid"], "branch": branch}
        if action == "wt_remove":
            # 0.35: Worktrees aufräumen (Wunsch: «AI erstellt Worktrees, die müssen wir auch tracken»). Nur saubere, nichts geht verloren.
            wt = str(b.get("worktree") or "")
            if not any(w["path"] == wt for w in r.get("worktrees") or []):
                raise UserError("Diesen Worktree gibt es in %s nicht (mehr). Einmal neu einlesen." % r["name"])
            ok, msg = (True, "Demo: nichts entfernt.") if self.demo else workspaces.worktree_remove(r["path"], wt)
            self.audit("workspace.worktree_remove", r["name"], ok=ok, path=wt, message=msg)
            if not ok:
                raise UserError(msg)
            return dict(self.workspaces_state(True), message=msg)
        raise UserError("Unbekannte Aktion.")

    def _ws_repo_for(self, host, pid):
        """Ohne eingetragenen Pfad: den Checkout aus Workspaces nehmen, dessen Remote zum Projekt passt (0.34, «automatisch verbunden»).
        Nur ein echtes Repo, kein Worktree; bei mehreren das zuletzt geholte."""
        c = self.ws_cache or {}
        cand = [r for r in c.get("repos") or [] if r.get("ok") and (r.get("project") or {}).get("pid") == pid and (r.get("project") or {}).get("host") == host
                and Path(r["path"], ".git").is_dir()]
        if not cand:
            return ""
        cand.sort(key=lambda r: (r.get("fetched_days") is None, r.get("fetched_days") or 0))
        return cand[0]["path"]
