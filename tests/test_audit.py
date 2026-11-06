"""Audit-Trail (0.17): Hash-Kette, nur anhängend, keine Secrets, ein Eintrag je Aktion, Jira-Doppelt-Schutz, Aufbewahrung, CLI."""
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import audit  # noqa: E402
import links  # noqa: E402
import server  # noqa: E402
from test_agents import HAVE_TMUX, Env, cfg as agent_cfg, git_repo, service, wait_for  # noqa: E402
from test_settings import start  # noqa: E402


class Chain(unittest.TestCase):
    def setUp(self):
        self.db = Path(tempfile.mkdtemp()) / "t.db"
        self.al = audit.AuditLog(self.db)

    def test_append_verify_and_rows(self):
        for i in range(5):
            self.al.add("board.stage", "DLP-%d" % i, detail={"stage": "impl"})
        self.al.add("jira.create", "DLP", ok=False, detail={"error": "nein"})
        v = self.al.verify()
        self.assertEqual((v["ok"], v["count"]), (True, 6))
        self.assertEqual(len(v["last_hash"]), 64)
        rows = self.al.rows()
        self.assertEqual(rows[0]["action"], "jira.create")           # neueste zuerst
        self.assertFalse(rows[0]["ok"])
        self.assertEqual(rows[1]["label"], "Station gesetzt")
        self.assertEqual([r["target"] for r in self.al.rows(target=["DLP-1", "DLP-3"])], ["DLP-3", "DLP-1"])
        self.assertEqual(len(self.al.rows(action="board.stage", limit=2)), 2)
        self.assertEqual([r["id"] for r in self.al.export()], sorted(r["id"] for r in rows))
        self.assertEqual(len({r["instance"] for r in rows}), 1)
        self.assertEqual(self.al.instance(), audit.AuditLog(self.db).instance())   # bleibt über Neustarts gleich

    def test_update_and_delete_are_blocked(self):
        self.al.add("flow.pin", "X-1")
        c = sqlite3.connect(str(self.db))
        for sql in ("update audit set target='X-2'", "delete from audit"):
            with self.assertRaises(sqlite3.DatabaseError):
                c.execute(sql)
        c.close()
        self.assertTrue(self.al.verify()["ok"])

    def _tamper(self, sql):
        c = sqlite3.connect(str(self.db), isolation_level=None)
        c.execute("drop trigger audit_no_update")
        c.execute("drop trigger audit_no_delete")
        c.execute(sql)
        c.close()

    def test_changed_entry_is_detected(self):
        for i in range(3):
            self.al.add("board.stage", "A-%d" % i, detail={"stage": "impl"})
        self._tamper("""update audit set detail='{"stage":"done"}' where id=2""")
        v = self.al.verify()
        self.assertFalse(v["ok"])
        self.assertEqual(v["broken_at"], 2)
        self.assertIn("Inhalt", v["reason"])

    def test_deleted_middle_and_tail_are_detected(self):
        for i in range(4):
            self.al.add("board.stage", "A-%d" % i)
        self._tamper("delete from audit where id=2")
        self.assertEqual(self.al.verify()["broken_at"], 3)
        db2 = Path(tempfile.mkdtemp()) / "t.db"
        al2 = audit.AuditLog(db2)
        for i in range(3):
            al2.add("board.stage", "B-%d" % i)
        c = sqlite3.connect(str(db2), isolation_level=None)
        c.execute("drop trigger audit_no_delete")
        c.execute("delete from audit where id=3")
        c.close()
        v = al2.verify()
        self.assertFalse(v["ok"])
        self.assertIn("fehlen", v["reason"])

    def test_no_secrets_and_bounded_detail(self):
        self.al.add("settings.save", "", detail={"api_token": "geheim", "password": "pw", "nested": {"Authorization": "Bearer x", "ok": 1},
                                                  "note": "Token glpat-abcdefghijklmnopqrstu im Text", "big": ["x" * 400] * 30})
        raw = sqlite3.connect(str(self.db)).execute("select detail from audit").fetchone()[0]
        self.assertNotIn("geheim", raw)
        self.assertNotIn("pw", json.loads(raw).values())
        self.assertNotIn("Bearer x", raw)
        self.assertNotIn("glpat-abcdefghijklmnopqrstu", raw)
        d = json.loads(raw)                               # bleibt gültiges JSON, auch wenn gekürzt
        self.assertIn("big", d.get("gekuerzt", []))
        self.assertEqual(d["nested"] if "nested" in d else {"ok": 1}, {"ok": 1})
        self.assertTrue(self.al.verify()["ok"])

    def test_prompt_hash(self):
        h = audit.prompt_hash("Bitte den Retry testen")
        self.assertTrue(h.startswith("sha256:"))
        self.assertEqual(h, audit.prompt_hash("Bitte den Retry testen"))
        self.assertNotEqual(h, audit.prompt_hash("anders"))


class AppAudit(unittest.TestCase):
    def setUp(self):
        self.old = os.environ.get("TINYOPS_HOME")
        os.environ["TINYOPS_HOME"] = tempfile.mkdtemp()
        cfg = server.load_config(None)
        cfg["data_dir"] = tempfile.mkdtemp()
        self.app = server.App(cfg, True, {}, Path("/nonexistent/c.json"))
        self.app.overview()

    def tearDown(self):
        if self.old is None:
            os.environ.pop("TINYOPS_HOME", None)
        else:
            os.environ["TINYOPS_HOME"] = self.old

    def n(self):
        return self.app.audit_log.verify()["count"]

    def last(self):
        return self.app.audit_log.rows(limit=1)[0]

    def test_each_action_writes_exactly_one_entry(self):
        a = self.app
        cases = [
            (lambda: a.board_action("stage", {"key": "DLP-104", "stage": "impl"}), "board.stage", "DLP-104"),
            (lambda: a.flow_action("complete", {"id": "DLP-104", "phase": 2}), "flow.complete", "DLP-104"),
            (lambda: a.flow_action("pin", {"id": "DLP-104"}), "flow.pin", "DLP-104"),
            (lambda: a.flow_action("tiny", {"project_id": 1, "branch": "feature/proxo-mapping", "title": "proxo", "project": "dlp-core"}), "flow.tiny", None),
            (lambda: a.board_action("add", {"title": "Doku schreiben", "stage": "idea"}), "board.add", None),
            (lambda: a.link_ticket({"project_id": 1, "branch": "feature/x", "ticket": "DLP-104"}), "link.set", "1:feature/x"),
            (lambda: a.unlink_ticket({"project_id": 1, "branch": "feature/x"}), "link.delete", "1:feature/x"),
        ]
        for fn, action, target in cases:
            before = self.n()
            try:
                fn()
            except server.UserError:
                pass
            self.assertEqual(self.n(), before + 1, action)
            r = self.last()
            self.assertEqual(r["action"], action)
            if target:
                self.assertEqual(r["target"], target)
        tiny = [r for r in a.audit_log.rows(action="flow.tiny")][0]
        self.assertTrue(tiny["target"].startswith("LOC-"))           # Ziel ist das neue Ticket, nicht der Branch
        self.assertEqual(tiny["detail"]["branch"], "1:feature/proxo-mapping")
        add = a.audit_log.rows(action="board.add")[0]
        self.assertTrue(add["target"].startswith("LOC-"))
        comp = a.audit_log.rows(action="flow.complete")[0]
        self.assertEqual(comp["detail"]["stage"], "review")
        self.assertTrue(a.audit_log.verify()["ok"])

    def test_failure_is_recorded_once(self):
        before = self.n()
        with self.assertRaises(server.UserError):
            self.app.flow_action("complete", {"id": "1:feature/proxo-mapping", "phase": 2})
        self.assertEqual(self.n(), before + 1)
        r = self.last()
        self.assertFalse(r["ok"])
        self.assertIn("Ticket", r["detail"]["error"])

    def test_accept_binds_commits_in_detail(self):
        ov = self.app.overview()
        card = next(c for c in ov["board"]["cards"] if any(x.get("iid") for x in c["items"]) and not links.is_ref_key(c["id"]))
        before = self.n()
        self.app.flow_action("accept", {"id": card["id"], "note": "Retry geprüft", "env": "test-7"})
        self.assertEqual(self.n(), before + 1)
        r = self.last()
        self.assertEqual((r["action"], r["target"]), ("flow.accept", card["id"]))
        self.assertEqual(r["detail"]["note"], "Retry geprüft")
        self.assertTrue(r["detail"]["accepted"])
        self.assertIn("@", r["detail"]["accepted"][0])

    def test_audit_failure_never_blocks(self):
        class Broken:
            def add(self, *a, **k):
                raise sqlite3.OperationalError("disk I/O error")
        self.app.audit_log = Broken()
        self.assertEqual(self.app.board_action("stage", {"key": "DLP-104", "stage": "impl"})["key"], "DLP-104")


class JiraDuplicate(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.p, cls.port = start("mock_jira.py")

    @classmethod
    def tearDownClass(cls):
        cls.p.terminate()
        cls.p.wait()

    def test_same_title_within_ten_minutes_asks(self):
        cfg = server.load_config(None)
        cfg["data_dir"] = tempfile.mkdtemp()
        cfg["jira"] = {"url": "http://127.0.0.1:%d" % self.port, "project_keys": ["DLP"], "allow_create": True}
        app = server.App(cfg, False, {"jira_token": "jtoken"}, Path("/nonexistent/c.json"))
        body = {"project": "DLP", "summary": "Retry für Upload", "description": "d", "issue_type": "Story"}
        k1 = app.ticket_create(body)["key"]
        with self.assertRaises(server.UserError) as cm:
            app.ticket_create(dict(body, summary="retry  für upload"))
        self.assertEqual(cm.exception.data["duplicate"], k1)
        self.assertIn(k1, str(cm.exception))
        k2 = app.ticket_create(dict(body, force=True))["key"]
        app.ticket_create(dict(body, summary="Etwas anderes"))
        rows = app.audit_log.rows(action="jira.create")
        self.assertEqual(len(rows), 3)                        # die abgelehnte Doppelung legt nichts an
        self.assertTrue(rows[1]["detail"]["forced"])
        # nach 10 min wieder ohne Rückfrage
        old = time.time() - 700
        app.audit_log = audit.AuditLog(Path(cfg["data_dir"]) / "old.db")
        app.audit_log.add("jira.create", "DLP-1", detail={"project": "DLP", "summary": "Alt"}, now=old)
        app.ticket_create(dict(body, summary="Alt"))


class LogDaysSetting(unittest.TestCase):
    def test_build_and_view(self):
        import settings
        new, err = settings.build_config({}, {"gitlab": {"url": "https://g.example"}, "agent_log_days": "14"})
        self.assertEqual((err, new["agent_log_days"]), ({}, 14))
        self.assertEqual(settings.view(new, Path("/x"))["agent_log_days"], 14)
        for bad in ("-1", "abc", 99999):
            _, err = settings.build_config({}, {"gitlab": {"url": "https://g.example"}, "agent_log_days": bad})
            self.assertIn("agent_log_days", err)
        self.assertEqual(server.load_config(None)["agent_log_days"], 30)


class Retention(unittest.TestCase):
    def test_local_files_older_than_days_go(self):
        d = Path(tempfile.mkdtemp())
        st = links.Store(d / "t.db")
        svc = server.agents.Service({"agents": [], "connections": []}, st, d / "runs", ROOT)
        events = []
        svc.audit = lambda *a, **k: events.append((a, k))
        (d / "runs").mkdir()
        old, new = d / "runs" / "3.log", d / "runs" / "4.log"
        old.write_text("x")
        new.write_text("y")
        t = time.time() - 40 * 86400
        os.utime(old, (t, t))
        self.assertIsNone(svc.retention(0))
        res = svc.retention(30)
        self.assertEqual(res["local"], 1)
        self.assertFalse(old.exists())
        self.assertTrue(new.exists())
        self.assertEqual(events[0][0][0], "agent.retention")
        self.assertEqual(svc.retention(30)["local"], 0)
        self.assertEqual(len(events), 1)                    # nichts gelöscht, kein Eintrag


@unittest.skipUnless(HAVE_TMUX, "tmux nicht installiert")
class AgentEvents(unittest.TestCase):
    def test_assign_start_finish_remove_with_prompt_hash(self):
        env = Env(self)
        svc = service(env, agent_cfg(env, command="echo fertig"))
        events = []
        svc.audit = lambda action, target="", ok=True, actor="du", **d: events.append((action, target, ok, actor, d))
        rid = svc.assign("a1", "DLP-9", 7, "", "Titel")
        svc.start(rid, "Mach den Retry")
        self.assertTrue(wait_for(lambda: (svc.poll(force=True), svc.store.agent_run(rid)["status"] == "fertig")[1]))
        svc.remove(rid)
        acts = [e[0] for e in events]
        self.assertEqual(acts, ["agent.assign", "agent.start", "agent.finish", "agent.remove"])
        start_ev = events[1]
        self.assertEqual(start_ev[1], "DLP-9")
        self.assertEqual(start_ev[4]["prompt_hash"], audit.prompt_hash("Mach den Retry"))
        self.assertNotIn("Mach den Retry", json.dumps(events))
        self.assertEqual(start_ev[4]["data_class"], "internal")
        self.assertEqual(start_ev[4]["mode"], "worktree")
        self.assertEqual(start_ev[4]["where"], "box")
        self.assertEqual(events[2][3], "agent")

    def test_blocked_assign_is_recorded(self):
        env = Env(self)
        svc = service(env, agent_cfg(env, kind="claude", allow=False))
        events = []
        svc.audit = lambda action, target="", ok=True, actor="du", **d: events.append((action, ok, d))
        with self.assertRaises(server.agents.AgentError):
            svc.assign("a1", "DLP-9", 7, "", "t")
        self.assertEqual(events[0][0], "agent.assign")
        self.assertFalse(events[0][1])
        self.assertEqual(events[0][2]["data_class"], "restricted")


class Http(unittest.TestCase):
    def test_routes_and_cli(self):
        home = tempfile.mkdtemp()
        data = tempfile.mkdtemp()
        conf = Path(home) / "config.json"
        conf.write_text(json.dumps({"data_dir": data}))
        al = audit.AuditLog(Path(data) / "tinyops.db")
        al.add("board.stage", "DLP-1", detail={"stage": "impl"})
        env = dict(os.environ, TINYOPS_HOME=home, TINYOPS_NO_WATCHDOG="1")
        r = subprocess.run([sys.executable, str(ROOT / "server.py"), "--config", str(conf), "--verify-audit"], capture_output=True, text=True, env=env)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("1 Einträge", r.stdout)
        out = Path(home) / "a.json"
        r = subprocess.run([sys.executable, str(ROOT / "server.py"), "--config", str(conf), "--export-audit", str(out)], capture_output=True, text=True, env=env)
        self.assertEqual(r.returncode, 0)
        self.assertEqual(json.loads(out.read_text())["rows"][0]["target"], "DLP-1")
        c = sqlite3.connect(str(Path(data) / "tinyops.db"), isolation_level=None)
        c.execute("drop trigger audit_no_update")
        c.execute("update audit set target='DLP-2'")
        c.close()
        r = subprocess.run([sys.executable, str(ROOT / "server.py"), "--config", str(conf), "--verify-audit"], capture_output=True, text=True, env=env)
        self.assertEqual(r.returncode, 1)
        self.assertIn("GEBROCHEN", r.stdout)

    def test_api(self):
        p, port = start_demo(self)
        def get(path):
            with urllib.request.urlopen("http://127.0.0.1:%d%s" % (port, path)) as r:
                return r.headers, json.loads(r.read())
        req = urllib.request.Request("http://127.0.0.1:%d/api/board/stage" % port, data=json.dumps({"key": "DLP-104", "stage": "impl"}).encode(),
                                     headers={"X-Requested-With": "tinyops", "Content-Type": "application/json"}, method="POST")
        urllib.request.urlopen(req).read()
        _, v = get("/api/audit?target=DLP-104&target=nix")
        self.assertEqual(v["rows"][0]["action"], "board.stage")
        self.assertTrue(v["instance"])
        _, ver = get("/api/audit/verify")
        self.assertTrue(ver["ok"])
        h, ex = get("/api/audit/export")
        self.assertIn("attachment", h["Content-Disposition"])
        self.assertEqual(ex["verify"]["count"], len(ex["rows"]))


def start_demo(tc):
    import socket
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    home, data = tempfile.mkdtemp(), tempfile.mkdtemp()
    conf = Path(home) / "config.json"
    conf.write_text(json.dumps({"data_dir": data, "port": port}))
    env = dict(os.environ, TINYOPS_HOME=home, TINYOPS_NO_WATCHDOG="1")
    p = subprocess.Popen([sys.executable, str(ROOT / "server.py"), "--config", str(conf), "--demo"], env=env,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, cwd=str(ROOT))
    tc.addCleanup(lambda: (p.terminate(), p.wait()))
    for _ in range(100):
        try:
            urllib.request.urlopen("http://127.0.0.1:%d/api/health" % port, timeout=1)
            break
        except Exception:
            time.sleep(0.1)
    return p, port


if __name__ == "__main__":
    unittest.main()
