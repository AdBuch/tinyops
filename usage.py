"""Rest-Kontingent der KI-Abos (nur lesen).

Claude und Codex haben keinen dokumentierten Endpunkt dafür. Beide CLIs benutzen aber einen, und genau den fragen wir hier ab:

* Claude: GET https://api.anthropic.com/api/oauth/usage   (Token aus ~/.claude/.credentials.json)
* Codex:  GET https://chatgpt.com/backend-api/wham/usage  (Token aus ~/.codex/auth.json)

Das sind inoffizielle Schnittstellen und können sich ohne Ankündigung ändern. Deshalb gilt: jeder Fehler wird zu «nicht abrufbar» mit Grund,
nie zu einer erfundenen Zahl. Das Token wird nur gelesen (nie erneuert, nie gespeichert, nie geloggt) und nur an den festen Host geschickt.
Mistral Vibe hat keinen solchen Endpunkt und kommt hier nicht vor.
"""
import json
import os
import ssl
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

CLAUDE_URL = "https://api.anthropic.com/api/oauth/usage"
CODEX_URL = "https://chatgpt.com/backend-api/wham/usage"
DEFAULT_FILES = {"claude": "~/.claude/.credentials.json", "codex": "~/.codex/auth.json"}
NAMES = {"claude": "Claude", "codex": "Codex (ChatGPT)"}
LOGIN_HINT = {"claude": "Einmal `claude` im Terminal starten (erneuert die Anmeldung).",
              "codex": "Einmal `codex` im Terminal starten (erneuert die Anmeldung)."}


class UsageError(Exception):
    pass


def _url(kind):
    # Nur für Tests: ein Fake-Server statt des echten Hosts
    return os.environ.get("TINYOPS_USAGE_%s_URL" % kind.upper()) or (CLAUDE_URL if kind == "claude" else CODEX_URL)


def _read_json(path):
    p = Path(os.path.expanduser(path))
    if not p.is_file():
        raise UsageError("Anmeldedatei nicht gefunden (%s). Im Container: Datei als Volume einhängen." % path)
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise UsageError("Anmeldedatei nicht lesbar (%s)." % path)


def claude_token(path):
    d = _read_json(path)
    o = d.get("claudeAiOauth") if isinstance(d.get("claudeAiOauth"), dict) else d
    tok = o.get("accessToken") or o.get("access_token")
    if not tok:
        raise UsageError("Kein Zugangstoken in %s. %s" % (path, LOGIN_HINT["claude"]))
    exp = o.get("expiresAt") or o.get("expires_at")
    if isinstance(exp, (int, float)) and exp > 0:
        if exp > 1e12:
            exp /= 1000.0
        if exp < time.time():
            raise UsageError("Anmeldung abgelaufen. " + LOGIN_HINT["claude"])
    return tok, {}


def codex_token(path):
    d = _read_json(path)
    t = d.get("tokens") if isinstance(d.get("tokens"), dict) else {}
    tok = t.get("access_token")
    if not tok:
        raise UsageError("Kein Login-Token in %s (nur ein API-Schlüssel reicht nicht, es braucht die ChatGPT-Anmeldung). %s" % (path, LOGIN_HINT["codex"]))
    extra = {"ChatGPT-Account-ID": t["account_id"]} if t.get("account_id") else {}
    return tok, extra


def _get(url, headers, ctx, timeout):
    req = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as r:
            return json.loads(r.read(1 << 20).decode("utf-8", "replace"))
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            raise UsageError("Zugriff abgelehnt (HTTP %d). Anmeldung abgelaufen oder die Schnittstelle erlaubt das nicht mehr." % e.code)
        if e.code == 404:
            raise UsageError("Schnittstelle nicht gefunden (HTTP 404). Der Anbieter hat sie wohl geändert.")
        raise UsageError("Anbieter antwortet mit HTTP %d." % e.code)
    except (urllib.error.URLError, OSError, TimeoutError) as e:
        raise UsageError("Anbieter nicht erreichbar (%s)." % getattr(e, "reason", e))
    except ValueError:
        raise UsageError("Antwort ist kein JSON. Die Schnittstelle hat sich wohl geändert.")


def _epoch(v):
    """ISO-Zeit, Sekunden oder Millisekunden → Epoche (oder None)."""
    if v in (None, ""):
        return None
    if isinstance(v, (int, float)):
        return float(v) / 1000.0 if v > 1e12 else float(v)
    try:
        return datetime.fromisoformat(str(v).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def _win(label, pct, reset, now):
    try:
        pct = max(0.0, min(100.0, float(pct)))
    except (TypeError, ValueError):
        return None
    r = _epoch(reset)
    return {"label": label, "used_pct": round(pct, 1), "left_pct": round(100 - pct, 1), "resets_at": r,
            "secs_left": max(0, int(r - now)) if r else None}


def parse_claude(d, now=None):
    now = now or time.time()
    out = []
    for key, label in (("five_hour", "5 h"), ("seven_day", "Woche"), ("seven_day_opus", "Woche Opus")):
        w = d.get(key) if isinstance(d, dict) else None
        if isinstance(w, dict) and w.get("utilization") is not None:
            x = _win(label, w["utilization"], w.get("resets_at"), now)
            if x:
                out.append(x)
    return out


def parse_codex(d, now=None):
    now = now or time.time()
    rl = (d.get("rate_limit") if isinstance(d, dict) else None) or {}
    out = []
    for key in ("primary_window", "secondary_window"):
        w = rl.get(key)
        if not isinstance(w, dict):
            continue
        secs = w.get("limit_window_seconds") or w.get("limitWindowSeconds")
        pct = w.get("used_percent", w.get("usedPercent"))
        reset = w.get("reset_at") or w.get("resetAt") or w.get("resets_at")
        if not reset and w.get("reset_after_seconds") is not None:
            reset = now + float(w["reset_after_seconds"])
        label = {300 * 60: "5 h", 7 * 24 * 3600: "Woche"}.get(int(secs or 0)) or ("5 h" if key == "primary_window" else "Woche")
        x = _win(label, pct, reset, now)
        if x:
            out.append(x)
    return out


def fetch(kind, path=None, ctx=None, timeout=10):
    """Ein Anbieter. Liefert immer ein Dict: ok, windows oder error. Wirft nie."""
    path = path or DEFAULT_FILES[kind]
    res = {"id": kind, "name": NAMES[kind], "ok": False, "error": "", "windows": [], "fetched": time.time()}
    try:
        if kind == "claude":
            tok, extra = claude_token(path)
            hdr = {"Authorization": "Bearer " + tok, "anthropic-beta": "oauth-2025-04-20", "Accept": "application/json", "User-Agent": "tinyops"}
            wins = parse_claude(_get(_url(kind), hdr, ctx, timeout))
        else:
            tok, extra = codex_token(path)
            hdr = {"Authorization": "Bearer " + tok, "User-Agent": "codex-cli", "OAI-Product-Sku": "codex", "Accept": "application/json"}
            hdr.update(extra)
            wins = parse_codex(_get(_url(kind), hdr, ctx, timeout))
        if not wins:
            raise UsageError("Die Antwort enthält keine Fenster (Konto ohne Limit oder Format geändert).")
        res.update(ok=True, windows=wins)
    except UsageError as e:
        res["error"] = str(e).replace(tok, "***") if "tok" in locals() and tok else str(e)
    return res
