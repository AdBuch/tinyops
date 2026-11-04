"""Fortschritt der Synchronisation und Zwischenergebnisse (Demo-Daten mit künstlicher Verzögerung)."""
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import server  # noqa: E402


class SyncTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        os.environ["TINYOPS_DEMO_DELAY"] = "0.25"
        cfg = server.load_config(None)
        cfg["data_dir"] = self.tmp.name
        cfg["jira"] = {"url": "https://jira.example", "project_keys": ["DLP"], "wip_issue_types": ["Story"]}
        self.app = server.App(cfg, True, {}, Path("/nonexistent/c.json"))

    def tearDown(self):
        os.environ.pop("TINYOPS_DEMO_DELAY", None)
        self.tmp.cleanup()

    def test_defaults_sync_rarely_and_branches_get_create_mr_link(self):
        self.assertEqual(server.DEFAULTS["cache_seconds"], 300)               # GitLab/Jira nur alle 5 Minuten
        self.assertEqual(server.USAGE_DEFAULTS["cache_seconds"], 300)
        self.assertEqual(self.app.cfg["cache_seconds"], 300)
        ov = self.app.overview()
        br = [i for i in ov["mine"] if i["kind"] == "branch"]
        self.assertTrue(br)
        for b in br:
            self.assertIn("/-/merge_requests/new?merge_request%5Bsource_branch%5D=", b["create_mr_url"])
        self.assertTrue(all(not i.get("create_mr_url") for i in ov["mine"] if i["kind"] == "mr"))
        card = next(c for c in ov["board"]["cards"] for x in c["items"] if x["iid"] is None)
        self.assertTrue(any(x["create_mr_url"] for x in card["items"] if x["iid"] is None))

    def test_overview_returns_immediately_with_progress_and_partial_data(self):
        t0 = time.time()
        ov = self.app.overview(wait=False)
        self.assertLess(time.time() - t0, 0.2)            # kein Warten auf GitLab
        self.assertTrue(ov["loading"])
        self.assertTrue(ov["sync"]["running"])
        time.sleep(0.1)
        ids = [s["id"] for s in self.app.sync_view()["steps"]]
        self.assertIn("gl-review", ids)
        time.sleep(0.8)
        mid = self.app.overview(wait=False)
        self.assertTrue(mid["loading"] and mid["sync"]["running"])
        self.assertTrue(mid["mine"], "schon geladene Projekte sollen sofort sichtbar sein")
        self.assertTrue(mid["sync"]["done"] >= 2)
        end = time.time() + 10
        while self.app.sync_view()["running"] and time.time() < end:
            time.sleep(0.05)
        fin = self.app.overview(wait=False)
        self.assertFalse(fin["loading"])
        self.assertFalse(fin["sync"]["running"])
        self.assertTrue(all(s["status"] in ("ok", "err") for s in fin["sync"]["steps"]))
        self.assertGreater(len(fin["mine"]), len(mid["mine"]) - 1)
        self.assertTrue(fin["jira"]["ok"])

    def test_second_refresh_keeps_showing_cached_data(self):
        self.app.overview()                                # blockierend: Cache füllen
        self.app.cache_t = 0.0
        ov = self.app.overview(wait=False)
        self.assertFalse(ov["loading"])                    # alte Daten bleiben stehen
        self.assertTrue(ov["mine"])
        self.assertTrue(ov["sync"]["running"])             # und der Abgleich läuft im Hintergrund

    def test_only_one_sync_at_a_time(self):
        self.assertTrue(self.app.start_sync())
        self.assertFalse(self.app.start_sync())
        self.app._sync_thread.join()

    def test_crash_in_sync_is_reported_not_swallowed(self):
        self.app.client.fetch = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("kaputt"))
        ov = self.app.overview()
        self.assertFalse(ov["sync"]["running"])
        self.assertTrue(any("kaputt" in e for e in ov["errors"]))


if __name__ == "__main__":
    unittest.main()
