"""Ticket-Entwurf (lokales Modell) und Ticket anlegen (Jira, schreibend)."""
import json
import os
import sys
import unittest
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import llm  # noqa: E402
import server  # noqa: E402
import settings  # noqa: E402
from test_settings import nostored, start, step  # noqa: E402


def last(port):
    with urllib.request.urlopen("http://127.0.0.1:%d/_last" % port) as r:
        return json.loads(r.read())


class LlmUnit(unittest.TestCase):
    def test_is_local(self):
        for u in ("http://127.0.0.1:11434", "http://localhost:8080", "http://192.168.1.20:8080", "http://10.1.2.3", "http://gpu-box:8080",
                  "http://llm.office.lan", "http://[::1]:8080"):
            self.assertTrue(llm.is_local(u), u)
        for u in ("http://8.8.8.8", "http://8.8.4.4:8080"):
            self.assertFalse(llm.is_local(u), u)

    def test_remote_is_refused_unless_allowed(self):
        with self.assertRaises(llm.LlmError) as c:
            llm.check_url({"url": "http://8.8.4.4:8080"})
        self.assertIn("Datenschutz", str(c.exception))
        self.assertEqual(llm.check_url({"url": "http://8.8.4.4:8080/", "allow_remote": True}), "http://8.8.4.4:8080")
        with self.assertRaises(llm.LlmError):
            llm.check_url({"url": "ftp://x"})

    def test_parse_draft(self):
        text = 'Gern:\n```json\n{"summary": " Titel ", "description": "h3. Ziel", "issue_type": "bug"}\n```'
        d = llm.parse_draft(text, ["Story", "Bug"])
        self.assertEqual((d["summary"], d["issue_type"]), ("Titel", "Bug"))
        self.assertEqual(llm.parse_draft('{"summary": "x", "issue_type": "Epic"}', ["Story"])["issue_type"], "")
        for bad in ("kein json", '{"summary": ""}', "{nope}"):
            with self.assertRaises(llm.LlmError):
                llm.parse_draft(bad, ["Story"])

    def test_template_and_prompt_send_no_more_than_titles(self):
        ctx = {"iid": 5, "title": "WIP: Sonar Welle", "branch": "agent/sonar", "project": "core", "url": "https://g/x",
               "mr_description": "Beschreibung", "commits": ["Fix A", "Fix B"], "issue_types": ["Story"]}
        t = llm.template_draft(ctx)
        self.assertEqual(t["summary"], "Sonar Welle")
        self.assertIn("* Fix A", t["description"])
        prompt = llm.build_prompt(ctx, "Bitte kurz")
        self.assertIn("Fix B", prompt)
        self.assertIn("Bitte kurz", prompt)


class OllamaAndOpenAI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.p, cls.port = start("mock_llm.py")
        os.environ["LLM_KEY"] = "1"
        cls.pk, cls.kport = start("mock_llm.py")
        del os.environ["LLM_KEY"]

    @classmethod
    def tearDownClass(cls):
        for p in (cls.p, cls.pk):
            p.terminate()
            p.wait()

    def cfg(self, **kw):
        c = {"provider": "ollama", "url": "http://127.0.0.1:%d" % self.port, "model": "llama3.2:3b", "timeout": 10}
        c.update(kw)
        return c

    def test_ollama_ok(self):
        r = settings.test_llm(self.cfg(), nostored)
        self.assertTrue(r["ok"], r)
        self.assertEqual(r["models"], ["llama3.2:3b", "broken"])
        self.assertEqual(step(r, "testentwurf")["status"], "ok")

    def test_ollama_wrong_model_and_no_model(self):
        r = settings.test_llm(self.cfg(model="nicht-da"), nostored)
        self.assertFalse(r["ok"])
        self.assertIn("ollama pull", step(r, "modell")["hint"])
        self.assertFalse(settings.test_llm(self.cfg(model=""), nostored)["ok"])

    def test_broken_model_is_only_a_warning(self):
        r = settings.test_llm(self.cfg(model="broken"), nostored)
        self.assertTrue(r["ok"])
        self.assertEqual(step(r, "testentwurf")["status"], "warn")

    def test_openai_dialect_and_key(self):
        c = self.cfg(provider="openai", url="http://127.0.0.1:%d" % self.kport, model="qwen2.5-7b")
        r = settings.test_llm(c, nostored)
        self.assertFalse(r["ok"])
        self.assertIn("401", step(r, "server antwortet")["detail"])
        r = settings.test_llm(dict(c, secret="lkey"), nostored)
        self.assertTrue(r["ok"], r)
        r = settings.test_llm(c, lambda n: ("lkey", "test"))   # Schlüssel aus dem Speicher
        self.assertTrue(r["ok"], r)

    def test_remote_address_refused_in_test(self):
        r = settings.test_llm(self.cfg(url="http://8.8.4.4:11434"), nostored)
        self.assertFalse(r["ok"])
        self.assertIn("Datenschutz", step(r, "adresse")["detail"])

    def test_draft_ticket(self):
        ctx = {"iid": None, "title": "t", "branch": "b", "project": "p", "commits": ["c1"], "issue_types": ["Story", "Bug"]}
        d = llm.draft_ticket(self.cfg(), "", ctx, hint="Fokus auf Tests")
        self.assertEqual(d["issue_type"], "Story")
        self.assertIn("Akzeptanzkriterien", d["description"])
        sent = last(self.port)
        self.assertIn("c1", sent["messages"][1]["content"])
        self.assertIn("Fokus auf Tests", sent["messages"][1]["content"])
        with self.assertRaises(llm.LlmError):
            llm.draft_ticket(self.cfg(model="broken"), "", ctx)

    def test_custom_provider_can_be_registered(self):
        class Fake:
            name, label, default_url = "fake", "Fake", "http://127.0.0.1:1"

            def models(self, cfg, key, ctx=None):
                return ["m"]

            def chat(self, cfg, key, system, user, ctx=None):
                return '{"summary": "aus fake", "description": "d", "issue_type": "Story"}'
        llm.register(Fake())
        try:
            d = llm.draft_ticket({"provider": "fake", "url": "http://127.0.0.1:1"}, "", {"issue_types": ["Story"]})
            self.assertEqual(d["summary"], "aus fake")
        finally:
            llm.PROVIDERS.pop("fake")


class JiraCreate(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.p, cls.port = start("mock_jira.py")
        jc = dict(server.JIRA_DEFAULTS, url="http://127.0.0.1:%d" % cls.port, allow_create=True)
        cls.jira = server.JiraClient(jc, "Bearer jtoken", server.ssl.create_default_context())

    @classmethod
    def tearDownClass(cls):
        cls.p.terminate()
        cls.p.wait()

    def test_types_and_create(self):
        self.assertEqual(self.jira.issue_types("DLP"), ["Story", "Bug"])   # ohne Unteraufgaben
        r = self.jira.create_issue("DLP", "Story", "Titel", "h3. Ziel")
        self.assertEqual(r["key"], "DLP-201")
        self.assertTrue(r["url"].endswith("/browse/DLP-201"))
        sent = last(self.port)["fields"]
        self.assertEqual((sent["project"]["key"], sent["issuetype"]["name"], sent["summary"]), ("DLP", "Story", "Titel"))

    def test_errors_are_readable(self):
        with self.assertRaises(server.UserError) as c:
            self.jira.create_issue("OPS", "Story", "x", "")
        self.assertIn("keine Berechtigung", str(c.exception))
        with self.assertRaises(server.UserError) as c:
            self.jira.create_issue("DLP", "Story", "", "")
        self.assertIn("summary", str(c.exception))


class AppTicketFlow(unittest.TestCase):
    """Über die App (Demo-Daten): Schutz, Entwurf, Anlegen."""

    @classmethod
    def setUpClass(cls):
        cls.p, cls.port = start("mock_llm.py")

    @classmethod
    def tearDownClass(cls):
        cls.p.terminate()
        cls.p.wait()

    def app(self, jira=None, llm_cfg=None):
        cfg = server.load_config(None)
        cfg["jira"] = dict({"url": "https://jira.example", "project_keys": ["DLP"]}, **(jira or {}))
        if llm_cfg:
            cfg["llm"] = llm_cfg
        return server.App(cfg, True, {}, Path("/nonexistent/c.json"))

    def test_create_is_off_by_default(self):
        a = self.app()
        self.assertFalse(a.ticket_meta()["can_create"])
        with self.assertRaises(server.UserError) as c:
            a.ticket_create({"project": "DLP", "summary": "x", "issue_type": "Story"})
        self.assertIn("ausgeschaltet", str(c.exception))

    def test_create_validates_and_works(self):
        a = self.app({"allow_create": True})
        self.assertTrue(a.ticket_meta()["can_create"])
        for bad, msg in (({"project": "XYZ", "summary": "x", "issue_type": "Story"}, "nicht erlaubt"),
                         ({"project": "DLP", "summary": "  ", "issue_type": "Story"}, "Titel"),
                         ({"project": "DLP", "summary": "x" * 256, "issue_type": "Story"}, "255"),
                         ({"project": "DLP", "summary": "x", "issue_type": "Epic"}, "gibt es")):
            with self.assertRaises(server.UserError) as c:
                a.ticket_create(bad)
            self.assertIn(msg, str(c.exception))
        r = a.ticket_create({"project": "dlp", "summary": "  Zwei   Leerzeichen ", "description": "d", "issue_type": "Bug"})
        self.assertTrue(r["key"].startswith("DLP-"))

    def test_draft_template_without_llm(self):
        a = self.app()
        d = a.ticket_draft({"project_id": 1, "iid": 35, "branch": "agent/sonar-wave-1"})
        self.assertEqual(d["source"], "vorlage")
        self.assertEqual(d["draft"]["issue_type"], "Story")
        self.assertIn("Sonar: Null-Checks", d["draft"]["description"])
        with self.assertRaises(server.UserError):
            a.ticket_draft({"project_id": 1, "iid": 35, "branch": "x", "use_llm": True})

    def test_draft_with_llm_and_fallback(self):
        url = "http://127.0.0.1:%d" % self.port
        a = self.app(llm_cfg={"enabled": True, "provider": "ollama", "url": url, "model": "llama3.2:3b"})
        self.assertTrue(a.ticket_meta()["llm"])
        d = a.ticket_draft({"project_id": 1, "iid": None, "branch": "wip/x", "use_llm": True, "hint": "kurz"})
        self.assertEqual(d["source"], "ki")
        self.assertEqual(d["draft"]["summary"], "Retry bei HTTP 429 ergänzen")
        self.assertEqual(d["draft"]["issue_type"], "Story")
        b = self.app(llm_cfg={"enabled": True, "provider": "ollama", "url": url, "model": "broken"})
        d = b.ticket_draft({"project_id": 1, "iid": 35, "branch": "x", "use_llm": True})
        self.assertEqual(d["source"], "vorlage")
        self.assertIn("nicht geliefert", d["warning"])
        c = self.app(llm_cfg={"enabled": True, "provider": "ollama", "url": "http://8.8.4.4:11434", "model": "m"})
        d = c.ticket_draft({"project_id": 1, "iid": 35, "branch": "x", "use_llm": True})
        self.assertEqual(d["source"], "vorlage")
        self.assertIn("Datenschutz", d["warning"])


class BuildConfigLlm(unittest.TestCase):
    def test_saves_and_validates(self):
        cfg, err = settings.build_config({}, {"gitlab": {"url": "https://g.example"}, "jira": {"url": "https://j.example", "allow_create": True, "create_type": "Aufgabe"},
                                              "llm": {"enabled": True, "provider": "openai", "url": "http://127.0.0.1:8080/", "model": "q"}})
        self.assertEqual(err, {})
        self.assertTrue(cfg["jira"]["allow_create"])
        self.assertEqual(cfg["jira"]["create_type"], "Aufgabe")
        self.assertEqual(cfg["llm"]["url"], "http://127.0.0.1:8080")
        _, err = settings.build_config({}, {"llm": {"enabled": True, "url": "http://8.8.4.4:1"}})
        self.assertIn("llm.url", err)
        _, err = settings.build_config({}, {"llm": {"enabled": True, "provider": "gibts-nicht", "url": "http://127.0.0.1:1"}})
        self.assertIn("llm.provider", err)
        v = settings.view(cfg, "/x")
        self.assertTrue(v["jira"]["allow_create"])
        self.assertEqual({p["id"] for p in v["llm"]["providers"]}, {"ollama", "openai"})


if __name__ == "__main__":
    unittest.main()
