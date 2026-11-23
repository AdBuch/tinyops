"""0.41: Branch übernehmen (Agent → Feature-Branch): Fast-Forward, Merge, Rebase, Cherry-Pick, Konflikte, nie push."""
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import integrate  # noqa: E402
import server  # noqa: E402

G = ["git", "-c", "user.name=T", "-c", "user.email=t@x", "-c", "init.defaultBranch=main"]


def git(cwd, *a):
    r = subprocess.run(G + list(a), cwd=cwd, capture_output=True, text=True)
    if r.returncode:
        raise AssertionError("git %s: %s" % (a, r.stderr))
    return r.stdout.strip()


def commit(cwd, name, text, msg):
    Path(cwd, name).write_text(text)
    git(cwd, "add", "-A")
    git(cwd, "commit", "-qm", msg)
    return git(cwd, "rev-parse", "HEAD")


class Base(unittest.TestCase):
    """origin (bare) mit main und feature/X; ein Agent hat agent/x-1 von feature/X gepusht; dein Checkout steht auf main."""

    def setUp(self):
        self.d = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.d, True)
        git(self.d, "init", "-q", "--bare", "origin.git")
        seed = self.d / "seed"
        git(self.d, "clone", "-q", str(self.d / "origin.git"), str(seed))
        commit(seed, "a.txt", "eins\nzwei\ndrei\n", "start")
        git(seed, "push", "-q", "origin", "main")
        git(seed, "checkout", "-qb", "feature/X")
        commit(seed, "f.txt", "feature\n", "feature: erster Schritt")
        git(seed, "push", "-q", "origin", "feature/X")
        git(seed, "checkout", "-qb", "agent/x-1")
        commit(seed, "b.txt", "agent 1\n", "agent: b")
        commit(seed, "c.txt", "agent 2\n", "agent: c")
        git(seed, "push", "-q", "origin", "agent/x-1")
        self.seed = seed
        self.repo = self.d / "work"
        git(self.d, "clone", "-q", str(self.d / "origin.git"), str(self.repo))
        git(self.repo, "config", "user.name", "Du")            # wie bei dir: dein Checkout kennt deinen Namen (CI hat keinen)
        git(self.repo, "config", "user.email", "du@example.org")
        self.i = integrate.Integrator(wt_base=self.d / "wt")
        self.origin_heads = self.heads()

    def heads(self):
        return git(self.d / "origin.git", "for-each-ref", "--format=%(refname) %(objectname)", "refs/heads")

    def local(self, ref):
        return git(self.repo, "rev-parse", ref)

    def feature_moves_on(self):
        """Auf GitLab kam inzwischen etwas auf feature/X dazu: kein Fast-Forward mehr."""
        git(self.seed, "checkout", "-q", "feature/X")
        commit(self.seed, "f.txt", "feature\nmehr\n", "feature: zweiter Schritt")
        git(self.seed, "push", "-q", "origin", "feature/X")
        self.origin_heads = self.heads()

    def tearDown(self):
        self.assertEqual(self.heads(), self.origin_heads, "tinyops darf nie pushen")
        self.assertEqual(git(self.repo, "symbolic-ref", "--short", "HEAD"), "main", "dein Checkout bleibt auf seinem Branch")


class Plan(Base):
    def test_plan_ff(self):
        p = self.i.plan(self.repo, "agent/x-1", "feature/X")
        self.assertEqual([c["subject"] for c in p["commits"]], ["agent: b", "agent: c"])
        self.assertTrue(p["can_ff"])
        self.assertEqual(p["conflicts"], [])
        self.assertIn("git -C", p["push"])

    def test_plan_conflict_predicted(self):
        git(self.seed, "checkout", "-q", "feature/X")
        commit(self.seed, "b.txt", "anders\n", "feature: b anders")
        git(self.seed, "push", "-q", "origin", "feature/X")
        self.origin_heads = self.heads()
        p = self.i.plan(self.repo, "agent/x-1", "feature/X")
        self.assertFalse(p["can_ff"])
        self.assertEqual(p["conflicts"], ["b.txt"])

    def test_bad_names_and_missing(self):
        with self.assertRaises(integrate.IntegrateError):
            self.i.plan(self.repo, "--upload-pack=x", "feature/X")
        with self.assertRaises(integrate.IntegrateError) as e:
            self.i.plan(self.repo, "agent/gibts-nicht", "feature/X")
        self.assertIn("pushen", str(e.exception))


class Run(Base):
    def test_fast_forward_creates_local_branch(self):
        out = self.i.run(self.repo, "agent/x-1", "feature/X", "ff")
        self.assertEqual((out["ok"], out["added"], out["ahead"]), (True, 2, 2))
        self.assertEqual(self.local("feature/X"), self.local("origin/agent/x-1"))

    def test_ff_refused_when_target_moved(self):
        self.feature_moves_on()
        with self.assertRaises(integrate.IntegrateError) as e:
            self.i.run(self.repo, "agent/x-1", "feature/X", "ff")
        self.assertIn("Fast-Forward geht nicht", str(e.exception))

    def test_rebase_puts_commits_on_top(self):
        self.feature_moves_on()
        out = self.i.run(self.repo, "agent/x-1", "feature/X", "rebase")
        self.assertEqual(out["added"], 2)
        log = git(self.repo, "log", "--format=%s", "feature/X").splitlines()
        self.assertEqual(log[:4], ["agent: c", "agent: b", "feature: zweiter Schritt", "feature: erster Schritt"])
        self.assertEqual(git(self.repo, "rev-list", "--merges", "--count", "feature/X"), "0")

    def test_merge_makes_merge_commit(self):
        self.feature_moves_on()
        out = self.i.run(self.repo, "agent/x-1", "feature/X", "merge")
        self.assertTrue(out["ok"])
        self.assertEqual(git(self.repo, "log", "-1", "--format=%s", "feature/X"), "Merge agent/x-1 in feature/X")
        self.assertEqual(git(self.repo, "rev-list", "--merges", "--count", "origin/feature/X..feature/X"), "1")

    def test_cherry_pick_selected(self):
        p = self.i.plan(self.repo, "agent/x-1", "feature/X")
        c = [x["sha"] for x in p["commits"] if x["subject"] == "agent: c"]
        out = self.i.run(self.repo, "agent/x-1", "feature/X", "pick", commits=c)
        self.assertEqual(out["added"], 1)
        self.assertEqual(git(self.repo, "log", "-1", "--format=%s", "feature/X"), "agent: c")
        self.assertEqual(git(self.repo, "show", "feature/X:c.txt"), "agent 2")
        self.assertNotEqual(subprocess.run(["git", "-C", str(self.repo), "show", "feature/X:b.txt"], capture_output=True).returncode, 0)

    def test_conflict_rolls_back(self):
        git(self.seed, "checkout", "-q", "feature/X")
        commit(self.seed, "b.txt", "anders\n", "feature: b anders")
        git(self.seed, "push", "-q", "origin", "feature/X")
        self.origin_heads = self.heads()
        before = git(self.repo, "for-each-ref", "refs/heads")
        out = self.i.run(self.repo, "agent/x-1", "feature/X", "merge")
        self.assertEqual((out["ok"], out["conflict"]), (False, ["b.txt"]))
        self.assertEqual(git(self.repo, "for-each-ref", "refs/heads"), before)
        self.assertEqual(git(self.repo, "worktree", "list").count("\n"), 0, "kein Worktree bleibt liegen")

    def test_conflict_resolved_in_worktree_then_finish(self):
        git(self.seed, "checkout", "-q", "feature/X")
        commit(self.seed, "b.txt", "anders\n", "feature: b anders")
        git(self.seed, "push", "-q", "origin", "feature/X")
        self.origin_heads = self.heads()
        out = self.i.run(self.repo, "agent/x-1", "feature/X", "merge", keep_on_conflict=True)
        wt = Path(out["worktree"])
        self.assertTrue(out["token"])
        with self.assertRaises(integrate.IntegrateError):
            self.i.finish(out["token"])                       # noch nicht gelöst
        (wt / "b.txt").write_text("gelöst\n")
        git(wt, "add", "b.txt")
        git(wt, "commit", "-qm", "Merge gelöst")
        res = self.i.finish(out["token"])
        self.assertTrue(res["ok"])
        self.assertEqual(git(self.repo, "show", "feature/X:b.txt"), "gelöst")
        self.assertFalse(wt.exists())

    def test_checked_out_target_fast_forwards_there_or_refuses_when_dirty(self):
        user = self.d / "feature-checkout"
        git(self.repo, "worktree", "add", "-q", str(user), "-b", "feature/X", "origin/feature/X")
        (user / "f.txt").write_text("in Arbeit\n")
        with self.assertRaises(integrate.IntegrateError) as e:
            self.i.run(self.repo, "agent/x-1", "feature/X", "rebase")
        self.assertIn("geänderte Dateien", str(e.exception))
        git(user, "checkout", "--", "f.txt")
        out = self.i.run(self.repo, "agent/x-1", "feature/X", "rebase")
        self.assertEqual(out["checked_out"], str(user))
        self.assertEqual((user / "c.txt").read_text(), "agent 2\n")     # der Checkout wurde nachgezogen
        git(self.repo, "worktree", "remove", str(user))

    def test_missing_identity_is_explained(self):
        self.feature_moves_on()
        git(self.repo, "config", "--unset", "user.name")
        env = dict(os.environ)
        try:
            os.environ.update(HOME=str(self.d), GIT_CONFIG_NOSYSTEM="1", GIT_AUTHOR_NAME="", GIT_COMMITTER_NAME="")   # wie auf GitHub: kein Name
            with self.assertRaises(integrate.IntegrateError) as e:
                self.i.run(self.repo, "agent/x-1", "feature/X", "merge")
        finally:
            os.environ.clear()
            os.environ.update(env)
        self.assertIn("git config --global user.name", str(e.exception))
        self.assertEqual(git(self.repo, "worktree", "list").count("\n"), 0, "kein Worktree bleibt liegen")

    def test_diverged_local_is_refused(self):
        git(self.repo, "branch", "feature/X", "origin/feature/X")
        wt = self.d / "tmp"
        git(self.repo, "worktree", "add", "-q", str(wt), "feature/X")
        commit(wt, "lokal.txt", "x\n", "lokal")
        git(self.repo, "worktree", "remove", str(wt))
        self.feature_moves_on()
        with self.assertRaises(integrate.IntegrateError) as e:
            self.i.run(self.repo, "agent/x-1", "feature/X", "merge")
        self.assertIn("auseinandergelaufen", str(e.exception))


class AppLevel(Base):
    def test_branch_action_and_audit(self):
        c = server.load_config(None)
        c.update(data_dir=str(self.d / "data"), projects=[{"id": 1, "name": "dlp-core", "repo_path": str(self.repo)}])
        os.environ.setdefault("TINYOPS_HOME", str(self.d / "home"))
        app = server.App(c, False, {}, self.d / "config.json", watchdog=False)
        app._integ = integrate.Integrator(wt_base=self.d / "wt")
        p = app.branch_action("plan", {"project_id": 1, "source": "agent/x-1", "target": "feature/X"})
        self.assertEqual(p["count"], 2)
        out = app.branch_action("run", {"project_id": 1, "source": "agent/x-1", "target": "feature/X", "how": "rebase"})
        self.assertTrue(out["ok"])
        rows = [r for r in app.audit_log.export() if r["action"] == "branch.integrate"]
        self.assertEqual(len(rows), 1)
        with self.assertRaises(server.UserError):
            app.branch_action("run", {"project_id": 9, "source": "agent/x-1", "target": "feature/X", "how": "ff"})


if __name__ == "__main__":
    unittest.main()
