"""0.20: Ideen bewerten, Ticket aus Idee, IntelliJ auf dem MR-Commit, Review-App-Link."""
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import flow  # noqa: E402
import links  # noqa: E402
import llm  # noqa: E402
import server  # noqa: E402
import settings  # noqa: E402
from test_github import free_port, wait  # noqa: E402

GIT = ["git", "-c", "user.name=T", "-c", "user.email=t@x", "-c", "init.defaultBranch=main"]


class Fake:
    name, label, default_url = "fake20", "Fake", "http://127.0.0.1:1"
    reply = ""

    def models(self, cfg, key, ctx=None):
        return ["m"]

    def chat(self, cfg, key, system, user, ctx=None):
        Fake.last = (system, user)
        return Fake.reply, 0.1


def demo_app(**cfg_extra):
    os.environ["TINYOPS_HOME"] = tempfile.mkdtemp()
    cfg = server.load_config(None)
    cfg["data_dir"] = tempfile.mkdtemp()
    cfg.update(cfg_extra)
    a = server.App(cfg, True, {}, Path("/nonexistent/c.json"))
    a.overview()
    return a


class Units(unittest.TestCase):
    def test_similar_and_slug(self):
        r = server.similar("Dark Mode für das Board einbauen", [("#1", "Board im Dark Mode"), ("#2", "Jira schneller"), ("X-1", "Dark-Mode Board Farben")])
        self.assertEqual([x["id"] for x in r], ["#1", "X-1"])
        self.assertEqual(server.similar("", [("#1", "x")]), [])
        self.assertEqual(server.ref_slug("Feature/DLP-101_a.b"), "feature-dlp-101-a-b")
        self.assertEqual(len(server.ref_slug("x" * 100)), 63)

    def test_parse_assessment(self):
        a = llm.parse_assessment('Hier: {"category": "feature", "benefit": "3", "effort": "m", "duplicates": ["#4", 99, "x"], '
                                 '"recommendation": "Jetzt", "why": "w"}', [4, 5])
        self.assertEqual((a["category"], a["benefit"], a["effort"], a["duplicates"], a["recommendation"]), ("Feature", 3, "M", [4], "jetzt"))
        for bad in ("kein json", '{"recommendation": "vielleicht"}'):
            with self.assertRaises(llm.LlmError):
                llm.parse_assessment(bad)

    def test_template_and_acceptance(self):
        t = llm.template_from_idea({"idea_id": 3, "idea_text": "Dark Mode\nAbends hell", "assessment": {"why": "hilft abends"}})
        for h in ("h3. Story", "h3. Akzeptanzkriterien", "h3. Risiken", "h3. Tests", "h3. Abhängigkeiten", "h3. Offene Fragen"):
            self.assertIn(h, t["description"])
        self.assertEqual(llm.acceptance_items(t["description"]), [])          # Platzhalter zählen nicht
        self.assertEqual(llm.acceptance_items("h3. Akzeptanzkriterien\n* A\n- B\nh3. Tests\n* T"), ["A", "B"])


class Ideas(unittest.TestCase):
    def setUp(self):
        llm.register(Fake())
        self.addCleanup(lambda: llm.PROVIDERS.pop("fake20", None))

    def test_assess_manual_and_model(self):
        a = demo_app(llm={"enabled": True, "provider": "fake20", "url": "http://127.0.0.1:1", "model": "m"})
        a.ideas.add("Dark Mode für das Board")
        a.ideas.add("Board im Dark Mode")
        i1, i2 = sorted(i["id"] for i in a.ideas.list())
        r = a.idea_assess(i1, {"manual": True, "recommendation": "später", "category": "Feature", "benefit": "2", "effort": "M", "why": "abends"})
        self.assertEqual((r["source"], r["benefit"]), ("du", 2))
        self.assertEqual(r["similar"][0]["id"], "#%d" % i2)                  # ohne Modell gefunden
        with self.assertRaises(server.UserError):
            a.idea_assess(i1, {"manual": True})
        Fake.reply = json.dumps({"category": "Feature", "benefit": 3, "effort": "S", "duplicates": [i2], "recommendation": "jetzt", "why": "klein"})
        r = a.idea_assess(i1, {})
        self.assertEqual((r["source"], r["recommendation"], r["duplicates"]), ("modell", "jetzt", [i2]))
        self.assertIn("Board im Dark Mode", Fake.last[1])                   # andere Ideen gehen für Dubletten mit
        self.assertEqual(a.ideas.get(i1)["assessment"]["recommendation"], "jetzt")
        Fake.reply = "Ich weiss nicht"
        with self.assertRaises(server.UserError):
            a.idea_assess(i1, {})
        acts = [(x["action"], x["ok"]) for x in a.audit_log.rows(action="idea.assess")]
        self.assertEqual(acts, [("idea.assess", False), ("idea.assess", True), ("idea.assess", True)])

    def test_assess_needs_local_model(self):
        a = demo_app(llm={"enabled": True, "provider": "fake20", "url": "http://8.8.8.8", "model": "m"})
        a.ideas.add("Etwas")
        with self.assertRaises(server.UserError) as cm:
            a.idea_assess(a.ideas.list()[0]["id"], {})
        self.assertIn("eigenen Netz", str(cm.exception))

    def test_draft_and_tiny_with_checklist(self):
        a = demo_app(llm={"enabled": True, "provider": "fake20", "url": "http://127.0.0.1:1", "model": "m"})
        a.ideas.add("Export als CSV\nFür die Auswertung im Excel")
        iid = a.ideas.list()[0]["id"]
        d = a.ticket_draft({"idea_id": iid})
        self.assertEqual((d["source"], d["draft"]["summary"]), ("vorlage", "Export als CSV"))
        Fake.reply = json.dumps({"summary": "CSV-Export", "issue_type": "Story", "description":
                                 "h3. Story\nAls Analyst ...\nh3. Akzeptanzkriterien\n* Button exportiert\n* Umlaute korrekt\nh3. Risiken\n* Grösse\nh3. Tests\n* Unit\nh3. Abhängigkeiten\n* keine\nh3. Offene Fragen\n* Trennzeichen?"})
        d = a.ticket_draft({"idea_id": iid, "use_llm": True})
        self.assertEqual((d["source"], d["acceptance"]), ("ki", ["Button exportiert", "Umlaute korrekt"]))
        self.assertIn("Für die Auswertung", Fake.last[1])
        r = a.idea_tiny(iid, {"summary": d["draft"]["summary"], "description": d["draft"]["description"], "checklist": True})
        self.assertTrue(r["key"].startswith("LOC-"))
        self.assertEqual(r["checks"], 2)
        self.assertEqual([x["text"] for x in a.store.checklists()[r["key"]]], ["Button exportiert", "Umlaute korrekt"])
        idea = a.ideas.get(iid)
        self.assertEqual((idea["status"], idea["ticket"]), ("erledigt", r["key"]))
        self.assertEqual(a.audit_log.rows(action="idea.ticket")[0]["detail"]["ticket"], r["key"])


class JiraFromIdea(unittest.TestCase):
    def test_create_links_idea(self):
        from test_settings import start
        p, port = start("mock_jira.py")
        self.addCleanup(lambda: (p.terminate(), p.wait()))
        os.environ["TINYOPS_HOME"] = tempfile.mkdtemp()
        cfg = server.load_config(None)
        cfg.update(data_dir=tempfile.mkdtemp(), jira={"url": "http://127.0.0.1:%d" % port, "project_keys": ["DLP"], "allow_create": True})
        a = server.App(cfg, False, {"jira_token": "jtoken"}, Path("/nonexistent/c.json"))
        a.ideas.add("Retry für Upload")
        iid = a.ideas.list()[0]["id"]
        res = a.ticket_create({"project": "DLP", "issue_type": "Story", "summary": "Retry für Upload", "description": "h3. Akzeptanzkriterien\n* 429 wird wiederholt",
                               "idea_id": iid, "checklist": True})
        self.assertEqual(res["checks"], 1)
        self.assertEqual(a.ideas.get(iid)["ticket"], res["key"])
        self.assertEqual([x["action"] for x in a.audit_log.rows()][:2], ["idea.ticket", "jira.create"])


def git(cwd, *args):
    return subprocess.run(GIT + list(args), cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


class Ide(unittest.TestCase):
    def setUp(self):
        d = Path(tempfile.mkdtemp())
        self.d = d
        origin = d / "origin.git"
        subprocess.run(GIT + ["init", "-q", "--bare", str(origin)], check=True)
        seed = d / "seed"
        subprocess.run(GIT + ["clone", "-q", str(origin), str(seed)], check=True, capture_output=True)
        (seed / "a.txt").write_text("1\n")
        git(seed, "add", "-A"); git(seed, "commit", "-qm", "init"); git(seed, "push", "-q", "origin", "HEAD:main")
        self.repo = d / "work" / "dlp-core"
        subprocess.run(GIT + ["clone", "-q", str(origin), str(self.repo)], check=True, capture_output=True)
        (seed / "a.txt").write_text("2\n")
        git(seed, "commit", "-qam", "MR-Stand")
        self.sha = git(seed, "rev-parse", "HEAD")
        git(seed, "push", "-q", "origin", "HEAD:refs/merge-requests/41/head")       # wie GitLab: nur über die MR-Ref erreichbar
        self.marker = d / "ide-args.txt"

    def app(self):
        a = demo_app(projects=[{"id": 1, "name": "dlp-core", "repo_path": str(self.repo)}],
                     ide_command="sh -c 'echo \"$0\" > %s' {path}" % self.marker)
        for it in a.cache["mine"]:
            if it.get("iid") == 41:
                it["sha"] = self.sha
        a.demo = False                 # echter Start des IDE-Befehls
        return a

    def test_open_accept_close(self):
        a = self.app()
        self.assertTrue(next(i for i in a.overview()["mine"] if i.get("iid") == 41)["ide"])
        r = a.ide_open({"host": "gitlab", "project_id": 1, "iid": 41})
        self.assertTrue(r["launched"], r)
        wt = Path(r["path"])
        self.assertEqual(wt.parent, self.repo.parent / ".tinyops-wt")
        self.assertEqual(git(wt, "rev-parse", "HEAD"), self.sha)
        self.assertEqual((wt / "a.txt").read_text(), "2\n")
        self.assertEqual(git(self.repo, "status", "--porcelain"), "")                 # dein Checkout bleibt sauber
        for _ in range(50):
            if self.marker.exists():
                break
            time.sleep(0.1)
        self.assertEqual(self.marker.read_text().strip(), str(wt))
        self.assertEqual(a.ide_open({"host": "gitlab", "project_id": 1, "iid": 41})["path"], str(wt))      # zweites Mal: derselbe
        # Abnahme nimmt den Commit des Worktrees
        for it in a.cache["mine"]:
            if it.get("iid") == 41:
                it["sha"] = "f" * 40                         # der MR ist inzwischen weiter
        ov = a.overview()
        item = next(x for x in ov["board"]["cards"] if x["id"] == "DLP-101")["items"][0]
        self.assertTrue(item["ide_wt"]["stale"])
        a.flow_action("accept", {"id": "DLP-101", "note": "in IntelliJ"})
        acc = a.store.acceptances()["DLP-101"]
        self.assertEqual(list(acc.values())[0]["sha"], self.sha)
        # Aufräumen: mit Änderung nur erzwungen
        (wt / "a.txt").write_text("lokal geändert\n")
        ref = item["ref"] or links.ref_of(1, item["branch"])
        with self.assertRaises(server.UserError) as cm:
            a.ide_close({"ref": ref})
        self.assertEqual(cm.exception.data["dirty"], 1)
        a.ide_close({"ref": ref, "force": True})
        self.assertFalse(wt.exists())
        self.assertNotIn(str(wt), git(self.repo, "worktree", "list"))
        acts = [x["action"] for x in a.audit_log.rows()]
        self.assertIn("ide.open", acts)
        self.assertIn("ide.close", acts)

    def test_done_cleans_clean_worktree(self):
        a = self.app()
        r = a.ide_open({"host": "gitlab", "project_id": 1, "iid": 41})
        a.overview()
        a.board_action("stage", {"key": "DLP-101", "stage": "done"})
        self.assertFalse(Path(r["path"]).exists())

    def test_errors(self):
        a = self.app()
        a.cfg["projects"][0].pop("repo_path")
        a.proj_cfg[1].pop("repo_path", None)
        with self.assertRaises(server.UserError) as cm:
            a.ide_open({"host": "gitlab", "project_id": 1, "iid": 41})
        self.assertIn("lokale Checkout", str(cm.exception))
        a = self.app()
        for it in a.cache["mine"]:
            if it.get("iid") == 41:
                it["sha"] = "0123456789abcdef0123456789abcdef01234567"
        with self.assertRaises(server.UserError) as cm:
            a.ide_open({"host": "gitlab", "project_id": 1, "iid": 41})
        self.assertIn("nicht da", str(cm.exception))
        a = self.app()
        a.cfg["ide_command"] = "gibt-es-nicht-xyz {path}"
        r = a.ide_open({"host": "gitlab", "project_id": 1, "iid": 41})
        self.assertFalse(r["launched"])
        self.assertIn("File → Open", r["hint"])

    def test_settings(self):
        new, err = settings.build_config({}, {"gitlab": {"url": "https://g.example"}, "projects": [{"id": 1, "name": "x", "repo_path": "~/work/x"}],
                                              "ide_command": 'open -na "IntelliJ IDEA.app" --args {path}'})
        self.assertEqual(err, {})
        self.assertEqual((new["projects"][0]["repo_path"], new["ide_command"]), ("~/work/x", 'open -na "IntelliJ IDEA.app" --args {path}'))
        _, err = settings.build_config({}, {"gitlab": {"url": "https://g.example"}, "projects": [{"id": 1, "name": "x", "repo_path": "relativ/pfad"}],
                                            "ide_command": 'idea "{path}'})
        self.assertIn("projects", err)
        self.assertIn("ide_command", err)
        self.assertEqual(settings.view(new, Path("/x"))["projects"][0]["repo_path"], "~/work/x")


class ReviewApp(unittest.TestCase):
    def test_link_and_test_step(self):
        port = free_port()
        p = subprocess.Popen([sys.executable, str(ROOT / "tests" / "mock_gitlab.py"), str(port)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.addCleanup(lambda: (p.terminate(), p.wait()))
        wait(port)
        d = tempfile.mkdtemp()
        os.environ["TINYOPS_HOME"] = d
        cfg = server.load_config(None)
        cfg.update(gitlab_url="http://127.0.0.1:%d" % port, data_dir=d, my_emails=["me@x.ch"], projects=[{"id": 1, "name": "dlp-core"}])
        a = server.App(cfg, False, {"gitlab_token": "secret"}, Path(d) / "c.json")
        ov = a.overview()
        m7 = next(i for i in ov["mine"] if i.get("iid") == 7)
        self.assertEqual((m7["review_app"], m7["review_env"], m7["target_branch"]), ("https://review-dlp-101.apps.x", "review/feature-dlp-101-a", ""))
        self.assertEqual(next(i for i in ov["mine"] if i.get("iid") == 8)["review_app"], "")       # ohne URL kein Link
        pool = a.pool_action("create", {"name": "dlp-core"})["id"]
        key = a.board_action("add", {"title": "Feature A", "stage": "planned", "pool_id": pool})["key"]       # ohne Jira: tiny-Ticket mit dem Branch verknüpft
        a.link_ticket({"project_id": 1, "branch": "feature/DLP-101-a", "ticket": key})
        a.overview()
        a.board_action("stage", {"key": key, "stage": "test"})
        nxt = a.overview()["flow"]["items"][key]["next"]
        self.assertEqual(nxt["id"], "test")
        self.assertEqual(nxt["action"]["review_app"], "https://review-dlp-101.apps.x")
        self.assertNotIn("ide", nxt["action"])                                            # kein lokaler Checkout eingetragen


if __name__ == "__main__":
    unittest.main()
