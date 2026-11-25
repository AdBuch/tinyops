"""Schema der Einstellungen (0.45): Zahlenfelder mit Grenzen, Standard und Hilfe an einer Stelle.

Bis 0.44 stand jede Grenze zweimal (Prüfung in settings.build_config, Standard in settings.view oder im Modul) und die
Fehlertexte waren dreierlei. Jetzt:
- `NUMBERS` nennt je Feld (Schlüssel wie in der Oberfläche, z. B. «sonar.max_items») Minimum, Maximum, Standard und Hilfe.
- `number()` prüft eine Eingabe dagegen, mit einem Fehlertext für alle Felder; `get()` liest den Wert aus der Config.
- `public()` geht mit `/api/settings` an die Oberfläche: `field()` setzt daraus min, max und den Hinweis zum Standard.
Eine neue Zahl in den Einstellungen ist damit eine Zeile hier, ein `number()` in build_config und ein `field()` in settings.js.
Texte, Listen und Abschnitte mit eigenen Regeln (Projekte, Agenten, Fokusbereiche) bleiben in ihren Prüfungen.
"""
import re
from typing import NamedTuple

import agent_rules
import focusplan
import helpdesk
import m365
import timesheet
import voice
import workspaces


class Num(NamedTuple):
    lo: int
    hi: int
    default: int
    help: str = ""


NUMBERS = {
    "branch_filter.max_branches": Num(1, 200, 40, "Je Projekt die neuesten so vielen Branches."),
    "branch_filter.max_age_days": Num(0, 3650, 90),            # «0 = nie» steht im Label
    "jira.story_limit": Num(1, 20, 2, "Mehr in Arbeit zeigt der Fokus als Warnung."),
    "llm.timeout": Num(10, 900, 120, "Sekunden."),
    "usage.cache_seconds": Num(30, 3600, 300, "Sekunden."),
    "sonar.cache_seconds": Num(30, 3600, 300, "Sekunden."),
    "sonar.max_items": Num(1, 200, 40),
    "sonar.report_max": Num(10, 1000, 200),
    "helpdesk.sla_hours": Num(1, 720, helpdesk.DEFAULTS["sla_hours"], "Stunden."),
    "m365.reply_days": Num(1, 14, m365.DEFAULTS["reply_days"], "Tage."),
    "m365.refresh_minutes": Num(1, 60, m365.DEFAULTS["refresh_minutes"], "Minuten."),
    "workspaces.depth": Num(1, 6, workspaces.DEFAULTS["depth"]),
    "workspaces.stale_days": Num(0, 365, workspaces.DEFAULTS["stale_days"], "Tage."),
    "workspaces.scan_minutes": Num(1, 240, workspaces.DEFAULTS["scan_minutes"], "Minuten."),
    "time.round_minutes": Num(1, 60, timesheet.DEFAULTS["round_minutes"], "Minuten."),
    "time.min_minutes": Num(0, 60, timesheet.DEFAULTS["min_minutes"], "Minuten."),
    "time.idle_minutes": Num(3, 240, timesheet.DEFAULTS["idle_minutes"], "Minuten."),
    "focus.week_hours": Num(1, 80, focusplan.DEFAULTS["week_hours"], "Stunden."),
    "ux.days": Num(1, 365, 30, "Tage."),
    "agent_log_days": Num(0, 3650, 30),                         # «0 = nie löschen» steht im Label
    "agent_guards.max_files": Num(1, 200, agent_rules.GUARD_DEFAULTS["max_files"]),
    "agent_guards.max_lines": Num(20, 20000, agent_rules.GUARD_DEFAULTS["max_lines"]),
    "voice.max_seconds": Num(10, 300, voice.DEFAULTS["max_seconds"], "Sekunden."),
    "voice.timeout": Num(5, 300, voice.DEFAULTS["timeout"], "Sekunden."),
    "voice.threads": Num(0, 64, voice.DEFAULTS["threads"], "0 heisst automatisch."),
}


def message(key):
    n = NUMBERS[key]
    return "Ganze Zahl von %d bis %d." % (n.lo, n.hi)


def number(key, raw, errors, keep=None):
    """Prüft eine Zahl. Leer oder fehlend: `keep` (der bisherige Wert), sonst der Standard. Falsch: Fehler unter `key`, Wert bleibt."""
    n = NUMBERS[key]
    fallback = n.default if keep is None else keep
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        return fallback
    try:
        v = int(str(raw).strip()) if isinstance(raw, str) else int(raw)
        if isinstance(raw, float) and raw != v:
            raise ValueError
    except (TypeError, ValueError):
        errors[key] = message(key)
        return fallback
    if not n.lo <= v <= n.hi:
        errors[key] = message(key)
        return fallback
    return v


def get(cfg, key):
    """Wert aus der Config (verschachtelt nach den Punkten im Schlüssel), sonst der Standard."""
    cur = cfg
    for part in key.split("."):
        cur = cur.get(part) if isinstance(cur, dict) else None
    return NUMBERS[key].default if cur is None else cur


def public():
    return {k: {"min": n.lo, "max": n.hi, "default": n.default, "help": n.help} for k, n in NUMBERS.items()}


def lst(v, what, errors, limit=60, upper=False):
    out = []
    if v is None:
        return out
    if isinstance(v, str):
        v = [x for x in re.split(r"[,\n]", v)]
    for x in v:
        x = str(x).strip()
        if not x:
            continue
        if len(x) > 200:
            errors[what] = "Eintrag zu lang."
            continue
        out.append(x.upper() if upper else x)
    if len(out) > limit:
        errors[what] = "Zu viele Einträge (höchstens %d)." % limit
    return out


def int_(v, what, lo, hi, errors, default):
    """Zahl ausserhalb des Schemas (z. B. je Fokusbereich), mit demselben Fehlertext."""
    if v in (None, ""):
        return default
    try:
        n = int(v)
    except (TypeError, ValueError):
        errors[what] = "Ganze Zahl von %d bis %d." % (lo, hi)
        return default
    if not lo <= n <= hi:
        errors[what] = "Ganze Zahl von %d bis %d." % (lo, hi)
        return default
    return n
