"""GitHub-Anbindung: nur lesend, eigene PRs und Branches, Review-Anfragen, Checks, Reviews und Daumen, Einstellungen und Abgleich."""
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import flow  # noqa: E402
import github  # noqa: E402
import server  # noqa: E402
import settings  # noqa: E402


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def wait(port):
    for _ in range(80):
        try:
            socket.create_connection(("127.0.0.1", port), timeout=0.2).close()
            return
        except OSError:
            time.sleep(0.1)
    raise RuntimeError("Server startet nicht")


class WithMock(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.port = free_port()
        cls.proc = subprocess.Popen([sys.executable, str(ROOT / "tests" / "mock_github.py"), str(cls.port)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        wait(cls.port)
        cls.base = "http://127.0.0.1:%d" % cls.port

    @classmethod
    def tearDownClass(cls):
        cls.proc.terminate()
        cls.proc.wait(5)

    def methods(self):
        return json.loads(urllib.request.urlopen(self.base + "/_methods").read())

    def fetch(self):
        c = github.Client(self.base, "ghtoken")
        sink, steps = {}, []
        ident = server.identity({"branch_filter": {}, "my_emails": []}, {})
        c.fetch(["adrian/hooks"], ident, server.classify_commits, {"max_branches": 40, "max_age_days": 0}, lambda b: False, sink,
                lambda *a: steps.append(a))
        return sink, steps


class ClientTests(WithMock):
    def test_fetch_items(self):
        sink, steps = self.fetch()
        mine = {i["branch"]: i for i in sink["mine"]}
        self.assertEqual(set(mine), {"feature/DLP-7-hooks", "wip/mine"})          # PR von bob und Branch von bob fehlen
        p = mine["feature/DLP-7-hooks"]
        self.assertEqual((p["kind"], p["iid"], p["host"], p["pipeline"], p["merge_status"]), ("mr", 7, "github", "success", "mergeable"))
        self.assertEqual((p["approved"], p["approved_by"], p["upvotes"], p["reviewers"]), (True, ["octocat"], 1, ["octocat"]))
        self.assertEqual(p["project_id"], github.pid_of(42))
        b = mine["wip/mine"]
        self.assertEqual((b["kind"], b["ahead"], b["title"]), ("branch", 1, "Retry eingebaut"))
        self.assertIn("/compare/main...wip%2Fmine?expand=1", b["create_mr_url"])
        rv = sink["review"]
        self.assertEqual([(r["project"], r["iid"], r["branch"], r["pipeline"], r["author"]) for r in rv], [("team/core", 3, "fix/thing", "running", "carol")])
        self.assertEqual(sink["assigned"], [])
        self.assertTrue(any(s[0] == "gh-user" and s[2] == "ok" for s in steps))

    def test_read_only(self):
        self.fetch()
        self.assertTrue(all(m.startswith("GET ") for m in self.methods()))

    def test_bad_token_and_missing_repo(self):
        c = github.Client(self.base, "wrong")
        with self.assertRaises(github.GitHubError) as cm:
            c.user()
        self.assertIn("401", str(cm.exception))
        sink, steps = {}, []
        g = github.Client(self.base, "ghtoken")
        g.fetch(["adrian/secret"], server.identity({}, {}), server.classify_commits, {}, lambda b: False, sink, lambda *a: steps.append(a))
        self.assertTrue(any("adrian/secret" in e for e in sink["errors"]))

    def test_flow_uses_reviews(self):
        sink, _ = self.fetch()
        p = next(i for i in sink["mine"] if i["kind"] == "mr")
        d = flow.derive({"id": "DLP-7", "key": "DLP-7", "title": "t", "items": [p], "stage": "impl", "manual_stage": False})
        self.assertEqual((d["phase_id"], d["next"]["id"]), ("test", "test"))
        self.assertIn("PR #7", d["next"]["why"])

    def test_search_repos(self):
        c = github.Client(self.base, "ghtoken")
        self.assertEqual([r["full"] for r in c.search_repos("hooks")], ["adrian/hooks"])
        self.assertEqual([r["full"] for r in c.search_repos("team/core")][0], "team/core")


class SettingsTests(WithMock):
    def test_connection_test(self):
        res = settings.test_github({"api_url": self.base, "secret": "ghtoken", "repos": [{"full": "adrian/hooks"}]}, lambda n: ("", ""))
        st = {s["id"]: s["status"] for s in res["steps"]}
        self.assertEqual((st["auth"], st["rate"], st["repos"]), ("ok", "ok", "ok"), res)
        self.assertEqual(res["ids"], {"adrian/hooks": 42})
        self.assertNotIn("ghtoken", json.dumps(res))
        res = settings.test_github({"api_url": self.base, "secret": "ghtoken", "repos": [{"full": "adrian/secret"}]}, lambda n: ("", ""))
        self.assertFalse(res["ok"])
        res = settings.test_github({"api_url": self.base, "secret": "falsch", "repos": []}, lambda n: ("", ""))
        self.assertEqual(res["steps"][-1]["status"], "skip")

    def test_build_config(self):
        cur = {"projects": []}
        new, errors = settings.build_config(cur, {"gitlab": {"url": ""}, "github": {"enabled": True, "api_url": "https://api.github.com",
                                                                                     "repos": [{"full": "adrian/hooks", "id": 42, "agent_dir": "hooks", "allow_cloud_agents": True},
                                                                                               {"full": "adrian/hooks"}]}})
        self.assertEqual(errors, {})
        self.assertEqual(new["github"]["repos"], [{"full": "adrian/hooks", "id": 42, "agent_dir": "hooks", "data_class": "internal"}])
        _, errors = settings.build_config(cur, {"github": {"enabled": True, "api_url": "http://evil.example", "repos": [{"full": "a b"}]}})
        self.assertIn("github.api_url", errors)
        self.assertIn("github.repos", errors)
        _, errors = settings.build_config(cur, {"github": {"enabled": True, "repos": []}})
        self.assertIn("github.repos", errors)
        v = settings.view(new, "/x")
        self.assertEqual(v["github"]["repos"][0]["full"], "adrian/hooks")
        self.assertIn("github_token", v["secrets"])


class AppTests(WithMock):
    def test_github_only_setup(self):
        with tempfile.TemporaryDirectory() as d:
            old = os.environ.get("TINYOPS_HOME")
            os.environ["TINYOPS_HOME"] = d
            try:
                cfg = server.load_config(None)
                cfg.update(data_dir=d, github={"enabled": True, "api_url": self.base, "repos": [{"full": "adrian/hooks", "id": 42, "allow_cloud_agents": True}]})
                app = server.App(cfg, False, {"github_token": "ghtoken"}, Path(d) / "c.json")
                self.assertTrue(app.configured)
                self.assertFalse(any(p.startswith("GitLab") for p in app.problems), app.problems)
                ov = app.overview()
                self.assertEqual(ov["errors"], [])
                cards = {c["id"]: c for c in ov["board"]["cards"]}
                self.assertIn("%d:wip/mine" % github.pid_of(42), cards)
                nxt = ov["flow"]["items"]["%d:wip/mine" % github.pid_of(42)]["next"]
                self.assertEqual(nxt["id"], "ticket")                   # Branch ohne Ticket: zuerst ein Ticket
                self.assertEqual([r["host"] for r in ov["flow"]["reviews"]], ["github"])
                # tiny-Ticket für den GitHub-Branch, Agenten sehen das Repo als Projekt
                r = app.flow_action("tiny", {"project_id": github.pid_of(42), "branch": "wip/mine", "title": "Retry", "project": "adrian/hooks"})
                app.cache_t = 0.0
                ov = app.overview()
                self.assertIn(r["key"], {c["id"] for c in ov["board"]["cards"]})
                self.assertIn({"id": github.pid_of(42), "name": "hooks", "data_class": "internal"}, app.agents.view()["projects"])
            finally:
                if old is None:
                    os.environ.pop("TINYOPS_HOME", None)
                else:
                    os.environ["TINYOPS_HOME"] = old
        self.assertTrue(all(m.startswith("GET ") for m in self.methods()))


if __name__ == "__main__":
    unittest.main()
