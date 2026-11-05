"""Coding-Agenten: Prüfungen der Eingaben, Cloud-Sperre, lokaler Lauf, SSH+tmux (mit echtem tmux und einem ssh-Ersatz), Einstellungen."""
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import agents  # noqa: E402
import links  # noqa: E402
import server  # noqa: E402
import settings  # noqa: E402

STUB_SSH = """#!/bin/sh
# Ersatz für ssh: überspringt Optionen bis «--», dann das Ziel, und führt den Rest lokal aus (HOME zeigt auf das «Zielhost»-Verzeichnis).
echo "$@" >> "$STUB_LOG"
while [ "$1" != "--" ]; do shift; done
shift; shift
case "$STUB_FAIL" in "") ;; *) echo "$STUB_FAIL" >&2; exit 255;; esac
exec sh -c "$1"
"""

HAVE_TMUX = shutil.which("tmux") is not None


def wait_for(fn, secs=15):
    end = time.time() + secs
    while time.time() < end:
        v = fn()
        if v:
            return v
        time.sleep(0.2)
    return None


class Env:
    """Temporäres «Zielhost»-Home mit ssh-Ersatz und eigenem tmux-Socket."""
    def __init__(self, tc):
        self.d = Path(tempfile.mkdtemp())
        tc.addCleanup(shutil.rmtree, self.d, True)
        self.remote = self.d / "remote"
        (self.remote / "ws" / "repo").mkdir(parents=True)
        (self.remote / "bin").mkdir()
        (self.remote / ".profile").write_text('export PATH="$HOME/bin:$PATH"\n')
        self.stub = self.d / "ssh"
        self.stub.write_text(STUB_SSH)
        self.stub.chmod(0o755)
        self.log = self.d / "ssh.log"
        self.tmux_tmp = self.d / "tmuxsock"
        self.tmux_tmp.mkdir()
        self.old = dict(os.environ)
        os.environ.update({"TINYOPS_SSH": str(self.stub), "STUB_LOG": str(self.log), "STUB_FAIL": "", "HOME": str(self.remote),
                           "TMUX_TMPDIR": str(self.tmux_tmp), "TINYOPS_HOME": str(self.d / "home"), "SHELL": "/bin/sh"})
        tc.addCleanup(self.close)

    def close(self):
        subprocess.run(["tmux", "kill-server"], capture_output=True)
        os.environ.clear()
        os.environ.update(self.old)

    def fake(self, name, body):
        f = self.remote / "bin" / name
        f.write_text("#!/bin/sh\n" + body)
        f.chmod(0o755)


def cfg(env, kind="custom", command=None, cloud=None, extra="", conn="box", allow=True):
    a = {"id": "a1", "name": "A1", "kind": kind, "connection": conn, "workspace_root": str(env.remote / "ws"), "extra_args": extra,
         "cloud": True if kind != "custom" else (True if cloud is None else cloud)}
    if command:
        a["command"] = command
    p = {"id": 7, "name": "repo"}
    if allow:
        p["allow_cloud_agents"] = True
    return {"connections": [{"id": "box", "name": "box", "host": "devbox", "user": "dev", "port": 22, "identity_file": "", "host_key": "strict"}],
            "agents": [a], "projects": [p]}


def service(env, c):
    return agents.Service(c, links.Store(env.d / "t.db"), env.d / "runs", ROOT)


class Validate(unittest.TestCase):
    def test_connections(self):
        e = {}
        out = agents.clean_connections([{"name": "Dev Box", "host": "dev.example.com", "user": "adrian", "port": "2222"},
                                        {"name": "x", "host": "a b"}, {"name": "local", "host": "h"}, {"name": "Dev Box", "host": "h2"}], e)
        self.assertEqual([c["id"] for c in out], ["dev-box", "x"])
        self.assertEqual(out[0]["port"], 2222)
        self.assertIn("connections.1.host", e)
        self.assertIn("connections.2.name", e)
        self.assertIn("connections.3.name", e)

    def test_option_injection_in_host_and_user(self):
        e = {}
        agents.clean_connections([{"name": "a", "host": "-oProxyCommand=evil"}, {"name": "b", "host": "h", "user": "-x"},
                                  {"name": "c", "host": "h;id"}], e)
        self.assertEqual(set(e), {"connections.0.host", "connections.1.user", "connections.2.host"})

    def test_agents_extra_args_and_roots(self):
        e = {}
        out = agents.clean_agents([{"name": "a", "kind": "claude", "connection": "box", "workspace_root": "/srv/ws", "extra_args": "--model opus"},
                                   {"name": "b", "kind": "claude", "connection": "box", "workspace_root": "rel", "extra_args": ""},
                                   {"name": "c", "kind": "claude", "connection": "box", "workspace_root": "/x", "extra_args": "$(id)"},
                                   {"name": "d", "kind": "claude", "connection": "nope", "workspace_root": "/x"},
                                   {"name": "e", "kind": "claude", "connection": "local", "workspace_root": "C:\\work"}], {"box"}, [], e)
        self.assertEqual(set(e), {"agents.1.workspace_root", "agents.2.extra_args", "agents.3.connection"})
        self.assertEqual(out[0]["extra_args"], "--model opus")

    def test_ui_cannot_set_command_but_keeps_existing(self):
        e = {}
        existing = [{"id": "x", "command": "my-agent {prompt_file}"}]
        out = agents.clean_agents([{"name": "x", "kind": "custom", "connection": "local", "workspace_root": "/w", "command": "evil"}], set(), existing, e)
        self.assertEqual(out[0]["command"], "my-agent {prompt_file}")
        out = agents.clean_agents([{"name": "y", "kind": "custom", "connection": "local", "workspace_root": "/w", "command": "evil"}], set(), existing, e)
        self.assertNotIn("command", out[0])

    def test_agent_dir(self):
        for ok in ("", "repo", "group/repo", "a.b_c-1"):
            self.assertTrue(agents.valid_agent_dir(ok), ok)
        for bad in ("../x", "/abs", "a/../b", "a b", "a;b", "x/"):
            self.assertFalse(agents.valid_agent_dir(bad), bad)

    def test_prompt_never_in_command_line(self):
        a = {"kind": "claude", "extra_args": "--model opus"}
        line = agents.remote_cmdline(a)
        self.assertIn('"$(cat "$R/$ID.prompt")"', line)
        self.assertIn("--model opus", line)
        self.assertNotIn("PROMPT", line)

    def test_ssh_args_have_no_shell_and_strict_keys(self):
        a = agents.ssh_args({"host": "h", "user": "u", "port": 2200, "identity_file": "", "host_key": "strict"})
        self.assertIn("BatchMode=yes", a)
        self.assertIn("StrictHostKeyChecking=yes", a)
        self.assertEqual(a[-2:], ["--", "u@h"])
        b = agents.ssh_args({"host": "h", "user": "", "port": 22, "identity_file": "~/k", "host_key": "accept-new"})
        self.assertIn("StrictHostKeyChecking=accept-new", b)
        self.assertIn("IdentitiesOnly=yes", b)

    def test_friendly_errors(self):
        c = {"host": "h"}
        self.assertIn("Host-Schlüssel", agents._friendly("Host key verification failed.", c))
        self.assertIn("abgelehnt", agents._friendly("Permission denied (publickey).", c))
        self.assertIn("auflösen", agents._friendly("ssh: Could not resolve hostname h", c))


class Gate(unittest.TestCase):
    def test_cloud_agent_needs_project_opt_in(self):
        env = Env(self)
        svc = service(env, cfg(env, kind="claude", allow=False))
        rid = svc.assign("a1", "T-1", 7, "b", "t")
        with self.assertRaises(agents.AgentError) as cm:
            svc.start(rid, "mach was")
        self.assertIn("nicht für Cloud-Agenten freigegeben", str(cm.exception))
        self.assertEqual(svc.store.agent_run(rid)["status"], "zugewiesen")
        self.assertFalse(env.log.exists(), "ohne Freigabe darf nicht einmal SSH aufgerufen werden")
        info = svc.prompt_info("a1", "T-1", 7, "b", "t", "T-1")
        self.assertFalse(info["allowed"])
        self.assertTrue(info["cloud"])

    def test_local_custom_agent_is_not_cloud(self):
        env = Env(self)
        svc = service(env, cfg(env, kind="custom", command="true", cloud=False, allow=False))
        self.assertTrue(svc.allowed(svc.agent("a1"), 7)[0])

    def test_duplicate_assign_and_unknown(self):
        env = Env(self)
        svc = service(env, cfg(env))
        svc.assign("a1", "T-1", 7, "", "t")
        with self.assertRaises(agents.AgentError):
            svc.assign("a1", "T-1", 7, "", "t")
        with self.assertRaises(agents.AgentError):
            svc.assign("zzz", "T-2", 7, "", "t")
        with self.assertRaises(agents.AgentError):
            svc.assign("a1", "", 7, "", "t")


@unittest.skipUnless(HAVE_TMUX, "tmux nicht installiert")
class Remote(unittest.TestCase):
    def test_full_run_with_hostile_prompt(self):
        env = Env(self)
        env.fake("claude", 'echo "ARGS:$#"; echo "FIRST:$1"; echo "PROMPT:$2"; pwd; echo "my token glpat-abcdefghijklmnopqrstuvwx"\n')
        svc = service(env, cfg(env, kind="claude", extra="--model opus"))
        rid = svc.assign("a1", "T-1", 7, "feature/x", "Titel")
        hostile = "Hallo'; touch %s/pwned; echo '$(touch %s/pwned2)` \"\nEOF\nTINYOPS_EOF_0\n" % (env.d, env.d)
        svc.start(rid, hostile)
        self.assertTrue(wait_for(lambda: (svc.poll(force=True), svc.store.agent_run(rid)["status"] != "läuft")[1]), "Lauf endet nicht")
        r = svc.store.agent_run(rid)
        self.assertEqual(r["status"], "fertig", r)
        self.assertEqual(r["exit_code"], 0)
        self.assertFalse((env.d / "pwned").exists() or (env.d / "pwned2").exists(), "Prompt wurde als Shell-Code ausgeführt")
        out = svc.tail(rid)
        self.assertIn("ARGS:4", out)            # -p, <prompt>, --model, opus
        self.assertIn("FIRST:-p", out)
        self.assertIn("touch %s/pwned" % env.d, out)     # Prompt kam unverändert an
        self.assertIn(str(env.remote / "ws" / "repo"), out)   # im Projektordner gestartet
        self.assertNotIn("glpat-abcdefghijklmnopqrstuvwx", out, "Secret im Log nicht geschwärzt")
        self.assertIn("ssh -t -p 22 dev@devbox tmux attach -t tinyops-%d" % rid, svc.run_view(svc.store.agent_run(rid))["attach"])
        svc.remove(rid)
        self.assertIsNone(svc.store.agent_run(rid))
        self.assertEqual(list((env.remote / ".tinyops" / "runs").glob("%d.*" % rid)), [])

    def test_failing_agent_and_exit_code(self):
        env = Env(self)
        svc = service(env, cfg(env, command="echo boom; exit 3"))
        rid = svc.assign("a1", "T-1", 7, "", "t")
        svc.start(rid, "x")
        self.assertTrue(wait_for(lambda: (svc.poll(force=True), svc.store.agent_run(rid)["status"] != "läuft")[1]))
        r = svc.store.agent_run(rid)
        self.assertEqual((r["status"], r["exit_code"]), ("fehlgeschlagen", 3))
        self.assertIn("boom", svc.tail(rid))

    def test_custom_prompt_file(self):
        env = Env(self)
        svc = service(env, cfg(env, command='cat {prompt_file}; echo; echo done'))
        rid = svc.assign("a1", "T-1", 7, "", "t")
        svc.start(rid, "zeile eins\nzeile zwei")
        self.assertTrue(wait_for(lambda: (svc.poll(force=True), svc.store.agent_run(rid)["status"] != "läuft")[1]))
        self.assertIn("zeile zwei", svc.tail(rid))

    def test_stop_and_one_run_per_workdir(self):
        env = Env(self)
        svc = service(env, cfg(env, command="sleep 60"))
        r1 = svc.assign("a1", "T-1", 7, "", "t")
        svc.start(r1, "x")
        self.assertEqual(svc.store.agent_run(r1)["status"], "läuft")
        r2 = svc.assign("a1", "T-2", 7, "", "t")
        with self.assertRaises(agents.AgentError) as cm:
            svc.start(r2, "y")
        self.assertIn("läuft in", str(cm.exception))
        svc.poll(force=True)
        self.assertEqual(svc.store.agent_run(r1)["status"], "läuft")
        with self.assertRaises(agents.AgentError):
            svc.remove(r1)
        svc.stop(r1)
        self.assertEqual(svc.store.agent_run(r1)["status"], "abgebrochen")
        self.assertNotEqual(subprocess.run(["tmux", "has-session", "-t", "tinyops-%d" % r1], capture_output=True).returncode, 0)

    def test_time_limit_kills_remote_run(self):
        env = Env(self)
        c = cfg(env, command="sleep 300 & sleep 300; wait")
        c["agents"][0]["max_minutes"] = 1
        svc = service(env, c)
        rid = svc.assign("a1", "T-1", 7, "", "t")
        svc.start(rid, "x")
        svc.store.agent_run_update(rid, started=time.time() - 120)      # vor zwei Minuten gestartet
        svc.poll(force=True)
        r = svc.store.agent_run(rid)
        self.assertEqual(r["status"], "abgelaufen")
        self.assertIn("Zeitlimit von 1 min", r["note"])
        self.assertNotEqual(subprocess.run(["tmux", "has-session", "-t", "tinyops-%d" % rid], capture_output=True).returncode, 0)
        out = subprocess.run(["pgrep", "-f", "sleep 300"], capture_output=True, text=True).stdout.split()
        self.assertEqual(out, [], "Prozesse des Agenten laufen nach dem Zeitlimit weiter")

    def test_missing_workspace_and_ssh_failure(self):
        env = Env(self)
        c = cfg(env, command="true")
        c["agents"][0]["workspace_root"] = str(env.remote / "nope")
        svc = service(env, c)
        rid = svc.assign("a1", "T-1", 7, "", "t")
        with self.assertRaises(agents.AgentError) as cm:
            svc.start(rid, "x")
        self.assertIn("gibt es auf dem Zielhost nicht", str(cm.exception))
        self.assertEqual(svc.store.agent_run(rid)["status"], "fehlgeschlagen")
        svc2 = service(env, cfg(env, command="true"))
        os.environ["STUB_FAIL"] = "Host key verification failed."
        r2 = svc2.assign("a1", "T-9", 7, "", "t")
        with self.assertRaises(agents.AgentError) as cm:
            svc2.start(r2, "x")
        self.assertIn("Host-Schlüssel", str(cm.exception))

    def test_status_unreachable_keeps_running_with_note(self):
        env = Env(self)
        svc = service(env, cfg(env, command="sleep 30"))
        rid = svc.assign("a1", "T-1", 7, "", "t")
        svc.start(rid, "x")
        os.environ["STUB_FAIL"] = "ssh: connect to host devbox port 22: Connection timed out"
        svc.poll(force=True)
        r = svc.store.agent_run(rid)
        self.assertEqual(r["status"], "läuft")
        self.assertIn("Status unbekannt", r["note"])
        os.environ["STUB_FAIL"] = ""
        svc.poll(force=True)
        self.assertEqual(svc.store.agent_run(rid)["note"], "")
        svc.stop(rid)

    def test_lost_session(self):
        env = Env(self)
        svc = service(env, cfg(env, command="sleep 30"))
        rid = svc.assign("a1", "T-1", 7, "", "t")
        svc.start(rid, "x")
        subprocess.run(["tmux", "kill-server"], capture_output=True)
        svc.poll(force=True)
        r = svc.store.agent_run(rid)
        self.assertEqual(r["status"], "verloren")

    def test_probe(self):
        env = Env(self)
        env.fake("claude", "true\n")
        c = cfg(env, kind="claude")
        res = settings.test_agent({"connection": c["connections"][0], "agent": {"kind": "claude", "workspace_root": c["agents"][0]["workspace_root"]}}, {})
        self.assertTrue(res["ok"], res)
        self.assertEqual([s["status"] for s in res["steps"]], ["ok"] * 4)
        res = settings.test_agent({"connection": c["connections"][0], "agent": {"kind": "codex", "workspace_root": str(env.remote / "zzz")}}, {})
        st = {s["id"]: s["status"] for s in res["steps"]}
        self.assertEqual((st["ws"], st["bin"]), ("fail", "fail"))
        os.environ["STUB_FAIL"] = "Permission denied (publickey)."
        res = settings.test_agent({"connection": c["connections"][0], "agent": {"kind": "claude", "workspace_root": "/x"}}, {})
        self.assertFalse(res["ok"])
        self.assertIn("abgelehnt", res["steps"][0]["detail"])
        self.assertEqual([s["status"] for s in res["steps"][1:]], ["skip"] * 3)


class Local(unittest.TestCase):
    def test_local_run_and_stop(self):
        env = Env(self)
        ws = env.d / "lws"
        (ws / "repo").mkdir(parents=True)
        c = cfg(env, command="echo hi from $(basename $(pwd)); cat {prompt_file}", conn="local")
        c["agents"][0]["workspace_root"] = str(ws)
        svc = service(env, c)
        rid = svc.assign("a1", "T-1", 7, "", "t")
        svc.start(rid, "lokaler prompt")
        self.assertTrue(wait_for(lambda: (svc.poll(force=True), svc.store.agent_run(rid)["status"] != "läuft")[1]))
        self.assertEqual(svc.store.agent_run(rid)["status"], "fertig")
        out = svc.tail(rid)
        self.assertIn("hi from repo", out)
        self.assertIn("lokaler prompt", out)
        svc.remove(rid)
        self.assertEqual(list((env.d / "runs").glob("%d.*" % rid)), [])
        c["agents"][0]["command"] = "sleep 60"
        svc2 = service(env, c)
        r2 = svc2.assign("a1", "T-2", 7, "", "t")
        svc2.start(r2, "x")
        wait_for(lambda: (env.d / "runs" / ("%d.pid" % r2)).exists())
        svc2.stop(r2)
        self.assertEqual(svc2.store.agent_run(r2)["status"], "abgebrochen")
        pid = int((env.d / "runs" / ("%d.pid" % r2)).read_text())
        gone = wait_for(lambda: not Path("/proc/%d" % pid).exists() or "Z" in Path("/proc/%d/stat" % pid).read_text().split(")")[-1][:3])
        self.assertTrue(gone, "Kindprozess läuft nach «Stoppen» weiter")

    def test_local_time_limit(self):
        env = Env(self)
        ws = env.d / "lws"
        (ws / "repo").mkdir(parents=True)
        c = cfg(env, command="sleep 300", conn="local")
        c["agents"][0].update(workspace_root=str(ws), max_minutes=1)
        svc = service(env, c)
        rid = svc.assign("a1", "T-1", 7, "", "t")
        svc.start(rid, "x")
        wait_for(lambda: (env.d / "runs" / ("%d.pid" % rid)).exists())
        pid = int((env.d / "runs" / ("%d.pid" % rid)).read_text())
        svc.store.agent_run_update(rid, started=time.time() - 61)
        svc.poll(force=True)
        self.assertEqual(svc.store.agent_run(rid)["status"], "abgelaufen")
        gone = wait_for(lambda: not Path("/proc/%d" % pid).exists() or "Z" in Path("/proc/%d/stat" % pid).read_text().split(")")[-1][:3])
        self.assertTrue(gone)

    def test_max_minutes_validation(self):
        e = {}
        out = agents.clean_agents([{"name": "a", "kind": "claude", "connection": "local", "workspace_root": "/w"},
                                   {"name": "b", "kind": "claude", "connection": "local", "workspace_root": "/w", "max_minutes": "0"},
                                   {"name": "c", "kind": "claude", "connection": "local", "workspace_root": "/w", "max_minutes": "5000"}], set(), [], e)
        self.assertEqual([a["max_minutes"] for a in out], [60, 0, 60])
        self.assertIn("agents.2.max_minutes", e)

    def test_local_missing_dir_and_binary(self):
        env = Env(self)
        c = cfg(env, kind="claude", conn="local")
        c["agents"][0]["workspace_root"] = str(env.d / "none")
        svc = service(env, c)
        rid = svc.assign("a1", "T-1", 7, "", "t")
        with self.assertRaises(agents.AgentError):
            svc.start(rid, "x")
        (env.d / "none" / "repo").mkdir(parents=True)
        old = os.environ["PATH"]
        os.environ["PATH"] = "/nonexistent"
        try:
            r2 = svc.assign("a1", "T-2", 7, "", "t")
            with self.assertRaises(agents.AgentError) as cm:
                svc.start(r2, "x")
            self.assertIn("nicht gefunden", str(cm.exception))
        finally:
            os.environ["PATH"] = old


@unittest.skipUnless(HAVE_TMUX, "tmux nicht installiert")
class AppApi(unittest.TestCase):
    def test_actions_through_app_and_overview(self):
        env = Env(self)
        c = server.load_config(None)
        c["data_dir"] = str(env.d / "data")
        c.update(cfg(env, command="echo hallo; sleep 1"))
        c["projects"] = [{"id": 1, "name": "dlp-core", "allow_cloud_agents": True}]
        (env.remote / "ws" / "dlp-core").mkdir()
        app = server.App(c, True, {}, Path("/nonexistent/c.json"))
        ov = app.overview()
        self.assertTrue(ov["agents"]["enabled"])
        self.assertEqual(ov["agents"]["projects"], [{"id": 1, "name": "dlp-core"}])
        info = app.agent_action("prompt", {"agent": "a1", "ticket": "DLP-1", "project_id": 1, "branch": "b", "title": "Titel", "key": "DLP-1"})
        self.assertTrue(info["allowed"])
        self.assertIn("DLP-1", info["prompt"])
        self.assertTrue(info["workdir"].endswith("/ws/dlp-core"))
        rid = app.agent_action("assign", {"agent": "a1", "ticket": "DLP-1", "project_id": 1, "branch": "b", "title": "Titel"})["id"]
        app.agent_action("start", {"run": rid, "prompt": info["prompt"], "project_id": 1})
        self.assertTrue(wait_for(lambda: (app.agents.poll(force=True), app.store.agent_run(rid)["status"] == "fertig")[1]))
        self.assertIn("hallo", app.agent_action("tail", {"run": rid})["text"])
        v = app.overview()["agents"]["runs"][0]
        self.assertEqual((v["ticket"], v["status"], v["where"]), ("DLP-1", "fertig", "box"))
        with self.assertRaises(server.UserError):
            app.agent_action("start", {"run": "x", "prompt": "p"})
        with self.assertRaises(server.UserError):
            app.agent_action("nope", {})
        # Sperre ohne Freigabe
        app.cfg["projects"][0].pop("allow_cloud_agents")
        app.cfg["agents"][0]["cloud"] = True
        r2 = app.agent_action("assign", {"agent": "a1", "ticket": "DLP-2", "project_id": 1, "branch": "", "title": "t"})["id"]
        with self.assertRaises(server.UserError) as cm:
            app.agent_action("start", {"run": r2, "prompt": "p", "project_id": 1})
        self.assertIn("Cloud-Agenten", str(cm.exception))

    def test_agents_route_not_gated_by_testenv(self):
        src = (ROOT / "server.py").read_text()
        self.assertIn('path == "/api/agent" or path.startswith(("/api/jobs"', src)


class Config(unittest.TestCase):
    def test_build_config_roundtrip_and_cloud_flag(self):
        cur = {"projects": [{"id": 7, "name": "repo"}], "agents": [{"id": "x", "name": "x", "kind": "custom", "connection": "local", "workspace_root": "/w", "command": "run {prompt_file}"}],
               "connections": []}
        body = {"gitlab": {"url": ""}, "projects": [{"id": 7, "name": "repo", "agent_dir": "grp/repo", "allow_cloud_agents": True}],
                "connections": [{"name": "box", "host": "h", "user": "u"}],
                "agents": [{"name": "x", "kind": "custom", "connection": "box", "workspace_root": "/srv", "command": "evil"},
                           {"name": "c", "kind": "claude", "connection": "local", "workspace_root": "/w"}]}
        new, errors = settings.build_config(cur, body)
        self.assertEqual(errors, {})
        self.assertEqual(new["projects"][0]["agent_dir"], "grp/repo")
        self.assertTrue(new["projects"][0]["allow_cloud_agents"])
        self.assertEqual(new["agents"][0]["command"], "run {prompt_file}")
        body["projects"][0]["allow_cloud_agents"] = False
        body["projects"][0]["agent_dir"] = ""
        new2, _ = settings.build_config(new, body)
        self.assertNotIn("allow_cloud_agents", new2["projects"][0])
        self.assertNotIn("agent_dir", new2["projects"][0])
        bad = dict(body, projects=[{"id": 7, "name": "repo", "agent_dir": "../etc"}])
        _, errors = settings.build_config(cur, bad)
        self.assertIn("projects", errors)

    def test_view_hides_command(self):
        v = settings.view({"agents": [{"id": "x", "name": "x", "kind": "custom", "connection": "local", "workspace_root": "/w", "command": "secret-cmd"}],
                           "projects": [], "connections": []}, "/x")
        self.assertNotIn("secret-cmd", json.dumps(v["agents"]))
        self.assertTrue(v["agents"][0]["has_command"])


if __name__ == "__main__":
    unittest.main()
