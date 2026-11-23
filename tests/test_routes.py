"""0.37: Sicherheitsnetz für das Zerlegen des Servers. Hält jede Route mit Statuscode, Inhaltstyp und Form der Antwort fest
(bei JSON die Schlüssel, bei Fehlern den Text). Ändert sich etwas, ist das entweder ein Fehler im Umbau oder gewollt;
dann den Schnappschuss neu schreiben: TINYOPS_ROUTES_WRITE=1 python3 -m unittest test_routes
"""
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
SNAP = Path(__file__).resolve().parent / "routes_snapshot.json"

# (Methode, Pfad, Körper). Aktionen unter einem Präfix mit einer unbekannten Aktion «x», damit nichts passiert.
CALLS = [
    ("GET", "/healthz", None), ("GET", "/", None), ("GET", "/logo/jira", None),
    ("GET", "/manifest.webmanifest", None), ("GET", "/sw.js", None), ("GET", "/pair", None), ("GET", "/icon.svg", None), ("GET", "/icon-192.png", None),
    ("GET", "/api/overview", None), ("GET", "/api/settings", None), ("GET", "/api/audit", None), ("GET", "/api/audit/verify", None),
    ("GET", "/api/audit/export", None), ("GET", "/api/bcs/day?date=2026-11-18", None), ("GET", "/api/focus/brief?key=TINY-999&title=x", None),
    ("GET", "/api/helpdesk/ticket?key=NOPE-1", None), ("GET", "/api/ideas/triage-prompt", None), ("GET", "/api/log?n=5", None),
    ("GET", "/api/m365", None), ("GET", "/api/m365/callback?error=x", None), ("GET", "/api/pair/devices", None), ("GET", "/api/qa", None),
    ("GET", "/api/sonar/report?project_id=1&iid=1", None), ("GET", "/api/time/day?date=2026-11-18", None), ("GET", "/api/update/news", None),
    ("GET", "/api/usage", None), ("GET", "/api/ux/report?days=7", None), ("GET", "/api/workspaces", None), ("GET", "/api/nichts", None),
    ("POST", "/api/groups", {}), ("POST", "/api/helpdesk/seen", {}), ("POST", "/api/ide/close", {}), ("POST", "/api/ide/open", {}),
    ("POST", "/api/ideas", {"text": ""}), ("POST", "/api/links", {}), ("POST", "/api/links/delete", {}), ("POST", "/api/mr/env", {}),
    ("POST", "/api/pair/claim", {"code": "AAAA-AAAA"}), ("POST", "/api/pair/revoke", {"id": 999}), ("POST", "/api/prompt", {}),
    ("POST", "/api/review/export", {}), ("POST", "/api/review/topics", {}), ("POST", "/api/ticket/create", {}), ("POST", "/api/ticket/draft", {}),
    ("POST", "/api/update/seen", {}), ("POST", "/api/usage/push", {}), ("POST", "/api/ux/events", {}), ("POST", "/api/ux/wish", {}),
    ("POST", "/api/agents/x", {}), ("POST", "/api/ai/x", {}), ("POST", "/api/bcs/x", {}), ("POST", "/api/board/x", {}), ("POST", "/api/flow/x", {}),
    ("POST", "/api/focus/x", {}), ("POST", "/api/m365/x", {}), ("POST", "/api/pools/x", {}), ("POST", "/api/qa/x", {}), ("POST", "/api/time/x", {}),
    ("POST", "/api/workspaces/x", {}), ("POST", "/api/nichts", {}),
    ("PATCH", "/api/ideas/999", {"status": "x"}), ("DELETE", "/api/ideas/999", None), ("POST", "/api/ideas/999/assess", {}),
    ("POST", "/api/settings/save", {}), ("POST", "/api/settings/identity", {}), ("POST", "/api/settings/nichts", {}), ("PATCH", "/api/settings", {}),
    ("POST", "/api/settings/test/agent", {}), ("POST", "/api/settings/test/sonar", {}),
    ("GET", "/api/update/check", None), ("POST", "/api/update/run", {}), ("POST", "/api/update/service", {"do": "install"}),      # 0.40
    ("POST", "/api/agents/back", {}), ("POST", "/api/agents/again", {}),
]
# bei diesen Routen hängt die Form an Zeit oder Zufall: nur Status und Typ festhalten
LOOSE = {"/api/overview", "/api/log?n=5", "/api/audit/export", "/api/settings/test/agent"}


def _port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def shape(path, code, ctype, body):
    out = {"status": code, "type": (ctype or "").split(";")[0]}
    if path in LOOSE or not out["type"].endswith("json"):
        return out
    try:
        data = json.loads(body)
    except ValueError:
        return out
    if code >= 400:
        out["error"] = data.get("error") if isinstance(data, dict) else None
    elif isinstance(data, dict):
        out["keys"] = sorted(data)
    else:
        out["kind"] = type(data).__name__
    return out


class Routes(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.d = Path(tempfile.mkdtemp())
        cls.port = _port()
        (cls.d / "config.json").write_text(json.dumps({"data_dir": str(cls.d / "data"), "port": cls.port}))
        env = dict(os.environ, TINYOPS_NO_WATCHDOG="1", TINYOPS_HOME=str(cls.d / "home"))
        cls.srv = subprocess.Popen([sys.executable, str(ROOT / "server.py"), "--demo", "--config", str(cls.d / "config.json")], cwd=ROOT, env=env,
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(100):
            try:
                urllib.request.urlopen("http://127.0.0.1:%d/healthz" % cls.port, timeout=1)
                break
            except OSError:
                time.sleep(0.2)

    @classmethod
    def tearDownClass(cls):
        cls.srv.terminate()
        cls.srv.wait(5)

    def call(self, method, path, body):
        req = urllib.request.Request("http://127.0.0.1:%d%s" % (self.port, path), method=method,
                                     headers={"X-Requested-With": "tinyops", "Content-Type": "application/json"},
                                     data=json.dumps(body).encode() if body is not None else None)
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return r.status, r.headers.get("Content-Type"), r.read()
        except urllib.error.HTTPError as e:
            return e.code, e.headers.get("Content-Type"), e.read()

    def test_all_routes_unchanged(self):
        got = {}
        for method, path, body in CALLS:
            got["%s %s" % (method, path)] = shape(path, *self.call(method, path, body))
        if os.environ.get("TINYOPS_ROUTES_WRITE"):
            SNAP.write_text(json.dumps(got, ensure_ascii=False, indent=1, sort_keys=True) + "\n")
            self.skipTest("Schnappschuss neu geschrieben")
        want = json.loads(SNAP.read_text())
        self.assertEqual(sorted(got), sorted(want))
        for k in want:
            self.assertEqual(got[k], want[k], k)


class Sizes(unittest.TestCase):
    def test_server_stays_small(self):
        """0.37: server.py ist 1'500 Zeilen kürzer (5'301 → unter 3'800); 0.38: unter 1'500 (siehe test_areas). Neues gehört in eigene Module."""
        n = len((ROOT / "server.py").read_text(encoding="utf-8").splitlines())
        self.assertLess(n, 1500, "server.py wächst wieder: %d Zeilen" % n)
        self.assertNotIn("def make_handler(app):\n    cfg", (ROOT / "server.py").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
