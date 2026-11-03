"""Manuelle Ticket-Verknüpfungen und Pools (nur lokal gespeichert)."""
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import links  # noqa: E402
import server  # noqa: E402


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "d" / "tinyops.db"
        self.s = links.Store(self.path)

    def tearDown(self):
        self.tmp.cleanup()

    def test_nothing_is_created_by_reading(self):
        self.assertEqual(self.s.links(), {})
        self.assertEqual(self.s.pools(), [])
        self.assertFalse(self.path.exists())

    def test_link_unlink_and_overwrite(self):
        self.assertEqual(self.s.link(1, "feature/x", "dlp-5568"), "DLP-5568")
        self.assertEqual(self.s.links(), {"1:feature/x": "DLP-5568"})
        self.s.link(1, "feature/x", "DLP-1")
        self.assertEqual(self.s.links()["1:feature/x"], "DLP-1")
        self.assertTrue(self.s.unlink(1, "feature/x"))
        self.assertFalse(self.s.unlink(1, "feature/x"))
        self.assertEqual(self.s.links(), {})
        for bad in ("", "abc", "DLP-", "DLP 12", "1-2", "DLP-12; drop"):
            with self.assertRaises(links.LinkError):
                self.s.link(1, "b", bad)

    def test_pools(self):
        pid = self.s.add_pool("  Agenten-VM ")
        with self.assertRaises(links.LinkError):
            self.s.add_pool("Agenten-VM")
        self.assertEqual(self.s.add_item(pid, "ticket", "ops-7"), "OPS-7")
        self.s.add_item(pid, "ticket", "OPS-7")   # doppelt: kein Fehler, kein zweiter Eintrag
        self.s.add_item(pid, "ref", "1:agent/sonar")
        p = self.s.pools()[0]
        self.assertEqual((p["name"], [(i["kind"], i["value"]) for i in p["items"]]), ("Agenten-VM", [("ticket", "OPS-7"), ("ref", "1:agent/sonar")]))
        self.assertEqual(self.s.pool_tickets(), ["OPS-7"])
        self.s.rename_pool(pid, "Agenten")
        self.assertTrue(self.s.remove_item(pid, "ticket", "OPS-7"))
        self.assertFalse(self.s.remove_item(pid, "ticket", "OPS-7"))
        for args in ((pid, "ref", "kaputt"), (pid, "x", "y"), (999, "ticket", "A-1")):
            with self.assertRaises(links.LinkError):
                self.s.add_item(*args)
        self.s.delete_pool(pid)
        self.assertEqual(self.s.pools(), [])
        with self.assertRaises(links.LinkError):
            self.s.delete_pool(pid)

    def test_survives_restart(self):
        self.s.link(2, "b", "DLP-9")
        pid = self.s.add_pool("P")
        self.s.add_item(pid, "ticket", "DLP-9")
        again = links.Store(self.path)
        self.assertEqual(again.links(), {"2:b": "DLP-9"})
        self.assertEqual(again.pool_tickets(), ["DLP-9"])


class AppFlow(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        cfg = server.load_config(None)
        cfg["data_dir"] = self.tmp.name
        cfg["jira"] = {"url": "https://jira.example", "project_keys": ["DLP"], "wip_issue_types": ["Story"]}
        self.app = server.App(cfg, True, {}, Path("/nonexistent/c.json"))

    def tearDown(self):
        self.tmp.cleanup()

    def item(self, ov, branch):
        return next(i for i in ov["mine"] + ov["review"] + ov["assigned"] if i["branch"] == branch)

    def test_manual_link_overrides_name_and_can_be_removed(self):
        ov = self.app.overview()
        b = "feature/proxo-mapping"
        self.assertTrue(self.item(ov, b)["no_ticket"])
        self.app.link_ticket({"project_id": 1, "branch": b, "ticket": "dlp-102"})
        ov = self.app.overview()
        it = self.item(ov, b)
        self.assertEqual(it["ticket"]["key"], "DLP-102")
        self.assertEqual(it["manual_link"], "DLP-102")
        self.assertFalse(it["no_ticket"])
        story = next(s for s in ov["jira"]["stories"] if s["key"] == "DLP-102")
        self.assertTrue(any(x["branch"] == b and x["manual"] for x in story["items"]))
        # automatisch erkannter Key wird überstimmt
        auto = "feature/DLP-101-vendex-retry"
        self.assertEqual(self.item(ov, auto)["ticket"]["key"], "DLP-101")
        self.app.link_ticket({"project_id": 1, "branch": auto, "ticket": "DLP-102"})
        self.assertEqual(self.item(self.app.overview(), auto)["ticket"]["key"], "DLP-102")
        # lösen: die automatische Erkennung greift wieder
        self.assertTrue(self.app.unlink_ticket({"project_id": 1, "branch": auto})["removed"])
        self.assertEqual(self.item(self.app.overview(), auto)["ticket"]["key"], "DLP-101")
        self.assertEqual(self.item(self.app.overview(), auto)["manual_link"], "")

    def test_link_validation(self):
        with self.assertRaises(server.UserError):
            self.app.link_ticket({"project_id": 1, "branch": "x", "ticket": "kein key"})
        with self.assertRaises(server.UserError) as c:
            self.app.link_ticket({"project_id": 1, "branch": "x", "ticket": "DLP-99999"})
        self.assertIn("gibt es in Jira nicht", str(c.exception))
        with self.assertRaises(server.UserError):
            self.app.link_ticket({"project_id": "x", "branch": "x", "ticket": "DLP-1"})

    def test_pools_show_tickets_and_branches(self):
        pid = self.app.pool_action("create", {"name": "Agenten-VM"})["id"]
        self.app.pool_action("add", {"id": pid, "kind": "ticket", "value": "DLP-120"})   # liegt nicht im aktiven Sprint
        self.app.pool_action("add", {"id": pid, "kind": "ref", "project_id": 1, "branch": "agent/sonar-wave-1"})
        self.app.pool_action("add", {"id": pid, "kind": "ref", "project_id": 1, "branch": "gibt-es-nicht-mehr"})
        pool = self.app.overview()["pools"][0]
        self.assertEqual(pool["name"], "Agenten-VM")
        t = pool["tickets"][0]
        self.assertEqual((t["key"], t["known"]), ("DLP-120", True))
        self.assertTrue(t["summary"])
        by_branch = {r["branch"]: r for r in pool["refs"]}
        self.assertFalse(by_branch["agent/sonar-wave-1"]["missing"])
        self.assertTrue(by_branch["gibt-es-nicht-mehr"]["missing"])
        self.assertEqual(self.app.overview()["jira"]["count"], 3)   # ein Pool zählt nicht zum Story-Limit
        with self.assertRaises(server.UserError):
            self.app.pool_action("add", {"id": pid, "kind": "ticket", "value": "DLP-99999"})
        self.app.pool_action("remove", {"id": pid, "kind": "ref", "project_id": 1, "branch": "gibt-es-nicht-mehr"})
        self.app.pool_action("remove", {"id": pid, "kind": "ticket", "value": "DLP-120"})
        self.assertEqual(len(self.app.overview()["pools"][0]["refs"]), 1)
        self.app.pool_action("delete", {"id": pid})
        self.assertEqual(self.app.overview()["pools"], [])


if __name__ == "__main__":
    unittest.main()
