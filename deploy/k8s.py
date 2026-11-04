#!/usr/bin/env python3
"""tinyops nach Kubernetes bringen und prüfen. Nur Python-Standardbibliothek, läuft unter Linux, macOS und Windows.

    python deploy/k8s.py secret       Zugangsdaten als Kubernetes-Secret ablegen (einmal, danach nur bei Änderungen)
    python deploy/k8s.py release      Tests, Image bauen, hochladen, ausrollen (alles in einem)
    python deploy/k8s.py forward      Panel auf http://localhost:8765 öffnen (port-forward, kein Ingress nötig)
    python deploy/k8s.py preflight    Verbindungen im Pod prüfen (GitLab, Jira, Modell), wie im echten Betrieb
    python deploy/k8s.py logs | status | token | build | push | deploy | reseed | undeploy | purge

Einstellungen: deploy/deploy.local.json (Vorlage: deploy/deploy.example.json) oder Umgebungsvariablen
TINYOPS_REGISTRY, TINYOPS_NAMESPACE, TINYOPS_CONTEXT, TINYOPS_DOCKER (docker oder podman).
Mit --dry-run wird nur angezeigt, was ausgeführt würde.
"""
import argparse
import base64
import getpass
import json
import os
import secrets as pysecrets
import shutil
import subprocess
import sys
import tempfile
import time
import webbrowser
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
APP = "tinyops"
SECRET = "tinyops"
# Secret-Schlüssel → Umgebungsvariable zum Befüllen (sonst Rückfrage). Die Namen im Pod beginnen mit TINYOPS_.
KEYS = [("TINYOPS_ACCESS_TOKEN", None, "Zugriffstoken für das Panel (leer lassen: wird erzeugt)"),
        ("TINYOPS_GITLAB_TOKEN", "GITLAB_TOKEN", "GitLab-Token (read_api)"),
        ("TINYOPS_JIRA_TOKEN", "JIRA_TOKEN", "Jira-Token (leer lassen, wenn Jira nicht genutzt wird)"),
        ("TINYOPS_SONAR_TOKEN", "SONAR_TOKEN", "Sonar-Token (leer lassen, wenn Sonar nicht genutzt wird)"),
        ("TINYOPS_LLM_KEY", "LLM_KEY", "Schlüssel des Sprachmodells (meist leer)")]


class Fail(SystemExit):
    pass


def die(msg):
    print("Fehler: %s" % msg, file=sys.stderr)
    raise Fail(1)


class Ctx:
    def __init__(self, dry):
        self.dry = dry
        cfg = {}
        f = HERE / "deploy.local.json"
        if f.exists():
            try:
                cfg = json.loads(f.read_text(encoding="utf-8"))
            except ValueError as e:
                die("%s ist kein gültiges JSON: %s" % (f, e))
        env = os.environ
        self.registry = (env.get("TINYOPS_REGISTRY") or cfg.get("registry") or "").strip().rstrip("/")
        self.ns = (env.get("TINYOPS_NAMESPACE") or cfg.get("namespace") or "tinyops").strip()
        self.context = (env.get("TINYOPS_CONTEXT") or cfg.get("context") or "").strip()
        self.docker = (env.get("TINYOPS_DOCKER") or cfg.get("docker") or "docker").strip()
        self.kubectl = (env.get("TINYOPS_KUBECTL") or "kubectl").strip()

    # -- Befehle ausführen
    def need_registry(self):
        if not self.registry or "example.com" in self.registry:
            die("Keine Registry eingestellt. deploy/deploy.example.json nach deploy/deploy.local.json kopieren und 'registry' eintragen "
                "(zum Beispiel registry.firma.ch/team) oder TINYOPS_REGISTRY setzen.")

    def kube(self, *args, ns=True):
        cmd = [self.kubectl] + (["--context", self.context] if self.context else []) + (["-n", self.ns] if ns else []) + list(args)
        return cmd

    def run(self, cmd, capture=False, check=True, stdin=None):
        shown = " ".join(cmd)
        if self.dry:
            print("[dry-run] %s" % shown)
            return subprocess.CompletedProcess(cmd, 0, "", "")
        print("$ %s" % shown, flush=True)
        if shutil.which(cmd[0]) is None:
            die("%s ist nicht installiert oder nicht im PATH." % cmd[0])
        r = subprocess.run(cmd, text=True, capture_output=capture, input=stdin)
        if check and r.returncode != 0:
            if capture and r.stderr:
                print(r.stderr.strip(), file=sys.stderr)
            die("%s ist fehlgeschlagen (Exit %d)." % (cmd[0], r.returncode))
        return r

    # -- Image
    def tag(self):
        """Image-Tag. Sauberer Stand genau auf dem Release-Tag vX.Y.Z: «X.Y.Z». Sonst «X.Y.Z-<sha>» (Docker erlaubt kein «+»);
        mit lokalen Änderungen zusätzlich «-dirty-HHMMSS». TINYOPS_TAG überschreibt alles."""
        if os.environ.get("TINYOPS_TAG"):
            return os.environ["TINYOPS_TAG"]
        ver = version()
        try:
            git = lambda *x: subprocess.run(["git", *x], cwd=ROOT, capture_output=True, text=True, check=True).stdout.strip()
            sha = git("rev-parse", "--short", "HEAD")
            dirty = git("status", "--porcelain")
            on_tag = subprocess.run(["git", "describe", "--exact-match", "--tags", "HEAD"], cwd=ROOT, capture_output=True, text=True).stdout.strip() == "v" + ver
            if on_tag and not dirty:
                return ver
            return "%s-%s%s" % (ver, sha, "-dirty-" + time.strftime("%H%M%S") if dirty else "")
        except (OSError, subprocess.CalledProcessError):
            return "%s-%s" % (ver, time.strftime("%Y%m%d-%H%M%S"))

    def image(self):
        self.need_registry()
        return "%s/%s:%s" % (self.registry, APP, self.tag())


def version():
    """Die Version steht nur in server.py (VERSION); hier gelesen, ohne server.py zu importieren."""
    import re
    m = re.search(r'^VERSION = "(\d+\.\d+\.\d+)"', (ROOT / "server.py").read_text(encoding="utf-8"), re.M)
    if not m:
        die("VERSION in server.py nicht gefunden.")
    return m.group(1)


def cmd_test(c, a):
    c.run([sys.executable, "-m", "unittest", "discover", "-s", str(ROOT / "tests"), "-p", "test_*.py"])


def cmd_build(c, a):
    img = c.image()
    c.run([c.docker, "build", "--build-arg", "VERSION=" + version(), "-t", img, str(ROOT)])
    print("Image: %s" % img)
    return img


def cmd_push(c, a):
    c.run([c.docker, "push", a.image or c.image()])


def secret_exists(c):
    return c.run(c.kube("get", "secret", SECRET, "-o", "name"), capture=True, check=False).returncode == 0


def existing_secret(c):
    r = c.run(c.kube("get", "secret", SECRET, "-o", "json"), capture=True, check=False)
    if r.returncode != 0 or not r.stdout:
        return {}
    data = json.loads(r.stdout).get("data") or {}
    return {k: base64.b64decode(v).decode() for k, v in data.items()}


def cmd_secret(c, a):
    """Legt das Secret an oder aktualisiert es. Bestehende Werte bleiben, wenn du nichts Neues eingibst."""
    have = existing_secret(c) if not c.dry else {}
    new = {}
    for key, env, label in KEYS:
        val = (os.environ.get(env) if env else None) or os.environ.get(key)
        if not val and not c.dry and not a.no_prompt:
            hint = " [bleibt wie gesetzt]" if key in have else ""
            val = getpass.getpass("%s%s: " % (label, hint)).strip()
        if val:
            new[key] = val.strip()
    merged = dict(have)
    merged.update(new)
    if "TINYOPS_ACCESS_TOKEN" not in merged:
        merged["TINYOPS_ACCESS_TOKEN"] = pysecrets.token_urlsafe(32)
        print("Zugriffstoken erzeugt. Anzeigen mit: python deploy/k8s.py token")
    if "TINYOPS_GITLAB_TOKEN" not in merged and not c.dry:
        die("Der GitLab-Token fehlt. GITLAB_TOKEN setzen oder das Skript in einem Terminal starten, dann fragt es danach.")
    ensure_ns(c)
    # Über eine Datei mit Rechten 600 statt über die Befehlszeile, damit nichts in der Prozessliste steht
    fd, path = tempfile.mkstemp(prefix="tinyops-secret-")
    try:
        os.chmod(path, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            for k, v in merged.items():
                f.write("%s=%s\n" % (k, v))
        manifest = c.run(c.kube("create", "secret", "generic", SECRET, "--from-env-file", path, "--dry-run=client", "-o", "yaml"), capture=True)
        c.run(c.kube("apply", "-f", "-"), stdin=manifest.stdout)
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass
    print("Secret %s gespeichert (%s)." % (SECRET, ", ".join(sorted(merged))))


def ensure_ns(c):
    r = c.run(c.kube("create", "namespace", c.ns, "--dry-run=client", "-o", "yaml", ns=False), capture=True)
    c.run(c.kube("apply", "-f", "-", ns=False), stdin=r.stdout)


def cmd_deploy(c, a):
    img = a.image or c.image()
    ensure_ns(c)
    if not c.dry and not secret_exists(c):
        die("Das Secret fehlt. Erst: python deploy/k8s.py secret")
    # Manifeste rendern und das Image direkt einsetzen: so startet nie ein Pod mit einem Platzhalter-Image
    rendered = c.run(c.kube("kustomize", str(HERE / "k8s"), ns=False), capture=True).stdout
    if not c.dry and "image: tinyops:latest" not in rendered:
        die("Im gerenderten Manifest fehlt 'image: tinyops:latest'. Wurde deploy/k8s/deployment.yaml verändert?")
    c.run(c.kube("apply", "-f", "-"), stdin=rendered.replace("image: tinyops:latest", "image: %s" % img))
    r = c.run(c.kube("rollout", "status", "deployment/%s" % APP, "--timeout=180s"), check=False)
    if r.returncode != 0:
        print("\nDer Pod ist nicht bereit geworden. Hinweise:", file=sys.stderr)
        c.run(c.kube("get", "pods", "-l", "app=%s" % APP), check=False)
        c.run(c.kube("describe", "pods", "-l", "app=%s" % APP), check=False)
        c.run(c.kube("logs", "deployment/%s" % APP, "--all-containers", "--tail=60"), check=False)
        die("Rollout fehlgeschlagen. Häufig: ImagePullBackOff (Registry-Zugang im Cluster), Pending (keine StorageClass fürs Volume), "
            "CrashLoop (Logs oben).")
    print("\nFertig: %s läuft. Öffnen: python deploy/k8s.py forward" % img)


def cmd_release(c, a):
    cmd_test(c, a)
    a.image = cmd_build(c, a)
    cmd_push(c, a)
    cmd_deploy(c, a)


def token(c):
    return existing_secret(c).get("TINYOPS_ACCESS_TOKEN", "")


def cmd_token(c, a):
    t = token(c)
    if not t:
        die("Kein Zugriffstoken gefunden (Secret fehlt?).")
    print("http://localhost:%d/?token=%s" % (a.port, t))


def cmd_forward(c, a):
    url = "http://localhost:%d/" % a.port
    t = token(c) if not c.dry else "<token>"
    full = url + ("?token=" + t if t else "")
    print("Panel: %s\n(Strg+C beendet die Weiterleitung)" % (url + "?token=…" if t else url))
    if a.open and not c.dry:
        webbrowser.open(full)
    else:
        print("Mit Token einmal öffnen: python deploy/k8s.py token")
    c.run(c.kube("port-forward", "service/%s" % APP, "%d:8765" % a.port))


def cmd_logs(c, a):
    c.run(c.kube("logs", "deployment/%s" % APP, "--tail=%d" % a.tail) + ([] if a.no_follow else ["-f"]))


def cmd_preflight(c, a):
    c.run(c.kube("exec", "deployment/%s" % APP, "--", "python", "server.py", "--preflight"))


def cmd_status(c, a):
    c.run(c.kube("get", "deployment,pod,service", "-l", "app=%s" % APP), check=False)
    c.run(c.kube("get", "pvc,secret,configmap"), check=False)


def cmd_reseed(c, a):
    """Config zurück auf die Vorlage aus deploy/k8s/config.seed.json (verwirft Änderungen aus der Einstellungsseite)."""
    if not a.yes and not c.dry:
        die("Das ersetzt die Config im Pod durch die Vorlage. Mit --yes bestätigen.")
    c.run(c.kube("exec", "deployment/%s" % APP, "--", "rm", "-f", "/data/config.json"))
    c.run(c.kube("rollout", "restart", "deployment/%s" % APP))
    c.run(c.kube("rollout", "status", "deployment/%s" % APP, "--timeout=180s"))


def cmd_undeploy(c, a):
    """Entfernt Deployment und Service. Volume (Daten) und Secret bleiben."""
    c.run(c.kube("delete", "deployment,service", "-l", "app=%s" % APP, "--ignore-not-found"))
    print("Volume und Secret bleiben. Alles löschen: python deploy/k8s.py purge --yes")


def cmd_purge(c, a):
    if not a.yes and not c.dry:
        die("Das löscht auch Ideen, Verknüpfungen und Board (Volume) und das Secret. Mit --yes bestätigen.")
    c.run(c.kube("delete", "deployment,service", "-l", "app=%s" % APP, "--ignore-not-found"))
    c.run(c.kube("delete", "secret/%s" % SECRET, "configmap/tinyops-seed", "pvc/tinyops-data", "--ignore-not-found"))


COMMANDS = {"test": cmd_test, "build": cmd_build, "push": cmd_push, "secret": cmd_secret, "deploy": cmd_deploy, "release": cmd_release,
            "token": cmd_token, "forward": cmd_forward, "logs": cmd_logs, "preflight": cmd_preflight, "status": cmd_status,
            "reseed": cmd_reseed, "undeploy": cmd_undeploy, "purge": cmd_purge}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0], formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    ap.add_argument("command", choices=sorted(COMMANDS))
    ap.add_argument("--dry-run", action="store_true", help="nur anzeigen, nichts ausführen")
    ap.add_argument("--image", help="fertiges Image statt eines neu gebauten (build/push/deploy)")
    ap.add_argument("--port", type=int, default=8765, help="lokaler Port für forward (Standard 8765)")
    ap.add_argument("--open", action="store_true", help="forward: Browser mit Token öffnen")
    ap.add_argument("--tail", type=int, default=200)
    ap.add_argument("--no-follow", action="store_true", help="logs: nicht mitlesen")
    ap.add_argument("--no-prompt", action="store_true", help="secret: nichts abfragen, nur Umgebungsvariablen verwenden")
    ap.add_argument("--yes", action="store_true", help="reseed/purge bestätigen")
    a = ap.parse_args(argv)
    COMMANDS[a.command](Ctx(a.dry_run), a)


if __name__ == "__main__":
    main()
