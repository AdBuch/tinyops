"""0.22: Zeitmarke und Tempo beim KI-Kontingent, UI-Nutzung lokal erfassen und auswerten."""
import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import server  # noqa: E402
import settings  # noqa: E402
import usage  # noqa: E402
import ux  # noqa: E402


class Pace(unittest.TestCase):
    def test_same_percent_means_different_things(self):
        now = 1_800_000_000
        early = usage._win("5 h", 20, now + 4.75 * 3600, now)       # 20 % nach 15 min
        late = usage._win("5 h", 20, now + 0.5 * 3600, now)         # 20 % in den letzten 30 min
        self.assertEqual((early["time_left_pct"], late["time_left_pct"]), (95.0, 10.0))
        self.assertGreater(early["projected_pct"], 100)              # zu schnell
        self.assertLess(early["empty_in_secs"], early["secs_left"])
        self.assertEqual(late["projected_pct"], 22)                  # bleibt viel übrig: mehr nutzen
        self.assertGreater(late["ahead"], 50)
        self.assertNotIn("empty_in_secs", late)

    def test_edges(self):
        now = 1_800_000_000
        w = usage._win("5 h", 5, now + 5 * 3600 - 60, now)           # gerade begonnen
        self.assertIsNone(w["projected_pct"])
        self.assertNotIn("time_left_pct", usage._win("Sonstwas", 5, now + 60, now))      # unbekannte Fensterlänge: keine Marke
        self.assertNotIn("time_left_pct", usage._win("5 h", 5, None, now))
        c = usage.parse_codex({"rate_limit": {"primary_window": {"used_percent": 50, "limit_window_seconds": 18000, "reset_after_seconds": 9000}}}, now)
        self.assertEqual(c[0]["time_left_pct"], 50.0)

    def test_month_window(self):
        from datetime import datetime, timezone
        r = datetime(2026, 12, 1, tzinfo=timezone.utc).timestamp()
        self.assertEqual(r - usage.month_before(r), 30 * 86400)
        r = datetime(2026, 3, 31, tzinfo=timezone.utc).timestamp()
        self.assertEqual(datetime.fromtimestamp(usage.month_before(r), timezone.utc).day, 28)
        now = time.time()
        m = usage.mistral_item({"pushed": now, "budgets": {"vibe": {"pct": 10.0, "budget": 20.0, "cur": "EUR", "reset": now + 15 * 86400}}}, now)
        self.assertIn("time_left_pct", m["windows"][0])


T0 = 1_800_000_000


def ev(k, t="", ts=0.0, v="focus", c="", x=None, y=None, e=None):
    d = {"k": k, "t": t, "ts": T0 + ts, "v": v, "c": c}
    if x is not None:
        d.update(x=x, y=y)
    if e is not None:
        d["e"] = e
    return d


class Ux(unittest.TestCase):
    def setUp(self):
        self.log = ux.UxLog(Path(tempfile.mkdtemp()) / "t.db")

    def test_store_validates_and_prunes(self):
        n = self.log.add_batch("Sess-1!", [ev("click", "button «Ok»", x=2.0, y=-1), {"k": "evil"}, "kaputt", ev("type", "input#fAdd(text)", e={"n": 5})], now=T0)
        self.assertEqual(n, 2)
        rows = self.log.events(0)
        self.assertEqual((rows[0]["sess"], rows[0]["x"], rows[0]["y"]), ("sess1", 1.0, 0.0))
        self.log.add_batch("s", [ev("click", "alt", ts=-40 * 86400)], days=30, now=T0 + 3 * 86400)   # Zeitstempel zu alt: auf jetzt gesetzt
        self.log.add_batch("s", [ev("click", "neu")], days=1, now=T0 + 10 * 86400)
        self.assertEqual([r["target"] for r in self.log.events(0)], ["neu"])
        self.assertEqual(self.log.clear(), 1)

    def test_analysis(self):
        es = [ev("env", e={"w": 1920, "h": 1080, "dpr": 1}), ev("view", "focus", 0), ev("view", "board", 10, v="board"), ev("view", "focus", 20)]
        es += [ev("click", "button[fgo] «Schritt erledigt»", 21 + i * 30, e={"h": 2500}, x=0.5, y=0.3) for i in range(4)]
        es += [ev("dead", "span.chip", 30 + i * 0.4, x=0.2, y=0.2) for i in range(3)]                   # tote Klicks und Wutklick
        es += [ev("dialog", "tkDlg", 200, e={"s": "open"}), ev("click", "button#tkClose «Schliessen»", 203, c="tkDlg"), ev("dialog", "tkDlg", 203, e={"s": "close"})]
        es += [ev("dialog", "tkDlg", 300, e={"s": "open"}), ev("click", "button#tk-copy «Text kopieren»", 305, c="tkDlg"), ev("dialog", "tkDlg", 306, e={"s": "close"})]
        es += [ev("key", "j", 310), ev("key", "j", 311), ev("type", "input#fAdd(text)", 312, e={"n": 12})]
        es += [ev("move", "", 320, e={"d": 3.5, "g": {"0,0": 10, "11,7": 2}}), ev("error", "TypeError: x is undefined (Zeile 9)", 321)]
        self.log.add_batch("a", es, now=T0)
        a = ux.analyse(self.log.events(0))
        self.assertEqual(a["sessions"], 1)
        self.assertEqual(a["actions"]["button[fgo] «Schritt erledigt»"]["n"], 4)
        self.assertEqual(ux._median(a["actions"]["button[fgo] «Schritt erledigt»"]["hes"]), 2500)
        self.assertEqual(len(a["dead"]), 3)
        self.assertEqual(a["rage"]["span.chip"], 1)
        self.assertEqual((a["dialogs"]["tkDlg"]["open"], a["dialogs"]["tkDlg"]["abandoned"]), (2, 1))   # Schliessen zählt nicht als Aktion
        self.assertEqual(a["transitions"]["focus → board"], 1)
        self.assertEqual(a["keys"]["j"], 2)
        self.assertEqual(a["typed"]["input#fAdd(text)"], 12)
        md = ux.report_md(a, 7, "0.22.0")
        for part in ("## Auffällig", "tote Klicks auf «span.chip»", "Wutklick", "gezögert", "## Maus", "|@", "JavaScript-Fehler", "1920×1080"):
            self.assertIn(part, md)
        self.assertEqual(len(ux.heat({"0,0": 10, "11,7": 2})), 8)

    def test_scrubs_tokens(self):
        self.log.add_batch("s", [ev("error", "fetch failed glpat-abcdefghijklmnopqrstuv")], now=T0)
        self.assertNotIn("glpat-", json.dumps(self.log.events(0)))


class AppUx(unittest.TestCase):
    def app(self, **c):
        os.environ["TINYOPS_HOME"] = tempfile.mkdtemp()
        cfg = server.load_config(None)
        cfg["data_dir"] = tempfile.mkdtemp()
        cfg.update(c)
        a = server.App(cfg, True, {}, Path("/nonexistent/c.json"))
        a.overview()
        return a

    def test_routes_and_switch(self):
        a = self.app()
        self.assertTrue(a.overview()["ux"]["enabled"])
        self.assertEqual(a.ux_events({"sess": "x", "events": [{"k": "click", "t": "button «Ok»", "ts": time.time(), "v": "focus"}]})["n"], 1)
        r = a.ux_report(7)
        self.assertEqual(r["events"], 1)
        self.assertIn("# tinyops UI-Nutzung", r["text"])
        self.assertEqual(a.ux_clear()["deleted"], 1)
        self.assertEqual(a.audit_log.rows(action="ux.clear")[0]["detail"]["events"], 1)
        off = self.app(ux={"enabled": False})
        self.assertTrue(off.ux_events({"sess": "x", "events": [{"k": "click"}]})["off"])
        self.assertEqual(off.uxlog.count()["events"], 0)

    def test_settings(self):
        new, err = settings.build_config({}, {"gitlab": {"url": "https://g.example"}, "ux": {"enabled": False, "days": "14"}})
        self.assertEqual((err, new["ux"]), ({}, {"enabled": False, "days": 14}))
        _, err = settings.build_config({}, {"gitlab": {"url": "https://g.example"}, "ux": {"days": "0"}})
        self.assertIn("ux.days", err)

    def test_ui_never_reads_field_values(self):
        html = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
        block = html[html.index("// ------------------------------------------------ UI-Nutzung (0.22)"):]
        block = block[:block.index("</script>")]
        self.assertNotIn(".value", block)                 # der Tracker liest nie, was in Feldern steht
        self.assertIn("keepalive", block)


if __name__ == "__main__":
    unittest.main()
