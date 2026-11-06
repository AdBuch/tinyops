"""Coding-Agenten (Claude Code, Codex, Mistral Vibe, eigene Befehle), lokal oder per SSH in tmux, direkt an Tickets zugewiesen.

Wie es läuft
* Eine Verbindung ist «lokal» (dieser Rechner, losgelöster Prozess, auch unter Windows) oder ein SSH-Ziel.
* Remote startet tinyops pro Aufgabe eine tmux-Sitzung `tinyops-<Nr>` auf dem Zielhost. Prompt, Befehl und Log liegen unter
  `~/.tinyops/runs/` auf dem Zielhost. Der Stand wird aus der Exit-Datei und `tmux has-session` gelesen, das Log mit `tail`.
  Man kann jederzeit selbst mit `tmux attach -t tinyops-<Nr>` hineinschauen.
* Der Prompt enthält nur, was auf der Karte steht (Key, Titel, Projekt, Branch) plus das, was du im Dialog änderst. Er wird als Datei
  übertragen, nie als Teil eines Shell-Befehls.
* Cloud-Agenten (Claude, Codex, Vibe) schicken Prompt und Code an den Anbieter. Deshalb startet nichts, solange beim Projekt nicht
  ausdrücklich «Cloud-Agent erlaubt» steht (Standard: aus).
* Der Befehl eines Agenten kommt aus fest eingebauten Vorlagen. Nur bei «custom» steht er in der config.json, und die Oberfläche kann ihn nicht ändern.
"""
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

import secretstore as store
import tlog
import audit as _audit

log = tlog.get("agents")

ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,30}$")
HOST_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,251}$")
USER_RE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9._-]{0,63}$")
EXTRA_RE = re.compile(r"^[A-Za-z0-9_@%+=:,./ \-]{0,200}$")      # keine Anführungszeichen, kein ; | & $ ` < > und kein Zeilenumbruch
DIR_RE = re.compile(r"^[A-Za-z0-9._][A-Za-z0-9._/-]{0,198}$")
PROMPT = "\0PROMPT\0"
PROMPT_FILE = "\0PROMPT_FILE\0"
MODEL = "\0MODEL\0"
MODEL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,79}$")
CLASSES = ("restricted", "internal", "public")
CLASS_LABEL = {"restricted": "restricted (nur lokale Agenten)", "internal": "internal (Cloud mit Freigabe)", "public": "public"}
PATH_RE = re.compile(r"^[A-Za-z0-9._][A-Za-z0-9._/-]{0,199}$")
ISOLATION = ("worktree", "shared")
STATUS_ACTIVE = ("läuft",)
STATUS_ALL = ("zugewiesen", "läuft", "fertig", "fehlgeschlagen", "abgebrochen", "verloren", "abgelaufen")
DEFAULT_MAX_MINUTES = 60
MAX_PROMPT = 20000
KINDS = {
    "claude": {"label": "Claude Code", "bin": "claude", "argv": ["claude", "-p", PROMPT], "provider": "Anthropic"},
    "codex": {"label": "Codex", "bin": "codex", "argv": ["codex", "exec", PROMPT], "provider": "OpenAI"},
    "vibe": {"label": "Mistral Vibe", "bin": "vibe", "argv": ["vibe", "-p", PROMPT], "provider": "Mistral"},
    # Lokale Agenten: Aufrufe aus der Dokumentation der CLIs abgeleitet, nicht gegen die echten Programme getestet.
    "goose": {"label": "Goose", "bin": "goose", "argv": ["goose", "run", "-i", PROMPT_FILE], "provider": "dem in Goose eingestellten Anbieter",
              "env": {"GOOSE_PROVIDER": "ollama", "GOOSE_MODEL": MODEL}, "local": True},
    "opencode": {"label": "opencode", "bin": "opencode", "argv": ["opencode", "run", "--model", "ollama/" + MODEL, PROMPT],
                 "provider": "dem in opencode eingestellten Anbieter", "local": True},
    "custom": {"label": "Eigener Befehl", "bin": "", "argv": None, "provider": "dem Anbieter des Befehls", "local": True},
}
ANSI = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]|\x1b\][^\x07]*\x07")

RUNNER = '''R="$HOME/.tinyops/runs"
ID="$1"
export R ID
{ "${SHELL:-/bin/sh}" -l -c 'exec sh "$R/$ID.cmd"'; echo $? > "$R/$ID.exit.tmp"; mv "$R/$ID.exit.tmp" "$R/$ID.exit"; } 2>&1 | tee "$R/$ID.log"
'''


class AgentError(Exception):
    pass


def slug(s):
    return re.sub(r"[^a-z0-9_-]+", "-", str(s or "").strip().lower()).strip("-")[:31]


# ------------------------------------------------------------------ Konfiguration prüfen
def clean_connections(raw, errors):
    out, seen = [], set()
    for i, c in enumerate(raw or []):
        if not isinstance(c, dict):
            continue
        k = "connections.%d." % i
        cid = slug(c.get("id") or c.get("name"))
        if not ID_RE.fullmatch(cid) or cid == "local":
            errors[k + "name"] = "Name fehlt oder ist ungültig (Buchstaben, Ziffern, - und _; «local» ist reserviert)."
            continue
        if cid in seen:
            errors[k + "name"] = "Diesen Namen gibt es schon."
            continue
        seen.add(cid)
        host = str(c.get("host") or "").strip()
        if not HOST_RE.fullmatch(host):
            errors[k + "host"] = "Rechnername oder Adresse fehlt oder ist ungültig."
        user = str(c.get("user") or "").strip()
        if user and not USER_RE.fullmatch(user):
            errors[k + "user"] = "Ungültiger Benutzername."
        try:
            port = int(c.get("port") or 22)
            if not 1 <= port <= 65535:
                raise ValueError
        except (TypeError, ValueError):
            port = 22
            errors[k + "port"] = "Port zwischen 1 und 65535."
        ident = str(c.get("identity_file") or "").strip()
        if ident and (len(ident) > 300 or "\n" in ident or "\0" in ident or ident.startswith("-")):
            errors[k + "identity_file"] = "Ungültiger Pfad."
        hk = c.get("host_key") if c.get("host_key") in ("strict", "accept-new") else "strict"
        out.append({"id": cid, "name": str(c.get("name") or cid).strip()[:40] or cid, "host": host, "user": user, "port": port,
                    "identity_file": ident, "host_key": hk})
    return out


def clean_agents(raw, conn_ids, existing, errors):
    """`existing`: bisherige Agenten aus der config.json. Den Befehl von «custom» übernimmt nur sie, nie die Oberfläche."""
    old = {a.get("id"): a for a in existing or []}
    out, seen = [], set()
    for i, a in enumerate(raw or []):
        if not isinstance(a, dict):
            continue
        k = "agents.%d." % i
        aid = slug(a.get("id") or a.get("name"))
        if not ID_RE.fullmatch(aid):
            errors[k + "name"] = "Name fehlt oder ist ungültig."
            continue
        if aid in seen:
            errors[k + "name"] = "Diesen Namen gibt es schon."
            continue
        seen.add(aid)
        kind = a.get("kind") if a.get("kind") in KINDS else "claude"
        conn = a.get("connection") or "local"
        if conn != "local" and conn not in conn_ids:
            errors[k + "connection"] = "Diese Verbindung gibt es nicht."
        root = str(a.get("workspace_root") or "").strip()
        if not root or len(root) > 300 or "\n" in root or "\0" in root or root.startswith("-"):
            errors[k + "workspace_root"] = "Arbeitsordner fehlt oder ist ungültig."
        elif conn != "local" and not (root.startswith("/") or root == "~" or root.startswith("~/")):
            errors[k + "workspace_root"] = "Auf dem Zielhost: absoluter Pfad (/home/… oder ~/…)."
        extra = str(a.get("extra_args") or "").strip()
        if not EXTRA_RE.fullmatch(extra):
            errors[k + "extra_args"] = "Nur Buchstaben, Ziffern und - _ . / : , = @ + %. Keine Anführungszeichen, kein ; | & $ ` < >."
        try:
            mx = int(a.get("max_minutes") if a.get("max_minutes") not in (None, "") else DEFAULT_MAX_MINUTES)
            if not 0 <= mx <= 1440:
                raise ValueError
        except (TypeError, ValueError):
            mx = DEFAULT_MAX_MINUTES
            errors[k + "max_minutes"] = "Zeitlimit in Minuten zwischen 0 (aus) und 1440."
        model = str(a.get("model") or "").strip()
        if KINDS[kind].get("local") and kind != "custom":
            if not MODEL_RE.fullmatch(model or "x"):
                errors[k + "model"] = "Modellname: Buchstaben, Ziffern und . _ : / -"
            elif not model:
                errors[k + "model"] = "Welches lokale Modell (z. B. qwen2.5-coder:32b)?"
        iso = a.get("isolation") if a.get("isolation") in ISOLATION else "worktree"
        # Cloud: Claude, Codex, Vibe immer; lokale Arten nur, wenn du es so einstellst (Standard: lokal)
        cloud = True if not KINDS[kind].get("local") else bool(a.get("cloud", False))
        entry = {"id": aid, "name": str(a.get("name") or aid).strip()[:40] or aid, "kind": kind, "connection": conn, "workspace_root": root, "max_minutes": mx,
                 "extra_args": extra, "cloud": cloud, "isolation": iso}
        if model and KINDS[kind].get("local") and kind != "custom":
            entry["model"] = model
        cmd = (old.get(aid) or {}).get("command")
        if kind == "custom" and cmd:
            entry["command"] = str(cmd)
        out.append(entry)
    return out


def data_class(p):
    """Datenklasse eines Projekts/Repos. Ohne Angabe: aus der alten Freigabe «Cloud-Agent erlaubt» (0.12–0.15), sonst restricted."""
    c = (p or {}).get("data_class")
    if c in CLASSES:
        return c
    return "internal" if (p or {}).get("allow_cloud_agents") else "restricted"


def clean_paths(raw):
    """Freigegebene Pfade für Cloud-Agenten: relativ, ohne «..». Gibt (Liste, Fehler) zurück."""
    items = raw if isinstance(raw, list) else re.split(r"[\s,]+", str(raw or ""))
    out = []
    for x in items:
        x = str(x or "").strip().strip("/")
        if not x:
            continue
        if not PATH_RE.fullmatch(x) or ".." in x.split("/"):
            return out, "Pfad «%s» ist ungültig (relativ, ohne «..», nur Buchstaben, Ziffern und . _ - /)." % x[:60]
        if x not in out:
            out.append(x)
    if len(out) > 30:
        return out[:30], "Höchstens 30 freigegebene Pfade."
    return out, ""


def path_allowed(f, paths):
    f = f.strip("/")
    return any(f == p or f.startswith(p + "/") for p in paths)


def valid_agent_dir(d):
    d = str(d or "").strip()
    return (not d) or (DIR_RE.fullmatch(d) is not None and ".." not in d.split("/") and not d.endswith("/"))


# ------------------------------------------------------------------ Befehle bauen
def _sh_path(p):
    if p == "~":
        return '"$HOME"'
    if p.startswith("~/"):
        return '"$HOME"/' + shlex.quote(p[2:])
    return shlex.quote(p)


def _extra(agent):
    return shlex.split(agent.get("extra_args") or "")


def _sub_model(a, model):
    return a.replace(MODEL, model or "")


def remote_cmdline(agent):
    """Zeile für `<Nr>.cmd` auf dem Zielhost. Der Prompt wird dort aus der Datei gelesen, nicht eingebettet."""
    if agent["kind"] == "custom":
        cmd = agent.get("command")
        if not cmd:
            raise AgentError("Für diesen eigenen Agenten steht kein «command» in der config.json (die Oberfläche kann ihn nicht setzen).")
        return cmd.replace("{prompt_file}", '"$R/$ID.prompt"')
    spec, model = KINDS[agent["kind"]], agent.get("model", "")
    parts = ["%s=%s" % (k, shlex.quote(_sub_model(v, model))) for k, v in (spec.get("env") or {}).items()]
    for a in spec["argv"] + _extra(agent):
        parts.append('"$(cat "$R/$ID.prompt")"' if a == PROMPT else '"$R/$ID.prompt"' if a == PROMPT_FILE else shlex.quote(_sub_model(a, model)))
    return " ".join(parts)


def local_spec(agent, prompt, prompt_file, workdir):
    if agent["kind"] == "custom":
        cmd = agent.get("command")
        if not cmd:
            raise AgentError("Für diesen eigenen Agenten steht kein «command» in der config.json (die Oberfläche kann ihn nicht setzen).")
        pf = subprocess.list2cmdline([str(prompt_file)]) if os.name == "nt" else shlex.quote(str(prompt_file))
        return {"shell": cmd.replace("{prompt_file}", pf), "cwd": workdir}
    spec = KINDS[agent["kind"]]
    exe = shutil.which(spec["bin"])
    if not exe:
        raise AgentError("«%s» wurde im PATH dieses Rechners nicht gefunden." % spec["bin"])
    model = agent.get("model", "")
    argv = [exe] + [prompt if a == PROMPT else str(prompt_file) if a == PROMPT_FILE else _sub_model(a, model) for a in spec["argv"][1:] + _extra(agent)]
    out = {"argv": argv, "cwd": workdir}
    if spec.get("env"):
        out["env"] = {k: _sub_model(v, model) for k, v in spec["env"].items()}
    return out


def _delim(*texts):
    n = 0
    while True:
        d = "TINYOPS_EOF_%d" % n
        if not any(d in t for t in texts):
            return d
        n += 1


# ------------------------------------------------------------------ Isolation (Worktree oder Export) als Shell, lokal und remote gleich
def _resolve_base(base):
    b = shlex.quote(base or "")
    return ('BASE=%s; '
            'if [ -n "$BASE" ] && git -C "$REPO" rev-parse -q --verify "$BASE^{commit}" >/dev/null 2>&1; then :; '
            'elif [ -n "$BASE" ] && git -C "$REPO" rev-parse -q --verify "origin/$BASE^{commit}" >/dev/null 2>&1; then BASE="origin/$BASE"; '
            'else BASE=HEAD; fi\n') % b


def prepare_script(mode, repo_sh, root_sh, rid, branch, base, paths=()):
    """Setzt WD (Arbeitsordner des Agenten). Exit 41 Ordner fehlt, 43 kein Git, 44 Worktree, 45 Export. Erwartet R und ID."""
    rid = int(rid)
    s = "REPO=%s\n[ -d \"$REPO\" ] || { echo \"Arbeitsverzeichnis fehlt\" >&2; exit 41; }\n" % repo_sh
    if mode == "shared":
        return s + 'WD="$REPO"\n'
    s += 'command -v git >/dev/null 2>&1 || { echo "git fehlt" >&2; exit 43; }\n'
    s += 'git -C "$REPO" rev-parse --git-dir >/dev/null 2>&1 || { echo "kein Git-Repository" >&2; exit 43; }\n'
    s += "WD=%s/.tinyops-wt/%d\n" % (root_sh, rid)
    s += _resolve_base(base)
    s += 'mkdir -p "$(dirname "$WD")"\nrm -rf "$WD"\n'
    if mode == "worktree":
        s += ('git -C "$REPO" worktree add -q -b %s "$WD" "$BASE" >&2 || { echo "Worktree konnte nicht angelegt werden" >&2; exit 44; }\n'
              'git -C "$WD" rev-parse HEAD > "$R/$ID.base"\n') % shlex.quote(branch)
        return s
    q = " ".join(shlex.quote(p) for p in paths)
    s += ('mkdir -p "$WD"\n'
          'git -C "$REPO" archive --format=tar "$BASE" -- %s | tar -x -C "$WD" || { echo "Export der freigegebenen Pfade fehlgeschlagen (gibt es sie im Branch?)" >&2; exit 45; }\n'
          'git -C "$REPO" rev-parse "$BASE^{commit}" > "$R/$ID.base"\n'
          '( cd "$WD" && git init -q && git add -A && git -c user.name=tinyops -c user.email=tinyops@localhost commit -qm "tinyops: freigegebene Pfade" '
          '&& git rev-parse HEAD > "$R/$ID.init" ) >&2 || { echo "Export-Repository konnte nicht angelegt werden" >&2; exit 45; }\n') % q
    return s


def cleanup_script(mode, repo_sh, wt, rid):
    """Worktree: offene Änderungen als Commit auf dem Agenten-Branch sichern, dann Worktree entfernen (Branch bleibt). Export: Ordner löschen."""
    w = shlex.quote(wt)
    if mode == "worktree":
        return ('REPO=%s; WD=%s; if [ -d "$WD" ]; then cd "$WD" && git add -A && '
                '(git diff --cached --quiet || git -c user.name=tinyops -c user.email=tinyops@localhost commit -qm "tinyops: offener Stand von Lauf %d gesichert" --no-verify); '
                'cd / && git -C "$REPO" worktree remove --force "$WD"; fi; git -C "$REPO" worktree prune; true') % (repo_sh, w, int(rid))
    if mode == "export":
        return 'rm -rf %s; true' % w
    return "true"


def changes_script(wt):
    """Export: offene Änderungen committen und alle geänderten Dateien seit dem Export auflisten."""
    return ('cd %s && git add -A && (git diff --cached --quiet || git -c user.name=tinyops -c user.email=tinyops@localhost commit -qm "tinyops: Stand des Agenten" --no-verify) >/dev/null '
            '&& INIT=$(cat "$R/$ID.init") && git diff --name-only "$INIT" HEAD && git diff --binary "$INIT" HEAD > "$R/$ID.patch"') % shlex.quote(wt)


def apply_script(repo_sh, root_sh, rid, branch, message):
    """Export: Patch auf einem neuen Branch im echten Repo anwenden (eigener, kurzlebiger Worktree), dann den Worktree entfernen."""
    return ('REPO=%s; AW=%s/.tinyops-wt/%d-apply; BASE=$(cat "$R/$ID.base"); rm -rf "$AW"; '
            'git -C "$REPO" worktree add -q -b %s "$AW" "$BASE" >&2 || exit 44; '
            'if git -C "$AW" apply --index "$R/$ID.patch" >&2 && git -C "$AW" -c user.name=tinyops -c user.email=tinyops@localhost commit -qm %s --no-verify >&2; '
            'then git -C "$REPO" worktree remove --force "$AW"; echo applied; else git -C "$REPO" worktree remove --force "$AW"; git -C "$REPO" branch -D %s >/dev/null 2>&1; exit 46; fi'
            ) % (repo_sh, root_sh, int(rid), shlex.quote(branch), shlex.quote(message), shlex.quote(branch))


ISO_ERR = {41: "Das Arbeitsverzeichnis %s gibt es nicht. Repository dort klonen oder den Ordner beim Projekt/Agenten anpassen.",
           43: "%s ist kein Git-Repository (oder git fehlt). Für die Isolation braucht der Agent ein geklontes Repository.",
           44: "Der Worktree unter %s konnte nicht angelegt werden (Branch schon vorhanden? Repository gesperrt?).",
           45: "Der Export der freigegebenen Pfade aus %s ist fehlgeschlagen. Gibt es die Pfade im Ausgangs-Branch?",
           46: "Die Änderungen liessen sich nicht auf den Ausgangsstand von %s anwenden."}


def remote_start_script(agent, rid, workdir, prompt, prep=None):
    cmdline = remote_cmdline(agent)
    d1, d2 = _delim(prompt), _delim(cmdline)
    wd = _sh_path(workdir)
    return """set +e
R="$HOME/.tinyops/runs"
mkdir -p "$R"
chmod 700 "$R" 2>/dev/null || true
rm -f "$R/{rid}.exit" "$R/{rid}.log"
cat > "$R/{rid}.prompt" <<'{d1}'
{prompt}
{d1}
cat > "$R/{rid}.cmd" <<'{d2}'
{cmdline}
{d2}
cat > "$R/runner.sh" <<'TINYOPS_RUNNER_EOF'
{runner}TINYOPS_RUNNER_EOF
command -v tmux >/dev/null 2>&1 || {{ echo "tmux nicht gefunden" >&2; exit 42; }}
ID={rid}
{prep}echo "$WD" > "$R/{rid}.wd"
tmux new-session -d -s tinyops-{rid} -c "$WD" "sh '$R/runner.sh' {rid}"
echo "started $WD"
""".format(rid=int(rid), d1=d1, d2=d2, prompt=prompt, cmdline=cmdline, runner=RUNNER, prep=prep if prep is not None else 'REPO=%s\n[ -d "$REPO" ] || {{ echo "Arbeitsverzeichnis fehlt" >&2; exit 41; }}\nWD="$REPO"\n'.replace("{{", "{").replace("}}", "}") % wd)


def remote_kill_script(rid):
    """Beendet die Sitzung samt Prozessen: erst TERM an die Prozessgruppe jedes Fensters, dann die Sitzung selbst."""
    return ('S=tinyops-%d; for p in $(tmux list-panes -s -t "$S" -F "#{pane_pid}" 2>/dev/null); do '
            'g=$(ps -o pgid= -p "$p" 2>/dev/null | tr -d " "); [ -n "$g" ] && kill -TERM -- "-$g" 2>/dev/null; pkill -TERM -P "$p" 2>/dev/null; done; '
            'sleep 1; tmux kill-session -t "$S" 2>/dev/null; true') % int(rid)


def remote_status_script(ids):
    return ('R="$HOME/.tinyops/runs"; for i in %s; do '
            'if [ -f "$R/$i.exit" ]; then echo "$i exit $(cat "$R/$i.exit")"; '
            'elif tmux has-session -t tinyops-$i 2>/dev/null; then echo "$i running"; '
            'elif [ -f "$R/$i.exit" ]; then echo "$i exit $(cat "$R/$i.exit")"; '
            'else echo "$i gone"; fi; done') % " ".join(str(int(i)) for i in ids)


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


def clean_text(s, limit=20000):
    s = ANSI.sub("", s or "").replace("\r\n", "\n").replace("\r", "\n")
    s = TOKEN_RE.sub("***", store.scrub(s))
    return s[-limit:]


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


# ------------------------------------------------------------------ Dienst: Läufe an Tickets
class Service:
    def __init__(self, cfg, store_, run_dir, base_dir):
        self.cfg, self.store = cfg, store_
        self.run_dir, self.base = Path(run_dir), Path(base_dir)
        self.lock = threading.RLock()
        self.poll_t = 0.0
        self.audit = lambda *a, **k: None          # setzt die App: audit(action, target, ok, actor, **detail)

    def _ev(self, action, r, ok=True, actor="du", **kw):
        """Audit-Eintrag zu einem Lauf: wer, wo, welche Datenklasse, welcher Modus. Der Prompt nur als Hash."""
        try:
            a = self.agent(r["agent"])
        except AgentError:
            a = None
        p = self.project(r.get("project_id")) if r.get("project_id") is not None else None
        det = {"run": r["id"], "agent": r["agent"], "kind": a["kind"] if a else "?", "cloud": bool(a.get("cloud", True)) if a else None,
               "where": ("lokal" if a["connection"] == "local" else a["connection"]) if a else "?",
               "project_id": r.get("project_id"), "data_class": data_class(p) if p else None}
        if r.get("mode"):
            det["mode"] = r["mode"]
        det.update(kw)
        try:
            self.audit(action, r.get("ticket") or "", ok, actor, **det)
        except Exception as e:      # Audit darf einen Lauf nie aufhalten
            log.error("Audit %s für Lauf %s: %s", action, r.get("id"), e)

    # -- Konfiguration
    def agent_list(self):
        return list(self.cfg.get("agents") or [])

    def conns(self):
        return {c["id"]: c for c in self.cfg.get("connections") or []}

    def agent(self, aid):
        for a in self.agent_list():
            if a["id"] == aid:
                return a
        raise AgentError("Diesen Agenten gibt es nicht (mehr).")

    def conn_of(self, agent):
        if agent["connection"] == "local":
            return None
        c = self.conns().get(agent["connection"])
        if not c:
            raise AgentError("Die Verbindung «%s» dieses Agenten gibt es nicht." % agent["connection"])
        return c

    def projects(self):
        """GitLab-Projekte und GitHub-Repos (Projektnummer 10**12 + Repo-ID)."""
        out = list(self.cfg.get("projects") or [])
        for r in (self.cfg.get("github") or {}).get("repos") or []:
            if r.get("id") and r.get("full"):
                out.append({"id": 10 ** 12 + int(r["id"]), "name": r["full"].split("/")[-1], "agent_dir": r.get("agent_dir", ""),
                            "allow_cloud_agents": bool(r.get("allow_cloud_agents")), "data_class": r.get("data_class"), "cloud_paths": r.get("cloud_paths") or []})
        return out

    def project(self, pid):
        for p in self.projects():
            if p["id"] == pid:
                return p
        return None

    def workdir(self, agent, pid):
        p = self.project(pid)
        if p is None:
            raise AgentError("Bitte ein Projekt wählen (der Agent braucht ein Repository).")
        sub = (p.get("agent_dir") or "").strip() or re.sub(r"[^A-Za-z0-9._-]+", "-", p.get("name") or str(pid)).strip("-") or str(pid)
        root = agent["workspace_root"].rstrip("/\\") if agent["connection"] != "local" else agent["workspace_root"]
        return (root + "/" + sub) if agent["connection"] != "local" else os.path.join(os.path.expanduser(root), *sub.split("/"))

    def allowed(self, agent, pid):
        """(erlaubt, Grund). Datenklasse restricted: nur Agenten ohne Cloud. internal und public: auch Cloud-Agenten."""
        p = self.project(pid)
        if p is None:
            return False, "Projekt fehlt."
        cls = data_class(p)
        if agent.get("cloud", True) and cls == "restricted":
            prov = KINDS[agent["kind"]]["provider"]
            return False, ("Projekt «%s» ist restricted: nur lokale Agenten. %s sendet Prompt und Code an %s. "
                           "Ändern unter Einstellungen → Projekte → Datenklasse (internal oder public)." % (p.get("name"), KINDS[agent["kind"]]["label"], prov))
        return True, ""

    def mode(self, agent, pid):
        """Wie der Agent arbeitet: export (nur freigegebene Pfade, eigenes Git), worktree (eigener Branch) oder shared (alter gemeinsamer Ordner)."""
        p = self.project(pid) or {}
        if agent.get("cloud", True) and data_class(p) == "internal" and p.get("cloud_paths"):
            return "export"
        return "shared" if agent.get("isolation") == "shared" else "worktree"

    def out_branch(self, ticket, rid):
        return "agent/%s-%d" % (slug(ticket).replace("_", "-") or "lauf", int(rid))

    def _paths(self, agent, pid):
        """(Repo, Wurzel) als Shell-Ausdruck bzw. Pfad, je nach Ziel."""
        wd = self.workdir(agent, pid)
        if agent["connection"] == "local":
            return wd, os.path.expanduser(agent["workspace_root"])
        return wd, agent["workspace_root"].rstrip("/") or "/"

    def _sh(self, agent, conn, script, rid, timeout=60):
        """Ein Shell-Skript mit R und ID im Run-Ordner ausführen: remote per SSH, lokal mit sh (unter Windows aus Git for Windows)."""
        if conn is not None:
            return run_remote(conn, 'R="$HOME/.tinyops/runs"; ID=%d; mkdir -p "$R"; ' % int(rid) + script, timeout=timeout)
        shx = shutil.which("sh")
        if not shx:
            raise AgentError("Für die Isolation braucht tinyops «sh» (Windows: den Ordner Git\\bin von Git for Windows in den PATH) oder beim Agenten «gemeinsamer Ordner».")
        self.run_dir.mkdir(parents=True, exist_ok=True)
        try:
            r = subprocess.run([shx, "-c", script], capture_output=True, timeout=timeout, stdin=subprocess.DEVNULL,
                               env=dict(os.environ, R=str(self.run_dir), ID=str(int(rid))))
        except subprocess.TimeoutExpired:
            raise AgentError("Zeitüberschreitung bei der Vorbereitung.")
        return r.returncode, r.stdout.decode("utf-8", "replace"), r.stderr.decode("utf-8", "replace")

    def _q(self, agent, path):
        return shlex.quote(path) if agent["connection"] == "local" else _sh_path(path)

    WORKSPACE_LINES = {
        "worktree": "Du arbeitest in einem eigenen Worktree auf dem Branch agent/<key>-<nr> (abgezweigt von {branch}). Committe dort; den Branch pusht der Mensch.",
        "export": "Du siehst nur einen Ausschnitt des Repositorys: {paths}. Ändere nur Dateien darin. tinyops übernimmt die Änderungen nach Prüfung als Branch.",
        "shared": "Arbeite im aktuellen Repository. Lege den Branch an, falls er fehlt (vom Hauptbranch aus), und arbeite nur dort.",
    }

    def default_prompt(self, title, key, project, branch, url="", mode="shared", paths=()):
        f = self.base / "prompts" / "agent-task.md"
        try:
            tpl = f.read_text(encoding="utf-8")
        except OSError:
            tpl = "Aufgabe {key}: {title}\nProjekt: {project}\nBranch: {branch}\n{url_line}"

        class D(dict):
            def __missing__(self, k):
                return ""
        ws = self.WORKSPACE_LINES.get(mode, self.WORKSPACE_LINES["shared"]).replace("{branch}", branch or "dem Hauptbranch").replace("{paths}", ", ".join(paths) or "-")
        return tpl.format_map(D(key=key or "(ohne Key)", title=title or "", project=project or "", branch=branch or "(noch keiner)",
                                url_line=("Link: %s\n" % url) if url else "", workspace_line=ws)).strip() + "\n"

    def prompt_info(self, aid, ticket, pid, branch, title, key, url=""):
        a = self.agent(aid)
        conn = self.conn_of(a)
        ok, why = self.allowed(a, pid)
        try:
            wd = self.workdir(a, pid)
        except AgentError as e:
            wd, ok, why = "", False, str(e)
        p = self.project(pid) or {}
        mode = self.mode(a, pid) if p else "shared"
        return {"prompt": self.default_prompt(title, key, p.get("name", ""), branch, url, mode, p.get("cloud_paths") or []), "workdir": wd,
                "where": "lokal auf diesem Rechner" if conn is None else "%s (%s)" % (conn["name"], ("%s@%s" % (conn["user"], conn["host"])) if conn["user"] else conn["host"]),
                "cloud": bool(a.get("cloud", True)), "provider": KINDS[a["kind"]]["provider"], "kind": KINDS[a["kind"]]["label"],
                "allowed": ok, "reason": why, "data_class": data_class(p), "mode": self.mode(a, pid) if p else "",
                "cloud_paths": p.get("cloud_paths") or [] if self.mode(a, pid) == "export" else []}

    # -- Ansichten
    def run_view(self, r):
        a = next((x for x in self.agent_list() if x["id"] == r["agent"]), None)
        conn = None
        try:
            conn = self.conn_of(a) if a else None
        except AgentError:
            pass
        end = r["finished"] or time.time()
        v = dict(r)
        v["prompt_text"] = v.pop("prompt", "")
        v.update(agent_name=a["name"] if a else r["agent"] + " (entfernt)", kind=a["kind"] if a else "custom",
                 where=("lokal" if a and a["connection"] == "local" else conn["name"] if conn else "?"),
                 active=r["status"] in STATUS_ACTIVE, secs=int(end - r["started"]) if r["started"] else 0,
                 attach=("ssh -t -p %s %s tmux attach -t tinyops-%d" % (conn["port"], (("%s@%s" % (conn["user"], conn["host"])) if conn["user"] else conn["host"]), r["id"])) if conn else "")
        return v

    def view(self):
        agents = [{"id": a["id"], "name": a["name"], "kind": a["kind"], "label": KINDS[a["kind"]]["label"], "cloud": a.get("cloud", True),
                   "isolation": a.get("isolation", "worktree"),
                   "where": "lokal" if a["connection"] == "local" else (self.conns().get(a["connection"]) or {}).get("name", "?"),
                   "workspace_root": a["workspace_root"]} for a in self.agent_list()]
        projects = [{"id": p["id"], "name": p.get("name") or str(p["id"]), "data_class": data_class(p)} for p in self.projects()]
        return {"enabled": bool(agents), "agents": agents, "projects": projects, "runs": [self.run_view(r) for r in self.store.agent_runs(limit=200)]}

    # -- Zuweisen, Starten, Stoppen
    def assign(self, aid, ticket, pid, branch, title):
        self.agent(aid)
        ticket = str(ticket or "").strip()
        if not ticket or len(ticket) > 120:
            raise AgentError("Die Karte hat keine Kennung.")
        for r in self.store.agent_runs(ticket=ticket):
            if r["agent"] == aid and r["status"] in ("zugewiesen", "läuft"):
                raise AgentError("Dieser Agent ist dem Ticket schon zugewiesen.")
        if pid is not None:
            ok, why = self.allowed(self.agent(aid), pid)
            if not ok:
                self._ev("agent.assign", {"id": None, "agent": aid, "ticket": ticket, "project_id": pid}, ok=False, error=why)
                raise AgentError(why)
        rid = self.store.agent_run_add(aid, ticket, pid, str(branch or "")[:200], str(title or "")[:300])
        self._ev("agent.assign", self.store.agent_run(rid), branch=str(branch or "")[:200])
        return rid

    def start(self, run_id, prompt, pid=None, branch=None):
        with self.lock:
            r = self.store.agent_run(run_id)
            if not r:
                raise AgentError("Diese Zuweisung gibt es nicht (mehr).")
            if r["status"] != "zugewiesen":
                raise AgentError("Nur zugewiesene Läufe lassen sich starten (Status: %s)." % r["status"])
            a = self.agent(r["agent"])
            conn = self.conn_of(a)
            pid = pid if pid is not None else r["project_id"]
            ok, why = self.allowed(a, pid)
            if not ok:
                self._ev("agent.start", dict(r, project_id=pid), ok=False, error=why)
                raise AgentError(why)
            prompt = str(prompt or "").replace("\r\n", "\n").strip()
            if not prompt or len(prompt) > MAX_PROMPT or "\0" in prompt:
                raise AgentError("Der Prompt fehlt oder ist länger als %d Zeichen." % MAX_PROMPT)
            wd = self.workdir(a, pid)
            mode = self.mode(a, pid)
            if mode == "shared":
                for o in self.store.agent_runs(status="läuft"):
                    if o["agent"] == a["id"] and o["workdir"] == wd and (o.get("mode") or "shared") == "shared":
                        raise AgentError("Auf diesem Agenten läuft in %s schon eine Aufgabe (%s). Erst beenden." % (wd, o["ticket"]))
            branch = str(branch if branch is not None else r["branch"])[:200]
            outb = self.out_branch(r["ticket"], run_id) if mode != "shared" else ""
            repo, root = self._paths(a, pid)
            prep = prepare_script(mode, self._q(a, repo), self._q(a, root), run_id, outb, branch, (self.project(pid) or {}).get("cloud_paths") or [])
            self.store.agent_run_update(run_id, project_id=pid, branch=branch, workdir=wd, prompt=prompt, mode=mode, out_branch=outb)
            try:
                if conn is None:
                    run_wd = self._local_prepare(a, run_id, prep) if mode != "shared" else wd
                    self._local_start(a, run_id, run_wd, prompt)
                else:
                    rc, out, err = run_remote(conn, remote_start_script(a, run_id, wd, prompt, prep), timeout=60)
                    if rc in ISO_ERR:
                        raise AgentError(ISO_ERR[rc] % wd)
                    if rc == 42:
                        raise AgentError("Auf dem Zielhost ist tmux nicht installiert.")
                    if rc != 0 or "started" not in out:
                        raise AgentError("Start fehlgeschlagen (Exit %d): %s" % (rc, clean_text(err or out, 300).strip()))
                    run_wd = out.split("started", 1)[1].strip().splitlines()[0] if "started" in out else wd
                self.store.agent_run_update(run_id, wt=run_wd if mode != "shared" else "")
            except AgentError as e:
                self.store.agent_run_update(run_id, status="fehlgeschlagen", note=str(e)[:300], finished=time.time())
                log.warning("Start von Lauf %d (%s) fehlgeschlagen: %s", run_id, a["id"], e)
                self._ev("agent.start", self.store.agent_run(run_id), ok=False, error=str(e)[:300], prompt_hash=_audit.prompt_hash(prompt))
                raise
            self.store.agent_run_update(run_id, status="läuft", started=time.time(), note="")
            self._ev("agent.start", self.store.agent_run(run_id), prompt_hash=_audit.prompt_hash(prompt), prompt_chars=len(prompt),
                     workdir=wd, branch=branch, out_branch=outb, max_minutes=int(a.get("max_minutes", DEFAULT_MAX_MINUTES) or 0))
            log.info("Lauf %d gestartet: Agent %s, Ticket %s, %s", run_id, a["id"], r["ticket"], wd)
            return run_id

    def _local_prepare(self, a, rid, prep):
        rc, out, err = self._sh(a, None, prep + 'echo "WD=$WD"\n', rid)
        if rc in ISO_ERR:
            raise AgentError(ISO_ERR[rc] % self.workdir(a, self.store.agent_run(rid)["project_id"]))
        if rc != 0:
            raise AgentError("Vorbereitung fehlgeschlagen (Exit %d): %s" % (rc, clean_text(err or out, 300).strip()))
        line = [x for x in out.splitlines() if x.startswith("WD=")]
        return line[-1][3:] if line else ""

    def _local_start(self, a, rid, wd, prompt):
        if not os.path.isdir(wd):
            raise AgentError("Das Arbeitsverzeichnis %s gibt es auf diesem Rechner nicht." % wd)
        d = self.run_dir
        d.mkdir(parents=True, exist_ok=True)
        for ext in ("exit", "exit.tmp", "log", "hb", "pid"):
            try:
                (d / ("%d.%s" % (rid, ext))).unlink()
            except OSError:
                pass
        pf = d / ("%d.prompt" % rid)
        pf.write_text(prompt, encoding="utf-8")
        spec = local_spec(a, prompt, pf, wd)
        (d / ("%d.spec.json" % rid)).write_text(json.dumps(spec), encoding="utf-8")
        kw = {"stdin": subprocess.DEVNULL, "stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL, "cwd": str(d), "close_fds": True}
        if os.name == "nt":
            kw["creationflags"] = 0x00000008 | 0x00000200      # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
        else:
            kw["start_new_session"] = True
        try:
            subprocess.Popen([sys.executable, str(self.base / "agentwrap.py"), str(d), str(rid)], **kw)
        except OSError as e:
            raise AgentError("Start fehlgeschlagen: %s" % e)

    def _local_status(self, r):
        d = self.run_dir
        ex = d / ("%d.exit" % r["id"])
        if ex.exists():
            try:
                return "exit", int(ex.read_text().strip() or "1")
            except (OSError, ValueError):
                return "exit", 1
        hb = d / ("%d.hb" % r["id"])
        try:
            age = time.time() - hb.stat().st_mtime
        except OSError:
            age = time.time() - (r["started"] or time.time())
        return ("running", 0) if age < 30 else ("gone", 0)

    def poll(self, force=False):
        """Stand aller laufenden Läufe ablesen (ein SSH-Aufruf je Zielhost). Fehler bei der Abfrage lassen den Lauf auf «läuft» und stehen im Hinweis."""
        with self.lock:
            if not force and time.time() - self.poll_t < 2.0:
                return
            self.poll_t = time.time()
            active = self.store.agent_runs(status="läuft")
            if not active:
                return
            active = [r for r in active if not self._expire(r)]
            if not active:
                return
            by_conn = {}
            for r in active:
                try:
                    a = self.agent(r["agent"])
                    by_conn.setdefault(a["connection"], []).append(r)
                except AgentError:
                    self.store.agent_run_update(r["id"], status="verloren", note="Der Agent wurde aus der Konfiguration entfernt.", finished=time.time())
            for cid, runs in by_conn.items():
                if cid == "local":
                    res = {r["id"]: self._local_status(r) for r in runs}
                else:
                    conn = self.conns().get(cid)
                    if not conn:
                        for r in runs:
                            self.store.agent_run_update(r["id"], status="verloren", note="Die Verbindung wurde entfernt.", finished=time.time())
                        continue
                    try:
                        rc, out, err = run_remote(conn, remote_status_script([r["id"] for r in runs]), timeout=20)
                    except AgentError as e:
                        for r in runs:
                            self.store.agent_run_update(r["id"], note="Status unbekannt: %s" % str(e)[:200])
                        continue
                    res = {}
                    for line in out.splitlines():
                        p = line.split()
                        if len(p) >= 2 and p[0].isdigit():
                            res[int(p[0])] = ("exit", int(p[2]) if len(p) > 2 and p[2].lstrip("-").isdigit() else 1) if p[1] == "exit" else (p[1], 0)
                for r in runs:
                    st = res.get(r["id"])
                    if st is None:
                        continue
                    if st[0] == "exit":
                        self.store.agent_run_update(r["id"], status="fertig" if st[1] == 0 else "fehlgeschlagen", exit_code=st[1], finished=time.time(), note="")
                        self._ev("agent.finish", r, ok=st[1] == 0, actor="agent", status="fertig" if st[1] == 0 else "fehlgeschlagen", exit_code=st[1],
                                 minutes=int((time.time() - (r["started"] or time.time())) // 60))
                    elif st[0] == "gone":
                        self.store.agent_run_update(r["id"], status="verloren", finished=time.time(),
                                                    note="Weder Exit-Datei noch Sitzung gefunden (Zielhost neu gestartet, tmux beendet?).")
                        self._ev("agent.finish", r, ok=False, actor="agent", status="verloren")
                    else:
                        if r["note"]:
                            self.store.agent_run_update(r["id"], note="")

    def _expire(self, r):
        """Zeitlimit des Agenten überschritten? Dann beenden und als «abgelaufen» markieren. Gibt True zurück, wenn beendet."""
        try:
            a = self.agent(r["agent"])
        except AgentError:
            return False
        mx = int(a.get("max_minutes", DEFAULT_MAX_MINUTES) or 0)
        if not mx or not r["started"] or time.time() - r["started"] < mx * 60:
            return False
        try:
            conn = self.conn_of(a)
            if conn is None:
                self._local_kill(r)
            else:
                run_remote(conn, remote_kill_script(r["id"]), timeout=20)
        except AgentError as e:
            log.warning("Lauf %d: Zeitlimit erreicht, Beenden fehlgeschlagen: %s", r["id"], e)
            self.store.agent_run_update(r["id"], note="Zeitlimit erreicht, Beenden fehlgeschlagen: %s" % str(e)[:200])
            if "Beenden fehlgeschlagen" not in (r.get("note") or ""):
                self._ev("agent.expire", r, ok=False, actor="watchdog", max_minutes=mx, error=str(e)[:200])
            return False
        self.store.agent_run_update(r["id"], status="abgelaufen", finished=time.time(), note="Zeitlimit von %d min erreicht und beendet." % mx)
        self._ev("agent.expire", r, actor="watchdog", max_minutes=mx)
        log.warning("Lauf %d (%s, Ticket %s) nach %d min beendet (Zeitlimit)", r["id"], a["id"], r["ticket"], mx)
        return True

    def stop(self, run_id):
        with self.lock:
            r = self.store.agent_run(run_id)
            if not r or r["status"] != "läuft":
                raise AgentError("Dieser Lauf läuft nicht.")
            a = self.agent(r["agent"])
            conn = self.conn_of(a)
            if conn is None:
                self._local_kill(r)
            else:
                run_remote(conn, remote_kill_script(run_id), timeout=20)
            self.store.agent_run_update(run_id, status="abgebrochen", finished=time.time(), note="Von dir gestoppt.")
            self._ev("agent.stop", r, minutes=int((time.time() - (r["started"] or time.time())) // 60))

    def _local_kill(self, r):
        pidf = self.run_dir / ("%d.pid" % r["id"])
        try:
            pid = int(pidf.read_text().strip())
        except (OSError, ValueError):
            return
        try:
            if os.name == "nt":
                subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True, timeout=10)
            else:
                import signal
                os.killpg(pid, signal.SIGTERM)
        except (OSError, subprocess.SubprocessError):
            pass

    def changes(self, run_id):
        """Export: geänderte Dateien seit dem Export (committet die offenen Änderungen im Export-Repo)."""
        r = self.store.agent_run(run_id)
        if not r or r.get("mode") != "export" or not r.get("wt"):
            raise AgentError("Nur Läufe im Export-Modus haben Änderungen zum Übernehmen.")
        a = self.agent(r["agent"])
        rc, out, err = self._sh(a, self.conn_of(a), changes_script(r["wt"]), run_id)
        if rc != 0:
            raise AgentError("Änderungen nicht lesbar (Exit %d): %s" % (rc, clean_text(err or out, 300).strip()))
        return [x for x in out.splitlines() if x.strip()]

    def takeover(self, run_id):
        """Export: Änderungen als Branch agent/<key>-<nr> ins echte Repo übernehmen. Nur Dateien innerhalb der freigegebenen Pfade."""
        with self.lock:
            r = self.store.agent_run(run_id)
            if not r:
                raise AgentError("Diesen Lauf gibt es nicht (mehr).")
            if r["status"] in ("zugewiesen", "läuft"):
                raise AgentError("Erst wenn der Lauf beendet ist.")
            if r.get("taken"):
                raise AgentError("Schon übernommen: Branch %s." % r["taken"])
            files = self.changes(run_id)
            if not files:
                raise AgentError("Der Agent hat nichts geändert.")
            a = self.agent(r["agent"])
            paths = (self.project(r["project_id"]) or {}).get("cloud_paths") or []
            bad = [f for f in files if not path_allowed(f, paths)]
            if bad:
                self._ev("agent.takeover", r, ok=False, error="Pfade ausserhalb der Freigabe", blocked=bad[:20])
                raise AgentError("Änderungen ausserhalb der freigegebenen Pfade, nichts übernommen: %s" % ", ".join(bad[:8]))
            repo, root = self._paths(a, r["project_id"])
            outb = r.get("out_branch") or self.out_branch(r["ticket"], run_id)
            msg = "%s: Ergebnis von Agent %s (Lauf %d)" % (r["ticket"], a["name"], run_id)
            rc, out, err = self._sh(a, self.conn_of(a), apply_script(self._q(a, repo), self._q(a, root), run_id, outb, msg), run_id)
            if rc != 0 or "applied" not in out:
                raise AgentError((ISO_ERR.get(rc, "Übernehmen fehlgeschlagen (Exit %d)." % rc) % repo if rc in ISO_ERR else "Übernehmen fehlgeschlagen (Exit %d)." % rc)
                                 + " " + clean_text(err, 300).strip())
            self.store.agent_run_update(run_id, taken=outb, out_branch=outb, note="Übernommen als Branch %s (%d Dateien). Pushen und MR erstellen machst du." % (outb, len(files)))
            log.info("Lauf %d übernommen: %s, %d Dateien", run_id, outb, len(files))
            self._ev("agent.takeover", r, branch=outb, files=len(files), file_list=files[:40])
            return {"branch": outb, "files": files}

    def remove(self, run_id, force=False):
        with self.lock:
            r = self.store.agent_run(run_id)
            if not r:
                return
            if r["status"] == "läuft":
                raise AgentError("Der Lauf läuft noch. Erst stoppen.")
            if r.get("mode") == "export" and r.get("wt") and not r.get("taken") and not force:
                try:
                    files = self.changes(run_id)
                except AgentError:
                    files = []
                if files:
                    raise AgentError("Die Änderungen des Agenten (%d Dateien) sind noch nicht übernommen. Erst «Übernehmen», oder «Trotzdem entfernen»." % len(files))
            try:
                a = self.agent(r["agent"])
                conn = self.conn_of(a)
                if r.get("mode") in ("worktree", "export") and r.get("wt"):
                    repo, _root = self._paths(a, r["project_id"])
                    self._sh(a, conn, cleanup_script(r["mode"], self._q(a, repo), r["wt"], run_id), run_id)
                if conn is None:
                    for ext in ("exit", "exit.tmp", "log", "hb", "pid", "prompt", "spec.json", "base", "init", "patch", "wd"):
                        try:
                            (self.run_dir / ("%d.%s" % (run_id, ext))).unlink()
                        except OSError:
                            pass
                elif r["status"] != "zugewiesen":
                    run_remote(conn, 'R="$HOME/.tinyops/runs"; rm -f "$R/%d."*; true' % int(run_id), timeout=15)
            except AgentError:
                pass     # Aufräumen ist Beiwerk; der Eintrag verschwindet trotzdem
            self._ev("agent.remove", r, status=r["status"], force=bool(force), taken=r.get("taken") or "")
            self.store.agent_run_delete(run_id)

    # -- Aufbewahrung: alte Logs, Prompts und Patches auf allen Rechnern löschen. Die Läufe in der Liste bleiben, nur ihre Dateien gehen.
    def retention(self, days, now=None):
        days = int(days or 0)
        if days <= 0:
            return None
        now = now or time.time()
        cut = now - days * 86400
        active = {r["id"] for r in self.store.agent_runs(status="läuft")}
        local = 0
        if self.run_dir.is_dir():
            for f in self.run_dir.iterdir():
                m = re.match(r"(\d+)\.", f.name)
                if not m or int(m.group(1)) in active:
                    continue
                try:
                    if f.is_file() and f.stat().st_mtime < cut:
                        f.unlink()
                        local += 1
                except OSError:
                    pass
        remote, failed = {}, []
        used = {a["connection"] for a in self.agent_list() if a["connection"] != "local"}
        for cid in sorted(used):
            conn = self.conns().get(cid)
            if not conn:
                continue
            keep = " ".join("! -name '%d.*'" % i for i in sorted(active))
            script = ('R="$HOME/.tinyops/runs"; [ -d "$R" ] || { echo 0; exit 0; }\n'
                      'find "$R" -maxdepth 1 -type f -mtime +%d %s -print -delete 2>/dev/null | wc -l\n' % (max(0, days - 1), keep))
            try:
                rc, out, err = run_remote(conn, script, timeout=30)
                remote[conn.get("name") or cid] = int((out.strip().splitlines() or ["0"])[-1]) if rc == 0 else 0
                if rc != 0:
                    failed.append(conn.get("name") or cid)
            except (AgentError, ValueError) as e:
                failed.append(conn.get("name") or cid)
                log.warning("Aufbewahrung auf %s: %s", cid, e)
        res = {"days": days, "local": local, "remote": remote, "failed": failed}
        if local or any(remote.values()) or failed:
            try:
                self.audit("agent.retention", "", not failed, "watchdog", **res)
            except Exception as e:
                log.error("Audit agent.retention: %s", e)
            log.info("Aufbewahrung %d Tage: %d lokale, %s entfernte Dateien gelöscht", days, local, remote)
        return res

    def tail(self, run_id, lines=80):
        r = self.store.agent_run(run_id)
        if not r:
            raise AgentError("Diesen Lauf gibt es nicht (mehr).")
        if r["status"] == "zugewiesen":
            return "(noch nicht gestartet)"
        a = self.agent(r["agent"])
        conn = self.conn_of(a)
        n = max(1, min(int(lines), 400))
        if conn is None:
            try:
                data = (self.run_dir / ("%d.log" % run_id)).read_bytes()[-200000:].decode("utf-8", "replace")
            except OSError:
                return "(noch keine Ausgabe)"
            return clean_text("\n".join(data.splitlines()[-n:]))
        rc, out, err = run_remote(conn, 'tail -n %d "$HOME/.tinyops/runs/%d.log" 2>/dev/null || echo "(noch keine Ausgabe)"' % (n, int(run_id)), timeout=20)
        return clean_text(out)
