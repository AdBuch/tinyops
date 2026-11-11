"""0.28: Microsoft 365 über Graph (Anmeldung, Mail, Kalender, Teams, Fokuszeit eintragen, Termin als Zeit), Review-XP, Agenten-Streaming, Logos."""
import json
import os
import re
import sys
import tempfile
import time
import unittest
import urllib.parse
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import agents  # noqa: E402
import m365  # noqa: E402
import mock_graph  # noqa: E402
import server  # noqa: E402
import settings  # noqa: E402

TENANT, CLIENT = "11111111-2222-3333-4444-555555555555", "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"


def mem_store(initial=""):
    box = {"rt": initial}
    return box, (lambda: box["rt"], lambda v: box.__setitem__("rt", v), lambda: box.__setitem__("rt", ""))


class Graph(unittest.TestCase):
    def setUp(self):
        self.now = time.time()
        self.srv, self.st, self.url = mock_graph.start(self.now)
        self.box, store = mem_store()
        self.conf = dict(m365.DEFAULTS, enabled=True, tenant=TENANT, client_id=CLIENT)
        self.c = m365.Client(self.conf, None, "http://localhost:8765/api/m365/callback", store, login=self.url, graph=self.url + "/v1.0")

    def tearDown(self):
        self.srv.shutdown()

    def login(self):
        u = urllib.parse.urlparse(self.c.auth_url())
        q = dict(urllib.parse.parse_qsl(u.query))
        return self.c.callback("good-code", q["state"]), q

    def test_auth_url_and_callback(self):
        u = urllib.parse.urlparse(self.c.auth_url())
        q = dict(urllib.parse.parse_qsl(u.query))
        self.assertEqual(u.path, "/%s/oauth2/v2.0/authorize" % TENANT)
        self.assertEqual((q["client_id"], q["code_challenge_method"], q["redirect_uri"]), (CLIENT, "S256", "http://localhost:8765/api/m365/callback"))
        self.assertEqual(q["scope"], "offline_access User.Read Mail.Read Calendars.Read Chat.Read")
        with self.assertRaises(m365.GraphError):
            self.c.callback("good-code", "fremder-state")                        # nur Anmeldungen, die dieses tinyops begonnen hat
        with self.assertRaises(m365.GraphError) as cm:
            self.c.callback("bad-code", q["state"])
        self.assertIn("abgelaufen oder widerrufen", str(cm.exception))
        self.assertNotIn("Trace ID", str(cm.exception))
        with self.assertRaises(m365.GraphError):
            self.c.callback("good-code", q["state"])                             # ein state gilt nur einmal
        me, _ = self.login()
        self.assertEqual(me["mail"], "adrian@firma.example")
        self.assertTrue(self.box["rt"].startswith("rt-"))
        tok = [c for c in self.st.calls if c[1].endswith("/token")][-1][2]
        self.assertIn("code_verifier=", tok)
        self.assertNotIn("client_secret", tok)

    def test_fetch_classifies(self):
        self.login()
        r = self.c.fetch(self.now)
        self.assertEqual(r["errors"], {})
        mail = r["mail"]
        self.assertEqual([w["subject"] for w in mail["waiting"]], ["Re: Frage zu DLP-120"])       # beantwortet, Verteiler, no-reply, von mir: nicht
        self.assertEqual(mail["waiting"][0]["key"], "DLP-120")
        self.assertEqual([f["subject"] for f in mail["flagged"]], ["Offerte"])
        cal = r["calendar"]
        subj = [e["subject"] for e in cal["today"] + cal["tomorrow"]]
        self.assertNotIn("Abgesagt", subj)
        self.assertNotIn("Abgelehnt", subj)
        self.assertEqual(cal["next"]["subject"], "Daily")                                       # der eigene Fokus-Termin zählt nicht als nächster Termin
        self.assertIn("Refinement DLP-120", [e["subject"] for e in cal["past_unbooked"]])
        self.assertEqual(r["teams"]["unread_total"], 1)
        self.assertEqual((r["teams"]["unread"][0]["from"], r["teams"]["unread"][0]["preview"]), ("Nico", "Pipeline grün"))

    def test_one_part_failing_keeps_others(self):
        self.login()
        self.st.chats_forbidden = True
        r = self.c.fetch(self.now)
        self.assertIsNone(r["teams"])
        self.assertIn("HTTP 403", r["errors"]["teams"])
        self.assertIsNotNone(r["mail"])
        self.c.conf["mail"] = False
        self.assertIsNone(self.c.fetch(self.now)["mail"])

    def test_refresh_and_expiry(self):
        self.login()
        rt = self.box["rt"]
        self.c.access_exp = 0                                                   # Access-Token abgelaufen: mit dem Refresh-Token neu holen
        self.c.whoami()
        self.c.me = None
        self.c.fetch(self.now)
        self.assertEqual(self.st.refresh_tokens, [rt])
        self.assertNotEqual(self.box["rt"], rt)                                  # das neue Refresh-Token ist gespeichert
        self.c.access_exp = 0
        self.st.refresh_ok = False
        with self.assertRaises(m365.GraphError):
            self.c.token()
        self.assertIn("neu «Anmelden»", self.c.last_error)
        self.c.logout()
        self.assertEqual(self.box["rt"], "")
        self.assertFalse(self.c.has_login())

    def test_device_code(self):
        d = self.c.device_start()
        self.assertEqual(d["user_code"], "ABCD-EFGH")
        self.assertTrue(wait(lambda: (self.c.device_state() or {}).get("state") == "fertig"))
        self.assertTrue(self.c.has_login())

    def test_block_needs_switch(self):
        self.login()
        with self.assertRaises(m365.GraphError):
            self.c.block("Fokus: x", self.now, self.now + 1500)
        self.c.conf["calendar_write"] = True
        self.assertIn("Calendars.ReadWrite", m365.scopes(self.c.conf))
        ev = self.c.block("Fokus: Berufsbildung", self.now, self.now + 1500, "von tinyops")
        self.assertEqual(ev["url"], "https://outlook.example/new")
        made = self.st.events_created[-1]
        self.assertEqual((made["showAs"], made["categories"], made["start"]["timeZone"]), ("busy", ["tinyops"], "UTC"))

    def test_not_ready(self):
        c = m365.Client(dict(m365.DEFAULTS, enabled=True, tenant="x y", client_id="nein"), None, "", mem_store()[1])
        self.assertFalse(c.ready())
        with self.assertRaises(m365.GraphError):
            c.auth_url()


def wait(fn, t=5):
    end = time.time() + t
    while time.time() < end:
        if fn():
            return True
        time.sleep(0.05)
    return False


class AppM365(unittest.TestCase):
    def app(self, demo=True, **m):
        os.environ["TINYOPS_HOME"] = tempfile.mkdtemp()
        c = server.load_config(None)
        c["data_dir"] = tempfile.mkdtemp()
        c["time"] = {"enabled": True}
        if m:
            c["m365"] = dict(m365.DEFAULTS, **m)
        return server.App(c, demo, {}, Path("/nonexistent/c.json"))

    def test_demo_state_book_and_focus_block(self):
        a = self.app()
        ov = a.overview()
        st = ov["m365"]
        self.assertTrue(st["logged_in"] and st["calendar"]["today"])
        past = [e for e in st["calendar"]["past_unbooked"]]
        if past:                                                                 # je nach Tageszeit sind schon Termine vorbei
            r = a.m365_action("book", {"id": past[0]["id"], "key": "dlp-120"})
            self.assertGreater(r["minutes"], 0)
            seg = [x for x in a.timebook.range_segments(past[0]["start"] - 1, past[0]["end"] + 1) if x["source"] == "termin"]
            self.assertEqual((seg[0]["key"], seg[0]["activity"]), ("DLP-120", "Termin"))
            self.assertNotIn(past[0]["id"], [e["id"] for e in a.m365_state()["calendar"]["past_unbooked"]])     # nicht mehr angeboten
            with self.assertRaises(server.UserError):
                a.m365_action("book", {"id": past[0]["id"], "key": "DLP-120"})
        with self.assertRaises(server.UserError):
            a.m365_action("book", {"id": "gibt-es-nicht", "key": "X-1"})
        r = a.focus_action("start", {"area": "bb", "minutes": 25, "calendar": True})
        self.assertTrue(r["calendar"]["ok"])

    def test_real_flow_against_mock(self):
        srv, st, url = mock_graph.start()
        try:
            a = self.app(demo=False, enabled=True, tenant=TENANT, client_id=CLIENT, calendar_write=True)
            box, store = mem_store()
            a.m365.store, a.m365.login, a.m365.graph = store, url, url + "/v1.0"
            self.assertEqual(a.m365_state()["logged_in"], False)
            q = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(a.m365_action("login", {})["url"]).query))
            ok, msg = a.m365_callback({"code": ["good-code"], "state": [q["state"]]})
            self.assertTrue(ok, msg)
            self.assertIn("Adrian Test", msg)
            ok, msg = a.m365_callback({"error": ["access_denied"], "error_description": ["User cancelled"]})
            self.assertFalse(ok)
            self.assertIn("abgebrochen", msg)
            a._m365_fetch(force=True)
            s = a.m365_state()
            self.assertEqual((s["logged_in"], s["mail"]["waiting_total"], s["teams"]["unread_total"]), (True, 1, 1))
            r = a.focus_action("start", {"area": "bb", "minutes": 25, "calendar": True})
            self.assertTrue(r["calendar"]["ok"], r["calendar"])
            self.assertEqual(st.events_created[-1]["subject"], "Fokus: Berufsbildung")
            acts = [x["action"] for x in a.audit_log.rows(limit=20)]
            for want in ("m365.login", "m365.event", "focus.start"):
                self.assertIn(want, acts)
            a.m365_action("logout", {})
            self.assertEqual(box["rt"], "")
            self.assertFalse(a.m365_state()["logged_in"])
        finally:
            srv.shutdown()

    def test_settings_validation(self):
        cur = server.load_config(None)
        cfg, errors = settings.build_config(cur, {"m365": {"enabled": True, "tenant": "nicht gut", "client_id": "123", "reply_days": 99, "calendar": False, "calendar_write": True}})
        self.assertIn("m365.tenant", errors)
        self.assertIn("m365.client_id", errors)
        self.assertIn("m365.reply_days", errors)
        cfg, errors = settings.build_config(cur, {"m365": {"enabled": True, "tenant": "firma.onmicrosoft.com", "client_id": CLIENT, "calendar": False, "calendar_write": True}})
        self.assertEqual(errors, {})
        self.assertFalse(cfg["m365"]["calendar_write"])                          # ohne Kalender kein Eintragen


class ReviewXp(unittest.TestCase):
    def test_approval_gives_xp_once(self):
        os.environ["TINYOPS_HOME"] = tempfile.mkdtemp()
        c = server.load_config(None)
        c["data_dir"] = tempfile.mkdtemp()
        a = server.App(c, True, {}, Path("/nonexistent/c.json"))
        before = a.store.flow_stats()["total_xp"]
        data = {"me": "adrian", "review": [{"project_id": 1, "iid": 41, "title": "Retry", "approved_by": ["Adrian"], "key": "DLP-101"},
                                          {"project_id": 1, "iid": 42, "title": "Andere", "approved_by": ["mara"]}]}
        a._review_xp(data)
        a._review_xp(data)
        st = a.store.flow_stats()
        self.assertEqual(st["total_xp"] - before, server.App.REVIEW_XP)
        self.assertEqual([x["kind"] for x in st["recent"]][:1], ["review"])
        a._review_xp({"me": "", "review": data["review"]})


class Streaming(unittest.TestCase):
    def test_args(self):
        self.assertIn("--output-format stream-json --verbose", agents.remote_cmdline({"kind": "claude"}))
        self.assertNotIn("stream-json", agents.remote_cmdline({"kind": "claude", "extra_args": "--output-format=text"}))
        self.assertIn("--output streaming", agents.remote_cmdline({"kind": "vibe"}))
        self.assertNotIn("streaming", agents.remote_cmdline({"kind": "vibe", "extra_args": "--output json"}))
        self.assertNotIn("stream", agents.remote_cmdline({"kind": "codex"}))
        self.assertIn("PYTHONUNBUFFERED=1", agents.RUNNER)

    def test_render(self):
        ev = [{"type": "system", "subtype": "init", "model": "m"}, {"type": "stream_event", "event": {}},
              {"type": "assistant", "message": {"content": [{"type": "text", "text": "Schaue mir das an."}, {"type": "tool_use", "name": "Bash", "input": {"command": "mvn -q test"}}]}},
              {"type": "user", "message": {"content": [{"type": "tool_result", "content": "BUILD FAILURE\nmehr", "is_error": True}]}},
              {"type": "assistant", "message": {"content": [{"type": "tool_use", "name": "TodoWrite", "input": {"todos": [{"status": "completed"}, {"status": "pending"}]}}]}},
              {"type": "result", "subtype": "success", "num_turns": 3, "duration_ms": 61000, "result": "Fertig."},
              {"role": "assistant", "content": "Ich teste.", "tool_calls": [{"function": {"name": "bash", "arguments": "{\"command\": \"pytest\"}"}}]},
              {"role": "tool", "content": "2 passed"}, {"role": "user", "content": "Prompt"}]
        txt = agents.render_stream("\n".join(json.dumps(e) for e in ev) + "\n{kaputt\n[tinyops-check] Exit 0")
        self.assertEqual(txt.splitlines(), ["● gestartet (m)", "Schaue mir das an.", "▸ Bash: mvn -q test", "  ✗ BUILD FAILURE (+1 Zeilen)",
                                            "▸ TodoWrite: 1 von 2 Punkten erledigt", "■ fertig nach 3 Schritten, 61 s", "Fertig.", "Ich teste.", "▸ bash: pytest",
                                            "  → 2 passed", "{kaputt", "[tinyops-check] Exit 0"])

    def test_vibe_hint(self):
        svc = agents.Service({"agents": [{"id": "v", "name": "v", "kind": "vibe", "connection": "local", "workspace_root": "/w"}], "projects": [{"id": 1, "name": "p", "data_class": "internal"}]},
                             None, Path(tempfile.mkdtemp()), ROOT)
        self.assertIn("--auto-approve", svc.prompt_info("v", "T-1", 1, "", "t", "T-1")["hints"][0])


class Ui(unittest.TestCase):
    def test_static(self):
        html = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
        for needle in ("function m365Rail()", "/api/m365/login", "/api/m365/device", "data-mbook", 'id="fsCal"', "function meetSoon()", "https://admin.mistral.ai/subscription",
                       "LOGO_MISS", 'data-goto="m365"', "data-copyfile", "--auto-approve"):
            self.assertIn(needle, html, needle)
        ids = set(re.findall(r"sect\('([a-z0-9]+)'", html))
        helped = set(re.findall(r"^  ([a-z0-9]+): `", html, re.M))
        self.assertEqual(ids - helped - {"more"}, set())

    def test_logo_route_and_callback_page(self):
        src = (ROOT / "server.py").read_text(encoding="utf-8")
        self.assertIn('path == "/api/m365/callback"', src)
        self.assertIn("html_escape(msg)", src)


if __name__ == "__main__":
    unittest.main()
