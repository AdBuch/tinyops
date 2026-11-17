"""0.36: vor dem Umbau. Wünsche und Bericht vom 17.11.: Lauf weiterführen und Entscheidungen, Rollen/Push/Kontingent der Agenten,
zurückgeschickte Reviews, Helpdesk → Jira, BCS ohne lange Wartezeiten, tinyops als App mit gekoppeltem Handy."""
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

import agents  # noqa: E402
import bcs  # noqa: E402
import briefing  # noqa: E402
import devices  # noqa: E402
import flow  # noqa: E402
import links  # noqa: E402
import settings  # noqa: E402


class Decisions(unittest.TestCase):
    REPORT = ("## Kurz\nRetry eingebaut.\n\n## Offene Entscheidungen\n1. Exponentiell oder fix? Optionen: exponentiell | fix 3×\n"
              "2. Logging-Level für Fehler\n   bei 429?\n\n## Bewusst nicht gemacht\nNichts.\n")

    def test_open_decisions_from_report(self):
        sec = briefing.report_sections(self.REPORT)
        self.assertIn("decide", sec)
        self.assertIn("notdone", sec)            # «Offene Entscheidungen» landet nicht bei «offen»
        od = briefing.open_decisions(sec["decide"])
        self.assertEqual(od[0], {"n": 1, "q": "Exponentiell oder fix?", "options": ["exponentiell", "fix 3×"]})
        self.assertEqual(od[1]["q"], "Logging-Level für Fehler bei 429?")

    def test_followup_carries_text_and_answers(self):
        run = {"id": 7, "agent_name": "Vibe", "summary": self.REPORT, "criteria": [], "checks": [],
               "qa": [{"q": "Neue Tabelle?", "a": "Nein, bestehende", "decision": True}, {"q": "Wo liegt X?", "a": "in core"}]}
        txt = briefing.followup(run, "Bitte noch einen Test\nfür den Timeout.", {"1": "exponentiell", "2": ""})
        self.assertIn("Fortsetzung von Lauf 7", txt)
        self.assertIn("Bitte noch einen Test\nfür den Timeout.", txt)        # Zeilen bleiben
        self.assertIn("1. Exponentiell oder fix? → exponentiell", txt)
        self.assertNotIn("2. Logging", txt)                                   # ohne Antwort nicht erwähnt
        self.assertIn("Neue Tabelle? → Nein, bestehende", txt)               # schon Entschiedenes gilt weiter
        self.assertNotIn("Wo liegt X?", txt)                                  # normale Rückfragen sind keine Entscheidungen

    def test_decisions_in_mr_description(self):
        run = {"id": 1, "ticket": "DLP-1", "title": "Retry", "summary": "## Kurz\nx\n## Entscheidungen\nPolicy als eigene Klasse.\n",
               "qa": [{"q": "Fix oder exponentiell?", "a": "exponentiell", "decision": True}], "criteria": [], "checks": [], "result": {}}
        md = briefing.mr_description(run)
        self.assertIn("## Entscheidungen", md)
        self.assertIn("Fix oder exponentiell? → **exponentiell**", md)
        self.assertIn("Policy als eigene Klasse.", md)

    def test_ask_marks_decision(self):
        q = agents.parse_question('{"id": 2, "question": "A oder B?", "options": ["A", "B"], "blocking": true, "decision": true}')
        self.assertTrue(q["decision"])
        self.assertFalse(agents.parse_question('{"id": 1, "question": "x"}')["decision"])
        self.assertIn("-d) dec=true", agents.HELPERS["tinyops-ask"])


class Roles(unittest.TestCase):
    def test_parse_roles(self):
        self.assertEqual(agents.parse_roles("plan=/planner, develop"), ({"plan": "/planner", "develop": "/developer"}, ""))
        self.assertEqual(agents.parse_roles({"reviewer": "/rev"})[0], {"review": "/rev"})
        self.assertTrue(agents.parse_roles("plan=planner")[1])                 # ohne Schrägstrich
        self.assertTrue(agents.parse_roles("deploy=/x")[1])
        self.assertEqual(agents.agent_roles({"roles": {"plan": "/p"}}), ["plan"])
        self.assertEqual(agents.agent_roles({}), list(agents.ROLE_PHASES))

    def test_clean_agents_keeps_roles_push_quota(self):
        err = {}
        out = agents.clean_agents([{"name": "vibe1", "kind": "vibe", "connection": "local", "workspace_root": "~/w", "roles": "plan=/planner",
                                    "push": True}, {"name": "c", "kind": "claude", "connection": "local", "workspace_root": "~/w", "quota": "none"}],
                                  set(), [], err)
        self.assertEqual(err, {})
        self.assertEqual(out[0]["roles"], {"plan": "/planner"})
        self.assertTrue(out[0]["push"])
        self.assertEqual(out[0]["quota"], "mistral")                          # Vibe verbraucht Mistral
        self.assertEqual(out[1]["quota"], "")
        self.assertNotIn("push", out[1])

    def test_prompt_with_role_and_push(self):
        d = Path(tempfile.mkdtemp())
        svc = agents.Service.__new__(agents.Service)
        svc.base, svc.cfg = ROOT, {}
        p = svc.default_prompt("Retry", "DLP-1", "core", "main", mode="worktree", template="agent-task",
                               agent={"roles": {"develop": "/developer"}, "push": True})
        self.assertTrue(p.startswith("/developer\n\n# Umsetzen"))
        self.assertIn("git push -u origin HEAD", p)
        self.assertIn("am Ende pushst du diesen Branch", p)
        self.assertNotIn("kein Push,", p)
        q = svc.default_prompt("Retry", "DLP-1", "core", "main", mode="worktree", template="agent-plan", agent={"roles": {"develop": "/developer"}})
        self.assertFalse(q.startswith("/"))                                   # Planen hat hier keine Rolle
        r = svc.default_prompt("Retry", "DLP-1", "core", "main", mode="worktree", template="agent-task", agent={})
        self.assertIn("Kein Merge, kein Push, kein Force-Push", r)
        self.assertIn("den Branch pusht der Mensch", r)
        del d


class ReviewsSentBack(unittest.TestCase):
    def item(self, **kw):
        return dict({"kind": "review", "title": "MR", "author": "kollege", "age_days": 2, "url": "u", "project_id": 1, "branch": "b"}, **kw)

    def test_waiting_when_sent_back_or_draft(self):
        for kw, waiting, text in (({"my_review": "requested_changes"}, True, "Änderungen angefordert"),
                                  ({"my_review": "reviewed"}, True, "kommentiert"),
                                  ({"my_review": "approved"}, True, "freigegeben"),
                                  ({"draft": True}, True, "Entwurf"),
                                  ({"my_review": "unreviewed"}, False, "Wartet auf dein Review"),
                                  ({"merge_status": "requested_changes"}, False, "Jemand hat")):
            v = flow.review_view({"review": [self.item(**kw)]})[0]
            self.assertEqual(v["waiting"], waiting, kw)
            self.assertIn(text, v["status"])
            self.assertEqual(v["next"]["kind"], "wait" if waiting else "do")
            if waiting:
                self.assertEqual(v["next"]["owner"], "other")


class BcsPause(unittest.TestCase):
    def test_unreachable_answers_fast_after_first_failure(self):
        s = socket.socket()
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
        s.close()                                  # niemand hört zu: sofort «connection refused»
        c = bcs.Client("http://127.0.0.1:%d" % port)
        with self.assertRaises(bcs.BcsError) as e1:
            c.day("2026-11-17")
        self.assertIn("nicht erreichbar", str(e1.exception))
        t0 = time.time()
        with self.assertRaises(bcs.BcsError) as e2:
            c.overview("2026-11-17")
        self.assertLess(time.time() - t0, 0.05)
        self.assertIn("nächster Versuch in", str(e2.exception))
        c.down = (time.time() - bcs.PAUSE_AFTER_FAIL - 1, "alt")
        with self.assertRaises(bcs.BcsError) as e3:              # nach der Pause wird wieder echt gefragt
            c.day("2026-11-17")
        self.assertNotIn("nächster Versuch", str(e3.exception))

    def test_reads_have_short_timeout(self):
        self.assertLessEqual(bcs.READ_TIMEOUT, 10)


class Pairing(unittest.TestCase):
    def setUp(self):
        self.now = [1000.0]
        self.store = links.Store(Path(tempfile.mkdtemp()) / "t.db")
        self.dev = devices.Devices(self.store, now=lambda: self.now[0])

    def test_code_claim_check_revoke(self):
        c = self.dev.new_code()
        self.assertRegex(c["code"], r"^[A-Z2-9]{4}-[A-Z2-9]{4}$")
        val, d = self.dev.claim(c["code"].lower(), "Mein Handy")
        self.assertEqual(d["name"], "Mein Handy")
        with self.assertRaises(devices.DeviceError):
            self.dev.claim(c["code"], "x")                                   # nur einmal
        got = self.dev.check("a=b; tinyops_dev=%s" % val)
        self.assertEqual(got["id"], d["id"])
        self.assertNotIn(val.split(".", 1)[1], json.dumps(self.store.device_list()))     # nur der Hash liegt in der Datenbank
        self.assertIsNone(self.dev.check("tinyops_dev=%s" % val[:-2] + "xx"))
        self.dev.revoke(d["id"])
        self.assertIsNone(self.dev.check("tinyops_dev=%s" % val))

    def test_wrong_codes_burn_open_codes_and_expiry(self):
        c = self.dev.new_code()
        for _ in range(devices.CODE_TRIES):
            with self.assertRaises(devices.DeviceError):
                self.dev.claim("ZZZZ-ZZZZ", "")
        with self.assertRaises(devices.DeviceError):
            self.dev.claim(c["code"], "")                                    # nach 5 Fehlversuchen verbrannt
        c2 = self.dev.new_code()
        self.now[0] += devices.CODE_TTL + 1
        with self.assertRaises(devices.DeviceError):
            self.dev.claim(c2["code"], "")

    def test_remote_detection_and_phone_url(self):
        self.assertFalse(devices.is_remote("127.0.0.1", "127.0.0.1:8765", {}))
        self.assertFalse(devices.is_remote("127.0.0.1", "localhost", {}))
        self.assertTrue(devices.is_remote("127.0.0.1", "laptop.tail.ts.net", {}))           # Proxy auf diesem Rechner
        self.assertTrue(devices.is_remote("127.0.0.1", "localhost:8765", {"X-Forwarded-For": "100.64.0.2"}))
        self.assertTrue(devices.is_remote("10.0.0.5", "localhost", {}))
        self.assertEqual(devices.phone_url("https://Laptop.tail.ts.net/")[:2], ("https://laptop.tail.ts.net", "laptop.tail.ts.net"))
        self.assertTrue(devices.phone_url("https://8.8.8.8")[2])
        self.assertTrue(devices.phone_url("http://localhost:8765")[2])
        self.assertTrue(devices.phone_url("https://x.example/pfad")[2])
        cfg, err = settings.build_config({}, {"app": {"phone_url": "ftp://x"}})
        self.assertIn("app.phone_url", err)
        cfg, err = settings.build_config({}, {"app": {"phone_url": "https://laptop.tail.ts.net"}})
        self.assertEqual(cfg["app"]["phone_url"], "https://laptop.tail.ts.net")


def _port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class ServerFlow(unittest.TestCase):
    """Echter Server (Demo): App-Hülle öffentlich, Panel von aussen nur mit gekoppeltem Gerät, Helpdesk → Jira, Ziel der Fokus-Aufgabe."""

    @classmethod
    def setUpClass(cls):
        cls.d = Path(tempfile.mkdtemp())
        cls.port = _port()
        (cls.d / "config.json").write_text(json.dumps({"data_dir": str(cls.d / "data"), "port": cls.port, "app": {"phone_url": "https://laptop.tail.ts.net"}}))
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

    def call(self, method, path, body=None, headers=None):
        h = {"X-Requested-With": "tinyops", "Content-Type": "application/json"}
        h.update(headers or {})
        req = urllib.request.Request("http://127.0.0.1:%d%s" % (self.port, path), method=method, headers=h,
                                     data=json.dumps(body).encode() if body is not None else None)
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                return r.status, r.read(), dict(r.headers)
        except urllib.error.HTTPError as e:
            return e.code, e.read(), dict(e.headers)

    def test_app_shell_public(self):
        remote = {"Host": "laptop.tail.ts.net"}
        code, body, h = self.call("GET", "/manifest.webmanifest", headers=remote)
        self.assertEqual(code, 200)
        self.assertEqual(json.loads(body)["display"], "standalone")
        code, body, h = self.call("GET", "/sw.js", headers=remote)
        self.assertEqual(code, 200)
        self.assertIn("/api/", body.decode())                  # Daten nie im Cache
        code, body, h = self.call("GET", "/icon-192.png", headers=remote)
        self.assertEqual((code, body[:4]), (200, b"\x89PNG"))
        code, body, h = self.call("GET", "/pair", headers=remote)
        self.assertIn("Code", body.decode())

    def test_remote_needs_paired_device(self):
        remote = {"Host": "laptop.tail.ts.net"}
        self.assertEqual(self.call("GET", "/api/overview", headers=remote)[0], 401)
        code, body, _ = self.call("GET", "/", headers=remote)
        self.assertEqual(code, 401)
        self.assertIn("Noch nicht gekoppelt", body.decode())
        self.assertEqual(self.call("GET", "/api/overview", headers={"Host": "fremd.example"})[0], 403)
        self.assertEqual(self.call("POST", "/api/pair/start", {}, headers=remote)[0], 401)
        code, body, _ = self.call("POST", "/api/pair/start", {})
        self.assertEqual(code, 200)
        c = json.loads(body)
        self.assertEqual(c["phone_url"], "https://laptop.tail.ts.net")
        code, body, h = self.call("POST", "/api/pair/claim", {"code": c["code"], "name": "Handy"}, headers=remote)
        self.assertEqual(code, 200, body)
        ck = h["Set-Cookie"]
        self.assertIn("HttpOnly", ck)
        self.assertIn("Secure", ck)                          # Adresse mit https
        dev = {"Host": "laptop.tail.ts.net", "Cookie": ck.split(";")[0]}
        self.assertEqual(self.call("GET", "/api/overview", headers=dev)[0], 200)
        self.assertEqual(self.call("POST", "/api/pair/start", {}, headers=dev)[0], 403)
        self.assertEqual(self.call("POST", "/api/settings/save", {}, headers=dev)[0], 403)
        devs = json.loads(self.call("GET", "/api/pair/devices")[1])["devices"]
        self.assertEqual([x["name"] for x in devs], ["Handy"])
        self.call("POST", "/api/pair/revoke", {"id": devs[0]["id"]})
        self.assertEqual(self.call("GET", "/api/overview", headers=dev)[0], 401)

    def test_helpdesk_draft_and_focus_brief(self):
        ov = json.loads(self.call("GET", "/api/overview")[1])
        hk = ((ov.get("flow") or {}).get("hd_queue") or [{}])[0].get("key")
        if hk:
            code, body, _ = self.call("POST", "/api/ticket/draft", {"hd_key": hk})
            self.assertEqual(code, 200, body)
            d = json.loads(body)
            self.assertEqual(d["source"], "helpdesk")
            self.assertIn(hk, d["draft"]["summary"])
            self.assertIn("Aus Helpdesk-Ticket [%s|" % hk, d["draft"]["description"])
            self.assertIn("Kundendaten", d["warning"])
        code, body, _ = self.call("GET", "/api/focus/brief?key=TINY-999&title=x")
        self.assertEqual(code, 200)
        self.assertIn("criteria", json.loads(body))


if __name__ == "__main__":
    unittest.main()
