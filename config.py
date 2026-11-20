"""Config von tinyops (0.38 aus server.py gelöst): Standardwerte, Laden, Umgebungsvariablen, Teil-Configs je Anbindung.
Wo die Config liegt (Programmordner, Datenordner), bleibt in server.py."""
import json
import os

import github
import timesheet

DEFAULTS = {
    "gitlab_url": "",
    "token_env": "GITLAB_TOKEN",
    "ca_bundle": "",
    "my_emails": [],
    "branch_filter": {},
    "features": {"ideas": True, "ai": False, "score": True},   # score (0.35, E3): Spielstand, abschaltbar
    "data_dir": "",               # leer = ./data (Ideenbox)
    "log_level": "info",          # debug zeigt jede Anfrage und jede Branch-Entscheidung
    "log_dir": "",                # leer = ~/.config/tinyops/logs
    "log_max_mb": 2,
    "log_backups": 5,
    "projects": [],
    "wip_limit": 2,
    "stale_days": 7,
    "cache_seconds": 300,      # GitLab/Jira höchstens alle 5 Minuten abgleichen; «Neu laden» erzwingt es
    "bind": "127.0.0.1",
    "port": 8765,
    "allowed_hosts": [],
    "app": {"phone_url": ""},     # 0.36: Adresse, unter der das Handy tinyops erreicht (z. B. Tailscale)
    "connections": [],     # SSH-Ziele für Coding-Agenten (Einstellungen → Agenten)
    "agents": [],
    "ux": {"enabled": True, "days": 30},   # UI-Nutzung lokal erfassen (0.22), für die Optimierung der Oberfläche
    "agent_log_days": 30,      # Logs, Prompts und Patches der Agentenläufe nach so vielen Tagen löschen (0 = nie)
    "idea_cap": 25,
    "idea_expire_days": 30,
    "jira": {},
    "llm": {},
    "secrets": {},
}

LLM_DEFAULTS = {
    "enabled": False,
    "provider": "ollama",          # ollama oder openai (llama.cpp, LM Studio, vLLM ...), siehe llm.py
    "url": "http://127.0.0.1:11434",
    "model": "",
    "timeout": 120,                # Sekunden ohne ein Byte Antwort, bis abgebrochen wird (grosse Modelle laden beim ersten Aufruf lange)
    "allow_remote": False,         # nur das eigene Netz, solange das nicht ausdrücklich an ist (DLP)
}

USAGE_DEFAULTS = {
    "claude": False,           # Rest des Claude-Abos lesen (inoffizielle Schnittstelle, Token aus der Anmeldedatei des CLI)
    "codex": False,            # dasselbe für Codex
    "mistral": False,          # Mistral: Stand kommt per Lesezeichen aus dem Browser (kein Zugriff auf die Sitzung)
    "claude_file": "",         # leer = ~/.claude/.credentials.json
    "codex_file": "",          # leer = ~/.codex/auth.json
    "cache_seconds": 300,
}

SONAR_DEFAULTS = {
    "enabled": False,
    "url": "",
    "cache_seconds": 300,      # ein Quality Gate ändert sich nur nach einer neuen Analyse: nicht bei jedem Abgleich neu fragen
    "max_items": 40,           # höchstens so viele MRs/Branches pro Abgleich prüfen (eigene zuerst)
    "report_max": 200,         # höchstens so viele Findings im Report für die Zwischenablage (nach Schwere sortiert)
}

JIRA_DEFAULTS = {
    "url": "",
    "auth": "bearer",          # bearer = Personal Access Token, basic = Benutzername + Passwort
    "username": "",
    "project_keys": [],
    "story_limit": 2,
    "wip_issue_types": [],
    "group_link_types": [],        # 0.30: welche Issue-Links Tickets zu einem Task gruppieren; leer = jeder Link zwischen Tickets in Arbeit
    "only_active_sprints": True,   # nur Tickets aus aktiven Sprints (Jira Software, JQL sprint in openSprints())
    "jql_in_progress": 'assignee = currentUser() AND statusCategory = "In Progress" ORDER BY updated DESC',
    "allow_create": False,         # Tickets aus dem Panel anlegen (Schreibzugriff auf Jira!). Aus, bis du es einschaltest.
    "create_type": "Story",        # Vorgangstyp, der im Dialog vorgewählt ist
    "create_pid": "",
    "create_issuetype": "",
    "helpdesk": {},
}

PLAIN_SECRET_KEYS = {"token", "password", "access_token", "gitlab_token", "jira_token",
                     "jira_password", "api_key", "apikey", "secret"}


# ---------------------------------------------------------------- helpers
def reject_plain_secrets(cfg):
    for scope, d in (("config.json", cfg), ("jira", cfg.get("jira") or {})):
        for k, v in d.items():
            if k.lower() in PLAIN_SECRET_KEYS and isinstance(v, str) and v.strip():
                raise SystemExit(
                    "%s enthält ein Secret im Feld '%s'. Entferne es dort und speichere es sicher mit:\n"
                    "  python3 server.py --set-secret <name>   (gitlab_token, jira_token, jira_password, access_token)"
                    % (scope, k))


def load_config(path):
    cfg = dict(DEFAULTS)
    if path:
        with open(path, encoding="utf-8") as f:
            cfg.update(json.load(f))
    reject_plain_secrets(cfg)
    apply_env(cfg)
    return cfg


def apply_env(cfg, env=None):
    """Für Container: Adresse, Port und erlaubte Hosts per Umgebungsvariable, ohne die config.json anzufassen."""
    env = os.environ if env is None else env
    if (env.get("TINYOPS_BIND") or "").strip():
        cfg["bind"] = env["TINYOPS_BIND"].strip()
    if (env.get("TINYOPS_PORT") or "").strip():
        try:
            port = int(env["TINYOPS_PORT"])
            if not 1 <= port <= 65535:
                raise ValueError
        except ValueError:
            raise SystemExit("TINYOPS_PORT muss eine Zahl zwischen 1 und 65535 sein.")
        cfg["port"] = port
    if (env.get("TINYOPS_ALLOWED_HOSTS") or "").strip():
        cfg["allowed_hosts"] = [h.strip() for h in env["TINYOPS_ALLOWED_HOSTS"].split(",") if h.strip()]


def jira_cfg(cfg):
    j = dict(JIRA_DEFAULTS)
    j.update(cfg.get("jira") or {})
    return j


def usage_cfg(cfg):
    c = dict(USAGE_DEFAULTS)
    c.update(cfg.get("usage") or {})
    return c


GITHUB_DEFAULTS = {"enabled": False, "api_url": github.API_DEFAULT, "repos": []}


TIME_DEFAULTS = timesheet.DEFAULTS


def time_cfg(cfg):
    c = dict(TIME_DEFAULTS)
    c.update(cfg.get("time") or {})
    return c


def github_cfg(cfg):
    c = dict(GITHUB_DEFAULTS)
    c.update(cfg.get("github") or {})
    return c


def sonar_cfg(cfg):
    c = dict(SONAR_DEFAULTS)
    c.update(cfg.get("sonar") or {})
    return c


def llm_cfg(cfg):
    c = dict(LLM_DEFAULTS)
    c.update(cfg.get("llm") or {})
    return c


def feature(cfg, name):
    """Fehlt ein Schalter in der Config (z. B. «score» in einer Config von vor 0.35), gilt der Standard, nicht «aus»."""
    return bool((cfg.get("features") or {}).get(name, DEFAULTS["features"].get(name, False)))


# ---------------------------------------------------------------- Jobs
