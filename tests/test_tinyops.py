"""Unit-Tests: python3 -m unittest discover -s tests -v  (im Ordner tinyops)"""
import http.server
import json
import os
import stat
import sys
import tempfile
import threading
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import secretstore as store  # noqa: E402
import server  # noqa: E402
import tlog  # noqa: E402


class KeyExtraction(unittest.TestCase):
    def test_branch_and_title(self):
        self.assertEqual(server.extract_keys("feature/dlp-123-retry Fix DLP-124", ["DLP"]), ["DLP-123", "DLP-124"])

    def test_lowercase_ignored_without_allowlist(self):
        self.assertEqual(server.extract_keys("agent/sonar-wave-1 feature/DLP-5"), ["DLP-5"])
        self.assertEqual(server.extract_keys("feature/dlp-5"), [])

    def test_false_positives_without_allowlist(self):
        self.assertEqual(server.extract_keys("UTF-8 SHA-256 CVE-2024-1234 feature/DLP-5"), ["DLP-5"])

    def test_allowlist(self):
        self.assertEqual(server.extract_keys("OPS-1 DLP-2 fix-3", ["dlp"]), ["DLP-2"])

    def test_no_key(self):
        self.assertEqual(server.extract_keys("chore/docker-nonroot"), [])


class Timestamps(unittest.TestCase):
    def test_jira_offset_without_colon(self):
        self.assertIsNotNone(server.parse_ts("2026-10-23T09:12:03.000+0200"))

    def test_gitlab_zulu(self):
        self.assertIsNotNone(server.parse_ts("2026-10-23T09:12:03.000Z"))

    def test_garbage(self):
        self.assertIsNone(server.parse_ts("gestern"))


class Secrets(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        os.environ["TINYOPS_HOME"] = str(Path(self.tmp.name) / "cfg")
        for k in ("TINYOPS_JIRA_TOKEN", "TINYOPS_GITLAB_TOKEN"):
            os.environ.pop(k, None)
        self._kr = store._keyring
        store._keyring = lambda: None   # Test ohne Schlüsselbund

    def tearDown(self):
        store._keyring = self._kr
        os.environ.pop("TINYOPS_HOME", None)
        self.tmp.cleanup()

    def test_file_is_private(self):
        where = store.set_secret("jira_token", "geheim-wert-123")
        self.assertIn("Datei", where)
        p = store.secrets_file()
        self.assertEqual(stat.S_IMODE(p.stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(p.parent.stat().st_mode), 0o700)
        self.assertEqual(store.resolve("jira_token")[0], "geheim-wert-123")

    def test_refuses_world_readable(self):
        store.set_secret("jira_token", "geheim-wert-123")
        os.chmod(str(store.secrets_file()), 0o644)
        with self.assertRaises(store.SecretError):
            store.resolve("jira_token")

    def test_env_beats_file(self):
        store.set_secret("jira_token", "aus-datei-1234")
        os.environ["TINYOPS_JIRA_TOKEN"] = "aus-env-1234"
        self.assertEqual(store.resolve("jira_token")[0], "aus-env-1234")

    def test_cmd_source(self):
        val, src = store.resolve("jira_token", {"cmd": ["echo", "aus-befehl-1234"]})
        self.assertEqual(val, "aus-befehl-1234")
        self.assertIn("Befehl", src)

    def test_cmd_failure_is_error_not_secret(self):
        with self.assertRaises(store.SecretError):
            store.resolve("jira_token", {"cmd": ["false"]})

    def test_unknown_name(self):
        with self.assertRaises(store.SecretError):
            store.set_secret("passwort", "x")

    def test_scrub(self):
        store.register("topsecret-value")
        self.assertEqual(store.scrub("Bearer topsecret-value ok"), "Bearer *** ok")

    def test_delete(self):
        store.set_secret("jira_token", "geheim-wert-123")
        self.assertEqual(store.delete_secret("jira_token"), ["Datei"])
        self.assertEqual(store.resolve("jira_token"), (None, None))


class PlainSecretsRejected(unittest.TestCase):
    def test_top_level(self):
        with self.assertRaises(SystemExit):
            server.reject_plain_secrets({"access_token": "abc"})

    def test_in_jira(self):
        with self.assertRaises(SystemExit):
            server.reject_plain_secrets({"jira": {"password": "abc"}})

    def test_empty_is_fine(self):
        server.reject_plain_secrets({"access_token": "", "jira": {"url": "https://j"}})


class NoRedirectLeak(unittest.TestCase):
    """Eine Weiterleitung darf den Token nie an einen anderen Host schicken."""

    def test_token_not_forwarded(self):
        seen = []

        class Trap(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                seen.append(self.headers.get("PRIVATE-TOKEN"))
                self.send_response(200)
                self.send_header("Content-Length", "2")
                self.end_headers()
                self.wfile.write(b"{}")

            def log_message(self, *a):
                pass

        trap = http.server.HTTPServer(("127.0.0.1", 0), Trap)
        port = trap.server_address[1]

        class Redirector(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(302)
                self.send_header("Location", "http://127.0.0.1:%d/steal" % port)
                self.send_header("Content-Length", "0")
                self.end_headers()

            def log_message(self, *a):
                pass

        redir = http.server.HTTPServer(("127.0.0.1", 0), Redirector)
        for s in (trap, redir):
            threading.Thread(target=s.serve_forever, daemon=True).start()
        try:
            client = server.Http("GitLab", "http://127.0.0.1:%d" % redir.server_address[1],
                                 {"PRIVATE-TOKEN": "supersecret"}, server.make_ssl({}))
            with self.assertRaises(server.UserError) as cm:
                client.get("/x")
            self.assertIn("302", str(cm.exception))
            self.assertEqual(seen, [])
        finally:
            trap.shutdown()
            redir.shutdown()


class BranchClassification(unittest.TestCase):
    IDENT = {"emails": {"me@x.ch"}, "names": {"ich"}, "agent_emails": {"bot@x.ch"},
             "agent_names": set(), "patterns": ["co-authored-by: claude"]}

    def c(self, email, msg="x", name=""):
        return {"author_email": email, "author_name": name, "message": msg, "title": msg}

    def test_mine(self):
        r = server.classify_commits([self.c("me@x.ch")], self.IDENT)
        self.assertTrue(r["include"] and r["by_me"] and not r["by_agent"])

    def test_agent_account(self):
        r = server.classify_commits([self.c("bot@x.ch")], self.IDENT)
        self.assertTrue(r["include"] and r["by_agent"])

    def test_my_commit_with_trailer_is_agent(self):
        r = server.classify_commits([self.c("me@x.ch", "a\n\nCo-Authored-By: Claude")], self.IDENT)
        self.assertTrue(r["include"] and r["by_agent"])

    def test_colleague_with_trailer_excluded(self):
        r = server.classify_commits([self.c("k@x.ch", "Co-Authored-By: Claude")], self.IDENT)
        self.assertFalse(r["include"])

    def test_older_commit_of_mine_counts(self):
        r = server.classify_commits([self.c("k@x.ch"), self.c("ME@x.ch")], self.IDENT)
        self.assertTrue(r["include"])

    def test_name_match_and_empty(self):
        self.assertTrue(server.classify_commits([self.c("z@z", name="Ich")], self.IDENT)["include"])
        self.assertFalse(server.classify_commits([], self.IDENT)["include"])


class LogFile(unittest.TestCase):
    def test_scrubbed_private_and_levels(self):
        with tempfile.TemporaryDirectory() as d:
            store.register("topsecret-value")
            tlog.setup({"log_dir": d}, "debug", console=False)
            lg = tlog.get("test")
            lg.info("Token topsecret-value im Text")
            lg.debug("nur debug")
            try:
                raise ValueError("topsecret-value")
            except ValueError:
                lg.exception("kaputt")
            for h in tlog.logging.getLogger("tinyops").handlers:
                h.flush()
            text = Path(d, "tinyops.log").read_text()
            self.assertNotIn("topsecret-value", text)
            self.assertIn("nur debug", text)
            self.assertEqual(stat.S_IMODE(os.stat(Path(d, "tinyops.log")).st_mode), 0o600)
            warn = tlog.tail({"log_dir": d}, 50, "warning")
            self.assertTrue(any("kaputt" in x for x in warn))
            self.assertTrue(any("Traceback" in x for x in warn))   # Traceback bleibt beim Eintrag
            self.assertFalse(any("nur debug" in x for x in warn))
            tlog.setup({"log_dir": d}, "info", console=False)   # Handler lösen, bevor das Verzeichnis verschwindet


if __name__ == "__main__":
    unittest.main()
