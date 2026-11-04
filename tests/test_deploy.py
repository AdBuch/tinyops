"""Betrieb im Container: Umgebungs-Overrides, /healthz, Preflight gegen die Mock-Server."""
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import server  # noqa: E402


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


class Env(unittest.TestCase):
    def test_overrides(self):
        cfg = {"bind": "127.0.0.1", "port": 8765, "allowed_hosts": []}
        server.apply_env(cfg, {"TINYOPS_BIND": " 0.0.0.0 ", "TINYOPS_PORT": "9000", "TINYOPS_ALLOWED_HOSTS": "a.example, b.example,,"})
        self.assertEqual((cfg["bind"], cfg["port"], cfg["allowed_hosts"]), ("0.0.0.0", 9000, ["a.example", "b.example"]))
        untouched = {"bind": "127.0.0.1", "port": 1, "allowed_hosts": ["x"]}
        server.apply_env(untouched, {})
        self.assertEqual(untouched, {"bind": "127.0.0.1", "port": 1, "allowed_hosts": ["x"]})
        for bad in ("abc", "0", "70000"):
            with self.assertRaises(SystemExit):
                server.apply_env({}, {"TINYOPS_PORT": bad})


class Container(unittest.TestCase):
    """Startet das Panel so wie im Pod: bind 0.0.0.0 per Umgebung, Zugriffstoken aus der Umgebung, Probe ohne Token."""

    def test_healthz_and_protection(self):
        port = free_port()
        with tempfile.TemporaryDirectory() as tmp:
            env = dict(os.environ, TINYOPS_HOME=tmp, TINYOPS_BIND="0.0.0.0", TINYOPS_PORT=str(port), TINYOPS_ALLOWED_HOSTS="tinyops.local",
                       TINYOPS_ACCESS_TOKEN="geheim")
            srv = subprocess.Popen([sys.executable, str(ROOT / "server.py"), "--demo"], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            try:
                wait(port)

                def get(path, host=None, cookie=None):
                    h = {}
                    if host:
                        h["Host"] = host
                    if cookie:
                        h["Cookie"] = cookie
                    try:
                        with urllib.request.urlopen(urllib.request.Request("http://127.0.0.1:%d%s" % (port, path), headers=h), timeout=5) as r:
                            return r.status, r.read()
                    except urllib.error.HTTPError as e:
                        return e.code, e.read()
                code, body = get("/healthz", host="10.1.2.3:8765")   # kubelet kommt mit der Pod-IP als Host
                self.assertEqual(code, 200)
                self.assertEqual(json.loads(body)["ok"], True)
                self.assertNotIn(b"geheim", body)
                self.assertEqual(get("/api/overview", host="tinyops.local")[0], 401)       # ohne Token zu
                self.assertEqual(get("/api/overview", host="10.1.2.3")[0], 403)            # fremder Host zu
                self.assertEqual(get("/", host="evil.example")[0], 403)
            finally:
                srv.terminate()
                srv.wait(5)

    def test_refuses_open_bind_without_token(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = {k: v for k, v in os.environ.items() if not k.startswith("TINYOPS_")}
            env.update(TINYOPS_HOME=tmp, TINYOPS_BIND="0.0.0.0", TINYOPS_PORT=str(free_port()))
            r = subprocess.run([sys.executable, str(ROOT / "server.py"), "--demo"], env=env, capture_output=True, text=True, timeout=20)
            self.assertNotEqual(r.returncode, 0)
            self.assertIn("Zugriffstoken", r.stdout + r.stderr)


class Preflight(unittest.TestCase):
    def run_pf(self, gl_token, extra_env=None):
        gp, jp = free_port(), free_port()
        procs = [subprocess.Popen([sys.executable, str(ROOT / "tests" / "mock_gitlab.py"), str(gp)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL),
                 subprocess.Popen([sys.executable, str(ROOT / "tests" / "mock_jira.py"), str(jp)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)]
        try:
            wait(gp)
            wait(jp)
            with tempfile.TemporaryDirectory() as tmp:
                cfg = Path(tmp, "config.json")
                cfg.write_text(json.dumps({
                    "gitlab_url": "http://127.0.0.1:%d" % gp, "projects": [{"id": 1, "name": "dlp-core"}], "data_dir": str(Path(tmp, "data")),
                    "jira": {"url": "http://127.0.0.1:%d" % jp, "auth": "bearer", "project_keys": ["DLP"]}}))
                env = {k: v for k, v in os.environ.items() if not k.startswith(("TINYOPS_", "GITLAB_TOKEN"))}
                env.update(TINYOPS_HOME=tmp, TINYOPS_GITLAB_TOKEN=gl_token, TINYOPS_JIRA_TOKEN="jtoken")
                env.update(extra_env or {})
                return subprocess.run([sys.executable, str(ROOT / "server.py"), "--preflight", "--config", str(cfg)], env=env,
                                      capture_output=True, text=True, timeout=60)
        finally:
            for p in procs:
                p.terminate()
                p.wait(5)

    def test_all_good(self):
        r = self.run_pf("secret")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("Alles bereit.", r.stdout)
        self.assertIn("Ergebnis:", r.stdout)
        self.assertNotIn("secret", r.stdout.replace("secrets", ""))      # nie ein Secret ausgeben
        self.assertNotIn("jtoken", r.stdout)

    def test_wrong_token_fails_with_hint_and_skips_sync(self):
        r = self.run_pf("falsch")
        self.assertEqual(r.returncode, 1, r.stdout)
        self.assertIn("FAIL", r.stdout)
        self.assertIn("übersprungen", r.stdout)
        self.assertNotIn("falsch", r.stdout)

    def test_missing_secret_is_named(self):
        r = self.run_pf("")
        self.assertEqual(r.returncode, 1)
        self.assertIn("GitLab-Token: fehlt", r.stdout)


if __name__ == "__main__":
    unittest.main()
