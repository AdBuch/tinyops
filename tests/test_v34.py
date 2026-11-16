"""0.34: Doppelungen I (nur BCS, Review-Umgebung statt alter Testumgebung, Prompts zum Kopieren) und Korrekturen aus dem Prüfbericht 0.33."""
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import helpdesk  # noqa: E402
import reviewenv  # noqa: E402
import server  # noqa: E402


def demo_app(**over):
    os.environ["TINYOPS_HOME"] = tempfile.mkdtemp()
    cfg = server.load_config(None)
    cfg["data_dir"] = tempfile.mkdtemp()
    cfg["time"] = {"enabled": True}
    cfg.update(over)
    return server.App(cfg, True, {}, Path("/nonexistent/c.json"), watchdog=False)


class HelpdeskPinAny(unittest.TestCase):
    """r23-04: Ein Ticket aus Queue oder Beobachtung liess sich nur im Helpdesk öffnen, nicht anheften."""

    def test_pin_queue_ticket_starts_time_and_shows_as_mine(self):
        a = demo_app()
        f = a.overview()["flow"]
        assigned = {e["key"] for e in f["helpdesk"]}
        q = next(x for x in f["hd_queue"] if x["key"] not in assigned)
        a.flow_action("pin", {"id": "hd:" + q["key"]})
        f = a.overview()["flow"]
        self.assertEqual(f["pinned"], "hd:" + q["key"])
        e = next(x for x in f["helpdesk"] if x["key"] == q["key"])
        self.assertTrue(e.get("picked"))
        self.assertEqual(e["next"]["action"]["open"], "hd:" + q["key"])
        self.assertEqual(a.timebook.current()["key"], q["key"])
        a.flow_action("pin", {"id": None})
        self.assertFalse(any(x["key"] == q["key"] for x in a.overview()["flow"]["helpdesk"]))
        with self.assertRaises(server.UserError):
            a.flow_action("pin", {"id": "hd:SD-1"})

    def test_find(self):
        hd = {"assigned": [{"key": "A-1"}], "queue": [{"key": "A-2"}], "watched": [{"key": "A-3"}]}
        self.assertEqual([helpdesk.find(hd, k)["key"] for k in ("A-1", "A-2", "A-3")], ["A-1", "A-2", "A-3"])
        self.assertIsNone(helpdesk.find(hd, "A-4"))
        self.assertIsNone(helpdesk.find(None, "A-1"))


class TestenvGone(unittest.TestCase):
    """E2: Helm-Deploy je MR, Jobs und die alten Agenten-Knöpfe sind weg. Prompts und Befehle bleiben zum Kopieren."""

    def test_removed(self):
        for name in ("deploy", "teardown", "run_agent", "_check_cluster"):
            self.assertFalse(hasattr(server.App, name), name)
        self.assertFalse(hasattr(server, "Jobs"))
        for k in ("kube_context", "namespace_prefix", "deploy_command", "teardown_command", "job_timeout", "agent_command"):
            self.assertNotIn(k, server.DEFAULTS)
        self.assertNotIn("testenv", server.DEFAULTS["features"])
        self.assertTrue((ROOT / "deploy" / "k8s.py").exists())          # tinyops selbst in Kubernetes betreiben bleibt

    def test_prompts_and_mr_env(self):
        a = demo_app()
        data = a.overview()
        self.assertEqual(data["prompts"], ["review-brief", "smoke-test", "repro-test"])
        mr = next(x for x in data["mine"] + data["review"] if x.get("iid") and x.get("project_id") == 1)
        txt = a.render_prompt("smoke-test", 1, mr["iid"])
        self.assertIn("(keine Review-Umgebung eingetragen)", txt)
        with self.assertRaises(server.UserError):
            a.render_prompt("agent-task", 1, mr["iid"])                    # nur die drei MR-Prompts
        st = a.mr_env({"project_id": 1, "iid": mr["iid"]})
        self.assertIsNone(st["env"])
        with self.assertRaises(server.UserError) as cm:
            a.mr_env({"project_id": 1, "iid": mr["iid"], "do": "up"})
        self.assertIn("keine Review-Umgebung", str(cm.exception))
        a.proj_cfg[1]["review_env"] = {"kind": "compose", "up": "docker compose -p {name} up -d", "down": "docker compose -p {name} down", "url": "http://localhost:{port}"}
        st = a.mr_env({"project_id": 1, "iid": mr["iid"]})
        name = "review-dlp-core-mr%d" % mr["iid"]
        self.assertEqual((st["env"]["name"], st["env"]["up"]), (name, "docker compose -p %s up -d" % name))
        self.assertEqual(st["env"]["url"], "http://localhost:%d" % (30000 + mr["iid"]))
        self.assertIn(name, a.render_prompt("smoke-test", 1, mr["iid"]))
        r = a.mr_env({"project_id": 1, "iid": mr["iid"], "do": "up"})
        self.assertEqual(r["state"], "startet")
        import time as _t
        for _ in range(50):
            if (a.store.renv_get("mr:gitlab:1:%d" % mr["iid"]) or {}).get("state") == "läuft":
                break
            _t.sleep(0.1)
        self.assertEqual(a.mr_env({"project_id": 1, "iid": mr["iid"]})["state"]["state"], "läuft")
        self.assertIn("review.env.up", [x["action"] for x in a.audit_log.rows()])


class ComposeAndWorkspaces(unittest.TestCase):
    """Wunsch aus dem Nutzungsbericht: Review-Befehle vorbefüllt, Umsysteme zusammenklicken, Checkout aus Workspaces automatisch."""

    def test_compose_plan(self):
        d = Path(tempfile.mkdtemp())
        self.assertIn("weder eine Compose-Datei", reviewenv.compose_plan({}, str(d), "/g.yml")[2])
        (d / "Dockerfile").write_text("FROM scratch\n")
        files, yaml, err = reviewenv.compose_plan({"services": ["postgres"], "app_port": 9000}, str(d), "/g.yml")
        self.assertEqual((files, err), (["/g.yml"], ""))
        self.assertIn('build: "%s"' % d, yaml)
        self.assertIn('"${REVIEW_PORT}:9000"', yaml)
        self.assertIn("depends_on:\n      - postgres", yaml)
        (d / "docker-compose.yml").write_text("services: {}\n")
        files, yaml, _ = reviewenv.compose_plan({"services": []}, str(d), "/g.yml")
        self.assertEqual((files, yaml), ([str(d / "docker-compose.yml")], None))           # eigene Compose-Datei, nichts erzeugt
        files, yaml, _ = reviewenv.compose_plan({"services": ["redis", "repo:/srv/other-repo"]}, str(d), "/g.yml")
        self.assertEqual(files, [str(d / "docker-compose.yml"), "/g.yml"])
        self.assertNotIn("app:", yaml)
        self.assertIn('other-repo:\n    build: "/srv/other-repo"', yaml)
        self.assertEqual(reviewenv.compose_files_in(str(d)), ["docker-compose.yml"])
        self.assertEqual(reviewenv.fill(reviewenv.KINDS["compose"]["up"], {"name": "n", "compose_files": reviewenv.compose_arg(files)}),
                         "docker compose -f %s -f /g.yml -p n up -d --build" % (d / "docker-compose.yml"))

    def test_clean_services(self):
        env, err = reviewenv.clean({"kind": "compose", "up": "x", "services": ["postgres", "boom", "repo:/abs", "repo:rel"], "app_port": "70000"})
        self.assertIn("Port", err)
        env, err = reviewenv.clean({"kind": "compose", "up": "x", "services": ["postgres", "boom", "repo:/abs", "repo:rel", "postgres"]})
        self.assertEqual((err, env["services"], env["app_port"]), ("", ["postgres", "repo:/abs"], 8080))
        self.assertNotIn("services", reviewenv.clean({"kind": "custom", "up": "x"})[0])

    def test_repo_from_workspaces_and_generated_file(self):
        d = Path(tempfile.mkdtemp())
        repo = d / "work" / "dlp-core"
        (repo / ".git").mkdir(parents=True)
        (repo / "Dockerfile").write_text("FROM scratch\n")
        wt = d / "work" / ".tinyops-wt" / "dlp-core-mr1"
        wt.mkdir(parents=True)
        (wt / ".git").write_text("gitdir: x\n")                     # Worktree: .git ist eine Datei
        a = demo_app()
        a.demo = False
        a.ws_cache = {"repos": [{"ok": True, "path": str(wt), "name": "dlp-core-mr1", "project": {"pid": 1, "host": "gitlab"}, "fetched_days": 0},
                                {"ok": True, "path": str(repo), "name": "dlp-core", "project": {"pid": 1, "host": "gitlab"}, "fetched_days": 3},
                                {"ok": True, "path": str(d / "nix"), "name": "x", "project": None}]}
        a.proj_cfg[1] = {"id": 1, "name": "dlp-core"}
        self.assertEqual(a._repo_of("gitlab", 1), str(repo))                           # automatisch verbunden, kein Worktree
        a.proj_cfg[1]["repo_path"] = "/eigener/pfad"
        self.assertEqual(a._repo_of("gitlab", 1), "/eigener/pfad")                     # eingetragener Pfad geht vor
        a.proj_cfg[1].pop("repo_path")
        h = a.settings_hints()
        self.assertEqual(h["projects"]["1"], {"ws_path": str(repo), "compose": [], "dockerfile": True})
        self.assertEqual(h["repos"], [{"name": "dlp-core", "path": str(repo)}])
        self.assertIn("postgres", [x["id"] for x in h["infra"]])
        vals, err = a._renv_vals({"kind": "compose", "services": ["postgres"], "app_port": 8080}, "mr:gitlab:1:7", {"name": "n"}, str(repo))
        self.assertEqual(err, "")
        gen = Path(vals["compose_files"].split("-f ")[1].strip())
        self.assertTrue(gen.exists())
        self.assertNotIn(str(repo), str(gen.parent))                                  # erzeugte Datei liegt nie im Repo
        self.assertIn("postgres:", gen.read_text())


if __name__ == "__main__":
    unittest.main()
