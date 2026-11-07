"""Fester Ablauf je Vorhaben: Station, nächster Schritt, Übersteuerung, Agenten, Teilschritte, Spielstand."""
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import flow  # noqa: E402
import links  # noqa: E402
import server  # noqa: E402


def mr(**kw):
    d = {"kind": "mr", "iid": 7, "url": "https://gl/mr/7", "pipeline": "success", "draft": False, "merge_status": "mergeable", "sonar": "OK",
         "project_id": 1, "branch": "feature/X-1", "pipeline_url": "https://gl/p/1", "sha": "a" * 40}
    d.update(kw)
    d.setdefault("ref", "%s:%s" % (d["project_id"], d["branch"]))
    return d


OK = {"1:feature/X-1": {"sha": "a" * 40, "ts": time.time(), "note": "", "env": ""}}   # Abnahme auf dem aktuellen Commit


def card(items=(), **kw):
    d = {"id": "X-1", "key": "X-1", "title": "Titel", "items": list(items), "stage": "planned", "manual_stage": False, "jira_in_progress": False}
    d.update(kw)
    return d


def nxt(c, **kw):
    if c.get("manual_stage") and c.get("stage") in ("tested", "done") and "acceptance" not in kw:
        kw["acceptance"] = OK
    d = flow.derive(c, **kw)
    return d["phase_id"], d["next"]["kind"], d["next"]["id"]


class Derive(unittest.TestCase):
    def test_strecke_aus_den_daten(self):
        self.assertEqual(nxt(card()), ("plan", "do", "start"))
        self.assertEqual(nxt(card(jira_in_progress=True)), ("branch", "do", "branch"))
        self.assertEqual(nxt(card([{"kind": "branch", "branch": "b", "ahead": 3, "create_mr_url": "u"}])), ("code", "do", "mr_create"))
        self.assertEqual(nxt(card([mr(draft=True)])), ("mr", "do", "ready"))
        self.assertEqual(nxt(card([mr(pipeline="failed")])), ("check", "blocked", "pipeline"))
        self.assertEqual(nxt(card([mr(merge_status="conflict")])), ("check", "blocked", "rebase"))
        self.assertEqual(nxt(card([mr(sonar="ERROR")])), ("check", "blocked", "sonar"))
        self.assertEqual(nxt(card([mr(pipeline="running")])), ("check", "wait", "ci"))
        self.assertEqual(nxt(card([mr(merge_status="not_approved")])), ("check", "wait", "review"))
        self.assertEqual(nxt(card([mr(merge_status="discussions_not_resolved")])), ("check", "do", "threads"))
        self.assertEqual(nxt(card([mr()])), ("test", "do", "test"))

    def test_branch_command_and_links(self):
        d = flow.derive(card(jira_in_progress=True, title="Retry bei 429"))
        self.assertEqual(d["next"]["action"]["copy"], "git switch -c feature/X-1-retry-bei-429")
        d = flow.derive(card([mr(pipeline="failed")]))
        self.assertEqual(d["next"]["action"]["url"], "https://gl/p/1")
        d = flow.derive(card([mr(sonar="ERROR")]))
        self.assertEqual(d["next"]["action"]["report"]["iid"], 7)

    def test_bottleneck_mr_decides(self):
        self.assertEqual(nxt(card([mr(), mr(iid=8, pipeline="failed")])), ("check", "blocked", "pipeline"))

    def test_override(self):
        self.assertEqual(nxt(card([mr()], stage="tested", manual_stage=True)), ("merge", "do", "merge"))
        self.assertEqual(nxt(card([mr()], stage="done", manual_stage=True)), ("done", "done", "done"))
        # Übersteuern versteckt keinen Blocker
        self.assertEqual(nxt(card([mr(pipeline="failed")], stage="tested", manual_stage=True)), ("merge", "blocked", "pipeline"))
        self.assertEqual(nxt(card([mr(pipeline="running")], stage="tested", manual_stage=True)), ("merge", "wait", "ci"))
        d = flow.derive(card([mr()], stage="tested", manual_stage=True))
        self.assertTrue(d["override"])

    def test_acceptance_bound_to_commit(self):
        c = card([mr()], stage="tested", manual_stage=True)
        self.assertEqual(nxt(c, acceptance=OK), ("merge", "do", "merge"))
        d = flow.derive(c, acceptance={"1:feature/X-1": {"sha": "b" * 40, "ts": time.time(), "note": "", "env": ""}})
        self.assertEqual((d["phase_id"], d["next"]["id"]), ("test", "retest"))
        self.assertIn("bbbbbbbb → aaaaaaaa", d["next"]["why"])
        self.assertIn("Abnahme veraltet", d["flags"])
        self.assertEqual(d["complete_to"], "tested")
        d = flow.derive(c, acceptance=None)              # vor 0.15 gesetzt: ohne Commit
        self.assertEqual(d["next"]["id"], "retest")
        self.assertIn("Abnahme ohne Commit", d["flags"])
        # auch «Fertig» mit offenem MR braucht eine gültige Abnahme
        self.assertEqual(nxt(card([mr()], stage="done", manual_stage=True), acceptance={}), ("test", "do", "retest"))
        # Blocker bleiben vorne
        self.assertEqual(nxt(card([mr(pipeline="failed")], stage="tested", manual_stage=True), acceptance={}), ("test", "blocked", "pipeline"))
        # gemergt (kein offener MR): keine Abnahme nötig
        self.assertEqual(nxt(card([], stage="done", manual_stage=True), acceptance={}), ("done", "done", "done"))
        # Ansicht für das Panel
        v = flow.derive(c, acceptance=OK)["acceptance"]
        self.assertEqual((v[0]["state"], v[0]["sha"]), ("ok", "aaaaaaaa"))
        self.assertTrue(flow.derive(card([mr()]))["next"]["action"]["accept"])

    def test_merged_mr_disappears(self):
        self.assertEqual(nxt(card(jira_in_progress=True), seen_max=5), ("merge", "do", "close"))
        self.assertEqual(flow.derive(card(jira_in_progress=True), seen_max=5)["next"]["action"]["stage"], "done")

    def test_agents(self):
        run = {"id": 3, "status": "läuft", "agent_name": "claude", "started": time.time() - 120}
        self.assertEqual(nxt(card(jira_in_progress=True), runs=[run]), ("branch", "wait", "agent"))
        self.assertEqual(nxt(card([mr(pipeline="failed")]), runs=[dict(run, status="fehlgeschlagen")]), ("check", "blocked", "pipeline"))
        self.assertEqual(nxt(card(jira_in_progress=True), runs=[dict(run, status="fehlgeschlagen")]), ("branch", "blocked", "agent_failed"))
        self.assertEqual(nxt(card(jira_in_progress=True), runs=[dict(run, status="fertig")]), ("branch", "do", "agent_result"))
        self.assertEqual(nxt(card(jira_in_progress=True), runs=[dict(run, status="zugewiesen")]), ("branch", "do", "agent_start"))

    def test_checklist_is_the_smallest_next_step(self):
        cl = [{"id": 1, "text": "Test schreiben", "done": 1}, {"id": 2, "text": "Retry einbauen", "done": 0}]
        d = flow.derive(card([{"kind": "branch", "branch": "b"}]), checklist=cl)
        self.assertEqual((d["next"]["id"], d["next"]["label"], d["next"]["action"]["check"]), ("check", "Retry einbauen", 2))
        self.assertEqual(d["next"]["action"]["then"]["id"], "mr_create")
        self.assertEqual(d["checks"], {"done": 1, "total": 2})
        self.assertEqual(nxt(card([mr(pipeline="failed")]), checklist=cl), ("check", "blocked", "pipeline"))

    def test_review_and_approval(self):
        self.assertEqual(nxt(card([mr(reviewers=[], approved=False)])), ("check", "do", "reviewer"))
        self.assertEqual(nxt(card([mr(reviewers=["anna"], approved=False)])), ("check", "wait", "review"))
        self.assertEqual(nxt(card([mr(reviewers=["anna"], approved=False, upvotes=1)])), ("test", "do", "test"))
        self.assertEqual(nxt(card([mr(reviewers=["anna"], approved=True, approved_by=["anna"])])), ("test", "do", "test"))
        # Regeln verlangen noch eine Freigabe: der Daumen reicht nicht
        self.assertEqual(nxt(card([mr(reviewers=["anna"], upvotes=2, approved=False, approvals_left=1)])), ("check", "wait", "review"))
        # Merge erst mit Freigabe, auch wenn von Hand auf «Getestet» gesetzt
        self.assertEqual(nxt(card([mr(reviewers=["anna"], approved=False)], stage="tested", manual_stage=True)), ("merge", "wait", "review"))
        self.assertIn("@anna", flow.derive(card([mr(reviewers=["anna"], approved=False)]))["next"]["why"])
        self.assertEqual(nxt(card([mr()])), ("test", "do", "test"))      # Quelle liefert nichts dazu: nicht blockieren

    def test_unknown_is_not_green(self):
        self.assertEqual(nxt(card([mr(reviewers=["anna"], approval_unknown=True)])), ("check", "do", "check_approval"))
        d = flow.derive(card([mr(approval_unknown=True)]))
        self.assertIn("nicht lesbar", d["next"]["why"])
        self.assertEqual(d["complete_to"], "test")          # du kannst es nach eigener Prüfung weiterschieben
        self.assertIn("veraltet", flow.derive(card([mr(outdated=True)]))["flags"])

    def test_github_labels(self):
        d = flow.derive(card([mr(host="github", pipeline="failed", iid=12)]))
        self.assertIn("PR #12", d["next"]["why"])

    def test_branch_needs_ticket(self):
        d = flow.derive(card([{"kind": "branch", "branch": "fix/x", "project_id": 3, "project": "core", "title": "WIP fix"}], key="", id="3:fix/x"))
        self.assertEqual((d["next"]["kind"], d["next"]["id"]), ("blocked", "ticket"))
        self.assertEqual(d["next"]["action"]["tiny"], {"project_id": 3, "branch": "fix/x", "title": "WIP fix", "project": "core"})
        self.assertIsNone(d["complete_to"])
        d = flow.derive(card([mr(pipeline="failed")], key="", id="1:feature/X-1"))
        self.assertEqual(d["next"]["id"], "ticket")

    def test_complete_to(self):
        self.assertEqual(flow.derive(card())["complete_to"], "impl")
        self.assertEqual(flow.derive(card([mr()]))["complete_to"], "tested")
        self.assertEqual(flow.next_stage(4), "test")
        self.assertIsNone(flow.next_stage(7))

    def test_orphan_flag_and_ideas(self):
        d = flow.derive(card([{"kind": "branch", "branch": "b"}], key="", id="1:b"))
        self.assertIn("ohne Ticket", d["flags"])
        self.assertEqual(nxt(card(idea_id=4, key="", id="idea:4", stage="idea", manual_stage=True)), ("plan", "do", "plan"))

    def test_priority(self):
        blocked = flow.derive(card([mr(pipeline="failed")]))
        draft = flow.derive(card([mr(draft=True)]))
        plan = flow.derive(card())
        wait = flow.derive(card([mr(pipeline="running")]))
        p = lambda d: flow.priority(card(), d)
        self.assertGreater(p(blocked), p(draft))
        self.assertGreater(p(draft), p(plan))
        self.assertLess(p(wait), 0)


class Score(unittest.TestCase):
    def setUp(self):
        self.st = links.Store(Path(tempfile.mkdtemp()) / "t.db")

    def test_points_only_for_new_stations(self):
        st, t = self.st, time.time()
        self.assertEqual(st.flow_record([("X-1", "X-1", "T", 2)], t), [])          # neu: keine Punkte
        self.assertEqual(st.flow_record([("X-1", "X-1", "T", 4)], t), [("X-1", 4, 20)])
        self.assertEqual(st.flow_record([("X-1", "X-1", "T", 2)], t), [])          # zurück
        self.assertEqual(st.flow_record([("X-1", "X-1", "T", 4)], t), [])          # wieder vor: schon erreicht
        self.assertEqual(st.flow_record([("X-1", "X-1", "T", 7)], t), [("X-1", 7, 60)])  # Fertig mit Bonus
        s = st.flow_stats(3, t)
        self.assertEqual((s["today_steps"], s["today_xp"], s["streak"]), (2, 80, 1))

    def test_streak_and_week(self):
        st = self.st
        now = time.time()
        for days in (1, 2, 3, 5):
            st.flow_event_once("e%d" % days, "K", "", "phase", 3, 10, "", now - days * 86400)
        s = st.flow_stats(3, now)
        self.assertEqual(s["streak"], 3)          # heute noch nichts: gestern, vorgestern, vor 3 Tagen
        st.flow_event_once("today", "K", "", "phase", 3, 10, "", now)
        self.assertEqual(st.flow_stats(3, now)["streak"], 4)
        self.assertEqual(len(st.flow_stats(3, now)["week"]), 7)

    def test_event_once(self):
        self.assertTrue(self.st.flow_event_once("run:1", "K", "", "agent", -1, 5, ""))
        self.assertFalse(self.st.flow_event_once("run:1", "K", "", "agent", -1, 5, ""))

    def test_checklist_store(self):
        st = self.st
        a = st.check_add("X-1", "  eins  ")
        st.check_add("X-1", "zwei")
        self.assertEqual([c["text"] for c in st.checklists()["X-1"]], ["eins", "zwei"])
        self.assertTrue(st.check_toggle(a)["done"])
        self.assertFalse(st.check_toggle(a)["done"])
        st.check_delete(a)
        self.assertEqual(len(st.checklists()["X-1"]), 1)
        with self.assertRaises(links.LinkError):
            st.check_add("X-1", "")


class AppFlow(unittest.TestCase):
    def setUp(self):
        self.old = os.environ.get("TINYOPS_HOME")
        os.environ["TINYOPS_HOME"] = tempfile.mkdtemp()
        cfg = server.load_config(None)
        cfg["data_dir"] = tempfile.mkdtemp()
        self.app = server.App(cfg, True, {}, Path("/nonexistent/c.json"))

    def tearDown(self):
        if self.old is None:
            os.environ.pop("TINYOPS_HOME", None)
        else:
            os.environ["TINYOPS_HOME"] = self.old

    def test_overview_has_flow_for_every_card(self):
        ov = self.app.overview()
        f = ov["flow"]
        self.assertEqual(set(f["items"]), {c["id"] for c in ov["board"]["cards"]})
        kinds = {d["next"]["id"] for d in f["items"].values()}
        self.assertTrue({"ticket", "ready", "ci", "test"} <= kinds, kinds)
        self.assertTrue(f["reviews"])
        self.assertEqual([p["id"] for p in f["phases"]], [p for p, _ in flow.PHASES])

    def test_check_actions_and_points_once(self):
        ov = self.app.overview()
        key = ov["board"]["cards"][0]["id"]
        cid = self.app.flow_action("add", {"key": key, "text": "Test schreiben"})["id"]
        r = self.app.flow_action("toggle", {"id": cid})
        self.assertTrue(r["done"])
        xp = r["stats"]["today_xp"]
        self.app.flow_action("toggle", {"id": cid})
        r = self.app.flow_action("toggle", {"id": cid})
        self.assertEqual(r["stats"]["today_xp"], xp)        # ab- und wieder anhaken zählt nicht doppelt
        self.assertEqual(self.app.overview()["flow"]["items"][key]["checks"]["total"], 1)
        with self.assertRaises(server.UserError):
            self.app.flow_action("add", {"key": key, "text": ""})
        with self.assertRaises(server.UserError):
            self.app.flow_action("toggle", {"id": "x"})

    def test_complete_and_tiny_ticket(self):
        ov = self.app.overview()
        r = self.app.flow_action("complete", {"id": "DLP-104", "phase": 1})
        self.assertEqual(r["stage"], "impl")
        with self.assertRaises(server.UserError) as cm:
            self.app.flow_action("complete", {"id": "1:feature/proxo-mapping", "phase": 2})
        self.assertIn("Ticket", str(cm.exception))
        r = self.app.flow_action("tiny", {"project_id": 1, "branch": "feature/proxo-mapping", "title": "proxo Mapping", "project": "dlp-core"})
        self.assertTrue(r["key"].startswith("LOC-"))
        self.assertEqual(r["pool"], "dlp-core")
        self.app.cache_t = 0.0
        ov = self.app.overview()
        card = next(c for c in ov["board"]["cards"] if c["id"] == r["key"])
        self.assertEqual([x["branch"] for x in card["items"]], ["feature/proxo-mapping"])
        self.assertNotIn("1:feature/proxo-mapping", {c["id"] for c in ov["board"]["cards"]})
        self.assertNotEqual(ov["flow"]["items"][r["key"]]["next"]["id"], "ticket")
        # zweites tiny-Ticket im selben Projekt nimmt dieselbe Kategorie
        r2 = self.app.flow_action("tiny", {"project_id": 1, "branch": "idea/ui-prototype", "title": "UI", "project": "dlp-core"})
        self.assertEqual(len([p for p in self.app.store.pools() if p["name"] == "dlp-core"]), 1)
        self.assertNotEqual(r["key"], r2["key"])

    def test_accept_binds_current_sha_and_new_commit_makes_stale(self):
        ov = self.app.overview()
        r = self.app.flow_action("accept", {"id": "DLP-102", "note": "Login und Export geprüft", "env": "test-dlp-38"})
        self.assertEqual(r["stage"], "tested")
        self.assertEqual(r["commits"][0]["sha"], "a1b2c3d4")
        acc = self.app.store.acceptances()["DLP-102"]
        rec = next(iter(acc.values()))
        self.assertEqual((rec["note"], rec["env"]), ("Login und Export geprüft", "test-dlp-38"))
        ov = self.app.overview()
        self.assertEqual(ov["flow"]["items"]["DLP-102"]["phase_id"], "merge")
        # neuer Commit im MR
        for it in self.app.cache["mine"]:
            if it.get("iid") == 38:
                it["sha"] = "ffffeeee00001111"
        ov = self.app.overview()
        d = ov["flow"]["items"]["DLP-102"]
        self.assertEqual((d["phase_id"], d["next"]["id"]), ("test", "retest"))
        with self.assertRaises(server.UserError):
            self.app.flow_action("accept", {"id": "1:feature/proxo-mapping"})

    def test_sources_and_last_good_data_on_outage(self):
        ov = self.app.overview()
        self.assertEqual({s["id"]: s["ok"] for s in ov["sources"]}, {"gitlab": True, "jira": True, "sonar": True, "helpdesk": True})
        prev_mine = [dict(i) for i in self.app.cache["mine"]]
        data = {"mine": [i for i in prev_mine if i["project_id"] != 1], "review": [], "assigned": [], "errors": ["dlp-core: HTTP 503"], "gl_failed_pids": [1]}
        self.app._keep_last_good(data)
        kept = [i for i in data["mine"] if i.get("outdated")]
        self.assertEqual(len(kept), len([i for i in prev_mine if i["project_id"] == 1]))
        self.assertTrue(all(i["outdated_since"] for i in kept))
        data = {"mine": [], "review": [], "assigned": [], "errors": ["GitLab nicht erreichbar"], "gl_failed_all": True}
        self.app._keep_last_good(data)
        self.assertTrue(data["review"] and all(i["outdated"] for i in data["review"]))

    def test_pin(self):
        self.app.overview()
        self.app.flow_action("pin", {"id": "DLP-104"})
        self.assertEqual(self.app.overview()["flow"]["pinned"], "DLP-104")
        self.app.flow_action("pin", {"id": None})
        self.assertIsNone(self.app.overview()["flow"]["pinned"])
        with self.assertRaises(server.UserError):
            self.app.flow_action("pin", {"id": "NOPE-1"})

    def test_stage_change_gives_points(self):
        self.app.overview()
        key = "DLP-101"
        self.app.board_action("stage", {"key": key, "stage": "tested"})
        ov = self.app.overview()
        self.assertEqual(ov["flow"]["items"][key]["phase_id"], "merge")
        self.assertGreaterEqual(ov["flow"]["stats"]["today_xp"], 20)


if __name__ == "__main__":
    unittest.main()
