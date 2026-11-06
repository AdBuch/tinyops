"""Fokus-Zeit, Zeitentwürfe und Übergabe an den MCP (0.19) mit simulierter Zeit und einem Fake-MCP."""
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.request
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import server  # noqa: E402
import settings  # noqa: E402
import timesheet  # noqa: E402
from test_github import free_port, wait  # noqa: E402

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

    def test_compose_and_payload(self):
        ev = [{"key": "A-1", "text": "Station Prüfen", "ts": T0 + 100, "kind": "phase"}, {"key": "A-1", "text": "Test für 429", "ts": T0 + 200, "kind": "check"}]
        acc = [{"key": "A-1", "label": "1:feature/a", "sha": "abcdef123456", "ts": T0}]
        c = timesheet.compose(D, {"A-1": {"secs": 50 * 60, "title": "A"}}, {"A-1": {"title": "Retry", "project_hint": "dlp-core"}}, ev, acc)
        self.assertEqual(c[0]["minutes"], 45)
        self.assertEqual(c[0]["text"], "Retry: Test für 429")
        self.assertIn("Station Prüfen 09:01", c[0]["evidence"])
        self.assertIn("Abnahme 1:feature/a @ abcdef12", c[0]["evidence"])
        p = timesheet.payload({"id": "td-x", "date": D, "ticket": "A-1", "project_hint": "p", "minutes": 45, "text": "t", "evidence": []})
        self.assertEqual(p["schema"], "tinyops.time-entry/1")
        self.assertEqual(p["idempotency_key"], timesheet.payload(dict(p))["idempotency_key"])
        self.assertNotEqual(p["idempotency_key"], timesheet.payload(dict(p, minutes=60))["idempotency_key"])


class AppTime(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.port = free_port()
        cls.proc = subprocess.Popen([sys.executable, str(ROOT / "tests" / "mock_mcp.py"), str(cls.port)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        wait(cls.port)
        cls.url = "http://127.0.0.1:%d/time-entries" % cls.port

    @classmethod
    def tearDownClass(cls):
        cls.proc.terminate()
        cls.proc.wait(5)

    def mlog(self):
        return json.loads(urllib.request.urlopen("http://127.0.0.1:%d/_log" % self.port).read())

    def app(self, **time_cfg):
        os.environ["TINYOPS_HOME"] = tempfile.mkdtemp()
        cfg = server.load_config(None)
        cfg["data_dir"] = tempfile.mkdtemp()
        cfg["time"] = dict(time_cfg)
        a = server.App(cfg, True, {"mcp_token": "mcptoken"} if time_cfg.get("mcp_url") else {}, Path("/nonexistent/c.json"))
        a.overview()
        return a

    def seed(self, a, key="DLP-101", minutes=50):
        now = time.time()
        a.timebook.add_segment(key, "t", now - minutes * 60 - 5, now - 5)
        d = a.time_day()
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

    def test_confirm_without_mcp_then_pull_and_result(self):
        a = self.app()
        dr = self.seed(a)
        self.assertEqual(dr["minutes"], 45)
        self.assertEqual(dr["state"], "offen")
        self.assertEqual(a.time_export()["drafts"], [])                 # nichts ohne Bestätigung
        self.assertEqual(a.time_action("confirm", {"id": dr["id"]})["state"], "bestätigt")
        ex = a.time_export()["drafts"]
        self.assertEqual([(x["id"], x["minutes"], x["state"]) for x in ex], [(dr["id"], 45, "bestätigt")])
        self.assertIn("idempotency_key", ex[0])
        a.time_result({"id": dr["id"], "status": "booked", "reference": "PRJ-9"})
        self.assertEqual(a.timebook.draft(dr["id"])["state"], "gebucht")
        self.assertTrue(a.time_result({"id": dr["id"], "status": "booked"})["already"])
        with self.assertRaises(server.UserError):
            a.time_action("edit", {"id": dr["id"], "minutes": 60})            # gebucht ist fest
        acts = [r["action"] for r in a.audit_log.rows()]
        self.assertIn("time.confirm", acts)
        self.assertIn("time.result", acts)

    def test_send_booked_once_and_idempotent(self):
        a = self.app(mcp_url=self.url)
        dr = self.seed(a, "DLP-102")
        before = len([x for x in self.mlog()["log"] if x["method"] == "POST"])
        r = a.time_action("confirm", {"id": dr["id"]})
        self.assertEqual(r["state"], "gebucht")
        self.assertTrue(r["reference"].startswith("PRJ-"))
        r2 = a.time_action("send", {"id": dr["id"]})
        self.assertTrue(r2["already"])                                     # tinyops sendet nicht doppelt
        posts = [x for x in self.mlog()["log"] if x["method"] == "POST"][before:]
        self.assertEqual(len(posts), 1)
        self.assertEqual(posts[0]["schema"], "tinyops.time-entry/1")
        # zweite Instanz sendet denselben Inhalt nochmals: gleicher Schlüssel, der MCP bucht einmal
        body = timesheet.payload(a.timebook.draft(dr["id"]))
        req = urllib.request.Request(self.url, data=json.dumps(body).encode(), method="POST",
                                     headers={"Authorization": "Bearer mcptoken", "Idempotency-Key": body["idempotency_key"], "Content-Type": "application/json"})
        self.assertEqual(json.loads(urllib.request.urlopen(req).read())["reference"], r["reference"])

    def test_failures_stay_visible(self):
        a = self.app(mcp_url=self.url)
        for ticket, state in (("REJ-1", "abgelehnt"), ("BAD-1", "fehlgeschlagen"), ("ERR-1", "fehlgeschlagen")):
            did = a.time_action("add", {"date": timesheet.today(), "ticket": ticket, "minutes": 30, "text": "x"})["id"]
            r = a.time_action("confirm", {"id": did})
            self.assertEqual(r["state"], state, (ticket, r))
            self.assertNotEqual(a.timebook.draft(did)["state"], "gebucht")
            self.assertTrue(r["message"])
        rows = [x for x in a.audit_log.rows(action="time.send")]
        self.assertTrue(all(not x["ok"] for x in rows))

    def test_unreachable_then_resend(self):
        port = free_port()
        a = self.app(mcp_url="http://127.0.0.1:%d/time-entries" % port)
        dr = self.seed(a, "DLP-103")
        r = a.time_action("confirm", {"id": dr["id"]})
        self.assertEqual(r["state"], "fehlgeschlagen")
        self.assertIn("nicht erreichbar", r["message"])
        p = subprocess.Popen([sys.executable, str(ROOT / "tests" / "mock_mcp.py"), str(port)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            wait(port)
            self.assertEqual(a.time_action("send", {"id": dr["id"]})["state"], "gebucht")
            self.assertEqual(a.timebook.draft(dr["id"])["attempts"], 2)
        finally:
            p.terminate()
            p.wait(5)

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

    def test_remote_mcp_needs_permission(self):
        a = self.app(mcp_url="http://8.8.8.8/time")
        did = a.time_action("add", {"date": timesheet.today(), "ticket": "DLP-1", "minutes": 15, "text": ""})["id"]
        a.timebook.update(did, state="bestätigt")
        with self.assertRaises(server.UserError) as cm:
            a.time_action("send", {"id": did})
        self.assertIn("eigenen Netz", str(cm.exception))

    def test_settings_and_test_is_get_only(self):
        cfg, err = settings.build_config({}, {"gitlab": {"url": "https://g.example"}, "time": {"mcp_url": self.url, "round_minutes": "10", "idle_minutes": "20"}})
        self.assertEqual(err, {})
        self.assertEqual((cfg["time"]["round_minutes"], cfg["time"]["idle_minutes"], cfg["time"]["mcp_url"]), (10, 20, self.url))
        _, err = settings.build_config({}, {"gitlab": {"url": "https://g.example"}, "time": {"mcp_url": "http://8.8.8.8/x", "round_minutes": "0"}})
        self.assertIn("time.mcp_url", err)
        self.assertIn("time.round_minutes", err)
        n = len(self.mlog()["log"])
        r = settings.test_mcp({"url": self.url, "secret": "mcptoken"}, lambda name: ("", ""))
        self.assertTrue(r["ok"], r)
        r = settings.test_mcp({"url": self.url}, lambda name: ("", ""))
        self.assertFalse(r["ok"])
        self.assertTrue(all(x["method"] == "GET" for x in self.mlog()["log"][n:]))
        self.assertIn("mcp_token", settings.SECRET_FIELDS)


if __name__ == "__main__":
    unittest.main()
