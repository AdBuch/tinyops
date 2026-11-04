"""deploy/k8s.py mit falschen kubectl/docker-Programmen: prüft die Befehle, ohne einen Cluster zu brauchen (nur POSIX)."""
import json
import os
import re
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CLI = ROOT / "deploy" / "k8s.py"

STUB = """#!/usr/bin/env python3
import json, os, sys
log = os.environ["STUB_LOG"]
stdin = "" if sys.stdin.isatty() else sys.stdin.read()
open(log, "a").write(json.dumps({"prog": os.path.basename(sys.argv[0]), "args": sys.argv[1:], "stdin": stdin}) + "\\n")
a = sys.argv[1:]
while a[:1] in (["-n"], ["--context"]):
    a = a[2:]
if "kustomize" in a:
    sys.stdout.write("kind: Deployment\\nspec:\\n  initContainers:\\n  - image: tinyops:latest\\n  containers:\\n  - image: tinyops:latest\\n")
elif a[:2] == ["get", "secret"] and "-o" in a and a[a.index("-o") + 1] == "json":
    import base64
    if os.environ.get("STUB_SECRET") == "none":
        sys.exit(1)
    sys.stdout.write(json.dumps({"data": {"TINYOPS_ACCESS_TOKEN": base64.b64encode(b"alt-token").decode(), "TINYOPS_GITLAB_TOKEN": base64.b64encode(b"alt-gl").decode()}}))
elif a[:2] == ["get", "secret"]:
    sys.exit(1 if os.environ.get("STUB_SECRET") == "none" else 0)
elif "create" in a and "namespace" in a:
    sys.stdout.write("kind: Namespace\\n")
elif "create" in a and "--dry-run=client" in a:
    f = a[a.index("--from-env-file") + 1] if "--from-env-file" in a else None
    sys.stdout.write("kind: Secret\\n" + (open(f).read() if f else ""))
elif "rollout" in a and "status" in a and os.environ.get("STUB_ROLLOUT_FAIL"):
    sys.exit(1)
"""


class Cli(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.bin = Path(self.tmp.name, "bin")
        self.bin.mkdir()
        for n in ("kubectl", "docker", "podman"):
            p = self.bin / n
            p.write_text(STUB)
            p.chmod(p.stat().st_mode | stat.S_IEXEC)
        self.log = Path(self.tmp.name, "calls.jsonl")

    def tearDown(self):
        self.tmp.cleanup()

    def run_cli(self, *args, env=None):
        e = {k: v for k, v in os.environ.items() if not k.startswith(("TINYOPS_", "GITLAB_TOKEN", "JIRA_TOKEN", "LLM_KEY", "STUB_"))}
        e.update(PATH=str(self.bin) + os.pathsep + e["PATH"], STUB_LOG=str(self.log), TINYOPS_REGISTRY="reg.firma.ch/team", TINYOPS_TAG="t1")
        e.update(env or {})
        r = subprocess.run([sys.executable, str(CLI), *args], env=e, capture_output=True, text=True, timeout=60, stdin=subprocess.DEVNULL)
        calls = [json.loads(x) for x in self.log.read_text().splitlines()] if self.log.exists() else []
        return r, calls

    def test_deploy_puts_real_image_into_manifest_and_waits(self):
        r, calls = self.run_cli("deploy")
        self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
        apply = next(c for c in calls if c["args"][-3:] == ["apply", "-f", "-"] and "kind: Deployment" in c["stdin"])
        self.assertIn("image: reg.firma.ch/team/tinyops:t1", apply["stdin"])
        self.assertNotIn("tinyops:latest", apply["stdin"])
        self.assertEqual(apply["stdin"].count("reg.firma.ch/team/tinyops:t1"), 2)          # Init-Container und App
        self.assertTrue(any("rollout" in c["args"] and "status" in c["args"] for c in calls))
        self.assertEqual(apply["args"][:2], ["-n", "tinyops"])                       # nie im falschen Namespace

    def test_deploy_refuses_without_secret(self):
        r, calls = self.run_cli("deploy", env={"STUB_SECRET": "none"})
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("python deploy/k8s.py secret", r.stderr)
        self.assertFalse(any("kustomize" in c["args"] for c in calls))

    def test_failed_rollout_shows_hints_and_fails(self):
        r, calls = self.run_cli("deploy", env={"STUB_ROLLOUT_FAIL": "1"})
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("ImagePullBackOff", r.stderr)
        self.assertTrue(any("describe" in c["args"] for c in calls))
        self.assertTrue(any("logs" in c["args"] for c in calls))

    def test_secret_merges_with_existing_and_never_uses_commandline(self):
        r, calls = self.run_cli("secret", "--no-prompt", env={"JIRA_TOKEN": "neuer-jira"})
        self.assertEqual(r.returncode, 0, r.stderr)
        created = next(c for c in calls if "create" in c["args"] and "secret" in c["args"])
        applied = next(c for c in calls if c["args"][-2:] == ["-f", "-"] and "kind: Secret" in c["stdin"])
        for k, v in (("TINYOPS_ACCESS_TOKEN", "alt-token"), ("TINYOPS_GITLAB_TOKEN", "alt-gl"), ("TINYOPS_JIRA_TOKEN", "neuer-jira")):
            self.assertIn("%s=%s" % (k, v), applied["stdin"])        # Altes bleibt, Neues kommt dazu
        self.assertNotIn("neuer-jira", " ".join(created["args"]))     # nie in der Befehlszeile
        self.assertNotIn("neuer-jira", r.stdout + r.stderr)

    def test_secret_generates_access_token_and_requires_gitlab_token(self):
        r, _ = self.run_cli("secret", "--no-prompt", env={"STUB_SECRET": "none"})
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("GitLab-Token fehlt", r.stderr)
        r, calls = self.run_cli("secret", "--no-prompt", env={"STUB_SECRET": "none", "GITLAB_TOKEN": "glpat-x"})
        self.assertEqual(r.returncode, 0, r.stderr)
        applied = next(c for c in calls if c["args"][-2:] == ["-f", "-"] and "kind: Secret" in c["stdin"])
        tok = [l for l in applied["stdin"].splitlines() if l.startswith("TINYOPS_ACCESS_TOKEN=")][0].split("=", 1)[1]
        self.assertGreaterEqual(len(tok), 30)
        self.assertNotIn("glpat-x", r.stdout + r.stderr)

    def test_registry_required_and_podman(self):
        r, _ = self.run_cli("build", env={"TINYOPS_REGISTRY": ""})
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("Registry", r.stderr)
        r, calls = self.run_cli("build", env={"TINYOPS_DOCKER": "podman"})
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(calls[0]["prog"], "podman")
        self.assertEqual(calls[0]["args"][:5], ["build", "--build-arg", "VERSION=" + re.search(r"^VERSION = \"([^\"]+)\"", (ROOT / "server.py").read_text(), re.M).group(1), "-t", "reg.firma.ch/team/tinyops:t1"])

    def test_purge_and_reseed_need_confirmation(self):
        for cmd in ("purge", "reseed"):
            r, calls = self.run_cli(cmd)
            self.assertNotEqual(r.returncode, 0)
            self.assertIn("--yes", r.stderr)
            self.assertEqual(calls, [])
        r, calls = self.run_cli("undeploy")
        self.assertEqual(r.returncode, 0)
        self.assertFalse(any("pvc" in " ".join(c["args"]) for c in calls))     # Daten bleiben

    def test_token_and_context(self):
        r, _ = self.run_cli("token", env={"TINYOPS_CONTEXT": "prod-test"})
        self.assertEqual(r.returncode, 0)
        self.assertIn("http://localhost:8765/?token=alt-token", r.stdout)
        r, calls = self.run_cli("preflight", env={"TINYOPS_CONTEXT": "prod-test", "TINYOPS_NAMESPACE": "mein-ns"})
        self.assertEqual(calls[-1]["args"], ["--context", "prod-test", "-n", "mein-ns", "exec", "deployment/tinyops", "--", "python", "server.py", "--preflight"])


if __name__ == "__main__":
    unittest.main()
