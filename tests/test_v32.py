"""0.32: Begründung im Bericht statt im Code, «Kurz vorab» und MR-Beschreibung, Auschecken in einen eigenen Worktree,
Review-Umgebung auf Klick, Piktogramme für Repo und Branch."""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import agents  # noqa: E402
import briefing  # noqa: E402
import reviewenv  # noqa: E402
import server  # noqa: E402
import settings  # noqa: E402
from test_agents import git_repo, wait_for  # noqa: E402

REPORT = """## Kurz
Bei 429 wird jetzt mit Backoff wiederholt.

## Was und warum
- `core/retry.py` – RetryPolicy neu – damit 429 nicht sofort abbricht
- `tests/test_retry.py` – Test für 5 Versuche – belegt AK2

## Zuerst ansehen
Die Schleife in `RetryPolicy.run`.

## Getestet
pytest

## Bewusst nicht gemacht
Jitter, eigenes Ticket.
"""
WORK = ("mkdir -p core tests && printf '# erklärt die Retry-Logik fürs Review\\n# zweite Zeile\\nx = 1\\n' > core/retry.py && echo ok > tests/test_retry.py && "
        "echo n > notes.txt && git add -A && git -c user.name=T -c user.email=t@x commit -qm retry && tinyops-check true && "
        "tinyops-manual 'Import starten' 'kein Abbruch' && cat <<'EOF2' | tinyops-report\n" + REPORT + "EOF2\n")


class Pure(unittest.TestCase):
    def test_guard_mentions_reasons_not_comments(self):
        t = agents.guards_text(agents.guards_cfg({}), "develop")
        self.assertIn("Begründen im Bericht, nicht im Code", t)
        self.assertIn("keine auskommentierten Zeilen", t)
        for f in ("agent-task.md", "agent-followup.md"):
            s = (ROOT / "prompts" / f).read_text(encoding="utf-8")
            for w in ("## Kurz", "## Was und warum", "`pfad/Datei` – was geändert – warum so", "## Zuerst ansehen", "## Bewusst nicht gemacht"):
                self.assertIn(w, s, f)

    def test_diff_counts_and_warning(self):
        diff = ["diff --git a/a.py b/a.py", "--- a/a.py", "+++ b/a.py", "@@ -1 +1,6 @@", "+# eins", "+# zwei", "+x = 1", "-y", "+#!/bin/sh",
                "diff --git a/b.java b/b.java", "--- /dev/null", "+++ b/b.java", "@@ -0,0 +1,4 @@", "+// a", "+/* b", "+ * c", "+int x; // d",
                "diff --git a/README.md b/README.md", "--- a/README.md", "+++ b/README.md", "@@ -1 +1 @@", "+# Titel", "+-- kein Kommentar"]
        c = agents.diff_counts(diff)
        self.assertEqual(c["a.py"], {"add": 4, "del": 1, "comments": 2})
        self.assertEqual(c["b.java"], {"add": 4, "del": 0, "comments": 3})
        self.assertEqual(c["README.md"]["comments"], 0)
        res = {"files": [dict(path=k, st="M", **v) for k, v in c.items()], "stat": "", "dirty": 0}
        w = agents.guard_warnings(res, agents.guards_cfg({}))
        self.assertEqual(len(w), 1)
        self.assertIn("5 neue Kommentarzeilen", w[0])

    def test_report_sections_and_brief(self):
        sec = briefing.report_sections(REPORT)
        self.assertEqual(set(sec), {"short", "why", "first", "tested", "notdone"})
        run = {"id": 7, "ticket": "DLP-101", "title": "Retry", "summary": REPORT, "out_branch": "agent/dlp-101-7",
               "result": {"files": [{"st": "A", "path": "core/retry.py", "add": 3, "del": 0, "comments": 2}, {"st": "A", "path": "notes.txt", "add": 1, "del": 0}], "stat": "2 files changed"},
               "criteria": [{"n": 1, "text": "Retry", "state": "ok", "note": ""}, {"n": 2, "text": "5 Versuche", "state": "", "note": ""}],
               "checks": [{"cmd": "pytest", "exit": 0}], "manual": [{"kind": "review", "step": "Diff"}, {"kind": "test", "step": "Import starten", "expect": "kein Abbruch"}]}
        b = briefing.review_brief(run)
        self.assertTrue(b["short"].startswith("Bei 429"))
        self.assertEqual([f["why"] for f in b["files"]], ["RetryPolicy neu – damit 429 nicht sofort abbricht", ""])
        self.assertEqual(b["without_reason"], 1)
        self.assertEqual((b["ak_ok"], b["ak"], b["checks_ok"], b["checks"]), (1, 2, 1, 1))
        self.assertEqual([m["step"] for m in b["manual"]], ["Import starten"])
        md = briefing.mr_description(run)
        for w in ("## Worum es geht", "**DLP-101** – Retry", "`core/retry.py` (+3/−0) – RetryPolicy neu", "## So testest du",
                  "1. Import starten → erwartet: kein Abbruch", "Automatisch: 1 von 1 Prüfungen grün (`pytest`)", "- [x] Retry", "- [ ] 5 Versuche", "## Bewusst nicht gemacht"):
            self.assertIn(w, md)

    def test_reviewenv_helpers(self):
        self.assertEqual(reviewenv.env_name("DLP-101", 7), "review-dlp-101-7")
        self.assertEqual(reviewenv.env_port(7), "20007" and 20007)
        v = reviewenv.values({"id": 7, "ticket": "DLP-101", "out_branch": "agent/dlp-101-7"}, "/tmp/a b", "abc")
        self.assertEqual(reviewenv.fill("cd {path} && up {name} -p {port} {branch} {nix}", v), "cd '/tmp/a b' && up review-dlp-101-7 -p 20007 agent/dlp-101-7 {nix}")
        self.assertEqual(reviewenv.fill("http://localhost:{port}", v, quote=False), "http://localhost:20007")
        self.assertEqual(reviewenv.clean({"kind": ""}), (None, ""))
        self.assertIn("Start-Befehl", reviewenv.clean({"kind": "custom", "up": ""})[1])
        self.assertIn("einer Zeile", reviewenv.clean({"kind": "compose", "up": "a\nb"})[1])
        self.assertIn("http", reviewenv.clean({"kind": "compose", "up": "x", "url": "ftp://x"})[1])
        self.assertEqual(reviewenv.clean({"kind": "compose", "up": " docker compose up ", "down": "", "url": "http://h:{port}"})[0],
                         {"kind": "compose", "up": "docker compose up", "down": "", "url": "http://h:{port}"})
        conn = {"host": "devops", "user": "ad", "port": 2222}
        self.assertEqual(reviewenv.source_url({}, conn, "~/play/dlp"), "ssh://ad@devops:2222/~/play/dlp")
        self.assertEqual(reviewenv.source_url({}, conn, "play/dlp"), "ssh://ad@devops:2222/~/play/dlp")
        self.assertEqual(reviewenv.source_url({}, conn, "/srv/dlp"), "ssh://ad@devops:2222/srv/dlp")
        self.assertEqual(reviewenv.source_url({}, None, "/srv/dlp"), "/srv/dlp")
        cmds = reviewenv.checkout_commands("ssh://ad@devops:2222/~/play/dlp", "agent/dlp-101-7")
        self.assertEqual(cmds, "git fetch 'ssh://ad@devops:2222/~/play/dlp' agent/dlp-101-7:agent/dlp-101-7\ngit switch agent/dlp-101-7\n")

    def test_settings(self):
        new, errors = settings.build_config({"projects": [{"id": 1, "name": "p"}]},
                                            {"projects": [{"id": 1, "name": "p", "review_env": {"kind": "k8s", "up": "kubectl apply -k x", "down": "", "url": ""}}]})
        self.assertFalse(errors.get("projects"), errors)
        self.assertEqual(new["projects"][0]["review_env"]["kind"], "k8s")
        v = settings.view(new, Path("/x/c.json"))
        self.assertEqual(v["projects"][0]["review_env"]["kind"], "k8s")
        self.assertEqual([k["id"] for k in v["review_kinds"]], ["compose", "k8s", "custom"])
        new2, errors = settings.build_config(new, {"projects": [{"id": 1, "name": "p", "review_env": None}]})
        self.assertNotIn("review_env", new2["projects"][0])
        _, errors = settings.build_config(new, {"projects": [{"id": 1, "name": "p", "review_env": {"kind": "nope", "up": "x"}}]})
        self.assertIn("Unbekannte Art", errors["projects"])


class TryIt(unittest.TestCase):
    def setUp(self):
        d = Path(tempfile.mkdtemp())
        self.d = d
        git_repo(d / "ws" / "dlp-core")
        clone = d / "me" / "dlp-core"
        subprocess.run(["git", "clone", "-q", str(d / "ws" / "dlp-core"), str(clone)], check=True)
        self.marker = d / "env.txt"
        c = server.load_config(None)
        c.update(data_dir=str(d / "data"), connections=[], ide_command="true {path}",
                 projects=[{"id": 1, "name": "dlp-core", "data_class": "internal", "repo_path": str(clone),
                            "review_env": {"kind": "custom", "up": "echo up {name} {port} $REVIEW_NAME > %s && git rev-parse --short HEAD >> %s" % (self.marker, self.marker),
                                           "down": "echo down {name} >> %s" % self.marker, "url": "http://localhost:{port}"}}],
                 agents=[{"id": "a1", "name": "A1", "kind": "custom", "connection": "local", "workspace_root": str(d / "ws"), "cloud": False, "command": WORK}])
        self.a = server.App(c, False, {}, d / "config.json", watchdog=False)
        self.clone = clone

    def test_brief_checkout_env(self):
        a = self.a
        body = {"agent": "a1", "ticket": "DLP-101", "key": "DLP-101", "project_id": 1, "title": "Retry"}
        info = a.agent_action("prompt", body)
        rid = a.agent_action("assign", body)["id"]
        with self.assertRaises(server.UserError):
            a.agent_action("checkout", {"run": rid})
        a.agent_action("start", {"run": rid, "prompt": info["prompt"], "project_id": 1})
        self.assertTrue(wait_for(lambda: (a.agents.poll(force=True), a.store.agent_run(rid)["status"] != "läuft")[1]))
        v = a.agents.run_view(a.store.agent_run(rid))
        b = v["review_brief"]
        self.assertEqual({f["path"]: f["comments"] for f in b["files"]}, {"core/retry.py": 2, "notes.txt": 0, "tests/test_retry.py": 0})
        self.assertEqual(b["without_reason"], 1)
        self.assertIn("## Was sich geändert hat und warum", a.agent_action("mrdesc", {"run": rid})["text"])

        t = a.agent_action("try", {"run": rid})
        self.assertEqual((t["branch"], t["clone"], t["worktree"]), (v["out_branch"], str(self.clone), ""))
        self.assertIn("git switch " + v["out_branch"], t["commands"])
        self.assertEqual((t["env"]["kind"], t["env"]["name"], t["env"]["url"]), ("custom", "review-dlp-101-%d" % rid, "http://localhost:%d" % (20000 + rid)))
        self.assertEqual(t["push"], "git push -u origin " + v["out_branch"])

        co = a.agent_action("checkout", {"run": rid, "ide": True})
        self.assertTrue(co["launched"])
        wt = Path(co["path"])
        self.assertEqual(wt.parent.name, ".tinyops-wt")
        self.assertTrue((wt / "core" / "retry.py").exists())
        self.assertFalse((self.clone / "core").exists())                     # dein Checkout bleibt unberührt
        head = subprocess.run(["git", "-C", str(wt), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
        self.assertEqual(head, co["sha"])
        (wt / "scratch.txt").write_text("x")
        self.assertIn("geänderte Dateien", a.agent_action("checkout", {"run": rid, "ide": False})["hint"])
        os.remove(wt / "scratch.txt")

        st = a.agent_action("env", {"run": rid, "do": "up"})
        self.assertEqual(st["state"], "startet")
        self.assertTrue(wait_for(lambda: json.loads(a.store.agent_run(rid)["renv"] or "{}").get("state") == "läuft"))
        self.assertEqual(self.marker.read_text().split()[:4], ["up", "review-dlp-101-%d" % rid, str(20000 + rid), "review-dlp-101-%d" % rid])
        self.assertEqual(a.agent_action("try", {"run": rid})["env_state"]["url"], "http://localhost:%d" % (20000 + rid))
        a.agent_action("env", {"run": rid, "do": "down"})
        self.assertTrue(wait_for(lambda: json.loads(a.store.agent_run(rid)["renv"] or "{}").get("state") == "gestoppt"))
        self.assertIn("down review-dlp-101-%d" % rid, self.marker.read_text())
        acts = [r["action"] for r in a.audit_log.export()]
        for x in ("agent.checkout", "review.env.up", "review.env.down"):
            self.assertIn(x, acts)
        with self.assertRaises(server.UserError):
            a.agent_action("env", {"run": rid, "do": "restart"})

    def test_env_needs_config(self):
        self.a.cfg["projects"][0].pop("review_env")
        self.a.proj_cfg[1].pop("review_env", None)
        rid = self.a.agent_action("assign", {"agent": "a1", "ticket": "DLP-1", "project_id": 1, "title": "x"})["id"]
        with self.assertRaises(server.UserError) as cm:
            self.a.agent_action("env", {"run": rid, "do": "up"})
        self.assertIn("keine Review-Umgebung", str(cm.exception))


class Ui(unittest.TestCase):
    def test_static(self):
        html = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
        for n in ("function repoIcon(", "function branchIcon(", "function agBriefHtml(", "function agTryLoad(", "/api/agents/try", "/api/agents/checkout",
                  "/api/agents/env", "/api/agents/mrdesc", "Kurz vorab", "renderReviewEnvs", "class=\"hpics\""):
            self.assertIn(n, html, n)

    def test_icons_are_deterministic(self):
        import shutil
        node = shutil.which("node")
        if not node:
            self.skipTest("node fehlt")
        html = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
        start = html.index("function hash32(")
        end = html.index("function picLine(")
        js = ("const esc = s => String(s).replace(/[&<>\"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;',\"'\":'&#39;'}[c]));\n" + html[start:end] +
              "\nconsole.log(JSON.stringify([repoIcon('dlp-core')===repoIcon('dlp-core'), repoIcon('dlp-core')!==repoIcon('labelo'),"
              " branchIcon('feature/a')!==branchIcon('feature/b'), branchKind('bugfix/x'), branchKind('agent/dlp-1-2'), branchKind('feature/x'), branchKind('main'),"
              " branchIcon('<x>').includes('<x>'), branchIcon('')]))")
        out = json.loads(subprocess.run([node, "-e", js], capture_output=True, text=True, timeout=20).stdout)
        self.assertEqual(out, [True, True, True, "fix", "agent", "feature", "other", False, ""])


if __name__ == "__main__":
    unittest.main()
