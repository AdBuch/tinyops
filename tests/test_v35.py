"""0.35: weniger Begriffe (E3 Spielstand, E4 Fokus), Korrekturen aus Nutzungsbericht und Verlauf vom 16.11.:
Worktrees in Workspaces, lesbare Fetch-Fehler, Ideenpool statt Sackgasse, kein Verlaufseintrag ohne Änderung."""
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import server  # noqa: E402
import settings  # noqa: E402
import workspaces  # noqa: E402
from test_agents import GIT, git_repo  # noqa: E402
from test_board import BoardApp  # noqa: E402


def git(cwd, *a):
    return subprocess.run(GIT + list(a), cwd=cwd, capture_output=True, text=True)


class Worktrees(unittest.TestCase):
    def setUp(self):
        self.d = Path(tempfile.mkdtemp())
        self.repo = git_repo(self.d / "repo")

    def test_remove_only_safe(self):
        wt = self.d / ".tinyops-wt" / "repo-run1"
        self.assertEqual(git(self.repo, "worktree", "add", "-q", "-b", "agent/x-1", str(wt)).returncode, 0)
        (wt / "f.txt").write_text("x")
        ok, msg = workspaces.worktree_remove(str(self.repo), str(wt))
        self.assertFalse(ok)
        self.assertIn("1 geänderte Dateien", msg)                                   # schmutzig: bleibt
        git(wt, "add", "-A")
        git(wt, "commit", "-qm", "x")
        self.assertEqual(workspaces.worktree_remove(str(self.repo), str(wt)), (True, "Worktree entfernt."))   # Commit liegt auf agent/x-1
        self.assertFalse(wt.exists())
        self.assertEqual(git(self.repo, "rev-parse", "--verify", "-q", "agent/x-1").returncode, 0)            # der Branch bleibt

    def test_detached_commit_only_here_is_kept(self):
        wt = self.d / "wt-detached"
        git(self.repo, "worktree", "add", "-q", "--detach", str(wt))
        (wt / "g.txt").write_text("y")
        git(wt, "add", "-A")
        git(wt, "commit", "-qm", "nur hier")
        ok, msg = workspaces.worktree_remove(str(self.repo), str(wt))
        self.assertFalse(ok)
        self.assertIn("auf keinem Branch", msg)
        self.assertTrue(wt.exists())

    def test_missing_folder_is_pruned_and_unknown_refused(self):
        wt = self.d / "wt-gone"
        git(self.repo, "worktree", "add", "-q", "--detach", str(wt))
        import shutil
        shutil.rmtree(wt)
        self.assertTrue(workspaces.worktree_remove(str(self.repo), str(wt))[0])
        self.assertNotIn(str(wt), git(self.repo, "worktree", "list").stdout)
        self.assertFalse(workspaces.worktree_remove(str(self.repo), str(self.d / "nix"))[0])
        self.assertFalse(workspaces.worktree_remove(str(self.repo), str(self.repo))[0])          # das Repo selbst nie

    def test_scan_counts(self):
        wt = self.d / ".tinyops-wt" / "repo-mr1"
        git(self.repo, "worktree", "add", "-q", "--detach", str(wt))
        r = workspaces.read_repo(self.repo) if hasattr(workspaces, "read_repo") else None
        res = workspaces.scan([{"path": str(self.d)}])
        t = workspaces.totals(res)
        self.assertEqual((t["worktrees"], t["worktrees_tidy"]), (1, 1))                       # sauber und von tinyops: aufräumbar
        self.assertIsNone(r if r is None else None)


class FetchHint(unittest.TestCase):
    def test_messages(self):
        gl = "remote: \nremote: ====\nremote: The project you were looking for could not be found or you don't have permission to view it.\nfatal: x"
        self.assertIn("kennt dieses Projekt nicht", workspaces.fetch_hint(gl))
        self.assertIn("nicht erreichbar", workspaces.fetch_hint("ssh: Could not resolve host: git.example"))
        self.assertIn("SSH-Schlüssel", workspaces.fetch_hint("Permission denied (publickey)."))
        self.assertEqual(workspaces.fetch_hint("fatal: etwas anderes\n"), "Abholen fehlgeschlagen: fatal: etwas anderes")
        self.assertEqual(workspaces.fetch_hint(""), "Abholen fehlgeschlagen: git fetch meldet einen Fehler")


class PoolNoDeadEnd(BoardApp):
    def test_unassign_last_category_back_to_ideas(self):
        pid = self.pool("Produkt X")
        key = self.app.board_action("add", {"title": "Aufgabe", "stage": "idea"})["key"]
        self.app.board_action("assign", {"key": key, "pool_id": pid})
        self.app.board_action("stage", {"key": key, "stage": "planned"})
        with self.assertRaises(server.UserError) as cm:
            self.app.board_action("unassign", {"key": key, "pool_id": pid})
        self.assertEqual(cm.exception.data, {"to_pool": True})                   # die Oberfläche fragt nach, statt nur zu scheitern
        self.app.board_action("unassign", {"key": key, "pool_id": pid, "to_pool": True})
        card = next(c for c in self.app.overview()["board"]["cards"] if c["id"] == key)
        self.assertEqual((card["pools"], card["stage"]), ([], "idea"))


class Terms(unittest.TestCase):
    def test_score_switch_and_terms(self):
        self.assertTrue(server.DEFAULTS["features"]["score"])
        new, errors = settings.build_config({}, {"features": {"ideas": True, "ai": False, "score": False}})
        self.assertEqual(new["features"]["score"], False)
        html = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
        self.assertIn('id="ft-score"', html)
        self.assertIn("F().score === false", html)
        self.assertNotIn(">Fokus-Modus<", html)                                   # E4: ein Begriff weniger
        self.assertNotIn("'Fokusbereiche'", html)
        self.assertNotIn("Level ${s.level}", html)                                # E3: ein Zähler, kein Level mehr

    def test_ui_fixes_present(self):
        html = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
        for n in ("function setOffline(", "data-qtxt=", "QPEND", 'data-wsf="wt"', "data-wtrm", 'data-fsess="area:'):
            self.assertIn(n, html, n)


if __name__ == "__main__":
    unittest.main()


class V351(unittest.TestCase):
    """0.35.1: Korrekturen nach deinem Test am 16.11."""

    def test_bcs_token_can_be_stored(self):
        import secretstore
        self.assertIn("bcs_token", secretstore.NAMES)                 # seit 0.29 liess sich das Token der Middleware nicht speichern
        self.assertNotIn("mcp_token", secretstore.NAMES)
        for n in settings.SECRET_FIELDS:
            self.assertIn(n, secretstore.NAMES, n)                   # jedes Feld der Einstellungen ist auch speicherbar

    def test_bcs_lan_only_with_flag_and_private(self):
        import bcs
        with self.assertRaises(bcs.BcsError) as e:
            bcs.check_url("http://10.0.0.5:3210")
        self.assertIn("Middleware im eigenen Netz", str(e.exception))
        self.assertEqual(bcs.check_url("http://10.0.0.5:3210/", allow_lan=True), "http://10.0.0.5:3210")
        self.assertEqual(bcs.check_url("http://192.168.1.5:3210", allow_lan=True), "http://192.168.1.5:3210")
        with self.assertRaises(bcs.BcsError):
            bcs.check_url("http://8.8.8.8:3210", allow_lan=True)          # öffentlich bleibt verboten
        self.assertEqual(bcs.check_url("http://127.0.0.1:3210"), "http://127.0.0.1:3210")

    def test_settings_keep_lan_flag(self):
        cfg, err = settings.build_config({}, {"time": {"bcs": {"enabled": True, "url": "http://10.0.0.5:3210", "allow_lan": True}}})
        self.assertEqual(err, {})
        self.assertTrue(cfg["time"]["bcs"]["allow_lan"])
        cfg, err = settings.build_config({}, {"time": {"bcs": {"enabled": True, "url": "http://10.0.0.5:3210"}}})
        self.assertIn("time.bcs.url", err)

    def test_score_on_when_old_config_lacks_key(self):
        import server
        self.assertTrue(server.feature({"features": {"ideas": True, "ai": False}}, "score"))   # Config von vor 0.35
        self.assertFalse(server.feature({"features": {"score": False}}, "score"))
        self.assertFalse(server.feature({"features": {}}, "ai"))
