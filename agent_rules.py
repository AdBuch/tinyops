"""Regeln und Konfiguration der Agenten: Namen, Verbindungen, Rollen, Datenklassen, Phasen, Leitplanken, Auswertung von Diffs.

0.40 aus agents.py gelöst; agents.py gibt alle Namen weiter."""
import json
import re

ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,30}$")


HOST_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,251}$")


USER_RE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9._-]{0,63}$")


EXTRA_RE = re.compile(r"^[A-Za-z0-9_@%+=:,./ \-]{0,200}$")      # keine Anführungszeichen, kein ; | & $ ` < > und kein Zeilenumbruch


DIR_RE = re.compile(r"^[A-Za-z0-9._][A-Za-z0-9._/-]{0,198}$")


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


# 0.36: Rollen je Phase als Befehl, mit dem der Prompt beginnt (z. B. eigene Slash-Befehle /planner auf dem Agenten-Rechner)
ROLE_PHASES = ("plan", "develop", "review", "test")


ROLE_DEFAULTS = {"plan": "/planner", "develop": "/developer", "review": "/reviewer", "test": "/tester"}


ROLE_CMD_RE = re.compile(r"^/[A-Za-z0-9][A-Za-z0-9:_-]{0,39}$")


QUOTAS = ("claude", "codex", "mistral")


QUOTA_DEFAULT = {"claude": "claude", "codex": "codex", "vibe": "mistral"}


def parse_roles(raw):
    """«plan=/planner, develop=/developer» oder {"plan": "/planner"} → ({phase: befehl}, fehler)."""
    if isinstance(raw, dict):
        items = list(raw.items())
    else:
        items = [x.split("=", 1) if "=" in x else (x, "") for x in re.split(r"[,\s]+", str(raw or "").strip()) if x]
    out = {}
    for k, v in items:
        k, v = str(k).strip().lower(), str(v).strip()
        k = {"planner": "plan", "developer": "develop", "reviewer": "review", "tester": "test"}.get(k, k)
        if k not in ROLE_PHASES:
            return {}, "Rollen: plan, develop, review, test (z. B. plan=/planner)."
        v = v or ROLE_DEFAULTS[k]
        if not ROLE_CMD_RE.fullmatch(v):
            return {}, "Befehl je Rolle wie /planner: Schrägstrich, dann Buchstaben, Ziffern, - _ :"
        out[k] = v
    return out, ""


def agent_roles(a):
    """Für welche Phasen ein Agent da ist. Ohne Angabe: alle."""
    return [p for p in ROLE_PHASES if p in (a.get("roles") or {})] or list(ROLE_PHASES)


STATUS_ACTIVE = ("läuft",)


STATUS_ALL = ("zugewiesen", "läuft", "fertig", "fehlgeschlagen", "abgebrochen", "verloren", "abgelaufen")


DEFAULT_MAX_MINUTES = 60


MAX_PROMPT = 20000


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


GIT_NAME_RE = re.compile(r"^[\w][\w .()-]{0,79}$")
GIT_MAIL_RE = re.compile(r"^[A-Za-z0-9._%+-]{1,64}@[A-Za-z0-9.-]{1,120}\.[A-Za-z]{2,24}$")


def clean_agents(raw, conn_ids, existing, errors):
    """`existing`: bisherige Agenten aus der config.json. Den Befehl von «custom» übernimmt nur sie, nie die Oberfläche."""
    from agent_cmd import KINDS     # hier, weil agent_cmd dieses Modul braucht
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
        roles, err = parse_roles(a.get("roles"))
        if err:
            errors[k + "roles"] = err
        if roles:
            entry["roles"] = roles
        if a.get("push"):
            entry["push"] = True            # 0.36: pusht am Ende seinen Lauf-Branch (sonst nie)
        gname, gmail = " ".join(str(a.get("git_name") or "").split())[:80], str(a.get("git_email") or "").strip()[:120]
        if gname and not GIT_NAME_RE.fullmatch(gname):            # 0.40: Git-Benutzer je Agent
            errors[k + "git_name"] = "Git-Name: Buchstaben, Ziffern, Leerzeichen und . - _ ( ), höchstens 80 Zeichen."
        elif gname:
            entry["git_name"] = gname
        if gmail and not GIT_MAIL_RE.fullmatch(gmail):
            errors[k + "git_email"] = "Git-E-Mail: eine Adresse wie agent@example.org."
        elif gmail:
            entry["git_email"] = gmail
        q = str(a.get("quota") if a.get("quota") is not None else QUOTA_DEFAULT.get(kind, "")).strip().lower()
        if q and q not in QUOTAS + ("none",):
            errors[k + "quota"] = "Kontingent: claude, codex, mistral oder leer."
        entry["quota"] = q if q in QUOTAS else ""
        cmd = (old.get(aid) or {}).get("command")
        if kind == "custom" and cmd:
            entry["command"] = str(cmd)
        out.append(entry)
    return out


CLONE_URL_RE = re.compile(r"^(?:https://[A-Za-z0-9.-]+(?::\d+)?/|ssh://(?:[A-Za-z0-9._-]+@)?[A-Za-z0-9.-]+(?::\d+)?/|[A-Za-z0-9._-]+@[A-Za-z0-9.-]+:)[A-Za-z0-9._~/+-]+$")


# -- Zyklus (0.31): Planen → Umsetzen → Review → Test, jede Phase endet mit deiner Freigabe
PHASES = ("plan", "develop", "review", "test")


PHASE_LABEL = {"plan": "Planen", "develop": "Entwickeln", "review": "Review", "test": "Test"}      # 0.40: «Umsetzen» heisst «Entwickeln», wie die Rolle


PHASE_TEMPLATE = {"plan": "agent-plan", "develop": "agent-task", "review": "agent-prereview", "test": "agent-test"}


GATES = ("ok", "back")


GUARD_DEFAULTS = {"max_files": 8, "max_lines": 300, "extra": ""}


def guards_cfg(cfg):
    g = dict(GUARD_DEFAULTS)
    g.update(cfg.get("agent_guards") or {})
    return g


def guards_text(g, phase="develop"):
    """Leitplanken für jeden Prompt: eine gute, aber einfache Änderung, die sich leicht reviewen lässt."""
    lines = ["## Leitplanken",
             "- **Klein halten:** höchstens %d Dateien und etwa %d geänderte Zeilen. Wird es mehr, hör auf und schlag mit `tinyops-ask` eine Aufteilung vor." % (g["max_files"], g["max_lines"]),
             "- **Nur, was die Aufgabe verlangt:** kein Umbau nebenbei, keine Formatierung fremder Zeilen, keine neuen Abhängigkeiten ohne Rückfrage.",
             "- **Einfach vor clever:** bestehende Muster und den Stil des Projekts übernehmen; Namen, die erklären, was passiert.",
             "- **Jede Verhaltensänderung bekommt einen Test**, ausgeführt mit `tinyops-check`.",
             "- **Kleine Commits** mit einer Absicht je Commit und einer Nachricht, die sie nennt.",
             "- **Begründen im Bericht, nicht im Code:** Jede geänderte Datei bekommt im Bericht eine Zeile «Datei – was – warum». Keine Kommentare, die nur dem Review dienen, keine auskommentierten Zeilen, keine TODOs ohne Ticket. Kommentare im Code nur, wo sie auch in einem Jahr noch helfen.",
             "- **Für das Review schreiben:** Im Bericht zuerst, was ein Reviewer ansehen soll, und was du bewusst nicht gemacht hast."]
    if phase in ("plan", "review"):
        lines[1:3] = ["- **Nichts ändern:** In dieser Phase liest du nur. Keine Dateien bearbeiten, nichts committen.",
                      "- **Am Ziel messen:** Eine gute Änderung bleibt unter %d Dateien und etwa %d Zeilen. Ist mehr nötig, schlag eine Aufteilung vor." % (g["max_files"], g["max_lines"])]
    extra = " ".join(str(g.get("extra") or "").split())[:600]
    if extra:
        lines.append("- **Im Team vereinbart:** " + extra)
    return "\n".join(lines) + "\n"


def guard_warnings(result, g):
    """Was am Ergebnis über die Leitplanken geht. Nur Hinweise: entscheiden tust du."""
    if not result:
        return []
    out = []
    files = len(result.get("files") or [])
    m = re.search(r"(\d+) insertion", result.get("stat") or "")
    d = re.search(r"(\d+) deletion", result.get("stat") or "")
    lines = (int(m.group(1)) if m else 0) + (int(d.group(1)) if d else 0)
    if files > g["max_files"]:
        out.append("%d Datei%s geändert, Ziel höchstens %d. Lässt es sich aufteilen?" % (files, "" if files == 1 else "en", g["max_files"]))
    if lines > g["max_lines"]:
        out.append("%d Zeilen geändert, Ziel etwa %d. Gross für ein gründliches Review." % (lines, g["max_lines"]))
    if result.get("dirty"):
        out.append("%d Datei%s nicht committet." % (result["dirty"], "" if result["dirty"] == 1 else "en"))
    nc = sum(f.get("comments") or 0 for f in result.get("files") or [] if isinstance(f, dict))
    if nc >= COMMENT_WARN:
        out.append("%d neue Kommentarzeilen im Code. Begründungen gehören in den Bericht. Bleiben sollten nur Kommentare, die in einem Jahr noch helfen." % nc)
    return out


COMMENT_WARN = 5


CODE_EXT = {"py", "java", "kt", "kts", "js", "mjs", "ts", "tsx", "jsx", "go", "rb", "sh", "bash", "c", "h", "cc", "cpp", "hpp", "cs", "php", "scala",
            "rs", "sql", "yml", "yaml", "xml", "html", "vue", "svelte", "groovy", "gradle", "swift", "tf", "properties", "toml", "ini", "dockerfile"}


_COMMENT = re.compile(r"^\s*(//|/\*|\*(\s|/|$)|#(?![!\[{]|include|define|if|endif|region|pragma)|<!--|--\s|;\s)")


def diff_counts(diff_lines):
    """Je Datei: hinzugefügte und entfernte Zeilen, dazu neue Kommentarzeilen (nur in Code-Dateien). Aus `git diff -U0`."""
    out, cur = {}, None
    for ln in diff_lines:
        if ln.startswith("+++ "):
            p = ln[4:].strip()
            cur = out.setdefault(p[2:] if p.startswith("b/") else p, {"add": 0, "del": 0, "comments": 0}) if p != "/dev/null" else None
            continue
        if ln.startswith("--- ") or ln.startswith("diff --git") or cur is None:
            if ln.startswith("diff --git"):
                m = re.search(r" b/(.+)$", ln)
                cur = out.setdefault(m.group(1), {"add": 0, "del": 0, "comments": 0}) if m else None
            continue
        if ln.startswith("+"):
            cur["add"] += 1
            path = next((k for k, v in out.items() if v is cur), "")
            ext = path.rsplit("/", 1)[-1].lower()
            ext = "dockerfile" if ext.startswith("dockerfile") else ext.rsplit(".", 1)[-1] if "." in ext else ""
            if ext in CODE_EXT and _COMMENT.match(ln[1:]):
                cur["comments"] += 1
        elif ln.startswith("-"):
            cur["del"] += 1
    return out


SEVERITIES = ("hoch", "mittel", "klein")


def parse_findings(text):
    """0.42: Befunde aus <nr>.findings (eine JSON-Zeile je tinyops-finding). Pfad ohne ../ und ohne führenden Schrägstrich."""
    out = []
    for line in (text or "").splitlines()[-100:]:
        try:
            d = json.loads(line)
            n = int(d.get("line") or 0)
        except (ValueError, TypeError, AttributeError):
            continue
        path = str(d.get("path") or "").strip()
        while path.startswith(("./", "/")):
            path = path[2:] if path.startswith("./") else path[1:]
        text_ = " ".join(str(d.get("text") or "").split())[:2000]
        if not path or not text_ or ".." in path.split("/") or n < 0:
            continue
        sev = d.get("severity") if d.get("severity") in SEVERITIES else "mittel"
        out.append({"path": path[:300], "line": n, "text": text_, "severity": sev})
    return out


def parse_manual(text):
    out = []
    for line in (text or "").splitlines()[-30:]:
        try:
            d = json.loads(line)
        except ValueError:
            continue
        st = " ".join(str(d.get("step") or "").split())[:300]
        if st:
            out.append({"step": st, "expect": " ".join(str(d.get("expect") or "").split())[:300]})
    return out[:20]


def review_items(v):
    """Deine Prüfpunkte für ein manuelles Review des Ergebnisses: fest, plus je Akzeptanzkriterium."""
    items = [{"kind": "review", "step": "Diff ganz gelesen", "expect": "Jede geänderte Zeile verstanden; nichts ausserhalb der Aufgabe"},
             {"kind": "review", "step": "Umfang passt", "expect": "Klein genug, sonst aufteilen lassen (Nachbessern)"},
             {"kind": "review", "step": "Tests passen zur Änderung", "expect": "Neue oder geänderte Logik ist durch Tests abgedeckt, Belege grün"}]
    items += [{"kind": "review", "step": "AK%d: %s" % (c["n"], c["text"]), "expect": "im Code erfüllt"} for c in v.get("criteria") or []]
    return items


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
