"""Version, CHANGELOG und Image-Tag müssen zusammenpassen."""
import re
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "deploy"))

import server  # noqa: E402
import k8s  # noqa: E402

SEMVER = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")


class Version(unittest.TestCase):
    def test_is_semver(self):
        self.assertRegex(server.VERSION, SEMVER)

    def test_changelog_top_entry_matches(self):
        heads = re.findall(r"^## \[([^\]]+)\]", (ROOT / "CHANGELOG.md").read_text(encoding="utf-8"), re.M)
        self.assertTrue(heads)
        self.assertEqual(heads[0], server.VERSION)
        self.assertTrue(all(SEMVER.match(h) for h in heads))

    def test_deploy_reads_same_version(self):
        self.assertEqual(k8s.version(), server.VERSION)

    def test_cli_version(self):
        r = subprocess.run([sys.executable, str(ROOT / "server.py"), "--version"], capture_output=True, text=True)
        self.assertEqual(r.stdout.strip(), "tinyops " + server.VERSION)

    def test_tag_is_docker_safe_and_carries_version(self):
        import os
        old = os.environ.pop("TINYOPS_TAG", None)
        try:
            c = k8s.Ctx.__new__(k8s.Ctx)
            t = c.tag()
        finally:
            if old:
                os.environ["TINYOPS_TAG"] = old
        self.assertTrue(t.startswith(server.VERSION), t)
        self.assertRegex(t, r"^[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}$")      # kein «+»
