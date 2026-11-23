"""0.40: Update aus dem Panel (neue Version erkennen, über start.py aktualisieren, zurück bei Fehlern) und Dienst unter Linux."""
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import updater  # noqa: E402

GIT = ["git", "-c", "user.name=T", "-c", "user.email=t@x", "-c", "init.defaultBranch=main"]


def sh(cwd, *args):
    subprocess.run(list(args), cwd=cwd, check=True, capture_output=True)


def fake_release(repo, version, selftest_ok=True):
    """Ein «Release» des Mini-tinyops: server.py mit VERSION und einem Selbsttest, dazu der echte Starter."""
    (repo / "server.py").write_text('VERSION = "%s"\nimport sys\nsys.exit(%d)\n' % (version, 0 if selftest_ok else 1))
    sh(repo, *GIT, "add", "-A")
    sh(repo, *GIT, "commit", "-qm", "v" + version)
    sh(repo, *GIT, "tag", "v" + version)


class Updates(unittest.TestCase):
    def setUp(self):
        self.d = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.d, True)
        self.old = dict(os.environ)
        os.environ["TINYOPS_HOME"] = str(self.d / "home")
        self.addCleanup(lambda: (os.environ.clear(), os.environ.update(self.old)))
        self.origin = self.d / "origin"
        self.origin.mkdir()
        sh(self.origin, *GIT, "init", "-q")
        shutil.copy(ROOT / "start.py", self.origin / "start.py")
        fake_release(self.origin, "0.39.0")
        self.app = self.d / "app"
        sh(self.d, *GIT, "clone", "-q", str(self.origin), str(self.app))
        sh(self.app, "git", "checkout", "-q", "--detach", "v0.39.0")

    def up(self):
        return updater.Updater(self.app, "0.39.0", argv=[])

    def test_nothing_new(self):
        st = self.up().check()
        self.assertEqual((st["latest"], st["available"], st["can_update"]), ("v0.39.0", False, False))

    def test_new_release_and_update(self):
        fake_release(self.origin, "0.41.0")
        u = self.up()
        st = u.check()
        self.assertEqual((st["latest"], st["available"], st["can_update"], st["why"]), ("v0.41.0", True, True, ""))
        self.assertEqual(subprocess.run(["git", "-C", str(self.app), "describe", "--tags"], capture_output=True, text=True).stdout.strip(), "v0.39.0",
                         "Nachsehen darf nichts ändern")
        out = u.run(restart=False)
        self.assertTrue(out["changed"], out["text"])
        self.assertEqual(out["version"], "0.41.0")
        self.assertIn("Aktualisiert: v0.39.0 → v0.41.0", out["text"])
        self.assertTrue((self.d / "home" / "last-update.json").exists())       # Hinweis im Panel nach dem Neustart

    def test_failing_selftest_goes_back(self):
        fake_release(self.origin, "0.41.0", selftest_ok=False)
        out = self.up().run(restart=False)
        self.assertFalse(out["changed"])
        self.assertIn("zurück auf v0.39.0", out["text"])
        self.assertIn('VERSION = "0.39.0"', (self.app / "server.py").read_text())

    def test_branch_or_dirty_blocks(self):
        fake_release(self.origin, "0.41.0")
        (self.app / "server.py").write_text("geändert\n")
        st = self.up().check()
        self.assertTrue(st["available"])
        self.assertFalse(st["can_update"])
        self.assertIn("geändert", st["why"])
        self.assertFalse(self.up().run(restart=False)["changed"])
        sh(self.app, "git", "checkout", "-q", "--", "server.py")
        sh(self.app, "git", "checkout", "-q", "-b", "dev")
        st = self.up().check()
        self.assertIn("Branch dev", st["why"])
        self.assertFalse(st["can_update"])

    def test_no_git_checkout(self):
        st = updater.Updater(self.d / "nirgends", "0.39.0", argv=[]).check()
        self.assertFalse(st["can_update"])
        self.assertIn("Kein Git-Checkout", st["why"])

    def test_release_url(self):
        self.assertEqual(updater.release_url("https://github.com/AdBuch/tinyops.git", "v0.40.0"), "https://github.com/AdBuch/tinyops/releases/tag/v0.40.0")
        self.assertEqual(updater.release_url("git@github.com:AdBuch/tinyops.git", "v1.0.0"), "https://github.com/AdBuch/tinyops/releases/tag/v1.0.0")
        self.assertEqual(updater.release_url("https://gitlab.example/x/y.git", "v1.0.0"), "")


@unittest.skipUnless(sys.platform.startswith("linux"), "nur Linux")
class Service(unittest.TestCase):
    def test_install_and_remove_with_fake_systemctl(self):
        d = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, d, True)
        b = d / "bin"
        b.mkdir()
        (b / "systemctl").write_text('#!/bin/sh\necho "$@" >> %s\ncase "$2" in is-active) echo active;; is-enabled) echo enabled;; esac\n' % (d / "calls"))
        (b / "systemctl").chmod(0o755)
        old = dict(os.environ)
        self.addCleanup(lambda: (os.environ.clear(), os.environ.update(old)))
        os.environ["PATH"] = str(b) + os.pathsep + os.environ["PATH"]
        os.environ.pop("TINYOPS_SERVICE", None)
        u = updater.Updater(ROOT, "0.40.0", argv=["--config", "/tmp/eigene config.json"], unit_dir=d / "units")
        self.assertFalse(u.service()["installed"])
        st = u.install_service()
        unit = (d / "units" / "tinyops.service").read_text()
        self.assertIn("ExecStart=%s %s --config '/tmp/eigene config.json'" % (sys.executable, ROOT / "start.py"), unit)
        self.assertIn("Restart=on-failure", unit)
        self.assertIn("Environment=TINYOPS_SERVICE=1", unit)
        self.assertIn("WantedBy=default.target", unit)
        self.assertEqual((st["installed"], st["active"], st["enabled"]), (True, True, True))
        calls = (d / "calls").read_text()
        self.assertIn("--user daemon-reload", calls)
        self.assertIn("--user enable tinyops.service", calls)
        st = u.remove_service()
        self.assertFalse(st["installed"])
        self.assertIn("--user disable tinyops.service", (d / "calls").read_text())

    def test_routes_keep_paired_devices_out(self):
        src = (ROOT / "routes.py").read_text(encoding="utf-8")
        self.assertIn('path in ("/api/update/run", "/api/update/service")', src)


if __name__ == "__main__":
    unittest.main()
