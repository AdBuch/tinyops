"""0.27: Geheimnis-Scan, Anbieter/Modell für Goose, Projekt-Zugriff und Klonen beim Agenten, Vorprüfung, Fokus-Sitzung endet von selbst, Hilfe."""
import os
import re
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import agents  # noqa: E402
import briefing  # noqa: E402
import secretscan  # noqa: E402
import server  # noqa: E402
import workspaces  # noqa: E402
from test_agents import Env, cfg, git_repo, service, wait_for  # noqa: E402


def git(d, *a):
    return subprocess.run(["git", "-C", str(d), "-c", "user.name=T", "-c", "user.email=t@x"] + list(a), capture_output=True, text=True, check=True).stdout


DIFF = '''commit:abc1234
diff --git a/app.py b/app.py
--- a/app.py
+++ b/app.py
@@ -1,0 +2,10 @@
+password = "hunter2hunter2"
+password = os.environ["PW"]
+token = get_token()
+API_KEY = "changeme"
+url = "https://user:Sup3rGeheim@db.intern/x"
+key = "glpat-abcdefghijklmnopqrstu"
+x = 1
+secret: ${SECRET}
+db_password=Xk29_fjq8Lz   # tinyops:allow-secret
+-----BEGIN OPENSSH PRIVATE KEY-----
-old_password = "wegwegwegweg1"
 context_secret = "bleibtbleibt1"
+++ b/package-lock.json
@@ -0,0 +1 @@
+"token": "abcdefghijklmnopqrstuvwxyz123"
'''


class Scan(unittest.TestCase):
    def test_rules_lines_and_exceptions(self):
        f = secretscan.scan_diff(DIFF)
        self.assertEqual([(x["line"], x["rule"]) for x in f], [(2, "Passwort oder Token im Klartext"), (6, "Zugangsdaten in URL"), (7, "GitLab-Token"), (11, "Privater Schlüssel")])
        self.assertTrue(all(x["where"] == "Commit abc1234" and x["file"] == "app.py" for x in f))
        for x in f:                                      # der Wert selbst steht nirgends
            for bad in ("hunter2", "Sup3r", "glpat-abc"):
                self.assertNotIn(bad, str(x))
        self.assertIn("4 mögliche Geheimnisse in app.py", secretscan.summary(f))
        self.assertEqual(secretscan.scan_diff(""), [])
        self.assertEqual(secretscan.summary([]), "")

    def test_more_tokens(self):
        for line, rule in (('aws = "AKIAABCDEFGHIJKLMNOP"', "AWS-Zugangsschlüssel"), ("k = sk-ant-abcdefghijklmnopqrstuvwxyz0123", "API-Schlüssel (sk-…)"),
                           ("Authorization: Bearer abcdefghijklmnopqrstuvwxyz", "Bearer-Token"), ("t=ghp_abcdefghijklmnopqrstuvwxyz0123456789", "GitHub-Token"),
                           ("spring.datasource.password=Xk29_fjq8Lz", "Passwort oder Token im Klartext")):
            self.assertEqual((secretscan.check_line(line) or [None])[0], rule, line)
        for line in ("password = input()", "token: str = None", "password_field = PasswordField", "api_key = settings.API_KEY",
                     'password = "<dein-passwort>"', "max_tokens = 4096", "tokenizer = Tokenizer.load(path)"):
            self.assertIsNone(secretscan.check_line(line), line)


class WsSecrets(unittest.TestCase):
    def test_unpushed_and_uncommitted_only(self):
        d = Path(tempfile.mkdtemp())
        bare, repo = d / "origin.git", d / "repo"
        subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(bare)], check=True)
        git_repo(repo)
        git(repo, "remote", "add", "origin", str(bare))
        (repo / "old.py").write_text('password = "schon-gepusht-123"\n')
        git(repo, "add", "-A")
        git(repo, "commit", "-qm", "alt")
        git(repo, "push", "-q", "-u", "origin", "HEAD")
        self.assertEqual(workspaces.inspect(repo)["secrets"], [])                       # Gepushtes ist nicht mehr Thema dieses Scans
        (repo / "conf.py").write_text('x = 1\napi_key = "Zx81kq0PlmN7vv"\n')
        git(repo, "add", "-A")
        git(repo, "commit", "-qm", "neu")
        (repo / "old.py").write_text('password = "schon-gepusht-123"\ntoken = "glpat-abcdefghijklmnopqrstu"\n')
        info = workspaces.inspect(repo)
        self.assertEqual(sorted((s["file"], s["line"], s["where"][:6]) for s in info["secrets"]), [("conf.py", 2, "Commit"), ("old.py", 2, "nicht ")])
        self.assertEqual(info["secret_count"], 2)
        t = workspaces.totals({"repos": [info]})
        self.assertEqual((t["secrets"], t["secret_repos"]), (2, ["repo"]))
        src = (ROOT / "workspaces.py").read_text(encoding="utf-8")
        self.assertNotIn('"push"', src)


class Goose(unittest.TestCase):
    def test_provider_and_model(self):
        line = lambda **a: agents.remote_cmdline(dict({"kind": "goose"}, **a))
        self.assertEqual(line(model="qwen3-coder"), 'GOOSE_PROVIDER=ollama GOOSE_MODEL=qwen3-coder goose run -i "$R/$ID.prompt"')     # alter Eintrag ohne Anbieter
        self.assertEqual(line(model="qwen-lokal", provider=""), 'GOOSE_MODEL=qwen-lokal goose run -i "$R/$ID.prompt"')
        self.assertEqual(line(model="", provider=""), 'goose run -i "$R/$ID.prompt"')
        self.assertEqual(line(model="q", provider="litellm"), 'GOOSE_PROVIDER=litellm GOOSE_MODEL=q goose run -i "$R/$ID.prompt"')
        self.assertIn("--model litellm/q ", agents.remote_cmdline({"kind": "opencode", "model": "q", "provider": "litellm"}))
        self.assertEqual(agents.agent_env({"kind": "claude"}), {})

    def test_clean_agents(self):
        e = {}
        out = agents.clean_agents([{"name": "qwen", "kind": "goose", "connection": "local", "workspace_root": "/w", "model": "qwen-lokal", "provider": ""},
                                   {"name": "g2", "kind": "goose", "connection": "local", "workspace_root": "/w", "model": "", "provider": ""},
                                   {"name": "g3", "kind": "goose", "connection": "local", "workspace_root": "/w", "model": "", "provider": "litellm"},
                                   {"name": "g4", "kind": "goose", "connection": "local", "workspace_root": "/w", "model": "m", "provider": "Li te"},
                                   {"name": "g5", "kind": "goose", "connection": "local", "workspace_root": "/w", "model": "m", "clone_via": "https", "cloud": True},
                                   {"name": "c", "kind": "claude", "connection": "local", "workspace_root": "/w", "clone_via": "ftp"}], set(), [], e)
        self.assertEqual(set(e), {"agents.2.model", "agents.3.provider"})
        self.assertEqual((out[0]["provider"], out[0]["model"], out[0]["cloud"], out[0]["clone_via"]), ("", "qwen-lokal", False, "ssh"))
        self.assertEqual((out[4]["provider"], out[4]["clone_via"], out[4]["cloud"]), ("ollama", "https", True))
        self.assertEqual((out[5]["clone_via"], "provider" in out[5]), ("ssh", False))

    def test_cloud_looking_model_never_on_restricted(self):
        self.assertEqual([m for m in ("claude-sonnet-4", "gpt-oss:20b", "gpt-4o", "qwen3-coder:30b", "litellm/o3-mini", "anthropic/claude", "mistral-small", "devstral", "llama3", "")
                          if agents.looks_cloud(m)], ["claude-sonnet-4", "gpt-4o", "litellm/o3-mini", "anthropic/claude"])
        env = Env(self)
        c = cfg(env, conn="local", allow=False)
        c["projects"][0]["data_class"] = "restricted"
        c["agents"][0].update(kind="goose", cloud=False, model="qwen-lokal", provider="")
        svc = service(env, c)
        self.assertEqual(svc.allowed(svc.agent("a1"), 7), (True, ""))
        svc.cfg["agents"][0]["model"] = "claude-sonnet-4"
        ok, why = svc.allowed(svc.agent("a1"), 7)
        self.assertFalse(ok)
        self.assertIn("sieht nach einem Cloud-Modell aus", why)
        self.assertIn("sieht nach einem Cloud-Modell aus", svc.prompt_info("a1", "T-1", 7, "", "t", "T-1")["hints"][0])
        svc.cfg["projects"][0]["data_class"] = "internal"
        self.assertTrue(svc.allowed(svc.agent("a1"), 7)[0])
        svc.cfg["agents"][0].update(cloud=True, model="qwen-lokal")
        svc.cfg["projects"][0]["data_class"] = "restricted"
        self.assertFalse(svc.allowed(svc.agent("a1"), 7)[0])                             # als Cloud eingetragen: nie an restricted


class Access(unittest.TestCase):
    def setUp(self):
        self._re = agents.CLONE_URL_RE

    def tearDown(self):
        agents.CLONE_URL_RE = self._re

    def test_url_rule(self):
        for ok in ("git@gitlab.firma.ch:dlp/dlp-core.git", "https://gitlab.firma.ch/dlp/dlp-core.git", "ssh://git@gitlab.firma.ch:2222/dlp/core.git", "git@github.com:AdBuch/tinyops.git"):
            self.assertTrue(agents.CLONE_URL_RE.fullmatch(ok), ok)
        for bad in ("-oProxyCommand=evil", "file:///etc", "/srv/git/x.git", "https://user:pw@host/x.git", "ext::sh -c id", "git@host:x.git;id", "https://host/x y", "http://host/x.git", ""):
            self.assertFalse(agents.CLONE_URL_RE.fullmatch(bad), bad)

    def test_access_and_clone_local(self):
        env = Env(self)
        ws = env.d / "lws"
        git_repo(ws / "repo")
        src = env.d / "quelle"
        git_repo(src)
        c = cfg(env, conn="local")
        c["agents"][0]["workspace_root"] = str(ws)
        c["projects"] += [{"id": 8, "name": "fehlt", "allow_cloud_agents": True}, {"id": 9, "name": "ordner", "allow_cloud_agents": True},
                          {"id": 10, "name": "geheim", "data_class": "restricted"}]
        (ws / "ordner").mkdir()
        svc = service(env, c)
        events = []
        svc.audit = lambda action, target="", ok=True, actor="du", **d: events.append((action, ok, d))
        acc = svc.access("a1")
        self.assertEqual({k: v["state"] for k, v in acc.items()}, {7: "git", 8: "missing", 9: "dir", 10: "missing"})
        self.assertIs(svc.access("a1"), acc)                                             # kurz gemerkt
        with self.assertRaises(agents.AgentError):
            svc.clone("a1", 8, "/lokaler/pfad")                                          # nur https, ssh oder git@
        agents.CLONE_URL_RE = re.compile(r".+")                                          # im Test von einem lokalen Repo klonen
        for pid, msg in ((7, "liegt schon etwas"), (9, "liegt schon etwas"), (10, "restricted")):
            with self.assertRaises(agents.AgentError) as cm:
                svc.clone("a1", pid, str(src))
            self.assertIn(msg, str(cm.exception))
        self.assertEqual(svc.clone("a1", 8, str(src))["state"], "läuft")
        self.assertTrue(wait_for(lambda: svc.clone_state("a1", 8)["state"] != "läuft"))
        self.assertEqual(svc.clone_state("a1", 8)["state"], "fertig", svc.clone_state("a1", 8))
        self.assertTrue((ws / "fehlt" / ".git").exists())
        self.assertEqual(svc.access("a1")[8]["state"], "git")                            # der Merker wurde nach dem Klon verworfen
        acts = [(a, ok) for a, ok, _ in events]
        self.assertEqual(acts, [("agent.clone.start", True), ("agent.clone", True)])
        self.assertEqual(events[1][2]["path"], str(ws / "fehlt"))
        # Fehlschlag: Meldung bleibt, nichts bleibt liegen
        svc.cfg["projects"].append({"id": 11, "name": "kaputt", "allow_cloud_agents": True})
        svc.clone("a1", 11, str(env.d / "gibt-es-nicht"))
        self.assertTrue(wait_for(lambda: svc.clone_state("a1", 11)["state"] != "läuft"))
        st = svc.clone_state("a1", 11)
        self.assertEqual(st["state"], "fehler")
        self.assertTrue(st["msg"])
        self.assertFalse((ws / "kaputt").exists())
        self.assertEqual((events[-1][0], events[-1][1]), ("agent.clone", False))

    def test_access_and_clone_over_ssh(self):
        env = Env(self)
        ws = env.remote / "ws"                                  # dort liegt schon ws/repo
        src = env.d / "quelle"
        git_repo(src)
        c = cfg(env, conn="box")
        c["projects"].append({"id": 8, "name": "fehlt", "allow_cloud_agents": True})
        svc = service(env, c)
        self.assertEqual({k: v["state"] for k, v in svc.access("a1").items()}, {7: "git", 8: "missing"})
        agents.CLONE_URL_RE = re.compile(r".+")
        svc.clone("a1", 8, str(src))
        self.assertTrue(wait_for(lambda: svc.clone_state("a1", 8)["state"] != "läuft"))
        self.assertEqual(svc.clone_state("a1", 8)["state"], "fertig", svc.clone_state("a1", 8))
        self.assertTrue((ws / "fehlt" / ".git").exists())
        self.assertEqual(svc.access("a1")[8]["state"], "git")

    def test_clone_hint(self):
        self.assertIn("ssh -T git@gitlab.firma.ch", agents.clone_hint("Host key verification failed.", "git@gitlab.firma.ch:a/b.git"))
        self.assertIn("Deploy-Key", agents.clone_hint("git@gitlab.firma.ch: Permission denied (publickey).", "git@gitlab.firma.ch:a/b.git"))
        self.assertIn("credential helper", agents.clone_hint("fatal: could not read Username for 'https://x': terminal prompts disabled", "https://x/a/b.git"))


SECRET_WORK = ('printf \'api_key = "Zx81kq0PlmN7vv"\\n\' > conf.py && git add -A && git -c user.name=A -c user.email=a@x commit -qm "Konfig"; echo ok | tinyops-report')


class RunSecrets(unittest.TestCase):
    def test_result_lists_secret_and_prereview_brief(self):
        env = Env(self)
        ws = env.d / "lws"
        git_repo(ws / "repo")
        c = cfg(env, command=SECRET_WORK, conn="local")
        c["agents"][0]["workspace_root"] = str(ws)
        svc = service(env, c)
        rid = svc.assign("a1", "DLP-1", 7, "", "t")
        svc.start(rid, "Aufgabe\nAK1: Konfig da\n")
        self.assertTrue(wait_for(lambda: (svc.poll(force=True), svc.store.agent_run(rid)["status"] != "läuft")[1]))
        v = svc.run_view(svc.store.agent_run(rid))
        self.assertEqual([(s["file"], s["line"], s["rule"]) for s in v["result"]["secrets"]], [("conf.py", 1, "Passwort oder Token im Klartext")], svc.tail(rid))
        self.assertNotIn("Zx81kq", str(v["result"]["secrets"]))
        b = briefing.prereview(v)
        for w in ("Vorprüfung von Lauf %d" % rid, "git diff %s^ HEAD" % v["result"]["commits"][-1]["sha"], "AK1: Konfig da", "gemeldet: nicht gemeldet", "conf.py:1"):
            self.assertIn(w, b)
        info = svc.prompt_info("a1", "DLP-1", 7, v["out_branch"], "t", "DLP-1", template="agent-prereview", extra={"brief": b})
        self.assertIn("Du prüfst nur. Ändere keine Dateien", info["prompt"])
        self.assertEqual(len(briefing.parse_prompt(info["prompt"])), 1)


class ServerAccess(unittest.TestCase):
    def test_prompt_shows_access_clone_and_prereview(self):
        d = Path(tempfile.mkdtemp())
        git_repo(d / "ws" / "dlp-core")
        c = server.load_config(None)
        c.update(data_dir=str(d / "data"), projects=[{"id": 1, "name": "dlp-core", "data_class": "internal"}, {"id": 2, "name": "dlp-ui", "data_class": "internal"}], connections=[],
                 agents=[{"id": "a1", "name": "A1", "kind": "custom", "connection": "local", "workspace_root": str(d / "ws"), "cloud": False, "clone_via": "https",
                          "command": 'tinyops-ak 1 ok; echo fertig | tinyops-report'}])
        a = server.App(c, True, {}, d / "config.json", watchdog=False)
        body = {"agent": "a1", "ticket": "DLP-101", "key": "DLP-101", "project_id": 1, "title": "Retry"}
        info = a.agent_action("prompt", body)
        self.assertEqual((info["repo"]["state"], info["repo"]["via"], info["repo"]["clone"]["state"]), ("git", "https", ""))
        miss = a.agent_action("access", {"agent": "a1", "project_id": 2, "fresh": True})["repo"]
        self.assertEqual((miss["state"], miss["path"]), ("missing", str(d / "ws" / "dlp-ui")))
        with self.assertRaises(server.UserError) as cm:
            a.agent_action("clone", {"agent": "a1", "project_id": 2})
        self.assertIn("Demo", str(cm.exception))
        with self.assertRaises(server.UserError):
            a.agent_action("clone", {"agent": "a1"})
        rid = a.agent_action("assign", body)["id"]
        a.agent_action("start", {"run": rid, "prompt": info["prompt"], "project_id": 1})
        self.assertTrue(wait_for(lambda: (a.agents.poll(force=True), a.store.agent_run(rid)["status"] != "läuft")[1]))
        pre = a.agent_action("prompt", {"agent": "a1", "prereview": rid})
        self.assertEqual((pre["prereview"], pre["branch"], pre["repo"]["state"]), (rid, "agent/dlp-101-%d" % rid, "git"))
        self.assertIn("Review: DLP-101 ", pre["prompt"])
        self.assertEqual(len(briefing.parse_prompt(pre["prompt"])), 3)

    def test_github_clone_url(self):
        d = Path(tempfile.mkdtemp())
        c = server.load_config(None)
        c.update(data_dir=str(d / "data"))
        a = server.App(c, True, {}, d / "config.json", watchdog=False)
        a.demo = False
        a.ghc = dict(a.ghc, api_url="https://api.github.com", repos=[{"id": 5, "full": "AdBuch/tinyops"}])
        pid = server.github.pid_of(5)
        self.assertEqual(a.clone_url(pid, "ssh"), "git@github.com:AdBuch/tinyops.git")
        self.assertEqual(a.clone_url(pid, "https"), "https://github.com/AdBuch/tinyops.git")
        self.assertTrue(agents.CLONE_URL_RE.fullmatch(a.clone_url(pid, "ssh")))

        class GL:
            def clone_urls(self, pid):
                return {"ssh": "git@gitlab.firma.ch:dlp/core.git", "https": "https://oauth2:geheim@gitlab.firma.ch/dlp/core.git"}
        a.client = GL()
        self.assertEqual(a.clone_url(1, "ssh"), "git@gitlab.firma.ch:dlp/core.git")
        self.assertEqual(a.clone_url(1, "https"), "https://gitlab.firma.ch/dlp/core.git")      # Zugangsdaten nie in der Adresse


class FocusAuto(unittest.TestCase):
    def app(self):
        os.environ["TINYOPS_HOME"] = tempfile.mkdtemp()
        c = server.load_config(None)
        c["data_dir"] = tempfile.mkdtemp()
        c["time"] = {"enabled": True}
        a = server.App(c, True, {}, Path("/nonexistent/c.json"))
        a.overview()
        return a

    def start(self, a, minutes=25):
        st = a.focus_action("start", {"area": "bb", "minutes": minutes})
        return st["session"]["start"]

    def test_session_is_lifesign_then_expires_after_grace(self):
        a = self.app()
        t0 = self.start(a)
        for m in (10, 20, 30):                                   # das Panel fragt ab, niemand klickt: Die Zeit zählt trotzdem
            self.assertIsNotNone(a.focus_state(t0 + m * 60)["session"])
        self.assertEqual(a.focus_state(t0 + 30 * 60)["session"]["grace_secs"], 600)
        st = a.focus_state(t0 + 36 * 60)                         # 25 + 10 Minuten Frist vorbei
        self.assertIsNone(st["session"])
        self.assertEqual((st["last_ended"]["result"], st["last_ended"]["minutes"]), ("abgelaufen", 25))
        self.assertEqual(a.time_state()["running"]["key"], "Berufsbildung")              # die Zeit auf der Aufgabe läuft weiter
        self.assertTrue(any(e.get("kind") == "focus" for e in a.store.flow_events(limit=5)) if hasattr(a.store, "flow_events") else True)
        with self.assertRaises(server.UserError):
            a.focus_action("end", {"result": "erledigt"}, now=t0 + 37 * 60)

    def test_extend(self):
        a = self.app()
        t0 = self.start(a)
        a.focus_state(t0 + 14 * 60)
        st = a.focus_action("extend", {"minutes": 15}, now=t0 + 28 * 60)                 # schon 3 Minuten drüber: ab jetzt gerechnet
        self.assertEqual(st["session"]["planned_min"], 43)
        self.assertIsNotNone(a.focus_state(t0 + 40 * 60)["session"])
        for bad in (0, 2, 90, "x"):
            with self.assertRaises(server.UserError):
                a.focus_action("extend", {"minutes": bad}, now=t0 + 41 * 60)
        self.assertEqual(a.focus_state(t0 + 54 * 60)["last_ended"]["result"], "abgelaufen")

    def test_ends_when_panel_was_away_or_time_moves_on(self):
        a = self.app()
        t0 = self.start(a, 50)
        st = a.focus_state(t0 + 40 * 60)                         # 40 Minuten keine Abfrage (Rechner im Ruhezustand)
        self.assertEqual((st["session"], st["last_ended"]["result"], st["last_ended"]["minutes"]), (None, "pausiert", 0))
        t1 = time.time() + 7200
        a.focus_action("start", {"area": "bb", "minutes": 50}, now=t1)
        a.timebook.start("DLP-101", "anderes", now=t1 + 300, idle=15)
        st = a.focus_state(t1 + 360)
        self.assertEqual((st["session"], st["last_ended"]["result"], st["last_ended"]["minutes"]), (None, "abgelöst", 5))


class Ui(unittest.TestCase):
    def test_static(self):
        html = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
        for needle in ("const HELP = {", 'data-help="${id}"', "ssh-keygen -t ed25519", "data-fbext", "data-fmext", 'id="agRepo"', "/api/agents/clone", "/api/agents/access",
                       "function secretList(", 'id="agNext"', 'data-f="provider"', 'data-f="clone_via"', "FOCUS_AUTO"):
            self.assertIn(needle, html, needle)
        for gone in ("soll-only", "startLabel: 'Block starten'", "ohne Zeitbox"):          # die Leiste gibt es nur noch bei laufender Sitzung
            self.assertNotIn(gone, html, gone)
        ids = set(re.findall(r"sect\('([a-z]+)'", html))
        helped = set(re.findall(r"^  ([a-z]+): `", html, re.M))
        self.assertEqual(ids - helped - {"more"}, set())                                  # jeder Abschnitt der Einstellungen hat eine Hilfe


if __name__ == "__main__":
    unittest.main()
