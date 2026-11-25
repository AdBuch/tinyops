"""Eingebautes Whisper (0.44): tinyops richtet die Spracherkennung selbst ein und startet sie selbst.

Für Rechner ohne Grafikkarte: whisper.cpp läuft gut auf Intel- und AMD-Prozessoren. Auf deinen Klick «Einrichten»:
1. holt tinyops den Quelltext von whisper.cpp (fester Release-Tag, `git clone`, nur lesend) und baut `whisper-server` mit cmake,
   für genau diesen Prozessor. Liegt `whisper-server` schon im PATH oder trägst du ein Programm ein, entfällt das.
2. lädt es das Modell von Hugging Face (ggerganov/whisper.cpp) und prüft die SHA1-Prüfsumme aus der Modellkarte.
3. startet es den Server nur auf 127.0.0.1, sobald du das erste Mal diktierst, und beendet ihn nach 20 Minuten ohne Nutzung
   und wenn tinyops endet.
Alles liegt in `<Datenordner>/whisper/`; «Entfernen» löscht den Ordner. Gebaut wird ohne sudo; fehlen cmake oder ein C++-Compiler,
sagt tinyops, wie du sie installierst."""
import atexit
import hashlib
import os
import signal
import platform
import shutil
import socket
import subprocess
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

import apicalls
import tlog

log = tlog.get("tinyops")

TAG = "v1.9.5"
REPO = "https://github.com/ggml-org/whisper.cpp"
MODEL_BASE = "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/"
# id: (Datei, MiB, SHA1 aus der Modellkarte, Beschreibung)
MODELS = {
    "base": ("ggml-base-q5_1.bin", 57, "a3733eda680ef76256db5fc5dd9de8629e62c5e7", "klein und schnell, für schwache Rechner; Deutsch brauchbar"),
    "small": ("ggml-small-q5_1.bin", 181, "6fe57ddcfdd1c6b07cdcc73aaf620810ce5fc771", "Standard: gut für Deutsch, auf einem üblichen Intel-Prozessor wenige Sekunden je Satz"),
    "turbo": ("ggml-large-v3-turbo-q5_0.bin", 547, "e050f7970618a659205450ad97eb95a18d69c9ee", "am genauesten, auf dem Prozessor deutlich langsamer; mit 8 Kernen oder mehr"),
}
IDLE_STOP = 20 * 60
EXE = "whisper-server.exe" if os.name == "nt" else "whisper-server"


class KitError(Exception):
    pass


def _free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def install_hint():
    sysname = platform.system()
    if sysname == "Linux":
        return "Ubuntu/Debian: sudo apt install build-essential cmake git · Fedora: sudo dnf install gcc-c++ cmake git"
    if sysname == "Darwin":
        return "macOS: xcode-select --install, dann brew install cmake"
    return "Windows: Visual Studio Build Tools (C++) und CMake installieren, oder whisper-server.exe selbst bauen und unten als Programm eintragen"


class WhisperKit:
    def __init__(self, base, repo=REPO, tag=TAG, model_base=MODEL_BASE, models=None):
        self.dir = Path(base)
        self.repo, self.tag, self.model_base = repo, tag, model_base
        self.models = models or MODELS
        self.lock = threading.Lock()
        self.job = {"state": "", "step": "", "done": 0, "total": 0, "error": "", "log": []}
        self.proc = None
        self.port = 0
        self.last_use = 0.0
        self.started_with = None
        self._idle = None
        self._reap()
        atexit.register(self.stop)

    def _reap(self):
        """Ein whisper-server, der einen Neustart von tinyops überlebt hat (Update mit execv), wird beendet. Nur unserer: Pfad im Aufruf."""
        pf = self.dir / "server.pid"
        try:
            pid = int(pf.read_text().strip())
            cmd = Path("/proc/%d/cmdline" % pid).read_bytes().decode(errors="replace")
        except (OSError, ValueError):
            return
        if "whisper-server" in cmd and str(self.dir) in cmd and pid != os.getpid():
            try:
                os.kill(pid, signal.SIGTERM)
                log.info("Eingebautes Whisper: alten Server (pid %d) beendet", pid)
            except OSError:
                pass
        pf.unlink(missing_ok=True)

    # ------------------------------------------------------------ Zustand
    def built(self):
        p = self.dir / "bin" / EXE
        return p if p.exists() else None

    def program(self, custom=""):
        """Welcher whisper-server: eingetragenes Programm, selbst gebaut, oder aus dem PATH. Mit Herkunft."""
        if custom:
            p = Path(os.path.expanduser(custom))
            return (p, "eingetragen") if p.is_file() and os.access(p, os.X_OK) else (None, "eingetragen, aber nicht ausführbar: %s" % custom)
        if self.built():
            return self.built(), "von tinyops gebaut (whisper.cpp %s)" % self.tag
        w = shutil.which("whisper-server")
        return (Path(w), "aus dem PATH") if w else (None, "")

    def model_path(self, mid):
        return self.dir / "models" / self.models[mid][0]

    def tools(self):
        """Was zum Bauen fehlt."""
        miss = [t for t in ("git", "cmake") if not shutil.which(t)]
        if os.name != "nt" and not any(shutil.which(c) for c in ("c++", "g++", "clang++")):
            miss.append("C++-Compiler")
        return miss

    def status(self, custom="", mid="small"):
        prog, src = self.program(custom)
        mid = mid if mid in self.models else "small"
        with self.lock:
            job = dict(self.job, log=self.job["log"][-12:])
        return {"program": str(prog) if prog else "", "program_source": src, "model": mid,
                "models": [{"id": k, "file": v[0], "mib": v[1], "about": v[3], "present": self.model_path(k).exists()} for k, v in self.models.items()],
                "model_present": self.model_path(mid).exists(), "running": self.running(), "port": self.port if self.running() else 0,
                "ready": bool(prog) and self.model_path(mid).exists(), "missing_tools": [] if prog else self.tools(), "hint": install_hint(),
                "job": job, "dir": str(self.dir), "tag": self.tag}

    def running(self):
        return self.proc is not None and self.proc.poll() is None

    # ------------------------------------------------------------ Einrichten (im Hintergrund, auf Klick)
    def _set(self, **kw):
        with self.lock:
            self.job.update(kw)

    def _log(self, line):
        line = line.rstrip()
        if line:
            with self.lock:
                self.job["log"] = (self.job["log"] + [line[-300:]])[-60:]

    def setup(self, mid, custom=""):
        """Startet das Einrichten im Hintergrund. Einmal gleichzeitig."""
        if mid not in self.models:
            raise KitError("Unbekanntes Modell.")
        with self.lock:
            if self.job["state"] == "läuft":
                raise KitError("Das Einrichten läuft schon.")
            self.job = {"state": "läuft", "step": "Vorbereiten", "done": 0, "total": 0, "error": "", "log": []}
        threading.Thread(target=self._setup, args=(mid, custom), name="whisper-setup", daemon=True).start()

    def _setup(self, mid, custom):
        try:
            prog, _ = self.program(custom)
            if not prog:
                self._build()
            if not self.model_path(mid).exists():
                self._download(mid)
            self._set(state="fertig", step="Bereit", error="")
            log.info("Eingebautes Whisper: bereit (%s)", self.models[mid][0])
        except KitError as e:
            self._set(state="fehler", error=str(e))
            log.warning("Eingebautes Whisper: %s", e)
        except Exception as e:      # nie den Hintergrund-Thread still sterben lassen
            self._set(state="fehler", error="Unerwartet: %s" % e)
            log.exception("Eingebautes Whisper")

    def _run(self, argv, cwd, step):
        self._set(step=step)
        self._log("$ " + " ".join(str(a) for a in argv))
        env = dict(os.environ, GIT_TERMINAL_PROMPT="0")
        with subprocess.Popen([str(a) for a in argv], cwd=str(cwd), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, errors="replace", env=env) as p:
            for line in p.stdout:
                self._log(line)
        if p.returncode:
            raise KitError("%s fehlgeschlagen (Exit %d). Die letzten Zeilen stehen unten." % (step, p.returncode))

    def _build(self):
        miss = self.tools()
        if miss:
            raise KitError("Zum Bauen fehlt: %s. %s" % (", ".join(miss), install_hint()))
        src = self.dir / "src"
        if src.exists():
            shutil.rmtree(src)
        self.dir.mkdir(parents=True, exist_ok=True)
        apicalls.record("Eingebautes Whisper", "GIT", "clone")
        self._run(["git", "clone", "--quiet", "--depth", "1", "--branch", self.tag, self.repo, src], self.dir, "Quelltext holen (whisper.cpp %s)" % self.tag)
        jobs = str(max(1, (os.cpu_count() or 2)))
        self._run(["cmake", "-B", "build", "-DCMAKE_BUILD_TYPE=Release", "-DBUILD_SHARED_LIBS=OFF", "-DWHISPER_BUILD_TESTS=OFF", "-DWHISPER_SDL2=OFF"],
                  src, "Bauen vorbereiten (cmake)")
        self._run(["cmake", "--build", "build", "-j", jobs, "--config", "Release", "--target", "whisper-server"], src,
                  "Bauen (dauert ein bis fünf Minuten)")
        found = next((p for p in (src / "build").rglob(EXE) if p.is_file()), None)
        if not found:
            raise KitError("Gebaut, aber %s nicht gefunden." % EXE)
        (self.dir / "bin").mkdir(exist_ok=True)
        shutil.copy2(found, self.dir / "bin" / EXE)
        shutil.rmtree(src, ignore_errors=True)            # Quelltext und Zwischenstände brauchen ~200 MB, das Programm 4 MB
        self._log("Programm: %s" % (self.dir / "bin" / EXE))

    def _download(self, mid):
        fname, mib, sha1, _ = self.models[mid]
        dest = self.model_path(mid)
        dest.parent.mkdir(parents=True, exist_ok=True)
        part = dest.with_suffix(".part")
        url = self.model_base + fname
        self._set(step="Modell laden (%s, %d MB)" % (fname, mib), done=0, total=mib * 1048576)
        self._log("GET " + url)
        apicalls.record("Eingebautes Whisper", "GET", "/ggerganov/whisper.cpp/resolve/main/" + fname)
        h = hashlib.sha1()
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "tinyops"}), timeout=60) as r, open(part, "wb") as f:
                total = int(r.headers.get("Content-Length") or 0)
                if total:
                    self._set(total=total)
                n = 0
                while True:
                    b = r.read(1 << 20)
                    if not b:
                        break
                    f.write(b)
                    h.update(b)
                    n += len(b)
                    self._set(done=n)
        except (urllib.error.URLError, OSError) as e:
            part.unlink(missing_ok=True)
            raise KitError("Modell nicht geladen (%s). Erreicht der Rechner huggingface.co?" % getattr(e, "reason", e))
        if h.hexdigest() != sha1:
            part.unlink(missing_ok=True)
            raise KitError("Prüfsumme des Modells stimmt nicht (erwartet %s…). Nicht verwendet." % sha1[:10])
        part.replace(dest)
        self._log("Modell geprüft (SHA1 %s…)" % sha1[:10])

    def remove(self):
        self.stop()
        with self.lock:
            if self.job["state"] == "läuft":
                raise KitError("Das Einrichten läuft noch.")
            self.job = {"state": "", "step": "", "done": 0, "total": 0, "error": "", "log": []}
        shutil.rmtree(self.dir, ignore_errors=True)

    # ------------------------------------------------------------ Betrieb
    def ensure(self, mid, lang="de", custom="", threads=0):
        """Läuft der Server mit diesem Modell? Sonst starten. Gibt die Adresse zurück."""
        prog, src = self.program(custom)
        if not prog:
            raise KitError("Das eingebaute Whisper ist noch nicht eingerichtet: Einstellungen → Sprache → «Einrichten».%s" % (" (%s)" % src if src else ""))
        model = self.model_path(mid if mid in self.models else "small")
        if not model.exists():
            raise KitError("Das Modell %s fehlt: Einstellungen → Sprache → «Einrichten»." % model.name)
        want = (str(prog), str(model), lang, int(threads or 0))
        with self.lock:
            self.last_use = time.time()
            if self.running() and self.started_with == want:
                return "http://127.0.0.1:%d" % self.port
        self.stop()
        n = int(threads or 0) or max(1, min(8, (os.cpu_count() or 2) - 1))
        port = _free_port()
        logf = open(self.dir / "server.log", "ab")
        argv = [str(prog), "-m", str(model), "--host", "127.0.0.1", "--port", str(port), "-l", lang if lang else "de", "-t", str(n), "-nt"]
        kw = {"creationflags": 0x08000000} if os.name == "nt" else {}       # kein Konsolenfenster unter Windows; sonst gleiche Prozessgruppe (Ctrl+C, systemd beenden ihn mit)
        proc = subprocess.Popen(argv, cwd=str(self.dir), stdout=logf, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, **kw)
        logf.close()
        (self.dir / "server.pid").write_text(str(proc.pid))
        t0 = time.time()
        while time.time() - t0 < 60:                       # Modell laden dauert je nach Grösse ein paar Sekunden
            if proc.poll() is not None:
                tail = (self.dir / "server.log").read_text(errors="replace")[-400:]
                raise KitError("whisper-server ist gleich beendet (Exit %s): %s" % (proc.returncode, " ".join(tail.split())[-200:]))
            try:
                socket.create_connection(("127.0.0.1", port), timeout=0.5).close()
                break
            except OSError:
                time.sleep(0.2)
        else:
            proc.kill()
            raise KitError("whisper-server antwortet nach 60 s nicht.")
        with self.lock:
            self.proc, self.port, self.started_with, self.last_use = proc, port, want, time.time()
        log.info("Eingebautes Whisper gestartet: %s, %d Threads, Port %d", model.name, n, port)
        if not self._idle:
            self._idle = threading.Thread(target=self._idle_loop, name="whisper-idle", daemon=True)
            self._idle.start()
        return "http://127.0.0.1:%d" % port

    def _idle_loop(self):
        while True:
            time.sleep(30)
            if self.running() and time.time() - self.last_use > IDLE_STOP:
                log.info("Eingebautes Whisper: %d min nicht benutzt, beendet (startet beim nächsten Diktieren wieder)", IDLE_STOP // 60)
                self.stop()

    def stop(self):
        with self.lock:
            p, self.proc, self.started_with = self.proc, None, None
        (self.dir / "server.pid").unlink(missing_ok=True)
        if p is not None and p.poll() is None:
            p.terminate()
            try:
                p.wait(5)
            except subprocess.TimeoutExpired:
                p.kill()



