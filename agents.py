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

import briefing
import secretscan
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
PROVIDER = "\0PROVIDER\0"
PROVIDER_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,39}$")
PROVIDERS = ("ollama", "openai", "litellm", "openrouter")      # Vorschläge; Goose kennt weitere
# Modellnamen, die nach einem Cloud-Modell aussehen. Offene Gewichte wie gpt-oss laufen lokal und zählen nicht.
CLOUD_MODEL_RE = re.compile(r"(?i)(?:^|[/:._-])(?:claude|sonnet|opus|haiku|gpt(?!-oss)|chatgpt|o[134](?:-|$)|gemini|grok)")


def looks_cloud(model):
    return bool(model and CLOUD_MODEL_RE.search(model))
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
    "claude": {"label": "Claude Code", "bin": "claude", "argv": ["claude", "-p", PROMPT], "provider": "Anthropic",
               "write_flags": ("--permission-mode", "--dangerously-skip-permissions", "--allowedTools", "--allowed-tools"), "write_hint": "--permission-mode acceptEdits"},
    "codex": {"label": "Codex", "bin": "codex", "argv": ["codex", "exec", PROMPT], "provider": "OpenAI",
              "write_flags": ("--full-auto", "--sandbox", "-s", "--dangerously-bypass-approvals-and-sandbox"), "write_hint": "--full-auto"},
    "vibe": {"label": "Mistral Vibe", "bin": "vibe", "argv": ["vibe", "-p", PROMPT], "provider": "Mistral"},
    # Lokale Agenten: Aufrufe aus der Dokumentation der CLIs abgeleitet, nicht gegen die echten Programme getestet.
    # Anbieter und Modell je Agent (0.27): Laufen alle Modelle über denselben Proxy, sagt nur der Agent-Eintrag, ob ein Modell lokal ist.
    "goose": {"label": "Goose", "bin": "goose", "argv": ["goose", "run", "-i", PROMPT_FILE], "provider": "dem in Goose eingestellten Anbieter",
              "env": {"GOOSE_PROVIDER": PROVIDER, "GOOSE_MODEL": MODEL}, "local": True},
    "opencode": {"label": "opencode", "bin": "opencode", "argv": ["opencode", "run", "--model", PROVIDER + "/" + MODEL, PROMPT],
                 "provider": "dem in opencode eingestellten Anbieter", "local": True},
    "custom": {"label": "Eigener Befehl", "bin": "", "argv": None, "provider": "dem Anbieter des Befehls", "local": True},
}
ANSI = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]|\x1b\][^\x07]*\x07")

RUNNER = '''R="$HOME/.tinyops/runs"
ID="$1"
export R ID
{ "${SHELL:-/bin/sh}" -l -c 'PATH="$R/bin:$PATH"; TINYOPS_RUN_DIR="$R"; TINYOPS_RUN_ID="$ID"; export PATH TINYOPS_RUN_DIR TINYOPS_RUN_ID; exec sh "$R/$ID.cmd"'; echo $? > "$R/$ID.exit.tmp"; mv "$R/$ID.exit.tmp" "$R/$ID.exit"; } 2>&1 | tee "$R/$ID.log"
'''

# ------------------------------------------------------------------ Hilfsskripte für den Agenten (0.18): fragen, belegen, berichten
# Sie liegen in $R/bin und stehen im PATH des Laufs. Reines POSIX-sh, ohne Python, damit sie auf jedem Zielhost laufen.
_HELPER_HEAD = r'''#!/bin/sh
R="${TINYOPS_RUN_DIR:-$HOME/.tinyops/runs}"; N="${TINYOPS_RUN_ID:-}"
case "$N" in ""|*[!0-9]*) echo "tinyops: TINYOPS_RUN_ID fehlt, das geht nur in einem Lauf aus tinyops." >&2; exit 2;; esac
j() { printf '%s' "$1" | tr '\n\r\t' '   ' | tr -d '\000-\037' | sed 's/\\/\\\\/g; s/"/\\"/g'; }
'''
HELPERS = {
    "tinyops-ask": _HELPER_HEAD + r'''# tinyops-ask [-n] [-t SEK] "Frage" ["Option" ...]   fragt den Menschen in tinyops und gibt die Antwort aus
# tinyops-ask --wait NR [-t SEK]                     wartet weiter auf die Antwort zu Frage NR
# Exit 3: noch keine Antwort nach SEK Sekunden (Standard 100). Dann mit --wait NR weiter warten, nicht neu fragen.
wait=1; to="${TINYOPS_ASK_TIMEOUT:-100}"; K=""
while [ $# -gt 0 ]; do case "$1" in -n) wait=0; shift;; -t) to="$2"; shift 2;; --wait) K="$2"; shift 2;; *) break;; esac; done
case "$to" in ""|*[!0-9]*) to=100;; esac
if [ -z "$K" ]; then
  [ -n "$1" ] || { echo 'Aufruf: tinyops-ask [-n] [-t SEK] "Frage" ["Option" ...]' >&2; exit 2; }
  K=$(( $(cat "$R/$N.qn" 2>/dev/null || echo 0) + 1 )); echo "$K" > "$R/$N.qn"
  Q=$(j "$1"); shift; O=""
  for o in "$@"; do O="$O${O:+, }\"$(j "$o")\""; done
  b=true; [ "$wait" = 1 ] || b=false
  printf '{"id": %d, "question": "%s", "options": [%s], "blocking": %s, "ts": %s}\n' "$K" "$Q" "$O" "$b" "$(date +%s)" > "$R/$N.question.tmp" && mv "$R/$N.question.tmp" "$R/$N.question.json"
  [ "$wait" = 1 ] || { echo "$K"; exit 0; }
  echo "[tinyops] Frage $K gestellt. Warte auf die Antwort in tinyops ..." >&2
fi
case "$K" in ""|*[!0-9]*) echo "tinyops-ask: Fragenummer fehlt" >&2; exit 2;; esac
t=0
while [ ! -f "$R/$N.answer.$K" ]; do
  if [ "$to" -gt 0 ] && [ "$t" -ge "$to" ]; then echo "[tinyops] Noch keine Antwort auf Frage $K. Weiter warten mit: tinyops-ask --wait $K" >&2; exit 3; fi
  sleep 2; t=$((t + 2))
done
cat "$R/$N.answer.$K"
''',
    "tinyops-check": _HELPER_HEAD + r'''# tinyops-check BEFEHL [ARG ...]   führt den Befehl aus und hält Befehl, Exit-Code und Dauer als Beleg fest
[ $# -gt 0 ] || { echo "Aufruf: tinyops-check BEFEHL [ARG ...]" >&2; exit 2; }
t0=$(date +%s); "$@"; rc=$?; t1=$(date +%s)
printf '{"cmd": "%s", "exit": %d, "secs": %d, "ts": %d}\n' "$(j "$*")" "$rc" $((t1 - t0)) "$t1" >> "$R/$N.checks"
echo "[tinyops-check] Exit $rc nach $((t1 - t0)) s: $*" >&2
exit $rc
''',
    "tinyops-ak": _HELPER_HEAD + r'''# tinyops-ak NR erfüllt|offen|unklar ["Beleg oder Grund"]   meldet den Stand eines Akzeptanzkriteriums (AK1, AK2 …) an tinyops
# Auch: ok, erfuellt, done | offen, open, fail | unklar, unclear. Die letzte Meldung je Kriterium gilt.
k=$(printf '%s' "$1" | sed 's/^[Aa][Kk]//')
case "$k" in ""|*[!0-9]*) echo 'Aufruf: tinyops-ak NR erfüllt|offen|unklar ["Beleg oder Grund"]' >&2; exit 2;; esac
case "$2" in ok|OK|erf*|done|ja|pass*) s=ok;; offen|open|fail*|nein|nicht*) s=open;; unklar|unclear|block*|"?") s=unclear;;
  *) echo 'tinyops-ak: Stand fehlt. Erlaubt: erfüllt, offen, unklar' >&2; exit 2;; esac
printf '{"n": %d, "state": "%s", "note": "%s", "ts": %s}\n' "$k" "$s" "$(j "$3" | cut -c1-400)" "$(date +%s)" >> "$R/$N.ak"
echo "[tinyops] AK$k: $s" >&2
''',
    "tinyops-report": _HELPER_HEAD + r'''# tinyops-report < bericht.md   oder   tinyops-report "Text"   speichert den Ergebnisbericht (Markdown, höchstens 20 KB)
if [ $# -gt 0 ]; then printf '%s\n' "$*"; else cat; fi | head -c 20000 > "$R/$N.summary.md.tmp" && mv "$R/$N.summary.md.tmp" "$R/$N.summary.md"
echo "[tinyops] Bericht gespeichert." >&2
''',
}


def helpers_script():
    """Shell, die die Hilfsskripte nach $R/bin schreibt (Teil des Startskripts auf dem Zielhost)."""
    out = ['mkdir -p "$R/bin"']
    for name, body in HELPERS.items():
        d = _delim(body)
        out.append("cat > \"$R/bin/%s\" <<'%s'\n%s%s\nchmod 755 \"$R/bin/%s\"" % (name, d, body, d, name))
    return "\n".join(out) + "\n"


def write_helpers(run_dir):
    b = Path(run_dir) / "bin"
    b.mkdir(parents=True, exist_ok=True)
    for name, body in HELPERS.items():
        f = b / name
        f.write_text(body, encoding="utf-8", newline="\n")
        try:
            f.chmod(0o755)
        except OSError:
            pass
    return b


def parse_question(text):
    """Frage aus <nr>.question.json. Ungültiges JSON zählt als Frage im Klartext (Nr 0 wird nie beantwortet erwartet)."""
    text = (text or "").strip()
    if not text:
        return None
    try:
        q = json.loads(text)
        if not isinstance(q, dict):
            raise ValueError
    except ValueError:
        return {"id": 1, "question": clean_text(text, 1000), "options": [], "blocking": True, "raw": True}
    try:
        qid = int(q.get("id") or 1)
    except (TypeError, ValueError):
        qid = 1
    opts = [clean_text(str(o), 200).strip() for o in (q.get("options") or []) if str(o).strip()][:8] if isinstance(q.get("options"), list) else []
    return {"id": qid, "question": clean_text(str(q.get("question") or ""), 1000).strip() or "(leere Frage)", "options": opts,
            "blocking": q.get("blocking") is not False}


def parse_checks(text):
    out = []
    for line in (text or "").splitlines()[-50:]:
        try:
            c = json.loads(line)
            out.append({"cmd": clean_text(str(c.get("cmd") or ""), 300).strip(), "exit": int(c.get("exit")), "secs": int(c.get("secs") or 0),
                        "ts": int(c.get("ts") or 0)})
        except (ValueError, TypeError, AttributeError):
            continue
    return out


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
            elif not model and (kind == "opencode" or str(a.get("provider", "ollama") or "")):
                errors[k + "model"] = "Welches Modell (z. B. qwen2.5-coder:32b)? Bei Goose ohne Anbieter darf es leer bleiben."
        iso = a.get("isolation") if a.get("isolation") in ISOLATION else "worktree"
        # Cloud: Claude, Codex, Vibe immer; lokale Arten nur, wenn du es so einstellst (Standard: lokal)
        cloud = True if not KINDS[kind].get("local") else bool(a.get("cloud", False))
        entry = {"id": aid, "name": str(a.get("name") or aid).strip()[:40] or aid, "kind": kind, "connection": conn, "workspace_root": root, "max_minutes": mx,
                 "extra_args": extra, "cloud": cloud, "isolation": iso}
        if KINDS[kind].get("local") and kind != "custom":
            if model:
                entry["model"] = model
            prov = str(a.get("provider", "ollama") or "").strip().lower()
            if prov and not PROVIDER_RE.fullmatch(prov):
                errors[k + "provider"] = "Anbieter: Kleinbuchstaben, Ziffern, - und _ (z. B. ollama, openai, litellm)."
            elif not prov and kind == "opencode":
                errors[k + "provider"] = "opencode braucht einen Anbieter (z. B. ollama)."
            else:
                entry["provider"] = prov
        via = a.get("clone_via")
        entry["clone_via"] = via if via in ("ssh", "https") else "ssh"
        cmd = (old.get(aid) or {}).get("command")
        if kind == "custom" and cmd:
            entry["command"] = str(cmd)
        out.append(entry)
    return out


CLONE_URL_RE = re.compile(r"^(?:https://[A-Za-z0-9.-]+(?::\d+)?/|ssh://(?:[A-Za-z0-9._-]+@)?[A-Za-z0-9.-]+(?::\d+)?/|[A-Za-z0-9._-]+@[A-Za-z0-9.-]+:)[A-Za-z0-9._~/+-]+$")


def clone_hint(msg, url):
    """Fehlermeldung von git clone, mit dem nächsten Schritt in einfachen Worten."""
    low = msg.lower()
    host = (re.search(r"@([A-Za-z0-9.-]+)", url) or re.search(r"//([A-Za-z0-9.-]+)", url) or [None, "dem Git-Server"])[1]
    if "host key verification failed" in low:
        return msg + "\nDer Zielrechner kennt %s noch nicht. Einmal dort von Hand: ssh -T git@%s" % (host, host)
    if "permission denied" in low or "could not read from remote" in low:
        return msg + "\nDer Benutzer auf dem Zielrechner hat keinen Schlüssel, den %s für dieses Projekt akzeptiert (Deploy-Key oder SSH-Schlüssel des Benutzers hinterlegen)." % host
    if "could not read username" in low or "authentication failed" in low or "terminal prompts disabled" in low:
        return msg + "\nFür HTTPS fehlen auf dem Zielrechner gespeicherte Zugangsdaten (git credential helper). Einfacher: beim Agenten «Klonen über SSH»."
    if "not found" in low and "repository" in low:
        return msg + "\nDas Repository gibt es unter dieser Adresse nicht, oder der Benutzer darf es nicht sehen."
    return msg


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


def _sub_model(a, model, provider="ollama"):
    return a.replace(MODEL, model or "").replace(PROVIDER, provider or "")


def provider_of(agent):
    """Anbieter für Goose/opencode. Alte Einträge ohne Angabe: ollama. Leer: Goose nimmt, was in seiner eigenen Konfiguration steht."""
    return agent.get("provider", "ollama") or ""


def agent_env(agent):
    """Umgebungsvariablen der Art, ohne leere Werte (leerer Anbieter oder leeres Modell: die eigene Konfiguration der CLI gilt)."""
    out = {}
    for k, v in (KINDS[agent["kind"]].get("env") or {}).items():
        v = _sub_model(v, agent.get("model", ""), provider_of(agent))
        if v:
            out[k] = v
    return out


def agent_args(agent):
    """Feste Argumente der Art mit Anbieter/Modell. opencode ohne Anbieter: nur der Modellname."""
    out = []
    for a in KINDS[agent["kind"]]["argv"]:
        if a in (PROMPT, PROMPT_FILE):
            out.append(a)
        else:
            out.append(_sub_model(a, agent.get("model", ""), provider_of(agent)).lstrip("/"))
    return out


def remote_cmdline(agent):
    """Zeile für `<Nr>.cmd` auf dem Zielhost. Der Prompt wird dort aus der Datei gelesen, nicht eingebettet."""
    if agent["kind"] == "custom":
        cmd = agent.get("command")
        if not cmd:
            raise AgentError("Für diesen eigenen Agenten steht kein «command» in der config.json (die Oberfläche kann ihn nicht setzen).")
        return cmd.replace("{prompt_file}", '"$R/$ID.prompt"')
    parts = ["%s=%s" % (k, shlex.quote(v)) for k, v in agent_env(agent).items()]
    for a in agent_args(agent) + _extra(agent):
        parts.append('"$(cat "$R/$ID.prompt")"' if a == PROMPT else '"$R/$ID.prompt"' if a == PROMPT_FILE else shlex.quote(a))
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
    argv = [exe] + [prompt if a == PROMPT else str(prompt_file) if a == PROMPT_FILE else a for a in agent_args(agent)[1:] + _extra(agent)]
    out = {"argv": argv, "cwd": workdir}
    if agent_env(agent):
        out["env"] = agent_env(agent)
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
rm -f "$R/{rid}.question.json" "$R/{rid}.qn" "$R/{rid}.checks" "$R/{rid}.ak" "$R/{rid}.summary.md" "$R/{rid}.answer."*
{helpers}ID={rid}
{prep}echo "$WD" > "$R/{rid}.wd"
tmux new-session -d -s tinyops-{rid} -c "$WD" "sh '$R/runner.sh' {rid}"
echo "started $WD"
""".format(rid=int(rid), d1=d1, d2=d2, prompt=prompt, cmdline=cmdline, runner=RUNNER, helpers=helpers_script(), prep=prep if prep is not None else 'REPO=%s\n[ -d "$REPO" ] || {{ echo "Arbeitsverzeichnis fehlt" >&2; exit 41; }}\nWD="$REPO"\n'.replace("{{", "{").replace("}}", "}") % wd)


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
            'else echo "$i gone"; fi; '
            'if [ -f "$R/$i.question.json" ]; then printf "%%s q " "$i"; head -c 4000 "$R/$i.question.json" | tr "\\n\\r" "  "; echo; fi; done') % " ".join(str(int(i)) for i in ids)


def remote_report_script(rid):
    return ('R="$HOME/.tinyops/runs"; echo "@@SUMMARY"; head -c 20000 "$R/%d.summary.md" 2>/dev/null; echo; echo "@@CHECKS"; '
            'tail -n 50 "$R/%d.checks" 2>/dev/null; echo "@@AK"; tail -n 200 "$R/%d.ak" 2>/dev/null; true') % (int(rid), int(rid), int(rid))


def result_script(wt, mode):
    """Was der Lauf am Code geändert hat, gegen den Ausgangsstand: Commits, Dateien, Umfang, offene Änderungen. Nur lesend. Erwartet R und ID."""
    base = "init" if mode == "export" else "base"
    return ('cd %s 2>/dev/null || exit 0; B=$(cat "$R/$ID.%s" 2>/dev/null); [ -n "$B" ] || exit 0; export GIT_OPTIONAL_LOCKS=0; '
            'echo "@@COMMITS"; git log --format="%%h %%s" "$B..HEAD" 2>/dev/null | head -n 30; '
            'echo "@@STAT"; git diff --shortstat "$B" 2>/dev/null; '
            'echo "@@FILES"; git diff --name-status "$B" 2>/dev/null | head -n 80; '
            'echo "@@DIRTY"; git status --porcelain 2>/dev/null | wc -l; '
            'echo "@@DIFF"; git diff -U0 --no-color "$B" 2>/dev/null | head -c 400000; true') % (shlex.quote(wt), base)


def parse_result(out):
    """Ausgabe von result_script lesen."""
    head, _, diff = (out or "").partition("@@DIFF")      # im Diff beginnen Hunk-Köpfe mit @@: er steht deshalb am Ende und wird vorher abgetrennt
    sec, cur = {"DIFF": diff.splitlines()}, None
    for line in head.splitlines():
        if line.startswith("@@"):
            cur = line[2:].strip()
            sec[cur] = []
        elif cur:
            sec[cur].append(line)
    if "COMMITS" not in sec:
        return None
    commits = [{"sha": x.split(" ", 1)[0], "subject": clean_text(x.split(" ", 1)[1] if " " in x else "", 200).strip()} for x in sec["COMMITS"] if x.strip()]
    files = []
    for x in sec.get("FILES") or []:
        p = x.split("\t")
        if len(p) >= 2:
            files.append({"st": p[0][:1], "path": clean_text(p[-1], 300).strip()})
    stat = " ".join(" ".join(sec.get("STAT") or []).split())
    try:
        dirty = int("".join(sec.get("DIRTY") or ["0"]).strip() or 0)
    except ValueError:
        dirty = 0
    secrets = secretscan.scan_diff("\n".join(sec.get("DIFF") or []), "Ergebnis des Laufs")[:20]
    return {"commits": commits, "files": files, "stat": clean_text(stat, 200), "dirty": dirty, "secrets": secrets}


def answer_script(rid, qid, text):
    d = _delim(text)
    return ('R="$HOME/.tinyops/runs"; [ -d "$R" ] || exit 4\n'
            'cat > "$R/{rid}.answer.{q}.tmp" <<\'{d}\'\n{text}\n{d}\n'
            'mv "$R/{rid}.answer.{q}.tmp" "$R/{rid}.answer.{q}"\n'
            'grep -q \'"id": {q},\' "$R/{rid}.question.json" 2>/dev/null && rm -f "$R/{rid}.question.json"\necho ok\n').format(rid=int(rid), q=int(qid), d=d, text=text)


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
        self._access, self._clones = {}, {}       # Zugriff je Agent (kurz gemerkt) und laufende Klone
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
        if cls == "restricted" and looks_cloud(agent.get("model", "")):
            return False, ("Projekt «%s» ist restricted, und das Modell «%s» sieht nach einem Cloud-Modell aus, obwohl der Agent als lokal eingetragen ist. "
                           "Laufen alle Modelle über denselben Proxy, erkennt tinyops den Unterschied nur am Eintrag: Für ein wirklich lokales Modell dem "
                           "Proxy-Alias einen eindeutigen Namen geben (z. B. qwen-lokal)." % (p.get("name"), agent.get("model")))
        return True, ""

    def mode(self, agent, pid):
        """Wie der Agent arbeitet: export (nur freigegebene Pfade, eigenes Git), worktree (eigener Branch) oder shared (alter gemeinsamer Ordner)."""
        p = self.project(pid) or {}
        if agent.get("cloud", True) and data_class(p) == "internal" and p.get("cloud_paths"):
            return "export"
        return "shared" if agent.get("isolation") == "shared" else "worktree"

    # -- Zugriff: Welche Projekte liegen beim Agenten? (0.27)
    def access(self, aid, fresh=False):
        """Je Projekt: liegt das Repository im Arbeitsordner des Agenten? {pid: {"state": git|dir|missing, "remote": …, "path": …}}. Eine Minute gemerkt."""
        a = self.agent(aid)
        hit = self._access.get(aid)
        if hit and not fresh and time.time() - hit[0] < 60:
            return hit[1]
        conn = self.conn_of(a)
        rows = []
        for p in self.projects():
            try:
                rows.append((p["id"], self.workdir(a, p["id"])))
            except AgentError:
                pass
        parts = ['export GIT_OPTIONAL_LOCKS=0']
        for pid, wd in rows:
            q = _sh_path(wd) if conn is not None else shlex.quote(wd)
            parts.append('if [ -d %s/.git ] || [ -f %s/.git ]; then echo "%d|git|$(git -C %s config --get remote.origin.url 2>/dev/null)"; '
                         'elif [ -e %s ]; then echo "%d|dir|"; else echo "%d|missing|"; fi' % (q, q, pid, q, q, pid, pid))
        rc, out, err = self._sh(a, conn, "; ".join(parts), 0, timeout=25)
        if rc != 0 and not out.strip():
            raise AgentError("Der Arbeitsordner des Agenten ist nicht lesbar: %s" % (clean_text(err, 300).strip() or "Exit %s" % rc))
        paths, res = dict(rows), {}
        for line in out.splitlines():
            f = line.split("|", 2)
            if len(f) == 3 and f[0].isdigit() and f[1] in ("git", "dir", "missing"):
                res[int(f[0])] = {"state": f[1], "remote": re.sub(r"//[^/@\s]+@", "//", clean_text(f[2], 300).strip()), "path": paths.get(int(f[0]), "")}
        self._access[aid] = (time.time(), res)
        return res

    def clone_state(self, aid, pid):
        return dict(self._clones.get((aid, pid)) or {"state": ""})

    def clone(self, aid, pid, url):
        """Das Projekt im Arbeitsordner des Agenten klonen (im Hintergrund). Nur lesend gegenüber dem Server; Zugangsdaten sind die des Zielrechners."""
        a = self.agent(aid)
        p = self.project(pid)
        if p is None:
            raise AgentError("Projekt fehlt.")
        ok, why = self.allowed(a, pid)
        if not ok:
            raise AgentError(why)
        if not CLONE_URL_RE.fullmatch(url or "") or ".." in url:
            raise AgentError("Die Adresse zum Klonen ist ungültig.")
        st = self.access(aid, fresh=True).get(pid) or {}
        if st.get("state") != "missing":
            raise AgentError("Unter %s liegt schon etwas. tinyops überschreibt nichts." % (st.get("path") or "dem Zielpfad"))
        with self.lock:
            if (self._clones.get((aid, pid)) or {}).get("state") == "läuft":
                raise AgentError("Dieses Projekt wird gerade geklont.")
            self._clones[(aid, pid)] = {"state": "läuft", "msg": "", "ts": time.time(), "url": url}
        conn, wd = self.conn_of(a), self.workdir(a, pid)
        q = _sh_path(wd) if conn is not None else shlex.quote(wd)
        script = ('D=%s; [ -e "$D" ] && { echo "Zielordner existiert schon" >&2; exit 3; }; mkdir -p "$(dirname "$D")" || exit 4; '
                  'GIT_TERMINAL_PROMPT=0 GIT_SSH_COMMAND="ssh -o BatchMode=yes" git clone --quiet -- %s "$D" 2>&1 | tail -n 6; '
                  '[ -d "$D/.git" ] || exit 5') % (q, shlex.quote(url))
        self.audit("agent.clone.start", "%s → %s" % (p.get("name"), a["id"]), agent=a["id"], project=pid, url=url, path=wd)

        def work():
            t0 = time.time()
            try:
                rc, out, err = self._sh(a, conn, script, 0, timeout=1200)
                msg = clean_text((out or "") + (err or ""), 1500).strip()
            except AgentError as e:
                rc, msg = 1, str(e)
            msg = re.sub(r"//[^/@\s]+@", "//", msg)
            ok_ = rc == 0
            self._clones[(aid, pid)] = {"state": "fertig" if ok_ else "fehler", "msg": "" if ok_ else (clone_hint(msg, url) or "Exit %s" % rc), "ts": time.time(), "url": url}
            self._access.pop(aid, None)
            self.audit("agent.clone", "%s → %s" % (p.get("name"), a["id"]), ok=ok_, agent=a["id"], project=pid, url=url, path=wd, seconds=int(time.time() - t0),
                       error="" if ok_ else msg[:300])
        threading.Thread(target=work, name="tinyops-clone", daemon=True).start()
        return self.clone_state(aid, pid)

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

    def default_prompt(self, title, key, project, branch, url="", mode="shared", paths=(), template="agent-task", extra=None):
        """Prompt aus prompts/<template>.md plus die Werkzeug-Hinweise aus prompts/agent-tools.md."""
        f = self.base / "prompts" / ("%s.md" % template)
        try:
            tpl = f.read_text(encoding="utf-8")
        except OSError:
            tpl = "Aufgabe {key}: {title}\nProjekt: {project}\nBranch: {branch}\n{url_line}"
        try:
            tools = (self.base / "prompts" / "agent-tools.md").read_text(encoding="utf-8").strip()
        except OSError:
            tools = ""

        class D(dict):
            def __missing__(self, k):
                return ""
        ws = self.WORKSPACE_LINES.get(mode, self.WORKSPACE_LINES["shared"]).replace("{branch}", branch or "dem Hauptbranch").replace("{paths}", ", ".join(paths) or "-")
        vals = D(key=key or "(ohne Key)", title=title or "", project=project or "", branch=branch or "(noch keiner)",
                 url_line=("Link: %s\n" % url) if url else "", workspace_line=ws)
        vals.update(extra or {})
        out = re.sub(r"\n{3,}", "\n\n", tpl.format_map(vals)).strip() + "\n"
        return out + ("\n" + tools + "\n" if tools else "")

    def prompt_info(self, aid, ticket, pid, branch, title, key, url="", template="agent-task", extra=None):
        a = self.agent(aid)
        conn = self.conn_of(a)
        ok, why = self.allowed(a, pid)
        try:
            wd = self.workdir(a, pid)
        except AgentError as e:
            wd, ok, why = "", False, str(e)
        p = self.project(pid) or {}
        mode = self.mode(a, pid) if p else "shared"
        hints = []
        spec = KINDS[a["kind"]]
        if spec.get("write_flags") and not any(x.split("=")[0] in spec["write_flags"] for x in _extra(a)):
            hints.append("%s läuft hier ohne Rückfrage-Fenster. Ohne «%s» in den zusätzlichen Argumenten (Einstellungen → Agenten) darf es laut Dokumentation "
                         "der CLI keine Dateien ändern und endet dann ohne Ergebnis." % (spec["label"], spec["write_hint"]))
        if KINDS[a["kind"]].get("local") and not a.get("cloud", True) and looks_cloud(a.get("model", "")):
            hints.append("Das Modell «%s» sieht nach einem Cloud-Modell aus, der Agent ist aber als lokal eingetragen. Stimmt das nicht, unter "
                         "Einstellungen → Agenten «sendet Daten an einen Cloud-Anbieter» anhaken." % a.get("model"))
        return {"prompt": self.default_prompt(title, key, p.get("name", ""), branch, url, mode, p.get("cloud_paths") or [], template, extra), "workdir": wd,
                "hints": hints, "model": a.get("model", ""),
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
        for k, empty in (("question", None), ("qa", []), ("checks", []), ("criteria", []), ("ak", []), ("result", None)):
            try:
                v[k] = json.loads(r[k]) if r.get(k) else empty
            except ValueError:
                v[k] = empty
        v["criteria"] = briefing.merge(v["criteria"] or [], v.pop("ak") or [])
        v["ak"] = briefing.counts(v["criteria"])
        v["ack"] = bool(r.get("ack"))
        v["checks_ok"] = all(c["exit"] == 0 for c in v["checks"]) if v["checks"] else None
        v.update(agent_name=a["name"] if a else r["agent"] + " (entfernt)", kind=a["kind"] if a else "custom",
                 where=("lokal" if a and a["connection"] == "local" else conn["name"] if conn else "?"),
                 active=r["status"] in STATUS_ACTIVE, secs=int(end - r["started"]) if r["started"] else 0,
                 attach=("ssh -t -p %s %s tmux attach -t tinyops-%d" % (conn["port"], (("%s@%s" % (conn["user"], conn["host"])) if conn["user"] else conn["host"]), r["id"])) if conn else "")
        return v

    def view(self):
        agents = [{"id": a["id"], "name": a["name"], "kind": a["kind"], "label": KINDS[a["kind"]]["label"], "cloud": a.get("cloud", True),
                   "isolation": a.get("isolation", "worktree"), "model": a.get("model", ""),
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
            crit = briefing.parse_prompt(prompt)
            self.store.agent_run_update(run_id, project_id=pid, branch=branch, workdir=wd, prompt=prompt, mode=mode, out_branch=outb,
                                        criteria=json.dumps(crit, ensure_ascii=False), ak="", result="")
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
                     workdir=wd, branch=branch, out_branch=outb, criteria=len(crit), max_minutes=int(a.get("max_minutes", DEFAULT_MAX_MINUTES) or 0))
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
        for f in list(d.glob("%d.answer.*" % rid)) + [d / ("%d.%s" % (rid, x)) for x in ("question.json", "qn", "checks", "ak", "summary.md")]:
            try:
                f.unlink()
            except OSError:
                pass
        pf = d / ("%d.prompt" % rid)
        pf.write_text(prompt, encoding="utf-8")
        spec = local_spec(a, prompt, pf, wd)
        hb = write_helpers(d)
        spec["env"] = dict(spec.get("env") or {}, TINYOPS_RUN_DIR=str(d), TINYOPS_RUN_ID=str(rid),
                           PATH=str(hb) + os.pathsep + os.environ.get("PATH", ""))
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

    def _local_question(self, r):
        try:
            return (self.run_dir / ("%d.question.json" % r["id"])).read_text(encoding="utf-8", errors="replace")[:4000]
        except OSError:
            return ""

    # -- Rückfragen (0.18)
    def _note_question(self, r, raw):
        """Neue Frage merken (genau einmal je Nummer), beantwortete oder verschwundene vergessen."""
        q = parse_question(raw) if raw else None
        answered = int(r.get("answered") or 0)
        cur = json.loads(r["question"]) if r.get("question") else None
        if q and q["id"] > answered:
            if not cur or cur.get("id") != q["id"]:
                q["ts"] = time.time()
                self.store.agent_run_update(r["id"], question=json.dumps(q, ensure_ascii=False))
                self._ev("agent.question", r, actor="agent", question=q["question"][:300], options=q["options"], blocking=q["blocking"], qid=q["id"])
                log.info("Lauf %d fragt (%d): %s", r["id"], q["id"], q["question"][:120])
        elif cur:
            self.store.agent_run_update(r["id"], question="")

    def answer(self, run_id, qid, text):
        text = str(text or "").replace("\r\n", "\n").strip()
        if not text or len(text) > 4000 or "\0" in text:
            raise AgentError("Die Antwort fehlt oder ist länger als 4000 Zeichen.")
        with self.lock:
            r = self.store.agent_run(run_id)
            if not r or r["status"] != "läuft":
                raise AgentError("Der Lauf läuft nicht mehr; die Antwort kommt nicht mehr an.")
            cur = json.loads(r["question"]) if r.get("question") else None
            try:
                qid = int(qid)
            except (TypeError, ValueError):
                raise AgentError("Fragenummer fehlt.")
            if not cur or cur.get("id") != qid:
                raise AgentError("Diese Frage ist nicht (mehr) offen.")
            a = self.agent(r["agent"])
            conn = self.conn_of(a)
            if conn is None:
                d = self.run_dir
                tmp = d / ("%d.answer.%d.tmp" % (run_id, qid))
                tmp.write_text(text + "\n", encoding="utf-8")
                os.replace(tmp, d / ("%d.answer.%d" % (run_id, qid)))
                try:
                    (d / ("%d.question.json" % run_id)).unlink()
                except OSError:
                    pass
            else:
                rc, out, err = run_remote(conn, answer_script(run_id, qid, text), timeout=20)
                if rc != 0 or "ok" not in out:
                    raise AgentError("Antwort nicht zugestellt (Exit %d): %s" % (rc, clean_text(err or out, 200).strip()))
            qa = json.loads(r["qa"]) if r.get("qa") else []
            qa.append({"id": qid, "q": cur.get("question", ""), "options": cur.get("options") or [], "a": text[:2000], "ts_q": cur.get("ts"), "ts_a": time.time()})
            self.store.agent_run_update(run_id, question="", answered=str(qid), qa=json.dumps(qa[-20:], ensure_ascii=False))
            self._ev("agent.answer", r, qid=qid, question=cur.get("question", "")[:300], answer=text[:300])
            return {"ok": True}

    # -- Ergebnisbericht und Belege (0.18)
    def collect(self, r):
        """Bericht (<nr>.summary.md) und Belege (<nr>.checks) einsammeln. Fehler sind still: Der Bericht ist eine Zugabe."""
        try:
            a = self.agent(r["agent"])
            conn = self.conn_of(a)
            if conn is None:
                d = self.run_dir
                rd = lambda ext: (d / ("%d.%s" % (r["id"], ext))).read_text(encoding="utf-8", errors="replace") if (d / ("%d.%s" % (r["id"], ext))).exists() else ""
                summary, checks, ak = rd("summary.md")[:20000], rd("checks"), rd("ak")
            else:
                rc, out, _ = run_remote(conn, remote_report_script(r["id"]), timeout=20)
                if rc != 0 or "@@CHECKS" not in out:
                    return False
                head, _, checks = out.partition("@@CHECKS")
                checks, _, ak = checks.partition("@@AK")
                summary = head.split("@@SUMMARY", 1)[-1].strip("\n")
            self.store.agent_run_update(r["id"], summary=clean_text(summary, 20000).strip(), checks=json.dumps(parse_checks(checks), ensure_ascii=False),
                                        ak=json.dumps(briefing.parse_ak(clean_text(ak, 60000)), ensure_ascii=False))
            cur = self.store.agent_run(r["id"]) or r
            if cur.get("wt") and cur.get("mode") in ("worktree", "export"):      # was am Code geändert wurde; fehlt der Ordner schon, bleibt der alte Stand
                rc, out, _ = self._sh(a, conn, result_script(cur["wt"], cur["mode"]), r["id"], timeout=25)
                res = parse_result(out) if rc == 0 else None
                if res is not None:
                    self.store.agent_run_update(r["id"], result=json.dumps(res, ensure_ascii=False))
            return True
        except (AgentError, OSError) as e:
            log.debug("Bericht von Lauf %s nicht lesbar: %s", r.get("id"), e)
            return False

    def ack(self, run_id):
        r = self.store.agent_run(run_id)
        if r and r["status"] not in ("zugewiesen", "läuft"):
            self.store.agent_run_update(run_id, ack="1")

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
                qs = {}
                if cid == "local":
                    res = {r["id"]: self._local_status(r) for r in runs}
                    qs = {r["id"]: self._local_question(r) for r in runs}
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
                        if len(p) >= 2 and p[0].isdigit() and p[1] == "q":
                            qs[int(p[0])] = line.split(" q ", 1)[1] if " q " in line else ""
                            continue
                        if len(p) >= 2 and p[0].isdigit():
                            res[int(p[0])] = ("exit", int(p[2]) if len(p) > 2 and p[2].lstrip("-").isdigit() else 1) if p[1] == "exit" else (p[1], 0)
                for r in runs:
                    st = res.get(r["id"])
                    if st is None:
                        continue
                    if st[0] == "exit":
                        self.store.agent_run_update(r["id"], status="fertig" if st[1] == 0 else "fehlgeschlagen", exit_code=st[1], finished=time.time(), note="",
                                                    question="")
                        self.collect(r)
                        self._ev("agent.finish", r, ok=st[1] == 0, actor="agent", status="fertig" if st[1] == 0 else "fehlgeschlagen", exit_code=st[1],
                                 minutes=int((time.time() - (r["started"] or time.time())) // 60))
                    elif st[0] == "gone":
                        self.store.agent_run_update(r["id"], status="verloren", finished=time.time(), question="",
                                                    note="Weder Exit-Datei noch Sitzung gefunden (Zielhost neu gestartet, tmux beendet?).")
                        self.collect(r)
                        self._ev("agent.finish", r, ok=False, actor="agent", status="verloren")
                    else:
                        if r["note"]:
                            self.store.agent_run_update(r["id"], note="")
                        self._note_question(self.store.agent_run(r["id"]), qs.get(r["id"], ""))

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
        self.store.agent_run_update(r["id"], status="abgelaufen", finished=time.time(), question="",
                                    note="Zeitlimit von %d min erreicht und beendet." % mx + (" Eine Frage war noch offen." if r.get("question") else ""))
        self.collect(r)
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
            self.store.agent_run_update(run_id, status="abgebrochen", finished=time.time(), note="Von dir gestoppt.", question="")
            self.collect(r)
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
                    for f in self.run_dir.glob("%d.*" % run_id) if self.run_dir.is_dir() else []:
                        try:
                            f.unlink()
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
