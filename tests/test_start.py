"""Starter (0.21): holt das neueste Release, prüft es mit dem Selbsttest, geht bei Fehlern zurück, ändert nie Unsicheres."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
GIT = ["git", "-c", "user.name=T", "-c", "user.email=t@x", "-c", "init.defaultBranch=main", "-c", "advice.detachedHead=false"]

FAKE_SERVER = '''import sys
OK = %s
if "--selftest" in sys.argv:
    print("  OK   Fake" if OK else "  FAIL Fake kaputt")
    sys.exit(0 if OK else 1)
print("server gestartet", sys.argv[1:])
'''


def git(cwd, *a):
    return subprocess.run(GIT + list(a), cwd=str(cwd), check=True, capture_output=True, text=True).stdout.strip()


class Starter(unittest.TestCase):
    def setUp(self):
        self.d = Path(tempfile.mkdtemp())
        self.origin = self.d / "origin.git"
        subprocess.run(GIT + ["init", "-q", "--bare", str(self.origin)], check=True)
        self.dev = self.d / "dev"
        subprocess.run(GIT + ["clone", "-q", str(self.origin), str(self.dev)], check=True, capture_output=True)
        shutil.copy(ROOT / "start.py", self.dev / "start.py")
        self.release("0.1.0")
        self.release("0.2.0")
        self.work = self.d / "work"
        subprocess.run(GIT + ["clone", "-q", str(self.origin), str(self.work)], check=True, capture_output=True)
        git(self.work, "checkout", "-q", "--detach", "v0.1.0")
        self.home = self.d / "home"

    def release(self, v, ok=True, qa=2):
        (self.dev / "server.py").write_text(FAKE_SERVER % ok)
        cl = (self.dev / "CHANGELOG.md").read_text() if (self.dev / "CHANGELOG.md").exists() else "# Changelog\n"
        (self.dev / "CHANGELOG.md").write_text(cl.replace("# Changelog\n", "# Changelog\n\n## [%s]\n- Neu in %s\n" % (v, v)))
        qc = (self.dev / "QA-CHECKLIST.md").read_text() if (self.dev / "QA-CHECKLIST.md").exists() else "# Prüfliste\n"
        qc += "\n## %s\n\n" % v + "".join("- [ ] `r-%s-%d` Aufgabe → ok\n" % (v, i) for i in range(qa))
        (self.dev / "QA-CHECKLIST.md").write_text(qc)
        git(self.dev, "add", "-A")
        git(self.dev, "commit", "-qm", "release %s" % v)
        git(self.dev, "tag", "-a", "v" + v, "-m", v)
        git(self.dev, "push", "-q", "origin", "HEAD:main", "--tags")

    def run_start(self, *a):
        r = subprocess.run([sys.executable, str(self.work / "start.py"), "--no-start"] + list(a), capture_output=True, text=True, timeout=120,
                           env=dict(os.environ, TINYOPS_HOME=str(self.home)))
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.stdout

    def at(self):
        return git(self.work, "describe", "--tags", "--exact-match", "HEAD")

    def note(self):
        return json.loads((self.home / "last-update.json").read_text())

    def test_update_with_selftest_and_news(self):
        out = self.run_start()
        self.assertEqual(self.at(), "v0.2.0")
        self.assertIn("v0.1.0 → v0.2.0", out)
        self.assertIn("2 neue Prüfpunkte", out)
        self.assertIn("## [0.2.0]", out)
        self.assertNotIn("## [0.1.0]", out)
        n = self.note()
        self.assertEqual((n["from"], n["to"], n["ok"], n["qa_new"], n["seen"]), ("v0.1.0", "v0.2.0", True, 2, False))
        self.assertIn("neuesten Stand", self.run_start())

    def test_failed_selftest_rolls_back(self):
        self.run_start()
        self.release("0.3.0", ok=False)
        out = self.run_start()
        self.assertEqual(self.at(), "v0.2.0")
        self.assertIn("Selbsttest von v0.3.0 fehlgeschlagen", out)
        self.assertIn("FAIL Fake kaputt", out)
        self.assertFalse(self.note()["ok"])

    def test_skips_skipped_releases_and_check(self):
        self.release("0.3.0")
        out = self.run_start("--check")
        self.assertIn("Neu verfügbar: v0.3.0", out)
        self.assertEqual(self.at(), "v0.1.0")
        self.run_start("--no-selftest")
        self.assertEqual(self.at(), "v0.3.0")
        self.assertEqual(self.note()["qa_new"], 4)                # 0.2.0 und 0.3.0

    def test_never_touches_unsafe_checkouts(self):
        (self.work / "server.py").write_text("# lokal geändert\n")
        self.assertIn("Geänderte Dateien", self.run_start())
        self.assertEqual(self.at(), "v0.1.0")
        git(self.work, "checkout", "-q", "--", "server.py")
        git(self.work, "checkout", "-q", "-b", "mein-branch")
        self.assertIn("nicht auf einem Release", self.run_start())
        self.assertEqual(git(self.work, "symbolic-ref", "--short", "HEAD"), "mein-branch")
        (self.work / "config.json").write_text("{}")              # ignorierte/untracked Dateien stören nicht
        git(self.work, "checkout", "-q", "--detach", "v0.1.0")
        self.run_start()
        self.assertEqual(self.at(), "v0.2.0")
        self.assertTrue((self.work / "config.json").exists())

    def test_offline_starts_as_is(self):
        git(self.work, "remote", "set-url", "origin", str(self.d / "gibtsnicht.git"))
        self.assertIn("Nicht erreichbar", self.run_start())
        self.assertEqual(self.at(), "v0.1.0")
        git(self.work, "remote", "remove", "origin")
        self.assertIn("Keine Remote", self.run_start())

    def test_channel_main(self):
        git(self.work, "checkout", "-q", "-B", "main", "v0.1.0")
        git(self.work, "branch", "-q", "--set-upstream-to", "origin/main")
        out = self.run_start("--channel", "main", "--no-selftest")
        self.assertIn("Aktualisiert", out)
        self.assertEqual(git(self.work, "rev-parse", "HEAD"), git(self.dev, "rev-parse", "HEAD"))

    def test_server_args_pass_through(self):
        r = subprocess.run([sys.executable, str(self.work / "start.py"), "--no-update", "--demo", "--port", "9"], capture_output=True, text=True, timeout=30,
                           env=dict(os.environ, TINYOPS_HOME=str(self.home)))
        self.assertIn("server gestartet ['--demo', '--port', '9']", r.stdout)


class PanelNote(unittest.TestCase):
    def test_note_once(self):
        import server
        home = Path(tempfile.mkdtemp())
        os.environ["TINYOPS_HOME"] = str(home)
        cfg = server.load_config(None)
        cfg["data_dir"] = tempfile.mkdtemp()
        a = server.App(cfg, True, {}, Path("/nonexistent/c.json"))
        self.assertIsNone(a.update_note())
        (home / "last-update.json").write_text(json.dumps({"from": "v0.19.0", "to": "v0.20.0", "ok": True, "qa_new": 13, "ts": __import__("time").time(), "seen": False}))
        self.assertEqual(a.overview()["update"]["qa_new"], 13)
        news = a.update_news()["text"]
        self.assertIn("## [0.20.0]", news)
        self.assertNotIn("## [0.19.0]", news)
        a.update_seen()
        self.assertIsNone(a.update_note())


if __name__ == "__main__":
    unittest.main()
