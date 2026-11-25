"""0.43: Voice Prompting. Spracherkennung über einen lokalen Server, Sprachbefehle an Agenten nur mit Bestätigung."""
import json
import os
import sys
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("TINYOPS_HOME", tempfile.mkdtemp())
import llm  # noqa: E402
import server  # noqa: E402
import settings  # noqa: E402
import ui  # noqa: E402
import voice  # noqa: E402


class FakeAsr:
    """Nimmt multipart an, merkt sich Pfad und Felder, antwortet wie whisper.cpp bzw. OpenAI."""
    def __init__(self, text="Gib DLP-7 an Qwen zum Entwickeln."):
        fake = self
        self.calls, self.text, self.code = [], text, 200

        class H(BaseHTTPRequestHandler):
            def do_POST(self):
                n = int(self.headers.get("Content-Length") or 0)
                raw = self.rfile.read(n)
                b = self.headers.get("Content-Type").split("boundary=")[1].encode()
                fields = {}
                for part in raw.split(b"--" + b)[1:-1]:
                    head, _, val = part.partition(b"\r\n\r\n")
                    name = head.decode().split('name="')[1].split('"')[0]
                    fields[name] = val[:-2] if name == "file" else val[:-2].decode()
                fake.calls.append((self.path, fields, self.headers.get("Authorization")))
                body = json.dumps({"text": fake.text}).encode()
                self.send_response(fake.code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *a):
                pass
        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.url = "http://127.0.0.1:%d" % self.srv.server_address[1]
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()


class Transcribe(unittest.TestCase):
    def setUp(self):
        self.asr = FakeAsr()
        self.addCleanup(self.asr.srv.shutdown)

    def test_whispercpp(self):
        vc = dict(voice.DEFAULTS, enabled=True, kind="whispercpp", url=self.asr.url)
        text, secs, _ = voice.transcribe(vc, voice.silence_wav(2.0))
        self.assertEqual((text, round(secs)), ("Gib DLP-7 an Qwen zum Entwickeln.", 2))
        path, f, auth = self.asr.calls[0]
        self.assertEqual((path, f["language"], f["response_format"], auth), ("/inference", "de", "json", None))
        self.assertTrue(f["file"].startswith(b"RIFF"))
        self.assertNotIn("model", f)

    def test_openai_compatible_with_model_key_and_v1_in_address(self):
        vc = dict(voice.DEFAULTS, enabled=True, kind="openai", url=self.asr.url + "/v1", model="mistralai/Voxtral-Mini-3B-2507", language="auto")
        voice.transcribe(vc, voice.silence_wav(1.0), key="k1")
        path, f, auth = self.asr.calls[0]
        self.assertEqual((path, f["model"], auth), ("/v1/audio/transcriptions", "mistralai/Voxtral-Mini-3B-2507", "Bearer k1"))
        self.assertNotIn("language", f, "auto: der Server erkennt die Sprache")

    def test_refusals(self):
        vc = dict(voice.DEFAULTS, enabled=True, url=self.asr.url)
        with self.assertRaises(voice.VoiceError):
            voice.transcribe(vc, b"OggS" + b"\0" * 100)
        with self.assertRaises(voice.VoiceError):
            voice.transcribe(dict(vc, max_seconds=10), voice.silence_wav(12))
        with self.assertRaises(voice.VoiceError) as e:
            voice.transcribe(dict(vc, url="http://8.8.8.8:8178"), voice.silence_wav(1))
        self.assertIn("eigenen Netz", str(e.exception))
        with self.assertRaises(voice.VoiceError):
            voice.transcribe(dict(vc, enabled=False), voice.silence_wav(1))
        self.assertEqual(self.asr.calls, [], "nichts ging raus")

    def test_blank_and_http_error(self):
        vc = dict(voice.DEFAULTS, enabled=True, url=self.asr.url)
        self.asr.text = " [BLANK_AUDIO] "
        self.assertEqual(voice.transcribe(vc, voice.silence_wav(1))[0], "")
        self.asr.code = 404
        with self.assertRaises(voice.VoiceError) as e:
            voice.transcribe(vc, voice.silence_wav(1))
        self.assertIn("/inference", str(e.exception))

    def test_settings_clean_and_test(self):
        errors, cfg = {}, {}
        voice.clean({"enabled": True, "kind": "openai", "url": "http://10.0.0.5:8000", "model": ""}, cfg, errors)
        self.assertIn("voice.model", errors)
        errors = {}
        voice.clean({"enabled": True, "kind": "whispercpp", "url": "https://asr.example.com"}, cfg, errors)
        self.assertIn("voice.url", errors)
        errors = {}
        voice.clean({"enabled": True, "kind": "whispercpp", "url": self.asr.url, "language": "xx", "max_seconds": "999"}, cfg, errors)
        self.assertEqual((errors, cfg["voice"]["language"], cfg["voice"]["max_seconds"]), ({}, "de", 300))
        r = settings.test_voice({"kind": "whispercpp", "url": self.asr.url}, lambda n: ("", ""))
        self.assertTrue(all(s["status"] == "ok" for s in r["steps"]), r)


def app_with_agents(d):
    c = server.load_config(None)
    c.update(data_dir=str(d / "data"), connections=[],
             projects=[{"id": 1, "name": "dlp-core", "data_class": "restricted"}],
             agents=[{"id": "qwen", "name": "Qwen", "kind": "goose", "model": "qwen3", "cloud": False, "connection": "local", "workspace_root": str(d / "ws"),
                      "roles": {"develop": "/developer", "review": "/reviewer"}},
                     {"id": "claude", "name": "Claude Code", "kind": "claude", "connection": "local", "workspace_root": str(d / "ws"), "roles": {"plan": "/planner"}}])
    app = server.App(c, False, {}, d / "config.json", watchdog=False)
    app._cards = {"DLP-7": {"id": "DLP-7", "key": "DLP-7", "title": "CSV-Export", "items": [{"project_id": 1, "branch": "feature/DLP-7-export"}]},
                  "DLP-12": {"id": "DLP-12", "key": "DLP-12", "title": "Login", "items": []}}
    app.cache = {"review": [{"host": "gitlab", "project_id": 1, "iid": 47, "title": "Filter", "branch": "feature/DLP-9", "sha": "abc", "keys": ["DLP-9"]}],
                 "mine": [], "assigned": []}
    return app


class Commands(unittest.TestCase):
    def setUp(self):
        self.d = Path(tempfile.mkdtemp())
        self.app = app_with_agents(self.d)

    def cmd(self, text):
        return self.app.voice_command({"text": text})

    def test_develop_with_agent_and_start(self):
        p = self.cmd("Gib DLP 7 an Qwen zum Entwickeln und starte gleich.")
        self.assertEqual((p["kind"], p["ticket"], p["agent"], p["phase"], p["start"], p["ok"], p["via"]),
                         ("agent", "DLP-7", "qwen", "develop", True, True, "Regeln"))
        self.assertEqual((p["project_id"], p["branch"]), (1, "feature/DLP-7-export"))

    def test_plan_only_assign_and_cloud_refused_for_restricted(self):
        p = self.cmd("DLP-7 an Claude Code zum Planen, nur zuweisen")
        self.assertEqual((p["agent"], p["phase"], p["start"]), ("claude", "plan", False))
        self.assertFalse(p["ok"])
        self.assertIn("restricted", p["why"])

    def test_no_agent_named_takes_role(self):
        self.assertEqual(self.cmd("DLP-12 planen")["agent"], "claude")
        self.assertEqual(self.cmd("DLP-12 umsetzen")["agent"], "qwen")

    def test_review_of_ticket_needs_dev_run(self):
        p = self.cmd("DLP-7 Review mit Qwen")
        self.assertEqual((p["phase"], p["ok"]), ("review", False))
        self.assertIn("Entwickeln-Lauf", p["why"])
        rid = self.app.store.agent_run_add("qwen", "DLP-7", 1, "feature/DLP-7-export", "x")
        self.app.store.agent_run_update(rid, status="fertig", finished=time.time())
        p = self.cmd("DLP-7 Review mit Qwen")
        self.assertEqual((p["ok"], p["parent"]), (True, rid))

    def test_mr_review(self):
        p = self.cmd("Review für MR 47 mit Qwen bitte")
        self.assertEqual((p["kind"], p["mr"]["iid"], p["agent"], p["ticket"], p["ok"]), ("mr_review", 47, "qwen", "DLP-9", True))
        with self.assertRaises(server.UserError):
            self.cmd("Review für MR 99")

    def test_unknown_ticket_and_model_fallback(self):
        with self.assertRaises(server.UserError) as e:
            self.cmd("Mach bitte den Export fertig")
        self.assertIn("Welches Ticket", str(e.exception))
        orig_ready, orig_ask = llm.ready, llm.ask
        self.addCleanup(lambda: (setattr(llm, "ready", orig_ready), setattr(llm, "ask", orig_ask)))
        llm.ready = lambda c: True
        seen = []
        llm.ask = lambda c, k, s, p, ctx=None, what="": (seen.append(p), '{"ticket": "DLP-7", "agent": "qwen", "phase": "develop", "start": true}')[1]
        p = self.cmd("Mach bitte den Export fertig")
        self.assertEqual((p["ticket"], p["via"]), ("DLP-7", "lokales Modell"))
        self.assertIn("DLP-7: CSV-Export", seen[0])
        llm.ask = lambda *a, **k: '{"ticket": "DLP-999", "agent": "qwen"}'
        with self.assertRaises(server.UserError):
            self.cmd("Mach bitte den Export fertig")

    def test_changed_plan_is_checked_again(self):
        p = self.app.voice_command({"text": "DLP-7 an Qwen", "plan": {"ticket": "DLP-7", "agent": "claude", "phase": "develop", "start": True}})
        self.assertFalse(p["ok"])
        self.assertIn("Rolle", p["warn"])


class Run(unittest.TestCase):
    def setUp(self):
        self.d = Path(tempfile.mkdtemp())
        self.app = app_with_agents(self.d)
        self.calls = []

        def fake(action, b):
            self.calls.append((action, dict(b)))
            if action == "prompt":
                return {"allowed": True, "prompt": "AUFTRAG", "repo": {"state": "git"}}
            if action == "assign":
                return {"id": 5}
            return {"id": b.get("run")}
        self.app.agent_action = fake

    def test_assign_and_start_with_spoken_words(self):
        out = self.app.voice_run({"ticket": "DLP-7", "agent": "qwen", "phase": "develop", "start": True, "text": "Gib DLP-7 an Qwen, Umlaute beachten"})
        self.assertEqual(([c[0] for c in self.calls], out["id"], out["started"]), (["prompt", "assign", "start"], 5, True))
        prompt = self.calls[2][1]["prompt"]
        self.assertTrue(prompt.startswith("AUFTRAG"))
        self.assertIn("## Dein gesprochener Auftrag (wörtlich)\n\nGib DLP-7 an Qwen, Umlaute beachten", prompt)
        self.assertEqual((self.calls[1][1]["project_id"], self.calls[1][1]["branch"]), (1, "feature/DLP-7-export"))
        rows = [r for r in self.app.audit_log.export() if r["action"] == "voice.run"]
        self.assertEqual(len(rows), 1)
        self.assertNotIn("Umlaute", json.dumps(rows[0], ensure_ascii=False), "Im Verlauf steht die Aktion, nicht der Wortlaut")

    def test_only_assign(self):
        self.app.voice_run({"ticket": "DLP-7", "agent": "qwen", "phase": "develop", "start": False, "text": "nur zuweisen"})
        self.assertEqual([c[0] for c in self.calls], ["prompt", "assign"])

    def test_refused_plan_runs_nothing(self):
        with self.assertRaises(server.UserError):
            self.app.voice_run({"ticket": "DLP-7", "agent": "claude", "phase": "develop", "text": "x"})
        with self.assertRaises(server.UserError):
            self.app.voice_run({"ticket": "DLP-404", "agent": "qwen", "text": "x"})
        self.assertEqual(self.calls, [])

    def test_mr_review_goes_through_review_start(self):
        got = []
        self.app.review_start = lambda b: (got.append(b), {"id": 8, "agent": "Qwen"})[1]
        out = self.app.voice_run({"mr": {"iid": 47}, "agent": "qwen", "text": "Review für MR 47, nur der Filter"})
        self.assertEqual((out["id"], got[0]["iid"], got[0]["ticket"], got[0]["goal"]), (8, 47, "DLP-9", "Review für MR 47, nur der Filter"))

    def test_demo_runs_nothing(self):
        self.app.demo = True
        with self.assertRaises(server.UserError):
            self.app.voice_run({"ticket": "DLP-7", "agent": "qwen", "text": "x"})


class Ui(unittest.TestCase):
    def test_parts(self):
        js = ui.source(ROOT)
        for s in ("/api/voice/transcribe", "/api/voice/command", "/api/voice/run", "getUserMedia", "VOICE_FIELDS", "encodeWav"):
            self.assertIn(s, js)


if __name__ == "__main__":
    unittest.main()
