"""Spielt den Einrichtungsassistenten komplett gegen Fake-GitLab und Fake-Jira durch (Antworten über stdin)."""
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Wizard(unittest.TestCase):
    def test_full_run(self):
        gp, jp = free_port(), free_port()
        procs = [subprocess.Popen([sys.executable, str(ROOT / "tests" / "mock_gitlab.py"), str(gp)]),
                 subprocess.Popen([sys.executable, str(ROOT / "tests" / "mock_jira.py"), str(jp)])]
        try:
            with tempfile.TemporaryDirectory() as tmp:
                work = Path(tmp, "app")
                work.mkdir()
                for f in ("setup.py", "server.py", "secretstore.py", "tlog.py", "config.example.json"):
                    shutil.copy(ROOT / f, work / f)
                for d in ("static", "prompts"):
                    shutil.copytree(ROOT / d, work / d)
                time.sleep(0.8)
                answers = [
                    "j",                          # 1 Voraussetzungen: ohne Schlüsselbund fortfahren
                    "http://127.0.0.1:%d" % gp, "",   # 2 URL, CA
                    "secret",                     # Token
                    "dlp", "1", "", "n", "",      # 3 Suche, Auswahl, Name, kein Helm, Ende
                    "", "2", "", "n",             # 4 ich = Vorgabe, Agent = Nr. 2, Muster = Vorgabe, Grenzen nein
                    "j", "http://127.0.0.1:%d" % jp, "", "jtoken", "DLP", "", "", "", "j",   # 5 Jira
                    "",                           # 6 kubectl-Kontext (kubectl fehlt hier)
                    "", "", "",                   # 7 bind, Port, Log-Stufe
                ]
                env = dict(os.environ, TINYOPS_HOME=str(Path(tmp, "home")), PATH="/usr/bin:/bin")
                env.pop("TINYOPS_GITLAB_TOKEN", None)
                r = subprocess.run([sys.executable, "-I", str(work / "setup.py")], input="\n".join(answers) + "\n",
                                   capture_output=True, text=True, cwd=str(work), env=env, timeout=60)
                out = r.stdout + r.stderr
                self.assertEqual(r.returncode, 0, out)
                self.assertIn("Schritt 8/8", out)
                self.assertIn("Alles in Ordnung", out)
                cfg = json.loads((work / "config.json").read_text())
                self.assertEqual(cfg["projects"][0]["id"], 1)
                self.assertEqual(cfg["branch_filter"]["agent_emails"], ["bot@x.ch"])
                self.assertIn("Co-Authored-By: Claude", cfg["branch_filter"]["agent_message_patterns"])
                self.assertEqual(cfg["jira"]["project_keys"], ["DLP"])
                self.assertEqual(cfg["kube_context"], "")
                raw = (work / "config.json").read_text()
                self.assertNotIn("secret", raw.replace("secrets", ""))
                self.assertNotIn("jtoken", raw)
                log = Path(tmp, "home", "logs", "tinyops.log").read_text()
                self.assertNotIn("jtoken", log)
                self.assertIn("Schritt gitlab abgeschlossen", log)
                # --doctor: nichts ändern, Exit 0
                d = subprocess.run([sys.executable, "-I", str(work / "setup.py"), "--doctor"], capture_output=True, text=True,
                                   cwd=str(work), env=env, timeout=60)
                self.assertEqual(d.returncode, 0, d.stdout + d.stderr)
        finally:
            for p in procs:
                p.terminate()
                p.wait()


if __name__ == "__main__":
    unittest.main()
