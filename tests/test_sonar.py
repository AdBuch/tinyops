"""SonarQube-Anbindung: Quality Gate pro MR und Branch (nur lesend), Einstellungen, Test, Sync."""
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import server  # noqa: E402
import settings  # noqa: E402
import sonar  # noqa: E402


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


class Describe(unittest.TestCase):
    def test_conditions_in_words(self):
        self.assertEqual(sonar.describe({"metricKey": "new_coverage", "actualValue": "61.2", "errorThreshold": "80", "comparator": "LT"}),
                         "Abdeckung neuer Code 61.2 % (mindestens 80 %)")
        self.assertEqual(sonar.describe({"metricKey": "new_vulnerabilities", "actualValue": "2", "errorThreshold": "0", "comparator": "GT"}),
                         "Neue Schwachstellen 2 (höchstens 0)")
        self.assertIn("C", sonar.describe({"metricKey": "new_security_rating", "actualValue": "3.0", "errorThreshold": "1", "comparator": "GT"}))
        self.assertIn("foo bar", sonar.describe({"metricKey": "foo_bar", "actualValue": "1", "errorThreshold": "0", "comparator": "GT"}))   # unbekannte Metrik bleibt lesbar

    def test_auth_header_is_basic_with_empty_password(self):
        import base64
        h = sonar.headers("abc")
        self.assertEqual(base64.b64decode(h["Authorization"].split()[1]).decode(), "abc:")


class WithMock(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.port = free_port()
        cls.proc = subprocess.Popen([sys.executable, str(ROOT / "tests" / "mock_sonar.py"), str(cls.port)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        wait(cls.port)
        cls.base = "http://127.0.0.1:%d" % cls.port

    @classmethod
    def tearDownClass(cls):
        cls.proc.terminate()
        cls.proc.wait(5)


class ClientTests(WithMock):
    def test_gate_states(self):
        c = sonar.Client(self.base, "sqtoken")
        self.assertEqual(c.gate("dlp-core", pr=7)["status"], "OK")
        r = c.gate("dlp-core", pr=8)
        self.assertEqual(r["status"], "ERROR")
        self.assertEqual(len(r["failed"]), 2)                    # nur die roten Bedingungen
        self.assertIn("pullRequest=8", r["url"])
        self.assertEqual(c.gate("dlp-core", branch="feature-b")["status"], "WARN")
        none = c.gate("dlp-core", pr=9)
        self.assertEqual(none["status"], "NONE")
        self.assertIn("keine Analyse", none["detail"])
        with self.assertRaises(sonar.SonarError) as cm:
            c.gate("dlp-core", branch="kaputt")
        self.assertFalse(cm.exception.auth)

    def test_wrong_token_is_auth_error(self):
        with self.assertRaises(sonar.SonarError) as cm:
            sonar.Client(self.base, "falsch").gate("dlp-core", pr=7)
        self.assertTrue(cm.exception.auth)
        self.assertNotIn("falsch", str(cm.exception))

    def test_unreachable(self):
        with self.assertRaises(sonar.SonarError):
            sonar.Client("http://127.0.0.1:%d" % free_port(), "x").gate("k", pr=1)


class ReportTests(WithMock):
    def client(self):
        return sonar.Client(self.base, "sqtoken")

    def test_links(self):
        c = self.client()
        r = c.gate("dlp-core", pr=8)
        self.assertIn("/project/issues?id=dlp-core&pullRequest=8&resolved=false", r["issues_url"])
        self.assertIn("/security_hotspots?id=dlp-core&branch=feature-b", c.hotspots_url("dlp-core", branch="feature-b"))
        self.assertEqual(c.gate("dlp-core", pr=9)["issues_url"], "")                    # ohne Analyse kein Findings-Link
        self.assertIn("dashboard?id=dlp-core&pullRequest=9", c.gate("dlp-core", pr=9)["url"])

    def test_issues_paging_limit_and_facets(self):
        iss, total, fac = self.client().issues("dlp-core", pr=8, limit=120)
        self.assertEqual((len(iss), total), (120, 251))                                  # zwei Seiten gelesen, dann abgeschnitten
        self.assertEqual(iss[0]["severity"], "BLOCKER")
        self.assertEqual(fac["severities"]["MAJOR"], 250)
        self.assertEqual(self.client().issues("dlp-core", pr=7)[1], 0)
        with self.assertRaises(sonar.SonarError):
            self.client().issues("dlp-core", branch="kaputt")

    def test_hotspots_unreadable_is_none(self):
        self.assertEqual(self.client().hotspots("dlp-core", pr=8)[1], 1)
        self.assertIsNone(self.client().hotspots("dlp-core", pr=7))

    def test_report_text(self):
        c = self.client()
        iss, total, fac = c.issues("dlp-core", pr=8, limit=30)
        txt = sonar.format_report("core, MR !8", c.gate("dlp-core", pr=8), "dlp-core", iss, total, fac, c.hotspots("dlp-core", pr=8), "https://s/x", 30)
        self.assertIn("# Sonar-Findings: core, MR !8", txt)
        self.assertIn("Quality Gate: **nicht bestanden**", txt)
        self.assertIn("Abdeckung neuer Code 61.2 %", txt)
        self.assertIn("Schwere: high 1, medium 250", txt)                              # Multi-Quality-Rule-Modus: Auswirkungen statt alter Schwere
        self.assertIn("Zeile 7 [high, Sicherheit]", txt)
        self.assertIn("### `src/Auth.java`", txt)                                       # Pfad ohne Projektschlüssel, schwerste Datei zuerst
        self.assertLess(txt.index("src/Auth.java"), txt.index("src/Repo.java"))
        self.assertIn("Es werden 30 von 251 Findings gezeigt", txt)
        self.assertIn("src/Crypto.java", txt)
        self.assertNotIn("\n\n\n\n", txt)
        auth_line = next(l for l in txt.splitlines() if "java:S2068" in l)
        self.assertTrue(auth_line.endswith("…") and "\n" not in auth_line and "  " not in auth_line)   # Meldung auf eine Zeile gekürzt
        self.assertLess(len(auth_line), 400)
        txt = sonar.format_report("x", c.gate("dlp-core", pr=7), "dlp-core", [], 0, {}, None, "", 30)
        self.assertIn("Keine offenen Findings.", txt)
        self.assertIn("Nicht lesbar", txt)


class TrendTests(WithMock):
    def client(self):
        return sonar.Client(self.base, "sqtoken")

    def test_history_parses_dates_and_skips_new_metrics_without_values(self):
        pts = self.client().history("dlp-core", pr=8, metrics=("violations", "bugs", "new_violations"))
        self.assertEqual([p["violations"] for p in pts], [12.0, 9.0, 7.0, 3.0])
        self.assertTrue(all("new_violations" not in p for p in pts))                  # Sonar liefert dafür nur Daten, keine Werte
        self.assertEqual(pts[0]["bugs"], 3.0)
        self.assertTrue(pts[0]["ts"] < pts[-1]["ts"])
        self.assertEqual(self.client().history("dlp-core", branch="gibt-es-nicht"), [])
        self.assertEqual(self.client().history("anderes", pr=8), [])
        with self.assertRaises(sonar.SonarError):
            self.client().history("dlp-core", branch="kaputt")

    def test_trend_of(self):
        t = sonar.trend_of([(1, 12.0), (2, 9.0), (3, 3.0)])
        self.assertEqual((t["first"], t["last"], t["delta"], t["points"], t["n"]), (12.0, 3.0, -9.0, [12, 9, 3], 3))
        self.assertIsNone(sonar.trend_of([(1, 5.0)]))
        self.assertIsNone(sonar.trend_of([(1, None), (2, None)]))
        self.assertEqual(len(sonar.trend_of([(i, float(i)) for i in range(100)], keep=24)["points"]), 24)

    def test_gate_values_and_mqr_labels(self):
        self.assertEqual(self.client().gate("dlp-core", pr=8)["values"]["new_coverage"], 61.2)
        self.assertEqual(sonar.describe({"metricKey": "new_software_quality_security_rating", "actualValue": "3.0", "errorThreshold": "1", "comparator": "GT"}),
                         "Sicherheit neuer Code C (höchstens A)")
        self.assertIn("Blocker-Findings", sonar.describe({"metricKey": "new_software_quality_blocker_issues", "actualValue": "2", "errorThreshold": "0", "comparator": "GT"}))

    def test_impact_prefers_mqr_and_falls_back(self):
        self.assertEqual(sonar.impact({"severity": "MAJOR", "type": "BUG", "impacts": [{"softwareQuality": "RELIABILITY", "severity": "MEDIUM"}, {"softwareQuality": "SECURITY", "severity": "HIGH"}]}), ("HIGH", "SECURITY"))
        self.assertEqual(sonar.impact({"severity": "MAJOR", "type": "BUG"}), ("MAJOR", "BUG"))

    def test_report_has_history_table(self):
        c = self.client()
        pts = c.history("dlp-core", pr=8, metrics=tuple(k for k, _ in sonar.HIST_COLS))
        txt = sonar.format_report("x", c.gate("dlp-core", pr=7), "dlp-core", [], 0, {}, None, "", 30, {"source": "Sonar-Verlauf", "cols": sonar.HIST_COLS, "rows": pts})
        self.assertIn("## Verlauf (Sonar-Verlauf)", txt)
        self.assertIn("| Stand | Findings | Bugs | Schwachstellen | Smells | Abdeckung % |", txt)
        self.assertIn("Findings: 12 → 3 (weniger)", txt)


class SettingsTests(WithMock):
    def stored(self, tok=""):
        return lambda name: (tok, "Test") if name == "sonar_token" else ("", "")

    def test_good_and_bad_key(self):
        r = settings.test_sonar({"url": self.base, "secret": "sqtoken", "projects": [{"id": 1, "name": "core", "sonar_key": "dlp-core"}]}, self.stored())
        self.assertTrue(r["ok"], r)
        st = {s["id"]: s for s in r["steps"]}
        self.assertEqual(st["keys"]["status"], "ok")
        self.assertEqual(st["prs"]["status"], "ok")
        self.assertIn("dlp-core: 2 analysiert (zuletzt !8)", st["prs"]["detail"])
        r = settings.test_sonar({"url": self.base, "secret": "sqtoken", "projects": [{"id": 1, "name": "core", "sonar_key": "gibt-es-nicht"}]}, self.stored())
        keys = next(s for s in r["steps"] if s["id"] == "keys")
        self.assertEqual(keys["status"], "warn")
        self.assertIn("gibt-es-nicht", keys["detail"])

    def test_wrong_token_and_missing_token(self):
        r = settings.test_sonar({"url": self.base, "secret": "falsch"}, self.stored())
        self.assertFalse(r["ok"])
        self.assertNotIn("falsch", json.dumps(r))
        r = settings.test_sonar({"url": self.base}, self.stored())
        self.assertFalse(r["ok"])
        self.assertIn("Kein Token", json.dumps(r, ensure_ascii=False))
        self.assertTrue(settings.test_sonar({"url": self.base}, self.stored("sqtoken"))["steps"])   # gespeicherter Token wird genommen

    def test_no_url_and_no_keys_hint(self):
        self.assertFalse(settings.test_sonar({"url": ""}, self.stored())["ok"])
        r = settings.test_sonar({"url": self.base, "secret": "sqtoken", "projects": [{"id": 1, "name": "x"}]}, self.stored())
        self.assertEqual(next(s for s in r["steps"] if s["id"] == "keys")["status"], "warn")

    def test_save_validation_and_view(self):
        cur = {"projects": [{"id": 1, "name": "core"}], "sonar": {}}
        cfg, err = settings.build_config(cur, {"projects": [{"id": 1, "name": "core", "sonar_key": "dlp-core"}],
                                               "sonar": {"enabled": True, "url": self.base + "/", "cache_seconds": "120", "max_items": "10"}})
        self.assertEqual(err, {}, err)
        self.assertEqual(cfg["projects"][0]["sonar_key"], "dlp-core")
        self.assertEqual((cfg["sonar"]["url"], cfg["sonar"]["cache_seconds"], cfg["sonar"]["max_items"]), (self.base, 120, 10))
        v = settings.view(cfg, "/x/config.json")
        self.assertEqual(v["projects"][0]["sonar_key"], "dlp-core")
        self.assertTrue(v["sonar"]["enabled"])
        _, err = settings.build_config(cur, {"sonar": {"enabled": True, "url": ""}})
        self.assertIn("sonar.url", err)
        _, err = settings.build_config(cur, {"sonar": {"enabled": False, "url": "kaputt"}})
        self.assertIn("sonar.url", err)
        _, err = settings.build_config(cur, {"projects": [{"id": 1, "sonar_key": "a b;c"}]})
        self.assertIn("projects", err)
        cfg, _ = settings.build_config(cfg, {"projects": [{"id": 1, "name": "core", "sonar_key": ""}]})
        self.assertNotIn("sonar_key", cfg["projects"][0])                       # leer = Schlüssel entfernen
        self.assertIn("sonar_token", settings.SECRET_FIELDS)


class SyncTests(WithMock):
    def app(self, **sc):
        self.tmp = tempfile.TemporaryDirectory()
        cfg = server.load_config(None)
        cfg["data_dir"] = self.tmp.name
        cfg["sonar"] = dict({"enabled": True, "url": self.base, "cache_seconds": 300, "max_items": 40}, **sc)
        cfg["projects"] = [{"id": 1, "name": "dlp-core", "sonar_key": "dlp-core"}, {"id": 2, "name": "ohne-key"}]
        a = server.App(cfg, True, {}, Path("/nonexistent/c.json"))
        a.sonar = sonar.Client(self.base, "sqtoken")      # echter Client gegen den Mock statt Demo
        a.demo = False
        return a

    def tearDown(self):
        if getattr(self, "tmp", None):
            self.tmp.cleanup()

    def test_items_get_gate_and_summary(self):
        a = self.app()
        a.client.fetch = lambda sink=None, step=None: {"me": "me", "errors": [], "assigned": [], "review": [],
            "mine": [{"kind": "mr", "iid": 7, "branch": "feature/DLP-1-a", "title": "A", "project_id": 1, "project": "dlp-core", "url": "u", "pipeline": "success", "draft": False, "age_days": 1},
                     {"kind": "mr", "iid": 8, "branch": "x", "title": "B", "project_id": 1, "project": "dlp-core", "url": "u", "pipeline": "success", "draft": False, "age_days": 1},
                     {"kind": "branch", "iid": None, "branch": "feature-b", "title": "C", "project_id": 1, "project": "dlp-core", "url": "u", "pipeline": "none", "draft": False, "age_days": 1},
                     {"kind": "branch", "iid": None, "branch": "kaputt", "title": "D", "project_id": 1, "project": "dlp-core", "url": "u", "pipeline": "none", "draft": False, "age_days": 1},
                     {"kind": "mr", "iid": 3, "branch": "y", "title": "E", "project_id": 2, "project": "ohne-key", "url": "u", "pipeline": "none", "draft": False, "age_days": 1}]}
        ov = a.overview()
        st = {i["title"]: (i.get("sonar") or {}).get("status") for i in ov["mine"]}
        self.assertEqual(st, {"A": "OK", "B": "ERROR", "C": "WARN", "D": "UNKNOWN", "E": None})   # Projekt ohne Schlüssel wird nicht gefragt
        self.assertEqual((ov["sonar"]["checked"], ov["sonar"]["red"], ov["sonar"]["warn"], ov["sonar"]["failed"]), (4, 1, 1, 1))
        b = next(c for c in ov["board"]["cards"] if c["items"] and c["items"][0]["iid"] == 8)
        self.assertEqual(b["items"][0]["sonar"], "ERROR")
        self.assertIn("Abdeckung", b["items"][0]["sonar_detail"])

    def test_trend_in_sync_from_sonar_history_and_local_fallback(self):
        a = self.app()
        items = [{"kind": "mr", "iid": n, "branch": "b%d" % n, "title": "T%d" % n, "project_id": 1, "project": "dlp-core", "url": "u", "pipeline": "none", "draft": False, "age_days": 1} for n in (7, 8)]
        items.append({"kind": "branch", "iid": None, "branch": "feature-b", "title": "B", "project_id": 1, "project": "dlp-core", "url": "u", "pipeline": "none", "draft": False, "age_days": 1})
        a.client.fetch = lambda sink=None, step=None: {"me": "me", "errors": [], "assigned": [], "review": [], "mine": [dict(i) for i in items]}
        ov = a.overview()
        by = {i["title"]: i["sonar"] for i in ov["mine"]}
        self.assertEqual(by["T8"]["trend"]["points"], [12, 9, 7, 3])                    # aus Sonars Verlauf
        self.assertEqual((by["T8"]["trend"]["delta"], by["T8"]["trend"]["source"]), (-9.0, "Sonar-Verlauf"))
        self.assertIsNone(by["T7"].get("trend"))                                         # nur ein Punkt: kein Trend
        card = next(c for c in ov["board"]["cards"] if any(x["iid"] == 8 for x in c["items"]))
        self.assertEqual(next(x for x in card["items"] if x["iid"] == 8)["sonar_trend"]["last"], 3.0)
        # Branch feature-b: Sonar kennt keinen Verlauf → lokale Schnappschüsse aus den Gate-Werten, Trend ab dem zweiten, geänderten Stand
        self.assertIsNone(by["B"].get("trend"))
        scope = a._scope_key("dlp-core", None, "feature-b")
        t0 = time.time() + 100
        a.store.snap_add(scope, {"new_violations": 5.0}, ts=t0)
        a.store.snap_add(scope, {"new_violations": 5.0}, ts=t0 + 10)                      # unverändert: nicht doppelt gespeichert
        a.store.snap_add(scope, {"new_violations": 2.0}, ts=t0 + 20)
        self.assertEqual(len(a.store.snap_rows(scope)), 3)                                # inkl. dem Stand aus dem Abgleich (new_duplicated_lines_density)
        t = a._sonar_trend("dlp-core", None, "feature-b", {"values": {}})
        self.assertEqual((t["source"], t["points"], t["delta"]), ("lokal beobachtet", [5, 2], -3.0))

    def test_report_via_app_is_read_only_and_clear_errors(self):
        import urllib.request
        a = self.app(report_max=50)
        r = a.sonar_report(1, iid=8)
        self.assertEqual((r["issues"], r["total"], r["truncated"], r["hotspots"]), (50, 251, True, 1))
        self.assertIn("MR !8", r["text"])
        self.assertIn("## Verlauf (Sonar-Verlauf)", r["text"])
        self.assertIn("dlp-core, MR !8", r["text"])
        a.sonar_report(1, branch="feature-b")
        for bad, msg in (({"project_id": 2, "iid": 3}, "kein Sonar-Schlüssel"), ({"project_id": 1}, "MR oder Branch")):
            with self.assertRaises(server.UserError) as cm:
                a.sonar_report(bad["project_id"], bad.get("iid"))
            self.assertIn(msg, str(cm.exception))
        with self.assertRaises(server.UserError):
            a.sonar_report(1, branch="kaputt")
        a.sonar = None
        with self.assertRaises(server.UserError):
            a.sonar_report(1, iid=8)
        calls = json.load(urllib.request.urlopen(self.base + "/_calls"))
        self.assertTrue(all(c.startswith("/api/") for c in calls))

    def test_wrong_token_aborts_with_clear_error(self):
        a = self.app()
        a.sonar = sonar.Client(self.base, "falsch")
        ov = a.overview()
        self.assertFalse(ov["sonar"]["ok"])
        self.assertTrue(any("Sonar" in e for e in ov["errors"]))
        self.assertTrue(all("sonar" not in i for i in ov["mine"]))

    def test_cache_limit_and_off_by_default(self):
        import urllib.request
        a = self.app(max_items=2)
        a.client.fetch = lambda sink=None, step=None: {"me": "me", "errors": [], "assigned": [], "review": [],
            "mine": [{"kind": "mr", "iid": n, "branch": "b%d" % n, "title": "T%d" % n, "project_id": 1, "project": "dlp-core", "url": "u", "pipeline": "none", "draft": False, "age_days": 1} for n in (7, 8, 9)]}
        calls = lambda: len([c for c in json.load(urllib.request.urlopen(self.base + "/_calls")) if "qualitygates" in c])
        before = calls()
        ov = a.overview()
        self.assertEqual(ov["sonar"]["skipped"], 1)
        self.assertEqual(calls() - before, 2)
        a.cache_t = 0.0
        a.overview()
        self.assertEqual(calls() - before, 2)                    # zweiter Abgleich: aus dem Zwischenspeicher
        with tempfile.TemporaryDirectory() as d:
            cfg = server.load_config(None)
            cfg["data_dir"] = d
            off = server.App(cfg, False, {"gitlab_token": "x"}, Path("/nonexistent/c.json"))
            self.assertIsNone(off.sonar)                          # ohne Einschalten gibt es keine Sonar-Anfragen
            cfg["sonar"] = {"enabled": True, "url": self.base}
            self.assertTrue(any("Sonar-Token" in p for p in server.App(cfg, False, {"gitlab_token": "x"}, Path("/nonexistent/c.json")).problems))

    def test_demo_shows_all_states(self):
        with tempfile.TemporaryDirectory() as d:
            cfg = server.load_config(None)
            cfg["data_dir"] = d
            ov = server.App(cfg, True, {}, Path("/nonexistent/c.json")).overview()
            seen = {(i.get("sonar") or {}).get("status") for i in ov["mine"] + ov["review"] + ov["assigned"]}
            self.assertTrue({"OK", "ERROR"} <= seen, seen)


class Preflight(WithMock):
    def test_preflight_includes_sonar(self):
        gp = free_port()
        g = subprocess.Popen([sys.executable, str(ROOT / "tests" / "mock_gitlab.py"), str(gp)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            wait(gp)
            with tempfile.TemporaryDirectory() as tmp:
                cfg = Path(tmp, "config.json")
                cfg.write_text(json.dumps({"gitlab_url": "http://127.0.0.1:%d" % gp, "data_dir": str(Path(tmp, "data")),
                                           "projects": [{"id": 1, "name": "dlp-core", "sonar_key": "dlp-core"}],
                                           "sonar": {"enabled": True, "url": self.base}}))
                env = {k: v for k, v in os.environ.items() if not k.startswith(("TINYOPS_", "GITLAB_TOKEN"))}
                env.update(TINYOPS_HOME=tmp, TINYOPS_GITLAB_TOKEN="secret", TINYOPS_SONAR_TOKEN="sqtoken")
                r = subprocess.run([sys.executable, str(ROOT / "server.py"), "--preflight", "--config", str(cfg)], env=env, capture_output=True, text=True, timeout=60)
                self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
                self.assertIn("Sonar", r.stdout)
                self.assertIn("Quality Gates geprüft", r.stdout)
                self.assertNotIn("sqtoken", r.stdout)
                env["TINYOPS_SONAR_TOKEN"] = ""
                r = subprocess.run([sys.executable, str(ROOT / "server.py"), "--preflight", "--config", str(cfg)], env=env, capture_output=True, text=True, timeout=60)
                self.assertEqual(r.returncode, 1)
                self.assertIn("Sonar-Token: fehlt", r.stdout)
        finally:
            g.terminate()
            g.wait(5)


if __name__ == "__main__":
    unittest.main()
