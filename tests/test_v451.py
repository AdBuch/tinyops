"""0.45.1: Co-Review des eigenen MR (Wunsch vom 27.11.): «Review mit Agent» auch für deine eigenen MRs, auch als Draft,
damit ein anderer Agent eine zweite Meinung gibt. Wer am MR mitgebaut hat, steht zuletzt in der Auswahl."""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("TINYOPS_HOME", tempfile.mkdtemp())
import server  # noqa: E402
import ui  # noqa: E402

MR = {"host": "gitlab", "project_id": 1, "iid": 29, "branch": "feature/DLP-103-labelo-client", "title": "Graph-Client Refactoring",
      "sha": "abcdef1234567890", "keys": ["DLP-103"], "url": "https://gitlab.example/mr/29", "draft": True}


class CoReview(unittest.TestCase):
    def setUp(self):
        d = Path(tempfile.mkdtemp())
        c = server.load_config(None)
        ws = str(d / "ws")
        c.update(data_dir=str(d / "data"), projects=[{"id": 1, "name": "dlp-core", "data_class": "internal"}], connections=[],
                 agents=[{"id": "claude", "name": "Claude", "kind": "claude", "connection": "local", "workspace_root": ws, "roles": {"review": "/reviewer"}},
                         {"id": "codex", "name": "Codex", "kind": "codex", "connection": "local", "workspace_root": ws},
                         {"id": "qwen", "name": "Qwen", "kind": "goose", "model": "qwen3", "cloud": False, "connection": "local", "workspace_root": ws}])
        self.app = app = server.App(c, False, {}, d / "config.json", watchdog=False)
        app.cache = {"mine": [MR], "review": [], "assigned": []}
        app.client = type("C", (), {"mr_detail": lambda self, pid, iid: {"description": "", "target_branch": "main"}})()
        app.ticket_brief = lambda key, title="": __import__("briefing").empty("jira", key, "Ticket nicht lesbar: 404")
        self.started = []
        app.agents.start = lambda rid, prompt, pid=None, branch=None, phase="develop", **k: self.started.append((rid, prompt, phase))
        self.ref = {"host": "gitlab", "project_id": 1, "iid": 29}
        st = app.agents.store                                # Claude hat das Ticket entwickelt, Codex auf dem Branch nachgebessert
        st.agent_run_update(st.agent_run_add("claude", "DLP-103", 1, MR["branch"], "Entwickeln"), phase="develop", status="fertig")
        st.agent_run_update(st.agent_run_add("codex", "1:other", 1, MR["branch"], "Nachbessern"), phase="develop", status="fertig")

    def test_options_know_own_draft_and_who_built_it(self):
        o = self.app.review_options(self.ref)
        self.assertEqual((o["mine"], o["draft"]), (True, True))
        self.assertEqual([(a["id"], a["built"]) for a in o["agents"]], [("qwen", False), ("claude", True), ("codex", True)],
                         "wer nicht mitgebaut hat, ist vorgewählt, auch vor der Rolle Review")

    def test_start_tells_the_reviewer_it_is_a_co_review_of_a_draft(self):
        out = self.app.review_start(dict(self.ref, goal="Ist der Client so testbar?"))
        rid, prompt, phase = self.started[0]
        self.assertEqual((out["agent"], phase), ("Qwen", "review"))
        self.assertIn("## Wessen MR", prompt)
        self.assertIn("eigene MR des Menschen", prompt)
        self.assertIn("noch ein Entwurf (Draft)", prompt)
        self.assertIn("Ist der Client so testbar?", prompt)
        self.assertNotIn("weder Beschreibung noch Ticket", prompt, "ein Ziel ist da")
        self.assertTrue(json.loads(self.app.store.agent_run(rid)["mr"])["mine"])
        st = self.app.review_state(self.ref)
        self.assertEqual([r["id"] for r in st["runs"]], [rid])

    def test_colleague_mr_unchanged(self):
        self.app.cache = {"mine": [], "review": [dict(MR, draft=False)], "assigned": []}
        self.app.review_start(dict(self.ref, agent="claude"))
        prompt = self.started[0][1]
        self.assertNotIn("Wessen MR", prompt)
        self.assertNotIn("Draft", prompt)
        self.assertFalse(self.app.review_options(self.ref)["mine"])

    def test_chosen_builder_is_allowed(self):
        out = self.app.review_start(dict(self.ref, agent="claude"))
        self.assertEqual(out["agent"], "Claude", "erlaubt, die Oberfläche warnt nur")

    def test_ui(self):
        js = ui.source(ROOT)
        for s in ("function rvMrs(e)", "e.t !== 'card'", "Co-Review mit Agent", "data-rvpick", "hat mitgebaut", "Für eine echte zweite Meinung"):
            self.assertIn(s, js)
        self.assertIn("if (rvOk(e)) body += rvHtml(e);               // 0.45.1", (ROOT / "static" / "js" / "detail.js").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
