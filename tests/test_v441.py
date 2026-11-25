"""0.44.1: Review-Befunde von Agenten, die tinyops-finding nicht aufrufen (Rückmeldung vom 25.11.): tinyops liest sie aus Bericht
oder letzter Antwort, und du bearbeitest die Liste vor dem Anlegen in GitLab."""
import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("TINYOPS_HOME", tempfile.mkdtemp())
import review_findings as rf  # noqa: E402
import server  # noqa: E402
import ui  # noqa: E402


class Parse(unittest.TestCase):
    def test_findings_block(self):
        t = "Fazit: noch nicht.\n\n```findings\nsrc/Foo.java:42 | hoch | Leere Liste wirft NPE.\n./src/Bar.java:7 | nit | Name sagt wenig | ehrlich\n" \
            "../etc/passwd:1 | hoch | nein\nkein Befund hier\n```\n"
        f = rf.from_report(t)
        self.assertEqual([(x["path"], x["line"], x["severity"]) for x in f], [("src/Foo.java", 42, "hoch"), ("src/Bar.java", 7, "klein")])
        self.assertEqual(f[1]["text"], "Name sagt wenig | ehrlich")
        self.assertTrue(all(x["from"] == "bericht" for x in f))

    def test_json_block(self):
        t = 'Hier:\n```json\n[{"file": "a/b.py", "line": "3", "message": "Off-by-one im Ende", "severity": "Major"},\n' \
            ' {"path": "c.ts", "comment": "Ohne Zeile, aber klar", "priority": "low"}, {"path": "", "text": "weg"}]\n```'
        f = rf.from_report(t)
        self.assertEqual([(x["path"], x["line"], x["severity"]) for x in f], [("a/b.py", 3, "hoch"), ("c.ts", 0, "klein")])

    def test_markdown_table(self):
        t = """## Befunde

| Schwere | Datei | Zeile | Befund |
|---|---|---|---|
| Hoch | `src/Foo.java` | 12 | Null wird nicht geprüft. |
| klein | src/Util.kt:30 | | Variable umbenennen. |
| – | nicht-ein-pfad | 1 | weg |
"""
        f = rf.from_report(t)
        self.assertEqual([(x["path"], x["line"], x["severity"], x["text"]) for x in f],
                         [("src/Foo.java", 12, "hoch", "Null wird nicht geprüft."), ("src/Util.kt", 30, "klein", "Variable umbenennen.")])

    def test_bullets_from_a_reply(self):
        t = """Bewertung: mit kleinen Punkten.

1. **Kritisch** `src/main/java/Export.java:88` – Umlaute gehen verloren, weil ohne UTF-8 geschrieben wird.
- `web/list.ts`, Zeile 14: Bei leerer Liste fehlt der Hinweis (AK2).
- Nit: src/style.css:3 Einrückung uneinheitlich.
- Gesamtbild gut, siehe README.md für die Doku.
- Tests laufen grün.
"""
        f = rf.from_report(t)
        self.assertEqual([(x["path"], x["line"], x["severity"]) for x in f],
                         [("src/main/java/Export.java", 88, "hoch"), ("web/list.ts", 14, "mittel"), ("src/style.css", 3, "klein")])
        self.assertTrue(f[0]["text"].startswith("Umlaute gehen verloren"))
        self.assertEqual(f[1]["text"], "Bei leerer Liste fehlt der Hinweis (AK2).")

    def test_block_wins_and_duplicates_go(self):
        t = "- `x.py:1` doppelt erwähnt im Text\n```findings\nx.py:1 | mittel | Einmal\nx.py:1 | mittel | Einmal\n```"
        self.assertEqual([x["text"] for x in rf.from_report(t)], ["Einmal"])
        self.assertEqual(rf.from_report("", None, "Alles gut, nichts zu beanstanden."), [])

    def test_clean_list_from_ui(self):
        out = rf.clean_list([{"path": "/src/A.java", "line": "5", "text": "  Gut  so? ", "severity": "hoch", "from": "bericht"},
                             {"path": "a b.java", "line": 1, "text": "Leerzeichen im Pfad"}, {"path": "x.go", "line": -3, "text": "neg", "severity": "riesig"},
                             "kein dict"])
        self.assertEqual(out, [{"path": "src/A.java", "line": 5, "text": "Gut so?", "severity": "hoch", "from": "bericht"},
                               {"path": "x.go", "line": 0, "text": "neg", "severity": "mittel", "from": "du"}])


REPORT = "**noch nicht**\n\n```findings\nsrc/Foo.java:12 | hoch | neu1 prüft null nicht\nREADME.md:0 | klein | Doku fehlt\n```\n"


class App(unittest.TestCase):
    def setUp(self):
        d = Path(tempfile.mkdtemp())
        c = server.load_config(None)
        c.update(data_dir=str(d / "data"), projects=[{"id": 1, "name": "dlp-core"}], connections=[],
                 agents=[{"id": "lokal", "name": "Qwen", "kind": "goose", "model": "qwen3", "cloud": False, "connection": "local", "workspace_root": str(d / "ws")}])
        self.app = server.App(c, False, {}, d / "config.json", watchdog=False)
        st = self.app.agents.store
        self.rid = st.agent_run_add("lokal", "1:feature-c", 1, "feature-c", "!9 Kollege C")
        st.agent_run_update(self.rid, status="fertig", phase="review", started=time.time() - 9, finished=time.time(),
                            mr=json.dumps({"host": "gitlab", "project_id": 1, "iid": 9, "sha": "fedcba0987654321", "target": "main"}))

    def test_collect_reads_report_when_no_finding_file(self):
        svc = self.app.agents
        svc.run_dir.mkdir(parents=True, exist_ok=True)
        for ext in ("summary.md", "findings"):                         # der Ordner der Läufe ist in allen Tests derselbe
            self.addCleanup(lambda p=svc.run_dir / ("%d.%s" % (self.rid, ext)): p.unlink(missing_ok=True))
        (svc.run_dir / ("%d.summary.md" % self.rid)).write_text(REPORT, encoding="utf-8")
        svc.collect(svc.store.agent_run(self.rid))
        got = json.loads(svc.store.agent_run(self.rid)["findings"])
        self.assertEqual([(x["path"], x["line"], x["from"]) for x in got], [("src/Foo.java", 12, "bericht"), ("README.md", 0, "bericht")])
        (svc.run_dir / ("%d.findings" % self.rid)).write_text('{"path": "src/Bar.java", "line": 3, "text": "über tinyops-finding", "severity": "klein"}\n')
        svc.collect(svc.store.agent_run(self.rid))
        got = json.loads(svc.store.agent_run(self.rid)["findings"])
        self.assertEqual([x["path"] for x in got], ["src/Bar.java"], "tinyops-finding hat Vorrang")

    def test_old_runs_read_at_view_time(self):
        self.app.agents.store.agent_run_update(self.rid, summary="", reply=REPORT)
        c = self.app.review_copy({"run": self.rid})
        self.assertEqual(c["count"], 2)
        self.assertTrue(c["text"].startswith("- **hoch** `src/Foo.java:12`"))

    def test_edit_reset_and_survives_collect(self):
        st = self.app.agents.store
        st.agent_run_update(self.rid, findings=json.dumps([{"path": "src/Foo.java", "line": 12, "text": "vom Agenten", "severity": "hoch"}]))
        out = self.app.review_findings({"run": self.rid, "findings": [
            {"path": "src/Foo.java", "line": 13, "text": "verschoben und umformuliert", "severity": "mittel", "from": "agent"},
            {"path": "src/Neu.java", "line": 0, "text": "von mir dazu", "severity": "klein"}, {"path": "../x", "line": 1, "text": "ungültig"}]})
        self.assertEqual(out["count"], 2)
        c = self.app.review_copy({"run": self.rid})
        self.assertIn("`src/Foo.java:13`: verschoben", c["text"])
        self.assertIn("`src/Neu.java`: von mir dazu", c["text"])
        self.app.agents.collect(st.agent_run(self.rid))                 # «Bericht neu einlesen» überschreibt deine Liste nicht
        self.assertEqual(self.app.review_copy({"run": self.rid})["count"], 2)
        self.app.review_findings({"run": self.rid, "reset": True})
        self.assertEqual(self.app.review_copy({"run": self.rid})["count"], 0, "collect hat inzwischen die (leere) Datei gelesen")
        self.assertTrue(any(r["action"] == "review.findings" for r in self.app.audit_log.export()))
        with self.assertRaises(server.UserError):
            self.app.review_findings({"run": self.rid, "findings": "kein liste"})

    def test_not_while_running(self):
        self.app.agents.store.agent_run_update(self.rid, status="läuft")
        with self.assertRaises(server.UserError):
            self.app.review_findings({"run": self.rid, "findings": []})

    def test_prompt_and_ui(self):
        p = (ROOT / "prompts" / "agent-mr-review.md").read_text(encoding="utf-8")
        self.assertIn("```findings", p)
        block = p.split("```findings", 1)[1].split("```", 1)[0]
        self.assertEqual(len(rf.from_report("```findings" + block + "```")), 1, "das Beispiel im Auftrag ist selbst lesbar")
        js = ui.source(ROOT)
        for s in ("/api/review/findings", "data-rvedit", "data-rvsave", "data-rvreset", "tinyops-finding</code> gemeldet"):
            self.assertIn(s, js)
        self.assertIn('"/api/review/findings"', (ROOT / "routes.py").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
