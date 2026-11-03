"""KI-Konten: Zeitfenster, Stand eintragen, automatischer Zähler fürs lokale Modell."""
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import links  # noqa: E402
import server  # noqa: E402


class AiStore(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.s = links.Store(Path(self.tmp.name) / "d" / "tinyops.db")

    def tearDown(self):
        self.tmp.cleanup()

    def test_window_math(self):
        i = self.s.ai_save(None, "Claude.ai", "claude", 5, 100, "%")
        a = self.s.ai_accounts()[0]
        self.assertEqual((a["running"], a["state"], a["left"]), (False, "free", 100.0))
        self.s.ai_set(i, used=70, resets_in_min=130)
        a = self.s.ai_accounts()[0]
        self.assertTrue(a["running"])
        self.assertEqual(a["left"], 30.0)
        self.assertAlmostEqual(a["secs_left"], 130 * 60, delta=5)
        self.s.ai_set(i, delta=15)
        self.assertEqual(self.s.ai_accounts()[0]["state"], "low")      # 15 von 100 übrig
        self.s.ai_set(i, delta=-500)
        self.assertEqual(self.s.ai_accounts()[0]["used"], 0.0)          # nie negativ
        self.s.ai_set(i, used=100)
        self.assertEqual(self.s.ai_accounts()[0]["state"], "empty")

    def test_window_expires(self):
        i = self.s.ai_save(None, "X", "claude", 1, 100, "%")
        self.s.ai_set(i, used=90, resets_in_min=0.5)
        with self.s._conn(True) as c:
            c.execute("update ai_accounts set window_start=? where id=?", (time.time() - 7200, i))
        a = self.s.ai_accounts()[0]
        self.assertEqual((a["running"], a["used"], a["left"]), (False, 0.0, 100.0))
        self.s.ai_set(i, delta=5)                                       # neues Fenster beginnt bei null
        a = self.s.ai_accounts()[0]
        self.assertEqual((a["running"], a["used"]), (True, 5.0))

    def test_validation(self):
        for args in (("", "claude", 5, 100, "%"), ("x" * 41, "claude", 5, 100, "%"), ("A", "nope", 5, 100, "%"),
                     ("A", "claude", "abc", 100, "%"), ("A", "claude", 0, 100, "%"), ("A", "claude", 5, -1, "%")):
            with self.assertRaises(links.LinkError):
                self.s.ai_save(None, *args)
        self.s.ai_save(None, "A", "claude", 5, 100, "%")
        with self.assertRaises(links.LinkError):
            self.s.ai_save(None, "A", "chatgpt", 5, 100, "%")           # Name doppelt
        with self.assertRaises(links.LinkError):
            self.s.ai_set(999, used=1)
        with self.assertRaises(links.LinkError):
            self.s.ai_set(1, resets_in_min=99999)

    def test_local_counter_and_no_budget(self):
        self.s.ai_save(None, "Lokal", "local", 24, 0, "Anfragen")
        self.s.ai_save(None, "Claude", "claude", 5, 100, "%")
        self.s.ai_bump("local"); self.s.ai_bump("local")
        a = {x["kind"]: x for x in self.s.ai_accounts()}
        self.assertEqual(a["local"]["used"], 2.0)
        self.assertIsNone(a["local"]["left"])
        self.assertEqual(a["claude"]["used"], 0.0)                      # andere Konten bleiben unberührt

    def test_delete_and_persist(self):
        i = self.s.ai_save(None, "A", "claude", 5, 100, "%")
        self.s.ai_set(i, used=10)
        again = links.Store(self.s.path)
        self.assertEqual(again.ai_accounts()[0]["used"], 10.0)
        again.ai_delete(i)
        self.assertEqual(again.ai_accounts(), [])
        self.s.ai_save(i, "A", "claude", 5, 100, "%") if False else None


class AiApp(unittest.TestCase):
    def test_overview_has_ai_and_actions(self):
        with tempfile.TemporaryDirectory() as d:
            cfg = server.load_config(None)
            cfg["data_dir"] = d
            cfg["features"] = dict(cfg["features"], ai=True)
            app = server.App(cfg, True, {}, Path("/nonexistent/c.json"))
            r = app.ai_action("save", {"name": "Mistral Vibe", "kind": "mistral", "window_hours": 5, "budget": 100, "unit": "%"})
            app.ai_action("set", {"id": r["id"], "used": 40, "resets_in_min": 60})
            ov = app.overview()
            self.assertEqual(ov["ai"][0]["left"], 60.0)
            with self.assertRaises(server.UserError):
                app.ai_action("save", {"name": "", "kind": "mistral", "window_hours": 5, "budget": 1})
            with self.assertRaises(server.UserError):
                app.ai_action("boom", {})
            app.ai_action("delete", {"id": r["id"]})
            self.assertEqual(app.overview()["ai"], [])

    def test_off_by_default(self):
        with tempfile.TemporaryDirectory() as d:
            cfg = server.load_config(None)
            cfg["data_dir"] = d
            app = server.App(cfg, True, {}, Path("/nonexistent/c.json"))
            app.ai_action("save", {"name": "X", "kind": "claude", "window_hours": 5, "budget": 100})
            self.assertEqual(app.overview()["ai"], [])        # Konten bleiben gespeichert, aber unsichtbar
            self.assertFalse(app.overview()["features"]["ai"])


if __name__ == "__main__":
    unittest.main()
