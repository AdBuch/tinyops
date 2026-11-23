"""Update aus dem Panel und tinyops als Dienst (0.40).

Update: tinyops fragt höchstens alle 6 Stunden mit `git ls-remote` nach Release-Tags (ändert dabei nichts am Checkout).
Ist ein neueres da, zeigt das Panel es an. «Aktualisieren» lässt `start.py --no-start` laufen: derselbe Weg wie beim Start
(holen, Selbsttest, bei Fehlern zurück auf die alte Version). Hat sich die Version geändert, startet tinyops sich selbst neu
(gleicher Prozess, gleiche Argumente), das Panel lädt danach neu.

Dienst (nur Linux mit systemd): `server.py --install-service` oder der Knopf in den Einstellungen legt einen Benutzer-Dienst an
(`~/.config/systemd/user/tinyops.service`, kein sudo). Er startet tinyops über `start.py` bei der Anmeldung und nach einem Absturz.
Ohne Anmeldung (z. B. nach einem Neustart des Rechners) läuft er erst mit `loginctl enable-linger`; das sagt tinyops dazu.

Aktualisiert wird nur, wenn es gefahrlos geht. Wie beim Starter verhindern geänderte Dateien, ein Branch statt eines Releases oder
ein Checkout ohne Git das Update, mit Grund."""
import os
import re
import shlex
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

import apicalls
import tlog

log = tlog.get("update")
TAG = re.compile(r"^v(\d+)\.(\d+)\.(\d+)$")
CHECK_EVERY = 6 * 3600
UNIT = "tinyops.service"


def ver(tag):
    m = TAG.match(tag or "")
    return tuple(int(x) for x in m.groups()) if m else None


def release_url(remote_url, tag):
    """Link auf die Release-Seite, wenn das Repo auf GitHub liegt; sonst leer."""
    m = re.match(r"^(?:https://github\.com/|git@github\.com:|ssh://git@github\.com/)([\w.-]+)/([\w.-]+?)(?:\.git)?/?$", remote_url or "")
    return "https://github.com/%s/%s/releases/tag/%s" % (m.group(1), m.group(2), tag) if m and tag else ""


class Updater:
    def __init__(self, base, version, argv=None, unit_dir=None):
        self.base = Path(base)
        self.version = version
        self.argv = [a for a in (sys.argv[1:] if argv is None else argv) if a not in ("--install-service", "--remove-service")]
        self.unit_dir = Path(unit_dir) if unit_dir else Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "systemd" / "user"
        self._st, self._lock, self._checking, self.busy = None, threading.Lock(), False, False

    def _git(self, *args, timeout=30):
        try:
            r = subprocess.run(["git", "-C", str(self.base)] + list(args), capture_output=True, text=True, timeout=timeout, stdin=subprocess.DEVNULL)
            return r.returncode, r.stdout.strip(), r.stderr.strip()
        except FileNotFoundError:
            return 127, "", "git nicht gefunden"
        except subprocess.TimeoutExpired:
            return 124, "", "Zeitüberschreitung"

    # -- neue Version?
    def check(self):
        """Sieht nach, ob es ein neueres Release gibt, und ob ein Update von hier aus gefahrlos geht. Ändert nichts."""
        cur = "v" + self.version
        st = {"current": cur, "latest": "", "available": False, "can_update": False, "why": "", "url": "", "checked": time.time()}
        if not (self.base / ".git").exists():
            st["why"] = "Kein Git-Checkout (z. B. aus einem ZIP). Neue Versionen kommen dann über einen neuen Download."
            return st
        rc, remote, _ = self._git("config", "--get", "tinyops.remote")
        remote = remote or "origin"
        rc, url, _ = self._git("remote", "get-url", remote)
        if rc:
            st["why"] = "Keine Remote «%s» im Checkout." % remote
            return st
        apicalls.record("Update", "GIT", "ls-remote")
        rc, out, err = self._git("ls-remote", "--tags", "--refs", remote, "v*", timeout=25)
        if rc:
            st["why"] = "GitHub nicht erreichbar: %s" % (err.splitlines()[-1][:160] if err else rc)
            return st
        tags = [ln.rsplit("/", 1)[-1] for ln in out.splitlines() if ver(ln.rsplit("/", 1)[-1])]
        latest = max(tags, key=ver) if tags else ""
        st.update(latest=latest, url=release_url(url, latest))
        st["available"] = bool(latest and ver(cur) and ver(latest) > ver(cur))
        rc, branch, _ = self._git("symbolic-ref", "--short", "-q", "HEAD")
        rc2, dirty, _ = self._git("status", "--porcelain", "--untracked-files=no")
        if branch:
            st["why"] = "Der Checkout steht auf dem Branch %s (Entwicklung). Aktualisieren geht nur auf einem Release." % branch
        elif dirty:
            st["why"] = "Im Checkout sind Dateien geändert (%d). Erst verwerfen oder committen." % len(dirty.splitlines())
        else:
            st["can_update"] = st["available"]
        return st

    def status(self, force=False):
        """Letzter Stand der Prüfung. Ist er alt, wird im Hintergrund neu geprüft (die Antwort wartet nicht darauf), ausser force."""
        with self._lock:
            st, stale = self._st, not self._st or time.time() - self._st["checked"] > CHECK_EVERY
        if force:
            st = self.check()
            with self._lock:
                self._st = st
        elif stale and not self._checking:
            self._checking = True

            def work():
                try:
                    s = self.check()
                    with self._lock:
                        self._st = s
                finally:
                    self._checking = False
            threading.Thread(target=work, daemon=True, name="update-check").start()
        out = dict(st or {"current": "v" + self.version, "latest": "", "available": False, "can_update": False, "why": "", "url": "", "checked": 0})
        out["busy"] = self.busy
        return out

    # -- aktualisieren
    def disk_version(self):
        try:
            m = re.search(r'^VERSION = "([^"]+)"', (self.base / "server.py").read_text(encoding="utf-8"), re.M)
            return m.group(1) if m else ""
        except OSError:
            return ""

    def run(self, restart=True):
        """Aktualisiert über start.py (holen, Selbsttest, zurück bei Fehlern). Neue Version: Neustart nach der Antwort."""
        st = self.check()
        with self._lock:
            self._st = st
        if not st["can_update"]:
            return {"ok": False, "changed": False, "text": st["why"] or "Auf dem neuesten Stand (%s)." % st["current"]}
        if self.busy:
            return {"ok": False, "changed": False, "text": "Das Update läuft schon."}
        self.busy = True
        try:
            r = subprocess.run([sys.executable, str(self.base / "start.py"), "--no-start"] + self.argv, capture_output=True, text=True,
                               timeout=420, cwd=str(self.base), stdin=subprocess.DEVNULL)
            text = (r.stdout + ("\n" + r.stderr if r.stderr.strip() else "")).strip()
        except (OSError, subprocess.TimeoutExpired) as e:
            self.busy = False
            return {"ok": False, "changed": False, "text": "Update fehlgeschlagen: %s" % e}
        new = self.disk_version()
        changed = bool(new) and new != self.version
        log.info("Update: %s → %s (%s)", self.version, new or "?", "neu gestartet" if changed else "unverändert")
        if changed and restart:
            self.restart()
        else:
            self.busy = False
        return {"ok": changed, "changed": changed, "version": new, "text": text[-4000:]}

    def restart(self, delay=1.0):
        """Startet tinyops mit denselben Argumenten neu, nachdem die Antwort raus ist. Unter Linux und macOS derselbe Prozess
        (wichtig für den Dienst), unter Windows ein neuer."""
        cmd = [sys.executable, str(self.base / "server.py")] + self.argv

        def go():
            time.sleep(delay)
            log.info("Neustart: %s", " ".join(cmd))
            try:
                if os.name == "nt":
                    subprocess.Popen(cmd, cwd=str(self.base), creationflags=0x00000008)
                    os._exit(0)
                os.execv(cmd[0], cmd)
            except OSError as e:
                log.error("Neustart fehlgeschlagen: %s", e)
                self.busy = False
        threading.Thread(target=go, daemon=True, name="restart").start()

    # -- Dienst (systemd --user)
    def unit_text(self):
        py = sys.executable
        venv = self.base / ".venv" / "bin" / "python"
        if venv.exists():
            py = str(venv)
        cmd = " ".join(shlex.quote(x) for x in [py, str(self.base / "start.py")] + self.argv)
        path = os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin")
        return ("[Unit]\nDescription=tinyops (lokales Arbeitspanel)\nAfter=network-online.target\n\n"
                "[Service]\nType=simple\nWorkingDirectory=%s\nExecStart=%s\nRestart=on-failure\nRestartSec=5\n"
                "Environment=TINYOPS_SERVICE=1\nEnvironment=%s\n\n"
                "[Install]\nWantedBy=default.target\n") % (self.base, cmd, shlex.quote("PATH=" + path) if " " in path else "PATH=" + path)

    def _ctl(self, *args, timeout=20):
        try:
            r = subprocess.run(["systemctl", "--user"] + list(args), capture_output=True, text=True, timeout=timeout, stdin=subprocess.DEVNULL)
            return r.returncode, (r.stdout + r.stderr).strip()
        except (OSError, subprocess.TimeoutExpired) as e:
            return 1, str(e)

    def service(self):
        """Stand des Dienstes. supported: Linux mit systemctl."""
        f = self.unit_dir / UNIT
        sup = sys.platform.startswith("linux") and bool(shutil.which("systemctl"))
        out = {"supported": sup, "installed": f.exists(), "unit": str(f), "active": False, "enabled": False,
               "running_as_service": os.environ.get("TINYOPS_SERVICE") == "1", "command": "python3 %s --install-service" % shlex.quote(str(self.base / "server.py"))}
        if sup and f.exists():
            out["active"] = self._ctl("is-active", UNIT)[1].splitlines()[:1] == ["active"]
            out["enabled"] = self._ctl("is-enabled", UNIT)[1].splitlines()[:1] == ["enabled"]
            user = os.environ.get("USER") or os.environ.get("LOGNAME") or ""
            out["linger"] = (Path("/var/lib/systemd/linger") / user).exists() if user else False
        return out

    def install_service(self, now=False):
        """Dienst anlegen und einschalten. now: gleich als Dienst neu starten (dieser Prozess endet, der Dienst übernimmt)."""
        if not sys.platform.startswith("linux") or not shutil.which("systemctl"):
            raise RuntimeError("Als Dienst geht tinyops nur unter Linux mit systemd. Unter macOS und Windows startet der Launcher tinyops.")
        self.unit_dir.mkdir(parents=True, exist_ok=True)
        (self.unit_dir / UNIT).write_text(self.unit_text(), encoding="utf-8")
        for args in (("daemon-reload",), ("enable", UNIT)):
            rc, msg = self._ctl(*args)
            if rc:
                raise RuntimeError("systemctl --user %s: %s" % (" ".join(args), msg[:300]))
        if now and os.environ.get("TINYOPS_SERVICE") != "1":
            # erst diesen Prozess beenden (Port frei), dann übernimmt der Dienst; RestartSec fängt einen zu frühen Start ab
            subprocess.Popen(["sh", "-c", "sleep 2; systemctl --user restart %s" % UNIT], start_new_session=True,
                             stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            threading.Thread(target=lambda: (time.sleep(1.0), os._exit(0)), daemon=True).start()
        return self.service()

    def remove_service(self):
        """Dienst ausschalten und entfernen. Läuft tinyops gerade als Dienst, läuft es bis zum nächsten Beenden weiter."""
        f = self.unit_dir / UNIT
        if shutil.which("systemctl"):
            self._ctl("disable", UNIT)
        try:
            f.unlink()
        except FileNotFoundError:
            pass
        if shutil.which("systemctl"):
            self._ctl("daemon-reload")
        return self.service()
