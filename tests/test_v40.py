"""0.40: Weiterführen in derselben Agenten-Sitzung (Gespräch im Lauf), Zurück ans Entwickeln, erneut prüfen, Git-Benutzer je Agent,
agents.py aufgeteilt."""
import json
import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import agent_cmd  # noqa: E402
import agent_rules  # noqa: E402
import agents  # noqa: E402
import briefing  # noqa: E402
import server  # noqa: E402
from test_agents import git_repo, wait_for  # noqa: E402

P = agent_cmd.PROMPT


class Argv(unittest.TestCase):
    def a(self, kind, **kw):
        return dict({"id": "x", "kind": kind, "extra_args": ""}, **kw)

    def test_claude_start_and_resume(self):
        a = self.a("claude", extra_args="--permission-mode acceptEdits")
        start = agent_cmd.command_argv(a, {"id": "0b7c9a52-1111-4222-8333-444455556666", "resume": False})
        self.assertEqual(start[:3], ["claude", "-p", P])
        self.assertIn("--session-id", start)
        self.assertEqual(start[-2:], ["--permission-mode", "acceptEdits"])
        res = agent_cmd.command_argv(a, {"id": "0b7c9a52-1111-4222-8333-444455556666", "resume": True})
        self.assertEqual(res[res.index("--resume") + 1], "0b7c9a52-1111-4222-8333-444455556666")
        self.assertNotIn("--session-id", res)
        self.assertEqual(agent_cmd.command_argv(a), ["claude", "-p", P, "--output-format", "stream-json", "--verbose", "--permission-mode", "acceptEdits"])

    def test_codex_vibe_goose_opencode(self):
        cx = self.a("codex", extra_args="--full-auto")
        self.assertEqual(agent_cmd.command_argv(cx, {"id": "019a-aaaa-bbbb-cccc-ddddeeeeffff", "resume": True}),
                         ["codex", "exec", "--full-auto", "resume", "019a-aaaa-bbbb-cccc-ddddeeeeffff", P])
        self.assertEqual(agent_cmd.command_argv(cx, {"id": "", "resume": True}), ["codex", "exec", "--full-auto", "resume", "--last", P])
        self.assertEqual(agent_cmd.command_argv(cx, {"id": "", "resume": False}), ["codex", "exec", P, "--full-auto"])
        vb = self.a("vibe")
        self.assertIn("--continue", agent_cmd.command_argv(vb, {"id": "", "resume": True}))
        self.assertEqual(agent_cmd.command_argv(vb, {"id": "s-123456", "resume": True})[-2:], ["--resume", "s-123456"])
        gs = self.a("goose", model="qwen", provider="ollama")
        self.assertEqual(agent_cmd.command_argv(gs, {"id": "tinyops-7", "resume": True})[:6], ["goose", "run", "--name", "tinyops-7", "--resume", "-i"])
        self.assertEqual(agent_cmd.command_argv(gs, {"id": "tinyops-7", "resume": False})[:5], ["goose", "run", "--name", "tinyops-7", "-i"])
        oc = self.a("opencode", model="qwen", provider="ollama")
        self.assertEqual(agent_cmd.command_argv(oc, {"id": "", "resume": True})[-1], "--continue")
        self.assertFalse(agent_cmd.can_resume(self.a("custom")))
        with self.assertRaises(agents.AgentError):
            agent_cmd.command_argv(self.a("claude"), {"id": "x; rm -rf /", "resume": True})

    def test_new_and_found_sessions(self):
        self.assertRegex(agent_cmd.new_session(self.a("claude"), 4), r"^[0-9a-f-]{36}$")
        self.assertEqual(agent_cmd.new_session(self.a("goose"), 4), "tinyops-4")
        self.assertEqual(agent_cmd.new_session(self.a("codex"), 4), "")
        self.assertEqual(agent_cmd.find_session(self.a("codex"), "workdir: /x\nsession id: 0199a1b2-c3d4-7e5f-8a9b-0c1d2e3f4a5b\n--------"),
                         "0199a1b2-c3d4-7e5f-8a9b-0c1d2e3f4a5b")
        self.assertEqual(agent_cmd.find_session(self.a("vibe"), '{"type": "x", "session_id": "abc_123-xyz"}'), "abc_123-xyz")
        self.assertEqual(agent_cmd.find_session(self.a("claude"), "session id: 0199a1b2-c3d4-7e5f-8a9b-0c1d2e3f4a5b"), "")

    def test_last_reply(self):
        log = '{"type":"assistant","message":{"content":[{"type":"text","text":"Ich schaue"}]}}\n{"type":"result","result":"Fertig: Retry eingebaut."}\n'
        self.assertEqual(agent_cmd.last_reply(log), "Fertig: Retry eingebaut.")
        self.assertIn("zeile 20", agent_cmd.last_reply("\n".join("zeile %d" % i for i in range(21))))
        self.assertNotIn("glpat-", agent_cmd.last_reply('{"type":"result","result":"token glpat-abcdefghijklmnopqrstuvwx"}'))

    def test_git_user(self):
        a = self.a("claude", git_name="Agent Claude", git_email="agent@example.org")
        line = agent_cmd.remote_cmdline(a)
        self.assertIn("GIT_AUTHOR_NAME='Agent Claude'", line)
        self.assertIn("GIT_COMMITTER_EMAIL=agent@example.org", line)
        c = self.a("custom", command="run {prompt_file}", git_name="Bot")
        self.assertTrue(agent_cmd.remote_cmdline(c).startswith("export GIT_AUTHOR_NAME=Bot; export GIT_COMMITTER_NAME=Bot; run "))
        errors = {}
        out = agent_rules.clean_agents([{"id": "a1", "name": "A", "kind": "claude", "connection": "local", "workspace_root": "/w",
                                         "git_name": "Bot; rm", "git_email": "nope"}], {"local"}, [], errors)
        self.assertTrue(any(k.endswith("git_name") for k in errors) and any(k.endswith("git_email") for k in errors), errors)
        ok = agent_rules.clean_agents([{"id": "a1", "name": "A", "kind": "claude", "connection": "local", "workspace_root": "/w",
                                        "git_name": "Claude (devvm)", "git_email": "claude@example.org"}], {"local"}, [], {})
        self.assertEqual((ok[0]["git_name"], ok[0]["git_email"]), ("Claude (devvm)", "claude@example.org"))

    def test_briefs(self):
        run = {"id": 5, "phase": "review", "phase_label": "Review", "agent_name": "R", "summary": "## Kurz\nZwei Punkte.\n\n## Befund\n- Retry fehlt bei 503",
               "criteria": [{"text": "Retry", "state": "open", "note": "fehlt"}], "checks": [{"exit": 1, "cmd": "mvn test"}]}
        b = briefing.back_to_dev(run, "Punkt 1 ist wichtig")
        for s in ("Review von R (Lauf 5)", "Punkt 1 ist wichtig", "Retry fehlt bei 503", "Exit 1: mvn test"):
            self.assertIn(s, b)
        self.assertEqual(briefing.resume(dict(run, summary=""), "Warum Punkt 2?").strip(), "## Nachricht des Menschen\n\nWarum Punkt 2?")
        dev = briefing.resume({"id": 3, "phase": "develop", "criteria": [{"text": "A", "state": "open", "note": ""}]}, "weiter")
        self.assertTrue(dev.startswith("Fortsetzung von tinyops-Lauf 3."))
        self.assertIn("AK1: A", dev)


class Split(unittest.TestCase):
    def test_modules_small_and_names_reachable(self):
        for f in ("agents.py", "agent_rules.py", "agent_cmd.py", "agent_scripts.py", "agent_ssh.py", "agent_talk.py"):
            n = len((ROOT / f).read_text(encoding="utf-8").splitlines())
            self.assertLess(n, 1000, "%s hat %d Zeilen" % (f, n))
        for name in ("KINDS", "clean_agents", "prepare_script", "remote_start_script", "stream_line", "PHASE_LABEL", "clean_text", "AgentError"):
            self.assertTrue(hasattr(agents, name), name)
        self.assertEqual(agents.PHASE_LABEL["develop"], "Entwickeln")


FAKE = """#!/bin/sh
# Ersatz für Claude Code: hält die Argumente fest, schreibt eine Zeile ins Repo, committet, antwortet wie im Streaming
printf '%s\\0' "$@" > "$ARGLOG.$TINYOPS_RUN_ID"
case "$*" in *"# Review:"*|*"Prüfe erneut"*) ;;     # Review ändert nichts
  *) echo "lauf $TINYOPS_RUN_ID" >> arbeit.txt
     git add -A >/dev/null 2>&1 && git -c user.name=a -c user.email=a@x commit -qm "lauf $TINYOPS_RUN_ID" >/dev/null 2>&1;;
esac
printf '%s\\n' '{"type":"result","result":"Antwort aus Lauf '"$TINYOPS_RUN_ID"'"}'
"""


class Conversation(unittest.TestCase):
    """Echter lokaler Lauf mit einem Ersatz für Claude Code: weiterführen, zurück ans Entwickeln, erneut prüfen."""

    def setUp(self):
        self.d = Path(tempfile.mkdtemp())
        git_repo(self.d / "ws" / "dlp-core")
        b = self.d / "bin"
        b.mkdir()
        (b / "claude").write_text(FAKE)
        (b / "claude").chmod(0o755 | stat.S_IEXEC)
        self.arglog = self.d / "args.log"
        self.old = dict(os.environ)
        os.environ.update(PATH=str(b) + os.pathsep + os.environ["PATH"], ARGLOG=str(self.arglog), TINYOPS_HOME=str(self.d / "home"))
        self.addCleanup(lambda: (os.environ.clear(), os.environ.update(self.old)))
        c = server.load_config(None)
        c.update(data_dir=str(self.d / "data"), projects=[{"id": 1, "name": "dlp-core", "data_class": "internal"}], connections=[],
                 agents=[{"id": "a1", "name": "Claude", "kind": "claude", "connection": "local", "workspace_root": str(self.d / "ws"),
                          "extra_args": "--permission-mode acceptEdits", "git_name": "Agent", "git_email": "agent@example.org"}])
        self.app = server.App(c, True, {}, self.d / "config.json", watchdog=False)
        self.body = {"agent": "a1", "ticket": "DLP-7", "key": "DLP-7", "project_id": 1, "title": "Retry"}

    def finish(self, rid):
        a = self.app
        self.assertTrue(wait_for(lambda: (a.agents.poll(force=True), a.store.agent_run(rid)["status"] not in ("läuft", "zugewiesen"))[1], 20))
        r = a.store.agent_run(rid)
        self.assertEqual(r["status"], "fertig", (r["note"], a.agents.tail(rid)))
        return r

    def start(self, body, info):
        rid = self.app.agent_action("assign", dict(body, branch=info.get("branch") or ""))["id"]
        self.app.agent_action("start", {"run": rid, "prompt": info["prompt"], "project_id": 1, "branch": info.get("branch"),
                                        "phase": info.get("phase"), "parent": info.get("parent")})
        return self.finish(rid)

    def args(self):
        """Argumente je Lauf, in der Reihenfolge der Läufe (der Ersatz schreibt sie getrennt durch NUL)."""
        fs = sorted(self.d.glob("args.log.*"), key=lambda f: int(f.suffix[1:]))
        return [f.read_text().split("\0")[:-1] for f in fs]

    def test_same_session_back_and_again(self):
        a = self.app
        dev = self.start(self.body, a.agent_action("prompt", self.body))
        sid = dev["session"]
        self.assertRegex(sid, r"^[0-9a-f-]{36}$")
        self.assertEqual(self.args()[0][self.args()[0].index("--session-id") + 1], sid)
        wt = dev["wt"]
        # Nachfrage in derselben Sitzung
        out = a.agent_action("continue", {"run": dev["id"], "text": "Bitte noch Logging"})
        self.assertTrue(out["session"])
        dev2 = self.finish(out["id"])
        self.assertEqual((dev2["wt"], dev2["session"], dev2["out_branch"], dev2["resume_of"]), (wt, sid, dev["out_branch"], str(dev["id"])))
        last = self.args()[-1]
        self.assertEqual(last[last.index("--resume") + 1], sid)
        self.assertNotIn("--session-id", last)
        old = a.store.agent_run(dev["id"])
        self.assertEqual((old["wt"], old["next_run"]), ("", str(dev2["id"])))
        self.assertIn("Weiter: DLP-7", dev2["prompt"])
        self.assertIn("Bitte noch Logging", dev2["prompt"])
        self.assertEqual((Path(wt) / "arbeit.txt").read_text().count("lauf"), 2)          # derselbe Ordner
        log = os.popen("git -C %s log -1 --format=%%an/%%ae" % wt).read().strip()
        self.assertEqual(log, "Agent/agent@example.org")      # Git-Benutzer des Agenten gilt sogar vor «git -c user.name=…»
        spec = json.loads((a.agents.run_dir / ("%d.spec.json" % dev2["id"])).read_text())
        self.assertEqual((spec["env"]["GIT_AUTHOR_NAME"], spec["env"]["GIT_COMMITTER_EMAIL"]), ("Agent", "agent@example.org"))
        v = a.agents.run_view(dev2)
        self.assertEqual([m["who"] for m in v["thread"]], ["du", "agent", "du", "agent"])
        self.assertEqual(v["thread"][1]["text"], "Antwort aus Lauf %d" % dev["id"])
        self.assertEqual(v["thread"][2]["text"], "Bitte noch Logging")
        self.assertEqual(v["round"], 2)
        self.assertTrue(v["same_session"])
        self.assertFalse(a.agents.run_view(old)["same_session"])                         # schon weitergeführt
        # Freigeben, Review mit eigenem Worktree, dann Befund zurück ans Entwickeln
        a.agent_action("gate", {"run": dev2["id"], "gate": "ok"}) if not a.agents.run_view(dev2)["manual"] else None
        rv_info = a.agent_action("prompt", dict(self.body, phase="review", parent=dev2["id"]))
        rv = self.start(self.body, rv_info)
        self.assertEqual(rv["phase"], "review")
        back = a.agent_action("back", {"run": rv["id"], "note": "Punkt 1 bitte"})
        self.assertEqual(back["dev"], dev2["id"])
        self.assertTrue(back["session"])
        dev3 = self.finish(back["id"])
        self.assertEqual((dev3["session"], dev3["wt"]), (sid, wt))
        self.assertIn("Zurück ans Entwickeln nach dem Review", dev3["prompt"])
        self.assertIn("Punkt 1 bitte", dev3["prompt"])
        self.assertEqual(a.store.agent_run(rv["id"])["gate"], "back")
        # Derselbe Reviewer prüft erneut, sein Ordner steht auf dem neuen Stand des Entwicklers
        again = a.agent_action("again", {"run": dev3["id"]})
        self.assertNotIn("fallback", again, again)
        rv2 = self.finish(again["id"])
        self.assertEqual((rv2["phase"], rv2["session"], rv2["wt"]), ("review", rv["session"], rv["wt"]))
        self.assertIn("lauf %d" % dev3["id"], (Path(rv["wt"]) / "arbeit.txt").read_text())
        rows = [r["action"] for r in a.audit_log.export()]
        for act in ("agent.continue", "agent.back", "agent.again"):
            self.assertIn(act, rows)

    def test_other_agent_or_lost_folder_means_new_session(self):
        a = self.app
        dev = self.start(self.body, a.agent_action("prompt", self.body))
        a.agents.store.agent_run_update(dev["id"], wt="")                                   # Ordner weg (z. B. entfernt)
        ok, why = a.agents.can_continue(a.store.agent_run(dev["id"]))
        self.assertFalse(ok)
        self.assertIn("Arbeitsordner", why)
        out = a.agent_action("continue", {"run": dev["id"], "text": "weiter"})
        self.assertFalse(out["session"])
        new = self.finish(out["id"])
        self.assertEqual((new["fresh"], new["resume_of"]), ("1", str(dev["id"])))
        self.assertNotEqual(new["session"], dev["session"])
        self.assertIn("--session-id", self.args()[-1])
        self.assertTrue(a.agents.run_view(new)["thread"][2]["fresh"])


if __name__ == "__main__":
    unittest.main()
