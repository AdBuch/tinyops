"""Fokus-Zeit und Zeitentwürfe (0.19) mit simulierter Zeit. Gebucht wird seit 0.34 nur noch über BCS (test_v29)."""
import os
import sys
import tempfile
import time
import unittest
from datetime import date, datetime, time as dtime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import server  # noqa: E402
import settings  # noqa: E402
import timesheet  # noqa: E402

T0 = datetime(2026, 11, 5, 9, 0).timestamp()      # Donnerstag 09:00 lokal
D = "2026-11-05"


class Book(unittest.TestCase):
    def setUp(self):
        self.tb = timesheet.TimeBook(Path(tempfile.mkdtemp()) / "t.db")

    def test_round(self):
        r = timesheet.round_minutes
        self.assertEqual([r(s * 60) for s in (0, 4, 5, 7, 8, 22, 23, 50, 52, 53)], [0, 0, 15, 15, 15, 15, 30, 45, 45, 60])
        self.assertEqual(r(10 * 60, unit=5, minimum=0), 10)

    def test_start_switch_stop(self):
        tb = self.tb
        tb.start("A-1", "A", now=T0)
        tb.ping(T0 + 600)
        tb.start("B-1", "B", now=T0 + 900)            # Wechsel: A endet jetzt
        tb.stop(T0 + 1500)
        t = tb.totals(D, T0 + 3600)
        self.assertEqual((t["A-1"]["secs"], t["B-1"]["secs"]), (900, 600))
        self.assertIsNone(tb.current())
        self.assertEqual(tb.gaps(D), [])

    def test_idle_becomes_gap_not_time(self):
        tb = self.tb
        tb.start("A-1", "A", now=T0)
        tb.ping(T0 + 300, idle=15)
        tb.ping(T0 + 300 + 20 * 60, idle=15)          # 20 min ohne Lebenszeichen
        tb.ping(T0 + 300 + 25 * 60, idle=15)
        t = tb.totals(D, T0 + 300 + 25 * 60, idle=15)
        self.assertEqual(t["A-1"]["secs"], 300 + 5 * 60)
        g = tb.gaps(D)
        self.assertEqual((len(g), g[0]["minutes"]), (1, 20))
        tb.gap_set(g[0]["id"], True)
        self.assertEqual(tb.totals(D, T0 + 300 + 25 * 60, idle=15)["A-1"]["secs"], 300 + 25 * 60)
        self.assertIsNone(tb.gap_set(g[0]["id"], True))           # nur einmal

    def test_open_segment_without_ping_counts_until_last_sign(self):
        tb = self.tb
        tb.start("A-1", "A", now=T0)
        tb.ping(T0 + 600)
        self.assertEqual(tb.totals(D, T0 + 3 * 3600, idle=15)["A-1"]["secs"], 600)       # Browser zu: nicht weiterzählen
        self.assertEqual(tb.totals(D, T0 + 700, idle=15)["A-1"]["secs"], 700)
        tb.stop(T0 + 3 * 3600, idle=15)
        self.assertEqual(len(tb.gaps(D)), 1)

    def test_midnight_split(self):
        tb = self.tb
        late = datetime(2026, 11, 5, 23, 30).timestamp()
        tb.add_segment("A-1", "A", late, late + 3600)
        self.assertEqual(tb.totals("2026-11-05")["A-1"]["secs"], 1800)
        self.assertEqual(tb.totals("2026-11-06")["A-1"]["secs"], 1800)

    def test_sync_keeps_edits(self):
        tb = self.tb
        comp = [{"ticket": "A-1", "title": "A", "project_hint": "p", "minutes": 30, "text": "A", "evidence": []}]
        tb.sync_auto(D, comp)
        did = "td-%s-A-1" % D
        tb.update(did, minutes=45, edited=1)
        tb.sync_auto(D, [dict(comp[0], minutes=60)])
        d = tb.draft(did)
        self.assertEqual((d["minutes"], d["calc_minutes"]), (45, 60))
        tb.update(did, state="gebucht")
        tb.sync_auto(D, [dict(comp[0], minutes=90)])
        self.assertEqual(tb.draft(did)["calc_minutes"], 60)          # gebucht bleibt unverändert

    def test_compose(self):
        ev = [{"key": "A-1", "text": "Station Prüfen", "ts": T0 + 100, "kind": "phase"}, {"key": "A-1", "text": "Test für 429", "ts": T0 + 200, "kind": "check"}]
        acc = [{"key": "A-1", "label": "1:feature/a", "sha": "abcdef123456", "ts": T0}]
        c = timesheet.compose(D, {"A-1": {"secs": 50 * 60, "title": "A"}}, {"A-1": {"title": "Retry", "project_hint": "dlp-core"}}, ev, acc)
        self.assertEqual(c[0]["minutes"], 45)
        self.assertEqual(c[0]["text"], "Retry: Test für 429")
        self.assertIn("Station Prüfen 09:01", c[0]["evidence"])
        self.assertIn("Abnahme 1:feature/a @ abcdef12", c[0]["evidence"])


class AppTime(unittest.TestCase):
    def app(self, **time_cfg):
        os.environ["TINYOPS_HOME"] = tempfile.mkdtemp()
        cfg = server.load_config(None)
        cfg["data_dir"] = tempfile.mkdtemp()
        cfg["time"] = dict(time_cfg)
        a = server.App(cfg, True, {}, Path("/nonexistent/c.json"))
        a.overview()
        return a

    def seed(self, a, key="DLP-101", minutes=50):
        # Fester Tag in der Vergangenheit (gestern ab 09:00): unabhängig von der Uhrzeit, zu der die Tests laufen (CI auch um 00:01)
        self._slot = getattr(self, "_slot", 0) + 1
        y = date.fromtimestamp(time.time()) - timedelta(days=1)
        start = datetime.combine(y, dtime(9, 0)).timestamp() + self._slot * 7200
        a.timebook.add_segment(key, "t", start, start + minutes * 60)
        d = a.time_day(y.isoformat())
        return next(x for x in d["drafts"] if x["ticket"] == key)

    def test_pin_starts_and_switch_stops(self):
        a = self.app()
        a.flow_action("pin", {"id": "DLP-101"})
        self.assertEqual(a.time_state()["running"]["key"], "DLP-101")
        a.flow_action("pin", {"id": "DLP-102"})
        self.assertEqual(a.time_state()["running"]["key"], "DLP-102")
        a.time_action("pause", {})
        self.assertIsNone(a.time_state()["running"])
        a.time_action("resume", {})
        self.assertEqual(a.time_state()["running"]["key"], "DLP-102")
        a.flow_action("pin", {"id": None})
        self.assertIsNone(a.time_state()["running"])
        self.assertIn("time", a.overview())

    def test_confirm_then_booked_is_fixed(self):
        a = self.app()
        dr = self.seed(a)
        self.assertEqual(dr["minutes"], 45)
        self.assertEqual(dr["state"], "offen")
        self.assertEqual(a.time_action("confirm", {"id": dr["id"]})["state"], "bestätigt")
        a.timebook.update(dr["id"], state="gebucht")                       # gebucht wird in BCS (test_v29)
        with self.assertRaises(server.UserError) as cm:
            a.time_action("edit", {"id": dr["id"], "minutes": 60})            # gebucht ist fest
        self.assertIn("BCS", str(cm.exception))
        acts = [r["action"] for r in a.audit_log.rows()]
        self.assertIn("time.confirm", acts)
        with self.assertRaises(server.UserError):
            a.time_action("send", {"id": dr["id"]})                          # 0.34: kein Senden an einen MCP mehr

    def test_edit_merge_discard_and_rules(self):
        a = self.app()
        d1 = self.seed(a, "DLP-101", 20)
        d2 = self.seed(a, "DLP-102", 35)
        a.time_action("edit", {"id": d1["id"], "minutes": 30, "text": "Retry, Review"})
        x = a.timebook.draft(d1["id"])
        self.assertEqual((x["minutes"], x["edited"]), (30, 1))
        a.time_action("merge", {"id": d2["id"], "into": d1["id"]})
        self.assertEqual(a.timebook.draft(d1["id"])["minutes"], 60)
        self.assertEqual(a.timebook.draft(d2["id"])["state"], "verworfen")
        a.time_action("restore", {"id": d2["id"]})
        a.time_action("discard", {"id": d2["id"]})
        with self.assertRaises(server.UserError):
            a.time_action("edit", {"id": d1["id"], "minutes": 5000})
        ref = a.time_action("add", {"date": timesheet.today(), "ticket": "1:feature/x", "minutes": 15, "text": ""})["id"]
        with self.assertRaises(server.UserError) as cm:
            a.time_action("confirm", {"id": ref})
        self.assertIn("Ticket", str(cm.exception))

    def test_settings_drop_projectron_keys(self):
        old = {"gitlab": {"url": "https://g.example"}, "time": {"mcp_url": "http://127.0.0.1:3100/x", "send_on_confirm": True, "allow_remote": False}}
        cfg, err = settings.build_config(old, {"time": {"round_minutes": "10", "idle_minutes": "20"}})
        self.assertEqual(err, {})
        self.assertEqual((cfg["time"]["round_minutes"], cfg["time"]["idle_minutes"]), (10, 20))
        for k in ("mcp_url", "send_on_confirm", "allow_remote"):
            self.assertNotIn(k, cfg["time"])                                # E1: nur noch BCS
        _, err = settings.build_config({}, {"gitlab": {"url": "https://g.example"}, "time": {"round_minutes": "0"}})
        self.assertIn("time.round_minutes", err)
        self.assertNotIn("mcp_token", settings.SECRET_FIELDS)
        self.assertFalse(hasattr(settings, "test_mcp"))

if __name__ == "__main__":
    unittest.main()
