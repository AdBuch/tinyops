"""0.45: Einstellungen nach Schema (settings_schema.py), Verbindungstests in conntest*.py, veraltete Einstellungen fallen weg.
Die Datenbank-Migrationen prüft test_dbschema."""
import json
import os
import re
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("TINYOPS_HOME", tempfile.mkdtemp())
import config  # noqa: E402
import settings  # noqa: E402
import settings_schema as S  # noqa: E402
import ui  # noqa: E402

JS = (ROOT / "static" / "js" / "settings.js").read_text(encoding="utf-8")


def ui_numbers():
    """Alle Zahlenfelder, die settings.js mit field(…, { type: 'number', err: '…' }) zeigt."""
    return {k for k in re.findall(r"type: 'number', err: '([a-z0-9_.]+)'", JS) if not k.startswith("focus.areas.")}   # je Bereich: eigene Prüfung


class Schema(unittest.TestCase):
    def test_every_number_in_the_ui_is_in_the_schema(self):
        self.assertEqual(sorted(ui_numbers() - set(S.NUMBERS)), [], "Zahlenfeld ohne Zeile in settings_schema.NUMBERS")
        only_server = {"voice.timeout"}                      # kein Feld, nur die Grenze für die Config
        self.assertEqual(sorted(set(S.NUMBERS) - ui_numbers() - only_server), [], "Zeile im Schema ohne Feld in der Oberfläche")

    def test_number(self):
        e = {}
        self.assertEqual(S.number("sonar.max_items", "", e), 40)
        self.assertEqual(S.number("sonar.max_items", None, e, keep=7), 7)
        self.assertEqual(S.number("sonar.max_items", " 12 ", e), 12)
        self.assertEqual(e, {})
        self.assertEqual(S.number("sonar.max_items", "500", e, keep=9), 9)
        self.assertEqual(e, {"sonar.max_items": "Ganze Zahl von 1 bis 200."})
        e = {}
        self.assertEqual(S.number("ux.days", "drei", e), 30)
        self.assertEqual(S.number("ux.days", 2.5, e), 30)
        self.assertEqual(e, {"ux.days": "Ganze Zahl von 1 bis 365."})

    def test_build_config_uses_the_schema(self):
        cfg, err = settings.build_config({}, {"sonar": {"max_items": "0", "cache_seconds": "60"}, "usage": {"cache_seconds": "5"},
                                              "time": {"idle_minutes": "1"}, "agent_guards": {"max_files": "3"}, "agent_log_days": "-1"})
        self.assertEqual(err, {"sonar.max_items": "Ganze Zahl von 1 bis 200.", "usage.cache_seconds": "Ganze Zahl von 30 bis 3600.",
                               "time.idle_minutes": "Ganze Zahl von 3 bis 240.", "agent_log_days": "Ganze Zahl von 0 bis 3650."})
        self.assertEqual((cfg["sonar"]["cache_seconds"], cfg["sonar"]["max_items"]), (60, 40))
        cfg, err = settings.build_config({}, {"agent_guards": {"max_files": "3"}})
        self.assertEqual((err, cfg["agent_guards"]["max_files"], cfg["agent_guards"]["max_lines"]), ({}, 3, 300), "fehlendes Feld behält den Standard")

    def test_view_carries_schema_and_defaults(self):
        v = settings.view({}, Path("/tmp/c.json"))
        self.assertEqual(v["schema"], S.public())
        self.assertEqual(v["schema"]["sonar.max_items"], {"min": 1, "max": 200, "default": 40, "help": ""})
        for key in ("sonar.max_items", "sonar.report_max", "llm.timeout", "usage.cache_seconds", "agent_log_days"):
            sec, _, name = key.rpartition(".")
            got = v[sec][name] if sec else v[name]
            self.assertEqual(got, S.NUMBERS[key].default, key)

    def test_ui_takes_limits_from_the_schema(self):
        js = ui.source(ROOT)
        self.assertIn("SET_SCHEMA = S.schema || {}", js)
        self.assertIn('min="${sch.min}" max="${sch.max}"', js)


class Split(unittest.TestCase):
    def test_settings_is_smaller_and_names_stay(self):
        self.assertLess(len((ROOT / "settings.py").read_text(encoding="utf-8").splitlines()), 700)
        for f in ("conntest.py", "conntest_jira.py"):
            self.assertLess(len((ROOT / f).read_text(encoding="utf-8").splitlines()), 1000, f)
        for name in ("test_gitlab", "test_jira", "test_helpdesk", "test_sonar", "test_github", "test_llm", "test_voice", "test_agent",
                     "search_projects", "search_github", "suggest_identity", "JQL_DEFAULT"):
            self.assertTrue(callable(getattr(settings, name)) or name == "JQL_DEFAULT", name)


class Obsolete(unittest.TestCase):
    def test_dropped_on_load_and_gone_after_save(self):
        d = Path(tempfile.mkdtemp())
        p = d / "config.json"
        p.write_text(json.dumps({"kube_context": "prod", "agent_command": "x", "time": {"mcp_url": "http://x", "round_minutes": 30},
                                 "features": {"testenv": True, "ideas": True}, "jira": {"helpdesk": {"jql": "x"}}}))
        with self.assertLogs("tinyops", "INFO") as log:
            cfg = config.load_config(str(p))
        self.assertIn("kube_context", log.output[0])
        self.assertNotIn("kube_context", cfg)
        self.assertEqual(cfg["time"], {"round_minutes": 30})
        self.assertEqual(cfg["features"], {"ideas": True})
        self.assertEqual(cfg["jira"], {"helpdesk": {"jql": "x"}}, "jira.helpdesk liest JiraClient.helpdesk() noch")
        settings.write_config(p, cfg)
        self.assertNotIn("kube_context", p.read_text())

    def test_no_code_reads_them(self):
        src = {f.name: f.read_text(encoding="utf-8") for f in ROOT.glob("*.py") if f.name != "config.py"}
        section = {"time": ("timesheet.py", "area_time.py", "bcs.py"), "features": ("server.py", "area_sync.py", "area_focus.py")}
        for key, _ in config.OBSOLETE:
            parent, _, last = key.rpartition(".")
            files = section[parent] if parent else list(src)        # verschachtelt: nur die Module, die diesen Abschnitt lesen
            pat = re.compile(r'(\.get\(|\[)"%s"' % re.escape(last) if parent else r'"%s"' % re.escape(last))
            self.assertEqual([n for n in files if n in src and pat.search(src[n])], [], key)

if __name__ == "__main__":
    unittest.main()
