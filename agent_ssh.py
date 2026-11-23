"""Verbindung zu den Agenten-Rechnern (0.40 aus agents.py gelöst): SSH-Aufruf, verständliche Fehler, Prüfen für die Einstellungen."""
import os
import shlex
import shutil
import subprocess
from pathlib import Path

import secretstore as store
import tlog
from agent_cmd import KINDS, _sh_path
from agent_rules import AgentError

log = tlog.get("agents")


# ------------------------------------------------------------------ SSH
def ssh_args(conn):
    a = [os.environ.get("TINYOPS_SSH") or "ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=8", "-o", "ServerAliveInterval=10",
         "-o", "StrictHostKeyChecking=%s" % ("accept-new" if conn.get("host_key") == "accept-new" else "yes"), "-p", str(conn.get("port") or 22)]
    if conn.get("identity_file"):
        a += ["-o", "IdentitiesOnly=yes", "-i", os.path.expanduser(conn["identity_file"])]
    target = ("%s@%s" % (conn["user"], conn["host"])) if conn.get("user") else conn["host"]
    return a + ["--", target]


def _friendly(err, conn):
    e = (err or "").strip()
    low = e.lower()
    where = conn.get("host", "?")
    if "host key verification failed" in low or "no matching host key" in low:
        return ("Der Host-Schlüssel von %s ist nicht bekannt oder hat sich geändert. Einmal im Terminal «ssh %s» ausführen und den Schlüssel prüfen und bestätigen, "
                "oder bei der Verbindung «accept-new» wählen (vertraut beim ersten Mal, warnt bei Änderungen)." % (where, where))
    if "permission denied" in low:
        return ("Anmeldung an %s abgelehnt. Benutzer und Schlüsseldatei prüfen. tinyops fragt nie nach Passwörtern; ein Schlüssel mit Passphrase "
                "braucht einen laufenden ssh-agent." % where)
    if "could not resolve" in low or "name or service not known" in low:
        return "Der Name %s lässt sich nicht auflösen (VPN verbunden? Tippfehler?)." % where
    if "timed out" in low or "no route" in low or "connection refused" in low:
        return "%s ist nicht erreichbar (%s). VPN, Port und Firewall prüfen." % (where, e.splitlines()[-1][:120] if e else "Zeitüberschreitung")
    return "SSH zu %s fehlgeschlagen: %s" % (where, (e.splitlines()[-1] if e else "unbekannter Fehler")[:200])


def run_remote(conn, script, timeout=25):
    args = ssh_args(conn) + ["sh -c " + shlex.quote(script)]
    try:
        r = subprocess.run(args, capture_output=True, timeout=timeout, stdin=subprocess.DEVNULL)
    except FileNotFoundError:
        raise AgentError("Der SSH-Client «ssh» wurde nicht gefunden. Windows: «OpenSSH-Client» als optionales Feature installieren; Container: openssh-client im Image.")
    except subprocess.TimeoutExpired:
        raise AgentError("SSH zu %s: keine Antwort innerhalb von %d s." % (conn.get("host"), timeout))
    out = r.stdout.decode("utf-8", "replace")[:300000]
    err = r.stderr.decode("utf-8", "replace")[:20000]
    if r.returncode == 255:
        raise AgentError(_friendly(err, conn))
    return r.returncode, out, err


TOKEN_RE = store.TOKEN_RE


# ------------------------------------------------------------------ Prüfen (für die Einstellungen)
def probe(agent, conn, workdir_hint=""):
    """Fakten über Ziel und Agent. Schreibt nichts außer dem Ordner ~/.tinyops/runs. Gibt ein Dict zurück oder wirft AgentError."""
    if conn is None:
        spec = KINDS[agent["kind"]]
        root = os.path.expanduser(agent["workspace_root"])
        d = Path(os.environ.get("TINYOPS_RUNS_PROBE") or Path.home() / ".tinyops" / "probe")
        try:
            d.mkdir(parents=True, exist_ok=True)
            writable = os.access(d, os.W_OK)
        except OSError:
            writable = False
        return {"os": os.name, "tmux": None, "workspace": os.path.isdir(root), "bin": (shutil.which(spec["bin"]) or "") if spec["bin"] else None, "writable": writable,
                "git": bool(shutil.which("git")), "sh": bool(shutil.which("sh")), "user": None, "root": None, "sudo": None, "docker": None}
    wd = _sh_path(agent["workspace_root"])
    binpart = ""
    if KINDS[agent["kind"]]["bin"]:
        binpart = 'echo "bin:$("${SHELL:-/bin/sh}" -l -c \'command -v %s\' 2>/dev/null)"; ' % shlex.quote(KINDS[agent["kind"]]["bin"])[1:-1] if False else \
                  'echo "bin:$("${SHELL:-/bin/sh}" -l -c %s 2>/dev/null)"; ' % shlex.quote("command -v " + KINDS[agent["kind"]]["bin"])
    script = ('echo "TINYOPS_OK"; echo "os:$(uname -s)"; '
              '(command -v tmux >/dev/null 2>&1 && echo "tmux:yes") || echo "tmux:no"; '
              '([ -d %s ] && echo "ws:yes") || echo "ws:no"; '
              '(mkdir -p "$HOME/.tinyops/runs" 2>/dev/null && [ -w "$HOME/.tinyops/runs" ] && echo "runs:yes") || echo "runs:no"; '
              '(command -v git >/dev/null 2>&1 && echo "git:yes") || echo "git:no"; '
              'echo "user:$(id -un 2>/dev/null)"; echo "uid:$(id -u 2>/dev/null)"; '
              '(command -v sudo >/dev/null 2>&1 && sudo -n true >/dev/null 2>&1 && echo "sudo:yes") || echo "sudo:no"; '
              '([ -w /var/run/docker.sock ] && echo "docker:yes") || echo "docker:no"; ' % wd) + binpart
    rc, out, err = run_remote(conn, script, timeout=25)
    facts = {}
    for line in out.splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            facts[k.strip()] = v.strip()
    if "os" not in facts and "tmux" not in facts:
        raise AgentError("Unerwartete Antwort vom Zielhost (Login-Banner oder Shell, die nichts ausgibt?).")
    return {"os": facts.get("os", "?"), "tmux": facts.get("tmux") == "yes", "workspace": facts.get("ws") == "yes",
            "bin": facts.get("bin", "") if KINDS[agent["kind"]]["bin"] else None, "writable": facts.get("runs") == "yes",
            "git": facts.get("git") == "yes", "sh": True, "user": facts.get("user", "?"), "root": facts.get("uid") == "0",
            "sudo": facts.get("sudo") == "yes", "docker": facts.get("docker") == "yes"}
