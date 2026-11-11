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
GIT = ["git", "-c", "user.name=T", "-c", "user.email=t@x", "-c", "init.defaultBranch=main"]


def git_repo(path, files=None):
    """Ein kleines Repository mit einem Commit (Agenten arbeiten ab 0.16 in einem Worktree davon)."""
    path = Path(path)
    path.mkdir(parents=True, exist_ok=True)
    for name, text in (files or {"README.md": "hallo\n"}).items():
        f = path / name
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(text)
    subprocess.run(GIT + ["init", "-q"], cwd=path, check=True)
    subprocess.run(GIT + ["add", "-A"], cwd=path, check=True)
    subprocess.run(GIT + ["commit", "-qm", "init"], cwd=path, check=True)
    return path


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
        git_repo(self.remote / "ws" / "repo")
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
        with self.assertRaises(agents.AgentError) as cm:          # ab 0.16 schon beim Zuweisen gesperrt
            svc.assign("a1", "T-1", 7, "b", "t")
        self.assertIn("restricted", str(cm.exception))
        rid = svc.store.agent_run_add("a1", "T-1", 7, "b", "t")     # z. B. vor 0.16 zugewiesen
        with self.assertRaises(agents.AgentError):
            svc.start(rid, "mach was")
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
        self.assertIn("ARGS:7", out)            # -p, <prompt>, --output-format stream-json --verbose (0.28), --model, opus
        self.assertIn("FIRST:-p", out)
        self.assertIn("touch %s/pwned" % env.d, out)     # Prompt kam unverändert an
        self.assertIn(str(env.remote / "ws" / ".tinyops-wt" / str(rid)), out)   # im eigenen Worktree gestartet
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
        c = cfg(env, command="sleep 60")
        c["agents"][0]["isolation"] = "shared"          # nur der alte gemeinsame Ordner sperrt sich selbst
        svc = service(env, c)
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
        self.assertIn("gibt es nicht", str(cm.exception))
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
        st = {s["id"]: s["status"] for s in res["steps"]}
        self.assertEqual([st[k] for k in ("conn", "tmux", "ws", "bin", "git")], ["ok"] * 5)
        self.assertIn(st["rights"], ("ok", "warn"))          # im Test-Container läuft alles als root: Warnung
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
        git_repo(ws / "repo")
        c = cfg(env, command="echo hi from $(basename $(pwd)); cat {prompt_file}", conn="local")
        c["agents"][0]["workspace_root"] = str(ws)
        svc = service(env, c)
        rid = svc.assign("a1", "T-1", 7, "", "t")
        svc.start(rid, "lokaler prompt")
        self.assertTrue(wait_for(lambda: (svc.poll(force=True), svc.store.agent_run(rid)["status"] != "läuft")[1]))
        self.assertEqual(svc.store.agent_run(rid)["status"], "fertig")
        out = svc.tail(rid)
        self.assertIn("hi from %d" % rid, out)          # im Worktree .tinyops-wt/<nr>
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
        git_repo(ws / "repo")
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
        c["agents"][0].update(workspace_root=str(env.d / "none"), isolation="shared")
        svc = service(env, c)
        rid = svc.assign("a1", "T-1", 7, "", "t")
        with self.assertRaises(agents.AgentError):
            svc.start(rid, "x")
        git_repo(env.d / "none" / "repo")
        old = os.environ["PATH"]
        os.environ["PATH"] = "/nonexistent"
        try:
            r2 = svc.assign("a1", "T-2", 7, "", "t")
            with self.assertRaises(agents.AgentError) as cm:
                svc.start(r2, "x")
            self.assertIn("nicht gefunden", str(cm.exception))
        finally:
            os.environ["PATH"] = old


def git_out(path, *args):
    return subprocess.run(GIT + list(args), cwd=path, capture_output=True, text=True).stdout


@unittest.skipUnless(HAVE_TMUX, "tmux nicht installiert")
class Isolation(unittest.TestCase):
    def test_worktree_runs_in_parallel_and_keep_main_checkout_clean(self):
        env = Env(self)
        repo = env.remote / "ws" / "repo"
        svc = service(env, cfg(env, command='echo neu > datei.txt; git add datei.txt; git -c user.name=A -c user.email=a@x commit -qm agent; echo dirty > offen.txt'))
        r1 = svc.assign("a1", "DLP-7", 7, "", "t")
        r2 = svc.assign("a1", "DLP-8", 7, "", "t")
        svc.start(r1, "x")
        svc.start(r2, "y")                                         # kein «läuft schon» mehr
        for rid in (r1, r2):
            self.assertTrue(wait_for(lambda: (svc.poll(force=True), svc.store.agent_run(rid)["status"] != "läuft")[1]))
            self.assertEqual(svc.store.agent_run(rid)["status"], "fertig")
        r = svc.store.agent_run(r1)
        self.assertEqual((r["mode"], r["out_branch"]), ("worktree", "agent/dlp-7-%d" % r1))
        self.assertTrue(r["wt"].endswith("/.tinyops-wt/%d" % r1))
        self.assertEqual(git_out(repo, "status", "--porcelain"), "")       # Hauptcheckout unberührt
        self.assertFalse((repo / "datei.txt").exists())
        self.assertIn("agent", git_out(repo, "log", "--oneline", "agent/dlp-7-%d" % r1))
        svc.remove(r1)                                                     # offene Datei wird gesichert, Worktree verschwindet
        self.assertFalse(Path(r["wt"]).exists())
        self.assertIn("gesichert", git_out(repo, "log", "--oneline", "agent/dlp-7-%d" % r1))
        self.assertIn("offen.txt", git_out(repo, "show", "--stat", "agent/dlp-7-%d" % r1))
        self.assertNotIn(r["wt"], git_out(repo, "worktree", "list"))

    def test_worktree_starts_from_ticket_branch(self):
        env = Env(self)
        repo = env.remote / "ws" / "repo"
        subprocess.run(GIT + ["switch", "-qc", "feature/DLP-9"], cwd=repo, check=True)
        (repo / "f.txt").write_text("feature\n")
        subprocess.run(GIT + ["add", "-A"], cwd=repo, check=True)
        subprocess.run(GIT + ["commit", "-qm", "feature"], cwd=repo, check=True)
        subprocess.run(GIT + ["switch", "-q", "main"], cwd=repo, check=True)
        svc = service(env, cfg(env, command="cat f.txt"))
        rid = svc.assign("a1", "DLP-9", 7, "feature/DLP-9", "t")
        svc.start(rid, "x")
        self.assertTrue(wait_for(lambda: (svc.poll(force=True), svc.store.agent_run(rid)["status"] != "läuft")[1]))
        self.assertIn("feature", svc.tail(rid))

    def test_restricted_blocks_cloud_but_allows_local(self):
        env = Env(self)
        c = cfg(env, kind="claude", allow=False)
        c["projects"][0]["data_class"] = "restricted"
        c["agents"].append({"id": "goose", "name": "goose", "kind": "goose", "connection": "box", "workspace_root": c["agents"][0]["workspace_root"],
                            "extra_args": "", "cloud": False, "model": "qwen2.5-coder:7b", "isolation": "worktree", "max_minutes": 60})
        svc = service(env, c)
        with self.assertRaises(agents.AgentError):
            svc.assign("a1", "T-1", 7, "", "t")
        self.assertTrue(svc.assign("goose", "T-1", 7, "", "t"))
        self.assertEqual(svc.prompt_info("goose", "T-1", 7, "", "t", "T-1")["data_class"], "restricted")

    def test_export_only_contains_allowed_paths_and_takeover(self):
        env = Env(self)
        repo = env.remote / "ws" / "repo"
        shutil.rmtree(repo)
        git_repo(repo, {"src/util/Strings.java": "class Strings {}\n", "src/core/Secret.java": "class Secret {}\n", "README.md": "x\n"})
        secret_blob = git_out(repo, "rev-parse", "HEAD:src/core/Secret.java").strip()
        c = cfg(env, command='ls -R; git log --oneline | wc -l; git cat-file -e %s && echo LEAK || echo NOLEAK; '
                             'echo "class StringsTest {}" > src/util/StringsTest.java' % secret_blob)
        c["projects"][0].update(data_class="internal", cloud_paths=["src/util"])
        svc = service(env, c)
        rid = svc.assign("a1", "DLP-11", 7, "", "t")
        info = svc.prompt_info("a1", "DLP-11", 7, "", "t", "DLP-11")
        self.assertEqual((info["mode"], info["cloud_paths"]), ("export", ["src/util"]))
        svc.start(rid, "Tests schreiben")
        self.assertTrue(wait_for(lambda: (svc.poll(force=True), svc.store.agent_run(rid)["status"] != "läuft")[1]))
        out = svc.tail(rid)
        self.assertIn("Strings.java", out)
        self.assertNotIn("Secret.java", out)
        self.assertNotIn("README.md", out)
        self.assertIn("NOLEAK", out)                       # die Objekte des echten Repos sind nicht erreichbar
        with self.assertRaises(agents.AgentError):         # nicht übernommene Änderungen schützen
            svc.remove(rid)
        res = svc.takeover(rid)
        self.assertEqual(res["files"], ["src/util/StringsTest.java"])
        b = res["branch"]
        self.assertEqual(b, "agent/dlp-11-%d" % rid)
        self.assertIn("StringsTest.java", git_out(repo, "show", "--stat", b))
        self.assertEqual(git_out(repo, "status", "--porcelain"), "")
        with self.assertRaises(agents.AgentError):
            svc.takeover(rid)
        svc.remove(rid)
        self.assertFalse(Path(svc.store.agent_run(rid) or {}).exists() if False else (env.remote / "ws" / ".tinyops-wt" / str(rid)).exists())

    def test_takeover_refuses_changes_outside_allowed_paths(self):
        env = Env(self)
        repo = env.remote / "ws" / "repo"
        shutil.rmtree(repo)
        git_repo(repo, {"src/util/A.java": "a\n", "pom.xml": "<p/>\n"})
        c = cfg(env, command='mkdir -p src/core; echo x > src/core/Evil.java; echo y >> src/util/A.java')
        c["projects"][0].update(data_class="internal", cloud_paths=["src/util"])
        svc = service(env, c)
        rid = svc.assign("a1", "DLP-12", 7, "", "t")
        svc.start(rid, "x")
        self.assertTrue(wait_for(lambda: (svc.poll(force=True), svc.store.agent_run(rid)["status"] != "läuft")[1]))
        with self.assertRaises(agents.AgentError) as cm:
            svc.takeover(rid)
        self.assertIn("src/core/Evil.java", str(cm.exception))
        self.assertNotIn("agent/dlp-12", git_out(repo, "branch"))
        svc.remove(rid, force=True)

    def test_paths_and_class_helpers(self):
        self.assertEqual(agents.clean_paths("src/util, src/main/java/ch/x/ "), (["src/util", "src/main/java/ch/x"], ""))
        self.assertTrue(agents.clean_paths("../etc")[1])
        self.assertTrue(agents.clean_paths("-rf")[1])
        self.assertTrue(agents.path_allowed("src/util/A.java", ["src/util"]))
        self.assertFalse(agents.path_allowed("src/utility/A.java", ["src/util"]))
        self.assertEqual(agents.data_class({}), "restricted")
        self.assertEqual(agents.data_class({"allow_cloud_agents": True}), "internal")
        self.assertEqual(agents.data_class({"data_class": "public", "allow_cloud_agents": False}), "public")

    def test_local_kinds_cmdline(self):
        g = agents.remote_cmdline({"kind": "goose", "model": "qwen2.5-coder:32b", "extra_args": ""})
        self.assertEqual(g, 'GOOSE_PROVIDER=ollama GOOSE_MODEL=qwen2.5-coder:32b goose run -i "$R/$ID.prompt"')
        o = agents.remote_cmdline({"kind": "opencode", "model": "qwen2.5-coder:32b", "extra_args": ""})
        self.assertEqual(o, 'opencode run --model ollama/qwen2.5-coder:32b "$(cat "$R/$ID.prompt")"')
        e = {}
        out = agents.clean_agents([{"name": "g", "kind": "goose", "connection": "local", "workspace_root": "/w", "model": "qwen2.5-coder:32b", "cloud": True},
                                   {"name": "o", "kind": "opencode", "connection": "local", "workspace_root": "/w"},
                                   {"name": "c", "kind": "claude", "connection": "local", "workspace_root": "/w", "cloud": False}], set(), [], e)
        self.assertEqual([a["cloud"] for a in out], [True, False, True])        # Claude bleibt immer Cloud
        self.assertIn("agents.1.model", e)


@unittest.skipUnless(HAVE_TMUX, "tmux nicht installiert")
class AppApi(unittest.TestCase):
    def test_actions_through_app_and_overview(self):
        env = Env(self)
        c = server.load_config(None)
        c["data_dir"] = str(env.d / "data")
        c.update(cfg(env, command="echo hallo; sleep 1"))
        c["projects"] = [{"id": 1, "name": "dlp-core", "allow_cloud_agents": True}]
        git_repo(env.remote / "ws" / "dlp-core")
        app = server.App(c, True, {}, Path("/nonexistent/c.json"))
        ov = app.overview()
        self.assertTrue(ov["agents"]["enabled"])
        self.assertEqual(ov["agents"]["projects"], [{"id": 1, "name": "dlp-core", "data_class": "internal"}])
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
        with self.assertRaises(server.UserError) as cm:
            app.agent_action("assign", {"agent": "a1", "ticket": "DLP-2", "project_id": 1, "branch": "", "title": "t"})
        self.assertIn("restricted", str(cm.exception))

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
        self.assertEqual(new["projects"][0]["data_class"], "internal")      # alte Freigabe → internal
        self.assertNotIn("allow_cloud_agents", new["projects"][0])
        self.assertEqual(new["agents"][0]["command"], "run {prompt_file}")
        body["projects"][0] = {"id": 7, "name": "repo", "agent_dir": "", "data_class": "restricted", "cloud_paths": ["src/util"]}
        new2, _ = settings.build_config(new, body)
        self.assertEqual(new2["projects"][0]["data_class"], "restricted")
        self.assertNotIn("cloud_paths", new2["projects"][0])          # Pfade gelten nur bei internal
        body["projects"][0].update(data_class="internal", cloud_paths="src/util, src/main/java/ch/x")
        new3, errors = settings.build_config(new, body)
        self.assertEqual(new3["projects"][0]["cloud_paths"], ["src/util", "src/main/java/ch/x"])
        body["projects"][0].update(cloud_paths="../etc")
        _, errors = settings.build_config(new, body)
        self.assertIn("projects", errors)
        self.assertEqual(settings.view(new3, "/x")["projects"][0]["data_class"], "internal")
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


ASK_CMD = ('ans=$(tinyops-ask -t 30 "Retry mit Backoff oder fix?" "Backoff" "fix"); echo "got:$ans"; '
           'tinyops-check sh -c "exit 0"; tinyops-check sh -c "exit 4"; echo "# Bericht\\n- Backoff eingebaut" | tinyops-report')


class Questions(unittest.TestCase):
    """0.18: Der Agent fragt (tinyops-ask), bekommt die Antwort, läuft weiter; Bericht und Belege landen im Lauf."""

    def run_case(self, conn):
        env = Env(self)
        c = cfg(env, command=ASK_CMD, conn=conn)
        if conn == "local":
            ws = env.d / "lws"
            git_repo(ws / "repo")
            c["agents"][0]["workspace_root"] = str(ws)
        svc = service(env, c)
        events = []
        svc.audit = lambda action, target="", ok=True, actor="du", **d: events.append((action, actor, d))
        rid = svc.assign("a1", "DLP-1", 7, "", "t")
        svc.start(rid, "Mach es")
        q = wait_for(lambda: (svc.poll(force=True), svc.run_view(svc.store.agent_run(rid))["question"])[1])
        self.assertTrue(q, svc.tail(rid))
        self.assertEqual((q["id"], q["question"], q["options"], q["blocking"]), (1, "Retry mit Backoff oder fix?", ["Backoff", "fix"], True))
        for _ in range(3):                                  # mehrmals abfragen: die Frage zählt einmal
            svc.poll(force=True)
        self.assertEqual([e[0] for e in events].count("agent.question"), 1)
        # Ablauf: «Agent fragt» steht als nächster Schritt da
        import flow
        d = flow.derive({"id": "DLP-1", "key": "DLP-1", "items": [], "stage": "impl"}, [svc.run_view(svc.store.agent_run(rid))])
        self.assertEqual((d["next"]["id"], d["next"]["kind"], d["next"]["action"]["qid"]), ("agent_question", "do", 1))
        with self.assertRaises(agents.AgentError):
            svc.answer(rid, 2, "falsche Nummer")
        svc.answer(rid, 1, "Backoff")
        self.assertIsNone(svc.run_view(svc.store.agent_run(rid))["question"])
        with self.assertRaises(agents.AgentError):
            svc.answer(rid, 1, "doppelt")
        self.assertTrue(wait_for(lambda: (svc.poll(force=True), svc.store.agent_run(rid)["status"] != "läuft")[1]))
        v = svc.run_view(svc.store.agent_run(rid))
        self.assertEqual(v["status"], "fertig", svc.tail(rid))
        self.assertIn("got:Backoff", svc.tail(rid))
        self.assertEqual([x["exit"] for x in v["checks"]], [0, 4])
        self.assertFalse(v["checks_ok"])
        self.assertIn("Backoff eingebaut", v["summary"])
        self.assertEqual(v["qa"][0]["a"], "Backoff")
        self.assertEqual([e[0] for e in events], ["agent.assign", "agent.start", "agent.question", "agent.answer", "agent.finish"])
        self.assertEqual(events[2][1], "agent")
        d = flow.derive({"id": "DLP-1", "key": "DLP-1", "items": [], "stage": "impl"}, [v])
        self.assertEqual(d["next"]["id"], "agent_result")
        self.assertIn("2 Belege, 1 mit Fehler", d["next"]["why"])
        svc.ack(rid)
        self.assertTrue(svc.run_view(svc.store.agent_run(rid))["ack"])
        return svc, rid

    @unittest.skipUnless(HAVE_TMUX, "tmux nicht installiert")
    def test_remote_question_answer_report(self):
        self.run_case("box")

    def test_local_question_answer_report(self):
        svc, rid = self.run_case("local")
        self.assertTrue((svc.run_dir / "bin" / "tinyops-ask").exists())

    def test_ask_timeout_and_rewait(self):
        d = Path(tempfile.mkdtemp())
        agents.write_helpers(d)
        env = dict(os.environ, TINYOPS_RUN_DIR=str(d), TINYOPS_RUN_ID="9", PATH=str(d / "bin") + os.pathsep + os.environ["PATH"])
        r = subprocess.run(["tinyops-ask", "-t", "2", "Frage?"], env=env, capture_output=True, text=True, timeout=20)
        self.assertEqual(r.returncode, 3)
        self.assertIn("--wait 1", r.stderr)
        (d / "9.answer.1").write_text("ja\n")
        r = subprocess.run(["tinyops-ask", "--wait", "1", "-t", "2"], env=env, capture_output=True, text=True, timeout=20)
        self.assertEqual((r.returncode, r.stdout.strip()), (0, "ja"))
        self.assertEqual(json.loads((d / "9.question.json").read_text())["id"], 1)
        r = subprocess.run(["tinyops-ask", "x"], env=dict(env, TINYOPS_RUN_ID=""), capture_output=True, text=True)
        self.assertEqual(r.returncode, 2)

    def test_parse_question_and_checks(self):
        self.assertEqual(agents.parse_question("kein json")["question"], "kein json")
        self.assertIsNone(agents.parse_question(" "))
        q = agents.parse_question('{"id": 3, "question": "x", "options": ["a", "", "b"], "blocking": false}')
        self.assertEqual((q["id"], q["options"], q["blocking"]), (3, ["a", "b"], False))
        c = agents.parse_checks('{"cmd": "mvn test", "exit": 0, "secs": 3, "ts": 1}\nmüll\n{"cmd": "x"}')
        self.assertEqual(c, [{"cmd": "mvn test", "exit": 0, "secs": 3, "ts": 1}])

    def test_prompt_mentions_tools(self):
        env = Env(self)
        svc = service(env, cfg(env, command="true"))
        p = svc.prompt_info("a1", "DLP-1", 7, "b", "T", "DLP-1")["prompt"]
        for w in ("tinyops-ask", "tinyops-check", "tinyops-report"):
            self.assertIn(w, p)
