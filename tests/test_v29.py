"""0.29: BCS-Buchungen über die Middleware (Tag lesen, Vorschau, einmal bestätigen, Abgleich nach Abbruch), Aufgaben-Zuordnung, Lernende, Buchungstexte."""
import os
import re
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import bcs  # noqa: E402
import llm  # noqa: E402
import mock_bcs  # noqa: E402
import server  # noqa: E402
import settings  # noqa: E402
import timesheet  # noqa: E402

DAY = "2026-11-10"


class Unit(unittest.TestCase):
    def test_check_url_loopback_only(self):
        self.assertEqual(bcs.check_url("http://127.0.0.1:3210/"), "http://127.0.0.1:3210")
        self.assertEqual(bcs.check_url("http://localhost:3210"), "http://localhost:3210")
        for bad in ("http://10.0.0.5:3210", "https://bcs.firma.ch", "ftp://127.0.0.1", "http://u:p@127.0.0.1:3210", "http://127.0.0.1:3210?x=1", ""):
            with self.assertRaises(bcs.BcsError, msg=bad):
                bcs.check_url(bad)

    def test_change_and_match(self):
        ch = bcs.change_for({"ticket": "DLP-12", "text": "Retry  eingebaut", "minutes": 45}, "T-1")
        self.assertEqual(ch, {"action": "add", "kind": "work", "durationMinutes": 45, "description": "DLP-12 Retry eingebaut", "taskId": "T-1"})
        self.assertEqual(bcs.change_for({"ticket": "DLP-12", "text": "DLP-12 schon vorne", "minutes": 5}, "T-1")["description"], "DLP-12 schon vorne")
        e = {"kind": "work", "durationMinutes": 45, "description": "DLP-12 Retry eingebaut", "task": {"id": "T-1"}}
        self.assertTrue(bcs.matches(e, ch))
        self.assertFalse(bcs.matches(dict(e, durationMinutes=30), ch))
        self.assertEqual((bcs.prefix_of("DLP-12"), bcs.prefix_of("Berufsbildung"), bcs.prefix_of("LOC-3")), ("DLP-*", "", "LOC-*"))

    def test_settings(self):
        cur = server.load_config(None)
        cfg, err = settings.build_config(cur, {"time": {"bcs": {"enabled": True, "url": "http://192.168.1.9:3210"}}})
        self.assertIn("time.bcs.url", err)
        cfg, err = settings.build_config(cur, {"time": {"bcs": {"enabled": True, "url": "http://127.0.0.1:3210/"}}})
        self.assertEqual((err, cfg["time"]["bcs"]["url"]), ({}, "http://127.0.0.1:3210"))
        self.assertIn("bcs_token", settings.SECRET_FIELDS)


class Flow(unittest.TestCase):
    def setUp(self):
        self.srv, self.st, self.url = mock_bcs.start()
        os.environ["TINYOPS_HOME"] = tempfile.mkdtemp()
        c = server.load_config(None)
        c["data_dir"] = tempfile.mkdtemp()
        c["time"] = {"enabled": True, "bcs": {"enabled": True, "url": self.url}}
        self.a = server.App(c, False, {"bcs_token": "tok"}, Path("/nonexistent/c.json"))
        self.st.token = "tok"
        tb = self.a.timebook
        self.d1 = tb.add_manual(DAY, "DLP-12", 45, "Retry eingebaut")
        self.d2 = tb.add_manual(DAY, "DLP-13", 30, "Review")
        self.d3 = tb.add_manual(DAY, "Berufsbildung", 60, "Lernende")
        for d in (self.d1, self.d2, self.d3):
            self.a.time_action("confirm", {"id": d})

    def tearDown(self):
        self.srv.shutdown()

    def state(self, did):
        return self.a.timebook.draft(did)["state"]

    def test_day_map_preview_commit(self):
        r = self.a.bcs_day(DAY)
        self.assertEqual((r["day"]["attendance_minutes"], r["day"]["issues"], r["week"]["targetMinutes"]), (480, ["Pause fehlt"], 2520))
        self.assertEqual(self.a.time_day(DAY)["bcs"]["on"], True)
        with self.assertRaises(server.UserError):
            self.a.bcs_action("preview", {"date": DAY})                                 # noch keine Aufgabe zugeordnet
        self.assertEqual(self.a.bcs_action("targets", {"date": DAY, "query": "dlp"})["items"][0]["id"], "T-1")
        self.assertEqual(self.a.bcs_action("map", {"ticket": "DLP-12", "task_id": "T-1", "name": "Entwicklung DLP", "path": ["Produkte", "DLP"], "scope": "project"})["pattern"], "DLP-*")
        self.a.bcs_action("map", {"ticket": "Berufsbildung", "task_id": "T-2", "name": "Berufsbildung", "scope": "ticket"})
        drafts = {x["id"]: x for x in self.a.time_day(DAY)["drafts"]}
        self.assertEqual((drafts[self.d2]["bcs_task"]["pattern"], drafts[self.d3]["bcs_task"]["task_id"]), ("DLP-*", "T-2"))
        p = self.a.bcs_action("preview", {"date": DAY})
        self.assertEqual((p["status"], len(p["included"]), p["skipped"]), ("ready", 3, []))
        self.assertIn("DLP-12 Retry eingebaut", [x["description"] for x in p["included"]])
        self.assertEqual([c[0] for c in self.st.calls if c[1] == "/api/v1/drafts/commit"], [])         # die Vorschau bucht nichts
        with self.assertRaises(server.UserError):
            self.a.bcs_action("commit", {"date": DAY, "draft_id": "00000000-0000-4000-8000-000000000000"})   # fremde draftId
        r = self.a.bcs_action("commit", {"date": DAY, "draft_id": p["draft_id"]})
        self.assertEqual(r["status"], "committed")
        self.assertEqual([self.state(d) for d in (self.d1, self.d2, self.d3)], ["gebucht"] * 3)
        self.assertEqual(self.a.timebook.draft(self.d1)["reference"], "BCS %s" % DAY)
        with self.assertRaises(server.UserError):
            self.a.bcs_action("commit", {"date": DAY, "draft_id": p["draft_id"]})      # eine Vorschau nur einmal
        acts = [x["action"] for x in self.a.audit_log.rows(limit=30)]
        for want in ("bcs.map", "bcs.preview", "bcs.commit"):
            self.assertIn(want, acts)
        self.assertTrue(all(c[0] != "POST" or "Authorization" not in c for c in self.st.calls))

    def test_changed_after_preview_needs_new_preview(self):
        self.a.bcs_action("map", {"ticket": "DLP-12", "task_id": "T-1", "scope": "project"})
        self.a.bcs_action("map", {"ticket": "Berufsbildung", "task_id": "T-2"})
        p = self.a.bcs_action("preview", {"date": DAY})
        self.a.time_action("edit", {"id": self.d1, "minutes": 60})                       # zurück auf «offen»
        with self.assertRaises(server.UserError) as cm:
            self.a.bcs_action("commit", {"date": DAY, "draft_id": p["draft_id"]})
        self.assertIn("geändert", str(cm.exception))
        self.assertFalse([c for c in self.st.calls if c[1] == "/api/v1/drafts/commit"])

    def test_blocked_dry_run_rejected(self):
        self.a.bcs_action("map", {"ticket": "DLP-12", "task_id": "T-X", "scope": "project"})
        self.a.bcs_action("map", {"ticket": "Berufsbildung", "task_id": "T-2"})
        p = self.a.bcs_action("preview", {"date": DAY})
        self.assertEqual((p["status"], p["draft_id"], p["warnings"][0]["message"]), ("blocked", None, "Aufgabe unbekannt"))
        self.a.bcs_action("map", {"ticket": "DLP-12", "task_id": "T-1", "scope": "project"})
        self.st.mode = "dry_run"
        r = self.a.bcs_action("commit", {"date": DAY, "draft_id": self.a.bcs_action("preview", {"date": DAY})["draft_id"]})
        self.assertEqual(r["status"], "dry_run")
        self.assertEqual(self.state(self.d1), "bestätigt")
        self.st.mode = "rejected"
        r = self.a.bcs_action("commit", {"date": DAY, "draft_id": self.a.bcs_action("preview", {"date": DAY})["draft_id"]})
        self.assertEqual((r["status"], self.state(self.d1), self.a.timebook.draft(self.d1)["message"]), ("rejected", "abgelehnt", "Tag ist abgeschlossen"))

    def test_connection_drop_never_retries_then_reconcile(self):
        self.a.bcs_action("map", {"ticket": "DLP-12", "task_id": "T-1", "scope": "project"})
        self.a.bcs_action("map", {"ticket": "Berufsbildung", "task_id": "T-2"})
        self.st.mode = "drop"
        p = self.a.bcs_action("preview", {"date": DAY})
        r = self.a.bcs_action("commit", {"date": DAY, "draft_id": p["draft_id"]})
        self.assertEqual(r["status"], "unklar")
        self.assertEqual(len([c for c in self.st.calls if c[1] == "/api/v1/drafts/commit"]), 1)        # genau ein Versuch
        self.assertEqual([self.state(d) for d in (self.d1, self.d2, self.d3)], ["unklar"] * 3)
        with self.assertRaises(server.UserError):
            self.a.time_action("edit", {"id": self.d1, "minutes": 10})                  # gesperrt bis zum Abgleich
        with self.assertRaises(server.UserError):
            self.a.bcs_action("preview", {"date": DAY})                                 # unklare gehen nicht nochmals in eine Vorschau
        r = self.a.bcs_action("reconcile", {"date": DAY})
        self.assertEqual((r["booked"], r["back"]), (3, 0))
        self.assertEqual([self.state(d) for d in (self.d1, self.d2, self.d3)], ["gebucht"] * 3)

    def test_drop_without_booking_goes_back(self):
        self.a.bcs_action("map", {"ticket": "DLP-12", "task_id": "T-1", "scope": "project"})
        self.a.bcs_action("map", {"ticket": "Berufsbildung", "task_id": "T-2"})
        self.st.mode = "drop_nothing"
        self.a.bcs_action("commit", {"date": DAY, "draft_id": self.a.bcs_action("preview", {"date": DAY})["draft_id"]})
        r = self.a.bcs_action("reconcile", {"date": DAY})
        self.assertEqual((r["booked"], r["back"], self.state(self.d1)), (0, 3, "bestätigt"))

    def test_apprentices_and_token(self):
        r = self.a.bcs_action("apprentices", {})
        self.assertEqual(r["members"][0], {"id": "a1", "name": "Lea", "status": "available", "ytd": -30, "week": 15, "vacation_left": 9, "as_of": None})
        self.a.bcs.token = "falsch"
        with self.assertRaises(server.UserError) as cm:
            self.a.bcs_day(DAY)
        self.assertIn("Token", str(cm.exception))

    def test_unreachable(self):
        self.srv.shutdown()
        self.srv.server_close()
        with self.assertRaises(server.UserError) as cm:
            self.a.bcs_day(DAY)
        self.assertIn("nicht erreichbar", str(cm.exception))
        self.srv, self.st, _ = mock_bcs.start()


class Demo(unittest.TestCase):
    def test_demo_end_to_end_and_texts(self):
        os.environ["TINYOPS_HOME"] = tempfile.mkdtemp()
        c = server.load_config(None)
        c["data_dir"] = tempfile.mkdtemp()
        c["time"] = {"enabled": True}
        a = server.App(c, True, {}, Path("/nonexistent/c.json"))
        d = timesheet.today()
        did = a.timebook.add_manual(d, "DLP-101", 90, "Retry")
        a.time_action("confirm", {"id": did})
        a.bcs_action("map", {"ticket": "DLP-101", "task_id": "T-100", "name": "Entwicklung DLP", "scope": "project"})
        p = a.bcs_action("preview", {"date": d})
        self.assertEqual(a.bcs_action("commit", {"date": d, "draft_id": p["draft_id"]})["status"], "committed")
        self.assertIn("DLP-101 Retry", [e["description"] for e in a.bcs_day(d)["day"]["entries"]])
        self.assertEqual(len(a.bcs_action("apprentices", {})["members"]), 2)
        # Buchungstexte: Modell liefert JSON, nur bekannte ids zählen
        did2 = a.timebook.add_manual(d, "DLP-102", 30, "x")
        a.lc = dict(a.lc, enabled=True, url="http://127.0.0.1:11434", model="qwen")
        orig = llm._ask
        llm._ask = lambda *a_, **k: 'Hier: {"%s": "Helm-Limits gesetzt und getestet", "fremd": "nein"}' % did2
        try:
            r = a.time_action("texts", {"date": d})
        finally:
            llm._ask = orig
        self.assertEqual(r["texts"], {did2: "Helm-Limits gesetzt und getestet"})
        self.assertEqual(a.timebook.draft(did2)["text"], "x")                             # nur ein Vorschlag


class Ui(unittest.TestCase):
    def test_static(self):
        html = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
        for needle in ("function renderBcs()", "function bcsPreview()", "function bcsMap(", "/api/bcs/commit", "/api/bcs/reconcile", "id=\"bc-on\"", "data-ttext", "Mit BCS abgleichen"):
            self.assertIn(needle, html, needle)
        src = (ROOT / "bcs.py").read_text(encoding="utf-8")
        self.assertEqual(len(re.findall(r'"/api/v1/drafts/commit"', src)), 1)


if __name__ == "__main__":
    unittest.main()
