"""0.42: Testen von Hand (Prüfliste je Ticket, Jetzt testen, Fehler zurück ans Entwickeln, Abnahme) und Rückmeldungen aus dem Bericht."""
import json
import os
import socket
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("TINYOPS_HOME", tempfile.mkdtemp())
import bcs  # noqa: E402
import flow  # noqa: E402
import routes  # noqa: E402
import server  # noqa: E402
import ui  # noqa: E402


def app_with_run():
    c = server.load_config(None)
    c.update(data_dir=tempfile.mkdtemp(), projects=[{"id": 1, "name": "dlp-core"}])
    app = server.App(c, False, {}, Path("/nonexistent/c.json"), watchdog=False)
    st = app.store
    rid = st.agent_run_add("a1", "DLP-7", 1, "feature/DLP-7", "Export")
    st.agent_run_update(rid, status="fertig", started=time.time() - 60, finished=time.time(), mode="worktree", out_branch="agent/dlp-7-1",
                        criteria=json.dumps([{"n": 1, "text": "Export als CSV"}, {"n": 2, "text": "Leere Liste zeigt Hinweis"}]),
                        msteps=json.dumps([{"step": "Liste leeren", "expect": "Hinweis sichtbar"}]))
    return app, rid


class Checklist(unittest.TestCase):
    def setUp(self):
        self.app, self.rid = app_with_run()

    def items(self):
        return self.app.test_action("list", {"key": "DLP-7"})["items"]

    def test_sources(self):
        lst = self.app.test_action("list", {"key": "DLP-7"})
        self.assertEqual([(i["source"], i["text"]) for i in lst["items"]],
                         [("Kriterium", "Export als CSV"), ("Kriterium", "Leere Liste zeigt Hinweis"), ("Entwickler", "Liste leeren → Hinweis sichtbar"),
                          ("tinyops", "Aus Sicht eines Nutzers ist das Ticket-Ziel erreicht")])
        self.assertEqual((lst["open"], lst["dev_run"], lst["target"]), (4, self.rid, {"run": self.rid}))

    def test_without_agent_the_ticket_criteria_count(self):
        self.app.ticket_brief = lambda key, title="": {"criteria": ["Login mit 2FA", "Fehlermeldung bei falschem Code"]}
        lst = self.app.test_list("DLP-9")
        self.assertEqual([i["text"] for i in lst["items"]][:2], ["Login mit 2FA", "Fehlermeldung bei falschem Code"])
        self.assertEqual((lst["dev_run"], lst["target"]), (None, {}))
        with self.assertRaises(server.UserError):
            self.app.test_action("start", {"key": "DLP-9"})

    def test_check_fail_needs_a_note_and_state_survives(self):
        i = self.items()[0]
        with self.assertRaises(server.UserError):
            self.app.test_action("check", {"key": "DLP-7", "id": i["id"], "state": "fail"})
        out = self.app.test_action("check", {"key": "DLP-7", "id": i["id"], "state": "fail", "note": "Umlaute kaputt"})
        self.assertEqual((out["fail"], out["items"][0]["note"]), (1, "Umlaute kaputt"))
        self.app.test_action("check", {"key": "DLP-7", "id": self.items()[1]["id"], "state": "ok"})
        self.assertEqual([x["state"] for x in self.items()][:2], ["fail", "ok"])
        with self.assertRaises(server.UserError):
            self.app.test_action("check", {"key": "DLP-7", "id": "gibtsnicht", "state": "ok"})
        with self.assertRaises(server.UserError):
            self.app.test_action("check", {"key": "DLP-7", "id": i["id"], "state": "vielleicht"})

    def test_own_items(self):
        out = self.app.test_action("add", {"key": "DLP-7", "text": "Export mit 10'000 Zeilen"})
        own = [x for x in out["items"] if x.get("own")]
        self.assertEqual([x["text"] for x in own], ["Export mit 10'000 Zeilen"])
        self.app.test_action("remove", {"key": "DLP-7", "id": self.items()[0]["id"]})      # vorgeschlagene bleiben
        self.assertEqual(len(self.items()), 5)
        out = self.app.test_action("remove", {"key": "DLP-7", "id": own[0]["id"]})
        self.assertEqual(len(out["items"]), 4)

    def test_back_sends_failures_to_the_developer(self):
        sent = []
        self.app._agent_back = lambda svc, b: (sent.append(b), {"id": 99, "dev": b["run"], "session": True})[1]
        with self.assertRaises(server.UserError):
            self.app.test_action("back", {"key": "DLP-7"})                       # nichts als Fehler markiert
        i = self.items()[0]
        self.app.test_action("check", {"key": "DLP-7", "id": i["id"], "state": "fail", "note": "Umlaute kaputt"})
        out = self.app.test_action("back", {"key": "DLP-7", "note": "mit Excel geöffnet"})
        self.assertEqual((out["sent"], sent[0]["run"]), (1, self.rid))
        self.assertIn("- Export als CSV: Umlaute kaputt", sent[0]["note"])
        self.assertIn("Dazu: mit Excel geöffnet", sent[0]["note"])
        again = self.items()[0]
        self.assertEqual(again["state"], "", "nach dem Nachbessern wieder offen")
        self.assertIn("zurück an Lauf 99", again["note"])
        self.assertTrue(any(r["action"] == "test.back" for r in self.app.audit_log.export()))

    def test_done_needs_all_checked_or_force(self):
        got = []
        self.app._flow_accept = lambda b: (got.append(b), {"stage": "tested"})[1]
        ids = [x["id"] for x in self.items()]
        self.app.test_action("check", {"key": "DLP-7", "id": ids[0], "state": "fail", "note": "kaputt"})
        with self.assertRaises(server.UserError):
            self.app.test_action("done", {"key": "DLP-7", "force": True})       # Fehler blockiert immer
        self.app.test_action("check", {"key": "DLP-7", "id": ids[0], "state": "ok"})
        with self.assertRaises(server.UserError) as e:
            self.app.test_action("done", {"key": "DLP-7"})
        self.assertIn("noch offen", str(e.exception))
        self.app.test_action("done", {"key": "DLP-7", "force": True})
        self.assertEqual(got[0]["note"], "Prüfliste: 1 ok, 3 offen")
        for i in ids[1:]:
            self.app.test_action("check", {"key": "DLP-7", "id": i, "state": "ok"})
        self.app.test_action("done", {"key": "DLP-7"})
        self.assertEqual(got[1]["note"], "Prüfliste: 4 ok")

    def test_start_on_a_run_reports_each_step(self):
        out = self.app.test_action("start", {"key": "DLP-7"})
        self.assertEqual(out["steps"][0]["step"], "Worktree und IntelliJ")
        self.assertFalse(out["steps"][0]["ok"])                               # Agent a1 gibt es hier nicht: Meldung statt Absturz
        self.assertTrue(out["steps"][0]["msg"])

    def test_start_is_not_allowed_from_a_paired_device(self):
        self.assertIn('"/api/test/start"', (ROOT / "routes.py").read_text(encoding="utf-8"))

    def test_route(self):
        self.assertTrue(any(m == "POST" and p == "/api/test/" for m, p, _ in routes.PREFIX))


class Feedback(unittest.TestCase):
    def test_merge_step_says_where_merging_happens(self):
        src = (ROOT / "flow.py").read_text(encoding="utf-8")
        self.assertIn("In GitLab mergen", src)

    def test_bcs_pause_grows(self):
        s = socket.socket()
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
        s.close()
        c = bcs.Client("http://127.0.0.1:%d" % port)
        pauses = []
        for _ in range(6):
            c.down = (0, "x") if c.down else None                 # Pause abgelaufen: wieder echt fragen
            with self.assertRaises(bcs.BcsError):
                c.day("2026-11-23")
            with self.assertRaises(bcs.BcsError) as e:
                c.day("2026-11-23")
            pauses.append(int(str(e.exception).rsplit("in ", 1)[1].split()[0]))
        self.assertIn(pauses[0], (bcs.PAUSE_AFTER_FAIL, bcs.PAUSE_AFTER_FAIL + 1))
        self.assertTrue(all(a <= b for a, b in zip(pauses, pauses[1:])))
        self.assertLessEqual(pauses[-1], bcs.PAUSE_MAX + 1)
        self.assertGreater(pauses[-1], bcs.PAUSE_AFTER_FAIL * 4)

    def test_ui_has_test_section(self):
        js = ui.source(ROOT)
        for s in ("/api/test/list", "/api/test/start", "data-tcback", "data-tcdone", "tcDraw"):
            self.assertIn(s, js)


# ------------------------------------------------------------ Reviews in GitLab (E14)
class FakeGitLab:
    """Nimmt alles an und merkt sich jede Anfrage; kennt Versionen, einen Diff und Entwürfe."""
    DIFF = "@@ -10,4 +10,5 @@ class Foo\n ctx1\n-alt\n+neu1\n+neu2\n ctx2\n"

    def __init__(self):
        import threading
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
        fake = self
        self.calls, self.drafts, self.next_id = [], {500: {"id": 500, "note": "Entwurf von dir, von Hand"}}, 600

        class H(BaseHTTPRequestHandler):
            def _send(self, code, obj):
                b = json.dumps(obj).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(b)))
                self.end_headers()
                self.wfile.write(b)

            def _do(self, method):
                n = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(n) or b"null") if n else None
                path = self.path.split("?")[0].replace("/api/v4", "")
                fake.calls.append((method, path, body, self.headers.get("PRIVATE-TOKEN")))
                base = "/projects/1/merge_requests/9"
                if method == "GET" and path == base + "/versions":
                    return self._send(200, [{"id": 3, "head_commit_sha": "c" * 40, "base_commit_sha": "a" * 40, "start_commit_sha": "b" * 40},
                                            {"id": 2, "head_commit_sha": "fedcba0987654321" + "0" * 24, "base_commit_sha": "a" * 40, "start_commit_sha": "b" * 40}])
                if method == "GET" and path.startswith(base + "/versions/"):
                    vid = int(path.rsplit("/", 1)[1])
                    return self._send(200, {"id": vid, "head_commit_sha": ("c" * 40) if vid == 3 else "fedcba0987654321" + "0" * 24, "base_commit_sha": "a" * 40,
                                            "start_commit_sha": "b" * 40, "diffs": [{"old_path": "src/Foo.java", "new_path": "src/Foo.java", "diff": FakeGitLab.DIFF}]})
                if method == "GET" and path == base + "/draft_notes":
                    return self._send(200, list(fake.drafts.values()))
                if method == "POST" and path == base + "/draft_notes":
                    fake.next_id += 1
                    fake.drafts[fake.next_id] = dict(body, id=fake.next_id)
                    return self._send(201, fake.drafts[fake.next_id])
                if method == "DELETE" and path.startswith(base + "/draft_notes/"):
                    fake.drafts.pop(int(path.rsplit("/", 1)[1]), None)
                    return self._send(204, {})
                return self._send(404, {"message": "404"})

            def do_GET(self):
                self._do("GET")

            def do_POST(self):
                self._do("POST")

            def do_DELETE(self):
                self._do("DELETE")

            def do_PUT(self):
                self._do("PUT")

            def log_message(self, *a):
                pass
        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.url = "http://127.0.0.1:%d" % self.srv.server_address[1]
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()


FINDINGS = [{"path": "src/Foo.java", "line": 12, "text": "neu1 prüft null nicht", "severity": "hoch"},          # hinzugefügte Zeile
            {"path": "src/Foo.java", "line": 10, "text": "Name sagt wenig", "severity": "klein"},              # Kontextzeile: old_line nötig
            {"path": "src/Foo.java", "line": 80, "text": "ausserhalb", "severity": "mittel"},                 # nicht im Diff
            {"path": "README.md", "line": 0, "text": "Doku fehlt", "severity": "mittel"}]                     # Datei nicht im Diff


class Drafts(unittest.TestCase):
    def setUp(self):
        import gitlab_review
        self.gr = gitlab_review
        self.gl = FakeGitLab()
        self.addCleanup(self.gl.srv.shutdown)
        c = server.load_config(None)
        c.update(data_dir=tempfile.mkdtemp(), projects=[{"id": 1, "name": "dlp-core"}])
        c["gitlab"] = {"url": self.gl.url}
        c["gitlab_url"] = self.gl.url
        self.app = server.App(c, False, {}, Path("/nonexistent/c.json"), watchdog=False)
        self.app.cfg["gitlab_url"] = self.gl.url
        st = self.app.store
        self.rid = st.agent_run_add("a1", "1:feature-c", 1, "feature-c", "!9 Kollege C")
        st.agent_run_update(self.rid, status="fertig", phase="review", started=time.time() - 9, finished=time.time(),
                            mr=json.dumps({"host": "gitlab", "project_id": 1, "iid": 9, "sha": "fedcba0987654321", "target": "main", "url": self.gl.url + "/mr/9"}),
                            findings=json.dumps(FINDINGS))
        os.environ["TINYOPS_GITLAB_REVIEW_TOKEN"] = "glpat-review-geheim"
        self.addCleanup(os.environ.pop, "TINYOPS_GITLAB_REVIEW_TOKEN", None)

    def test_whitelist(self):
        ok = [("POST", "/projects/1/merge_requests/9/draft_notes"), ("DELETE", "/projects/1/merge_requests/9/draft_notes/7"),
              ("GET", "/projects/1/merge_requests/9/versions/3")]
        bad = [("POST", "/projects/1/merge_requests/9/draft_notes/bulk_publish"), ("POST", "/projects/1/merge_requests/9/draft_notes/7/publish"),
               ("PUT", "/projects/1/merge_requests/9/draft_notes/7/publish"), ("POST", "/projects/1/merge_requests/9/approve"),
               ("PUT", "/projects/1/merge_requests/9/merge"), ("POST", "/projects/1/merge_requests/9/notes"), ("POST", "/projects/1/merge_requests/9/discussions"),
               ("PUT", "/projects/1/merge_requests/9/discussions/abc"), ("DELETE", "/projects/1/merge_requests/9"), ("GET", "/user")]
        for m, p in ok:
            self.assertTrue(self.gr.allowed(m, p), (m, p))
        for m, p in bad:
            self.assertFalse(self.gr.allowed(m, p), (m, p))
        d = self.gr.Drafts(self.gl.url, "t", None)
        with self.assertRaises(server.UserError):
            d._req("POST", "/projects/1/merge_requests/9/draft_notes/bulk_publish")
        self.assertEqual(self.gl.calls, [], "abgelehnt, bevor etwas rausgeht")

    def test_plan_positions(self):
        v = {"base_commit_sha": "a", "start_commit_sha": "b", "head_commit_sha": "c",
             "diffs": [{"old_path": "src/Foo.java", "new_path": "src/Foo.java", "diff": FakeGitLab.DIFF}]}
        self.assertEqual(self.gr.diff_lines(FakeGitLab.DIFF), {10: 10, 11: None, 12: None, 13: 12})
        p = self.gr.plan(FINDINGS, v)
        self.assertEqual(p[0]["position"]["new_line"], 12)
        self.assertNotIn("old_line", p[0]["position"])
        self.assertEqual((p[1]["position"]["new_line"], p[1]["position"]["old_line"]), (10, 10))
        self.assertIsNone(p[2]["position"])
        self.assertIn("`src/Foo.java:80`", p[2]["note"])
        self.assertIn("`README.md`", p[3]["note"])
        self.assertTrue(all(x["note"].endswith(self.gr.MARK) for x in p))
        self.assertTrue(p[0]["note"].startswith("**Wichtig:**"))

    def test_drafts_created_replaced_never_published(self):
        out = self.app.review_drafts({"run": self.rid})
        self.assertEqual((out["created"], out["positioned"], out["general"], out["replaced"]), (4, 2, 2, 0))
        self.assertTrue(out["old"], "lief auf Version 2, MR ist inzwischen auf Version 3")
        posted = [b for m, p, b, _ in self.gl.calls if m == "POST"]
        self.assertEqual(posted[0]["position"]["head_sha"], "fedcba0987654321" + "0" * 24, "Position auf der Version, die geprüft wurde")
        self.assertIn("geprüft auf fedcba09", posted[0]["note"])
        out2 = self.app.review_drafts({"run": self.rid, "only": [0]})
        self.assertEqual((out2["created"], out2["replaced"]), (1, 4))
        self.assertIn(500, self.gl.drafts, "fremder (eigener, von Hand) Entwurf bleibt")
        self.assertEqual(len(self.gl.drafts), 2)
        for m, p, _, tok in self.gl.calls:
            self.assertTrue(self.gr.allowed(m, p), (m, p))
            self.assertEqual(tok, "glpat-review-geheim")
            self.assertNotIn("publish", p)
        self.assertTrue(any(r["action"] == "review.drafts" for r in self.app.audit_log.export()))

    def test_without_token_copy(self):
        os.environ.pop("TINYOPS_GITLAB_REVIEW_TOKEN")
        with self.assertRaises(server.UserError) as e:
            self.app.review_drafts({"run": self.rid})
        self.assertIn("Kopieren", str(e.exception))
        self.assertEqual(self.gl.calls, [])
        t = self.app.review_copy({"run": self.rid})
        self.assertEqual(t["count"], 4)
        self.assertTrue(t["text"].startswith("- **hoch** `src/Foo.java:12`"))

    def test_agent_never_gets_the_token(self):
        import agents
        src = (ROOT / "agents.py").read_text(encoding="utf-8")
        self.assertIn('spec["unset"]', src)
        self.assertIn("TINYOPS_GITLAB_REVIEW_TOKEN", {"TINYOPS_" + n.upper() for n in agents.store.NAMES})
        self.assertIn('spec.get("unset")', (ROOT / "agentwrap.py").read_text(encoding="utf-8"))

    def test_finding_helper_and_parse(self):
        import subprocess
        import agent_rules
        import agent_scripts
        d = Path(tempfile.mkdtemp())
        sh = d / "tinyops-finding"
        sh.write_text(agent_scripts.HELPERS["tinyops-finding"])
        env = dict(os.environ, TINYOPS_RUN_DIR=str(d), TINYOPS_RUN_ID="5")
        for args in (["src/Foo.java", "12", 'sagt "nichts"', "hoch"], ["README.md", "-", "Doku"], ["x", "zwölf", "y"]):
            subprocess.run(["sh", str(sh)] + args, env=env, capture_output=True)
        got = agent_rules.parse_findings((d / "5.findings").read_text() + '{"path": "../etc/passwd", "line": 1, "text": "x"}\n')
        self.assertEqual([(f["path"], f["line"], f["severity"]) for f in got], [("src/Foo.java", 12, "hoch"), ("README.md", 0, "mittel")])
        self.assertEqual(got[0]["text"], 'sagt "nichts"')


class ReviewStart(unittest.TestCase):
    """0.42.1: Agent wählen, Ticket und Ziel gehen mit an den Reviewer (Rückmeldung vom 24.11.)."""
    def setUp(self):
        import briefing
        d = Path(tempfile.mkdtemp())
        c = server.load_config(None)
        c.update(data_dir=str(d / "data"), projects=[{"id": 1, "name": "dlp-core", "data_class": "restricted"}], connections=[],
                 agents=[{"id": "cloud", "name": "Claude", "kind": "claude", "connection": "local", "workspace_root": str(d / "ws"), "roles": {"review": "/reviewer"}},
                         {"id": "lokal", "name": "Qwen", "kind": "goose", "model": "qwen3", "cloud": False, "connection": "local", "workspace_root": str(d / "ws")},
                         {"id": "shared", "name": "Alt", "kind": "goose", "model": "qwen3", "cloud": False, "connection": "local", "workspace_root": str(d / "ws"),
                          "isolation": "shared"}])
        self.app = app = server.App(c, False, {}, d / "config.json", watchdog=False)
        mr = {"host": "gitlab", "project_id": 1, "iid": 9, "branch": "feature/DLP-7-export", "title": "Export als CSV", "sha": "c0ffee1234567890",
              "keys": ["DLP-7"], "url": "https://gitlab.example/mr/9"}
        app._find_mr = lambda host, pid, iid: mr if (pid, iid) == (1, 9) else None
        app.client = type("C", (), {"mr_detail": lambda self, pid, iid: {"description": "Siehe auch DLP-8. Token: glpat-abcdefghijklmnopqrstu", "target_branch": "develop"}})()
        self.briefs = {"DLP-7": briefing.make("jira", "DLP-7", "CSV-Export", "Story", "In Arbeit", "Nutzer exportieren Listen.\n\nh3. Akzeptanzkriterien\n* Umlaute stimmen\n* Leere Liste zeigt Hinweis", [])}
        app.ticket_brief = lambda key, title="": self.briefs.get(key) or briefing.empty("jira", key, "Ticket nicht lesbar: 404")
        self.started = []
        app.agents.start = lambda rid, prompt, pid=None, branch=None, phase="develop", **k: self.started.append((rid, prompt, phase))
        self.ref = {"host": "gitlab", "project_id": 1, "iid": 9}

    def test_options_list_agents_with_reason_and_ticket(self):
        o = self.app.review_options(self.ref)
        self.assertEqual([(a["id"], a["ok"]) for a in o["agents"]], [("lokal", True), ("cloud", False), ("shared", False)])
        self.assertIn("restricted", o["agents"][1]["why"])
        self.assertIn("Worktree", o["agents"][2]["why"])
        self.assertEqual(o["keys"], ["DLP-7", "DLP-8"])
        self.assertEqual((o["ticket"]["key"], o["ticket"]["criteria"], o["target"]), ("DLP-7", 2, "develop"))
        self.assertEqual(self.app.review_options(dict(self.ref, ticket=""))["ticket"], None)
        self.assertTrue(self.app.review_options(dict(self.ref, ticket="DLP-99"))["ticket"]["error"])
        with self.assertRaises(server.UserError):
            self.app.review_options(dict(self.ref, ticket="kein key"))

    def test_start_with_chosen_agent_ticket_and_goal(self):
        with self.assertRaises(server.UserError) as e:
            self.app.review_start(dict(self.ref, agent="cloud"))
        self.assertIn("restricted", str(e.exception))
        out = self.app.review_start(dict(self.ref, agent="lokal", ticket="dlp-7", goal="Nur der Export, die Liste selbst ist schon reviewt."))
        rid, prompt, phase = self.started[0]
        self.assertEqual((out["agent"], phase, rid), ("Qwen", "review", out["id"]))
        self.assertIn("Nur der Export, die Liste selbst ist schon reviewt.", prompt)
        self.assertIn("## Ticket DLP-7: CSV-Export", prompt)
        self.assertIn("AK2: Leere Liste zeigt Hinweis", prompt)
        self.assertIn("Prüf je Kriterium", prompt)
        self.assertIn("## Beschreibung des MR", prompt)
        self.assertNotIn("glpat-abcdefghijklmnopqrstu", prompt, "Geheimnisse in der MR-Beschreibung werden geschwärzt")
        self.assertIn("git diff --stat origin/develop...HEAD", prompt)
        mr = json.loads(self.app.store.agent_run(rid)["mr"])
        self.assertEqual((mr["ticket"], mr["goal"][:8]), ("DLP-7", "Nur der "))
        self.assertTrue(any(r["action"] == "review.start" for r in self.app.audit_log.export()))

    def test_start_without_ticket_says_so(self):
        self.app.client = type("C", (), {"mr_detail": lambda self, pid, iid: {}})()
        self.app.review_start(self.ref)                    # ohne Wahl: der erste, der darf
        prompt = self.started[0][1]
        self.assertIn("weder Beschreibung noch Ticket", prompt)
        self.assertNotIn("## Ticket", prompt)

    def test_ui(self):
        js = ui.source(ROOT)
        for s in ("/api/review/options", "id=\"rvAgent\"", "id=\"rvTicket\"", "id=\"rvGoal\"", "data-rvrun"):
            self.assertIn(s, js)


class ApiCalls(unittest.TestCase):
    """Entscheid vom 20.11.: jeder Aufruf nach aussen steht in apicalls.CALLS; keine Verbindung daran vorbei."""
    OPEN = ("urlopen(", "opener.open(", "self._open(req")

    def test_every_connection_is_recorded(self):
        import re
        for f in sorted(ROOT.glob("*.py")):
            src = f.read_text(encoding="utf-8")
            n = sum(src.count(x) for x in self.OPEN) - src.count("def _open(")
            if f.name in ("routes.py", "start.py"):                # Server-Seite (Antworten) und Start-Skript: keine Aufrufe nach aussen über diese
                continue
            if n:
                self.assertGreaterEqual(src.count("apicalls.record("), 1 if f.name in ("m365.py", "net.py", "httpclient.py") else n, f.name)
        for f in ("github.py", "sonar.py", "settings.py", "conntest.py", "conntest_jira.py"):      # 0.45: Verbindungstests in conntest*
            src = (ROOT / f).read_text(encoding="utf-8")
            self.assertEqual(len(re.findall(r"net\.probe\((?![^\n]*svc=)", src)), 0, f)

    def test_paths_in_code_are_listed(self):
        import re
        import apicalls
        skip = {"/browse/", "/issues/?jql=", "/secure/CreateIssue!default.jspa", "/project/", "/rest/api/2", "/checks", "/repos/([^/]+/[^/]+)$", "/api/v4", "/issue/"}
        for f, svc in (("gitlab_client.py", "GitLab"), ("jira_client.py", "Jira"), ("github.py", "GitHub"), ("sonar.py", "Sonar"), ("bcs.py", "BCS"), ("m365.py", "Microsoft 365")):
            for p in sorted(set(re.findall(r'"(/[a-zA-Z_%][^" ]*)"', (ROOT / f).read_text(encoding="utf-8")))):
                if p in skip or "." in p.split("/")[-1] and "..." not in p:
                    continue
                path = p.replace("/repos/%s", "/repos/o/r").replace("%s", "1").replace("%d", "1")
                self.assertTrue(any(apicalls.find(svc, m, path) is not None for m in ("GET", "POST", "DELETE")), "%s: %s fehlt in apicalls.CALLS" % (f, p))

    def test_record_and_view(self):
        import apicalls
        apicalls.reset()
        apicalls.record("GitLab", "GET", "/projects/7/merge_requests/3/approvals")
        apicalls.record("GitLab", "GET", "https://g.example/api/v4/projects/7/pipelines?ref=x")
        apicalls.record("GitLab", "POST", "/projects/7/merge_requests/3/merge")
        v = apicalls.view()["rows"]
        self.assertEqual(sum(r["count"] for r in v if not r.get("unknown")), 2)
        unk = [r for r in v if r.get("unknown")]
        self.assertEqual((unk[0]["path"], unk[0]["write"]), ("/projects/:id/merge_requests/:id/merge", True))
        self.assertTrue(all(r["token"] for r in v if not r.get("unknown")))


if __name__ == "__main__":
    unittest.main()
