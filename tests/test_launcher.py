"""Launcher (0.21.1): erster Start klont auf das neueste Release, danach übernimmt start.py; auch als Zipapp."""
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "launcher"))
from test_start import FAKE_SERVER, GIT, git  # noqa: E402


class Launcher(unittest.TestCase):
    def setUp(self):
        self.d = Path(tempfile.mkdtemp())
        self.origin = self.d / "origin.git"
        subprocess.run(GIT + ["init", "-q", "--bare", str(self.origin)], check=True)
        self.dev = self.d / "dev"
        subprocess.run(GIT + ["clone", "-q", str(self.origin), str(self.dev)], check=True, capture_output=True)
        shutil.copy(ROOT / "start.py", self.dev / "start.py")
        for v in ("0.1.0", "0.2.0"):
            self.release(v)
        self.app = self.d / "app"
        self.env = dict(os.environ, TINYOPS_HOME=str(self.d / "home"))

    def release(self, v):
        (self.dev / "server.py").write_text(FAKE_SERVER % True)
        (self.dev / "CHANGELOG.md").write_text("# Changelog\n\n## [%s]\n- x\n" % v)
        git(self.dev, "add", "-A")
        git(self.dev, "commit", "-qm", v)
        git(self.dev, "tag", "-a", "v" + v, "-m", v)
        git(self.dev, "push", "-q", "origin", "HEAD:main", "--tags")

    def launch(self, *a, pyz=False):
        prog = [sys.executable, str(self.pyz)] if pyz else [sys.executable, str(ROOT / "launcher" / "tinyops_launcher.py")]
        r = subprocess.run(prog + ["--dir", str(self.app), "--repo", str(self.origin), "--no-browser"] + list(a), capture_output=True, text=True,
                           timeout=120, env=self.env)
        return r.returncode, r.stdout + r.stderr

    def test_first_start_then_update(self):
        rc, out = self.launch("--demo")
        self.assertEqual(rc, 0, out)
        self.assertIn("Installiert: v0.2.0", out)
        self.assertIn("server gestartet ['--demo']", out)
        self.assertEqual(git(self.app, "describe", "--tags"), "v0.2.0")
        self.release("0.3.0")
        rc, out = self.launch()
        self.assertIn("v0.2.0 → v0.3.0", out)                  # ab jetzt aktualisiert start.py
        self.assertEqual(git(self.app, "describe", "--tags"), "v0.3.0")
        rc, out = self.launch("--where")
        self.assertIn("Version: v0.3.0", out)

    def test_zipapp(self):
        sys.path.insert(0, str(ROOT / "launcher"))
        import build
        self.pyz = build.build(self.d / "l.pyz")
        rc, out = self.launch(pyz=True)
        self.assertEqual(rc, 0, out)
        self.assertIn("server gestartet", out)
        r = subprocess.run([sys.executable, str(self.pyz), "--version"], capture_output=True, text=True)
        self.assertIn("tinyops-launcher", r.stdout)

    def test_refuses_foreign_dir_and_bad_repo(self):
        self.app.mkdir()
        (self.app / "meins.txt").write_text("x")
        rc, out = self.launch()
        self.assertEqual(rc, 2)
        self.assertIn("nicht leer", out)
        shutil.rmtree(self.app)
        self.origin = self.d / "gibtsnicht.git"
        rc, out = self.launch()
        self.assertEqual(rc, 1)
        self.assertIn("Herunterladen fehlgeschlagen", out)

    def test_hints(self):
        import tinyops_launcher as tl
        self.assertIn("git", tl.hint_install("git"))
        self.assertIn("Python", tl.hint_install("python"))
        self.assertTrue(tl.find_python())
        self.assertEqual(tl.read_port(["--port", "9000"]), 9000)


if __name__ == "__main__":
    unittest.main()
