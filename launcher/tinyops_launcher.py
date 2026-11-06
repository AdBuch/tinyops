#!/usr/bin/env python3
"""tinyops-Launcher: ein Doppelklick lädt tinyops aus dem Repo, hält es aktuell, startet es und öffnet den Browser.

Beim ersten Start:  git clone <Repo> in den Installationsordner, auf das neueste Release.
Bei jedem Start:    start.py im Installationsordner (holt neue Releases, Selbsttest, Rückfall bei Fehler), dann Browser.

    tinyops-launcher                    installieren bzw. aktualisieren und starten
    tinyops-launcher --demo             Optionen für tinyops einfach anhängen
    tinyops-launcher --dir D:\\tools\\tinyops --repo https://github.com/AdBuch/tinyops.git
    tinyops-launcher --no-browser       ohne Browser
    tinyops-launcher --where            zeigt Installationsordner, Repo und Version

Braucht git und Python 3.10 oder neuer auf dem Rechner (tinyops selbst läuft mit dem Python des Rechners, auch wenn der
Launcher als .exe gebaut ist). Fehlt etwas, sagt der Launcher, wie man es installiert. Einstellungen, Zugangsdaten und
Datenbank liegen wie immer in ~/.config/tinyops und haben mit dem Installationsordner nichts zu tun.
Nur Standardbibliothek.
"""
import argparse
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import urllib.request
import webbrowser
from pathlib import Path

LAUNCHER_VERSION = "0.21.1"
DEFAULT_REPO = "https://github.com/AdBuch/tinyops.git"
TAG = re.compile(r"^v(\d+)\.(\d+)\.(\d+)$")


def say(msg):
    print("[tinyops] " + msg, flush=True)


def default_dir():
    if os.name == "nt":
        return Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local") / "tinyops" / "app"
    return Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share") / "tinyops" / "app"


def find_python():
    """Ein Python ≥ 3.10 auf dem Rechner. Als .exe gebaut ist sys.executable der Launcher selbst, nicht Python."""
    cands = []
    if not getattr(sys, "frozen", False):
        cands.append([sys.executable])
    if os.environ.get("TINYOPS_PYTHON"):
        cands.insert(0, [os.environ["TINYOPS_PYTHON"]])
    if os.name == "nt":
        cands += [["py", "-3"], ["python"], ["python3"]]
    else:
        cands += [["python3"], ["python"]]
    for c in cands:
        if not shutil.which(c[0]) and not Path(c[0]).exists():
            continue
        try:
            r = subprocess.run(c + ["-c", "import sys; print('%d.%d' % sys.version_info[:2])"], capture_output=True, text=True, timeout=15)
        except (OSError, subprocess.TimeoutExpired):
            continue
        try:
            major, minor = (int(x) for x in r.stdout.strip().split("."))
        except ValueError:
            continue
        if (major, minor) >= (3, 10):
            return c
    return None


def hint_install(what):
    if what == "git":
        if os.name == "nt":
            return "git fehlt. Installieren: winget install --id Git.Git -e   (oder https://git-scm.com/download/win), dann neu starten."
        if sys.platform == "darwin":
            return "git fehlt. Installieren: xcode-select --install   (oder brew install git)."
        return "git fehlt. Installieren: sudo apt install git   (bzw. dnf/pacman)."
    if os.name == "nt":
        return "Python 3.10+ fehlt. Installieren: winget install --id Python.Python.3.13 -e   (oder https://www.python.org), dann neu starten."
    if sys.platform == "darwin":
        return "Python 3.10+ fehlt. Installieren: brew install python@3.13   (oder https://www.python.org)."
    return "Python 3.10+ fehlt. Installieren: sudo apt install python3."


def git(cwd, *args, timeout=600):
    return subprocess.run(["git", "-C", str(cwd)] + list(args), capture_output=True, text=True, timeout=timeout)


def latest_tag(d):
    r = git(d, "tag", "--list", "v*")
    tags = [t for t in r.stdout.split() if TAG.match(t)]
    return max(tags, key=lambda t: tuple(int(x) for x in TAG.match(t).groups())) if tags else ""


def install(d, repo):
    """Erster Start: klonen (ohne Blobs der alten Historie) und auf das neueste Release."""
    d.parent.mkdir(parents=True, exist_ok=True)
    say("Lade tinyops von %s nach %s …" % (repo, d))
    r = subprocess.run(["git", "clone", "--filter=blob:none", "--quiet", repo, str(d)], capture_output=True, text=True, timeout=900)
    if r.returncode:
        say("Herunterladen fehlgeschlagen: %s" % (r.stderr.strip().splitlines() or ["?"])[-1])
        return False
    tag = latest_tag(d)
    if tag:
        git(d, "-c", "advice.detachedHead=false", "checkout", "--quiet", "--detach", tag)
        say("Installiert: %s" % tag)
    else:
        say("Installiert (noch ohne Release-Tag, Stand main).")
    return True


def read_port(args_rest):
    if "--port" in args_rest:
        try:
            return int(args_rest[args_rest.index("--port") + 1])
        except (IndexError, ValueError):
            pass
    for f in (Path(os.environ.get("TINYOPS_HOME") or Path.home() / ".config" / "tinyops") / "config.json",):
        try:
            m = re.search(r'"port"\s*:\s*(\d+)', f.read_text(encoding="utf-8"))
            if m:
                return int(m.group(1))
        except OSError:
            pass
    return 8765


def open_when_up(port, timeout=90):
    url = "http://127.0.0.1:%d/" % port
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            urllib.request.urlopen(url, timeout=2).read(64)
            say("Läuft: %s" % url)
            webbrowser.open(url)
            return
        except Exception:
            time.sleep(0.7)
    say("tinyops antwortet nach %d s nicht auf %s. Die Meldungen oben zeigen, warum." % (timeout, url))


def main(argv=None):
    ap = argparse.ArgumentParser(prog="tinyops-launcher", description="Lädt tinyops, hält es aktuell und startet es.")
    ap.add_argument("--dir", default=os.environ.get("TINYOPS_APP_DIR") or str(default_dir()), help="Installationsordner")
    ap.add_argument("--repo", default=os.environ.get("TINYOPS_REPO") or DEFAULT_REPO, help="Repo, aus dem geladen wird")
    ap.add_argument("--no-browser", action="store_true", help="Browser nicht öffnen")
    ap.add_argument("--where", action="store_true", help="Installationsordner, Repo und Version zeigen")
    ap.add_argument("--version", action="store_true", help="Version des Launchers")
    args, rest = ap.parse_known_args(argv)
    if args.version:
        print("tinyops-launcher %s" % LAUNCHER_VERSION)
        return 0
    d = Path(args.dir).expanduser()
    if not shutil.which("git"):
        say(hint_install("git"))
        return 2
    py = find_python()
    if not py:
        say(hint_install("python"))
        return 2
    if args.where:
        cur = git(d, "describe", "--tags", "--always").stdout.strip() if (d / ".git").exists() else "nicht installiert"
        url = git(d, "remote", "get-url", "origin").stdout.strip() if (d / ".git").exists() else args.repo
        print("Ordner:  %s\nRepo:    %s\nVersion: %s\nPython:  %s\nLauncher: %s" % (d, url, cur, " ".join(py), LAUNCHER_VERSION))
        return 0
    if not (d / ".git").exists():
        if d.exists() and any(d.iterdir()):
            say("%s ist nicht leer und kein tinyops-Checkout. Anderen Ordner mit --dir wählen." % d)
            return 2
        if not install(d, args.repo):
            return 1
    start = d / "start.py"
    if not start.exists():
        say("%s fehlt (zu alte Version?). Einmal: git -C \"%s\" checkout --detach %s" % (start, d, latest_tag(d) or "main"))
        return 1
    if not args.no_browser and "--check" not in rest:
        threading.Thread(target=open_when_up, args=(read_port(rest),), daemon=True).start()
    env = dict(os.environ)
    if getattr(sys, "frozen", False):
        env.pop("PYTHONHOME", None)        # PyInstaller-Variablen nicht ans System-Python weitergeben
        env.pop("PYTHONPATH", None)
    try:
        return subprocess.call(py + [str(start)] + rest, cwd=str(d), env=env)
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    sys.exit(main())
