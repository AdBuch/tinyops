"""Ganzer Weg über den echten Server: Start ohne Config, Einstellungen testen und speichern, danach läuft das Panel."""
import json
import os
import socket
import stat
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def wait(port):
    for _ in range(80):
        try:
            socket.create_connection(("127.0.0.1", port), timeout=0.2).close()
            return
        except OSError:
            time.sleep(0.1)
    raise RuntimeError("Server startet nicht")


class Flow(unittest.TestCase):
    def call(self, method, path, body=None):
        req = urllib.request.Request("http://127.0.0.1:%d%s" % (self.port, path), method=method,
                                     data=json.dumps(body).encode() if body is not None else None,
                                     headers={"X-Requested-With": "tinyops", "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read())

    def overview(self):
        """/api/overview antwortet sofort; hier warten, bis die Synchronisation durch ist."""
        end = time.time() + 20
        while True:
            code, ov = self.call("GET", "/api/overview")
            started = ov.get("me") or not ov.get("configured")      # direkt nach dem Speichern hat der Abgleich noch nicht begonnen
            if code != 200 or (started and not ov.get("sync", {}).get("running") and not ov.get("loading")) or time.time() > end:
                return code, ov
            time.sleep(0.1)

    def test_flow(self):
        gp, jp, self.port = free_port(), free_port(), free_port()
        procs = [subprocess.Popen([sys.executable, str(ROOT / "tests" / "mock_gitlab.py"), str(gp)]),
                 subprocess.Popen([sys.executable, str(ROOT / "tests" / "mock_jira.py"), str(jp)])]
        try:
            with tempfile.TemporaryDirectory() as tmp:
                cfgfile = Path(tmp, "config.json")
                (Path(tmp, "bind.json")).write_text(json.dumps({"port": self.port}))
                env = dict(os.environ, TINYOPS_HOME=str(Path(tmp, "home")))
                env.pop("TINYOPS_GITLAB_TOKEN", None)
                env.pop("GITLAB_TOKEN", None)
                # Start mit einer minimalen Config, die nur den Port setzt (kein GitLab, kein Token)
                cfgfile.write_text(json.dumps({"port": self.port, "data_dir": str(Path(tmp, "data"))}))
                srv = subprocess.Popen([sys.executable, str(ROOT / "server.py"), "--config", str(cfgfile)], env=env,
                                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                procs.append(srv)
                wait(self.port)
                wait(gp)
                wait(jp)

                code, ov = self.overview()
                self.assertEqual(code, 200)
                self.assertFalse(ov["configured"])
                self.assertTrue(ov["problems"])
                self.assertEqual(ov["features"], {"ideas": True, "testenv": False, "ai": False})

                code, st = self.call("GET", "/api/settings")
                self.assertEqual(code, 200)
                self.assertFalse(st["secrets"]["gitlab_token"]["set"])

                glurl, jiurl = "http://127.0.0.1:%d" % gp, "http://127.0.0.1:%d" % jp
                # falscher Token: klarer Fehler
                code, t = self.call("POST", "/api/settings/test/gitlab", {"url": glurl, "token": "falsch"})
                self.assertEqual(code, 200)
                self.assertFalse(t["ok"])
                # richtiger Token
                code, t = self.call("POST", "/api/settings/test/gitlab", {"url": glurl, "token": "secret", "projects": [1]})
                self.assertTrue(t["ok"], t)
                # ungültige Eingabe wird abgelehnt, nichts wird geschrieben
                code, bad = self.call("POST", "/api/settings/save", {"gitlab": {"url": "kaputt"}})
                self.assertEqual(code, 400)
                self.assertIn("gitlab.url", bad["errors"])
                self.assertNotIn("gitlab_url", json.loads(cfgfile.read_text()))
                # speichern
                code, saved = self.call("POST", "/api/settings/save", {
                    "gitlab": {"url": glurl}, "projects": [{"id": 1, "name": "dlp-core"}],
                    "branch_filter": {"emails": ["me@x.ch"], "agent_emails": ["bot@x.ch"]},
                    "jira": {"url": jiurl, "auth": "bearer", "project_keys": ["DLP"], "story_limit": 2, "wip_issue_types": ["Story"]},
                    "secrets": {"gitlab_token": "secret", "jira_token": "jtoken"}})
                self.assertEqual(code, 200, saved)
                self.assertTrue(saved["configured"])
                raw = cfgfile.read_text()
                self.assertNotIn("secret", raw.replace("secrets", ""))
                self.assertNotIn("jtoken", raw)
                self.assertEqual(stat.S_IMODE(cfgfile.stat().st_mode), 0o600)
                self.assertEqual(json.loads(raw)["port"], self.port)   # Fremdes bleibt erhalten
                code, au = self.call("GET", "/api/audit?action=settings.save")      # 0.17: im Verlauf, ohne Werte
                self.assertEqual(code, 200)
                self.assertEqual(len(au["rows"]), 1)
                self.assertIn("gitlab_url", au["rows"][0]["detail"]["sections"])
                self.assertEqual(sorted(au["rows"][0]["detail"]["stored"]), ["gitlab_token", "jira_token"])
                self.assertNotIn("jtoken", json.dumps(au))
                self.assertNotIn('"secret"', json.dumps(au))

                code, ov = self.overview()
                self.assertTrue(ov["configured"], ov)
                self.assertEqual(ov["me"], "me", {k: ov.get(k) for k in ("errors", "sync", "loading", "problems", "sources")})
                self.assertTrue(ov["jira"]["ok"])
                self.assertTrue(any(i["kind"] == "branch" and i["branch"] == "agent/DLP-130-retry" for i in ov["mine"]))
                br = next(i for i in ov["mine"] if i["kind"] == "branch" and i["branch"] == "agent/DLP-130-retry")
                self.assertIn("/-/merge_requests/new?merge_request%5Bsource_branch%5D=agent%2FDLP-130-retry", br["create_mr_url"])   # Branch ohne MR: Link zum Anlegen
                self.assertTrue(all(not i.get("create_mr_url") for i in ov["mine"] if i["kind"] == "mr"))
                names = [(i["kind"], i["branch"]) for i in ov["mine"]]
                self.assertNotIn(("branch", "release/2.0"), names)   # release/* wird standardmäßig ignoriert
                self.assertNotIn(("mr", "release/1.5"), names)
                self.assertIn(("mr", "feature/DLP-101-a"), names)
                self.assertTrue(ov["jira"]["only_active"])
                self.assertEqual({x["key"] for x in ov["jira"]["stories"]}, {"DLP-101", "DLP-102", "DLP-103"})   # DLP-120 liegt nicht im aktiven Sprint
                self.assertEqual({x["key"]: x["counts"] for x in ov["jira"]["stories"]}["DLP-103"], False)   # 0.30: der Bug bleibt sichtbar, zählt aber nicht
                self.assertEqual(ov["jira"]["count"], 2)
                self.assertEqual(ov["jira"]["sprints"][0]["name"], "Sprint 12")
                self.assertGreater(ov["jira"]["sprints"][0]["days_left"], 100)
                t101 = next(i for i in ov["mine"] if i["branch"] == "feature/DLP-101-a")["ticket"]
                self.assertTrue(t101["in_sprint"])
                self.assertEqual(t101["sprint"], "Sprint 12")
                self.assertEqual(ov["ideas"], [])
                self.assertEqual(ov["jobs"], [])

                code, st = self.call("GET", "/api/settings")
                self.assertTrue(st["secrets"]["gitlab_token"]["set"])
                self.assertNotIn("secret", json.dumps(st["gitlab"]))
                self.assertNotIn('"jtoken"', json.dumps(st))

                # ausgeblendete Funktionen sind auch serverseitig zu
                for m, path in (("POST", "/api/deploy"),
                                ("POST", "/api/prompt"), ("GET", "/api/jobs")):
                    code, r = self.call(m, path, {} if m == "POST" else None)
                    self.assertEqual(code, 404, path)
                    self.assertIn("ausgeschaltet", r["error"])
                # release/* wieder zeigen und alle Sprints zulassen
                code, _ = self.call("POST", "/api/settings/save", {
                    "gitlab": {"url": glurl}, "projects": [{"id": 1, "name": "dlp-core"}],
                    "branch_filter": {"emails": ["me@x.ch"], "ignore_branches": []},
                    "jira": {"url": jiurl, "auth": "bearer", "project_keys": ["DLP"], "wip_issue_types": ["Story"],
                             "only_active_sprints": False}})
                self.assertEqual(code, 200)
                code, ov = self.overview()
                names = [(i["kind"], i["branch"]) for i in ov["mine"]]
                self.assertIn(("branch", "release/2.0"), names)
                self.assertIn(("mr", "release/1.5"), names)
                self.assertEqual({x["key"] for x in ov["jira"]["stories"]}, {"DLP-101", "DLP-102", "DLP-103", "DLP-120"})   # 0.30: DLP-103 (Bug) bleibt sichtbar
                # einschalten, ohne Neustart
                code, _ = self.call("POST", "/api/settings/save", {
                    "gitlab": {"url": glurl}, "projects": [{"id": 1, "name": "dlp-core"}], "features": {"ideas": True, "testenv": True},
                    "jira": {"url": jiurl, "auth": "bearer", "project_keys": ["DLP"]}})
                self.assertEqual(code, 200)
                code, r = self.call("POST", "/api/ideas", {"text": "Test"})
                self.assertEqual(code, 200, r)
                code, ov = self.overview()
                self.assertEqual(len(ov["ideas"]), 1)
                self.assertTrue(ov["configured"])   # gespeicherter Token blieb erhalten

                # Secret löschen
                code, _ = self.call("POST", "/api/settings/save", {"gitlab": {"url": glurl}, "delete_secrets": ["gitlab_token"]})
                self.assertEqual(code, 200)
                code, ov = self.overview()
                self.assertFalse(ov["configured"])

                log = Path(tmp, "home", "logs", "tinyops.log").read_text()
                self.assertNotIn("jtoken", log)
                self.assertIn("Einstellungen gespeichert", log)
        finally:
            for p in procs:
                p.terminate()
                p.wait()


if __name__ == "__main__":
    unittest.main()
