"""0.44: Eingebautes Whisper. tinyops baut whisper-server (hier: Nachbau über cmake aus einem Test-Repo), lädt das Modell mit Prüfsumme,
startet den Server nur auf 127.0.0.1 und beendet ihn wieder."""
import hashlib
import json
import os
import shutil
import subprocess
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
import server  # noqa: E402
import ui  # noqa: E402
import voice  # noqa: E402
import voicekit  # noqa: E402

FAKE_SERVER = r'''#!/usr/bin/env python3
import json, sys
from http.server import BaseHTTPRequestHandler, HTTPServer
a = sys.argv
opt = lambda k: a[a.index(k) + 1]
model, port, lang = opt("-m"), int(opt("--port")), opt("-l")
class H(BaseHTTPRequestHandler):
    def do_POST(self):
        self.rfile.read(int(self.headers.get("Content-Length") or 0))
        b = json.dumps({"text": "Hallo von %s (%s, %s Threads)" % (model.rsplit("/", 1)[-1], lang, opt("-t"))}).encode()
        self.send_response(200 if self.path == "/inference" else 404)
        self.send_header("Content-Type", "application/json"); self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)
    def log_message(self, *x): pass
HTTPServer(("127.0.0.1", port), H).serve_forever()
'''
CMAKE = """cmake_minimum_required(VERSION 3.10)
project(fakewhisper NONE)
add_custom_target(whisper-server ALL
  COMMAND ${CMAKE_COMMAND} -E make_directory ${CMAKE_BINARY_DIR}/bin
  COMMAND ${CMAKE_COMMAND} -E copy ${CMAKE_SOURCE_DIR}/fake_server.py ${CMAKE_BINARY_DIR}/bin/whisper-server)
"""
MODEL_BYTES = b"ggml" + b"\x01" * 4096


def git(cwd, *a):
    subprocess.run(["git", "-c", "user.name=T", "-c", "user.email=t@x", "-c", "init.defaultBranch=main"] + list(a), cwd=cwd, check=True, capture_output=True)


def fake_repo(d):
    src = d / "repo"
    src.mkdir()
    (src / "CMakeLists.txt").write_text(CMAKE)
    (src / "fake_server.py").write_text(FAKE_SERVER)
    os.chmod(src / "fake_server.py", 0o755)
    git(src, "init", "-q")
    git(src, "add", "-A")
    git(src, "commit", "-qm", "fake")
    git(src, "tag", "v9.9.9")
    return str(src)


class Files:
    """Liefert Modelle wie huggingface.co/…/resolve/main/<datei>."""
    def __init__(self):
        fake = self
        self.hits = []

        class H(BaseHTTPRequestHandler):
            def do_GET(self):
                fake.hits.append(self.path)
                name = self.path.rsplit("/", 1)[-1]
                body = MODEL_BYTES if name.startswith("ggml-") else b""
                self.send_response(200 if body else 404)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *a):
                pass
        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.url = "http://127.0.0.1:%d/ggerganov/whisper.cpp/resolve/main/" % self.srv.server_address[1]
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()


SHA = hashlib.sha1(MODEL_BYTES).hexdigest()
MODELS = {"base": ("ggml-base-q5_1.bin", 1, SHA, "klein"), "small": ("ggml-small-q5_1.bin", 1, SHA, "Standard"),
          "bad": ("ggml-bad.bin", 1, "0" * 40, "falsche Prüfsumme")}


def wait_job(kit, secs=180):
    t0 = time.time()
    while kit.job["state"] == "läuft" and time.time() - t0 < secs:
        time.sleep(0.2)
    return kit.job


@unittest.skipUnless(shutil.which("cmake") and shutil.which("git"), "cmake und git nötig")
class Kit(unittest.TestCase):
    def setUp(self):
        self.d = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.d, True)
        self.files = Files()
        self.addCleanup(self.files.srv.shutdown)
        self.kit = voicekit.WhisperKit(self.d / "whisper", repo=fake_repo(self.d), tag="v9.9.9", model_base=self.files.url, models=MODELS)
        self.addCleanup(self.kit.stop)
        if shutil.which("whisper-server"):           # ein echtes im PATH würde das Bauen überspringen
            self.skipTest("whisper-server liegt im PATH")

    def test_setup_build_download_run_stop_remove(self):
        st = self.kit.status(mid="small")
        self.assertEqual((st["program"], st["ready"], st["running"]), ("", False, False))
        self.kit.setup("small")
        job = wait_job(self.kit)
        self.assertEqual(job["state"], "fertig", job)
        st = self.kit.status(mid="small")
        self.assertTrue(st["ready"])
        self.assertIn("von tinyops gebaut", st["program_source"])
        self.assertFalse((self.d / "whisper" / "src").exists(), "Quelltext wird nach dem Bauen gelöscht")
        self.assertEqual(self.files.hits, ["/ggerganov/whisper.cpp/resolve/main/ggml-small-q5_1.bin"])
        base = self.kit.ensure("small", "de", threads=3)
        self.assertTrue(base.startswith("http://127.0.0.1:"))
        text, _, _ = voice.transcribe(dict(voice.DEFAULTS, enabled=True, kind="whispercpp", url=base), voice.silence_wav(1))
        self.assertEqual(text, "Hallo von ggml-small-q5_1.bin (de, 3 Threads)")
        pid = self.kit.proc.pid
        self.assertEqual(self.kit.ensure("small", "de", threads=3), base, "läuft schon: kein Neustart")
        self.assertEqual(self.kit.proc.pid, pid)
        self.kit.stop()
        self.assertFalse(self.kit.running())
        self.kit.remove()
        self.assertFalse((self.d / "whisper").exists())

    def test_wrong_checksum_is_not_used(self):
        self.kit.setup("bad")
        job = wait_job(self.kit)
        self.assertEqual(job["state"], "fehler")
        self.assertIn("Prüfsumme", job["error"])
        self.assertFalse(list((self.d / "whisper" / "models").glob("ggml-bad*")))

    def test_custom_program_skips_build(self):
        prog = self.d / "mein-whisper"
        prog.write_text(FAKE_SERVER)
        os.chmod(prog, 0o755)
        self.kit.setup("base", custom=str(prog))
        self.assertEqual(wait_job(self.kit)["state"], "fertig")
        self.assertFalse((self.d / "whisper" / "bin").exists(), "nichts gebaut")
        self.assertEqual(self.kit.status(str(prog), "base")["program_source"], "eingetragen")
        base = self.kit.ensure("base", "auto", custom=str(prog))
        self.assertIn("(auto,", voice.transcribe(dict(voice.DEFAULTS, enabled=True, url=base, kind="builtin"), voice.silence_wav(1))[0])

    def test_missing_tools_explained(self):
        orig = voicekit.shutil.which
        voicekit.shutil.which = lambda n: None if n == "cmake" else orig(n)
        self.addCleanup(setattr, voicekit.shutil, "which", orig)
        self.kit.setup("small")
        job = wait_job(self.kit)
        self.assertEqual(job["state"], "fehler")
        self.assertIn("cmake", job["error"])
        self.assertIn("apt install", job["error"]) if sys.platform.startswith("linux") else None

    def test_not_set_up_says_how(self):
        with self.assertRaises(voicekit.KitError) as e:
            self.kit.ensure("small")
        self.assertIn("Einrichten", str(e.exception))

    def test_stale_server_after_restart_is_ended(self):
        prog = self.d / "whisper" / "bin"
        prog.mkdir(parents=True)
        (prog / "whisper-server").write_text(FAKE_SERVER)
        os.chmod(prog / "whisper-server", 0o755)
        (self.d / "whisper" / "models").mkdir()
        (self.d / "whisper" / "models" / "ggml-small-q5_1.bin").write_bytes(MODEL_BYTES)
        self.kit.ensure("small")
        old = self.kit.proc
        self.kit.proc = None                          # wie nach einem Update mit execv: der neue Prozess kennt ihn nicht
        voicekit.WhisperKit(self.d / "whisper", models=MODELS)
        old.wait(5)
        self.assertIsNotNone(old.poll(), "alter Server beendet")


class AppLevel(unittest.TestCase):
    def setUp(self):
        self.d = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.d, True)
        c = server.load_config(None)
        c.update(data_dir=str(self.d / "data"), voice={"enabled": True, "kind": "builtin", "builtin_model": "small"})
        self.app = server.App(c, False, {}, self.d / "config.json", watchdog=False)

    def test_builtin_default_and_status(self):
        self.assertEqual(voice.DEFAULTS["kind"], "builtin")
        st = self.app.voice_kit({})
        self.assertEqual((st["model"], st["ready"], st["tag"]), ("small", False, voicekit.TAG))
        self.assertEqual([m["id"] for m in st["models"]], ["base", "small", "turbo"])
        with self.assertRaises(server.UserError) as e:
            self.app.voice_transcribe(voice.silence_wav(1))
        self.assertIn("Einrichten", str(e.exception))

    def test_settings_clean(self):
        errors, cfg = {}, {}
        voice.clean({"enabled": True, "kind": "builtin", "builtin_model": "turbo", "threads": "4"}, cfg, errors)
        self.assertEqual((errors, cfg["voice"]["builtin_model"], cfg["voice"]["threads"]), ({}, "turbo", 4))
        voice.clean({"enabled": True, "kind": "builtin", "builtin_model": "riesig"}, cfg, errors)
        self.assertEqual(cfg["voice"]["builtin_model"], "small")

    def test_models_have_real_checksums(self):
        for mid, (fname, mib, sha1, _) in voicekit.MODELS.items():
            self.assertRegex(sha1, r"^[0-9a-f]{40}$")
            self.assertTrue(fname.startswith("ggml-") and fname.endswith(".bin"))

    def test_only_on_this_computer(self):
        self.assertIn('"/api/voice/kit"', (ROOT / "routes.py").read_text(encoding="utf-8"))

    def test_ui(self):
        js = ui.source(ROOT)
        for s in ("/api/voice/kit", "vk-setup", "vo-bmodel", "Eingebautes Whisper"):
            self.assertIn(s, js)


if __name__ == "__main__":
    unittest.main()
