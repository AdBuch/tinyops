"""Kontingent-Reader (Claude, Codex) gegen einen Fake-Server: Parser, Fehlerbilder, Token-Schutz, nur GET, Server, Einstellungen."""
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import server  # noqa: E402
import settings  # noqa: E402
import usage  # noqa: E402


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Parsers(unittest.TestCase):
    def test_claude_windows(self):
        w = usage.parse_claude({"five_hour": {"utilization": 37.5, "resets_at": "2099-01-01T00:00:00Z"}, "seven_day": None,
                                "seven_day_opus": {"utilization": 100, "resets_at": None}})
        self.assertEqual([x["label"] for x in w], ["5 h", "Woche Opus"])
        self.assertEqual(w[0]["left_pct"], 62.5)
        self.assertEqual(w[1]["left_pct"], 0.0)
        self.assertIsNone(w[1]["secs_left"])
        self.assertEqual(usage.parse_claude({"x": 1}), [])
        self.assertEqual(usage.parse_claude({"five_hour": {"utilization": "abc"}}), [])    # Unsinn wird nicht zur Zahl

    def test_codex_windows_by_duration(self):
        now = 1000.0
        w = usage.parse_codex({"rate_limit": {"primary_window": {"used_percent": 20, "limit_window_seconds": 18000, "reset_at": 4600},
                                              "secondary_window": {"usedPercent": 64, "limitWindowSeconds": 604800, "resetAt": 87400}}}, now)
        self.assertEqual([(x["label"], x["left_pct"], x["secs_left"]) for x in w], [("5 h", 80.0, 3600), ("Woche", 36.0, 86400)])
        self.assertEqual(usage.parse_codex({}), [])

    def test_percent_is_clamped(self):
        self.assertEqual(usage.parse_claude({"five_hour": {"utilization": 250, "resets_at": None}})[0]["left_pct"], 0.0)


class WithMock(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.port = free_port()
        cls.proc = subprocess.Popen([sys.executable, str(ROOT / "tests" / "mock_usage.py"), str(cls.port)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(80):
            try:
                socket.create_connection(("127.0.0.1", cls.port), timeout=0.2).close()
                break
            except OSError:
                time.sleep(0.1)
        cls.base = "http://127.0.0.1:%d" % cls.port
        cls.tmp = tempfile.TemporaryDirectory()
        t = Path(cls.tmp.name)
        cls.cl_ok = t / "claude.json"
        cls.cl_ok.write_text(json.dumps({"claudeAiOauth": {"accessToken": "claude-ok", "expiresAt": int((time.time() + 3600) * 1000)}}))
        cls.cl_old = t / "claude-old.json"
        cls.cl_old.write_text(json.dumps({"claudeAiOauth": {"accessToken": "claude-ok", "expiresAt": int((time.time() - 60) * 1000)}}))
        cls.cl_bad = t / "claude-bad.json"
        cls.cl_bad.write_text(json.dumps({"claudeAiOauth": {"accessToken": "SECRET-falsch"}}))
        cls.cx_ok = t / "codex.json"
        cls.cx_ok.write_text(json.dumps({"tokens": {"access_token": "codex-ok", "account_id": "acc-1"}}))
        cls.cx_key = t / "codex-key.json"
        cls.cx_key.write_text(json.dumps({"OPENAI_API_KEY": "sk-x"}))
        os.environ["TINYOPS_USAGE_CLAUDE_URL"] = cls.base + "/claude/usage"
        os.environ["TINYOPS_USAGE_CODEX_URL"] = cls.base + "/codex/usage"

    @classmethod
    def tearDownClass(cls):
        cls.proc.terminate()
        cls.proc.wait(5)
        cls.tmp.cleanup()
        os.environ.pop("TINYOPS_USAGE_CLAUDE_URL", None)
        os.environ.pop("TINYOPS_USAGE_CODEX_URL", None)

    def calls(self):
        return json.load(urllib.request.urlopen(self.base + "/_calls"))


class Fetch(WithMock):
    def test_claude_ok(self):
        r = usage.fetch("claude", str(self.cl_ok))
        self.assertTrue(r["ok"], r)
        self.assertEqual(r["windows"][0]["left_pct"], 62.5)
        self.assertTrue(any(c["beta"] == "oauth-2025-04-20" for c in self.calls()))

    def test_codex_ok_sends_account_header(self):
        r = usage.fetch("codex", str(self.cx_ok))
        self.assertTrue(r["ok"], r)
        self.assertEqual([w["left_pct"] for w in r["windows"]], [80.0, 36.0])
        self.assertTrue(any(c["account"] == "acc-1" for c in self.calls()))

    def test_error_cases_never_raise_and_never_leak_token(self):
        r = usage.fetch("claude", str(self.cl_bad))
        self.assertFalse(r["ok"])
        self.assertIn("HTTP 401", r["error"])
        self.assertNotIn("SECRET", json.dumps(r))
        self.assertIn("abgelaufen", usage.fetch("claude", str(self.cl_old))["error"])       # abgelaufen: gar nicht erst senden
        self.assertIn("nicht gefunden", usage.fetch("claude", "/nicht/da.json")["error"])
        self.assertIn("ChatGPT-Anmeldung", usage.fetch("codex", str(self.cx_key))["error"])
        bad = Path(self.tmp.name, "kaputt.json")
        bad.write_text("{nicht json")
        self.assertIn("nicht lesbar", usage.fetch("codex", str(bad))["error"])

    def test_unknown_format_and_404(self):
        os.environ["TINYOPS_USAGE_CLAUDE_URL"] = self.base + "/broken/usage"
        try:
            self.assertIn("keine Fenster", usage.fetch("claude", str(self.cl_ok))["error"])
            os.environ["TINYOPS_USAGE_CLAUDE_URL"] = self.base + "/gibts/nicht"
            self.assertIn("404", usage.fetch("claude", str(self.cl_ok))["error"])
        finally:
            os.environ["TINYOPS_USAGE_CLAUDE_URL"] = self.base + "/claude/usage"

    def test_unreachable(self):
        os.environ["TINYOPS_USAGE_CODEX_URL"] = "http://127.0.0.1:%d/x" % free_port()
        try:
            self.assertIn("nicht erreichbar", usage.fetch("codex", str(self.cx_ok))["error"])
        finally:
            os.environ["TINYOPS_USAGE_CODEX_URL"] = self.base + "/codex/usage"

    def test_only_get(self):
        usage.fetch("claude", str(self.cl_ok))
        usage.fetch("codex", str(self.cx_ok))
        self.assertTrue(all(c["method"] == "GET" for c in self.calls()))


class InApp(WithMock):
    def app(self, **uc):
        self.t2 = tempfile.TemporaryDirectory()
        cfg = server.load_config(None)
        cfg["data_dir"] = self.t2.name
        cfg["usage"] = dict({"claude": True, "codex": True, "claude_file": str(self.cl_ok), "codex_file": str(self.cx_ok), "cache_seconds": 300}, **uc)
        return server.App(cfg, False, {"gitlab_token": "x"}, Path("/nonexistent/c.json"))

    def tearDown(self):
        if getattr(self, "t2", None):
            self.t2.cleanup()

    def test_view_cache_and_partial_failure(self):
        a = self.app(codex_file="/nicht/da.json")
        before = len(self.calls())
        v = a.usage_view()
        self.assertTrue(v["enabled"])
        by = {i["id"]: i for i in v["items"]}
        self.assertTrue(by["claude"]["ok"])
        self.assertFalse(by["codex"]["ok"])                     # ein Fehler stoppt den anderen nicht
        a.usage_view()
        self.assertEqual(len(self.calls()) - before, 1)         # zweiter Aufruf aus dem Zwischenspeicher
        a.usage_view(fresh=True)
        self.assertEqual(len(self.calls()) - before, 2)

    def test_off_by_default_and_no_requests(self):
        with tempfile.TemporaryDirectory() as d:
            cfg = server.load_config(None)
            cfg["data_dir"] = d
            a = server.App(cfg, False, {"gitlab_token": "x"}, Path("/nonexistent/c.json"))
            before = len(self.calls())
            self.assertFalse(a.usage_view()["enabled"])
            self.assertEqual(len(self.calls()), before)
            self.assertEqual(a.usage_providers(), [])

    def test_demo_and_overview_flag(self):
        with tempfile.TemporaryDirectory() as d:
            cfg = server.load_config(None)
            cfg["data_dir"] = d
            cfg["usage"] = {"claude": True}
            a = server.App(cfg, True, {}, Path("/nonexistent/c.json"))
            v = a.usage_view()
            self.assertEqual([i["id"] for i in v["items"]], ["claude"])
            self.assertEqual(a.overview()["usage_providers"], ["claude"])


class Settings(unittest.TestCase):
    def test_save_and_view(self):
        cfg, err = settings.build_config({"projects": []}, {"usage": {"claude": True, "codex": False, "claude_file": " /x/c.json ", "cache_seconds": "60"}})
        self.assertEqual(err, {}, err)
        self.assertEqual((cfg["usage"]["claude"], cfg["usage"]["codex"], cfg["usage"]["claude_file"], cfg["usage"]["cache_seconds"]), (True, False, "/x/c.json", 60))
        v = settings.view(cfg, "/x/config.json")
        self.assertTrue(v["usage"]["claude"])
        self.assertFalse(v["usage"]["codex"])
        _, err = settings.build_config({"projects": []}, {"usage": {"cache_seconds": "5"}})
        self.assertIn("usage.cache_seconds", err)
        # Das Token selbst taucht nirgends in Config oder Ansicht auf
        self.assertNotIn("token", json.dumps(v["usage"]).lower())


if __name__ == "__main__":
    unittest.main()
