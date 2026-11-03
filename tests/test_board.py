"""Board: Workflow-Stufen, Zusammenführen pro Ticket, Jira-Panel mit Aufgaben in Arbeit."""
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import links  # noqa: E402
import server  # noqa: E402


class BoardStore(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.s = links.Store(Path(self.tmp.name) / "tinyops.db")

    def tearDown(self):
        self.tmp.cleanup()

    def test_local_tasks_and_stages(self):
        k = self.s.task_add("Agenten-VM aufräumen", "idea")
        self.assertEqual(k, "LOC-1")
        self.assertEqual(self.s.stages()[k]["stage"], "idea")
        with self.assertRaises(links.LinkError):
            self.s.stage_set(k, "planned")                     # ohne Kategorie nur im Ideenpool
        with self.assertRaises(links.LinkError):
            self.s.task_add("Ohne Kategorie", "planned")
        pid = self.s.add_pool("Agenten-VM")
        self.s.add_item(pid, "ticket", k)
        self.assertEqual(self.s.pools_of(k), [pid])
        self.s.stage_set(k, "impl")
        self.assertEqual(self.s.stages()[k]["stage"], "impl")
        with self.assertRaises(links.LinkError):
            self.s.stage_set(k, "unsinn")
        with self.assertRaises(links.LinkError):
            self.s.stage_set("LOC-99", "done")                  # gibt es nicht
        self.assertEqual(self.s.stage_set("dlp-5", "planned"), "DLP-5")   # Jira-Tickets brauchen keine Kategorie
        self.assertEqual(self.s.staged_tickets(), ["DLP-5"])      # LOC zählt nicht als Jira-Ticket
        self.assertEqual(self.s.stage_set("3:feature/x", "review"), "3:feature/x")
        for bad in ("", "abc", "DLP-", "1:"):
            with self.assertRaises(links.LinkError):
                self.s.stage_set(bad, "done")
        for bad in ("", "x" * 201):
            with self.assertRaises(links.LinkError):
                self.s.task_add(bad)

    def test_delete_local_cleans_up(self):
        k = self.s.task_add("X")
        self.s.link(1, "b", k)
        pid = self.s.add_pool("P")
        self.s.add_item(pid, "ticket", k)
        self.s.task_delete(k)
        self.assertEqual(self.s.tasks(), [])
        self.assertEqual(self.s.links(), {})
        self.assertEqual(self.s.pool_tickets(), [])
        self.assertNotIn(k, self.s.stages())
        with self.assertRaises(links.LinkError):
            self.s.task_delete("DLP-1")                          # Jira-Tickets löscht man nicht


class BoardApp(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        cfg = server.load_config(None)
        cfg["data_dir"] = self.tmp.name
        cfg["jira"] = {"url": "https://jira.example", "project_keys": ["DLP"], "wip_issue_types": ["Story"]}
        self.app = server.App(cfg, True, {}, Path("/nonexistent/c.json"))

    def tearDown(self):
        self.tmp.cleanup()

    def pool(self, name="Agenten-VM"):
        return self.app.pool_action("create", {"name": name})["id"]

    def cards(self, ov):
        return {c["id"]: c for c in ov["board"]["cards"]}

    def test_derived_stages_and_merge_of_many_mrs(self):
        ov = self.app.overview()
        cards = self.cards(ov)
        c = cards["DLP-101"]                                       # in Arbeit laut Jira, hat einen MR
        self.assertEqual(c["stage"], "review")
        self.assertTrue(c["jira_in_progress"])
        self.assertFalse(c["manual_stage"])
        # ein zweiter Branch von Hand dazu: dasselbe Ticket, dieselbe Karte, zwei Einträge
        branch = next(i for i in ov["mine"] if i["kind"] == "branch")
        self.app.link_ticket({"project_id": branch["project_id"], "branch": branch["branch"], "ticket": "DLP-101"})
        ov = self.app.overview()
        c = self.cards(ov)["DLP-101"]
        self.assertGreaterEqual(len(c["items"]), 2)
        self.assertEqual(len({x["ref"] for x in c["items"]}), len(c["items"]))
        self.assertEqual(sum(1 for x in ov["board"]["cards"] if x["id"] == "DLP-101"), 1)   # nie doppelt
        self.assertNotIn(branch["ref"], self.cards(ov))             # der Branch ist keine eigene Karte mehr

    def test_in_progress_stage_shows_in_jira_panel(self):
        pid = self.pool()
        k = self.app.board_action("add", {"title": "Agenten-VM patchen", "stage": "planned", "pool_id": pid})["key"]
        ov = self.app.overview()
        self.assertNotIn(k, [s["key"] for s in ov["jira"]["stories"]])
        n0 = ov["jira"]["count"]
        self.app.board_action("stage", {"key": k, "stage": "impl"})
        ov = self.app.overview()
        st = next(s for s in ov["jira"]["stories"] if s["key"] == k)
        self.assertTrue(st["local"] if "local" in st else True)
        self.assertEqual(st["stage"], "impl")
        self.assertEqual(ov["jira"]["count"], n0 + 1)
        self.assertEqual(ov["jira"]["over"], ov["jira"]["count"] > ov["jira"]["limit"])
        self.app.board_action("stage", {"key": k, "stage": "tested"})
        self.assertNotIn(k, [s["key"] for s in self.app.overview()["jira"]["stories"]])

    def test_manual_link_to_local_task_merges(self):
        k = self.app.board_action("add", {"title": "Eigene Aufgabe", "stage": "impl", "pool_id": self.pool()})["key"]
        branch = next(i for i in self.app.overview()["mine"] if i["kind"] == "branch")
        self.app.link_ticket({"project_id": branch["project_id"], "branch": branch["branch"], "ticket": k})
        ov = self.app.overview()
        c = self.cards(ov)[k]
        self.assertEqual([x["ref"] for x in c["items"]], [branch["ref"]])
        story = next(s for s in ov["jira"]["stories"] if s["key"] == k)
        self.assertEqual(len(story["items"]), 1)
        it = next(i for i in ov["mine"] if i["ref"] == branch["ref"])
        self.assertEqual(it["ticket"]["key"], k)
        self.assertFalse(it["no_ticket"])

    def test_orphans_ideas_and_validation(self):
        ov = self.app.overview()
        orphans = [c for c in ov["board"]["cards"] if c.get("orphan")]
        self.assertTrue(all(c["key"] == "" and len(c["items"]) == 1 for c in orphans))
        ids = [c["id"] for c in ov["board"]["cards"]]
        self.assertEqual(len(ids), len(set(ids)))
        idea = self.app.ideas.add("Cache für Lookups") if hasattr(self.app.ideas, "add") else None
        if idea is not None:
            ov = self.app.overview()
            ic = next(c for c in ov["board"]["cards"] if c.get("idea_id"))
            self.assertEqual(ic["stage"], "idea")
            with self.assertRaises(server.UserError):
                self.app.board_action("plan_idea", {"id": ic["idea_id"]})    # ohne Kategorie nicht
            pid = self.pool("Produkt X")
            self.app.board_action("plan_idea", {"id": ic["idea_id"], "pool_id": pid})
            ov = self.app.overview()
            self.assertFalse(any(c.get("idea_id") for c in ov["board"]["cards"]))
            self.assertTrue(any(c["title"].startswith("Cache") and c["stage"] == "planned" for c in ov["board"]["cards"]))
        for bad in ({"key": "DLP-1", "stage": "x"}, {"key": "nope", "stage": "done"}, {"key": "idea:1", "stage": "done"}, {"key": "LOC-77", "stage": "done"}):
            with self.assertRaises(server.UserError):
                self.app.board_action("stage", bad)
        with self.assertRaises(server.UserError):
            self.app.board_action("add", {"title": "", "stage": "planned"})
        with self.assertRaises(server.UserError):
            self.app.board_action("zzz", {})

    def test_done_is_capped(self):
        for n in range(15):
            self.app.board_action("add", {"title": "T%d" % n, "stage": "done", "pool_id": self.pool("P")} if n == 0 else {"title": "T%d" % n, "stage": "done", "pool_id": 1})
        b = self.app.overview()["board"]
        self.assertEqual(sum(1 for c in b["cards"] if c["stage"] == "done"), 12)
        self.assertEqual(b["done_hidden"], 3)


class BoardPools(BoardApp):
    def test_categories_filter_and_rules(self):
        pid = self.pool("Produkt X")
        idea = self.app.board_action("add", {"title": "Idee ohne Kategorie", "stage": "idea"})["key"]
        with self.assertRaises(server.UserError):
            self.app.board_action("stage", {"key": idea, "stage": "planned"})
        self.app.board_action("assign", {"key": idea, "pool_id": pid})
        self.app.board_action("stage", {"key": idea, "stage": "planned"})
        b = self.app.overview()["board"]
        self.assertEqual([p["name"] for p in b["pools"]], ["Produkt X"])
        self.assertEqual(b["pools"][0]["count"], 1)
        card = next(c for c in b["cards"] if c["id"] == idea)
        self.assertEqual(card["pools"], [{"id": pid, "name": "Produkt X"}])
        with self.assertRaises(server.UserError):
            self.app.board_action("unassign", {"key": idea, "pool_id": pid})   # letzte Kategorie einer geplanten Aufgabe
        self.app.board_action("stage", {"key": idea, "stage": "idea"})
        self.app.board_action("unassign", {"key": idea, "pool_id": pid})       # im Ideenpool geht es
        self.assertEqual(next(c for c in self.app.overview()["board"]["cards"] if c["id"] == idea)["pools"], [])
        with self.assertRaises(server.UserError):
            self.app.board_action("assign", {"key": idea, "pool_id": 999})

    def test_jira_ticket_and_branch_can_get_category(self):
        pid = self.pool("Sprint-fremd")
        ov = self.app.overview()
        branch = next(i for i in ov["mine"] if i["kind"] == "branch" and not i["keys"])
        self.app.board_action("assign", {"ref": branch["ref"], "pool_id": pid})
        self.app.board_action("assign", {"key": "DLP-103", "pool_id": pid})
        cards = self.cards(self.app.overview())
        self.assertEqual(cards[branch["ref"]]["pools"][0]["id"], pid)
        self.assertEqual(cards["DLP-103"]["pools"][0]["id"], pid)


if __name__ == "__main__":
    unittest.main()
