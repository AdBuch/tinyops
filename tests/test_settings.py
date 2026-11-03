"""Verbindungstests der Einstellungsseite: gute und schlechte Fälle gegen Fake-Server, inklusive TLS und Weiterleitungen."""
import http.server
import json
import os
import shutil
import socket
import ssl
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import secretstore as store  # noqa: E402
import settings  # noqa: E402
import sprint  # noqa: E402
import server  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def start(script):
    port = free_port()
    p = subprocess.Popen([sys.executable, str(ROOT / "tests" / script), str(port)])
    for _ in range(50):
        try:
            socket.create_connection(("127.0.0.1", port), timeout=0.2).close()
            return p, port
        except OSError:
            time.sleep(0.1)
    raise RuntimeError("Mock startet nicht")


def nostored(name):
    return None, ""


def step(res, sid):
    return next(s for s in res["steps"] if s["id"] == sid)


class Stub:
    """Kleiner Server mit fester Antwort (Weiterleitung, 404, HTML ...)."""

    def __init__(self, status, body=b"", headers=None, ctype="application/json"):
        outer = self

        class H(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(status)
                for k, v in (headers or {}).items():
                    self.send_header(k, v)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *a):
                pass
        self.srv = http.server.HTTPServer(("127.0.0.1", 0), H)
        self.port = self.srv.server_address[1]
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()

    def stop(self):
        self.srv.shutdown()


class GitLabTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.p, cls.port = start("mock_gitlab.py")
        cls.url = "http://127.0.0.1:%d" % cls.port

    @classmethod
    def tearDownClass(cls):
        cls.p.terminate()
        cls.p.wait()

    def test_ok(self):
        r = settings.test_gitlab({"url": self.url, "token": "secret", "projects": [1]}, nostored)
        self.assertTrue(r["ok"], r)
        self.assertEqual(r["user"]["username"], "me")
        self.assertEqual(step(r, "api")["status"], "ok")
        self.assertIn("19.2.5", step(r, "version")["detail"])
        self.assertEqual(step(r, "project-1")["status"], "ok")

    def test_wrong_token(self):
        r = settings.test_gitlab({"url": self.url, "token": "falsch"}, nostored)
        self.assertFalse(r["ok"])
        a = step(r, "auth")
        self.assertEqual(a["status"], "fail")
        self.assertIn("401", a["detail"])
        self.assertIn("read_api", a["hint"])
        self.assertEqual(step(r, "scopes")["status"], "skip")

    def test_token_not_in_output(self):
        r = settings.test_gitlab({"url": self.url, "token": "geheimes-token-xyz"}, nostored)
        self.assertNotIn("geheimes-token-xyz", json.dumps(r))

    def test_no_token(self):
        r = settings.test_gitlab({"url": self.url}, nostored)
        self.assertFalse(r["ok"])
        self.assertIn("Kein Token", step(r, "auth")["detail"])

    def test_stored_token_used(self):
        r = settings.test_gitlab({"url": self.url}, lambda n: ("secret", "Testspeicher"))
        self.assertTrue(r["ok"], r)
        self.assertIn("Testspeicher", step(r, "auth")["detail"])

    def test_missing_project(self):
        r = settings.test_gitlab({"url": self.url, "token": "secret", "projects": [999]}, nostored)
        self.assertFalse(r["ok"])
        self.assertIn("404", step(r, "project-999")["detail"])

    def test_refused(self):
        port = free_port()   # nichts lauscht darauf
        r = settings.test_gitlab({"url": "http://127.0.0.1:%d" % port, "token": "x"}, nostored)
        self.assertEqual(step(r, "tcp")["status"], "fail")
        self.assertIn("Port", step(r, "tcp")["hint"])
        self.assertEqual(step(r, "api")["status"], "skip")

    def test_dns(self):
        r = settings.test_gitlab({"url": "https://gibt-es-nicht.invalid", "token": "x"}, nostored)
        self.assertEqual(step(r, "dns")["status"], "fail")
        self.assertIn("VPN", step(r, "dns")["hint"])

    def test_bad_urls(self):
        for u in ("", "gitlab.firma.ch", "ftp://x"):
            r = settings.test_gitlab({"url": u, "token": "x"}, nostored)
            self.assertFalse(r["ok"], u)
            self.assertEqual(step(r, "url")["status"], "fail")

    def test_url_cleanup(self):
        r = settings.test_gitlab({"url": self.url + "/api/v4/", "token": "secret"}, nostored)
        self.assertTrue(r["ok"], r)
        self.assertIn("/api/v4", step(r, "url")["detail"])

    def test_bad_ca_file(self):
        r = settings.test_gitlab({"url": self.url, "token": "x", "ca_bundle": "/nicht/da.pem"}, nostored)
        self.assertEqual(step(r, "ca")["status"], "fail")

    def test_redirect_wrong_path_html(self):
        s = Stub(301, headers={"Location": "https://gitlab.example/"})
        try:
            r = settings.test_gitlab({"url": "http://127.0.0.1:%d" % s.port, "token": "x"}, nostored)
            self.assertEqual(step(r, "api")["status"], "fail")
            self.assertIn("https://gitlab.example/", step(r, "api")["detail"])
        finally:
            s.stop()
        s = Stub(404, b"<html>nope</html>", ctype="text/html")
        try:
            r = settings.test_gitlab({"url": "http://127.0.0.1:%d" % s.port, "token": "x"}, nostored)
            self.assertIn("Unterpfad", step(r, "api")["hint"])
        finally:
            s.stop()
        s = Stub(200, b"<html>login</html>", ctype="text/html")
        try:
            r = settings.test_gitlab({"url": "http://127.0.0.1:%d" % s.port, "token": "x"}, nostored)
            self.assertEqual(step(r, "api")["status"], "fail")
        finally:
            s.stop()

    def test_403_and_503(self):
        for code, word in ((403, "Firewall"), (503, "Wartungsmodus")):
            s = Stub(code, b'{"message":"x"}')
            try:
                r = settings.test_gitlab({"url": "http://127.0.0.1:%d" % s.port, "token": "x"}, nostored)
                self.assertIn(word, step(r, "api")["hint"])
            finally:
                s.stop()

    def test_project_search_and_identity(self):
        res = settings.search_projects({"url": self.url, "token": "secret", "q": "dlp"}, nostored)
        self.assertEqual(res["items"][0]["id"], 1)
        res = settings.search_projects({"url": self.url, "token": "falsch", "q": "dlp"}, nostored)
        self.assertIn("401", res["error"])
        ident = settings.suggest_identity({"url": self.url, "token": "secret", "project_id": 1}, nostored)
        self.assertTrue(any(a["is_me"] for a in ident["authors"]))
        self.assertEqual(ident["trailers"][0]["pattern"], "Co-Authored-By: Claude")


class JiraTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.p, cls.port = start("mock_jira.py")
        cls.url = "http://127.0.0.1:%d" % cls.port

    @classmethod
    def tearDownClass(cls):
        cls.p.terminate()
        cls.p.wait()

    def form(self, **kw):
        f = {"url": self.url, "auth": "bearer", "secret": "jtoken", "project_keys": ["DLP"], "issue_types": ["Story"],
             "jql": 'assignee = currentUser() AND statusCategory = "In Progress"', "story_limit": 2}
        f.update(kw)
        return f

    def test_ok(self):
        r = settings.test_jira(self.form(), nostored)
        self.assertTrue(r["ok"], r)
        self.assertEqual(step(r, "api")["status"], "ok")
        self.assertIn("9.4.14", step(r, "api")["detail"])
        self.assertEqual(step(r, "projects")["status"], "ok")
        self.assertEqual(step(r, "types")["status"], "ok")
        self.assertIn("2 zählen", step(r, "jql")["detail"])   # 2 Stories, 1 Bug
        self.assertEqual(r["projects"], ["DLP", "OPS"])

    def test_wrong_bearer(self):
        r = settings.test_jira(self.form(secret="falsch"), nostored)
        a = step(r, "auth")
        self.assertEqual(a["status"], "fail")
        self.assertIn("Personal Access Token", a["hint"])
        self.assertIn("basic", a["hint"])
        self.assertEqual(step(r, "jql")["status"], "skip")

    def test_basic_ok_wrong_and_cooldown(self):
        ok = settings.test_jira(self.form(auth="basic", username="jira-user", secret="jpass"), nostored)
        self.assertTrue(ok["ok"], ok)
        bad = settings.test_jira(self.form(auth="basic", username="u-cool", secret="falsch"), nostored)
        self.assertIn("401", step(bad, "auth")["detail"])
        self.assertIn("Benutzername", step(bad, "auth")["hint"])
        again = settings.test_jira(self.form(auth="basic", username="u-cool", secret="nochmal-falsch"), nostored)
        self.assertIn("Pause", step(again, "auth")["detail"])   # kein zweiter Versuch gegen Jira
        other = settings.test_jira(self.form(auth="basic", username="jira-user", secret="jpass"), nostored)
        self.assertTrue(other["ok"])                            # andere Konten sind nicht betroffen

    def test_missing_secret_and_user(self):
        r = settings.test_jira(self.form(secret=""), nostored)
        self.assertIn("Kein Token", step(r, "auth")["detail"])
        r = settings.test_jira(self.form(auth="basic", username="", secret="x"), nostored)
        self.assertIn("Benutzername", step(r, "auth")["detail"])

    def test_warnings_keys_types(self):
        r = settings.test_jira(self.form(project_keys=["DLP", "XYZ"], issue_types=["Story", "Aufgabe"]), nostored)
        self.assertEqual(step(r, "projects")["status"], "warn")
        self.assertIn("XYZ", step(r, "projects")["detail"])
        self.assertEqual(step(r, "types")["status"], "warn")
        self.assertIn("Aufgabe", step(r, "types")["detail"])
        self.assertTrue(r["ok"])   # Warnungen sind kein Fehler

    def test_bad_jql(self):
        r = settings.test_jira(self.form(jql="kaputt ("), nostored)
        j = step(r, "jql")
        self.assertEqual(j["status"], "fail")
        self.assertIn("unbekannte JQL", j["detail"])
        self.assertIn("In Progress", j["hint"])   # Status der Instanz als Hilfe
        self.assertFalse(r["ok"])

    def test_sprint_filter_in_test(self):
        r = settings.test_jira(self.form(), nostored)
        self.assertEqual(step(r, "sprintfield")["status"], "ok")
        j = step(r, "jql")
        self.assertIn("sprint in openSprints()", j["detail"])   # zeigt die tatsächlich abgefragte JQL
        self.assertIn("Sprint 12", j["detail"])
        self.assertIn("3 Treffer", j["detail"])                  # DLP-120 liegt im Backlog
        r = settings.test_jira(self.form(only_active_sprints=False), nostored)
        self.assertIn("4 Treffer", step(r, "jql")["detail"])
        self.assertNotIn("openSprints", step(r, "jql")["detail"])

    def test_client_marks_sprint(self):
        jc = dict(server.JIRA_DEFAULTS, url=self.url)
        c = server.JiraClient(jc, "Bearer jtoken", server.make_ssl({}))
        got = c.lookup(["DLP-101", "DLP-120"])
        self.assertIs(got["DLP-101"]["in_sprint"], True)
        self.assertEqual(got["DLP-101"]["sprint"], "Sprint 12")
        self.assertIs(got["DLP-120"]["in_sprint"], False)
        keys = {i["key"] for i in c.in_progress()}
        self.assertEqual(keys, {"DLP-101", "DLP-102", "DLP-103"})
        c2 = server.JiraClient(dict(jc, only_active_sprints=False), "Bearer jtoken", server.make_ssl({}))
        self.assertIn("DLP-120", {i["key"] for i in c2.in_progress()})

    def test_over_limit_warns(self):
        r = settings.test_jira(self.form(story_limit=1), nostored)
        self.assertEqual(step(r, "jql")["status"], "warn")

    def test_cloud_and_captcha_and_sso(self):
        s = Stub(403, b"{}", headers={"X-Authentication-Denied-Reason": "CAPTCHA_CHALLENGE; login-url=x"})
        try:
            # serverInfo 403 ohne HTML gilt als Jira; myself liefert dann das CAPTCHA
            r = settings.test_jira(self.form(url="http://127.0.0.1:%d" % s.port), nostored)
            self.assertIn("CAPTCHA", step(r, "auth")["detail"])
        finally:
            s.stop()
        s = Stub(302, headers={"Location": "https://sso.firma.example/login?x=1"})
        try:
            r = settings.test_jira(self.form(url="http://127.0.0.1:%d" % s.port), nostored)
            self.assertEqual(step(r, "api")["status"], "fail")
            self.assertIn("SSO", step(r, "api")["hint"])
        finally:
            s.stop()


@unittest.skipUnless(shutil.which("openssl"), "openssl fehlt")
class TlsTests(unittest.TestCase):
    def test_self_signed_then_with_ca(self):
        with tempfile.TemporaryDirectory() as d:
            key, crt = Path(d, "k.pem"), Path(d, "c.pem")
            subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-keyout", str(key), "-out", str(crt),
                            "-days", "30", "-subj", "/CN=localhost", "-addext", "subjectAltName=DNS:localhost"],
                           check=True, capture_output=True)
            ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            ctx.load_cert_chain(str(crt), str(key))

            class H(http.server.BaseHTTPRequestHandler):
                def do_GET(self):
                    body = b'{"message":"401 Unauthorized"}'
                    self.send_response(401)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)

                def log_message(self, *a):
                    pass
            srv = http.server.HTTPServer(("127.0.0.1", 0), H)
            srv.socket = ctx.wrap_socket(srv.socket, server_side=True)
            threading.Thread(target=srv.serve_forever, daemon=True).start()
            url = "https://localhost:%d" % srv.server_address[1]
            try:
                r = settings.test_gitlab({"url": url, "token": "x"}, nostored)
                t = step(r, "tls")
                self.assertEqual(t["status"], "fail")
                self.assertIn("CA-Datei", t["hint"])
                self.assertEqual(step(r, "api")["status"], "skip")
                r = settings.test_gitlab({"url": url, "token": "x", "ca_bundle": str(crt)}, nostored)
                self.assertEqual(step(r, "tls")["status"], "ok", r)
                self.assertEqual(step(r, "api")["status"], "ok")
            finally:
                srv.shutdown()


class SprintHelpers(unittest.TestCase):
    def test_effective_jql(self):
        self.assertEqual(sprint.effective_jql('a = 1 ORDER BY x', True), '(a = 1) AND sprint in openSprints() ORDER BY x')
        self.assertEqual(sprint.effective_jql('a = 1', False), 'a = 1')
        self.assertEqual(sprint.effective_jql('sprint in openSprints() ORDER BY x', True), 'sprint in openSprints() ORDER BY x')
        self.assertEqual(sprint.effective_jql('', True), 'sprint in openSprints()')
        self.assertEqual(sprint.effective_jql('status = "Sprint Backlog"', True), '(status = "Sprint Backlog") AND sprint in openSprints()')

    def test_parse_sprints(self):
        txt = ["x.Sprint@1[id=1,state=CLOSED,name=Alt,endDate=2026-01-01]",
               "x.Sprint@2[id=2,state=ACTIVE,name=Sprint 12, Team A,endDate=2026-11-13T09:00:00.000+0100,completeDate=<null>]"]
        a = sprint.active_sprint(txt)
        self.assertEqual(a["name"], "Sprint 12, Team A")
        self.assertTrue(a["end"].startswith("2026-11-13"))
        self.assertEqual(sprint.active_sprint([{"name": "S", "state": "ACTIVE", "endDate": "2026-11-01"}])["name"], "S")
        self.assertIsNone(sprint.active_sprint(None))
        self.assertIsNone(sprint.active_sprint([{"name": "S", "state": "closed"}]))

    def test_ignored_branch(self):
        self.assertTrue(server.ignored_branch("release/1.2", ["release/*"]))
        self.assertFalse(server.ignored_branch("feature/release/x", ["release/*"]))
        self.assertFalse(server.ignored_branch("Release/1", ["release/*"]))
        self.assertFalse(server.ignored_branch("release/1", []))


class BuildAndSave(unittest.TestCase):
    def test_validation(self):
        cfg, err = settings.build_config({}, {"gitlab": {"url": "gitlab"}, "jira": {"url": "ftp://x", "project_keys": ["dlp", "1x"],
                                                                                      "story_limit": "abc"},
                                              "branch_filter": {"max_branches": 9999}})
        self.assertIn("gitlab.url", err)
        self.assertIn("jira.url", err)
        self.assertIn("jira.project_keys", err)
        self.assertIn("jira.story_limit", err)
        self.assertIn("branch_filter.max_branches", err)

    def test_preserves_unknown_and_project_extras(self):
        disk = {"secrets": {"gitlab_token": {"cmd": ["pass", "x"]}}, "kube_context": "t", "port": 9000,
                "projects": [{"id": 5, "name": "alt", "chart": "./helm/x", "repo_path": "/r"}]}
        cfg, err = settings.build_config(disk, {"gitlab": {"url": "https://g.example/"}, "projects": [{"id": "5", "name": "neu"}, {"id": 6, "name": "b"}],
                                                "jira": {"url": "https://j.example", "project_keys": ["dlp"], "story_limit": 3, "wip_issue_types": "Story, Bug"},
                                                "features": {"ideas": True}})
        self.assertEqual(err, {})
        self.assertEqual(cfg["secrets"], disk["secrets"])
        self.assertEqual(cfg["kube_context"], "t")
        self.assertEqual(cfg["port"], 9000)
        self.assertEqual(cfg["gitlab_url"], "https://g.example")
        self.assertEqual(cfg["projects"][0], {"id": 5, "name": "neu", "chart": "./helm/x", "repo_path": "/r"})
        self.assertEqual(cfg["jira"]["project_keys"], ["DLP"])
        self.assertEqual(cfg["jira"]["wip_issue_types"], ["Story", "Bug"])
        self.assertEqual(cfg["features"], {"ideas": True, "testenv": False, "ai": False})
        self.assertEqual(json.dumps(disk).count("projects"), 1)   # Eingabe unverändert

    def test_new_options_roundtrip(self):
        cfg, err = settings.build_config({}, {"branch_filter": {"ignore_branches": "release/*, hotfix/*"},
                                              "jira": {"url": "https://j.example", "only_active_sprints": False}})
        self.assertEqual(err, {})
        self.assertEqual(cfg["branch_filter"]["ignore_branches"], ["release/*", "hotfix/*"])
        self.assertFalse(cfg["jira"]["only_active_sprints"])
        v = settings.view(cfg, "c.json")
        self.assertEqual(v["branch_filter"]["ignore_branches"], ["release/*", "hotfix/*"])
        self.assertFalse(v["jira"]["only_active_sprints"])
        d = settings.view({}, "c.json")   # ohne Eintrag gelten die Standards
        self.assertEqual(d["branch_filter"]["ignore_branches"], ["release/*"])
        self.assertTrue(d["jira"]["only_active_sprints"])

    def test_empty_jira_url_switches_off(self):
        cfg, err = settings.build_config({"jira": {"url": "https://j", "auth": "basic"}}, {"jira": {"url": ""}})
        self.assertEqual(cfg["jira"], {})

    def test_secrets_saved_and_validated(self):
        with tempfile.TemporaryDirectory() as d:
            os.environ["TINYOPS_HOME"] = d
            try:
                where, err = settings.save_secrets({"secrets": {"gitlab_token": "glpat-abc", "jira_token": "mit leerzeichen", "bogus": "x"}})
                self.assertIn("gitlab_token", where)
                self.assertIn("jira_token", err)
                self.assertIn("bogus", err)
                self.assertEqual(store.resolve("gitlab_token")[0], "glpat-abc")
                self.assertEqual((settings.view({}, "c.json")["secrets"]["gitlab_token"])["set"], True)
                self.assertNotIn("glpat-abc", json.dumps(settings.view({}, "c.json")))
                settings.save_secrets({"delete_secrets": ["gitlab_token"]})
                self.assertIsNone(store.resolve("gitlab_token")[0])
            finally:
                os.environ.pop("TINYOPS_HOME", None)


if __name__ == "__main__":
    unittest.main()
