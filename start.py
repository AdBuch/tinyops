#!/usr/bin/env python3
"""tinyops-Starter: holt die neueste Version aus dem Repo (GitHub oder GitLab, je nach Remote), prüft sie und startet.

    python3 start.py                 neuestes Release holen, Selbsttest, starten
    python3 start.py --demo          alles nach «--» oder unbekannte Optionen gehen an server.py
    python3 start.py --check         nur zeigen, ob es etwas Neues gibt
    python3 start.py --no-update     ohne Netz, so wie es ist
    python3 start.py --channel main  dem Branch main folgen statt Releases (für Entwicklung)

Ablauf:
1. `git fetch --tags` von der Remote (Standard origin, sonst `git config tinyops.remote`). Ohne Netz: Start mit dem, was da ist.
2. Kanal «release»: Ist ein neueres Tag vX.Y.Z da, `git checkout --detach` auf dieses Tag.
   Kanal «main»: `git merge --ff-only` von <remote>/main.
3. Selbsttest der neuen Version (`server.py --selftest`). Schlägt er fehl, geht es zurück auf die alte Version.
4. Was neu ist, steht kurz in der Konsole. Im Panel erscheint einmal ein Hinweis mit den neuen Prüfpunkten.

Aktualisiert wird nur, wenn es gefahrlos geht: Geänderte Dateien im Checkout, ein Stand ausserhalb eines Releases oder ein
lokaler Branch verhindern das Update (mit Hinweis). Einstellungen, Zugangsdaten und Datenbank liegen ausserhalb des Repos
(`~/.config/tinyops` bzw. `data_dir`) und bleiben unberührt. `--verify` verlangt signierte Tags (`git verify-tag`).

Nur Python-Standardbibliothek. Dieser Starter importiert absichtlich nichts aus tinyops, damit ein kaputtes Update ihn nicht trifft.
"""
import argparse
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

BASE = Path(__file__).resolve().parent
TAG = re.compile(r"^v(\d+)\.(\d+)\.(\d+)$")


def say(msg):
    print("[tinyops] " + msg, flush=True)


def git(*args, timeout=60):
    try:
        r = subprocess.run(["git", "-C", str(BASE)] + list(args), capture_output=True, text=True, timeout=timeout)
        return r.returncode, r.stdout.strip(), r.stderr.strip()
    except FileNotFoundError:
        return 127, "", "git nicht gefunden"
    except subprocess.TimeoutExpired:
        return 124, "", "Zeitüberschreitung"


def ver(tag):
    m = TAG.match(tag or "")
    return tuple(int(x) for x in m.groups()) if m else None


def home_dir():
    return Path(os.environ.get("TINYOPS_HOME") or (Path.home() / ".config" / "tinyops"))


def current_tag():
    rc, out, _ = git("tag", "--points-at", "HEAD")
    tags = [t for t in out.splitlines() if ver(t)]
    return max(tags, key=ver) if tags else ""


def latest_tag():
    rc, out, _ = git("tag", "--list", "v*")
    tags = [t for t in out.splitlines() if ver(t)]
    return max(tags, key=ver) if tags else ""


def changelog_between(old, new):
    """Die CHANGELOG-Abschnitte nach `old` bis einschliesslich `new` (Versionen ohne v)."""
    try:
        text = (BASE / "CHANGELOG.md").read_text(encoding="utf-8")
    except OSError:
        return ""
    out, take = [], False
    for ln in text.splitlines():
        m = re.match(r"^## \[(\d+\.\d+\.\d+)\]", ln)
        if m:
            v = tuple(int(x) for x in m.group(1).split("."))
            take = (old is None or v > old) and v <= new
        if take:
            out.append(ln)
    return "\n".join(out).strip()


def qa_new(old, new):
    """Neue Prüfpunkte (Abschnitte «## X.Y.Z» in QA-CHECKLIST.md) zwischen den Versionen."""
    try:
        text = (BASE / "QA-CHECKLIST.md").read_text(encoding="utf-8")
    except OSError:
        return 0
    n, take = 0, False
    for ln in text.splitlines():
        m = re.match(r"^##\s+(\d+\.\d+\.\d+)", ln)
        if ln.startswith("## "):
            take = bool(m) and (old is None or tuple(int(x) for x in m.group(1).split(".")) > old) and tuple(int(x) for x in m.group(1).split(".")) <= new
            continue
        if take and re.match(r"^\s*- \[[ xX]\] `", ln):
            n += 1
    return n


def selftest(server_args):
    cmd = [sys.executable, str(BASE / "server.py"), "--selftest"]
    if "--config" in server_args:
        i = server_args.index("--config")
        cmd += server_args[i:i + 2]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=180, env=dict(os.environ, TINYOPS_NO_WATCHDOG="1"))
    except subprocess.TimeoutExpired:
        return False, "Selbsttest nach 180 s abgebrochen"
    return r.returncode == 0, (r.stdout + r.stderr).strip()


def note_update(old, new, ok, qa_count, msg=""):
    """Für den Hinweis im Panel (einmal anzeigen, dann «gesehen»)."""
    try:
        h = home_dir()
        h.mkdir(parents=True, exist_ok=True)
        (h / "last-update.json").write_text(json.dumps({"from": old, "to": new, "ok": ok, "qa_new": qa_count, "message": msg[:500],
                                                         "ts": time.time(), "seen": False}, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass


def update(args, server_args):
    """Gibt (geändert, Text) zurück. Ändert nie etwas, wenn es nicht gefahrlos geht."""
    if not (BASE / ".git").exists():
        return False, "Kein Git-Checkout (z. B. aus einem ZIP): kein Update, Start wie vorhanden."
    rc, remote, _ = git("config", "--get", "tinyops.remote")
    remote = remote or "origin"
    rc, url, _ = git("remote", "get-url", remote)
    if rc:
        return False, "Keine Remote «%s». Einrichten: git remote add %s <URL des Repos>" % (remote, remote)
    rc, _, err = git("fetch", "--tags", "--prune", "--quiet", remote, timeout=args.timeout)
    if rc:
        return False, "Nicht erreichbar (%s): %s. Start mit dem, was da ist." % (re.sub(r"//[^@/]+@", "//***@", url), err.splitlines()[-1][:200] if err else rc)
    rc, dirty, _ = git("status", "--porcelain", "--untracked-files=no")
    if dirty:
        return False, "Geänderte Dateien im Checkout (%d), kein Update. Erst committen oder verwerfen." % len(dirty.splitlines())
    old_sha = git("rev-parse", "HEAD")[1]
    if args.channel == "main":
        rc, branch, _ = git("symbolic-ref", "--short", "-q", "HEAD")
        if branch != "main":
            return False, "Kanal main braucht den Branch main (jetzt: %s)." % (branch or "kein Branch")
        rc, ahead, _ = git("rev-list", "--count", "HEAD..%s/main" % remote)
        if rc or ahead in ("", "0"):
            return False, "Auf dem neuesten Stand von %s/main." % remote
        rc, _, err = git("merge", "--ff-only", "--quiet", "%s/main" % remote)
        if rc:
            return False, "main lässt sich nicht vorspulen (%s). Lokale Commits?" % err[:200]
        target, label_old, label_new = git("rev-parse", "HEAD")[1], old_sha[:8], git("rev-parse", "--short", "HEAD")[1]
    else:
        cur, new = current_tag(), latest_tag()
        if not new:
            return False, "Keine Release-Tags auf %s." % remote
        rc, branch, _ = git("symbolic-ref", "--short", "-q", "HEAD")
        if branch:                    # auf einem Branch wird entwickelt: den lässt der Starter in Ruhe
            return False, "Checkout steht auf dem Branch %s, nicht auf einem Release: kein Update. Auf Releases wechseln: git checkout %s" % (branch, new)
        if not cur:
            return False, "Checkout steht nicht auf einem Release (%s), kein Update. Auf Releases wechseln: git checkout %s" % (branch or old_sha[:8], new)
        if ver(new) <= ver(cur):
            return False, "Auf dem neuesten Stand (%s)." % cur
        if args.check:
            return False, "Neu verfügbar: %s (du hast %s)." % (new, cur)
        if args.verify:
            rc, _, err = git("verify-tag", new)
            if rc:
                return False, "%s ist nicht gültig signiert (%s), kein Update." % (new, err.splitlines()[-1][:120] if err else rc)
        rc, _, err = git("checkout", "--quiet", "--detach", new)
        if rc:
            return False, "Wechsel auf %s fehlgeschlagen: %s" % (new, err[:200])
        target, label_old, label_new = new, cur, new
    if args.check:
        return False, ""
    # neue Version prüfen, sonst zurück
    if not args.no_selftest:
        ok, out = selftest(server_args)
        if not ok:
            git("checkout", "--quiet", "--detach", old_sha) if args.channel != "main" else git("reset", "--quiet", "--keep", old_sha)
            fails = [ln.strip() for ln in out.splitlines() if ln.strip().startswith("FAIL")][:5]
            msg = "Selbsttest von %s fehlgeschlagen, zurück auf %s.%s" % (label_new, label_old, ("\n  " + "\n  ".join(fails)) if fails else "")
            note_update(label_old, label_new, False, 0, msg)
            return False, msg
    o, n = ver(label_old), ver(label_new)
    count = qa_new(o, n) if n else 0
    note_update(label_old, label_new, True, count)
    news = changelog_between(o, n) if n else ""
    text = "Aktualisiert: %s → %s." % (label_old, label_new)
    if count:
        text += (" 1 neuer Prüfpunkt" if count == 1 else " %d neue Prüfpunkte" % count) + " im Tab «Prüfen»."
    if news:
        lines = news.splitlines()
        text += "\n\n" + "\n".join(lines[:30]) + ("\n… (mehr in CHANGELOG.md)" if len(lines) > 30 else "")
    return True, text


def main(argv=None):
    ap = argparse.ArgumentParser(description="Startet tinyops und holt vorher die neueste Version.", add_help=True)
    ap.add_argument("--check", action="store_true", help="nur prüfen, ob es etwas Neues gibt, nicht starten")
    ap.add_argument("--no-update", action="store_true", help="nicht aktualisieren, nur starten")
    ap.add_argument("--no-selftest", action="store_true", help="nach dem Update keinen Selbsttest")
    ap.add_argument("--channel", choices=("release", "main"), default=os.environ.get("TINYOPS_CHANNEL", "release"))
    ap.add_argument("--verify", action="store_true", help="nur signierte Tags übernehmen (git verify-tag)")
    ap.add_argument("--timeout", type=int, default=30, help="Sekunden für git fetch (Standard 30)")
    ap.add_argument("--no-start", action="store_true", help=argparse.SUPPRESS)      # für Tests
    args, server_args = ap.parse_known_args(argv)
    if server_args[:1] == ["--"]:
        server_args = server_args[1:]
    if not args.no_update:
        changed, text = update(args, server_args)
        if text:
            for ln in text.splitlines():
                print(("[tinyops] " + ln) if ln and not ln.startswith(("#", " ", "-", "*")) else ln, flush=True)
    if args.check or args.no_start:
        return 0
    py = sys.executable
    venv = BASE / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    if venv.exists():
        py = str(venv)
    cmd = [py, str(BASE / "server.py")] + server_args
    if os.name == "nt":
        return subprocess.call(cmd)
    os.execv(py, cmd)


if __name__ == "__main__":
    sys.exit(main())
