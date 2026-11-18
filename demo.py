"""Demo-Daten für «--demo» und die Tests (0.37 aus server.py gelöst)."""
import os
import time
import urllib.parse
from datetime import datetime, timedelta, timezone

import github
import helpdesk
import sonar
import workspaces
from gitlab_client import derive_state


class DemoClient:
    """Erfundene Daten, um die Oberfläche ohne GitLab und Jira anzusehen."""

    def __init__(self, cfg):
        self.cfg = cfg

    def ticket_context(self, project_id, iid, branch):
        return {"project_id": project_id, "iid": iid, "branch": branch, "project": "dlp-core", "url": "https://gitlab.example/demo/" + branch,
                "title": "Findings Welle 1" if iid else "WIP " + branch, "mr_description": "Sonar-Findings der ersten Welle beheben." if iid else "",
                "commits": ["Sonar: Null-Checks ergänzen", "Sonar: ungenutzte Imports entfernen"]}

    @staticmethod
    def _ago(days):
        return datetime.fromtimestamp(time.time() - days * 86400, timezone.utc).isoformat()

    def _item(self, kind, iid, title, branch, days, pipeline="success", draft=False, project="dlp-core"):
        item = {
            "kind": kind, "project_id": 1, "project": project, "title": title,
            "branch": branch, "iid": iid, "url": "https://gitlab.example/demo/%s" % branch,
            "draft": draft, "pipeline": pipeline, "pipeline_url": "",
            "updated_at": self._ago(days), "sha": "a1b2c3d4e5f60718", "author": "demo",
            "can_deploy": iid is not None, "age_days": days,
        }
        if iid is None:
            item["create_mr_url"] = "https://gitlab.example/demo/-/merge_requests/new?merge_request%5Bsource_branch%5D=" + urllib.parse.quote(branch, safe="")
        item["state"] = derive_state(item) if kind == "mr" else "review"
        return item

    def fetch(self, sink=None, step=None):
        step = step or (lambda *a, **k: None)
        sink = sink if sink is not None else {}
        delay = float(os.environ.get("TINYOPS_DEMO_DELAY", "0"))   # nur zum Ansehen des Fortschritts

        def pause(sid, title, detail):
            step(sid, title, "run")
            time.sleep(delay)
            step(sid, title, "ok", detail)
        for sid, title in (("gl-user", "Bei GitLab anmelden"), ("gl-1", "Projekt dlp-core"), ("gl-2", "Projekt dlp-ui"),
                           ("gl-review", "Review-Queue"), ("gl-assigned", "Mir zugeteilte MRs")):
            step(sid, title, "wait")
        pause("gl-user", "Bei GitLab anmelden", "demo")
        mine = [
            self._item("mr", 41, "Vendex-Adapter: Retry bei 429", "feature/DLP-101-vendex-retry", 0, "running"),
            self._item("mr", 38, "Helm: Resource Limits setzen", "feature/DLP-102-helm-limits", 1, "success"),
            self._item("mr", 35, "Sonar: Findings Welle 1", "agent/sonar-wave-1", 3, "failed"),
            self._item("mr", 29, "Labelo: Graph-Client Refactoring", "feature/DLP-103-labelo-client", 9, "success", draft=True),
        ]
        for m, rv, up, by in ((mine[0], ["kollege"], 0, []), (mine[1], ["kollege"], 1, ["kollege"]), (mine[2], [], 0, []), (mine[3], [], 0, [])):
            m.update(reviewers=rv, upvotes=up, approved=bool(by), approved_by=by, host="gitlab", merge_status="mergeable" if by else "", target_branch="main")
        mine[1]["review_app"], mine[1]["review_env"] = "https://review-dlp-102-helm-limits.apps.example", "review/feature-dlp-102-helm-limits"
        for name, days, ahead, by_me, by_agent in (
                ("feature/proxo-mapping", 14, 5, True, False),
                ("idea/ui-prototype", 22, 2, True, True),
                ("feature/DLP-120-retry-tests", 1, 3, False, True)):
            b = self._item("branch", None, "WIP " + name, name, days, "none")
            b["kind"], b["state"], b["can_deploy"] = "branch", "kein-mr", False
            b.update({"ahead": ahead, "by_me": by_me, "by_agent": by_agent, "last_author": "Demo"})
            mine.append(b)
        review = [
            self._item("review", 52, "Angular: Policy-Tabelle filtern", "feature/DLP-140-policy-filter", 0, "success", project="dlp-ui"),
            self._item("review", 50, "Dockerfile: non-root", "chore/docker-nonroot", 2, "success"),
        ]
        assigned = [self._item("assigned", 47, "Sonar: Quality Gate anpassen", "feature/DLP-150-sonar-gate", 4, "success")]
        for r in review + assigned:
            r["author"] = "kollege"
        gh = self._item("mr", 7, "Webhook-Empfänger für GitHub", "feature/DLP-105-webhooks", 2, "success", project="adrian/tinyops-hooks")
        gh.update(project_id=github.pid_of(42), host="github", url="https://github.com/adrian/tinyops-hooks/pull/7", reviewers=["octocat"], upvotes=0,
                  approved=False, approved_by=[], merge_status="mergeable", can_deploy=False)
        mine.insert(4, gh)
        sink.update(me="demo", errors=[])
        sink.setdefault("mine", []).extend(mine[:5])
        pause("gl-1", "Projekt dlp-core", "4 MR")
        sink["mine"].extend(mine[5:])
        sink.setdefault("review", []).extend(review)
        pause("gl-2", "Projekt dlp-ui", "3 Branches")
        pause("gl-review", "Review-Queue", "%d MR" % len(review))
        sink.setdefault("assigned", []).extend(assigned)
        pause("gl-assigned", "Mir zugeteilte MRs", "%d MR" % len(assigned))
        return sink

    def review_threads(self, project_id, iid):
        sha = "a1b2c3d4e5f60718"
        pos = lambda f, line, head=sha: {"new_path": f, "old_path": f, "new_line": line, "head_sha": head, "position_type": "text"}
        note = lambda nid, who, body, **kw: dict({"id": nid, "body": body, "author": {"username": who}, "created_at": "2026-11-04T09:12:00Z",
                                                  "system": False, "resolvable": True, "resolved": False}, **kw)
        disc = [
            {"id": "d1", "notes": [note(901, "kollege", "Hier fehlt das Backoff: bei 429 sofort erneut zu senden verschärft das Rate-Limit. Bitte exponentiell mit Obergrenze.",
                                        position=pos("src/main/java/ch/dlp/vendex/VendexClient.java", 88)),
                                   note(902, "demo", "Guter Punkt, mache ich mit max. 3 Versuchen.")]},
            {"id": "d2", "notes": [note(903, "kollege", "Der Test deckt nur den Erfolgsfall ab. Bitte auch 429 und 503 prüfen.",
                                        position=pos("src/test/java/ch/dlp/vendex/VendexClientTest.java", 41, "0f9e8d7c6b5a4321"))]},
            {"id": "d3", "notes": [note(904, "kollege", "Magic Number 30000 bitte als Konstante mit Einheit.", position=pos("src/main/java/ch/dlp/vendex/VendexClient.java", 23),
                                        resolved=True)]},
            {"id": "d4", "notes": [note(905, "kollege", "Ist das mit dem Helm-Chart abgestimmt? Die Timeouts müssen zusammenpassen.")]},
            {"id": "d5", "notes": [note(906, "gitlab", "added 1 commit", system=True, resolvable=False)]},
        ]
        return {"target_branch": "main", "sha": sha, "web_url": "https://gitlab.example/demo/-/merge_requests/%s" % iid}, disc

    def mr(self, project_id, iid):
        return {"title": "Demo-MR %s" % iid, "branch": "feature/DLP-101-demo-%s" % iid,
                "sha": "a1b2c3d4e5f60718", "url": "https://gitlab.example/demo/%s" % iid}


def demo_workspaces():
    """Erfundene Workspaces für die Demo: ein Repo mit ungepushter Arbeit, ein Agent-Worktree, ein fremdes Repo, ein Ordner ohne Git."""
    now = time.time()

    def br(name, up, ahead, age, subject, behind=0, cur=False):
        return {"name": name, "upstream": up, "gone": False, "ahead": ahead, "behind": behind, "sha": "%07x" % (abs(hash(name)) % 0xfffffff), "subject": subject,
                "age_days": age, "agent": name.startswith("agent/"), "current": cur}

    def repo(name, rel, host, remote, pid, head, branches, dirty=(0, 0, 0), stashes=0, stash_age=None, wts=(), fetched=0.2):
        r = {"path": "/home/demo/work/" + rel, "name": name, "rel": rel, "root": "/home/demo/work", "ok": True, "head": head, "host": host, "remote": remote,
             "remotes": [{"name": "origin", "url": "https://" + remote + ".git", "host": remote.split("/")[0], "path": remote.split("/", 1)[1], "kind": host}] if remote else [],
             "project": {"pid": pid, "name": name, "host": host} if pid else None, "branches": branches,
             "dirty": {"staged": dirty[0], "changed": dirty[1], "new": dirty[2], "total": sum(dirty)}, "stashes": stashes, "stash_age_days": stash_age,
             "worktrees": list(wts), "fetched_days": fetched,
             "secrets": [{"file": "src/main/resources/application-dev.yml", "line": 14, "rule": "Passwort oder Token im Klartext", "excerpt": "… (18 Zeichen)",
                          "where": "Commit 4f2a9c1"}] if name == "dlp-core" else []}
        r.update(workspaces.summary(r))
        return r
    repos = [
        repo("dlp-core", "dlp-core", "gitlab", "gitlab.example/dlp/dlp-core", 1, "feature/DLP-101-vendex-retry",
             [br("main", "origin/main", 0, 1.0, "Merge DLP-99"), br("feature/DLP-101-vendex-retry", "origin/feature/DLP-101-vendex-retry", 3, 2.6, "Retry mit Backoff", cur=True),
              br("spike/quarantine-api", "", 5, 9.0, "WIP Quarantäne-API"), br("agent/dlp-120-7", "", 2, 0.2, "Retry-Tests ergänzt")],
             dirty=(1, 4, 2), stashes=2, stash_age=12.0,
             wts=[{"path": "/home/demo/work/.tinyops-wt/7", "branch": "agent/dlp-120-7", "sha": "a1b2c3d4", "detached": False, "agent": True, "missing": False, "dirty": 0}]),
        repo("dlp-ui", "dlp-ui", "gitlab", "gitlab.example/dlp/dlp-ui", 2, "main", [br("main", "origin/main", 0, 3.0, "Policy-Tabelle", behind=4, cur=True)], fetched=6.0),
        repo("sync-tool", "kunden/sync-tool", "github", "github.com/demo/sync-tool", None, "main",
             [br("main", "origin/main", 1, 0.4, "Mapping für Labelo", cur=True)], dirty=(0, 1, 0)),
        repo("notizen", "notizen", "none", "", None, "master", [br("master", "", 14, 30.0, "Notizen November", cur=True)]),
    ]
    repos.sort(key=lambda x: (not x.get("todo"), -(x.get("oldest_days") or 0), x["name"].lower()))
    return {"ts": now, "secs": 0.1, "partial": False, "repos": repos,
            "roots": [{"path": "/home/demo/work", "why": "Arbeitsordner von goose-lokal", "ok": True, "repos": 4, "plain": 1}],
            "plain": [{"path": "/home/demo/work/skripte/report-export", "name": "report-export", "rel": "skripte/report-export", "kind": "Python", "root": "/home/demo/work"}]}


class DemoHelpdesk:
    """Demo-Servicedesk (Jira 8.5): drei zugewiesene Tickets, eines über dem SLA, und eine kleine Queue."""
    base = "https://servicedesk.example"

    def _search(self, jql, fields, limit=100):
        def j(h):
            return datetime.fromtimestamp(time.time() - h * 3600, timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000+0000")
        mk = lambda k, s, st, p, c, u, r: {"key": k, "fields": {"summary": s, "status": {"name": st}, "priority": {"name": p}, "created": j(c), "updated": j(u),
                                                                "reporter": {"displayName": r}}}
        if jql.startswith("watcher"):
            return [mk("SD-4588", "Neuer Standort: Netzwerkdosen patchen", "In Progress", "Medium", 200, 1.5, "Facility"),
                    mk("SD-4640", "Lizenz für Zeichenprogramm verlängern", "Waiting for support", "Low", 120, 70, "Konstruktion")], 2
        if jql == "demo":
            return [mk("SD-4711", "Drucker im 3. Stock druckt nur leere Seiten", "Open", "Medium", 0.5, 0.5, "Empfang"),
                    mk("SD-4712", "VPN-Zugang für neue Lernende", "Open", "High", 2, 2, "Berufsbildung")], 2
        return [mk("SD-4690", "Outlook-Regel leitet Mails doppelt weiter", "In Progress", "High", 30, 3, "Buchhaltung"),
                mk("SD-4702", "Freigabe auf Laufwerk P: für Projektteam", "Open", "Medium", 6, 6, "Projektbüro"),
                mk("SD-4655", "Laptop-Tausch vorbereiten", "Waiting for customer", "Low", 80, 50, "Personal")], 3


DemoHelpdesk.detail = lambda self, key: dict(
    next(helpdesk.item(self.base, i, 24, time.time()) for q in ("x", "demo", "watcher") for i in self._search(q, [])[0] if i["key"] == key),
    description="Seit dem Update vom Montag kommen weitergeleitete Mails doppelt an.\n\nBetroffen: Sammelpostfach buchhaltung@.\nSchon versucht: Regel gelöscht und neu angelegt.",
    comments_total=2, comments=[{"author": "Buchhaltung", "age_h": 3.0, "body": "Passiert auch bei Mails von extern."},
                                {"author": "Demo", "age_h": 20.0, "body": "Regel geprüft, sieht korrekt aus. Ich schaue die Transportregeln an."}])


class DemoSonar:
    """Erfundene Quality Gates für die Demo: stabil pro MR/Branch."""
    base = "https://sonar.example"

    def gate(self, key, pr=None, branch=None):
        import zlib
        n = zlib.crc32(("%s|%s|%s" % (key, pr, branch)).encode()) % 5
        url = "%s/dashboard?id=%s" % (self.base, key)
        if n in (0, 1):
            return {"status": "OK", "failed": [], "url": url, "detail": "bestanden"}
        if n == 2:
            f = [sonar.describe({"metricKey": "new_coverage", "actualValue": "61.2", "errorThreshold": "80", "comparator": "LT"}),
                 sonar.describe({"metricKey": "new_vulnerabilities", "actualValue": "2", "errorThreshold": "0", "comparator": "GT"})]
            return {"status": "ERROR", "failed": f, "url": url, "detail": "; ".join(f)}
        if n == 3:
            f = [sonar.describe({"metricKey": "new_duplicated_lines_density", "actualValue": "4.1", "errorThreshold": "3", "comparator": "GT"})]
            return {"status": "WARN", "failed": f, "url": url, "detail": "; ".join(f)}
        return {"status": "NONE", "failed": [], "url": url, "detail": "keine Analyse"}

    def history(self, key, pr=None, branch=None, metrics=("violations",), limit=60):
        """Erfundener Verlauf: OK-Einträge werden besser, rote schlechter, der Rest bleibt flach."""
        import zlib
        n = zlib.crc32(("%s|%s|%s" % (key, pr, branch)).encode()) % 5
        base = time.time() - 6 * 86400
        shape = {0: [14, 11, 9, 4, 1, 0], 1: [8, 6, 5, 5, 2, 1], 2: [2, 3, 5, 6, 9, 12], 3: [5, 5, 6, 5, 5, 5]}.get(n)
        if not shape:
            return []
        out = []
        for i, v in enumerate(shape):
            row = {"ts": base + i * 86400, "violations": float(v), "bugs": float(v // 4), "vulnerabilities": float(v // 6), "code_smells": float(v - v // 4 - v // 6),
                   "coverage": 55.0 + i * 3}
            out.append({k: x for k, x in row.items() if k == "ts" or k in metrics})
        return out[-limit:]

    def pull_requests(self, key):
        return [{"key": "41", "status": {"qualityGateStatus": "OK"}}]

    def issues_url(self, key, pr=None, branch=None):
        return "%s/project/issues?id=%s&resolved=false" % (self.base, key)

    def hotspots_url(self, key, pr=None, branch=None):
        return "%s/security_hotspots?id=%s" % (self.base, key)

    def issues(self, key, pr=None, branch=None, limit=200):
        it = [{"component": key + ":src/main/java/ch/example/RetryClient.java", "line": 88, "severity": "CRITICAL", "type": "VULNERABILITY",
               "rule": "java:S5131", "message": "Make sure that this user-controlled value is sanitized before it is used."},
              {"component": key + ":src/main/java/ch/example/RetryClient.java", "line": 142, "severity": "MAJOR", "type": "CODE_SMELL",
               "rule": "java:S3776", "message": "Refactor this method to reduce its Cognitive Complexity from 21 to the 15 allowed."},
              {"component": key + ":src/test/java/ch/example/RetryClientTest.java", "line": 31, "severity": "MINOR", "type": "CODE_SMELL",
               "rule": "java:S1135", "message": "Complete the task associated to this TODO comment."}]
        return it[:limit], len(it), {"severities": {"CRITICAL": 1, "MAJOR": 1, "MINOR": 1}, "types": {"VULNERABILITY": 1, "CODE_SMELL": 2}}

    def hotspots(self, key, pr=None, branch=None, limit=100):
        return [{"component": key + ":src/main/resources/application.yml", "line": 12, "vulnerabilityProbability": "MEDIUM",
                 "securityCategory": "weak-cryptography", "message": "Make sure this weak hash algorithm is not used in a sensitive context."}], 1


class DemoJira:
    base = "https://jira.example"
    _DATA = {
        "DLP-101": ("Vendex-Adapter: Retry bei 429", "In Progress"),
        "DLP-102": ("Helm Resource Limits", "In Progress"),
        "DLP-104": ("Installer: Upgrade-Test", "In Progress"),
        "DLP-103": ("Labelo Graph-Client", "To Do"),
        "DLP-120": ("Retry-Tests ergänzen", "To Do"),
        "DLP-140": ("Policy-Tabelle filtern", "In Review"),
        "DLP-150": ("Sonar Quality Gate", "In Review"),
        "DLP-131": ("Export bricht bei Umlauten im Dateinamen ab", "In Progress"),
        "DLP-132": ("Begleitticket: Testfall und Release-Notiz zum Export-Fix", "In Progress"),
    }
    _TYPES = {"DLP-131": "Bug", "DLP-132": "Aufgabe"}
    _LINKS = {"DLP-131": [{"key": "DLP-132", "type": "Relates"}], "DLP-132": [{"key": "DLP-131", "type": "Relates"}]}

    _BACKLOG = {"DLP-103", "DLP-120"}   # nicht im aktiven Sprint

    def __init__(self, jc):
        self.jc = jc

    def _issue(self, key):
        summary, status = self._DATA[key]
        ins = key not in self._BACKLOG
        end = (datetime.now(timezone.utc) + timedelta(days=9)).isoformat()
        return {"key": key, "summary": summary, "status": status, "type": self._TYPES.get(key, "Story"), "url": "%s/browse/%s" % (self.base, key),
                "sprint": "Sprint 12" if ins else "", "sprint_end": end if ins else "", "in_sprint": ins,
                "links": list(self._LINKS.get(key, [])), "parent": ""}

    def in_progress(self):
        return [self._issue(k) for k, v in self._DATA.items() if v[1] == "In Progress"]

    def lookup(self, keys):
        return {k: self._issue(k) for k in keys if k in self._DATA}

    def brief(self, key):
        summary, status = self._DATA[key]
        return {"title": summary, "kind": "Story", "status": status, "url": "%s/browse/%s" % (self.base, key),
                "description": "h3. Ausgangslage\nDer Adapter bricht bei HTTP 429 sofort ab. Test-Zugang: token=demo-geheim-123\n\n"
                               "h3. Akzeptanzkriterien\n* Bei 429 wird mit Backoff erneut versucht\n* Höchstens 5 Versuche, dann ein klarer Fehler\n"
                               "* Ein Test deckt den Retry ab\n\nh3. Offene Fragen\n* Backoff fix oder exponentiell?",
                "comments": [{"author": "Mara", "body": "Bitte exponentiell, Start bei 500 ms."}]}

    def helpdesk(self):
        return {"open": 7, "oldest_hours": 52, "over_hours": 3, "sla_hours": 24, "truncated": False,
                "url": self.base + "/issues/?jql=project%3DHELP"}

    def create_url(self, summary):
        return self.base + "/secure/CreateIssue!default.jspa"

    def issue_types(self, project_key):
        return ["Story", "Bug", "Task"]

    def create_issue(self, project_key, issue_type, summary, description):
        DemoJira._n = getattr(DemoJira, "_n", 200) + 1
        key = "%s-%d" % (project_key, DemoJira._n)
        return {"key": key, "url": "%s/browse/%s" % (self.base, key)}
