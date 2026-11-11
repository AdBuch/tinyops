"""0.23: Helpdesk-Jira (zweite Instanz, nur lesend), Fokusbereiche mit Wochenziel, Fokus-Sitzungen."""
import os
import socket
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

import focusplan  # noqa: E402
import helpdesk  # noqa: E402
import server  # noqa: E402
import settings  # noqa: E402
import timesheet  # noqa: E402


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def wait(port):
    for _ in range(100):
        try:
            urllib.request.urlopen("http://127.0.0.1:%d/rest/api/2/serverInfo" % port, timeout=1)
            return
        except OSError:
            time.sleep(.05)


def ts(y, mo, d, h, mi=0):
    return datetime(y, mo, d, h, mi).timestamp()


class HelpdeskMock(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.port = free_port()
        cls.proc = subprocess.Popen([sys.executable, str(ROOT / "tests" / "mock_jira.py"), str(cls.port), "8.5.1"],
                                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        wait(cls.port)
        cls.url = "http://127.0.0.1:%d" % cls.port

    @classmethod
    def tearDownClass(cls):
        cls.proc.terminate()
        cls.proc.wait(5)

    def hc(self, **kw):
        return dict(helpdesk.DEFAULTS, enabled=True, url=self.url, username="jira-user",
                    assigned_jql="project = SD AND assignee = currentUser()", queue_jql="project = SD AND assignee is EMPTY", **kw)

    def test_fetch_entries_queue(self):
        hc = self.hc()
        client = server.JiraClient(dict(hc), helpdesk.auth_header(hc, {"helpdesk_password": "jpass"}), None)
        hd = helpdesk.fetch(client, hc)
        self.assertEqual([t["key"] for t in hd["assigned"]], ["SD-1", "SD-2"])
        self.assertTrue(hd["assigned"][0]["over_sla"])                      # 30 h > 24 h
        self.assertEqual(hd["assigned"][0]["url"], self.url + "/browse/SD-1")
        ent, queue = helpdesk.entries(hd, set())
        self.assertEqual(ent[0]["id"], "hd:SD-1")
        self.assertGreater(ent[0]["prio"], ent[1]["prio"])                  # High und über SLA vor Low
        self.assertIn("über dem SLA", ent[0]["next"]["why"])
        self.assertEqual(ent[1]["next"]["label"], "Antwort prüfen")         # wartet auf Kunde
        self.assertEqual(ent[0]["next"]["owner"], "me")
        self.assertEqual([(q["key"], q["new"]) for q in queue], [("SD-3", True)])
        self.assertFalse(helpdesk.entries(hd, {"SD-3"})[1][0]["new"])

    def test_auth(self):
        with self.assertRaises(ValueError):
            helpdesk.auth_header(dict(helpdesk.DEFAULTS), {"helpdesk_password": "x"})
        self.assertTrue(helpdesk.auth_header(dict(helpdesk.DEFAULTS, auth="bearer"), {"helpdesk_token": "t"}).startswith("Bearer "))
        self.assertEqual(helpdesk.secret_name({"auth": "basic"}), "helpdesk_password")

    def test_settings_test(self):
        stored = lambda n: (None, "")   # noqa: E731
        form = {"url": self.url, "auth": "basic", "username": "jira-user", "secret": "jpass",
                "assigned_jql": "project = SD AND assignee = currentUser()", "queue_jql": "project = SD AND assignee is EMPTY"}
        r = settings.test_helpdesk(form, stored)
        self.assertTrue(r["ok"], r)
        st = {s["id"]: s for s in r["steps"]}
        self.assertIn("8.5.1", st["api"]["detail"])
        self.assertIn("2 Tickets", st["assigned"]["detail"])
        self.assertIn("1 Tickets", st["queue"]["detail"])
        # Bearer auf 8.5: Hinweis, dass es keine Tokens gibt
        r = settings.test_helpdesk(dict(form, auth="bearer", secret="x"), stored)
        self.assertEqual({s["id"]: s for s in r["steps"]}["pat"]["status"], "warn")
        # falsches Passwort: 401, danach Pause statt weiterem Versuch
        r = settings.test_helpdesk(dict(form, username="other", secret="falsch"), stored)
        self.assertEqual({s["id"]: s for s in r["steps"]}["auth"]["status"], "fail")
        r = settings.test_helpdesk(dict(form, username="other", secret="falsch"), stored)
        self.assertIn("Pause", {s["id"]: s for s in r["steps"]}["auth"]["detail"])
        # ohne Queue: übersprungen
        r = settings.test_helpdesk(dict(form, queue_jql=""), stored)
        self.assertEqual({s["id"]: s for s in r["steps"]}["queue"]["status"], "skip")


class Plan(unittest.TestCase):
    def test_blocks(self):
        b = focusplan.parse_blocks("Di 13:30-17:00, do 8.00 – 10:00")
        self.assertEqual(b, [{"day": 2, "from": "13:30", "to": "17:00"}, {"day": 4, "from": "08:00", "to": "10:00"}])
        self.assertEqual(focusplan.blocks_text(b), "Di 13:30-17:00, Do 08:00-10:00")
        for bad in ("Dienstag", "Mo 10:00-09:00", "Xy 10:00-11:00", "Mo 25:00-26:00"):
            with self.assertRaises(ValueError):
                focusplan.parse_blocks(bad)
        self.assertEqual(focusplan.parse_blocks(""), [])

    def test_week_math(self):
        f = focusplan.cfg({})
        mon = ts(2026, 11, 2, 12, 30)          # Montag 12:30: 4,5 von 45 Stunden vorbei
        self.assertAlmostEqual(focusplan.worked_fraction(f, mon), 0.1)
        self.assertAlmostEqual(focusplan.worked_fraction(f, ts(2026, 11, 7, 10)), 1.0)    # Samstag: Woche ganz vorbei
        self.assertEqual(focusplan.week_start(mon), datetime(2026, 11, 2))
        segs = [{"area": "bb", "secs": 3600}, {"area": "", "secs": 7200}]
        rep = focusplan.week_report(f, segs, mon)
        bb = next(a for a in rep["areas"] if a["id"] == "bb")
        self.assertEqual(bb["target_secs"], int(.3 * 42 * 3600))
        self.assertEqual(bb["due_secs"], int(.3 * 42 * 3600 * .1))
        self.assertEqual(bb["behind_secs"], int(.3 * 42 * 3600 * .1) - 3600)
        self.assertEqual(next(a for a in rep["areas"] if a["id"] == "dev")["secs"], 7200)
        self.assertAlmostEqual(bb["share_pct"], 33.3)

    def test_blocks_now_and_next(self):
        f = focusplan.cfg({"focus": {"areas": [{"id": "bb", "name": "Berufsbildung", "target_pct": 30, "blocks": focusplan.parse_blocks("Di 13:30-17:00")}]}})
        self.assertEqual([a["id"] for a in f["areas"]], ["dev", "bb"])       # Entwicklung gibt es immer
        self.assertEqual(focusplan.current_block(f, ts(2026, 11, 3, 14))["until"], "17:00")
        self.assertIsNone(focusplan.current_block(f, ts(2026, 11, 3, 17)))
        n = focusplan.next_block(f, ts(2026, 11, 3, 18))
        self.assertEqual(datetime.fromtimestamp(n["ts"]), datetime(2026, 11, 10, 13, 30))
        self.assertEqual(focusplan.area_of_card(f, {"pools": [{"name": "berufsbildung"}]}), "dev")    # Kategorie fehlt in diesem Bereich
        f["areas"][1]["pools"] = ["Berufsbildung"]
        self.assertEqual(focusplan.area_of_card(f, {"pools": [{"name": "berufsbildung"}]}), "bb")
        self.assertEqual(focusplan.booking_key(f["areas"][1]), "Berufsbildung")


class Book(unittest.TestCase):
    def setUp(self):
        self.tb = timesheet.TimeBook(Path(tempfile.mkdtemp()) / "t.db")

    def test_activity_switch_and_range(self):
        t0 = ts(2026, 11, 3, 9)
        self.tb.start("Berufsbildung", "Berufsbildung", t0, area="bb", activity="Meeting")
        self.tb.start("Berufsbildung", "Berufsbildung", t0 + 600, area="bb", activity="Meeting")       # gleich: läuft weiter
        self.tb.start("Berufsbildung", "Berufsbildung", t0 + 1200, area="bb", activity="Aufgaben reviewen")
        self.tb.stop(t0 + 1800)
        segs = self.tb.range_segments(t0 - 100, t0 + 3600, t0 + 3600)
        self.assertEqual([(s["activity"], s["secs"]) for s in segs], [("Meeting", 1200), ("Aufgaben reviewen", 600)])
        tot = self.tb.totals("2026-11-03", t0 + 3600)
        self.assertEqual(tot["Berufsbildung"]["activities"], ["Meeting", "Aufgaben reviewen"])
        self.assertEqual(tot["Berufsbildung"]["area"], "bb")
        d = timesheet.compose("2026-11-03", tot, {}, [], [])
        self.assertIn("Meeting, Aufgaben reviewen", d[0]["text"])

    def test_sessions(self):
        t0 = ts(2026, 11, 3, 9)
        s1 = self.tb.session_start("K", "K", "bb", "", 25, t0)
        s2 = self.tb.session_start("L", "L", "dev", "", 50, t0 + 60)       # löst die erste ab
        self.assertEqual(self.tb.session()["id"], s2)
        rows = self.tb.sessions(t0 - 1, t0 + 100)
        self.assertEqual((rows[0]["id"], rows[0]["result"]), (s1, "abgelöst"))
        self.tb.session_update(s2, end=t0 + 120, result="erledigt")
        self.assertIsNone(self.tb.session())


class AppFocus(unittest.TestCase):
    def app(self, focus=None):
        os.environ["TINYOPS_HOME"] = tempfile.mkdtemp()
        cfg = server.load_config(None)
        cfg["data_dir"] = tempfile.mkdtemp()
        cfg["time"] = {"enabled": True}
        if focus:
            cfg["focus"] = focus
        a = server.App(cfg, True, {}, Path("/nonexistent/c.json"))
        return a

    def test_helpdesk_in_focus_and_seen(self):
        a = self.app()
        ov = a.overview()
        hd = ov["flow"]["helpdesk"]
        self.assertTrue(hd and all(e["id"].startswith("hd:") for e in hd))
        self.assertEqual(ov["flow"]["hd_info"]["name"], "Servicedesk")
        self.assertTrue(all(q["new"] for q in ov["flow"]["hd_queue"]))
        self.assertTrue(any(s["id"] == "helpdesk" for s in ov["sources"]))
        a.helpdesk_seen({"all": True})
        self.assertFalse(any(q["new"] for q in a.overview()["flow"]["hd_queue"]))
        # Anheften: Zeit läuft auf das Helpdesk-Ticket, Bereich Helpdesk
        key = hd[0]["key"]
        a.flow_action("pin", {"id": "hd:" + key})
        r = a.time_state()["running"]
        self.assertEqual((r["key"], r["area"]), (key, "hd"))
        self.assertIn(key, a._time_meta())
        self.assertEqual(a.overview()["flow"]["pinned"], "hd:" + key)
        with self.assertRaises(server.UserError):
            a.flow_action("pin", {"id": "hd:SD-0"})

    def test_session_in_area_park_switch_end(self):
        a = self.app()
        a.overview()
        st = a.focus_action("start", {"area": "bb", "activity": "Betreuung Lernende", "minutes": 50})
        self.assertEqual((st["session"]["area"], st["session"]["key"]), ("bb", "Berufsbildung"))
        run = a.time_state()["running"]
        self.assertEqual((run["key"], run["area"], run["activity"]), ("Berufsbildung", "bb", "Betreuung Lernende"))
        p = a.focus_action("park", {"text": "Mail an Lernende"})
        self.assertEqual(p["parked"], 1)
        self.assertTrue(any(i["text"] == "Mail an Lernende" for i in a.ideas.list()) if hasattr(a.ideas, "list") else True)
        a.focus_action("activity", {"activity": "Aufgaben reviewen"})
        self.assertEqual(a.time_state()["running"]["activity"], "Aufgaben reviewen")
        ses = a.timebook.session()
        for m in (10, 20):                                   # das Panel fragt ab: die Sitzung selbst ist das Lebenszeichen
            self.assertIsNotNone(a.focus_state(ses["start"] + m * 60)["session"])
        end = a.focus_action("end", {"result": "erledigt"}, now=ses["start"] + 30 * 60)
        self.assertEqual((end["ended"]["minutes"], end["ended"]["xp"]), (30, 15))
        self.assertIsNone(end["session"])
        self.assertIsNone(a.time_state()["running"])
        acts = [r["action"] for r in a.audit_log.rows(limit=20)]
        self.assertIn("focus.start", acts)
        self.assertIn("focus.end", acts)
        with self.assertRaises(server.UserError):
            a.focus_action("park", {"text": "x"})                      # keine Sitzung mehr

    def test_session_rules(self):
        a = self.app()
        a.overview()
        for bad in ({"area": "bb", "minutes": 3}, {"area": "nix"}, {"key": "hd:SD-0"}, {"key": "GIBTS-1"}):
            with self.assertRaises(server.UserError):
                a.focus_action("start", bad)
        st = a.focus_action("start", {"key": "hd:" + a.overview()["flow"]["helpdesk"][0]["key"], "minutes": 25})
        self.assertEqual(st["session"]["area"], "hd")
        ses = a.timebook.session()
        end = a.focus_action("end", {"result": "weiter"}, now=ses["start"] + 10 * 60)
        self.assertEqual(end["ended"]["xp"], 0)                        # unter 20 min: keine XP
        self.assertIsNotNone(a.time_state()["running"])                 # «weiter»: Zeit läuft weiter

    def test_week_report_in_overview(self):
        a = self.app({"areas": [{"id": "bb", "name": "Berufsbildung", "target_pct": 30, "pools": ["Berufsbildung"],
                                 "blocks": focusplan.parse_blocks("Mo 08:00-17:00, Di 08:00-17:00, Mi 08:00-17:00, Do 08:00-17:00, Fr 08:00-17:00")}]})
        now = time.time()
        a.timebook.add_segment("Berufsbildung", "Berufsbildung", now - 3600, now - 60, area="bb")
        f = a.overview()["focus"]
        bb = next(x for x in f["week"]["areas"] if x["id"] == "bb")
        self.assertGreaterEqual(bb["secs"], 3500)
        self.assertEqual(bb["target_pct"], 30)
        self.assertTrue(f["next_block"] or f["block"])

    def test_disabled_time_means_no_focus(self):
        os.environ["TINYOPS_HOME"] = tempfile.mkdtemp()
        cfg = server.load_config(None)
        cfg["data_dir"] = tempfile.mkdtemp()
        a = server.App(cfg, True, {}, Path("/nonexistent/c.json"))
        a.tc["enabled"] = False
        self.assertIsNone(a.focus_state())
        with self.assertRaises(server.UserError):
            a.focus_action("start", {"area": "bb"})


class Config(unittest.TestCase):
    def test_build_and_view(self):
        p = {"helpdesk": {"enabled": True, "url": "https://sd.example/", "auth": "basic", "username": "ab", "queue_jql": "  project = SD  ",
                          "sla_hours": "12"},
             "focus": {"week_hours": 40, "day_start": "7:30", "day_end": "16:30",
                       "areas": [{"id": "dev", "name": "Entwicklung", "target_pct": 0},
                                 {"id": "bb", "name": "Berufsbildung", "target_pct": "30", "pools": "Berufsbildung, BB",
                                  "activities": "Meeting, Betreuung Lernende", "blocks_text": "Di 13:30-17:00"},
                                 {"name": "Weiterbildung", "target_pct": 10}]}}
        cfg, err = settings.build_config({}, p)
        self.assertEqual(err, {})
        self.assertEqual(cfg["helpdesk"]["url"], "https://sd.example")
        self.assertEqual((cfg["helpdesk"]["queue_jql"], cfg["helpdesk"]["sla_hours"]), ("project = SD", 12))
        self.assertEqual(cfg["focus"]["day_start"], "07:30")
        bb = cfg["focus"]["areas"][1]
        self.assertEqual((bb["pools"], bb["activities"], bb["blocks"]), (["Berufsbildung", "BB"], ["Meeting", "Betreuung Lernende"], [{"day": 2, "from": "13:30", "to": "17:00"}]))
        self.assertEqual(cfg["focus"]["areas"][2]["id"], "weiterbildung")
        v = settings.view(cfg, "x")
        self.assertEqual(v["focus"]["areas"][1]["blocks_text"], "Di 13:30-17:00")
        self.assertNotIn("password", str(v["helpdesk"]).lower())
        self.assertIn("helpdesk_password", v["secrets"])

    def test_errors(self):
        _, err = settings.build_config({}, {"helpdesk": {"enabled": True, "url": "", "auth": "basic"}})
        self.assertIn("helpdesk.url", err)
        self.assertIn("helpdesk.username", err)
        _, err = settings.build_config({}, {"helpdesk": {"url": "ftp://x", "auth": "ntlm"}})
        self.assertEqual(set(err), {"helpdesk.url", "helpdesk.auth"})
        _, err = settings.build_config({}, {"focus": {"areas": [{"name": "A", "target_pct": 70}, {"name": "B", "target_pct": 40}]}})
        self.assertIn("100", err["focus.areas"])
        _, err = settings.build_config({}, {"focus": {"areas": [{"name": "A", "blocks_text": "Mo 9-10"}]}})
        self.assertIn("focus.areas.0.blocks", err)
        _, err = settings.build_config({}, {"focus": {"day_start": "17:00", "day_end": "08:00"}})
        self.assertIn("focus.day_end", err)
        _, err = settings.build_config({}, {"focus": {"areas": [{"name": "A"}, {"name": "a"}]}})
        self.assertIn("doppelt", err["focus.areas"])

    def test_secret_names(self):
        import secretstore
        for n in ("helpdesk_password", "helpdesk_token"):
            self.assertIn(n, settings.SECRET_FIELDS)
            self.assertIn(n, secretstore.NAMES)


if __name__ == "__main__":
    unittest.main()
