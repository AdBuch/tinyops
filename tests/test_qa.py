"""Qualität (0.19): Prüfliste je Release, Stand in der Datenbank, Selbsttest."""
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import qa  # noqa: E402
import server  # noqa: E402

TXT = """# Prüfliste
## Grundprüfung
- [ ] `b-01` Panel öffnen → Version stimmt
- [x] `b-02` Mit `code` drin
Freitext wird ignoriert
## 9.9.9
- [ ] `r-1` Neu
"""


class Checklist(unittest.TestCase):
    def test_parse(self):
        s = qa.parse_checklist(TXT)
        self.assertEqual([(x["title"], x["version"], len(x["items"])) for x in s], [("Grundprüfung", "", 2), ("9.9.9", "9.9.9", 1)])
        self.assertEqual((s[0]["items"][0]["text"], s[0]["items"][0]["expect"]), ("Panel öffnen", "Version stimmt"))
        with self.assertRaises(ValueError):
            qa.parse_checklist(TXT + "- [ ] `b-01` doppelt\n")
        it = qa.parse_checklist("## x\n- [ ] `a` Log → Verlauf → «Kette prüfen» → in Ordnung\n")[0]["items"][0]
        self.assertEqual((it["text"], it["expect"]), ("Log → Verlauf → «Kette prüfen»", "in Ordnung"))      # das letzte → trennt

    def test_state_changed_and_report(self):
        book = qa.QaBook(Path(tempfile.mkdtemp()) / "t.db")
        s = qa.parse_checklist(TXT)
        book.set("b-01", "fehler", "Version fehlt oben", "9.9.9", s[0]["items"][0]["hash"])
        book.set("b-02", "ok", "", "9.9.9", "anderer-hash")
        v = qa.view(s, book.states())
        it = {i["id"]: i for sec in v for i in sec["items"]}
        self.assertEqual(it["b-01"]["status"], "fehler")
        self.assertEqual((it["b-02"]["status"], it["b-02"]["changed"]), ("offen", True))      # Text geändert: neu prüfen
        md = qa.report_md(v, "9.9.9")
        self.assertIn("## Fehler", md)
        self.assertIn("> Version fehlt oben", md)
        self.assertIn("`r-1` Neu", md)
        book.set("b-01", "offen", "", "9.9.9", "")
        self.assertNotIn("b-01", book.states())

    def test_repo_checklist_has_section_for_this_release(self):
        s = qa.parse_checklist((ROOT / "QA-CHECKLIST.md").read_text(encoding="utf-8"))
        self.assertIn(server.VERSION, [x["version"] for x in s], "QA-CHECKLIST.md braucht einen Abschnitt «## %s» mit dem, was sich geändert hat" % server.VERSION)
        self.assertGreaterEqual(sum(len(x["items"]) for x in s if not x["version"]), 40)       # Grundprüfung deckt alles ab


class AppQa(unittest.TestCase):
    def setUp(self):
        os.environ["TINYOPS_HOME"] = tempfile.mkdtemp()
        cfg = server.load_config(None)
        cfg["data_dir"] = tempfile.mkdtemp()
        self.app = server.App(cfg, True, {}, Path("/nonexistent/c.json"))
        self.app.overview()

    def test_actions(self):
        a = self.app
        v = a.qa_view()
        self.assertTrue(any(s["current"] for s in v["sections"]))
        first = v["sections"][0]["items"][0]["id"]
        a.qa_action("set", {"id": first, "status": "fehler", "note": "kaputt"})
        r = a.qa_action("report", {})["text"]
        self.assertIn("kaputt", r)
        key = a.qa_action("task", {"id": first})["key"]
        self.assertTrue(key.startswith("LOC-"))
        with self.assertRaises(server.UserError):
            a.qa_action("set", {"id": "gibtsnicht", "status": "ok"})
        with self.assertRaises(server.UserError):
            a.qa_action("set", {"id": first, "status": "super"})
        self.assertEqual(a.audit_log.rows(action="qa.check")[0]["target"], first)

    def test_selftest_passes_and_leaves_data_alone(self):
        before = self.app.audit_log.verify()["count"]
        res = self.app.qa_action("selftest", {})
        self.assertTrue(res["ok"], [x for x in res["steps"] if x["status"] == "fail"])
        ids = {x["id"] for x in res["steps"]}
        self.assertTrue({"ui", "prompts", "helpers", "checklist", "db", "audit", "demo", "flow", "audit_w", "time", "review", "qa"} <= ids, ids)
        self.assertEqual(self.app.audit_log.verify()["count"], before + 1)       # nur der Eintrag «Selbsttest»

    def test_cli(self):
        d = tempfile.mkdtemp()
        conf = Path(d) / "c.json"
        conf.write_text('{"data_dir": "%s"}' % d)
        r = subprocess.run([sys.executable, str(ROOT / "server.py"), "--config", str(conf), "--selftest"], capture_output=True, text=True, timeout=120,
                           env=dict(os.environ, TINYOPS_HOME=d, TINYOPS_NO_WATCHDOG="1"))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("Selbsttest bestanden", r.stdout)


if __name__ == "__main__":
    unittest.main()
