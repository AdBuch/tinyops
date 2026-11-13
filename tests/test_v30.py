"""0.30: Tickets zu Tasks gruppieren (Bug + Begleitticket, Story + Unteraufgaben, von Hand), Bugs bleiben sichtbar; tinyops-Wünsche im Nutzungsbericht; mehr Nutzungsdaten."""
import os
import re
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import groups  # noqa: E402
import server  # noqa: E402


def t(key, typ="Story", links=(), parent=""):
    return {"key": key, "type": typ, "summary": key, "links": [{"key": k, "type": lt} for k, lt in links], "parent": parent}


class Build(unittest.TestCase):
    def test_bug_with_companion_is_head(self):
        heads, head_of = groups.build([t("DLP-2", "Aufgabe", [("DLP-1", "Relates")]), t("DLP-1", "Bug", [("DLP-2", "Relates")]), t("DLP-5")])
        self.assertEqual([h["key"] for h in heads], ["DLP-1", "DLP-5"])
        self.assertEqual(head_of, {"DLP-2": "DLP-1"})
        self.assertEqual(heads[0]["companions"][0]["why"], "Begleitticket (Relates)")

    def test_single_bug_stays_and_counting(self):
        heads, _ = groups.build([t("DLP-1", "Fehler"), t("DLP-2", "Story")], counted=["Story"])
        self.assertEqual({h["key"]: h["counts"] for h in heads}, {"DLP-1": False, "DLP-2": True})
        heads, _ = groups.build([t("DLP-1", "Fehler", [("DLP-2", "x")]), t("DLP-2", "Story")], counted=["Story"])
        self.assertEqual([(h["key"], h["counts"]) for h in heads], [("DLP-1", True)])           # Gruppe zählt einmal, wenn ein Mitglied zählt

    def test_subtask_and_link_types(self):
        heads, head_of = groups.build([t("DLP-10"), t("DLP-11", "Sub-Task", parent="DLP-10"), t("DLP-12", links=[("DLP-10", "Blocks")])], link_types=["Relates"])
        self.assertEqual(head_of, {"DLP-11": "DLP-10"})                                         # «Blocks» ist nicht gewählt
        self.assertEqual(len(heads), 2)
        self.assertEqual(heads[0]["companions"][0]["why"], "Unteraufgabe")

    def test_manual_wins(self):
        tk = [t("DLP-1", "Bug", [("DLP-2", "Relates")]), t("DLP-2", links=[("DLP-1", "Relates")]), t("DLP-3")]
        heads, head_of = groups.build(tk, manual={"DLP-2": ""})                                 # eigenständig
        self.assertEqual(head_of, {})
        heads, head_of = groups.build(tk, manual={"DLP-3": "DLP-1"})
        self.assertEqual(head_of, {"DLP-2": "DLP-1", "DLP-3": "DLP-1"})
        self.assertTrue(heads[0]["grouped_by_hand"])
        heads, head_of = groups.build(tk, manual={"DLP-1": "DLP-2"})                            # von Hand: die Story ist der Task
        self.assertEqual(head_of, {"DLP-1": "DLP-2"})
        heads, _ = groups.build(tk, manual={"DLP-3": "DLP-99"})                                 # Kopf nicht in Arbeit: bleibt allein
        self.assertEqual(len(heads), 2)

    def test_links_of(self):
        f = {"issuelinks": [{"type": {"name": "Relates", "inward": "relates to", "outward": "relates to"}, "outwardIssue": {"key": "A-2"}},
                            {"type": {"name": "Blocks"}, "inwardIssue": {"key": "A-3"}}, {"type": {"name": "x"}}]}
        self.assertEqual(groups.links_of(f), [{"key": "A-2", "type": "Relates"}, {"key": "A-3", "type": "Blocks"}])


class App(unittest.TestCase):
    def app(self):
        os.environ["TINYOPS_HOME"] = tempfile.mkdtemp()
        c = server.load_config(None)
        c["data_dir"] = tempfile.mkdtemp()
        return server.App(c, True, {}, Path("/nonexistent/c.json"))

    def test_demo_groups_and_board(self):
        a = self.app()
        ov = a.overview()
        st = {s["key"]: s for s in ov["jira"]["stories"]}
        self.assertIn("DLP-131", st)
        self.assertNotIn("DLP-132", st)
        self.assertEqual(st["DLP-131"]["companions"][0]["key"], "DLP-132")
        cards = {c["key"]: c for c in ov["board"]["cards"] if c["key"]}
        self.assertNotIn("DLP-132", cards)
        self.assertEqual([x["key"] for x in cards["DLP-131"]["companions"]], ["DLP-132"])
        self.assertEqual(ov["jira"]["count"], len([s for s in ov["jira"]["stories"] if s["counts"]]))
        a.group_action({"key": "DLP-132", "head": ""})                                          # eigenständig
        a.cache_t = 0.0
        a._refresh()
        ov = a.overview()
        self.assertIn("DLP-132", {s["key"] for s in ov["jira"]["stories"]})
        a.group_action({"key": "DLP-132", "reset": True})
        for bad in ({"key": "x"}, {"key": "DLP-1", "head": "DLP-1"}, {"key": "DLP-1", "head": "kein key"}):
            with self.assertRaises(server.UserError):
                a.group_action(bad)
        acts = [r["action"] for r in a.audit_log.rows(limit=10)]
        self.assertIn("board.group", acts)


class Ui(unittest.TestCase):
    def test_static(self):
        html = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
        for needle in ("function openGroup(", "function compList(", "'Tasks in Arbeit'", "data-grp=", "id=\"grpHead\"", "ji-grp"):
            self.assertIn(needle, html, needle)


if __name__ == "__main__":
    unittest.main()


class Usage(unittest.TestCase):
    def setUp(self):
        import ux
        self.ux = ux
        self.log = ux.UxLog(Path(tempfile.mkdtemp()) / "ux.db")

    def test_wish_template_slow_help_versions(self):
        ux = self.ux
        self.log.add_batch("s1", [{"k": "env", "e": {"ver": "0.29.0", "views": ["focus", "board", "ws", "qa"]}}, {"k": "view", "t": "focus"},
                                  {"k": "dead", "t": "span.tt", "v": "focus"}, {"k": "dead", "t": "span.tt", "v": "focus"}, {"k": "dead", "t": "span.tt", "v": "focus"}])
        self.log.add_batch("s2", [{"k": "env", "e": {"ver": "0.30.0", "views": ["focus", "board", "ws", "qa"]}}, {"k": "view", "t": "board"},
                                  {"k": "fail", "t": "POST /api/bcs/preview", "e": {"m": "Ticket DLP-123 hat 3 Fehler «geheimer Titel»"}},
                                  {"k": "fail", "t": "POST /api/bcs/preview", "e": {"m": "Ticket DLP-9 hat 1 Fehler «anderer Titel»"}},
                                  {"k": "fail", "t": "POST /api/bcs/preview", "e": {"m": "Ticket DLP-7 hat 2 Fehler «x»"}},
                                  {"k": "slow", "t": "POST /api/agents/start", "e": {"ms": 2400}}, {"k": "slow", "t": "POST /api/agents/start", "e": {"ms": 3100}},
                                  {"k": "slow", "t": "POST /api/agents/start", "e": {"ms": 1900}}, {"k": "help", "t": "agents"}, {"k": "help", "t": "agents"}])
        self.log.add_wish("s2", "Gruppen auch im Fokus zeigen, password=hunter2hunter", "board", ["Klick button «Gruppieren …»", "Dialog wsDlg"], "0.30.0")
        with self.assertRaises(ValueError):
            self.log.add_wish("s2", "   ", "board")
        evs = self.log.events(0)
        a = ux.analyse(evs)
        sub, newest = ux.latest_only(evs, a)
        cur = ux.analyse(sub)
        md = ux.report_md(a, 7, "0.30.0", cur, newest)
        self.assertIn("Versionen: 0.29.0 (1 Sitzung), 0.30.0 (1 Sitzung)", md)
        self.assertIn("## Wünsche an tinyops", md)
        self.assertIn("Gruppen auch im Fokus zeigen", md)
        self.assertNotIn("hunter2", md)
        self.assertIn("zuvor: Klick button «Gruppieren …» → Dialog wsDlg", md)
        self.assertIn("«Ticket KEY hat # Fehler «…»» 3×", md)
        for bad in ("DLP-123", "geheimer Titel"):
            self.assertNotIn(bad, md)
        self.assertIn("POST /api/agents/start: 3×, Median 2.4 s", md)
        self.assertIn("agents 2×", md)
        self.assertIn("## Im Zeitraum nie geöffnet\nqa, ws", md)
        self.assertIn("## Auffällig (nur Sitzungen mit 0.30.0)", md)
        self.assertNotIn("tote Klicks auf «span.tt»", md.split("## Auffällig")[1].split("##")[0])     # alte Version zählt nicht zu «Auffällig»
        self.assertIn("dieselbe Fehlermeldung", md)

    def test_wish_endpoint_even_when_tracking_off(self):
        os.environ["TINYOPS_HOME"] = tempfile.mkdtemp()
        c = server.load_config(None)
        c["data_dir"] = tempfile.mkdtemp()
        c["ux"] = {"enabled": False}
        a = server.App(c, True, {}, Path("/nonexistent/c.json"))
        self.assertTrue(a.ux_wish({"text": "Knopf X fehlt", "view": "focus", "trail": ["Klick a"], "sess": "abc"})["ok"])
        r = a.ux_report(7)
        self.assertEqual(r["wishes"], 1)
        self.assertIn("Knopf X fehlt", r["text"])
        with self.assertRaises(server.UserError):
            a.ux_wish({"text": ""})

    def test_ui(self):
        html = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
        for needle in ('id="ideaWish"', "/api/ux/wish", "WISH_RE", "k: 'fail'", "k: 'slow'", "k: 'help'", "ver: state && state.version", "UX.trail"):
            self.assertIn(needle, html, needle)
