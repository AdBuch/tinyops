"""0.25: Workspaces. Echte Git-Repos in einem Temp-Ordner: ungepushte Commits, kein Upstream, offene Dateien, Stash, Worktree, Hosts."""
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import server  # noqa: E402
import settings  # noqa: E402
import workspaces as ws  # noqa: E402

ENV = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@example.com", GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@example.com",
           GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_SYSTEM=os.devnull)


def git(cwd, *a):
    r = subprocess.run(["git", "-C", str(cwd), "-c", "init.defaultBranch=main", "-c", "commit.gpgsign=false"] + list(a), capture_output=True, text=True, env=ENV)
    assert r.returncode == 0, (a, r.stderr)
    return r.stdout.strip()


def commit(repo, name, text="x"):
    (Path(repo) / name).write_text(text)
    git(repo, "add", name)
    git(repo, "commit", "-q", "-m", "add " + name)


@unittest.skipUnless(shutil.which("git"), "git fehlt")
class Scan(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp())
        w = cls.work = cls.tmp / "work"
        # «Server»: ein nacktes Repo als origin
        cls.origin = cls.tmp / "srv" / "dlp" / "dlp-core.git"
        cls.origin.mkdir(parents=True)
        git(cls.origin, "init", "-q", "--bare")
        core = cls.core = w / "dlp-core"
        core.mkdir(parents=True)
        git(core, "init", "-q")
        commit(core, "a.txt")
        git(core, "remote", "add", "origin", str(cls.origin))
        git(core, "push", "-q", "-u", "origin", "main")
        commit(core, "b.txt")                                   # 1 voraus auf main
        commit(core, "c.txt")                                   # 2 voraus
        git(core, "checkout", "-q", "-b", "spike/x")
        commit(core, "d.txt")                                   # Branch ohne Upstream: 3 Commits liegen auf keinem Remote
        git(core, "checkout", "-q", "main")
        (core / "a.txt").write_text("geändert")                 # geändert
        (core / "neu.txt").write_text("neu")                    # neu
        (core / "e.txt").write_text("e")
        git(core, "add", "e.txt")                               # vorgemerkt
        git(core, "worktree", "add", "-q", "-b", "agent/dlp-1-7", str(w / ".tinyops-wt" / "7"), "main")
        (w / ".tinyops-wt" / "7" / "w.txt").write_text("vom Agenten")
        # Repo mit GitHub-Remote samt Zugangsdaten in der Adresse, tiefer verschachtelt, mit Stash
        tool = cls.tool = w / "kunden" / "sync-tool"
        tool.mkdir(parents=True)
        git(tool, "init", "-q")
        commit(tool, "r.md")
        git(tool, "remote", "add", "origin", "https://user:geheim123@github.com/demo/sync-tool.git")
        (tool / "r.md").write_text("wip")
        git(tool, "stash", "-q")
        # Repo ohne Remote, Projekt ohne Git, Ordner zum Überspringen, zu tief liegendes Repo
        (w / "notizen").mkdir()
        git(w / "notizen", "init", "-q")
        commit(w / "notizen", "n.md")
        (w / "skripte" / "export").mkdir(parents=True)
        (w / "skripte" / "export" / "pyproject.toml").write_text("[project]")
        (w / "node_modules" / "pkg").mkdir(parents=True)
        git(w / "node_modules" / "pkg", "init", "-q")
        deep = w / "a" / "b" / "c" / "d" / "tief"
        deep.mkdir(parents=True)
        git(deep, "init", "-q")
        cls.projects = [{"pid": 1, "name": "dlp-core", "host": "gitlab", "full": "", "repo_path": str(core), "agent_dir": ""},
                        {"pid": 10 ** 12 + 5, "name": "sync-tool", "host": "github", "full": "demo/sync-tool", "repo_path": "", "agent_dir": ""}]
        cls.res = ws.scan([{"path": str(w), "why": "Test"}], {"gitlab": ["gitlab.example"], "github": ["github.com"]}, cls.projects, depth=3)
        cls.by = {r["name"]: r for r in cls.res["repos"]}

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_finds_repos_and_plain(self):
        self.assertEqual(set(self.by), {"dlp-core", "sync-tool", "notizen"})          # node_modules, .tinyops-wt und das zu tiefe Repo nicht
        self.assertEqual([(p["name"], p["kind"], p["rel"]) for p in self.res["plain"]], [("export", "Python", os.path.join("skripte", "export"))])
        self.assertEqual(self.by["sync-tool"]["rel"], os.path.join("kunden", "sync-tool"))
        self.assertEqual(self.res["roots"][0]["repos"], 3)

    def test_unpushed(self):
        r = self.by["dlp-core"]
        b = {x["name"]: x for x in r["branches"]}
        self.assertEqual((b["main"]["ahead"], b["main"]["upstream"], b["main"]["current"]), (2, "origin/main", True))
        self.assertEqual((b["spike/x"]["ahead"], b["spike/x"]["upstream"]), (3, ""))
        self.assertTrue(b["agent/dlp-1-7"]["agent"])
        self.assertEqual(b["agent/dlp-1-7"]["ahead"], 2)                              # zeigt auf main: dieselben 2 Commits
        self.assertEqual(r["dirty"], {"staged": 1, "changed": 1, "new": 1, "total": 3})
        self.assertTrue(r["todo"])
        self.assertEqual((r["unpushed_branches"], r["no_upstream"], r["agent_branches"]), (3, 2, 1))
        self.assertEqual(r["project"]["pid"], 1)

    def test_worktree_of_agent(self):
        w = self.by["dlp-core"]["worktrees"]
        self.assertEqual(len(w), 1)
        self.assertEqual((w[0]["branch"], w[0]["agent"], w[0]["dirty"], w[0]["missing"]), ("agent/dlp-1-7", True, 1, False))
        self.assertEqual(self.by["dlp-core"]["wt_dirty"], 1)

    def test_hosts_and_no_credentials(self):
        t = self.by["sync-tool"]
        self.assertEqual((t["host"], t["remote"], t["project"]["pid"]), ("github", "github.com/demo/sync-tool", 10 ** 12 + 5))
        self.assertNotIn("geheim123", str(t))
        self.assertEqual((t["stashes"], t["todo"]), (1, True))
        n = self.by["notizen"]
        self.assertEqual((n["host"], n["project"], n["remotes"]), ("none", None, []))
        self.assertEqual(n["branches"][0]["ahead"], 1)                                # ohne Remote ist jeder Commit nur lokal
        self.assertEqual(self.by["dlp-core"]["host"], "other")                        # Pfad als Remote: weder GitLab noch GitHub

    def test_scan_changes_nothing(self):
        before = (git(self.core, "status", "--porcelain"), git(self.core, "rev-parse", "HEAD"), git(self.core, "for-each-ref"))
        ws.scan([{"path": str(self.work), "why": ""}], {}, self.projects)
        self.assertEqual(before, (git(self.core, "status", "--porcelain"), git(self.core, "rev-parse", "HEAD"), git(self.core, "for-each-ref")))
        self.assertFalse((self.core / ".git" / "index.lock").exists())

    def test_totals_and_stale(self):
        t = ws.totals(self.res, stale_days=0)
        self.assertEqual((t["repos"], t["todo"], t["plain"], t["unknown"], t["stashes"]), (3, 3, 1, 1, 1))
        self.assertEqual(self.by["dlp-core"]["unpushed_commits"], 3)                  # main 2, spike 3, agent 2: zusammen 3 verschiedene
        self.assertEqual(t["commits"], 3 + 1 + 1)                                     # dazu sync-tool (nie gepusht) und notizen (kein Remote)
        self.assertEqual(ws.totals(self.res, stale_days=5)["stale"], [])              # alles frisch
        self.assertEqual(ws.totals(None)["repos"], 0)

    def test_real_app_scans_configured_roots(self):
        os.environ["TINYOPS_HOME"] = tempfile.mkdtemp()
        cfg = server.load_config(None)
        cfg.update(data_dir=tempfile.mkdtemp(), workspaces={"roots": [str(self.work)]},
                   projects=[{"id": 1, "name": "dlp-core", "repo_path": str(self.core)}])
        a = server.App(cfg, False, {}, Path("/nonexistent/c.json"), watchdog=False)
        w = a.workspaces_state()
        self.assertEqual({r["name"] for r in w["repos"]}, {"dlp-core", "sync-tool", "notizen"})
        self.assertEqual(next(r for r in w["repos"] if r["name"] == "dlp-core")["project"]["pid"], 1)
        self.assertEqual(w["roots"][0]["why"], "eingetragen")
        with self.assertRaises(server.UserError):                       # nur Repos aus dem Scan, keine beliebigen Pfade
            a.workspaces_action("fetch", {"path": str(self.tmp)})

    def test_fetch_only_moves_remote_refs(self):
        ok, err = ws.fetch(self.core)
        self.assertTrue(ok, err)
        self.assertEqual(ws.inspect(self.core)["dirty"]["total"], 3)
        bad = self.tmp / "kaputt"
        bad.mkdir()
        git(bad, "init", "-q")
        git(bad, "remote", "add", "origin", "https://user:geheim123@127.0.0.1:9/x.git")      # niemand hört auf Port 9
        ok, err = ws.fetch(bad)
        self.assertFalse(ok)
        self.assertNotIn("geheim123", err)


class Parse(unittest.TestCase):
    def test_remote(self):
        self.assertEqual(ws.parse_remote("git@gitlab.example:dlp/dlp-core.git"), ("gitlab.example", "dlp/dlp-core"))
        self.assertEqual(ws.parse_remote("https://tok:x@GitLab.example/grp/sub/proj.git"), ("gitlab.example", "grp/sub/proj"))
        self.assertEqual(ws.parse_remote("ssh://git@github.com:22/demo/x"), ("github.com", "demo/x"))
        self.assertEqual(ws.parse_remote("/srv/git/x.git")[0], "")
        self.assertEqual(ws.safe_url("https://tok:x@host/p.git"), "https://host/p.git")
        h = {"gitlab": ["git.firma.example"], "github": ["github.com"]}
        self.assertEqual([ws.classify(x, h) for x in ("git.firma.example", "gitlab.com", "github.com", "bitbucket.org", "")], ["gitlab", "gitlab", "github", "other", "none"])

    def test_match(self):
        ps = [{"pid": 1, "name": "dlp-core", "host": "gitlab", "full": "", "repo_path": "", "agent_dir": ""},
              {"pid": 2, "name": "x", "host": "github", "full": "demo/Sync-Tool", "repo_path": "", "agent_dir": ""}]
        self.assertEqual(ws.match_project("/x", [{"kind": "gitlab", "path": "dlp/dlp-core"}], ps)["pid"], 1)
        self.assertEqual(ws.match_project("/x", [{"kind": "github", "path": "demo/sync-tool"}], ps)["pid"], 2)
        self.assertIsNone(ws.match_project("/x", [{"kind": "github", "path": "dlp/dlp-core"}], ps))      # gleicher Name, anderer Host
        self.assertIsNone(ws.match_project("/x", [], ps))

    def test_roots_from_config(self):
        c = {"workspaces": {"roots": ["~/work"]}, "agents": [{"id": "g", "name": "goose", "connection": "local", "workspace_root": "/srv/agent"},
                                                             {"id": "c", "connection": "dev-vm", "workspace_root": "/home/remote/work"}],
             "projects": [{"id": 1, "repo_path": "/home/du/code/dlp-core"}], "github": {"repos": [{"id": 5, "full": "a/b", "repo_path": "/home/du/code/b"}]}}
        r = ws.roots_of(c)
        self.assertEqual([x["path"] for x in r], [str(Path("~/work").expanduser()), "/srv/agent", "/home/du/code"])     # Remote-Agent nicht, Doppeltes einmal
        self.assertEqual(ws.roots_of({}), [])

    def test_settings(self):
        cfg, err = settings.build_config({}, {"workspaces": {"roots": "~/work\n\n/srv/x ", "depth": 9, "stale_days": "3"}})
        self.assertIn("workspaces.depth", err)
        cfg, err = settings.build_config({}, {"workspaces": {"roots": "~/work\n\n/srv/x ", "depth": 2, "stale_days": "3", "enabled": False}})
        self.assertEqual(err, {})
        self.assertEqual((cfg["workspaces"]["roots"], cfg["workspaces"]["depth"], cfg["workspaces"]["stale_days"], cfg["workspaces"]["enabled"]), (["~/work", "/srv/x"], 2, 3, False))
        _, err = settings.build_config({}, {"workspaces": {"roots": ["relativ/pfad"]}})
        self.assertIn("workspaces.roots", err)
        self.assertIn("found", settings.view(cfg, "x")["workspaces"])


class AppWs(unittest.TestCase):
    def app(self, **extra):
        os.environ["TINYOPS_HOME"] = tempfile.mkdtemp()
        cfg = server.load_config(None)
        cfg["data_dir"] = tempfile.mkdtemp()
        cfg.update(extra)
        return server.App(cfg, True, {}, Path("/nonexistent/c.json"), watchdog=False)

    def test_demo_state_and_summary(self):
        a = self.app()
        w = a.workspaces_state()
        self.assertEqual(w["totals"]["todo"], 3)
        self.assertTrue(w["repos"][0]["todo"])                       # Repos mit Arbeit zuerst, das älteste oben
        self.assertGreaterEqual(w["repos"][0]["oldest_days"], w["repos"][1]["oldest_days"] or 0)
        ov = a.overview()["workspaces"]
        self.assertEqual((ov["todo"], len(ov["stale"])), (3, 2))

    def test_task_and_rules(self):
        a = self.app()
        a.workspaces_state()
        r = a.workspaces_action("task", {"path": "/home/demo/work/dlp-core", "title": "  Tests   für Retry ", "branch": "main"})
        self.assertEqual((r["title"], r["project_id"], r["branch"]), ("Tests für Retry", 1, "main"))
        self.assertTrue(r["key"])
        self.assertIn("workspace.task", [x["action"] for x in a.audit_log.rows(limit=10)])
        for bad in ({"path": "/home/demo/work/sync-tool", "title": "x"},                      # kein eingerichtetes Projekt
                    {"path": "/home/demo/work/dlp-core", "title": ""},
                    {"path": "/home/demo/work/dlp-core", "title": "x", "branch": "gibts/nicht"},
                    {"path": "/etc", "title": "x"}):
            with self.assertRaises(server.UserError):
                a.workspaces_action("task", bad)
        with self.assertRaises(server.UserError):
            a.workspaces_action("fetch", {"path": "/irgendwo"})
        self.assertIn("totals", a.workspaces_action("fetch", {"path": "/home/demo/work/dlp-core"}))

    def test_disabled(self):
        a = self.app(workspaces={"enabled": False})
        self.assertEqual(a.workspaces_state(), {"enabled": False})
        self.assertIsNone(a.overview()["workspaces"])

    def test_never_pushes(self):
        src = (ROOT / "workspaces.py").read_text(encoding="utf-8")
        calls = [l for l in src.splitlines() if "_git(" in l and '"push"' in l]
        self.assertEqual(calls, [])
        for verb in ('"commit"', '"checkout"', '"reset"', '"merge"', '"rebase"', '"clean"', '"stash", "pop"', '"stash", "drop"', '"branch", "-D"'):
            self.assertNotIn(verb, src)


if __name__ == "__main__":
    unittest.main()
