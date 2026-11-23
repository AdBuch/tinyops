"""Aufruf der Agenten-Programme: Arten (Claude Code, Codex, Vibe, Goose, opencode, eigener Befehl), Argumente, Umgebung,
lesbare Ausgabe aus dem Streaming, Befehlszeile für SSH und lokal.

0.40 aus agents.py gelöst; agents.py gibt alle Namen weiter."""
import json
import os
import re
import shlex
import shutil
import subprocess
import uuid

import secretstore as store
from agent_rules import AgentError, looks_cloud  # noqa: F401

PROMPT = "\0PROMPT\0"


PROMPT_FILE = "\0PROMPT_FILE\0"


MODEL = "\0MODEL\0"


PROVIDER = "\0PROVIDER\0"


KINDS = {
    # stream_args: damit man im Lauf sieht, was passiert. Im Druckmodus geben Claude Code und Vibe sonst erst am Ende etwas aus (0.28).
    "claude": {"label": "Claude Code", "bin": "claude", "argv": ["claude", "-p", PROMPT], "provider": "Anthropic",
               "stream_args": ["--output-format", "stream-json", "--verbose"], "stream_flags": ("--output-format",),
               "write_flags": ("--permission-mode", "--dangerously-skip-permissions", "--allowedTools", "--allowed-tools"), "write_hint": "--permission-mode acceptEdits"},
    "codex": {"label": "Codex", "bin": "codex", "argv": ["codex", "exec", PROMPT], "provider": "OpenAI",
              "write_flags": ("--full-auto", "--sandbox", "-s", "--dangerously-bypass-approvals-and-sandbox"), "write_hint": "--full-auto"},
    "vibe": {"label": "Mistral Vibe", "bin": "vibe", "argv": ["vibe", "-p", PROMPT], "provider": "Mistral",
             "stream_args": ["--output", "streaming"], "stream_flags": ("--output",),
             "write_flags": ("--auto-approve", "--yolo"), "write_hint": "--auto-approve"},
    # Lokale Agenten: Aufrufe aus der Dokumentation der CLIs abgeleitet, nicht gegen die echten Programme getestet.
    # Anbieter und Modell je Agent (0.27): Laufen alle Modelle über denselben Proxy, sagt nur der Agent-Eintrag, ob ein Modell lokal ist.
    "goose": {"label": "Goose", "bin": "goose", "argv": ["goose", "run", "-i", PROMPT_FILE], "provider": "dem in Goose eingestellten Anbieter",
              "env": {"GOOSE_PROVIDER": PROVIDER, "GOOSE_MODEL": MODEL}, "local": True},
    "opencode": {"label": "opencode", "bin": "opencode", "argv": ["opencode", "run", "--model", PROVIDER + "/" + MODEL, PROMPT],
                 "provider": "dem in opencode eingestellten Anbieter", "local": True},
    "custom": {"label": "Eigener Befehl", "bin": "", "argv": None, "provider": "dem Anbieter des Befehls", "local": True},
}


# Weiterführen in derselben Sitzung (0.40): der Agent behält den ganzen Kontext. Aufrufe aus der Dokumentation der CLIs.
# own: tinyops vergibt die Kennung beim Start (Claude Code: UUID, Goose: Name); find: die CLI nennt sie im Log;
# last: ohne Kennung die letzte Sitzung im Arbeitsordner. Geprüft gegen die echten Programme ist das noch nicht.
SESSION = "\0SESSION\0"
EXTRA = "\0EXTRA\0"
SESSION_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,99}$")
SESSIONS = {
    "claude": {"own": "uuid", "start": ["--session-id", SESSION], "resume": ["--resume", SESSION]},
    "codex": {"find": r"session id:\s*([0-9a-fA-F][0-9a-fA-F-]{20,60})",
              "resume_argv": ["codex", "exec", EXTRA, "resume", SESSION, PROMPT], "last_argv": ["codex", "exec", EXTRA, "resume", "--last", PROMPT]},
    "vibe": {"find": r'"session_id"\s*:\s*"([A-Za-z0-9_.:-]{6,100})"', "resume": ["--resume", SESSION], "last": ["--continue"]},
    "goose": {"own": "name", "at": 2, "start": ["--name", SESSION], "resume": ["--name", SESSION, "--resume"]},
    "opencode": {"last": ["--continue"]},
}


def can_resume(agent):
    """Kann dieser Agent eine Sitzung fortsetzen? Eigene Befehle nicht: tinyops kennt ihren Aufruf nicht."""
    return (agent or {}).get("kind") in SESSIONS


def new_session(agent, rid):
    """Kennung, die tinyops beim Start selbst vergibt, sonst leer (dann liest tinyops sie nach dem Lauf aus dem Log)."""
    own = SESSIONS.get(agent.get("kind"), {}).get("own")
    return str(uuid.uuid4()) if own == "uuid" else "tinyops-%d" % int(rid) if own == "name" else ""


def find_session(agent, text):
    """Kennung der Sitzung aus dem Log, für Agenten, die sie selbst vergeben (Codex, Vibe)."""
    rx = SESSIONS.get(agent.get("kind"), {}).get("find")
    m = re.search(rx, text or "") if rx else None
    return m.group(1) if m and SESSION_RE.match(m.group(1)) else ""


def git_env(agent):
    """Git-Benutzer je Agent (0.40): Commits des Agenten tragen diesen Namen statt des Kontos auf dem Zielrechner."""
    out = {}
    if agent.get("git_name"):
        out.update(GIT_AUTHOR_NAME=agent["git_name"], GIT_COMMITTER_NAME=agent["git_name"])
    if agent.get("git_email"):
        out.update(GIT_AUTHOR_EMAIL=agent["git_email"], GIT_COMMITTER_EMAIL=agent["git_email"])
    return out


ANSI = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]|\x1b\][^\x07]*\x07")


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
    """Umgebungsvariablen der Art, ohne leere Werte (leerer Anbieter oder leeres Modell: die eigene Konfiguration der CLI gilt), dazu der Git-Benutzer."""
    out = git_env(agent)
    for k, v in (KINDS[agent["kind"]].get("env") or {}).items():
        v = _sub_model(v, agent.get("model", ""), provider_of(agent))
        if v:
            out[k] = v
    return out


def agent_args(agent):
    """Feste Argumente der Art mit Anbieter/Modell. opencode ohne Anbieter: nur der Modellname. Dazu die Streaming-Argumente,
    ausser du setzt das Ausgabeformat selbst in den zusätzlichen Argumenten."""
    spec = KINDS[agent["kind"]]
    out = []
    for a in spec["argv"]:
        if a in (PROMPT, PROMPT_FILE):
            out.append(a)
        else:
            out.append(_sub_model(a, agent.get("model", ""), provider_of(agent)).lstrip("/"))
    if spec.get("stream_args") and not any(x.split("=")[0] in spec["stream_flags"] for x in _extra(agent)):
        out += spec["stream_args"]
    return out


def command_argv(agent, sess=None):
    """Ganze Befehlszeile (ohne Programmpfad aufgelöst) mit Platzhaltern für den Prompt. sess = {"id": …, "resume": bool}:
    beim Start die eigene Kennung mitgeben, beim Weiterführen die Sitzung fortsetzen."""
    ss = SESSIONS.get(agent["kind"]) if sess else None
    extra = _extra(agent)
    sid = (sess or {}).get("id") or ""
    if sid and not SESSION_RE.match(sid):
        raise AgentError("Ungültige Kennung der Agenten-Sitzung.")
    if ss and sess.get("resume") and "resume_argv" in ss:
        out = []
        for a in ss["resume_argv"] if sid else ss["last_argv"]:
            out += extra if a == EXTRA else [sid] if a == SESSION else [a]
        return out
    out = agent_args(agent)
    if ss:
        if sess.get("resume"):
            add = [sid if x == SESSION else x for x in ss["resume"]] if sid and "resume" in ss else list(ss.get("last") or [])
        else:
            add = [sid if x == SESSION else x for x in ss.get("start", [])] if sid else []
        at = ss.get("at")
        out = out[:at] + add + out[at:] if at else out + add
    return out + extra


def _short(v, n=140):
    v = " ".join(str(v if not isinstance(v, (dict, list)) else json.dumps(v, ensure_ascii=False)).split())
    return v if len(v) <= n else v[:n - 1] + "…"


def _tool_line(name, inp):
    inp = inp if isinstance(inp, dict) else {"args": inp}
    for k in ("command", "file_path", "path", "pattern", "url", "query", "description", "prompt"):
        if inp.get(k):
            return "▸ %s: %s" % (name, _short(inp[k], 160))
    if isinstance(inp.get("todos"), list):
        done = sum(1 for t in inp["todos"] if isinstance(t, dict) and t.get("status") == "completed")
        return "▸ %s: %d von %d Punkten erledigt" % (name, done, len(inp["todos"]))
    return "▸ %s %s" % (name, _short(inp, 120) if inp else "")


def _first(v):
    if isinstance(v, list):
        v = " ".join(x.get("text", "") if isinstance(x, dict) else str(x) for x in v)
    lines = [x for x in str(v or "").splitlines() if x.strip()]
    return (_short(lines[0], 120) + (" (+%d Zeilen)" % (len(lines) - 1) if len(lines) > 1 else "")) if lines else ""


def stream_line(obj):
    """Eine JSON-Zeile aus dem Stream von Claude Code oder Vibe in lesbaren Text. None = nicht zeigen."""
    t = obj.get("type")
    if t == "system":
        if obj.get("subtype") == "init":
            return "● gestartet%s" % (" (%s)" % obj["model"] if obj.get("model") else "")
        return ("● %s" % _short(obj.get("subtype") or "")) if obj.get("subtype") in ("api_retry", "compact_boundary") else None
    if t in ("assistant", "user"):
        out = []
        for c in ((obj.get("message") or {}).get("content") or []):
            if not isinstance(c, dict):
                continue
            if c.get("type") == "text" and c.get("text", "").strip():
                out.append(c["text"].strip())
            elif c.get("type") == "tool_use":
                out.append(_tool_line(c.get("name") or "Werkzeug", c.get("input")))
            elif c.get("type") == "tool_result":
                f = _first(c.get("content"))
                if c.get("is_error"):
                    out.append("  ✗ %s" % (f or "Fehler"))
                elif f:
                    out.append("  → %s" % f)
        return "\n".join(out) or None
    if t == "result":
        head = "■ %s nach %s Schritten%s" % ("fertig" if obj.get("subtype") == "success" and not obj.get("is_error") else "abgebrochen (%s)" % obj.get("subtype"),
                                           obj.get("num_turns", "?"), ", %d s" % (obj["duration_ms"] // 1000) if isinstance(obj.get("duration_ms"), int) else "")
        return head + ("\n" + str(obj["result"]).strip() if obj.get("result") else "")
    if t == "stream_event":
        return None
    role = obj.get("role")                      # Vibe (--output streaming): eine Nachricht je Zeile, OpenAI-ähnlich
    if role:
        out = []
        content = obj.get("content")
        if role == "assistant":
            if isinstance(content, str) and content.strip():
                out.append(content.strip())
            for tc in obj.get("tool_calls") or []:
                fn = (tc or {}).get("function") or {}
                args = fn.get("arguments")
                try:
                    args = json.loads(args) if isinstance(args, str) else args
                except ValueError:
                    pass
                out.append(_tool_line(fn.get("name") or "Werkzeug", args))
        elif role == "tool":
            f = _first(content)
            out.append("  → %s" % f if f else "")
        elif role in ("user", "system"):
            return None
        return "\n".join(x for x in out if x) or None
    return _short(obj, 200)


def render_stream(text):
    """Log eines Laufs für die Anzeige: JSON-Zeilen der Agenten lesbar machen, alles andere bleibt."""
    out = []
    for line in (text or "").splitlines():
        s_ = line.strip()
        if s_.startswith("{") and s_.endswith("}"):
            try:
                obj = json.loads(s_)
            except ValueError:
                out.append(line)
                continue
            r = stream_line(obj) if isinstance(obj, dict) else None
            if r:
                out.extend(r.splitlines())
        else:
            out.append(line)
    return "\n".join(out)


def last_reply(text, limit=3000):
    """0.40: Was der Agent am Ende gesagt hat, für das Gespräch im Lauf. Claude Code nennt es im Streaming als «result»,
    sonst die letzten Zeilen der lesbaren Ausgabe."""
    for line in reversed((text or "").splitlines()):
        s_ = line.strip()
        if s_.startswith("{") and '"result"' in s_:
            try:
                obj = json.loads(s_)
            except ValueError:
                continue
            if isinstance(obj, dict) and obj.get("type") == "result" and isinstance(obj.get("result"), str) and obj["result"].strip():
                return clean_text(obj["result"].strip(), limit)
    lines = [ln for ln in clean_text(render_stream(text), 60000).splitlines() if ln.strip()]
    return "\n".join(lines[-12:])[-limit:]


def remote_cmdline(agent, sess=None):
    """Zeile für `<Nr>.cmd` auf dem Zielhost. Der Prompt wird dort aus der Datei gelesen, nicht eingebettet."""
    if agent["kind"] == "custom":
        cmd = agent.get("command")
        if not cmd:
            raise AgentError("Für diesen eigenen Agenten steht kein «command» in der config.json (die Oberfläche kann ihn nicht setzen).")
        env = "".join("export %s=%s; " % (k, shlex.quote(v)) for k, v in git_env(agent).items())
        return env + cmd.replace("{prompt_file}", '"$R/$ID.prompt"')
    parts = ["%s=%s" % (k, shlex.quote(v)) for k, v in agent_env(agent).items()]
    for a in command_argv(agent, sess):
        parts.append('"$(cat "$R/$ID.prompt")"' if a == PROMPT else '"$R/$ID.prompt"' if a == PROMPT_FILE else shlex.quote(a))
    return " ".join(parts)


def local_spec(agent, prompt, prompt_file, workdir, sess=None):
    if agent["kind"] == "custom":
        cmd = agent.get("command")
        if not cmd:
            raise AgentError("Für diesen eigenen Agenten steht kein «command» in der config.json (die Oberfläche kann ihn nicht setzen).")
        pf = subprocess.list2cmdline([str(prompt_file)]) if os.name == "nt" else shlex.quote(str(prompt_file))
        out = {"shell": cmd.replace("{prompt_file}", pf), "cwd": workdir}
        if git_env(agent):
            out["env"] = git_env(agent)
        return out
    spec = KINDS[agent["kind"]]
    exe = shutil.which(spec["bin"])
    if not exe:
        raise AgentError("«%s» wurde im PATH dieses Rechners nicht gefunden." % spec["bin"])
    argv = [exe] + [prompt if a == PROMPT else str(prompt_file) if a == PROMPT_FILE else a for a in command_argv(agent, sess)[1:]]
    out = {"argv": argv, "cwd": workdir}
    if agent_env(agent):
        out["env"] = agent_env(agent)
    return out


def clean_text(s, limit=20000):
    """Ausgabe eines Agenten lesbar und ohne Geheimnisse: keine Farbcodes, bekannte Token-Formen geschwärzt, nur das Ende."""
    s = ANSI.sub("", s or "").replace("\r\n", "\n").replace("\r", "\n")
    s = store.TOKEN_RE.sub("***", store.scrub(s))
    return s[-limit:]
