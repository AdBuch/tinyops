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


FIXTURE = ('{"budget":{"usage_percentage":0.15907,"initial_budget":30,"currency":"USD","reset_at":"2026-12-01T00:00:00Z",'
           '"api_budget":{"usage_percentage":0.15907,"initial_budget":30,"currency":"USD","reset_at":"2026-12-01T00:00:00Z"},'
           '"vibe_budget":{"usage_percentage":0.05994501333333333,"initial_budget":300,"currency":"USD","reset_at":"2026-12-01T00:00:00Z"}}}')


class MistralPush(unittest.TestCase):
    def good(self, now):
        return {"vibe": {"pct": 0.06, "budget": 300, "cur": "USD", "reset": "2026-12-01T00:00:00Z"},
                "api": {"pct": 0.159, "budget": 30, "cur": "USD", "reset": "2026-12-01T00:00:00Z"}}

    def test_bookmarklet_parser_on_both_page_formats(self):
        import shutil
        node = shutil.which("node")
        if not node:
            self.skipTest("node fehlt")
        escaped = FIXTURE.replace('"', '\\"')           # HTML-Variante: Flight-Daten als JS-String mit maskierten Anführungszeichen
        for name, text in (("rsc", FIXTURE), ("html", '<script>self.__next_f.push([1,"%s"])</script>' % escaped), ("leer", "<html>nichts</html>")):
            code = usage.PARSE_JS + "console.log(JSON.stringify(parse(%s)))" % json.dumps(text)
            out = json.loads(subprocess.run([node, "-e", code], capture_output=True, text=True, check=True).stdout)
            if name == "leer":
                self.assertEqual(out, {"vibe": None, "api": None})
            else:
                self.assertEqual(out["vibe"], {"pct": 0.05994501333333333, "budget": 300, "cur": "USD", "reset": "2026-12-01T00:00:00Z"}, name)
                self.assertEqual(out["api"]["budget"], 30, name)

    def test_bookmarklet_source_has_no_secrets_and_posts_only_numbers(self):
        src = usage.BOOKMARKLET_JS
        self.assertIn("__ORIGIN__", src)
        self.assertNotIn("document.cookie", src)
        self.assertNotIn("localStorage", src)
        self.assertNotIn("headers:{cookie", src.lower())

    def test_clean_push_accepts_and_rejects(self):
        now = time.mktime((2026, 11, 4, 12, 0, 0, 0, 0, 0))
        c = usage.clean_push(self.good(now), now)
        self.assertEqual(sorted(c), ["api", "vibe"])
        self.assertEqual(usage.clean_push({"vibe": self.good(now)["vibe"]}, now).keys(), {"vibe"})
        bad = [None, [], {}, {"vibe": 5}, {"vibe": {"pct": "x", "budget": 1, "cur": "USD", "reset": "2026-12-01T00:00:00Z"}},
               {"vibe": {"pct": 5000, "budget": 1, "cur": "USD", "reset": "2026-12-01T00:00:00Z"}},
               {"vibe": {"pct": float("nan"), "budget": 1, "cur": "USD", "reset": "2026-12-01T00:00:00Z"}},
               {"vibe": {"pct": 1, "budget": 0, "cur": "USD", "reset": "2026-12-01T00:00:00Z"}},
               {"vibe": {"pct": 1, "budget": 1, "cur": "usd<", "reset": "2026-12-01T00:00:00Z"}},
               {"vibe": {"pct": 1, "budget": 1, "cur": "USD", "reset": "2099-01-01T00:00:00Z"}},
               {"vibe": {"pct": 1, "budget": 1, "cur": "USD", "reset": "morgen"}}]
        for b in bad:
            with self.assertRaises(usage.UsageError, msg=repr(b)):
                usage.clean_push(b, now)

    def test_item_values_stale_expired_missing(self):
        now = time.mktime((2026, 11, 4, 12, 0, 0, 0, 0, 0))
        push = {"pushed": now - 60, "budgets": usage.clean_push(self.good(now), now)}
        it = usage.mistral_item(push, now)
        self.assertTrue(it["ok"])
        v = next(w for w in it["windows"] if w["label"] == "Vibe Monat")
        self.assertEqual(v["left_pct"], 99.9)
        self.assertEqual(v["detail"], "0,18 $ von 300 $ verbraucht")                        # entspricht der Anzeige auf der Mistral-Seite
        self.assertEqual(next(w for w in it["windows"] if w["label"] == "API Monat")["detail"], "0,05 $ von 30 $ verbraucht")
        self.assertFalse(it["stale"])
        self.assertTrue(usage.mistral_item({"pushed": now - 40 * 3600, "budgets": push["budgets"]}, now)["stale"])
        gone = usage.mistral_item(push, now + 40 * 86400)                                     # Reset ist vorbei
        self.assertFalse(gone["ok"])
        self.assertIn("abgelaufenen Monat", gone["error"])
        self.assertIn("Lesezeichen", usage.mistral_item(None, now)["error"])

    def test_save_load_roundtrip_and_permissions(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertIsNone(usage.load_push(d))
            now = time.time()
            usage.save_push(d, usage.clean_push(self.good(now), now), now)
            self.assertEqual(usage.load_push(d)["budgets"]["vibe"]["budget"], 300.0)
            self.assertEqual(os.stat(Path(d) / usage.PUSH_FILE).st_mode & 0o077, 0)
            Path(d, usage.PUSH_FILE).write_text("{kaputt")
            self.assertIsNone(usage.load_push(d))

    def test_app_push_flow(self):
        with tempfile.TemporaryDirectory() as d:
            cfg = server.load_config(None)
            cfg["data_dir"] = d
            a = server.App(cfg, False, {"gitlab_token": "x"}, Path("/nonexistent/c.json"))
            with self.assertRaises(server.UserError):                                           # ausgeschaltet: wird nicht gespeichert
                a.usage_push(self.good(0))
            self.assertIsNone(usage.load_push(d))
            cfg["usage"] = {"mistral": True}
            a = server.App(cfg, False, {"gitlab_token": "x"}, Path("/nonexistent/c.json"))
            v = a.usage_view()
            self.assertFalse(v["items"][0]["ok"])                                               # vor dem ersten Klick: klare Anleitung
            with self.assertRaises(server.UserError):
                a.usage_push({"vibe": {"pct": "x"}})
            now = time.time()
            r = a.usage_push({"vibe": {"pct": 0.06, "budget": 300, "cur": "USD", "reset": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now + 20 * 86400))}})
            self.assertTrue(r["ok"] and r["item"]["ok"])
            self.assertEqual([i["id"] for i in a.usage_view()["items"]], ["mistral"])
            self.assertTrue(a.usage_view()["items"][0]["ok"])
            self.assertEqual(a.overview()["usage_providers"], ["mistral"])
            raw = (Path(d) / usage.PUSH_FILE).read_text()
            self.assertNotIn("cookie", raw.lower())


class Settings(unittest.TestCase):
    def test_save_and_view(self):
        cfg, err = settings.build_config({"projects": []}, {"usage": {"claude": True, "codex": False, "claude_file": " /x/c.json ", "cache_seconds": "60"}})
        self.assertEqual(err, {}, err)
        self.assertEqual((cfg["usage"]["claude"], cfg["usage"]["codex"], cfg["usage"]["claude_file"], cfg["usage"]["cache_seconds"]), (True, False, "/x/c.json", 60))
        v = settings.view(cfg, "/x/config.json")
        self.assertTrue(v["usage"]["claude"])
        self.assertFalse(v["usage"]["codex"])
        cfg, err = settings.build_config({"projects": []}, {"usage": {"mistral": True}})
        self.assertTrue(cfg["usage"]["mistral"])
        self.assertIn("__ORIGIN__", settings.view(cfg, "/x/config.json")["usage"]["bookmarklet_src"])
        _, err = settings.build_config({"projects": []}, {"usage": {"cache_seconds": "5"}})
        self.assertIn("usage.cache_seconds", err)
        # Das Token selbst taucht nirgends in Config oder Ansicht auf
        self.assertNotIn("token", json.dumps(v["usage"]).lower())


if __name__ == "__main__":
    unittest.main()
