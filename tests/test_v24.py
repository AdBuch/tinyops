"""0.24: Helpdesk im Panel lesen, beobachtete Tickets (Watcher), Fokus-Leiste, Korrekturen aus dem Nutzungsbericht."""
import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import helpdesk  # noqa: E402
import links  # noqa: E402
import server  # noqa: E402
import settings  # noqa: E402
import timesheet  # noqa: E402
import ux  # noqa: E402
from test_v23 import free_port, wait  # noqa: E402


class Mock(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.port = free_port()
        cls.proc = subprocess.Popen([sys.executable, str(ROOT / "tests" / "mock_jira.py"), str(cls.port), "8.5.1"],
                                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        wait(cls.port)
        cls.url = "http://127.0.0.1:%d" % cls.port

    @classmethod
    def tearDownClass(cls):
        cls.proc.terminate()
        cls.proc.wait(5)

    def client(self, **kw):
        hc = dict(helpdesk.DEFAULTS, enabled=True, url=self.url, username="jira-user", assigned_jql="project = SD AND assignee = currentUser()", **kw)
        return server.JiraClient(dict(hc), helpdesk.auth_header(hc, {"helpdesk_password": "jpass"}), None), hc

    def test_watched(self):
        c, hc = self.client()
        self.assertTrue(hc["watch_jql"].startswith("watcher = currentUser()"))        # Standard: an
        hd = helpdesk.fetch(c, hc)
        self.assertEqual([t["key"] for t in hd["watched"]], ["SD-9"])                 # SD-1 ist zugewiesen und fällt hier weg
        self.assertIsNotNone(hd["watched"][0]["updated_ts"])
        now = time.time()
        w = helpdesk.watched(hd, {})
        self.assertTrue(w[0]["new"])                                                 # nie gesehen
        self.assertFalse(helpdesk.watched(hd, {"SD-9": now})[0]["new"])              # nach der Änderung gesehen
        self.assertTrue(helpdesk.watched(hd, {"SD-9": now - 3 * 3600})[0]["new"])    # vor 3 h gesehen, vor 2 h geändert

    def test_watch_off_and_broken(self):
        c, hc = self.client(watch_jql="")
        self.assertEqual(helpdesk.fetch(c, hc)["watched"], [])
        c, hc = self.client(watch_jql="hdkaputt")
        hd = helpdesk.fetch(c, hc)                                                   # zugewiesene Tickets kommen trotzdem
        self.assertEqual(len(hd["assigned"]), 2)
        self.assertIn("watch_error", hd)

    def test_detail(self):
        c, _ = self.client()
        d = helpdesk.detail(c, "SD-1")
        self.assertTrue(d["description"].startswith("Zeile 1\nZeile 2"))
        self.assertLessEqual(len(d["description"]), 6002)
        self.assertEqual((d["comments_total"], len(d["comments"])), (7, 5))
        self.assertEqual(d["comments"][0]["body"], "Kommentar 1")                    # neuester zuerst
        self.assertEqual(d["assignee"], "Ich")
        for bad in ("", "sd-1", "SD-1/../../myself", "SD-1?expand=x"):
            with self.assertRaises(ValueError):
                helpdesk.detail(c, bad)

    def test_settings_test_has_watch_step(self):
        form = {"url": self.url, "auth": "basic", "username": "jira-user", "secret": "jpass", "watch_jql": helpdesk.DEFAULTS["watch_jql"]}
        r = settings.test_helpdesk(form, lambda n: (None, ""))
        st = {s["id"]: s for s in r["steps"]}
        self.assertIn("2 Tickets", st["watch"]["detail"])
        self.assertEqual(settings.test_helpdesk(dict(form, watch_jql=""), lambda n: (None, ""))["steps"][-1]["status"], "skip")


class AppHd(unittest.TestCase):
    def app(self):
        os.environ["TINYOPS_HOME"] = tempfile.mkdtemp()
        cfg = server.load_config(None)
        cfg["data_dir"] = tempfile.mkdtemp()
        cfg["time"] = {"enabled": True}
        return server.App(cfg, True, {}, Path("/nonexistent/c.json"))

    def test_watch_in_overview_and_seen(self):
        a = self.app()
        f = a.overview()["flow"]
        self.assertEqual([w["key"] for w in f["hd_watch"]], ["SD-4588", "SD-4640"])
        self.assertTrue(all(w["new"] for w in f["hd_watch"]))
        self.assertEqual(f["helpdesk"][0]["next"]["action"]["open"], f["helpdesk"][0]["id"])      # Knopf öffnet das Panel, keinen Tab
        d = a.helpdesk_ticket("SD-4588")                                                         # lesen = gesehen
        self.assertIn("description", d)
        w = {x["key"]: x["new"] for x in a.overview()["flow"]["hd_watch"]}
        self.assertEqual(w, {"SD-4588": False, "SD-4640": True})
        a.helpdesk_seen({"all": "watch"})
        self.assertFalse(any(x["new"] for x in a.overview()["flow"]["hd_watch"]))
        self.assertTrue(all(q["new"] for q in a.overview()["flow"]["hd_queue"]))                  # die Queue bleibt davon unberührt

    def test_ticket_only_known(self):
        a = self.app()
        a.overview()
        self.assertEqual(a.helpdesk_ticket("SD-4690")["key"], "SD-4690")
        for bad in ("SD-1", "DLP-101", "../x"):
            with self.assertRaises(server.UserError):
                a.helpdesk_ticket(bad)
        self.assertEqual(a.helpdesk_seen({"keys": ["SD-4711", "nix da", "x" * 300]})["seen"], 1)


class Small(unittest.TestCase):
    def test_seen_updates_time(self):
        st = links.Store(Path(tempfile.mkdtemp()) / "t.db")
        st.hd_seen_add(["SD-1"])
        t1 = st.hd_seen_ts()["SD-1"]
        time.sleep(0.02)
        st.hd_seen_add(["SD-1"])
        self.assertGreater(st.hd_seen_ts()["SD-1"], t1)
        self.assertEqual(st.hd_seen(), {"SD-1"})

    def test_first_start_race(self):
        """Zwei Threads öffnen eine frische Datenbank gleichzeitig: Früher brach das mit «duplicate column name» ab."""
        for _ in range(8):
            d = Path(tempfile.mkdtemp())
            st, errs = links.Store(d / "t.db"), []

            def go():
                try:
                    st.agent_runs(limit=1) if hasattr(st, "agent_runs") else st.hd_seen()
                    st.hd_seen_add(["SD-1"])
                    timesheet.TimeBook(d / "t.db").current()
                except Exception as e:      # noqa: BLE001
                    errs.append(str(e))
            ts = [threading.Thread(target=go) for _ in range(6)]
            [t.start() for t in ts]
            [t.join() for t in ts]
            self.assertEqual(errs, [])

    def test_config(self):
        cfg, err = settings.build_config({}, {"helpdesk": {"url": "https://sd.example", "watch_jql": "  watcher = currentUser()  "}})
        self.assertEqual(err, {})
        self.assertEqual(cfg["helpdesk"]["watch_jql"], "watcher = currentUser()")
        cfg, _ = settings.build_config({}, {"helpdesk": {"url": "https://sd.example", "watch_jql": ""}})
        self.assertEqual(cfg["helpdesk"]["watch_jql"], "")                                       # leer = aus, kein Standard zurück

    def test_ux_report_names_place_of_dead_clicks(self):
        log = ux.UxLog(Path(tempfile.mkdtemp()) / "u.db")
        now = time.time()
        log.add_batch("s1", [{"k": "dead", "t": "span", "c": "rcard.score", "v": "focus", "ts": now, "x": .5, "y": .5}] * 3, now=now)
        md = ux.report_md(ux.analyse(log.events(now - 60), now), 7, "0.24.0")
        self.assertIn("span in focus / rcard.score: 3×", md)

    def test_ui_contract(self):
        html = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
        for needle in ('id="fbar"', "function renderFbar()", "data-hdseen", "/api/helpdesk/ticket?key=", ".hero[data-fid]", 'data-jqlfor="hd-wjql"'):
            self.assertIn(needle, html)
        self.assertNotIn('id="fPill"', html)


if __name__ == "__main__":
    unittest.main()
