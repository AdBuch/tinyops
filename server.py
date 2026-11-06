#!/usr/bin/env python3
"""tinyops 1.5: kleines lokales Arbeitspanel (nur Python-Standardbibliothek).

Zeigt deine Branches/MRs mit Pipeline-Status, verknüpft sie mit Jira-Tickets, überwacht
das Story-Limit, die Review-Queue, dir zugeteilte MRs und eine Helpdesk-Zahl. Dazu eine
Ideenbox und Testumgebungen im Cluster. Kein Approve, kein Merge, kein Push.
Zugangsdaten liegen im Secret-Speicher (siehe secretstore.py), nie in der config.json.
"""
import argparse
import base64
import hashlib
import hmac
import http.client
import json
import os
import re
import shlex
import sqlite3
import ssl
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import agents
import audit
import qa
import review
import timesheet
import fnmatch
import flow
import github
import links
import llm
import sonar
import usage
import net
import secretstore as store
import settings
import sprint
import tlog
from net import NoRedirect  # noqa: F401  (Wiederverwendung in Tests)
from secretstore import scrub

VERSION = "0.20.0"   # Semantic Versioning: neue Funktion = minor, Korrektur = patch. Bei jeder Änderung auch CHANGELOG.md pflegen (ein Test prüft das)
BASE = Path(__file__).resolve().parent


def default_config_path():
    """Config, Ideen und Log liegen beim Nutzer (~/.config/tinyops), nicht im Projektordner:
    So überlebt alles ein neues Auspacken, ein git pull oder einen frischen Klon."""
    return store.home_dir() / "config.json"


def migrate_legacy(config_path):
    """Übernimmt eine alte config.json (und Ideen-DB) aus dem Projektordner, wenn am neuen Ort noch nichts liegt.
    Gibt Hinweistexte zurück. Die alten Dateien bleiben unangetastet."""
    import shutil
    notes = []
    config_path = Path(config_path)
    old = BASE / "config.json"
    if not config_path.exists() and old.is_file() and old.resolve() != config_path.resolve():
        config_path.parent.mkdir(parents=True, exist_ok=True)
        os.chmod(config_path.parent, 0o700)
        shutil.copy2(old, config_path)
        os.chmod(config_path, 0o600)
        notes.append("config.json aus dem Projektordner nach %s übernommen (die alte Datei kannst du löschen)." % config_path)
    return notes


def data_dir(cfg):
    d = Path(cfg["data_dir"]).expanduser() if cfg.get("data_dir") else store.home_dir() / "data"
    old = BASE / "data" / "tinyops.db"
    if not cfg.get("data_dir") and not (d / "tinyops.db").exists() and old.is_file():
        import shutil
        d.mkdir(parents=True, exist_ok=True)
        shutil.copy2(old, d / "tinyops.db")
        log.info("Ideen-Datenbank aus %s nach %s übernommen", old, d)
    return d
log = tlog.get("app")
hlog = tlog.get("http")
glog = tlog.get("gitlab")
jlog = tlog.get("jira")
slog = tlog.get("sonar")
slog_u = tlog.get("usage")
rlog = tlog.get("refresh")
joblog = tlog.get("job")
alog = tlog.get("access")
LOOPBACK = ("127.0.0.1", "localhost", "::1")

DEFAULTS = {
    "gitlab_url": "",
    "token_env": "GITLAB_TOKEN",
    "ca_bundle": "",
    "my_emails": [],
    "branch_filter": {},
    "features": {"ideas": True, "testenv": False, "ai": False},   # Testumgebung vorerst ausgeblendet (Einstellungen → Weitere Funktionen)
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
    "kube_context": "",
    "namespace_prefix": "test",
    "job_timeout": 900,
    "deploy_command": [
        "helm", "upgrade", "--install", "{release}", "{chart}",
        "--namespace", "{namespace}", "--create-namespace",
        "--kube-context", "{context}",
        "--set", "image.tag={tag}", "--wait", "--timeout", "5m",
    ],
    "teardown_command": [
        "kubectl", "--context", "{context}", "delete", "namespace",
        "{namespace}", "--wait=false",
    ],
    "agent_command": [],
    "connections": [],     # SSH-Ziele für Coding-Agenten (Einstellungen → Agenten)
    "agents": [],
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
    "only_active_sprints": True,   # nur Tickets aus aktiven Sprints (Jira Software, JQL sprint in openSprints())
    "jql_in_progress": 'assignee = currentUser() AND statusCategory = "In Progress" ORDER BY updated DESC',
    "allow_create": False,         # Tickets aus dem Panel anlegen (Schreibzugriff auf Jira!). Aus, bis du es einschaltest.
    "create_type": "Story",        # Vorgangstyp, der im Dialog vorgewählt ist
    "create_pid": "",
    "create_issuetype": "",
    "helpdesk": {},
}

BRANCH_DEFAULTS = {
    "emails": [],                 # weitere E-Mail-Adressen, unter denen DU committest
    "names": [],                  # weitere Autorennamen von dir
    "agent_emails": [],           # eigene Identität deines Agenten, falls er unter anderem Konto committet
    "agent_names": [],
    "agent_message_patterns": ["Co-Authored-By: Claude", "Claude-Session"],   # nur zum Beschriften
    "max_branches": 40,           # so viele Branches pro Projekt werden verglichen (neueste zuerst)
    "max_age_days": 90,           # ältere Branches werden ignoriert, 0 = kein Limit
    "ignore_branches": ["release/*"],   # Muster (* = beliebig): gilt für Branches ohne MR und für eigene MRs
}

PLAIN_SECRET_KEYS = {"token", "password", "access_token", "gitlab_token", "jira_token",
                     "jira_password", "api_key", "apikey", "secret"}


# ---------------------------------------------------------------- helpers
class UserError(Exception):
    data = None         # optional: weitere Felder für die Antwort (z. B. duplicate)


class HttpStatus(UserError):
    def __init__(self, msg, code):
        super().__init__(msg)
        self.code = code


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


def branch_cfg(cfg):
    b = dict(BRANCH_DEFAULTS)
    b.update(cfg.get("branch_filter") or {})
    return b


def ignored_branch(name, patterns):
    """Passt der Branch auf eines der Muster (zum Beispiel release/*)? Groß-/Kleinschreibung zählt."""
    return any(fnmatch.fnmatchcase(name, p) for p in patterns if p)


def slug(text, limit=30):
    s = re.sub(r"[^a-z0-9]+", "-", str(text).lower()).strip("-")[:limit].strip("-")
    return s or "x"


def parse_ts(iso):
    if not iso:
        return None
    s = str(iso).replace("Z", "+00:00")
    s = re.sub(r"([+-]\d\d)(\d\d)$", r"\1:\2", s)   # Jira liefert +0200 statt +02:00
    try:
        return datetime.fromisoformat(s)
    except ValueError:
        return None


def _delta_seconds(iso):
    ts = parse_ts(iso)
    if ts is None:
        return 0.0
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return max(0.0, (datetime.now(timezone.utc) - ts).total_seconds())


def age_days(iso):
    return int(_delta_seconds(iso) // 86400)


def hours_since(iso):
    return _delta_seconds(iso) / 3600.0


def _age_key(iso):
    """Sortierschlüssel: neueste zuerst, unbekannte Daten ans Ende."""
    return _delta_seconds(iso) if parse_ts(iso) else 1e12


def render(template, values):
    """Ersetzt nur bekannte {name}-Platzhalter, Klammern im Rest bleiben."""
    return re.sub(r"\{(\w+)\}", lambda m: str(values.get(m.group(1), m.group(0))), template)


KEY_RE = re.compile(r"(?<![A-Za-z0-9])([A-Za-z][A-Za-z0-9]{1,9}-\d{1,7})(?![A-Za-z0-9])")
DENY_PREFIXES = {"UTF", "SHA", "MD", "ISO", "TLS", "SSL", "AES", "RSA", "HTTP", "HTTPS",
                 "RFC", "CVE", "CWE", "JDK", "JAVA", "PR", "MR"}


def extract_keys(text, allowed=None):
    """Jira-Keys (z. B. DLP-123) aus Branchnamen und Titeln.

    Mit `allowed` (jira.project_keys) zählen nur diese Projekte, auch kleingeschrieben (feature/dlp-123).
    Ohne `allowed` zählen nur GROSS geschriebene Keys, sonst würde 'sonar-wave-1' als Ticket gelten."""
    allowed = {a.upper() for a in (allowed or [])}
    out = []
    for m in KEY_RE.finditer(text or ""):
        key = m.group(1).upper()
        prefix = key.rsplit("-", 1)[0]
        if allowed:
            if prefix not in allowed:
                continue
        elif not m.group(1).isupper() or prefix in DENY_PREFIXES:
            continue
        if key not in out:
            out.append(key)
    return out


def make_ssl(cfg):
    try:
        return net.make_ssl_ca(cfg.get("ca_bundle"))
    except ValueError as e:
        raise SystemExit(str(e))


def feature(cfg, name):
    return bool((cfg.get("features") or {}).get(name, False))


def warn_plain_http(url, label):
    host = urllib.parse.urlparse(url).hostname or ""
    if url.lower().startswith("http://") and host not in LOOPBACK:
        sys.stderr.write("Warnung: %s läuft über http://. Der Zugangstoken geht unverschlüsselt über das Netz.\n" % label)


# ---------------------------------------------------------------- HTTP-Client
class Http:
    def __init__(self, label, base, headers, ctx):
        self.label, self.base, self.headers = label, base, headers
        self.opener = urllib.request.build_opener(NoRedirect, urllib.request.HTTPSHandler(context=ctx))

    def post_json(self, path, body):
        """Schreibender Aufruf. Wird nur für ausdrücklich ausgelöste Aktionen benutzt (Ticket anlegen)."""
        lg = glog if self.label == "GitLab" else jlog
        req = urllib.request.Request(self.base + path, data=json.dumps(body).encode("utf-8"), method="POST",
                                     headers=dict(self.headers, **{"Content-Type": "application/json"}))
        t0 = time.time()
        try:
            with self.opener.open(req, timeout=20) as r:
                data = json.loads(r.read().decode("utf-8") or "{}")
                lg.info("SCHREIBEN POST %s → %s in %d ms", path, r.status, int((time.time() - t0) * 1000))
                return data
        except urllib.error.HTTPError as e:
            detail = ""
            try:
                j = json.loads(e.read(4000).decode("utf-8"))
                errs = list((j.get("errors") or {}).values()) + list(j.get("errorMessages") or [])
                detail = "; ".join(str(x) for x in errs)
            except Exception:
                pass
            lg.warning("SCHREIBEN POST %s → HTTP %s: %s", path, e.code, scrub(detail))
            hint = {401: " (Zugangsdaten falsch oder abgelaufen)", 403: " (keine Berechtigung zum Anlegen in diesem Projekt)"}.get(e.code, "")
            raise HttpStatus("%s: HTTP %s%s%s" % (self.label, e.code, hint, (": " + scrub(detail)) if detail else ""), e.code)
        except (urllib.error.URLError, http.client.HTTPException, OSError) as e:
            raise UserError("%s nicht erreichbar (%s)." % (self.label, scrub(getattr(e, "reason", e))))
        except ValueError:
            raise UserError("%s: Antwort ist kein JSON." % self.label)

    def get(self, path, params=None):
        url = self.base + path
        if params:
            url += "?" + urllib.parse.urlencode(params)
        req = urllib.request.Request(url, headers=self.headers)
        lg = glog if self.label == "GitLab" else jlog
        t0 = time.time()
        shown = path + (("?" + urllib.parse.urlencode(params)) if params else "")
        try:
            with self.opener.open(req, timeout=15) as r:
                data = json.loads(r.read().decode("utf-8"))
                ms = int((time.time() - t0) * 1000)
                (lg.info if ms > 3000 else lg.debug)("GET %s → %s in %d ms%s", shown, r.status, ms,
                                                    " (langsam)" if ms > 3000 else "")
                return data
        except urllib.error.HTTPError as e:
            lg.warning("GET %s → HTTP %s in %d ms", shown, e.code, int((time.time() - t0) * 1000))
            hint = ""
            if e.code == 401:
                hint = " (Zugangsdaten falsch oder abgelaufen)"
            elif e.code in (301, 302, 303, 307, 308):
                hint = " (URL leitet um, prüfe die URL in der config.json, z. B. https statt http)"
            raise HttpStatus("%s %s: HTTP %s%s" % (self.label, path, e.code, hint), e.code)
        except (urllib.error.URLError, http.client.HTTPException, OSError) as e:
            msg = scrub(getattr(e, "reason", e))
            lg.warning("GET %s → nicht erreichbar nach %d ms: %s", shown, int((time.time() - t0) * 1000), msg)
            hint = " Tipp: ca_bundle in der config.json auf die Firmen-CA setzen." if "CERTIFICATE_VERIFY_FAILED" in msg else ""
            raise UserError("%s nicht erreichbar (%s).%s" % (self.label, msg, hint))
        except ValueError:
            lg.warning("GET %s → Antwort ist kein JSON", shown)
            raise UserError("%s %s: Antwort ist kein JSON (falsche URL?)" % (self.label, path))


# ---------------------------------------------------------------- Ideen
class Ideas:
    def __init__(self, path, cap, expire_days):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.path = str(path)
        self.cap = cap
        self.expire_days = expire_days
        with self._conn() as c:
            c.execute(
                "create table if not exists ideas("
                "id integer primary key autoincrement, text text not null,"
                "status text not null default 'neu', created text not null)"
            )
            have = {r[1] for r in c.execute("pragma table_info(ideas)")}
            for col in ("assessment", "ticket", "draft"):            # 0.20: Bewertung, Ticket aus der Idee
                if col not in have:
                    c.execute("alter table ideas add column %s text not null default ''" % col)

    @contextmanager
    def _conn(self):
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def list(self):
        with self._conn() as c:
            rows = [dict(r) for r in c.execute("select * from ideas order by id desc")]
        for r in rows:
            r["age_days"] = age_days(r["created"])
            r["expired"] = r["status"] == "neu" and r["age_days"] >= self.expire_days
            try:
                r["assessment"] = json.loads(r.get("assessment") or "null")
            except ValueError:
                r["assessment"] = None
            try:
                r["draft"] = json.loads(r.get("draft") or "null")
            except ValueError:
                r["draft"] = None
        return rows

    def get(self, idea_id):
        return next((i for i in self.list() if i["id"] == int(idea_id)), None)

    def set_field(self, idea_id, **kw):
        bad = set(kw) - {"assessment", "ticket", "draft", "status"}
        if bad:
            raise UserError("Unbekannte Felder.")
        vals = [json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else ("" if v is None else str(v)) for v in kw.values()]
        with self._conn() as c:
            c.execute("update ideas set %s where id=?" % ", ".join("%s=?" % k for k in kw), vals + [int(idea_id)])

    def open_count(self):
        return sum(1 for r in self.list() if r["status"] in ("neu", "geparkt") and not r["expired"])

    def add(self, text):
        text = (text or "").strip()
        if not text:
            raise UserError("Leere Idee.")
        if len(text) > 2000:
            raise UserError("Idee ist zu lang (max. 2000 Zeichen).")
        if self.open_count() >= self.cap:
            raise UserError("Ideenbox voll (%d). Erst triagieren oder verwerfen." % self.cap)
        now = datetime.now(timezone.utc).isoformat()
        with self._conn() as c:
            cur = c.execute("insert into ideas(text, created) values(?, ?)", (text, now))
            return cur.lastrowid

    def set_status(self, idea_id, status):
        if status not in ("neu", "geparkt", "verworfen", "erledigt"):
            raise UserError("Unbekannter Status.")
        with self._conn() as c:
            c.execute("update ideas set status=? where id=?", (status, idea_id))

    def delete(self, idea_id):
        with self._conn() as c:
            c.execute("delete from ideas where id=?", (idea_id,))


STOPWORDS = set("und oder der die das ein eine einen dem den des mit für von zu im in am an auf aus bei ist sind wird werden nicht noch auch nur als wie "
                "mehr neue neuer neues soll sollte kann können machen einbauen bauen the and for with".split())


def _words(t):
    return {w for w in re.findall(r"[a-zäöüß0-9]{3,}", (t or "").lower()) if w not in STOPWORDS}


def similar(text, candidates, threshold=0.34, limit=5):
    """Ähnliche Ideen oder Vorhaben, ohne Modell: Anteil gemeinsamer Wörter (Jaccard). candidates: [(id, text)]."""
    a = _words(text)
    out = []
    if not a:
        return out
    for cid, t in candidates:
        b = _words(t)
        if not b:
            continue
        score = len(a & b) / float(len(a | b))
        if score >= threshold:
            out.append({"id": cid, "label": " ".join(str(t).split())[:120], "score": round(score, 2)})
    return sorted(out, key=lambda x: -x["score"])[:limit]


# ---------------------------------------------------------------- GitLab
def ref_slug(branch):
    """Wie CI_COMMIT_REF_SLUG: klein, alles ausser a-z0-9 wird «-», höchstens 63 Zeichen, ohne «-» am Rand."""
    s_ = re.sub(r"[^a-z0-9]", "-", (branch or "").lower())[:63]
    return s_.strip("-")


def derive_state(item):
    if item["kind"] == "branch":
        return "kein-mr"
    if item["draft"]:
        return "draft"
    if item["pipeline"] == "failed":
        return "rot"
    if item["pipeline"] in ("running", "pending", "created", "waiting_for_resource"):
        return "laeuft"
    if item["pipeline"] == "success":
        return "bereit"
    return "offen"


def identity(cfg, me):
    """Wer bin ich, wer ist mein Agent: aus den Einstellungen (Meine Commits) und dem angemeldeten Konto."""
    bf = branch_cfg(cfg)

    def low(xs):
        return {str(x).strip().lower() for x in xs if str(x).strip()}

    emails = low(list(cfg.get("my_emails") or []) + list(bf["emails"]) +
                 [me.get("email") or "", me.get("public_email") or "", me.get("commit_email") or ""])
    names = low(list(bf["names"]) + [me.get("name") or ""])
    return {"emails": emails, "names": names,
            "agent_emails": low(bf["agent_emails"]), "agent_names": low(bf["agent_names"]),
            "patterns": [p.lower() for p in bf["agent_message_patterns"] if p]}


def classify_commits(commits, ident):
    """Wem gehört ein Branch? Betrachtet alle Commits, die der Branch dem Default-Branch voraus hat.

    include  = mindestens ein Commit von dir oder von der Agent-Identität (diese Branches werden gezeigt)
    by_agent = Agent-Identität, oder deine Commits mit Agent-Zeile in der Nachricht (z. B. Co-Authored-By: Claude).
    Eine Agent-Zeile allein bei einem Kollegen reicht NICHT, sonst würden fremde Branches auftauchen."""
    by_me = agent_id = trailer = False
    for c in commits:
        email = (c.get("author_email") or "").strip().lower()
        name = (c.get("author_name") or "").strip().lower()
        msg = ("%s\n%s" % (c.get("message") or "", c.get("title") or "")).lower()
        if email in ident["emails"] or name in ident["names"]:
            by_me = True
        if email in ident["agent_emails"] or name in ident["agent_names"]:
            agent_id = True
        if any(p in msg for p in ident["patterns"]):
            trailer = True
    return {"ahead": len(commits), "by_me": by_me, "by_agent": agent_id or (by_me and trailer),
            "include": by_me or agent_id}


class GitLabClient:
    def __init__(self, cfg, token, ctx):
        self.cfg = cfg
        self.http = Http("GitLab", cfg["gitlab_url"].rstrip("/") + "/api/v4",
                         {"PRIVATE-TOKEN": token, "Accept": "application/json"}, ctx)
        self.proj_cfg = {p["id"]: p for p in cfg["projects"]}
        self._bcache = {}   # (Projekt, Branch, Commit) -> Ergebnis; ein neuer Commit ergibt einen neuen Eintrag

    def _pipeline(self, project_id, ref):
        try:
            res = self.http.get("/projects/%s/pipelines" % project_id, {"ref": ref, "per_page": 1})
        except UserError:
            return "none", ""
        if res:
            return res[0].get("status", "none"), res[0].get("web_url", "")
        return "none", ""

    def _mr_item(self, mr, kind, project_name):
        pid = mr["project_id"]
        pipeline, purl = "none", ""
        if pid in self.proj_cfg:
            pipeline, purl = self._pipeline(pid, mr["source_branch"])
        app_url, app_env = self._review_app(pid, mr["source_branch"]) if pid in self.proj_cfg else ("", "")
        item = {
            "kind": kind, "project_id": pid,
            "project": project_name, "title": mr["title"],
            "branch": mr["source_branch"], "iid": mr["iid"], "url": mr["web_url"],
            "draft": bool(mr.get("draft") or mr.get("work_in_progress")),
            "pipeline": pipeline, "pipeline_url": purl,
            "updated_at": mr.get("updated_at", ""), "sha": mr.get("sha", ""),
            "author": (mr.get("author") or {}).get("username", ""),
            "can_deploy": pid in self.proj_cfg,
            "merge_status": mr.get("detailed_merge_status") or "",   # GitLab ab 15.6: mergeable, not_approved, conflict, ...
            "reviewers": [r.get("username", "") for r in (mr.get("reviewers") or [])] if "reviewers" in mr else None,
            "upvotes": int(mr.get("upvotes") or 0), "host": "gitlab",
            "approved": None, "approved_by": [], "approvals_left": None,
            "target_branch": mr.get("target_branch", ""), "review_app": app_url, "review_env": app_env,
        }
        if kind == "mr":
            self._approvals(item)
        item["age_days"] = age_days(item["updated_at"])
        item["state"] = derive_state(item) if kind == "mr" else "review"
        return item

    def _review_app(self, pid, branch):
        """URL der Review-App zum Branch aus den GitLab-Environments (ein GET je Projekt und Minute, nur lesend).
        Erkannt wird ein Environment, dessen letzte Bereitstellung diesen Branch hat oder dessen Name auf den Branch-Slug endet
        (übliche Benennung review/$CI_COMMIT_REF_SLUG)."""
        cache = self.__dict__.setdefault("_env_cache", {})
        hit = cache.get(pid)
        if not hit or time.time() - hit[0] > 60:
            try:
                envs = self.http.get("/projects/%s/environments" % pid, {"states": "available", "per_page": 100}) or []
            except UserError as e:
                glog.debug("Environments von %s nicht lesbar: %s", pid, e)
                envs = []
            hit = cache[pid] = (time.time(), envs)
        slug = ref_slug(branch)
        for e in hit[1]:
            if not e.get("external_url"):
                continue
            last = (e.get("last_deployment") or {})
            if last.get("ref") == branch or (e.get("name") or "").rsplit("/", 1)[-1] == slug:
                return e["external_url"], e.get("name", "")
        return "", ""

    def _approvals(self, item):
        """Freigaben eines eigenen MR (ein GET je MR). Fehlt das Recht oder die Funktion, bleibt es «unbekannt»."""
        try:
            a = self.http.get("/projects/%s/merge_requests/%s/approvals" % (item["project_id"], item["iid"]))
        except UserError as e:
            glog.debug("Freigaben von !%s nicht lesbar: %s", item["iid"], e)
            item["approval_unknown"] = True
            return
        item["approved_by"] = [((x.get("user") or {}).get("username") or "") for x in (a.get("approved_by") or [])]
        left = a.get("approvals_left")
        item["approvals_left"] = int(left) if isinstance(left, int) else None
        item["approved"] = bool(item["approved_by"])     # «approved» von GitLab ist auch ohne Regeln wahr; zählt nur, wer wirklich freigegeben hat

    def _identity(self, me):
        return identity(self.cfg, me)

    def _classify(self, pid, default, b, ident):
        sha = (b.get("commit") or {}).get("id", "")
        key = (pid, b["name"], sha)
        if sha and key in self._bcache:
            return self._bcache[key]
        try:
            res = self.http.get("/projects/%s/repository/compare" % pid,
                                {"from": default, "to": b["name"], "straight": "false"})
        except UserError:
            return None
        info = classify_commits(res.get("commits") or [], ident)
        if sha:
            self._bcache[key] = info
        return info

    def review_threads(self, project_id, iid):
        """MR (Zielbranch, aktueller Commit) und seine Diskussionen, höchstens 500. Nur GET."""
        mr = self.http.get("/projects/%s/merge_requests/%s" % (project_id, iid))
        out = []
        for page in range(1, 6):
            res = self.http.get("/projects/%s/merge_requests/%s/discussions" % (project_id, iid), {"per_page": 100, "page": page}) or []
            out.extend(res)
            if len(res) < 100:
                break
        return mr, out

    def ticket_context(self, project_id, iid, branch):
        """Das, was ein Ticket-Entwurf braucht: Titel, MR-Beschreibung, Commit-Titel. Keine Diffs, keine Dateiinhalte."""
        ctx = {"project_id": project_id, "iid": iid, "branch": branch, "project": self._pname(project_id),
               "title": branch, "mr_description": "", "commits": [], "url": ""}
        if iid:
            mr = self.http.get("/projects/%s/merge_requests/%s" % (project_id, iid))
            ctx.update(title=mr.get("title", ""), mr_description=mr.get("description") or "", url=mr.get("web_url", ""))
            commits = self.http.get("/projects/%s/merge_requests/%s/commits" % (project_id, iid), {"per_page": 20})
        else:
            proj = self.http.get("/projects/%s" % project_id)
            default = proj.get("default_branch") or "main"
            ctx["url"] = proj.get("web_url", "") + "/-/tree/" + urllib.parse.quote(branch)
            res = self.http.get("/projects/%s/repository/compare" % project_id, {"from": default, "to": branch, "straight": "false"})
            commits = res.get("commits") or []
            ctx["title"] = (commits[-1].get("title") if commits else "") or branch
        ctx["commits"] = [(c.get("title") or "").strip() for c in commits if c.get("title")][:20]
        return ctx

    def _pname(self, project_id):
        return self.proj_cfg.get(project_id, {}).get("name", "Projekt %s" % project_id)

    def fetch(self, sink=None, step=None):
        """Holt alles von GitLab. Ergebnisse landen schon während des Abrufs in `sink` (Liste für Liste), und `step(id, Titel, Status, Detail)`
        meldet den Fortschritt, damit die Oberfläche nicht auf das Ende warten muss."""
        step = step or (lambda *a, **k: None)
        sink = sink if sink is not None else {}
        errors = sink.setdefault("errors", [])
        step("gl-user", "Bei GitLab anmelden", "run")
        me = self.http.get("/user")
        username = me["username"]
        sink["me"] = username
        step("gl-user", "Bei GitLab anmelden", "ok", username)
        ident = self._identity(me)
        glog.debug("Angemeldet als %s, %d E-Mails und %d Namen für die Branch-Erkennung", username,
                   len(ident["emails"]), len(ident["names"]))
        bf = branch_cfg(self.cfg)
        ignore = list(bf.get("ignore_branches") or [])
        mine = sink.setdefault("mine", [])
        review = sink.setdefault("review", [])
        assigned = sink.setdefault("assigned", [])

        def one(p):
            pid, name = p["id"], p.get("name", str(p["id"]))
            try:
                proj = self.http.get("/projects/%s" % pid)
                default = proj.get("default_branch", "main")
                mrs = self.http.get("/projects/%s/merge_requests" % pid,
                                    {"state": "opened", "author_username": username, "per_page": 50})
                with_mr = set()
                ignored_mrs = 0
                for mr in mrs:
                    with_mr.add(mr["source_branch"])
                    if ignored_branch(mr["source_branch"], ignore):
                        glog.debug("%s: MR !%s übersprungen (Branch %s passt auf ignore_branches)", name, mr["iid"], mr["source_branch"])
                        ignored_mrs += 1
                        continue
                    mine.append(self._mr_item(mr, "mr", name))
                branches = self.http.get("/projects/%s/repository/branches" % pid, {"per_page": 100})
                branches.sort(key=lambda b: _age_key((b.get("commit") or {}).get("committed_date")))
                checked = 0
                shown_b = skipped = 0
                for b in branches:
                    bn = b["name"]
                    reason = ("Default-Branch" if bn == default else "geschützt" if b.get("protected")
                              else "schon gemergt" if b.get("merged") else "hat einen MR" if bn in with_mr
                              else "passt auf ignore_branches" if ignored_branch(bn, ignore) else "")
                    if reason:
                        glog.debug("%s: Branch %s übersprungen (%s)", name, bn, reason)
                        continue
                    commit = b.get("commit") or {}
                    ts = commit.get("committed_date", "")
                    if int(bf["max_age_days"]) and age_days(ts) > int(bf["max_age_days"]):
                        glog.debug("%s: Branch %s übersprungen (%d Tage alt, Limit %s)", name, bn, age_days(ts), bf["max_age_days"])
                        skipped += 1
                        continue
                    if checked >= int(bf["max_branches"]):
                        glog.info("%s: max_branches=%s erreicht, weitere Branches werden nicht geprüft", name, bf["max_branches"])
                        break
                    checked += 1
                    info = self._classify(pid, default, b, ident)
                    if info is None:   # Vergleich fehlgeschlagen: dann zählt nur der letzte Commit
                        glog.warning("%s: Vergleich für Branch %s fehlgeschlagen, es zählt nur der letzte Commit", name, bn)
                        if (commit.get("author_email") or "").lower() not in ident["emails"]:
                            continue
                        info = {"ahead": 0, "by_me": True, "by_agent": False, "include": True}
                    if not info["include"]:
                        glog.debug("%s: Branch %s ausgeblendet (%d Commits, keiner von dir oder dem Agenten)", name, bn, info["ahead"])
                        continue
                    shown_b += 1
                    glog.debug("%s: Branch %s angezeigt (%d Commits, von mir=%s, Agent=%s)", name, bn, info["ahead"],
                               info["by_me"], info["by_agent"])
                    mine.append({
                        "kind": "branch", "project_id": pid, "project": name,
                        "title": commit.get("title", b["name"]), "branch": b["name"], "iid": None,
                        "url": proj.get("web_url", "") + "/-/tree/" + urllib.parse.quote(b["name"]),
                        "draft": False, "pipeline": "none", "pipeline_url": "",
                        "updated_at": ts, "sha": commit.get("id", ""), "author": username,
                        "can_deploy": False, "age_days": age_days(ts), "state": "kein-mr",
                        "ahead": info["ahead"], "by_me": info["by_me"], "by_agent": info["by_agent"],
                        "last_author": commit.get("author_name", ""),
                        "create_mr_url": proj.get("web_url", "") + "/-/merge_requests/new?merge_request%5Bsource_branch%5D=" + urllib.parse.quote(b["name"], safe=""),
                    })
                glog.info("%s: %d eigene MRs (%d ignoriert), %d Branches geprüft, %d angezeigt, %d zu alt", name, len(mrs),
                          ignored_mrs, checked, shown_b, skipped)
                return "ok", "%d MR, %d Branches" % (len(mrs) - ignored_mrs, shown_b)
            except UserError as e:
                glog.error("%s: %s", name, e)
                errors.append("%s: %s" % (name, e))
                sink.setdefault("gl_failed_pids", []).append(pid)
                return "err", str(e)

        def run_one(p):
            name = p.get("name", str(p["id"]))
            sid = "gl-%s" % p["id"]
            step(sid, "Projekt " + name, "run")
            status, detail = one(p)
            step(sid, "Projekt " + name, status, detail)

        projects = list(self.cfg["projects"])
        for p in projects:
            step("gl-%s" % p["id"], "Projekt " + p.get("name", str(p["id"])), "wait")
        step("gl-review", "Review-Queue", "wait")
        step("gl-assigned", "Mir zugeteilte MRs", "wait")
        if projects:
            from concurrent.futures import ThreadPoolExecutor
            with ThreadPoolExecutor(max_workers=min(3, len(projects))) as pool:
                list(pool.map(run_one, projects))
        order = {p["id"]: i for i, p in enumerate(projects)}
        mine.sort(key=lambda it: order.get(it["project_id"], 99))   # stabil: innerhalb eines Projekts bleibt die Reihenfolge
        step("gl-review", "Review-Queue", "run")
        try:
            rmrs = self.http.get("/merge_requests", {"state": "opened", "scope": "all",
                                                     "reviewer_username": username, "per_page": 50})
            for mr in rmrs:
                review.append(self._mr_item(mr, "review", self._pname(mr["project_id"])))
            step("gl-review", "Review-Queue", "ok", "%d MR" % len(review))
        except UserError as e:
            errors.append("Review-Queue: %s" % e)
            step("gl-review", "Review-Queue", "err", str(e))
        step("gl-assigned", "Mir zugeteilte MRs", "run")
        try:
            seen = {(m["project_id"], m["iid"]) for m in review}
            seen |= {(m["project_id"], m["iid"]) for m in mine if m["kind"] == "mr"}
            amrs = self.http.get("/merge_requests", {"state": "opened", "scope": "all",
                                                     "assignee_username": username, "per_page": 50})
            for mr in amrs:
                if (mr["project_id"], mr["iid"]) in seen:
                    continue
                assigned.append(self._mr_item(mr, "assigned", self._pname(mr["project_id"])))
            step("gl-assigned", "Mir zugeteilte MRs", "ok", "%d MR" % len(assigned))
        except UserError as e:
            errors.append("Zugeteilte MRs: %s" % e)
            step("gl-assigned", "Mir zugeteilte MRs", "err", str(e))
        return sink

    def mr(self, project_id, iid):
        mr = self.http.get("/projects/%s/merge_requests/%s" % (project_id, iid))
        return {"title": mr["title"], "branch": mr["source_branch"], "sha": mr["sha"],
                "url": mr["web_url"]}


# ---------------------------------------------------------------- Jira
class JiraClient:
    def __init__(self, jc, auth_header, ctx):
        self.jc = jc
        self.base = jc["url"].rstrip("/")
        self.http = Http("Jira", self.base + "/rest/api/2",
                         {"Authorization": auth_header, "Accept": "application/json"}, ctx)
        self._sf = None   # Feld-ID des Sprint-Feldes; "" = es gibt keines

    def sprint_field(self):
        if self._sf is None:
            self._sf = ""
            try:
                for f in self.http.get("/field"):
                    if f.get("name") == "Sprint" and "gh-sprint" in str((f.get("schema") or {}).get("custom", "")):
                        self._sf = f["id"]
                        break
                jlog.info("Sprint-Feld: %s", self._sf or "nicht gefunden (kein Jira Software?)")
            except UserError as e:
                jlog.warning("Sprint-Feld nicht lesbar: %s", e)
        return self._sf

    def _fields(self):
        sf = self.sprint_field()
        return ["summary", "status", "issuetype"] + ([sf] if sf else [])

    def _issue(self, i):
        f = i.get("fields") or {}
        out = {
            "key": i["key"], "summary": f.get("summary", ""),
            "status": (f.get("status") or {}).get("name", ""),
            "type": (f.get("issuetype") or {}).get("name", ""),
            "url": self.base + "/browse/" + i["key"],
            "sprint": "", "sprint_end": "", "in_sprint": None,
        }
        if self._sf:
            act = sprint.active_sprint(f.get(self._sf))
            out["in_sprint"] = bool(act)
            if act:
                out["sprint"], out["sprint_end"] = act["name"], act["end"]
        return out

    def _search(self, jql, fields, limit=100):
        res = self.http.get("/search", {"jql": jql, "fields": ",".join(fields), "maxResults": limit})
        return res.get("issues", []), int(res.get("total", 0))

    def jql_in_progress(self):
        return sprint.effective_jql(self.jc["jql_in_progress"], self.jc.get("only_active_sprints", True))

    def in_progress(self):
        fields = self._fields()
        jql = self.jql_in_progress()
        jlog.debug("JQL in Arbeit: %s", jql)
        issues, _ = self._search(jql, fields)
        out = [self._issue(i) for i in issues]
        if self.jc.get("only_active_sprints", True):
            for o in out:
                o["in_sprint"] = True   # die JQL hat es schon geprüft
        return out

    def lookup(self, keys):
        """Einzelabfragen: ein unbekannter Key bricht sonst die ganze JQL-Suche ab."""
        out = {}
        for key in keys[:60]:
            try:
                out[key] = self._issue(self.http.get("/issue/" + urllib.parse.quote(key),
                                                     {"fields": ",".join(self._fields())}))
            except HttpStatus as e:
                if e.code in (400, 403, 404):
                    continue
                raise
        return out

    def helpdesk(self):
        h = self.jc.get("helpdesk") or {}
        if not h.get("jql"):
            return None
        issues, total = self._search(h["jql"], ["created", "summary"])
        ages = [hours_since((i.get("fields") or {}).get("created")) for i in issues]
        sla = float(h.get("sla_hours", 24))
        return {
            "open": total,
            "oldest_hours": int(max(ages)) if ages else 0,
            "over_hours": sum(1 for a in ages if a >= sla),
            "sla_hours": sla,
            "truncated": total > len(issues),
            "url": self.base + "/issues/?jql=" + urllib.parse.quote(h["jql"]),
        }

    def issue_types(self, project_key):
        """Erlaubte Vorgangstypen des Projekts (ohne Unteraufgaben)."""
        res = self.http.get("/project/" + urllib.parse.quote(project_key))
        return [t["name"] for t in res.get("issueTypes", []) if not t.get("subtask")]

    def create_issue(self, project_key, issue_type, summary, description):
        res = self.http.post_json("/issue", {"fields": {
            "project": {"key": project_key}, "issuetype": {"name": issue_type},
            "summary": summary, "description": description}})
        return {"key": res["key"], "url": "%s/browse/%s" % (self.base, res["key"])}

    def create_url(self, summary):
        pid, it = self.jc.get("create_pid"), self.jc.get("create_issuetype")
        if pid and it:
            return "%s/secure/CreateIssueDetails!init.jspa?pid=%s&issuetype=%s&summary=%s" % (
                self.base, urllib.parse.quote(str(pid)), urllib.parse.quote(str(it)),
                urllib.parse.quote(summary[:200]))
        return self.base + "/secure/CreateIssue!default.jspa"


def jira_auth_header(jc, secrets):
    auth = jc.get("auth", "bearer")
    if auth == "bearer":
        return "Bearer " + secrets["jira_token"]
    if auth == "basic":
        if not jc.get("username"):
            raise SystemExit("jira.username fehlt in der config.json (nötig bei auth = basic).")
        raw = base64.b64encode(("%s:%s" % (jc["username"], secrets["jira_password"])).encode("utf-8")).decode("ascii")
        store.register(raw)
        return "Basic " + raw
    raise SystemExit("jira.auth muss 'bearer' oder 'basic' sein.")


# ---------------------------------------------------------------- Demo
class DemoClient:
    """Erfundene Daten, um die Oberfläche ohne GitLab und Jira anzusehen."""

    def __init__(self, cfg):
        self.cfg = cfg

    def ticket_context(self, project_id, iid, branch):
        return {"project_id": project_id, "iid": iid, "branch": branch, "project": "dlp-core", "url": "https://gitlab.example/demo/" + branch,
                "title": "Findings Welle 1" if iid else "WIP " + branch, "mr_description": "Sonar-Findings der ersten Welle beheben." if iid else "",
                "commits": ["Sonar: Null-Checks ergänzen", "Sonar: ungenutzte Imports entfernen"]}

    @staticmethod
    def _ago(days):
        return datetime.fromtimestamp(time.time() - days * 86400, timezone.utc).isoformat()

    def _item(self, kind, iid, title, branch, days, pipeline="success", draft=False, project="dlp-core"):
        item = {
            "kind": kind, "project_id": 1, "project": project, "title": title,
            "branch": branch, "iid": iid, "url": "https://gitlab.example/demo/%s" % branch,
            "draft": draft, "pipeline": pipeline, "pipeline_url": "",
            "updated_at": self._ago(days), "sha": "a1b2c3d4e5f60718", "author": "demo",
            "can_deploy": iid is not None, "age_days": days,
        }
        if iid is None:
            item["create_mr_url"] = "https://gitlab.example/demo/-/merge_requests/new?merge_request%5Bsource_branch%5D=" + urllib.parse.quote(branch, safe="")
        item["state"] = derive_state(item) if kind == "mr" else "review"
        return item

    def fetch(self, sink=None, step=None):
        step = step or (lambda *a, **k: None)
        sink = sink if sink is not None else {}
        delay = float(os.environ.get("TINYOPS_DEMO_DELAY", "0"))   # nur zum Ansehen des Fortschritts

        def pause(sid, title, detail):
            step(sid, title, "run")
            time.sleep(delay)
            step(sid, title, "ok", detail)
        for sid, title in (("gl-user", "Bei GitLab anmelden"), ("gl-1", "Projekt dlp-core"), ("gl-2", "Projekt dlp-ui"),
                           ("gl-review", "Review-Queue"), ("gl-assigned", "Mir zugeteilte MRs")):
            step(sid, title, "wait")
        pause("gl-user", "Bei GitLab anmelden", "demo")
        mine = [
            self._item("mr", 41, "Vendex-Adapter: Retry bei 429", "feature/DLP-101-vendex-retry", 0, "running"),
            self._item("mr", 38, "Helm: Resource Limits setzen", "feature/DLP-102-helm-limits", 1, "success"),
            self._item("mr", 35, "Sonar: Findings Welle 1", "agent/sonar-wave-1", 3, "failed"),
            self._item("mr", 29, "Labelo: Graph-Client Refactoring", "feature/DLP-103-labelo-client", 9, "success", draft=True),
        ]
        for m, rv, up, by in ((mine[0], ["kollege"], 0, []), (mine[1], ["kollege"], 1, ["kollege"]), (mine[2], [], 0, []), (mine[3], [], 0, [])):
            m.update(reviewers=rv, upvotes=up, approved=bool(by), approved_by=by, host="gitlab", merge_status="mergeable" if by else "", target_branch="main")
        mine[1]["review_app"], mine[1]["review_env"] = "https://review-dlp-102-helm-limits.apps.example", "review/feature-dlp-102-helm-limits"
        for name, days, ahead, by_me, by_agent in (
                ("feature/proxo-mapping", 14, 5, True, False),
                ("idea/ui-prototype", 22, 2, True, True),
                ("feature/DLP-120-retry-tests", 1, 3, False, True)):
            b = self._item("branch", None, "WIP " + name, name, days, "none")
            b["kind"], b["state"], b["can_deploy"] = "branch", "kein-mr", False
            b.update({"ahead": ahead, "by_me": by_me, "by_agent": by_agent, "last_author": "Demo"})
            mine.append(b)
        review = [
            self._item("review", 52, "Angular: Policy-Tabelle filtern", "feature/DLP-140-policy-filter", 0, "success", project="dlp-ui"),
            self._item("review", 50, "Dockerfile: non-root", "chore/docker-nonroot", 2, "success"),
        ]
        assigned = [self._item("assigned", 47, "Sonar: Quality Gate anpassen", "feature/DLP-150-sonar-gate", 4, "success")]
        for r in review + assigned:
            r["author"] = "kollege"
        gh = self._item("mr", 7, "Webhook-Empfänger für GitHub", "feature/DLP-105-webhooks", 2, "success", project="adrian/tinyops-hooks")
        gh.update(project_id=github.pid_of(42), host="github", url="https://github.com/adrian/tinyops-hooks/pull/7", reviewers=["octocat"], upvotes=0,
                  approved=False, approved_by=[], merge_status="mergeable", can_deploy=False)
        mine.insert(4, gh)
        sink.update(me="demo", errors=[])
        sink.setdefault("mine", []).extend(mine[:5])
        pause("gl-1", "Projekt dlp-core", "4 MR")
        sink["mine"].extend(mine[5:])
        sink.setdefault("review", []).extend(review)
        pause("gl-2", "Projekt dlp-ui", "3 Branches")
        pause("gl-review", "Review-Queue", "%d MR" % len(review))
        sink.setdefault("assigned", []).extend(assigned)
        pause("gl-assigned", "Mir zugeteilte MRs", "%d MR" % len(assigned))
        return sink

    def review_threads(self, project_id, iid):
        sha = "a1b2c3d4e5f60718"
        pos = lambda f, line, head=sha: {"new_path": f, "old_path": f, "new_line": line, "head_sha": head, "position_type": "text"}
        note = lambda nid, who, body, **kw: dict({"id": nid, "body": body, "author": {"username": who}, "created_at": "2026-11-04T09:12:00Z",
                                                  "system": False, "resolvable": True, "resolved": False}, **kw)
        disc = [
            {"id": "d1", "notes": [note(901, "kollege", "Hier fehlt das Backoff: bei 429 sofort erneut zu senden verschärft das Rate-Limit. Bitte exponentiell mit Obergrenze.",
                                        position=pos("src/main/java/ch/dlp/vendex/VendexClient.java", 88)),
                                   note(902, "demo", "Guter Punkt, mache ich mit max. 3 Versuchen.")]},
            {"id": "d2", "notes": [note(903, "kollege", "Der Test deckt nur den Erfolgsfall ab. Bitte auch 429 und 503 prüfen.",
                                        position=pos("src/test/java/ch/dlp/vendex/VendexClientTest.java", 41, "0f9e8d7c6b5a4321"))]},
            {"id": "d3", "notes": [note(904, "kollege", "Magic Number 30000 bitte als Konstante mit Einheit.", position=pos("src/main/java/ch/dlp/vendex/VendexClient.java", 23),
                                        resolved=True)]},
            {"id": "d4", "notes": [note(905, "kollege", "Ist das mit dem Helm-Chart abgestimmt? Die Timeouts müssen zusammenpassen.")]},
            {"id": "d5", "notes": [note(906, "gitlab", "added 1 commit", system=True, resolvable=False)]},
        ]
        return {"target_branch": "main", "sha": sha, "web_url": "https://gitlab.example/demo/-/merge_requests/%s" % iid}, disc

    def mr(self, project_id, iid):
        return {"title": "Demo-MR %s" % iid, "branch": "feature/DLP-101-demo-%s" % iid,
                "sha": "a1b2c3d4e5f60718", "url": "https://gitlab.example/demo/%s" % iid}


class DemoSonar:
    """Erfundene Quality Gates für die Demo: stabil pro MR/Branch."""
    base = "https://sonar.example"

    def gate(self, key, pr=None, branch=None):
        import zlib
        n = zlib.crc32(("%s|%s|%s" % (key, pr, branch)).encode()) % 5
        url = "%s/dashboard?id=%s" % (self.base, key)
        if n in (0, 1):
            return {"status": "OK", "failed": [], "url": url, "detail": "bestanden"}
        if n == 2:
            f = [sonar.describe({"metricKey": "new_coverage", "actualValue": "61.2", "errorThreshold": "80", "comparator": "LT"}),
                 sonar.describe({"metricKey": "new_vulnerabilities", "actualValue": "2", "errorThreshold": "0", "comparator": "GT"})]
            return {"status": "ERROR", "failed": f, "url": url, "detail": "; ".join(f)}
        if n == 3:
            f = [sonar.describe({"metricKey": "new_duplicated_lines_density", "actualValue": "4.1", "errorThreshold": "3", "comparator": "GT"})]
            return {"status": "WARN", "failed": f, "url": url, "detail": "; ".join(f)}
        return {"status": "NONE", "failed": [], "url": url, "detail": "keine Analyse"}

    def history(self, key, pr=None, branch=None, metrics=("violations",), limit=60):
        """Erfundener Verlauf: OK-Einträge werden besser, rote schlechter, der Rest bleibt flach."""
        import zlib
        n = zlib.crc32(("%s|%s|%s" % (key, pr, branch)).encode()) % 5
        base = time.time() - 6 * 86400
        shape = {0: [14, 11, 9, 4, 1, 0], 1: [8, 6, 5, 5, 2, 1], 2: [2, 3, 5, 6, 9, 12], 3: [5, 5, 6, 5, 5, 5]}.get(n)
        if not shape:
            return []
        out = []
        for i, v in enumerate(shape):
            row = {"ts": base + i * 86400, "violations": float(v), "bugs": float(v // 4), "vulnerabilities": float(v // 6), "code_smells": float(v - v // 4 - v // 6),
                   "coverage": 55.0 + i * 3}
            out.append({k: x for k, x in row.items() if k == "ts" or k in metrics})
        return out[-limit:]

    def pull_requests(self, key):
        return [{"key": "41", "status": {"qualityGateStatus": "OK"}}]

    def issues_url(self, key, pr=None, branch=None):
        return "%s/project/issues?id=%s&resolved=false" % (self.base, key)

    def hotspots_url(self, key, pr=None, branch=None):
        return "%s/security_hotspots?id=%s" % (self.base, key)

    def issues(self, key, pr=None, branch=None, limit=200):
        it = [{"component": key + ":src/main/java/ch/example/RetryClient.java", "line": 88, "severity": "CRITICAL", "type": "VULNERABILITY",
               "rule": "java:S5131", "message": "Make sure that this user-controlled value is sanitized before it is used."},
              {"component": key + ":src/main/java/ch/example/RetryClient.java", "line": 142, "severity": "MAJOR", "type": "CODE_SMELL",
               "rule": "java:S3776", "message": "Refactor this method to reduce its Cognitive Complexity from 21 to the 15 allowed."},
              {"component": key + ":src/test/java/ch/example/RetryClientTest.java", "line": 31, "severity": "MINOR", "type": "CODE_SMELL",
               "rule": "java:S1135", "message": "Complete the task associated to this TODO comment."}]
        return it[:limit], len(it), {"severities": {"CRITICAL": 1, "MAJOR": 1, "MINOR": 1}, "types": {"VULNERABILITY": 1, "CODE_SMELL": 2}}

    def hotspots(self, key, pr=None, branch=None, limit=100):
        return [{"component": key + ":src/main/resources/application.yml", "line": 12, "vulnerabilityProbability": "MEDIUM",
                 "securityCategory": "weak-cryptography", "message": "Make sure this weak hash algorithm is not used in a sensitive context."}], 1


class DemoJira:
    base = "https://jira.example"
    _DATA = {
        "DLP-101": ("Vendex-Adapter: Retry bei 429", "In Progress"),
        "DLP-102": ("Helm Resource Limits", "In Progress"),
        "DLP-104": ("Installer: Upgrade-Test", "In Progress"),
        "DLP-103": ("Labelo Graph-Client", "To Do"),
        "DLP-120": ("Retry-Tests ergänzen", "To Do"),
        "DLP-140": ("Policy-Tabelle filtern", "In Review"),
        "DLP-150": ("Sonar Quality Gate", "In Review"),
    }

    _BACKLOG = {"DLP-103", "DLP-120"}   # nicht im aktiven Sprint

    def __init__(self, jc):
        self.jc = jc

    def _issue(self, key):
        summary, status = self._DATA[key]
        ins = key not in self._BACKLOG
        end = (datetime.now(timezone.utc) + timedelta(days=9)).isoformat()
        return {"key": key, "summary": summary, "status": status, "type": "Story", "url": "%s/browse/%s" % (self.base, key),
                "sprint": "Sprint 12" if ins else "", "sprint_end": end if ins else "", "in_sprint": ins}

    def in_progress(self):
        return [self._issue(k) for k, v in self._DATA.items() if v[1] == "In Progress"]

    def lookup(self, keys):
        return {k: self._issue(k) for k in keys if k in self._DATA}

    def helpdesk(self):
        return {"open": 7, "oldest_hours": 52, "over_hours": 3, "sla_hours": 24, "truncated": False,
                "url": self.base + "/issues/?jql=project%3DHELP"}

    def create_url(self, summary):
        return self.base + "/secure/CreateIssue!default.jspa"

    def issue_types(self, project_key):
        return ["Story", "Bug", "Task"]

    def create_issue(self, project_key, issue_type, summary, description):
        DemoJira._n = getattr(DemoJira, "_n", 200) + 1
        key = "%s-%d" % (project_key, DemoJira._n)
        return {"key": key, "url": "%s/browse/%s" % (self.base, key)}


# ---------------------------------------------------------------- Jobs
class Jobs:
    def __init__(self, timeout):
        self.timeout = timeout
        self.items = {}
        self.lock = threading.Lock()
        self.counter = 0

    @staticmethod
    def _env():
        """Jobs erben keine Umgebungsvariablen mit Panel-Secrets."""
        drop = set(store.SENSITIVE_ENV)
        return {k: v for k, v in os.environ.items() if k not in drop and not k.startswith("TINYOPS_")}

    def start(self, title, argv, cwd):
        with self.lock:
            self.counter += 1
            jid = self.counter
            head = "$ " + " ".join(argv[:6]) + (" ..." if len(argv) > 6 else "")
            job = {"id": jid, "title": scrub(title), "status": "läuft", "started": time.time(),
                   "log": [scrub(head)], "returncode": None}
            self.items[jid] = job
        joblog.info("Job #%d gestartet: %s (%s)", jid, job["title"], scrub(head))
        threading.Thread(target=self._run, args=(job, argv, cwd), daemon=True).start()
        return jid

    def _run(self, job, argv, cwd):
        try:
            proc = subprocess.Popen(argv, cwd=str(cwd), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                    text=True, errors="replace", env=self._env(), stdin=subprocess.DEVNULL)
        except (OSError, ValueError) as e:
            joblog.error("Job #%d: Start fehlgeschlagen: %s", job["id"], e)
            job["log"].append(scrub("Start fehlgeschlagen: %s" % e))
            job["status"], job["returncode"] = "fehler", -1
            return
        timer = threading.Timer(self.timeout, proc.kill)
        timer.start()
        try:
            for line in proc.stdout:
                job["log"].append(scrub(line.rstrip()))
                joblog.debug("job#%d | %s", job["id"], line.rstrip())
                if len(job["log"]) > 2000:
                    del job["log"][:500]
            proc.wait()
        finally:
            timer.cancel()
        job["returncode"] = proc.returncode
        job["status"] = "ok" if proc.returncode == 0 else "fehler"
        secs = time.time() - job["started"]
        if proc.returncode == 0:
            joblog.info("Job #%d fertig in %.0f s: ok", job["id"], secs)
        else:
            tail_lines = " | ".join(job["log"][-5:])
            joblog.error("Job #%d fehlgeschlagen nach %.0f s (Exit %s). Letzte Zeilen: %s", job["id"], secs,
                         proc.returncode, tail_lines)

    def summary(self):
        with self.lock:
            out = [{k: v for k, v in j.items() if k != "log"} for j in self.items.values()]
        return sorted(out, key=lambda j: -j["id"])[:15]

    def get(self, jid):
        return self.items.get(jid)


# ---------------------------------------------------------------- App
class App:
    def __init__(self, cfg, demo, secrets, config_path=None, watchdog=True):
        self.demo = demo
        self.config_path = Path(config_path) if config_path else default_config_path()
        self.access_token = secrets.get("access_token") or ""
        self.cache_lock = threading.Lock()
        self.sync_lock = threading.Lock()
        self.sync = {"running": False, "steps": [], "started": 0.0, "finished": 0.0, "n": 0}
        self.partial, self.early_stories, self._sync_thread = None, None, None
        self.hd_lock = threading.Lock()
        self.ideas = None
        self.jobs = None
        self.apply(cfg, secrets)
        if watchdog and not os.environ.get("TINYOPS_NO_WATCHDOG"):
            threading.Thread(target=self._watchdog, name="agent-watchdog", daemon=True).start()

    def _watchdog(self):
        """Prüft alle 30 s laufende Agenten, auch wenn niemand das Panel offen hat (Zeitlimit, Ende, verloren).
        Einmal am Tag (und kurz nach dem Start) löscht er alte Agenten-Logs nach agent_log_days."""
        last_ret = time.time() - 86400 + 300
        while True:
            time.sleep(30)
            try:
                if self.store.agent_runs(status="läuft", limit=1):
                    self.agents.poll(force=True)
                if time.time() - last_ret >= 86400:
                    last_ret = time.time()
                    self.agents.retention(self.cfg.get("agent_log_days", 30))
            except Exception as e:   # der Wächter darf nie sterben
                log.warning("Agenten-Wächter: %s", scrub(e))

    def apply(self, cfg, secrets):
        """Baut Clients und Zwischenspeicher aus Config und Secrets neu. Läuft beim Start und nach dem Speichern der Einstellungen.
        Fehlende oder falsche Angaben stoppen nichts: Sie erscheinen als «problems», damit man sie in den Einstellungen beheben kann."""
        self.cfg = cfg
        self.jc = jira_cfg(cfg)
        self.lc = llm_cfg(cfg)
        self.sc = sonar_cfg(cfg)
        self.sonar, self._sonar_cache = None, {}
        self.uc = usage_cfg(cfg)
        self._usage_cache, self._usage_lock = None, threading.Lock()
        self.llm_key = secrets.get("llm_key", "")
        self.store = links.Store(data_dir(cfg) / "tinyops.db")
        self.audit_log = audit.AuditLog(data_dir(cfg) / "tinyops.db")
        if not hasattr(self, "_audit_ctx"):
            self._audit_ctx = threading.local()
        self._rv_cache = {}
        self.timebook = timesheet.TimeBook(data_dir(cfg) / "tinyops.db")
        self.qabook = qa.QaBook(data_dir(cfg) / "tinyops.db")
        self.tc = time_cfg(cfg)
        self.mcp_token = secrets.get("mcp_token", "")
        self.ssl_ctx = ssl.create_default_context()
        if not hasattr(self, "_send_lock"):
            self._send_lock = threading.Lock()
        self.agents = agents.Service(cfg, self.store, store.home_dir() / "agent-runs", BASE)
        self.agents.audit = self.audit
        if self.demo and not self.store.flow_stats()["total_xp"]:
            t = time.time()      # Demo: ein paar erfundene Erfolge der letzten Tage, damit der Spielstand etwas zeigt
            for i, (k, ph, xp, d) in enumerate((("DLP-098", 7, 60, 3), ("DLP-099", 4, 20, 2), ("DLP-101", 4, 10, 1), ("DLP-102", 4, 20, 1), ("DLP-103", 3, 10, 0))):
                self.store.flow_event_once("demo:%d" % i, k, "", "phase", ph, xp, "", t - d * 86400 - 600)
        self._agent_poll_busy = False
        self._cards = {}
        self._src_ok = {}
        self._types_cache = {}
        self._by_key = {}
        self.problems = []
        self.client, self.jira, self.github = None, None, None
        self.ghc = github_cfg(cfg)
        self.cache, self.cache_t = None, 0.0
        self.hd_cache, self.hd_t = None, 0.0
        self.over_limit = False
        self.inprogress_keys = set()
        self.proj_cfg = {p["id"]: p for p in cfg["projects"]}
        if self.jobs is None:
            self.jobs = Jobs(cfg["job_timeout"])
        if (self.demo or feature(cfg, "ideas")) and self.ideas is None:
            self.ideas = Ideas(data_dir(cfg) / "tinyops.db", cfg["idea_cap"], cfg["idea_expire_days"])
        if self.demo:
            self.client = DemoClient(cfg)
            self.jira = DemoJira(self.jc)
            self.sonar = DemoSonar()
            if not self.proj_cfg:
                self.proj_cfg = {1: {"id": 1, "name": "dlp-core", "chart": "./helm/dlp-core"}}
            return
        try:
            ctx = make_ssl(cfg)
        except SystemExit as e:
            self.problems.append(str(e))
            ctx = ssl.create_default_context()
        self.ssl_ctx = ctx
        if not cfg["gitlab_url"]:
            self.problems.append("GitLab-Adresse fehlt.")
        elif not secrets.get("gitlab_token"):
            self.problems.append("GitLab-Token fehlt.")
        else:
            self.client = GitLabClient(cfg, secrets["gitlab_token"], ctx)
        if self.jc["url"]:
            need = "jira_token" if self.jc["auth"] == "bearer" else "jira_password"
            if not secrets.get(need):
                self.problems.append("Jira-%s fehlt." % ("Token" if need == "jira_token" else "Passwort"))
            else:
                try:
                    self.jira = JiraClient(self.jc, jira_auth_header(self.jc, secrets), ctx)
                except SystemExit as e:
                    self.problems.append(str(e))
        if self.ghc["enabled"]:
            if not secrets.get("github_token"):
                self.problems.append("GitHub-Token fehlt.")
            elif not self.ghc["repos"]:
                self.problems.append("GitHub ist eingeschaltet, aber es ist kein Repo ausgewählt.")
                self.github = github.Client(self.ghc["api_url"], secrets["github_token"], ctx)
            else:
                self.github = github.Client(self.ghc["api_url"], secrets["github_token"], ctx)
        if not self.client and self.github:
            self.problems = [p for p in self.problems if not p.startswith("GitLab")]   # nur GitHub ist auch eine gültige Einrichtung
        if self.sc["enabled"]:
            if not self.sc["url"]:
                self.problems.append("Sonar-Adresse fehlt.")
            elif not secrets.get("sonar_token"):
                self.problems.append("Sonar-Token fehlt.")
            else:
                self.sonar = sonar.Client(self.sc["url"], secrets["sonar_token"], ctx)
        for pr in self.problems:
            log.warning("Konfiguration unvollständig: %s", pr)

    @property
    def configured(self):
        return self.client is not None or self.github is not None

    @staticmethod
    def _scope_key(key, pr, br):
        return "%s|%s|%s" % (key, pr or "", br or "")

    def _sonar_trend(self, key, pr, br, res):
        """Verlauf der Findings eines MR/Branches: aus Sonars eigener Historie (ab zwei Analysen), sonst aus lokalen Schnappschüssen der Gate-Werte.
        Gleichzeitig wird der aktuelle Stand lokal vermerkt (nur bei Änderung)."""
        scope = self._scope_key(key, pr, br)
        vals = res.get("values") or {}
        if vals:
            try:
                self.store.snap_add(scope, vals)
            except Exception as e:      # der Verlauf ist Beiwerk und darf den Abgleich nie stoppen
                slog.warning("Schnappschuss nicht gespeichert: %s", e)
        try:
            pts = self.sonar.history(key, pr=pr, branch=br, metrics=("violations",))
        except sonar.SonarError as e:
            if e.auth:
                raise
            pts = []
        t = sonar.trend_of([(p["ts"], p.get("violations")) for p in pts], "Sonar-Verlauf")
        if t:
            return t
        rows = self.store.snap_rows(scope)
        for metric in ("new_violations", "violations"):
            t = sonar.trend_of([(ts, v.get(metric)) for ts, v in rows], "lokal beobachtet")
            if t:
                return t
        return None

    def sonar_report(self, project_id, iid=None, branch=None):
        """Findings eines MR oder Branches als Markdown für die Zwischenablage (nur lesend, auf Knopfdruck, nicht im Abgleich)."""
        if not self.sonar:
            raise UserError("Sonar ist nicht eingeschaltet oder es fehlt der Token (Einstellungen → Sonar).")
        p = self.proj_cfg.get(project_id)
        key = (p or {}).get("sonar_key") or ("dlp-core" if self.demo and project_id == 1 else "dlp-ui" if self.demo and project_id == 2 else "")
        if not key:
            raise UserError("Für dieses Projekt ist kein Sonar-Schlüssel eingetragen (Einstellungen → GitLab).")
        pr = int(iid) if iid else None
        br = None if pr else (str(branch or "").strip() or None)
        if not pr and not br:
            raise UserError("MR oder Branch fehlt.")
        limit = int(self.sc["report_max"])
        try:
            gate = self.sonar.gate(key, pr=pr, branch=br)
            issues, total, facets = self.sonar.issues(key, pr=pr, branch=br, limit=limit)
            hot = self.sonar.hotspots(key, pr=pr, branch=br)
            pts = self.sonar.history(key, pr=pr, branch=br, metrics=tuple(k for k, _ in sonar.HIST_COLS), limit=12)
        except sonar.SonarError as e:
            slog.warning("Report: %s", e)
            raise UserError(str(e))
        title = "%s, %s" % ((p or {}).get("name") or key, ("MR !%d" % pr) if pr else "Branch %s" % br)
        slog.info("Report erzeugt: %s (%d von %d Findings)", title, len(issues), total)
        hist = {"source": "Sonar-Verlauf", "cols": sonar.HIST_COLS, "rows": pts} if len(pts) > 1 else None
        if not hist:
            snaps = self.store.snap_rows(self._scope_key(key, pr, br), 12)
            if len(snaps) > 1:
                hist = {"source": "lokal beobachtet", "rows": [dict(v, ts=ts) for ts, v in snaps],
                        "cols": (("new_violations", "Neue Findings"), ("new_coverage", "Abdeckung neuer Code %"), ("new_duplicated_lines_density", "Duplikate neuer Code %"))}
        text = sonar.format_report(title, gate, key, issues, total, facets, hot, gate.get("issues_url") or gate.get("url"), limit, hist)
        return {"text": text, "issues": len(issues), "total": total, "hotspots": len(hot[0]) if hot else 0, "truncated": total > len(issues)}

    def usage_providers(self):
        return [k for k in ("claude", "codex", "mistral") if self.uc.get(k)]

    def usage_view(self, fresh=False):
        """Rest-Kontingent der Abos. Claude und Codex werden abgefragt und zwischengespeichert, jeder einzeln (ein Fehler stoppt den
        anderen nicht). Mistral kommt aus dem zuletzt per Lesezeichen gesendeten Stand und kostet keine Anfrage."""
        prov = self.usage_providers()
        if not prov:
            return {"enabled": False, "items": [], "fetched": 0}
        remote = [k for k in prov if k != "mistral"]
        with self._usage_lock:
            c = self._usage_cache
            if not (c and not fresh and time.time() - c["fetched"] < float(self.uc["cache_seconds"]) and c["kinds"] == remote):
                now = time.time()
                if self.demo:
                    demo = [{"id": "claude", "name": "Claude", "ok": True, "error": "", "fetched": now, "windows": [
                                {"label": "5 h", "used_pct": 62.0, "left_pct": 38.0, "resets_at": now + 5400, "secs_left": 5400},
                                {"label": "Woche", "used_pct": 41.0, "left_pct": 59.0, "resets_at": now + 3 * 86400, "secs_left": 3 * 86400}]},
                            {"id": "codex", "name": "Codex (ChatGPT)", "ok": False, "fetched": now, "windows": [],
                             "error": "Anmeldedatei nicht gefunden (~/.codex/auth.json). Im Container: Datei als Volume einhängen."}]
                    items = [i for i in demo if i["id"] in remote]
                else:
                    items = []
                    for k in remote:
                        r = usage.fetch(k, self.uc.get(k + "_file") or None)
                        if not r["ok"]:
                            slog_u.warning("%s: %s", r["name"], r["error"])
                        items.append(r)
                c = self._usage_cache = {"enabled": True, "items": items, "fetched": now, "kinds": list(remote)}
            out = list(c["items"])
        if "mistral" in prov:
            if self.demo:
                now = time.time()
                out.append(usage.mistral_item({"pushed": now - 600, "budgets": {
                    "vibe": {"pct": 0.06, "budget": 300.0, "cur": "USD", "reset": now + 26 * 86400},
                    "api": {"pct": 0.159, "budget": 30.0, "cur": "USD", "reset": now + 26 * 86400}}}))
            else:
                out.append(usage.mistral_item(usage.load_push(data_dir(self.cfg))))
        return {"enabled": True, "items": out, "fetched": c["fetched"]}

    def usage_push(self, body):
        """Stand von Mistral aus dem Lesezeichen. Enthält nur Prozent, Budget und Reset, nie Cookies."""
        if not self.uc.get("mistral"):
            raise UserError("Mistral ist in den Einstellungen (KI-Kontingent) nicht eingeschaltet.")
        try:
            clean = usage.clean_push(body)
        except usage.UsageError as e:
            raise UserError(str(e))
        usage.save_push(data_dir(self.cfg), clean)
        slog_u.info("Mistral-Stand empfangen: %s", ", ".join("%s %.2f %%" % (k, v["pct"]) for k, v in clean.items()))
        return {"ok": True, "item": usage.mistral_item(usage.load_push(data_dir(self.cfg)))}

    def has(self, name):
        return feature(self.cfg, name)

    def reload(self):
        """Config und Secrets neu von der Platte lesen (nach dem Speichern)."""
        cfg = load_config(str(self.config_path) if self.config_path.exists() else None)
        secrets = resolve_secrets(cfg, self.demo)
        secrets["access_token"] = self.access_token or secrets.get("access_token", "")
        self.apply(cfg, secrets)
        log.info("Einstellungen neu geladen: GitLab %s, Jira %s, %d Projekt(e)", "ja" if self.client else "nein",
                 "ja" if self.jira else "nein", len(cfg["projects"]))

    def _key_rules(self):
        allowed = list(self.jc.get("project_keys") or [])
        return allowed + [links.LOCAL_PREFIX] if allowed else allowed   # tiny-Tickets (LOC-…) zählen im Branchnamen immer

    def _local_keys(self, data):
        """Ohne Jira: Keys aus Branchnamen und Hand-Verknüpfungen trotzdem setzen, damit tiny-Tickets ihre Branches finden."""
        manual = self.store.links()
        by_key = {t["key"]: self._local_ticket(t) for t in self.store.tasks()}
        self._by_key = by_key
        for it in data["mine"] + data["review"] + data["assigned"]:
            keys = [k for k in extract_keys("%s %s" % (it["branch"], it["title"])) if links.is_local_key(k)]
            m = manual.get(it["ref"])
            it["manual_link"] = m or ""
            it["keys"] = [m] if m else keys
            it["ticket"] = next((by_key[k] for k in it["keys"] if k in by_key), None)
            it["ticket_unknown"] = ""
            it["no_ticket"] = (not it["keys"]) and it["kind"] in ("mr", "branch")
            it["create_url"] = ""

    # -- Jira-Verknüpfung (läuft beim Auffrischen des Caches)
    def _jira_data(self, data, pre=None):
        j = self.jira
        if not j:
            return None
        limit = int(self.jc["story_limit"])
        out = {"enabled": True, "ok": False, "limit": limit, "count": 0, "over": False,
               "stories": [], "url": j.base, "error": ""}
        items = data["mine"] + data["review"] + data["assigned"]
        try:
            inprog = pre() if pre else j.in_progress()
            types = {t.lower() for t in (self.jc.get("wip_issue_types") or [])}
            if types:
                inprog = [i for i in inprog if i["type"].lower() in types]
            allowed = self._key_rules()
            manual = self.store.links()
            for it in items:
                it["keys"] = extract_keys("%s %s" % (it["branch"], it["title"]), allowed)
                m = manual.get(it["ref"])
                it["manual_link"] = m or ""
                if m:
                    it["keys"] = [m]   # eine von Hand gesetzte Verknüpfung gilt vor der Erkennung aus dem Namen
            progress_keys = {i["key"] for i in inprog}
            cand = {k for it in items for k in it["keys"]} | set(self.store.pool_tickets()) | set(self.store.staged_tickets())
            wanted = sorted(k for k in cand if not links.is_local_key(k) and k not in progress_keys)
            known = j.lookup(wanted) if wanted else {}
        except UserError as e:
            jlog.error("Jira-Abfrage fehlgeschlagen: %s", e)
            out["error"] = str(e)
            data["errors"].append("Jira: %s" % e)
            return out
        by_key = {k: dict(v, in_progress=False) for k, v in known.items()}
        by_key.update({i["key"]: dict(i, in_progress=True) for i in inprog})
        by_key.update({t["key"]: self._local_ticket(t) for t in self.store.tasks()})   # Aufgaben ohne Jira-Ticket zählen wie Tickets
        self._by_key = by_key
        over = len(inprog) > limit
        for it in items:
            tk = next((by_key[k] for k in it["keys"] if k in by_key), None)
            it["ticket"] = tk
            it["ticket_unknown"] = it["keys"][0] if (it["keys"] and not tk) else ""
            it["no_ticket"] = (not it["keys"]) and it["kind"] in ("mr", "branch")
            it["create_url"] = j.create_url(it["title"]) if it["no_ticket"] else ""
            it["agent_locked"] = bool(over and not (tk and tk["in_progress"]))
        for s in inprog:
            linked = self._linked(s["key"], items)
            s["items"] = linked
            s["no_mr"] = not any(x["kind"] in ("mr", "assigned") for x in linked)
        sprints = {}
        for t in list(by_key.values()):
            if t.get("sprint") and t["sprint"] not in sprints:
                end = t.get("sprint_end") or ""
                left = None
                if parse_ts(end):
                    left = int((parse_ts(end) - datetime.now(timezone.utc)).total_seconds() // 86400) if parse_ts(end).tzinfo else None
                sprints[t["sprint"]] = {"name": t["sprint"], "end": end, "days_left": left}
        out["sprints"] = list(sprints.values())
        out["only_active"] = bool(self.jc.get("only_active_sprints", True))
        out.update({"ok": True, "count": len(inprog), "over": over, "stories": inprog})
        linked_n = sum(1 for it in items if it.get("ticket"))
        jlog.info("%d Stories in Arbeit (Limit %d)%s; %d von %d Einträgen mit Ticket verknüpft, %d ohne Key, %d Key unbekannt",
                  len(inprog), limit, " → ÜBER DEM LIMIT" if over else "", linked_n, len(items),
                  sum(1 for it in items if it.get("no_ticket")), sum(1 for it in items if it.get("ticket_unknown")))
        for it in items:
            if it.get("ticket_unknown"):
                jlog.debug("Key %s aus %s/%s nicht in Jira gefunden", it["ticket_unknown"], it["project"], it["branch"])
        self.over_limit, self.inprogress_keys = over, progress_keys
        return out

    # -- Synchronisation: läuft im Hintergrund, Teilergebnisse sind sofort sichtbar
    def _step(self, sid, title, status, detail=""):
        now = time.time()
        with self.sync_lock:
            st = next((x for x in self.sync["steps"] if x["id"] == sid), None)
            if st is None:
                st = {"id": sid, "title": title, "status": "wait", "detail": "", "t0": 0.0, "secs": None}
                self.sync["steps"].append(st)
            if status == "run" and not st["t0"]:
                st["t0"] = now
            if status in ("ok", "err") and st["t0"]:
                st["secs"] = round(now - st["t0"], 1)
            st["status"], st["detail"] = status, str(detail)[:120]

    def start_sync(self):
        """Startet eine Synchronisation im Hintergrund, falls nicht schon eine läuft. Gibt True zurück, wenn eine neu begann."""
        with self.sync_lock:
            if self.sync["running"]:
                return False
            self.sync = {"running": True, "steps": [], "started": time.time(), "finished": 0.0, "n": self.sync["n"] + 1}
            self.partial = {"mine": [], "review": [], "assigned": [], "errors": [], "me": ""}
            self.early_stories = None
            t = threading.Thread(target=self._run_sync, name="sync", daemon=True)
            self._sync_thread = t
        t.start()
        return True

    def _run_sync(self):
        data = None
        try:
            data = self._refresh(self.partial, self._step)
        except Exception as e:   # der Hintergrund-Thread darf nie still sterben
            rlog.exception("Synchronisation abgebrochen: %s", e)
            data = {"me": "", "mine": [], "review": [], "assigned": [], "errors": ["Synchronisation abgebrochen: %s" % e], "jira": None}
        finally:
            with self.cache_lock:
                if data is not None:
                    self.cache, self.cache_t = data, time.time()
            with self.sync_lock:
                self.sync["running"] = False
                self.sync["finished"] = time.time()

    def sync_view(self):
        with self.sync_lock:
            sy = self.sync
            steps = sorted((dict(x) for x in sy["steps"]), key=lambda x: {"ji-link": 1, "sonar": 2}.get(x["id"], 0))   # Verknüpfen und Sonar kommen zuletzt
            return {"running": sy["running"], "n": sy["n"], "started": sy["started"], "finished": sy["finished"],
                    "steps": steps, "done": sum(1 for x in steps if x["status"] in ("ok", "err")), "total": len(steps),
                    "secs": round((sy["finished"] or time.time()) - sy["started"], 1) if sy["started"] else 0}

    @staticmethod
    def _local_ticket(t):
        return {"key": t["key"], "summary": t["title"], "status": "", "type": "Aufgabe", "url": "", "sprint": "", "sprint_end": "",
                "in_sprint": None, "in_progress": False, "local": True}

    @staticmethod
    def _linked(key, items):
        """Alle MRs und Branches eines Tickets: ein Ticket kann beliebig viele haben."""
        return [{"project": it["project"], "branch": it["branch"], "iid": it["iid"], "url": it["url"], "kind": it["kind"],
                 "pipeline": it["pipeline"], "project_id": it["project_id"], "manual": bool(it.get("manual_link")),
                 "draft": bool(it.get("draft")), "ref": it.get("ref", ""), "author": it.get("author", ""),
                 "sonar": (it.get("sonar") or {}).get("status", ""), "sonar_detail": (it.get("sonar") or {}).get("detail", ""),
                 "sonar_url": (it.get("sonar") or {}).get("url", ""), "sonar_issues_url": (it.get("sonar") or {}).get("issues_url", ""),
                 "sonar_trend": (it.get("sonar") or {}).get("trend"),
                 "create_mr_url": it.get("create_mr_url", ""), "merge_status": it.get("merge_status", ""), "pipeline_url": it.get("pipeline_url", ""),
                 "ahead": it.get("ahead", 0), "age_days": it.get("age_days", 0), "title": it.get("title", ""), "by_agent": bool(it.get("by_agent")),
                 "reviewers": it.get("reviewers"), "upvotes": it.get("upvotes", 0), "approved": it.get("approved"), "approved_by": it.get("approved_by") or [],
                 "approvals_left": it.get("approvals_left"), "host": it.get("host", "gitlab"), "sha": it.get("sha", ""),
                 "approval_unknown": bool(it.get("approval_unknown")), "outdated": bool(it.get("outdated")),
                 "review_app": it.get("review_app", ""), "review_env": it.get("review_env", ""), "target_branch": it.get("target_branch", ""),
                 "ide": bool(it.get("ide")), "ide_wt": it.get("ide_wt")}
                for it in items if key in it.get("keys", [])]

    def _board(self, data):
        """Board und Jira-Panel aus einer Quelle: jede Aufgabe (Jira-Ticket, lokale Aufgabe, Idee, MR/Branch ohne Ticket) ist eine Karte;
        alles mit demselben Ticket-Key wird zusammengeführt. Läuft bei jeder Anfrage auf dem Zwischenspeicher, damit Verschieben sofort wirkt."""
        stages = self.store.stages()
        items = data["mine"] + data["review"] + data["assigned"]
        j = data.get("jira")
        known = dict(self._by_key)
        for t in self.store.tasks():
            known[t["key"]] = self._local_ticket(t)
        pools, pool_list = {}, []
        for p in self.store.pools():
            for i in p["items"]:
                pools.setdefault(i["value"], []).append({"id": p["id"], "name": p["name"]})
        jira_prog = {st["key"] for st in (j or {}).get("stories", [])}
        mine_keys = {k for it in data["mine"] for k in it.get("keys", [])}
        # auch Keys, die Jira (noch) nicht kennt: sonst verschwände ein eigener MR mit Tippfehler im Key aus Board und Fokus
        keys = set(jira_prog) | set(known) | {k for k in stages if not links.is_ref_key(k)} | set(self.store.pool_tickets()) | mine_keys

        def derive(tk, linked):
            if tk and tk.get("in_progress"):
                return "review" if any(x["kind"] == "mr" and not x["draft"] for x in linked) else "impl"
            return "planned"
        cards = []
        for k in sorted(keys):
            tk = known.get(k)
            if k not in stages and k not in pools and k not in jira_prog and k not in mine_keys and not (tk and tk.get("local")):
                continue   # Tickets nur, wenn sie in Arbeit, im Pool, auf dem Board oder mit eigenem MR/Branch verbunden sind
            linked = self._linked(k, items)
            st = stages.get(k)
            card = {"id": k, "key": k, "title": (tk or {}).get("summary", "") or next((x.get("title", "") for x in linked if x.get("title")), ""), "status": (tk or {}).get("status", ""), "url": (tk or {}).get("url", ""),
                    "local": bool(tk and tk.get("local")), "known": tk is not None, "type": (tk or {}).get("type", ""), "items": linked,
                    "stage": st["stage"] if st else derive(tk, linked), "manual_stage": bool(st), "updated": st["updated"] if st else 0,
                    "pools": pools.get(k, []), "jira_in_progress": k in jira_prog, "sprint": (tk or {}).get("sprint", "")}
            cards.append(card)
        for it in data["mine"]:   # MRs/Branches ohne Ticket: eigene Karten, damit nichts fehlt
            if it["kind"] in ("mr", "branch") and not it.get("keys") and it.get("ref"):
                st = stages.get(it["ref"])
                linked = self._linked_ref(it)
                cards.append({"id": it["ref"], "key": "", "title": it["title"], "status": "", "url": it["url"], "local": False, "known": True, "type": "",
                              "items": [linked], "stage": st["stage"] if st else ("review" if it["kind"] == "mr" and not it.get("draft") else "impl"),
                              "manual_stage": bool(st), "updated": st["updated"] if st else 0, "pools": pools.get(it["ref"], []),
                              "jira_in_progress": False, "sprint": "", "orphan": True})
        if self.ideas is not None and self.has("ideas"):
            for i in self.ideas.list():
                if i["status"] in ("neu", "geparkt") and not i["expired"]:
                    cards.append({"id": "idea:%d" % i["id"], "key": "", "title": i["text"], "status": "", "url": "", "local": True, "known": True, "type": "Idee",
                                  "items": [], "stage": "idea", "manual_stage": True, "updated": 0, "pools": [], "jira_in_progress": False, "sprint": "",
                                  "idea_id": i["id"]})
        done = sorted((c for c in cards if c["stage"] == "done"), key=lambda c: -c["updated"])
        hide = {c["id"] for c in done[12:]}
        shown = [c for c in cards if c["id"] not in hide]
        for p in self.store.pools():
            pool_list.append({"id": p["id"], "name": p["name"], "count": sum(1 for c in cards if any(x["id"] == p["id"] for x in c["pools"]))})
        board = {"cards": shown, "done_hidden": len(hide), "stages": list(links.STAGES), "pools": pool_list}
        if j and j.get("ok") is not None and "stories" in j:
            j = dict(j)
            stories = [dict(st) for st in j["stories"]]
            have = {st["key"] for st in stories}
            for c in cards:
                if c["stage"] in links.PROGRESS and c["key"] and c["key"] not in have:
                    base = dict(known.get(c["key"]) or {"key": c["key"], "summary": "", "status": "", "type": "", "url": ""})
                    base.update(in_progress=True, via_board=True, items=c["items"], no_mr=not any(x["kind"] in ("mr", "assigned") for x in c["items"]))
                    stories.append(base)
            by_id = {c["id"]: c for c in cards}
            for st in stories:
                st["stage"] = (by_id.get(st["key"]) or {}).get("stage", "impl")
            if not j.get("partial"):
                j["stories"], j["count"] = stories, len(stories)
                j["over"] = len(stories) > int(j.get("limit", 2))
                prog_keys = {st["key"] for st in stories}
                for it in items:
                    tk = it.get("ticket")
                    it["agent_locked"] = bool(j["over"] and not (tk and tk["key"] in prog_keys))
                self.over_limit, self.inprogress_keys = j["over"], prog_keys
            data["jira"] = j
        return board

    @staticmethod
    def _linked_ref(it):
        return {"project": it["project"], "branch": it["branch"], "iid": it["iid"], "url": it["url"], "kind": it["kind"], "pipeline": it["pipeline"],
                "project_id": it["project_id"], "manual": False, "draft": bool(it.get("draft")), "ref": it.get("ref", ""), "author": it.get("author", ""),
                "sonar": (it.get("sonar") or {}).get("status", ""), "sonar_detail": (it.get("sonar") or {}).get("detail", ""), "sonar_url": (it.get("sonar") or {}).get("url", ""), "sonar_issues_url": (it.get("sonar") or {}).get("issues_url", ""),
                 "sonar_trend": (it.get("sonar") or {}).get("trend"),
                 "create_mr_url": it.get("create_mr_url", ""), "merge_status": it.get("merge_status", ""), "pipeline_url": it.get("pipeline_url", ""),
                 "ahead": it.get("ahead", 0), "age_days": it.get("age_days", 0), "title": it.get("title", ""), "by_agent": bool(it.get("by_agent")),
                 "reviewers": it.get("reviewers"), "upvotes": it.get("upvotes", 0), "approved": it.get("approved"), "approved_by": it.get("approved_by") or [],
                 "approvals_left": it.get("approvals_left"), "host": it.get("host", "gitlab"), "sha": it.get("sha", ""),
                 "approval_unknown": bool(it.get("approval_unknown")), "outdated": bool(it.get("outdated")),
                 "review_app": it.get("review_app", ""), "review_env": it.get("review_env", ""), "target_branch": it.get("target_branch", ""),
                 "ide": bool(it.get("ide")), "ide_wt": it.get("ide_wt")}

    def board_action(self, action, body):
        tgt = str(body.get("key") or body.get("ref") or ("idea:%s" % body["id"] if action == "plan_idea" and body.get("id") else "") or "")
        det = {k: body.get(k) for k in ("stage", "pool_id", "title") if body.get(k) not in (None, "")}
        return self._audited("board." + action, tgt, lambda: self._board_action(action, body),
                             target_of=lambda r: (r or {}).get("key") if isinstance(r, dict) else None, **det)

    def _board_action(self, action, body):
        st = self.store
        if action == "stage":
            key = body.get("key") or body.get("ref")
            if str(key or "").startswith("idea:"):
                raise UserError("Ideen werden mit «Planen» übernommen.")
            if key and not links.is_ref_key(key):
                key = self._local(links.norm_ticket, key)
                self._check_ticket_exists(key)
                if not links.is_local_key(key):
                    self._learn(key)
            key = self._local(st.stage_set, key, body.get("stage"))
            if body.get("stage") in ("tested", "done"):
                self._accept(key, body.get("note"), body.get("env"))
            if body.get("stage") == "done":
                self._ide_cleanup(key)
            return {"key": key}
        if action == "add":
            title = str(body.get("title") or "").strip()
            stage = body.get("stage") or "planned"
            if re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{1,19}-\d{1,9}", title):   # ein Jira-Key: Ticket aufs Board holen
                key = self._local(links.norm_ticket, title)
                self._check_ticket_exists(key)
                self._learn(key)
                return {"key": self._local(st.stage_set, key, stage)}
            self.cache_t = 0.0
            return {"key": self._local(st.task_add, title, stage, self._pool_id(body.get("pool_id")))}
        if action == "remove":
            key = str(body.get("key") or "")
            if links.is_local_key(key):
                self._local(st.task_delete, key)
            else:
                st.stage_clear(key)
            self.cache_t = 0.0
            return {}
        if action == "plan_idea":
            if not (self.ideas and self.has("ideas")):
                raise UserError("Die Ideenbox ist ausgeschaltet.")
            iid = int(body.get("id"))
            idea = next((i for i in self.ideas.list() if i["id"] == iid), None)
            if not idea:
                raise UserError("Idee nicht gefunden.")
            if not self._pool_id(body.get("pool_id")):
                raise UserError("Eine Idee braucht eine Kategorie (Pool), bevor sie geplant wird.")
            key = self._local(st.task_add, idea["text"].split("\n")[0][:200], body.get("stage") or "planned", self._pool_id(body.get("pool_id")))
            self.ideas.set_status(iid, "erledigt")
            self.cache_t = 0.0
            return {"key": key}
        if action in ("assign", "unassign"):
            key = body.get("key") or body.get("ref")
            pid = self._pool_id(body.get("pool_id"))
            if not pid:
                raise UserError("Kategorie fehlt.")
            kind = "ref" if links.is_ref_key(key) else "ticket"
            if kind == "ticket":
                key = self._local(links.norm_ticket, key)
                self._check_ticket_exists(key)
                if not links.is_local_key(key):
                    self._learn(key)
            if action == "assign":
                self._local(st.add_item, pid, kind, key)
            else:
                stage = (st.stages().get(key) or {}).get("stage", "")
                if kind == "ticket" and links.is_local_key(key) and stage not in ("", "idea") and len(st.pools_of(key)) <= 1:
                    raise UserError("%s braucht eine Kategorie. Erst in eine andere Kategorie legen oder zurück in den Ideenpool schieben." % key)
                st.remove_item(pid, kind, key)
            self.cache_t = 0.0
            return {}
        raise UserError("Unbekannte Aktion.")

    @staticmethod
    def _pool_id(v):
        try:
            return int(v) if v not in (None, "", 0, "0") else None
        except (TypeError, ValueError):
            raise UserError("Ungültige Kategorie.")

    def _learn(self, key):
        """Ein frisch aufs Board geholtes Jira-Ticket sofort bekannt machen, ohne auf den nächsten Abgleich zu warten."""
        if self.jira and key not in self._by_key:
            try:
                self._by_key.update({k: dict(v, in_progress=False) for k, v in self.jira.lookup([key]).items()})
            except UserError:
                pass
        self.cache_t = 0.0

    def _refresh(self, sink=None, step=None):
        t0 = time.time()
        step = step or (lambda *a, **k: None)
        self.refresh_no = getattr(self, "refresh_no", 0) + 1
        rlog.info("Auffrischen #%d beginnt", self.refresh_no)
        pre_holder = {}
        pre_thread = None
        if self.jira:
            step("ji-stories", "Jira: Stories in Arbeit", "run")

            def early():
                try:
                    r = self.jira.in_progress()
                    pre_holder["v"] = r
                    self.early_stories = r
                    step("ji-stories", "Jira: Stories in Arbeit", "ok", "%d Tickets" % len(r))
                except UserError as e:
                    pre_holder["e"] = e
                    step("ji-stories", "Jira: Stories in Arbeit", "err", str(e))
            pre_thread = threading.Thread(target=early, daemon=True)
            pre_thread.start()
            step("ji-link", "Tickets mit Branches verknüpfen", "wait")
        if self.sonar:
            step("sonar", "Sonar: Quality Gates", "wait")

        def pre():
            pre_thread.join()
            if "e" in pre_holder:
                raise pre_holder["e"]
            return pre_holder["v"]
        try:
            if self.client is None:
                data = sink if sink is not None else {}
                data.update(me=data.get("me", ""), errors=data.get("errors", []))
                for k in ("mine", "review", "assigned"):
                    data.setdefault(k, [])
            else:
                data = self.client.fetch(sink, step)
        except UserError as e:
            rlog.error("GitLab-Abfrage fehlgeschlagen: %s", e)
            step("gl-user", "Bei GitLab anmelden", "err", str(e))
            data = sink if sink is not None else {}
            data.setdefault("me", "")
            for k in ("mine", "review", "assigned"):
                data.setdefault(k, [])
            data.setdefault("errors", []).append(str(e))
            data["gl_failed_all"] = True
        gl_err = bool(data.get("gl_failed_all") or data.get("gl_failed_pids")) or any(not str(x).startswith("GitHub") for x in data.get("errors", []))
        n_err = len(data.get("errors", []))
        if self.github:
            self._github_fetch(data, step)
        gh_err = bool(data.get("gh_failed_all") or data.get("gh_failed_repos")) or len(data.get("errors", [])) > n_err
        self._keep_last_good(data)
        for it in data["mine"] + data["review"] + data["assigned"]:
            it["ref"] = links.ref_of(it["project_id"], it["branch"])
        if not self.jira:
            self._local_keys(data)
        if self.jira:
            step("ji-link", "Tickets mit Branches verknüpfen", "run")
            data["jira"] = self._jira_data(data, pre)
            j = data["jira"]
            step("ji-link", "Tickets mit Branches verknüpfen", "err" if not j["ok"] else "ok", j.get("error", "") if not j["ok"] else "")
            if not j["ok"]:
                self._by_key = {}
        else:
            data["jira"] = None
        data["sonar"] = self._sonar(data, step)
        now = time.time()
        src = []
        if self.client is not None:
            src.append(("gitlab", "GitLab", not gl_err))
        if self.github is not None:
            src.append(("github", "GitHub", not gh_err))
        if self.jira:
            src.append(("jira", "Jira", bool((data.get("jira") or {}).get("ok"))))
        if self.sonar:
            src.append(("sonar", "Sonar", bool((data.get("sonar") or {}).get("ok", True))))
        data["sources"] = []
        for sid, name, ok in src:
            if ok:
                self._src_ok[sid] = now
            data["sources"].append({"id": sid, "name": name, "ok": ok, "ts": now, "last_ok": self._src_ok.get(sid, 0)})
        rlog.info("Auffrischen #%d fertig in %.1f s: %d eigene Einträge, %d Review, %d zugeteilt, %d Fehler",
                  self.refresh_no, time.time() - t0, len(data["mine"]), len(data["review"]), len(data["assigned"]),
                  len(data["errors"]))
        return data

    def _keep_last_good(self, data):
        """Fällt eine Quelle (ganz oder je Projekt/Repo) aus, bleiben ihre letzten Einträge stehen, als «veraltet» markiert (outdated),
        statt aus Board und Fokus zu verschwinden."""
        prev = self.cache
        if not prev:
            return
        gl_all, gl_pids = data.get("gl_failed_all"), set(data.get("gl_failed_pids") or [])
        gh_all, gh_repos = data.get("gh_failed_all"), set(data.get("gh_failed_repos") or [])
        if not (gl_all or gl_pids or gh_all or gh_repos):
            return
        kept = 0
        for lst in ("mine", "review", "assigned"):
            have = {links.ref_of(i["project_id"], i["branch"]) for i in data.get(lst, [])}
            for it in prev.get(lst, []):
                gh = it.get("host") == "github"
                hit = (gh and (gh_all or it.get("project") in gh_repos)) or (not gh and (gl_all or (lst == "mine" and it.get("project_id") in gl_pids)))
                ref = links.ref_of(it["project_id"], it["branch"])
                if hit and ref not in have:
                    x = dict(it, outdated=True, outdated_since=it.get("outdated_since") or self.cache_t or time.time())
                    data.setdefault(lst, []).append(x)
                    have.add(ref)
                    kept += 1
        if kept:
            rlog.warning("%d Einträge aus dem letzten erfolgreichen Abgleich behalten (als veraltet markiert)", kept)

    def _github_fetch(self, data, step):
        bf = branch_cfg(self.cfg)
        ign = list(bf.get("ignore_branches") or [])
        ident = identity(self.cfg, {})
        repos = [r["full"] for r in self.ghc["repos"] if r.get("full")]
        self.github.fetch(repos, ident, classify_commits, bf, lambda b: ignored_branch(b, ign), data, step)

    def _sonar(self, data, step):
        """Quality Gate jedes MR und Branches (nur lesend). Ergebnisse stehen danach in it["sonar"]; ein einzelner Fehler stoppt nichts,
        falsche Zugangsdaten brechen ab, weil alle weiteren Abfragen dasselbe Ergebnis hätten."""
        if not self.sonar:
            return None
        title = "Sonar: Quality Gates"
        step("sonar", title, "run")
        keys = {pid: p.get("sonar_key") for pid, p in self.proj_cfg.items() if p.get("sonar_key")}
        if self.demo:
            keys = {pid: p.get("sonar_key") or p.get("name", str(pid)) for pid, p in self.proj_cfg.items()}
            keys.update({1: "dlp-core", 2: "dlp-ui"})
        cand = [it for lst in ("mine", "assigned", "review") for it in data[lst] if keys.get(it["project_id"]) and (it.get("iid") or it["kind"] == "branch")]
        out = {"enabled": True, "ok": True, "error": "", "checked": 0, "red": 0, "warn": 0, "none": 0, "failed": 0, "skipped": max(0, len(cand) - int(self.sc["max_items"]))}
        cand = cand[:int(self.sc["max_items"])]
        if not cand:
            step("sonar", title, "ok", "keine MRs/Branches mit Sonar-Schlüssel" if not keys else "nichts zu prüfen")
            return out
        now, ttl = time.time(), float(self.sc["cache_seconds"])
        stop = threading.Event()

        def one(it):
            if stop.is_set():
                return
            key = keys[it["project_id"]]
            pr = it["iid"] if it.get("iid") else None
            br = None if pr else it["branch"]
            hit = self._sonar_cache.get((key, pr, br))
            if hit and now - hit[0] < ttl:
                it["sonar"] = hit[1]
                return
            try:
                res = self.sonar.gate(key, pr=pr, branch=br)
                if res["status"] in ("OK", "WARN", "ERROR"):
                    res["trend"] = self._sonar_trend(key, pr, br, res)
            except sonar.SonarError as e:
                if e.auth:
                    out["ok"], out["error"] = False, str(e)
                    stop.set()
                    return
                it["sonar"] = {"status": "UNKNOWN", "failed": [], "url": "", "detail": str(e)}
                out["failed"] += 1
                return
            self._sonar_cache[(key, pr, br)] = (time.time(), res)
            it["sonar"] = res
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=3) as pool:
            list(pool.map(one, cand))
        for it in cand:
            s = (it.get("sonar") or {}).get("status")
            if s:
                out["checked"] += 1
                out["red"] += s == "ERROR"
                out["warn"] += s == "WARN"
                out["none"] += s == "NONE"
        if not out["ok"]:
            step("sonar", title, "err", out["error"])
            slog.error("%s", out["error"])
            data["errors"].append(out["error"])
        else:
            detail = "%d geprüft, %d nicht bestanden%s" % (out["checked"], out["red"], ", %d Fehler" % out["failed"] if out["failed"] else "")
            if out["skipped"]:
                detail += ", %d übersprungen (Limit %d)" % (out["skipped"], int(self.sc["max_items"]))
            step("sonar", title, "err" if out["failed"] and not out["checked"] else "ok", detail)
            slog.info("%s", detail)
        return out

    def _partial_view(self):
        """Zwischenstand während der ersten Synchronisation: schon geladene Listen, Jira-Stories ohne Zuordnung."""
        p = self.partial or {}
        data = {"me": p.get("me", ""), "mine": [dict(i) for i in p.get("mine", [])], "review": [dict(i) for i in p.get("review", [])],
                "assigned": [dict(i) for i in p.get("assigned", [])], "errors": list(p.get("errors", [])), "partial": True}
        for it in data["mine"] + data["review"] + data["assigned"]:
            it["ref"] = links.ref_of(it["project_id"], it["branch"])
            it["keys"] = extract_keys("%s %s" % (it["branch"], it["title"]), self._key_rules()) if self.jira else []
        if self.jira:
            st = self.early_stories
            data["jira"] = {"enabled": True, "ok": st is not None, "loading": st is None, "partial": True, "limit": int(self.jc["story_limit"]),
                            "count": len(st or []), "over": False, "url": self.jira.base, "error": "", "sprints": [],
                            "only_active": bool(self.jc.get("only_active_sprints", True)),
                            "stories": [dict(x, items=[], no_mr=False, in_progress=True) for x in (st or [])]}
        else:
            data["jira"] = None
        data["sonar"] = {"enabled": True, "ok": True, "loading": True} if self.sonar else None
        return data

    def helpdesk(self):
        if not self.jira or not (self.jc.get("helpdesk") or {}).get("jql"):
            return None   # ohne eigene JQL aus (Standard)
        ttl = float((self.jc.get("helpdesk") or {}).get("cache_minutes", 30)) * 60
        with self.hd_lock:
            if time.time() - self.hd_t > ttl:
                try:
                    self.hd_cache = self.jira.helpdesk()
                except UserError as e:
                    self.hd_cache = {"error": str(e)}
                self.hd_t = time.time()
            return self.hd_cache

    # -- Verknüpfungen und Pools (nur lokal gespeichert)
    def _local(self, fn, *a):
        try:
            return fn(*a)
        except links.LinkError as e:
            raise UserError(str(e))

    def _check_ticket_exists(self, key):
        if links.is_local_key(key):
            if key not in {t["key"] for t in self.store.tasks()}:
                raise UserError("Die Aufgabe %s gibt es nicht." % key)
            return
        if self.jira:
            try:
                if key not in self.jira.lookup([key]):
                    raise UserError("Das Ticket %s gibt es in Jira nicht (oder du darfst es nicht sehen)." % key)
            except HttpStatus as e:
                raise UserError("Jira konnte %s nicht prüfen: %s" % (key, e))

    def _ref(self, body):
        try:
            return int(body.get("project_id")), str(body.get("branch") or "")
        except (TypeError, ValueError):
            raise UserError("project_id muss eine Zahl sein.")

    def link_ticket(self, body):
        return self._audited("link.set", "%s:%s" % (body.get("project_id"), body.get("branch")), lambda: self._link_ticket(body), ticket=body.get("ticket"))

    def unlink_ticket(self, body):
        return self._audited("link.delete", "%s:%s" % (body.get("project_id"), body.get("branch")), lambda: self._unlink_ticket(body))

    def _link_ticket(self, body):
        pid, branch = self._ref(body)
        key = self._local(links.norm_ticket, body.get("ticket"))
        self._check_ticket_exists(key)
        self._local(self.store.link, pid, branch, key)
        log.info("Verknüpfung gesetzt: %s:%s → %s", pid, branch, key)
        self.cache_t = 0.0
        return {"ticket": key}

    def _unlink_ticket(self, body):
        pid, branch = self._ref(body)
        removed = self._local(self.store.unlink, pid, branch)
        log.info("Verknüpfung gelöst: %s:%s", pid, branch)
        self.cache_t = 0.0
        return {"removed": removed}

    def pool_action(self, action, body):
        det = {k: body.get(k) for k in ("id", "name") if body.get(k) not in (None, "")}
        return self._audited("pool." + action, "pool:%s" % (body.get("id") or body.get("name") or ""), lambda: self._pool_action(action, body),
                             target_of=lambda r: "pool:%s" % r["id"] if isinstance(r, dict) and r.get("id") else None, **det)

    def _pool_action(self, action, body):
        st = self.store
        if action == "create":
            return {"id": self._local(st.add_pool, body.get("name"))}
        if action == "rename":
            self._local(st.rename_pool, body.get("id"), body.get("name"))
            return {}
        if action == "delete":
            self._local(st.delete_pool, body.get("id"))
            return {}
        if action in ("add", "remove"):
            kind = body.get("kind")
            value = body.get("value")
            if kind == "ref":
                pid, branch = self._ref(body)
                value = links.ref_of(pid, branch)
            if action == "add":
                if kind == "ticket":
                    value = self._local(links.norm_ticket, value)
                    self._check_ticket_exists(value)
                value = self._local(st.add_item, body.get("id"), kind, value)
                if kind == "ticket":
                    self.cache_t = 0.0   # Jira-Daten des Tickets beim nächsten Abruf holen
                return {"value": value}
            return {"removed": self._local(st.remove_item, body.get("id"), kind, value)}
        raise UserError("Unbekannte Aktion.")

    def ai_action(self, action, body):
        st = self.store
        if action == "save":
            return {"id": self._local(st.ai_save, body.get("id"), body.get("name"), body.get("kind"), body.get("window_hours"),
                                      body.get("budget"), body.get("unit"))}
        if action == "delete":
            self._local(st.ai_delete, body.get("id"))
            return {}
        if action == "set":
            self._local(st.ai_set, body.get("id"), body.get("used"), body.get("resets_in_min"), body.get("delta"))
            return {}
        raise UserError("Unbekannte Aktion.")

    def pools_view(self, data):
        items = {it["ref"]: it for it in data["mine"] + data["review"] + data["assigned"] if it.get("ref")}
        out = []
        for p in self.store.pools():
            tickets, refs = [], []
            for i in p["items"]:
                if i["kind"] == "ticket":
                    t = self._by_key.get(i["value"])
                    tickets.append(dict(t, known=True) if t else {"key": i["value"], "summary": "", "status": "", "url": (self.jira.base + "/browse/" + i["value"]) if self.jira else "", "known": False})
                else:
                    it = items.get(i["value"])
                    if it:
                        refs.append({"ref": i["value"], "missing": False, "project_id": it["project_id"], "branch": it["branch"], "title": it["title"], "kind": it["kind"],
                                     "iid": it["iid"], "url": it["url"], "project": it["project"], "pipeline": it["pipeline"], "draft": it["draft"]})
                    else:
                        pid, _, br = i["value"].partition(":")
                        refs.append({"ref": i["value"], "missing": True, "project_id": int(pid), "branch": br, "title": br, "kind": "branch", "iid": None,
                                     "url": "", "project": self.proj_cfg.get(int(pid), {}).get("name", "Projekt %s" % pid), "pipeline": "none", "draft": False})
            out.append({"id": p["id"], "name": p["name"], "tickets": tickets, "refs": refs})
        return out

    # -- Tickets anlegen (Schreibzugriff: nur auf ausdrückliche Aktion, nur mit jira.allow_create)
    def ticket_meta(self):
        return {"can_create": bool(self.jira and self.jc.get("allow_create")), "jira": bool(self.jira),
                "llm": llm.ready(self.lc), "llm_label": llm.PROVIDERS[self.lc["provider"]].label if self.lc.get("provider") in llm.PROVIDERS else "",
                "projects": list(self.jc.get("project_keys") or []), "default_type": self.jc.get("create_type") or "Story"}

    def _types(self, project_key):
        if project_key not in self._types_cache:
            try:
                self._types_cache[project_key] = self.jira.issue_types(project_key) if self.jira else []
            except UserError as e:
                jlog.warning("Vorgangstypen für %s nicht lesbar: %s", project_key, e)
                return [self.jc.get("create_type") or "Story"]
        return self._types_cache[project_key] or [self.jc.get("create_type") or "Story"]

    def ticket_draft(self, body):
        if body.get("idea_id") not in (None, ""):
            return self._idea_draft(body)
        if not self.client:
            raise UserError("GitLab ist nicht verbunden.")
        try:
            pid = int(body.get("project_id"))
            iid = int(body["iid"]) if body.get("iid") not in (None, "") else None
        except (TypeError, ValueError):
            raise UserError("project_id und iid müssen Zahlen sein.")
        branch = str(body.get("branch") or "")[:250]
        meta = self.ticket_meta()
        project = str(body.get("project") or (meta["projects"][0] if meta["projects"] else "")).upper()
        ctx = self.client.ticket_context(pid, iid, branch)
        ctx["issue_types"] = self._types(project) if project else [meta["default_type"]]
        out = {"meta": meta, "project": project, "issue_types": ctx["issue_types"], "source": "vorlage", "warning": "",
               "draft": llm.template_draft(ctx)}
        if body.get("use_llm"):
            if not llm.ready(self.lc):
                raise UserError("Die KI ist nicht eingerichtet (Einstellungen → KI-Entwurf).")
            t0 = time.time()
            try:
                out["draft"] = llm.draft_ticket(self.lc, self.llm_key, ctx, str(body.get("hint") or ""))
                out["source"] = "ki"
                try:
                    if self.has("ai"):
                        self.store.ai_bump("local")   # Zähler der eigenen Anfragen an das lokale Modell
                except Exception as e:
                    log.debug("Zähler nicht aktualisiert: %s", e)
                log.info("KI-Entwurf von %s (%s) in %.1f s, %d Commit-Titel gesendet", self.lc["provider"], self.lc.get("model") or "-",
                         time.time() - t0, len(ctx["commits"]))
            except llm.LlmError as e:
                log.warning("KI-Entwurf fehlgeschlagen: %s", e)
                out["warning"] = "Die KI hat nicht geliefert (%s). Hier die Vorlage." % e
        if not out["draft"]["issue_type"] or out["draft"]["issue_type"] not in ctx["issue_types"]:
            dt = meta["default_type"]
            out["draft"]["issue_type"] = dt if dt in ctx["issue_types"] else ctx["issue_types"][0]
        return out

    def ticket_create(self, body):
        if not self.jira:
            raise UserError("Jira ist nicht verbunden.")
        if not self.jc.get("allow_create"):
            raise UserError("Das Anlegen von Tickets ist ausgeschaltet (Einstellungen → Jira → «Tickets aus dem Panel anlegen»).")
        keys = self.jc.get("project_keys") or []
        project = str(body.get("project") or "").strip().upper()
        if not project or (keys and project not in keys) or not settings.KEY_RE.match(project):
            raise UserError("Projekt-Key «%s» ist nicht erlaubt (erlaubt: %s)." % (project, ", ".join(keys) or "gültiger Key"))
        summary = " ".join(str(body.get("summary") or "").split())
        description = str(body.get("description") or "").strip()
        if not summary or len(summary) > 255:
            raise UserError("Der Titel fehlt oder ist länger als 255 Zeichen.")
        if len(description) > 30000:
            raise UserError("Die Beschreibung ist zu lang.")
        itype = str(body.get("issue_type") or "").strip()
        types = self._types(project)
        if itype not in types:
            raise UserError("Vorgangstyp «%s» gibt es in %s nicht (vorhanden: %s)." % (itype, project, ", ".join(types)))
        if not body.get("force"):
            for r in self.audit_log.rows(action="jira.create", since=time.time() - 600, limit=50):
                d = r["detail"]
                if r["ok"] and d.get("project") == project and (d.get("summary") or "").lower() == summary.lower():
                    err = UserError("Dasselbe Ticket hast du vor %d min schon angelegt: %s." % (max(1, int((time.time() - r["ts"]) // 60)), r["target"]))
                    err.data = {"duplicate": r["target"], "url": "%s/browse/%s" % (self.jc["url"].rstrip("/"), r["target"]) if self.jc.get("url") else ""}
                    raise err
        try:
            res = self.jira.create_issue(project, itype, summary, description)
        except UserError as e:
            self.audit("jira.create", project, ok=False, project=project, summary=summary, issue_type=itype, error=str(e)[:300])
            raise
        self.audit("jira.create", res["key"], project=project, summary=summary, issue_type=itype, description_chars=len(description), forced=bool(body.get("force")))
        jlog.info("Ticket %s angelegt (%s, %d Zeichen Beschreibung)", res["key"], itype, len(description))
        self.cache_t = 0.0   # beim nächsten Abruf neu lesen
        if body.get("idea_id") not in (None, ""):
            res["checks"] = self._idea_done(body, res["key"], summary, description)
        return res

    # -- Ideen (0.20): bewerten, als Ticket ausformulieren
    def _idea(self, iid):
        if not (self.ideas and self.has("ideas")):
            raise UserError("Die Ideenbox ist ausgeschaltet.")
        try:
            idea = self.ideas.get(int(iid))
        except (TypeError, ValueError):
            idea = None
        if not idea:
            raise UserError("Diese Idee gibt es nicht (mehr).")
        return idea

    def idea_assess(self, iid, b):
        """Bewertung an der Idee speichern: vom lokalen Modell oder von dir. Ähnliche Ideen und Vorhaben findet tinyops selbst (ohne Modell)."""
        idea = self._idea(iid)
        others = [i for i in self.ideas.list() if i["id"] != idea["id"] and i["status"] in ("neu", "geparkt") and not i["expired"]]
        tasks = [(cid, c.get("title") or "") for cid, c in (self._cards or {}).items() if not c.get("idea_id")]
        sim = similar(idea["text"], [("#%d" % o["id"], o["text"]) for o in others] + tasks)
        if b.get("manual"):
            a = {"category": b.get("category") if b.get("category") in llm.CATEGORIES else "",
                 "benefit": int(b.get("benefit")) if str(b.get("benefit")) in ("1", "2", "3") else 0,
                 "effort": b.get("effort") if b.get("effort") in llm.EFFORTS else "",
                 "effort_why": str(b.get("effort_why") or "")[:300], "duplicates": [],
                 "recommendation": b.get("recommendation") if b.get("recommendation") in llm.RECOMMEND else "", "why": str(b.get("why") or "")[:500]}
            if not a["recommendation"]:
                raise UserError("Empfehlung fehlt (jetzt, später oder verwerfen).")
            a["source"] = "du"
        else:
            if not llm.ready(self.lc):
                raise UserError("Die KI ist nicht eingerichtet (Einstellungen → KI-Entwurf). Du kannst die Idee auch selbst bewerten.")
            try:
                a = llm.assess_idea(self.lc, self.llm_key, idea, others, [t for _, t in tasks], self.ssl_ctx)
            except llm.LlmError as e:
                self.audit("idea.assess", "idea:%d" % idea["id"], ok=False, error=str(e)[:300])
                raise UserError("Bewertung fehlgeschlagen: %s" % e)
            a["source"] = "modell"
            a["model"] = self.lc.get("model") or self.lc.get("provider")
        a["similar"] = sim
        a["ts"] = time.time()
        self.ideas.set_field(idea["id"], assessment=a)
        self.audit("idea.assess", "idea:%d" % idea["id"], source=a["source"], recommendation=a["recommendation"], benefit=a["benefit"],
                   effort=a["effort"], category=a["category"], similar=[x["id"] for x in sim][:5])
        return a

    def _idea_draft(self, body):
        idea = self._idea(body.get("idea_id"))
        meta = self.ticket_meta()
        project = str(body.get("project") or (meta["projects"][0] if meta["projects"] else "")).upper()
        types = self._types(project) if project and self.jira else [meta["default_type"]]
        ctx = {"idea_id": idea["id"], "idea_text": idea["text"], "assessment": idea.get("assessment"), "issue_types": types}
        out = {"meta": meta, "project": project, "issue_types": types, "source": "vorlage", "warning": "", "draft": llm.template_from_idea(ctx),
               "idea": {"id": idea["id"], "text": idea["text"]}}
        if body.get("use_llm"):
            if not llm.ready(self.lc):
                raise UserError("Die KI ist nicht eingerichtet (Einstellungen → KI-Entwurf).")
            try:
                out["draft"] = llm.draft_from_idea(self.lc, self.llm_key, ctx, str(body.get("hint") or ""), self.ssl_ctx)
                out["source"] = "ki"
            except llm.LlmError as e:
                out["warning"] = "Die KI hat nicht geliefert (%s). Hier die Vorlage." % e
        if not out["draft"]["issue_type"] or out["draft"]["issue_type"] not in types:
            dt = meta["default_type"]
            out["draft"]["issue_type"] = dt if dt in types else types[0]
        out["acceptance"] = llm.acceptance_items(out["draft"]["description"])
        return out

    def _idea_done(self, body, key, summary, description):
        """Idee erledigt, Ticket an der Idee vermerken, auf Wunsch Akzeptanzkriterien als Teilschritte."""
        iid = int(body.get("idea_id"))
        self.ideas.set_field(iid, status="erledigt", ticket=key, draft={"summary": summary, "description": description[:30000]})
        n = 0
        if body.get("checklist", True):
            for t in llm.acceptance_items(description):
                try:
                    self.store.check_add(key, t)
                    n += 1
                except links.LinkError:
                    break
        self.audit("idea.ticket", "idea:%d" % iid, ticket=key, checks=n, kind="tiny" if links.is_local_key(key) else "jira")
        return n

    def idea_tiny(self, iid, b):
        """tiny-Ticket aus der Idee: lokale Aufgabe mit dem Titel des Entwurfs; Akzeptanzkriterien werden Teilschritte."""
        idea = self._idea(iid)
        summary = " ".join(str(b.get("summary") or idea["text"].splitlines()[0]).split())[:200]
        pool = self._pool_id(b.get("pool_id"))
        key = self.board_action("add", {"title": summary, "stage": "planned" if pool else "idea", "pool_id": pool})["key"]
        n = self._idea_done(dict(b, idea_id=idea["id"]), key, summary, str(b.get("description") or ""))
        self.cache_t = 0.0
        return {"key": key, "checks": n}

    # -- IntelliJ auf dem MR-Commit (0.20)
    def _repo_of(self, host, pid):
        if host == "github":
            r = next((x for x in (self.ghc.get("repos") or []) if github.pid_of(x.get("id") or 0) == pid), None)
        else:
            r = self.proj_cfg.get(pid)
        path = (r or {}).get("repo_path") or ""
        return str(Path(path).expanduser()) if path else ""

    def _git(self, repo, *args, timeout=60):
        try:
            r = subprocess.run(["git", "-C", repo] + list(args), capture_output=True, text=True, timeout=timeout)
        except FileNotFoundError:
            raise UserError("git ist auf diesem Rechner nicht installiert.")
        except subprocess.TimeoutExpired:
            raise UserError("git %s dauert zu lange (über %d s)." % (args[0], timeout))
        return r.returncode, r.stdout.strip(), scrub(r.stderr.strip())

    def ide_open(self, b):
        """Detached Worktree genau auf dem Head-Commit des MR und `idea <pfad>`. Nur lesend gegenüber GitLab (fetch, kein push)."""
        host = "github" if b.get("host") == "github" else "gitlab"
        try:
            pid, iid = int(b.get("project_id")), int(b.get("iid"))
        except (TypeError, ValueError):
            raise UserError("project_id und iid müssen Zahlen sein.")
        it = self._find_mr(host, pid, iid)
        if not it or not it.get("sha"):
            raise UserError("Diesen MR (mit Commit) kenne ich nicht (mehr). Einmal «Neu laden».")
        sha = it["sha"]
        repo = self._repo_of(host, pid)
        if self.demo and not repo:          # Demo: nichts anlegen, nur zeigen, wie es aussähe
            path = "/home/demo/work/.tinyops-wt/%s-mr%d-%s" % (it.get("project", "repo"), iid, sha[:8])
            ref_key = it.get("ref") or links.ref_of(pid, it.get("branch", ""))
            self.store.ide_set(ref_key, host, pid, iid, sha, path, "/home/demo/work/%s" % it.get("project", "repo"))
            self.audit("ide.open", ref_key, sha=sha[:12], path=path, launched=False, demo=True)
            return {"path": path, "sha": sha, "launched": False, "hint": "Demo: Worktree und IntelliJ nur angedeutet. Pfad kopiert."}
        if not repo:
            raise UserError("Für %s fehlt der lokale Checkout (Einstellungen → IntelliJ → Pfad zum Repository)." % it.get("project", pid))
        rc, _, err = self._git(repo, "rev-parse", "--git-dir")
        if rc:
            raise UserError("%s ist kein Git-Repository: %s" % (repo, err[:200]))
        ref = ("refs/pull/%d/head" % iid) if host == "github" else ("refs/merge-requests/%d/head" % iid)
        rc, _, _ = self._git(repo, "cat-file", "-e", sha + "^{commit}")
        if rc:
            rc2, remotes, _ = self._git(repo, "remote")
            remote = "origin" if "origin" in remotes.split() else (remotes.split() or ["origin"])[0]
            rc, _, err = self._git(repo, "fetch", "--no-tags", remote, ref, timeout=180)
            if rc:
                raise UserError("Holen von %s fehlgeschlagen: %s" % (ref, err[:300]))
            rc, _, _ = self._git(repo, "cat-file", "-e", sha + "^{commit}")
            if rc:
                raise UserError("Commit %s ist nach dem Holen nicht da (MR inzwischen neu gepusht? Einmal «Neu laden»)." % sha[:10])
        path = str(Path(repo).parent / ".tinyops-wt" / ("%s-%s%d-%s" % (Path(repo).name, "pr" if host == "github" else "mr", iid, sha[:8])))
        if not Path(path).exists():
            Path(path).parent.mkdir(parents=True, exist_ok=True)
            rc, _, err = self._git(repo, "worktree", "add", "--detach", path, sha, timeout=180)
            if rc:
                raise UserError("Worktree nicht angelegt: %s" % err[:300])
        ref_key = it.get("ref") or links.ref_of(pid, it.get("branch", ""))
        self.store.ide_set(ref_key, host, pid, iid, sha, path, repo)
        launched, hint = self._launch_ide(path)
        self.audit("ide.open", ref_key, sha=sha[:12], path=path, launched=launched)
        return {"path": path, "sha": sha, "launched": launched, "hint": hint}

    def _launch_ide(self, path):
        cmd = self.cfg.get("ide_command") or "idea {path}"
        try:
            argv = [a.replace("{path}", path) for a in shlex.split(cmd)]
        except ValueError:
            return False, "ide_command lässt sich nicht lesen."
        if "{path}" not in cmd:
            argv.append(path)
        if self.demo:
            return False, "Demo: IntelliJ wird nicht gestartet. Befehl wäre: %s" % " ".join(shlex.quote(a) for a in argv)
        kw = {"stdin": subprocess.DEVNULL, "stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL, "close_fds": True}
        if os.name == "nt":
            kw["creationflags"] = 0x00000008 | 0x00000200
        else:
            kw["start_new_session"] = True
        try:
            subprocess.Popen(argv, **kw)
            return True, ""
        except OSError as e:
            return False, "«%s» liess sich nicht starten (%s). In IntelliJ «File → Open» mit dem Pfad, oder unter Einstellungen → IntelliJ den Befehl anpassen (z. B. den Launcher aus «Tools → Create Command-line Launcher»)." % (argv[0], e.strerror or e)

    def ide_close(self, b, force=False):
        w = self.store.ide_get(str(b.get("ref") or ""))
        if not w:
            raise UserError("Kein IntelliJ-Worktree für diesen MR.")
        p = Path(w["path"])
        if p.parent.name != ".tinyops-wt":
            raise UserError("Unerwarteter Pfad, nichts gelöscht: %s" % w["path"])
        if p.exists():
            rc, out, _ = self._git(str(p), "status", "--porcelain")
            if out and not (force or b.get("force")):
                err = UserError("Im Worktree gibt es %d geänderte Dateien (vom Testen?). Trotzdem entfernen?" % len(out.splitlines()))
                err.data = {"dirty": len(out.splitlines())}
                raise err
            rc, _, e = self._git(w["repo"], "worktree", "remove", "--force", str(p))
            if rc:
                raise UserError("Worktree nicht entfernt: %s" % e[:300])
        self.store.ide_delete(w["ref"])
        self.audit("ide.close", w["ref"], sha=w["sha"][:12], forced=bool(force or b.get("force")))
        return {"ok": True}

    def _ide_cleanup(self, card_key):
        """Beim Abschliessen: saubere IntelliJ-Worktrees der Karte entfernen, geänderte stehen lassen."""
        card = self._cards.get(card_key) or {}
        for x in card.get("items") or []:
            ref = x.get("ref") or (links.ref_of(x["project_id"], x["branch"]) if x.get("project_id") is not None and x.get("branch") else "")
            if ref and self.store.ide_get(ref):
                try:
                    self.ide_close({"ref": ref})
                except UserError as e:
                    log.info("IntelliJ-Worktree %s bleibt: %s", ref, e)

    # -- Übersicht
    def overview(self, wait=True):
        """wait=True wartet auf eine frische Synchronisation (Tests, Skripte). wait=False liefert sofort, was da ist: den Zwischenspeicher
        oder, solange noch nichts vollständig geladen ist, den Zwischenstand."""
        if not self.configured:
            return {"configured": False, "problems": list(self.problems), "me": "", "mine": [], "review": [], "assigned": [],
                    "errors": [], "jira": None, "wip": 0, "wip_limit": self.cfg["wip_limit"], "stale_days": self.cfg["stale_days"],
                    "demo": self.demo, "version": VERSION, "usage_providers": self.usage_providers(), "features": {k: self.has(k) for k in settings.CONFIG_KEYS_FEATURES},
                    "agent_enabled": False, "prompts": [], "fetched": time.time(), "helpdesk": None}
        with self.cache_lock:
            expired = self.cache is None or time.time() - self.cache_t > self.cfg["cache_seconds"]
        if expired:
            self.start_sync()
        if wait:
            t = self._sync_thread
            if t is not None and expired:
                t.join()
        with self.cache_lock:
            cached = self.cache
        data = dict(cached) if cached is not None else self._partial_view()
        data["loading"] = cached is None
        data["board"] = None
        data["sync"] = self.sync_view()
        stale = self.cfg["stale_days"]
        wts = self.store.ide_all()
        for it in data["mine"] + data["review"] + data["assigned"]:
            it["stale"] = it["age_days"] >= stale
            if it.get("iid"):
                it["ide"] = bool(self._repo_of(it.get("host") or "gitlab", it["project_id"])) or self.demo
                w = wts.get(it.get("ref") or links.ref_of(it["project_id"], it.get("branch", "")))
                it["ide_wt"] = {"sha": w["sha"], "path": w["path"], "stale": bool(it.get("sha") and w["sha"] != it["sha"])} if w else None
        data["board"] = self._board(data)
        self._cards = {c["id"]: c for c in data["board"]["cards"]}
        agents_v = self.agents_view()
        by_ticket = {}
        for r in agents_v["runs"]:
            by_ticket.setdefault(r["ticket"], []).append(r)
        try:
            data["flow"] = flow.build(data["board"]["cards"], self.store, by_ticket, complete=not data["loading"] and not data.get("errors"),
                                      goal=int((self.cfg.get("flow") or {}).get("daily_goal", 3)))
            data["flow"]["reviews"] = flow.review_view(data)
            pin = self.store.pin_get()
            data["flow"]["pinned"] = pin if (pin in data["flow"]["items"] or (pin or "").startswith("rv:")) else None
        except Exception as e:   # der Ablauf ist eine Ansicht; er darf die Übersicht nie verhindern
            log.warning("Ablauf: %s", scrub(e))
            data["flow"] = None
        try:
            data["time"] = self.time_state()
        except Exception as e:      # die Zeit ist eine Zugabe; sie darf die Übersicht nie verhindern
            log.warning("Zeit: %s", scrub(e))
            data["time"] = {"enabled": False, "error": str(e)}
        data.update({
            "wip": len(data["mine"]), "wip_limit": self.cfg["wip_limit"],
            "stale_days": stale, "demo": self.demo, "agent_enabled": bool(self.cfg["agent_command"]),
            "prompts": self.prompt_names() if self.has("testenv") else [], "fetched": time.time(),
            "helpdesk": self.helpdesk(), "configured": True, "version": VERSION, "usage_providers": self.usage_providers(), "problems": list(self.problems),
            "features": {k: self.has(k) for k in settings.CONFIG_KEYS_FEATURES},
            "ignore_patterns": list(branch_cfg(self.cfg).get("ignore_branches") or []),
            "ticket": self.ticket_meta(),
            "pools": self.pools_view(data),
            "ai": self.store.ai_accounts() if self.has("ai") else [],
            "agents": agents_v,
        })
        return data

    # -- Audit
    def audit(self, action, target="", ok=True, actor="du", **detail):
        """Eintrag im Audit-Trail. Ein Fehler beim Schreiben bricht die Aktion nicht ab (sie ist schon passiert), steht aber im Log."""
        try:
            return self.audit_log.add(action, target, ok, actor, detail)
        except Exception as e:
            log.error("Audit-Eintrag %s %s nicht geschrieben: %s", action, target, scrub(e))
            return None

    def _audited(self, action, target, fn, target_of=None, **detail):
        """Führt fn aus und schreibt genau einen Eintrag. Verschachtelte Aufrufe (z. B. «Schritt erledigt» setzt eine Station)
        schreiben nichts Eigenes, sie ergänzen mit audit_note() nur Details zum äusseren Eintrag."""
        ctx = self._audit_ctx
        if getattr(ctx, "extra", None) is not None:
            return fn()
        ctx.extra = {}
        try:
            try:
                res = fn()
            except UserError as e:
                self.audit(action, target, ok=False, error=str(e)[:300], **detail, **ctx.extra)
                raise
            if target_of:
                target = target_of(res) or target
            self.audit(action, target, **detail, **ctx.extra)
            return res
        finally:
            ctx.extra = None

    def audit_note(self, **kw):
        extra = getattr(self._audit_ctx, "extra", None)
        if extra is not None:
            extra.update(kw)

    # -- Teilschritte (Checkliste je Karte)
    def flow_action(self, action, b):
        tgt = str(b.get("id") or b.get("key") or "")
        if action in ("add", "toggle", "delete"):
            return self._flow_action(action, b)          # Teilschritte: im Verlauf über den Spielstand, nicht im Audit
        if action == "tiny":
            return self._audited("flow.tiny", "", lambda: self._flow_action(action, b), target_of=lambda r: (r or {}).get("key"),
                                 branch="%s:%s" % (b.get("project_id"), b.get("branch")))
        return self._audited("flow." + action, tgt, lambda: self._flow_action(action, b),
                             **{k: b.get(k) for k in ("phase", "note", "env") if b.get(k) not in (None, "")})

    def _flow_action(self, action, b):
        st = self.store
        try:
            if action == "add":
                return {"id": st.check_add(str(b.get("key") or ""), b.get("text"))}
            if action == "toggle":
                r = st.check_toggle(int(b.get("id")), b.get("done"))
                if r["done"]:
                    st.flow_event_once("check:%d" % r["id"], r["key"], "", "check", -1, flow.XP_CHECK, r["text"])
                return {"done": bool(r["done"]), "stats": st.flow_stats(int((self.cfg.get("flow") or {}).get("daily_goal", 3)))}
            if action == "delete":
                st.check_delete(int(b.get("id")))
                return {"ok": True}
            if action == "complete":
                return self._flow_complete(b)
            if action == "tiny":
                return self._flow_tiny(b)
            if action == "accept":
                return self._flow_accept(b)
            if action == "pin":
                cid = b.get("id") or None
                if cid and cid not in self._cards and not str(cid).startswith("rv:"):
                    raise UserError("Dieses Vorhaben gibt es (gerade) nicht.")
                self.store.pin_set(cid)
                if self.tc["enabled"]:
                    if cid and not str(cid).startswith("rv:"):
                        self.timebook.start(cid, (self._cards.get(cid) or {}).get("title") or "", idle=self.tc["idle_minutes"])
                    else:
                        self.timebook.stop(idle=self.tc["idle_minutes"])
                return {"pinned": cid}
        except (TypeError, ValueError):
            raise UserError("Teilschritt-Nummer fehlt.")
        except links.LinkError as e:
            raise UserError(str(e))
        raise UserError("Unbekannte Aktion.")

    def _accept(self, cid, note="", env=""):
        """Abnahme an die aktuellen Head-Commits aller offenen MRs/PRs der Karte binden."""
        card = self._cards.get(cid) or {}
        refs = []
        for x in card.get("items") or []:
            if x.get("kind") in ("mr", "assigned") and x.get("iid"):
                ref = x.get("ref") or links.ref_of(x["project_id"], x["branch"])
                w = self.store.ide_get(ref)
                refs.append((ref, w["sha"] if w else x.get("sha") or ""))    # getestet wurde, was im IntelliJ-Worktree lag
        if refs:
            self.store.accept_set(cid, refs, note, env)
            self.audit_note(accepted=["%s@%s" % (r, (sh or "?")[:12]) for r, sh in refs])
            log.info("Abnahme %s: %s", cid, ", ".join("%s@%s" % (r, (sh or "?")[:8]) for r, sh in refs))
        return refs

    def _flow_accept(self, b):
        cid = str(b.get("id") or "")
        if not cid or cid.startswith("idea:") or links.is_ref_key(cid):
            raise UserError("Abnehmen geht nur für Vorhaben mit Ticket.")
        self.board_action("stage", {"key": cid, "stage": "tested", "note": b.get("note"), "env": b.get("env")})   # bindet die Abnahme
        card = self._cards.get(cid) or {}
        return {"stage": "tested", "commits": [{"ref": x.get("ref", ""), "sha": (x.get("sha") or "")[:8]} for x in card.get("items") or [] if x.get("iid")]}

    def _flow_complete(self, b):
        """«Schritt erledigt»: setzt die nächste Station von Hand. Branches und MRs ohne Ticket dürfen das nicht."""
        cid = str(b.get("id") or "")
        if not cid or cid.startswith("idea:"):
            raise UserError("Ideen werden mit «Einplanen» übernommen.")
        if links.is_ref_key(cid):
            raise UserError("Ein Branch braucht zuerst ein Jira- oder tiny-Ticket. Erst «Ticket zuordnen», dann geht es weiter.")
        try:
            phase = int(b.get("phase"))
        except (TypeError, ValueError):
            raise UserError("Station fehlt.")
        stage = flow.next_stage(phase)
        if stage is None:
            raise UserError("Schon fertig.")
        self.board_action("stage", {"key": cid, "stage": stage})
        self.audit_note(stage=stage)
        return {"stage": stage}

    def _flow_tiny(self, b):
        """Ein tiny-Ticket für einen Branch oder MR ohne Ticket: Aufgabe in «Umsetzung», Kategorie = Projekt, Branch verknüpft."""
        pid, branch = self._ref(b)
        title = " ".join(str(b.get("title") or branch).split())[:200]
        pname = (str(b.get("project") or "") or (self.proj_cfg.get(pid) or {}).get("name") or "Projekt %s" % pid)[:60]
        pool = next((p for p in self.store.pools() if p["name"].lower() == pname.lower()), None)
        pool_id = pool["id"] if pool else self._local(self.store.add_pool, pname)
        key = self._local(self.store.task_add, title, "impl", pool_id)
        self._local(self.store.link, pid, branch, key)
        log.info("tiny-Ticket %s für %s:%s angelegt (Kategorie %s)", key, pid, branch, pname)
        self.cache_t = 0.0
        return {"key": key, "pool": pname}

    # -- Coding-Agenten an Tickets
    def agents_view(self):
        """Agenten und Läufe für die Oberfläche. Der Stand der laufenden Läufe wird im Hintergrund abgefragt (SSH kann dauern)."""
        v = self.agents.view()
        if any(r["active"] for r in v["runs"]) and not self._agent_poll_busy:
            self._agent_poll_busy = True

            def work():
                try:
                    self.agents.poll()
                except Exception as e:   # Abfrage darf die Oberfläche nie stören
                    log.warning("Agenten-Abfrage: %s", scrub(e))
                finally:
                    self._agent_poll_busy = False
            threading.Thread(target=work, daemon=True).start()
        return v

    def agent_action(self, action, b):
        svc = self.agents
        try:
            if action == "prompt":
                if isinstance(b.get("review"), dict):      # Agent soll offene Review-Punkte bearbeiten
                    aid, rv = str(b.get("agent") or ""), dict(b["review"])
                    res, topics = self._review_pick(rv)
                    skipped = []
                    p = svc.project(res["mr"]["project_id"])
                    if p and svc.mode(svc.agent(aid), res["mr"]["project_id"]) == "export":
                        # Export: nur Punkte zu Dateien in den freigegebenen Pfaden; allgemeine Punkte können alles betreffen
                        paths = p.get("cloud_paths") or []
                        keep = [t for t in topics if t["file"] and agents.path_allowed(t["file"], paths)]
                        skipped = [review.where(t) for t in topics if t not in keep]
                        if not keep:
                            raise UserError("Keiner der Punkte liegt in den freigegebenen Pfaden (%s). Einen lokalen Agenten nehmen." % ", ".join(paths))
                        rv["ids"] = [t["id"] for t in keep]
                    extra, mr = self.review_prompt_extra(rv)
                    info = svc.prompt_info(aid, b.get("ticket"), mr["project_id"], mr["branch"],
                                           b.get("title") or "", b.get("key") or "", mr["url"], template="review-topics", extra=extra)
                    info["review_skipped"] = skipped
                    return info
                return svc.prompt_info(str(b.get("agent") or ""), b.get("ticket"), self._pid(b.get("project_id")), b.get("branch") or "",
                                       b.get("title") or "", b.get("key") or "", b.get("url") or "")
            if action == "assign":
                rid = svc.assign(str(b.get("agent") or ""), b.get("ticket"), self._pid(b.get("project_id")), b.get("branch"), b.get("title"))
                return {"id": rid}
            if action == "start":
                rid = svc.start(self._rid(b), b.get("prompt"), self._pid(b.get("project_id")), b.get("branch"))
                return {"id": rid}
            if action == "stop":
                svc.stop(self._rid(b))
                return {"ok": True}
            if action == "remove":
                svc.remove(self._rid(b), force=bool(b.get("force")))
                return {"ok": True}
            if action == "takeover":
                return svc.takeover(self._rid(b))
            if action == "changes":
                return {"files": svc.changes(self._rid(b))}
            if action == "refresh":
                svc.poll(force=True)
                return svc.view()
            if action == "tail":
                return {"text": svc.tail(self._rid(b), int(b.get("lines") or 80))}
            if action == "answer":
                return svc.answer(self._rid(b), b.get("qid"), b.get("text"))
            if action == "report":           # Bericht und Belege neu einlesen
                r = svc.store.agent_run(self._rid(b))
                if not r:
                    raise UserError("Diesen Lauf gibt es nicht (mehr).")
                svc.collect(r)
                return svc.run_view(svc.store.agent_run(r["id"]))
            if action == "ack":
                svc.ack(self._rid(b))
                return {"ok": True}
        except agents.AgentError as e:
            raise UserError(str(e))
        raise UserError("Unbekannte Aktion.")

    @staticmethod
    def _pid(v):
        if v in (None, ""):
            return None
        try:
            return int(v)
        except (TypeError, ValueError):
            raise UserError("project_id muss eine Zahl sein.")

    @staticmethod
    def _rid(b):
        try:
            return int(b.get("run"))
        except (TypeError, ValueError):
            raise UserError("Lauf-Nummer fehlt.")

    # -- Fokus-Zeit und Zeitentwürfe (0.19)
    def time_state(self, now=None):
        now = now or time.time()
        if not self.tc["enabled"]:
            return {"enabled": False}
        tb, idle = self.timebook, self.tc["idle_minutes"]
        cur = tb.current()
        d = timesheet.today(now)
        tot = tb.totals(d, now, idle)
        run = None
        if cur:
            idle_now = now - cur["last_seen"] > idle * 60
            run = {"key": cur["key"], "title": cur["title"], "since": cur["start"], "idle": idle_now,
                   "today_secs": (tot.get(cur["key"]) or {}).get("secs", 0)}
        return {"enabled": True, "running": run, "today_secs": sum(x["secs"] for x in tot.values()), "gaps": len(tb.gaps(d)),
                "open_drafts": len([x for x in tb.drafts(state="offen") if x["date"] < d]), "date": d}

    def _time_meta(self):
        meta = {}
        for cid, c in (self._cards or {}).items():
            hint = ", ".join(p["name"] for p in c.get("pools") or []) or next((x.get("project") for x in c.get("items") or [] if x.get("project")), "")
            meta[cid] = {"title": c.get("title") or cid, "project_hint": hint}
        return meta

    def time_day(self, d=None, now=None):
        """Abschnitte, Lücken und Entwürfe eines Tages. Führt die automatischen Entwürfe nach."""
        now = now or time.time()
        if not self.tc["enabled"]:
            raise UserError("Die Zeiterfassung ist ausgeschaltet (Einstellungen → Zeiterfassung).")
        d = d or timesheet.today(now)
        try:
            timesheet.day_bounds(d)
        except ValueError:
            raise UserError("Datum im Format JJJJ-MM-TT.")
        tb, idle = self.timebook, self.tc["idle_minutes"]
        a, b = timesheet.day_bounds(d)
        labels = dict(flow.PHASES)
        names = [p for p, _ in flow.PHASES]
        events = []
        for e in self.store.flow_events_between(a, b):
            if e["kind"] == "phase" and 0 <= e["phase"] < len(names):
                events.append({"key": e["key"], "text": "Station %s" % labels[names[e["phase"]]], "ts": e["ts"], "kind": "phase"})
            elif e["kind"] in ("check", "agent") and e["text"]:
                events.append({"key": e["key"], "text": e["text"], "ts": e["ts"], "kind": e["kind"]})
        accs = []
        for key, refs in self.store.acceptances().items():
            for ref, r in refs.items():
                if a <= (r.get("ts") or 0) < b:
                    accs.append({"key": key, "ref": ref, "label": ref, "sha": r.get("sha"), "ts": r["ts"]})
        tot = tb.totals(d, now, idle)
        meta = self._time_meta()
        tb.sync_auto(d, timesheet.compose(d, tot, meta, events, accs, self.tc["round_minutes"], self.tc["min_minutes"]), now)
        drafts = tb.drafts(d)
        for x in drafts:
            x["ticket_ok"] = not links.is_ref_key(x["ticket"])
            x["payload"] = timesheet.payload(x) if x["state"] != "verworfen" else None
        return {"date": d, "segments": tb.segments(d, now, idle), "gaps": tb.gaps(d), "drafts": drafts,
                "total_secs": sum(x["secs"] for x in tot.values()), "booked_minutes": sum(x["minutes"] for x in drafts if x["state"] == "gebucht"),
                "draft_minutes": sum(x["minutes"] for x in drafts if x["state"] not in ("verworfen",)),
                "mcp": bool(self.tc["mcp_url"]), "send_on_confirm": bool(self.tc["send_on_confirm"]), "round": self.tc["round_minutes"],
                "earlier_open": sorted({x["date"] for x in tb.drafts(state="offen") if x["date"] < d})[-7:]}

    def _draft(self, did):
        dr = self.timebook.draft(str(did or ""))
        if not dr:
            raise UserError("Diesen Entwurf gibt es nicht.")
        return dr

    def time_action(self, action, b):
        if not self.tc["enabled"]:
            raise UserError("Die Zeiterfassung ist ausgeschaltet.")
        tb, idle = self.timebook, self.tc["idle_minutes"]
        if action == "ping":
            tb.ping(idle=idle)
            return self.time_state()
        if action == "pause":
            tb.stop(idle=idle)
            self.audit("time.pause", (self.store.pin_get() or ""))
            return self.time_state()
        if action == "resume":
            pin = self.store.pin_get()
            if not pin or str(pin).startswith("rv:"):
                raise UserError("Erst ein Vorhaben als Fokus anheften.")
            tb.start(pin, (self._cards.get(pin) or {}).get("title") or "", idle=idle)
            return self.time_state()
        if action == "gap":
            g = tb.gap_set(int(b.get("id")), bool(b.get("count")))
            if not g:
                raise UserError("Diese Lücke ist schon erledigt.")
            self.audit("time.gap", g["key"], counted=bool(b.get("count")), minutes=int((g["end"] - g["start"]) // 60))
            return {"ok": True}
        if action == "add":
            d = str(b.get("date") or timesheet.today())
            ticket = " ".join(str(b.get("ticket") or "").split()).upper() if not links.is_ref_key(str(b.get("ticket") or "")) else str(b.get("ticket"))
            minutes = self._minutes(b.get("minutes"))
            if not ticket or len(ticket) > 120:
                raise UserError("Ticket fehlt.")
            did = tb.add_manual(d, ticket, minutes, str(b.get("text") or "")[:300], title=(self._cards.get(ticket) or {}).get("title", ""),
                                project_hint=(self._time_meta().get(ticket) or {}).get("project_hint", ""))
            self.audit("time.add", ticket, date=d, minutes=minutes)
            return {"id": did}
        dr = self._draft(b.get("id"))
        if dr["state"] in timesheet.LOCKED and action not in ("send",):
            raise UserError("Schon gebucht (%s). Ändern nur noch in Projectron." % (dr["reference"] or "ohne Referenz"))
        if action == "edit":
            if dr["state"] not in ("offen", "abgelehnt", "fehlgeschlagen", "bestätigt"):
                raise UserError("Verworfene Entwürfe erst wiederherstellen.")
            kw = {"edited": 1}
            if "minutes" in b:
                kw["minutes"] = self._minutes(b.get("minutes"))
            if "text" in b:
                kw["text"] = str(b.get("text") or "")[:300]
            if "ticket" in b:
                t = str(b.get("ticket") or "").strip()
                if not t:
                    raise UserError("Ticket fehlt.")
                kw["ticket"] = t[:120]
            if dr["state"] != "offen":
                kw["state"] = "offen"            # nach dem Ändern erneut bestätigen
            tb.update(dr["id"], **kw)
            self.audit("time.edit", dr["ticket"], draft=dr["id"], **{k: v for k, v in kw.items() if k in ("minutes", "ticket")})
            return {"ok": True}
        if action == "discard":
            tb.update(dr["id"], state="verworfen")
            self.audit("time.discard", dr["ticket"], draft=dr["id"], minutes=dr["minutes"])
            return {"ok": True}
        if action == "restore":
            tb.update(dr["id"], state="offen", merged_into="")
            return {"ok": True}
        if action == "merge":
            into = self._draft(b.get("into"))
            if into["id"] == dr["id"] or into["date"] != dr["date"] or into["state"] not in ("offen",) or dr["state"] != "offen":
                raise UserError("Zusammenlegen geht nur mit einem anderen offenen Entwurf desselben Tages.")
            ev = into["evidence"] + [e for e in dr["evidence"] if e not in into["evidence"]]
            tb.update(into["id"], minutes=into["minutes"] + dr["minutes"], text=(into["text"] + "; " + dr["text"])[:300], evidence=ev, edited=1)
            tb.update(dr["id"], state="verworfen", merged_into=into["id"])
            self.audit("time.merge", into["ticket"], draft=into["id"], merged=dr["id"], minutes=into["minutes"] + dr["minutes"])
            return {"ok": True}
        if action == "confirm":
            if dr["state"] != "offen":
                raise UserError("Nur offene Entwürfe lassen sich bestätigen (Status: %s)." % dr["state"])
            if links.is_ref_key(dr["ticket"]):
                raise UserError("Dieser Entwurf hängt an einem Branch ohne Ticket. Erst ein Ticket eintragen.")
            if dr["minutes"] <= 0:
                raise UserError("0 Minuten bucht man nicht. Verwerfen oder Zeit eintragen.")
            tb.update(dr["id"], state="bestätigt", message="")
            self.audit("time.confirm", dr["ticket"], draft=dr["id"], minutes=dr["minutes"], date=dr["date"])
            if self.tc["mcp_url"] and self.tc["send_on_confirm"]:
                return self.time_send(dr["id"])
            return {"state": "bestätigt"}
        if action == "send":
            return self.time_send(dr["id"])
        raise UserError("Unbekannte Aktion.")

    def _minutes(self, v):
        try:
            m = int(v)
        except (TypeError, ValueError):
            raise UserError("Minuten müssen eine ganze Zahl sein.")
        if not 0 <= m <= 24 * 60:
            raise UserError("Minuten zwischen 0 und 1440.")
        return m

    def _mcp_url(self):
        url = (self.tc.get("mcp_url") or "").strip()
        if not url:
            raise UserError("Keine Wrapper-API eingetragen (Einstellungen → Zeiterfassung).")
        try:
            return llm.check_url({"url": url, "allow_remote": self.tc.get("allow_remote")})
        except llm.LlmError as e:
            raise UserError(str(e))

    def time_send(self, did):
        """Einen bestätigten Entwurf an die Wrapper-API des MCP schicken. Gebucht ist er nur, wenn der MCP «booked» sagt."""
        with self._send_lock:
            dr = self._draft(did)
            if dr["state"] == "gebucht":
                return {"state": "gebucht", "reference": dr["reference"], "already": True}
            if dr["state"] not in timesheet.SENDABLE:
                raise UserError("Senden geht nur für bestätigte Entwürfe (Status: %s)." % dr["state"])
            url = self._mcp_url()
            body = timesheet.payload(dr)
            headers = {"Content-Type": "application/json", "Accept": "application/json", "Idempotency-Key": body["idempotency_key"], "User-Agent": "tinyops"}
            if self.mcp_token:
                headers["Authorization"] = "Bearer " + self.mcp_token
            state, ref, msg, code = "fehlgeschlagen", "", "", 0
            try:
                req = urllib.request.Request(url, data=json.dumps(body, ensure_ascii=False).encode("utf-8"), headers=headers, method="POST")
                opener = urllib.request.build_opener(urllib.request.HTTPSHandler(context=self.ssl_ctx), NoRedirect)
                with opener.open(req, timeout=20) as r:
                    code = r.status
                    res = json.loads(r.read(1 << 20).decode("utf-8") or "{}")
                st = str(res.get("status") or "")
                if st == "booked":
                    state, ref, msg = "gebucht", str(res.get("reference") or "")[:200], str(res.get("message") or "")[:300]
                elif st == "rejected":
                    state, msg = "abgelehnt", str(res.get("message") or "abgelehnt, ohne Begründung")[:300]
                else:
                    msg = "Antwort ohne «status: booked/rejected» (HTTP %s). Nicht als gebucht gewertet." % code
            except urllib.error.HTTPError as e:
                code = e.code
                try:
                    res = json.loads(e.read(1 << 16).decode("utf-8") or "{}")
                except ValueError:
                    res = {}
                if res.get("status") == "rejected":
                    state, msg = "abgelehnt", str(res.get("message") or "abgelehnt")[:300]
                else:
                    msg = "HTTP %s%s" % (e.code, (": " + str(res.get("message"))[:200]) if res.get("message") else "")
            except (urllib.error.URLError, OSError, http.client.HTTPException) as e:
                msg = "nicht erreichbar (%s)" % scrub(getattr(e, "reason", e))
            except ValueError:
                msg = "Antwort ist kein JSON (HTTP %s). Nicht als gebucht gewertet." % code
            tb = self.timebook
            tb.update(dr["id"], state=state, reference=ref, message=scrub(msg), attempts=int(dr["attempts"] or 0) + 1, sent=time.time())
            self.audit("time.send", dr["ticket"], ok=state == "gebucht", draft=dr["id"], minutes=dr["minutes"], date=dr["date"], state=state,
                       reference=ref, message=scrub(msg)[:200], http=code, key=body["idempotency_key"])
            log.info("Zeitentwurf %s → %s %s", dr["id"], state, ref or msg)
            return {"state": state, "reference": ref, "message": scrub(msg)}

    def time_export(self, state="bestätigt", d=None):
        """Für deinen MCP zum Abholen: Entwürfe im Vertragsformat."""
        out = []
        for x in self.timebook.drafts(d or None, state or None):
            if x["state"] == "verworfen":
                continue
            p = timesheet.payload(x)
            p["state"] = x["state"]
            p["reference"] = x["reference"]
            out.append(p)
        return {"schema": timesheet.CONTRACT, "drafts": out}

    def time_result(self, b):
        """Rückmeldung deines MCP nach dem Abholen: {id, status: booked|rejected, reference, message}."""
        dr = self._draft(b.get("id"))
        st = b.get("status")
        if st not in ("booked", "rejected"):
            raise UserError("status muss booked oder rejected sein.")
        if dr["state"] not in timesheet.SENDABLE + ("gebucht",):
            raise UserError("Nur bestätigte Entwürfe lassen sich buchen (Status: %s)." % dr["state"])
        if dr["state"] == "gebucht":
            return {"state": "gebucht", "already": True}
        new = "gebucht" if st == "booked" else "abgelehnt"
        self.timebook.update(dr["id"], state=new, reference=str(b.get("reference") or "")[:200], message=str(b.get("message") or "")[:300])
        self.audit("time.result", dr["ticket"], ok=new == "gebucht", actor="mcp", draft=dr["id"], state=new, reference=str(b.get("reference") or "")[:200])
        return {"state": new}

    # -- Qualität (0.19): Prüfliste und Selbsttest
    def _checklist(self):
        try:
            return qa.parse_checklist((BASE / "QA-CHECKLIST.md").read_text(encoding="utf-8"))
        except OSError:
            return []
        except ValueError as e:
            raise UserError(str(e))

    def qa_view(self):
        secs = qa.view(self._checklist(), self.qabook.states())
        for s_ in secs:
            s_["current"] = s_["version"] == VERSION
        return {"version": VERSION, "sections": secs, "file": str(BASE / "QA-CHECKLIST.md")}

    def qa_action(self, action, b):
        if action == "report":
            return {"text": qa.report_md(self.qa_view()["sections"], VERSION)}
        if action == "selftest":
            res = run_selftest(self.cfg)
            self.audit("qa.selftest", VERSION, ok=res["ok"], failed=[x["title"] for x in res["steps"] if x["status"] == "fail"],
                       warn=[x["title"] for x in res["steps"] if x["status"] == "warn"])
            return res
        iid = str(b.get("id") or "")
        it = next((i for s_ in self._checklist() for i in s_["items"] if i["id"] == iid), None)
        if not it:
            raise UserError("Diesen Prüfpunkt gibt es nicht (mehr).")
        if action == "set":
            st = b.get("status") or "offen"
            if st not in qa.STATES + ("offen",):
                raise UserError("Status: ok, fehler, übersprungen oder offen.")
            note = str(b.get("note") or "").strip()
            self.qabook.set(iid, st, note, VERSION, it["hash"])
            if st != "offen":
                self.audit("qa.check", iid, ok=st != "fehler", status=st, note=note[:200])
            return {"ok": True}
        if action == "task":
            title = "QA %s: %s" % (iid, it["text"])
            res = self.board_action("add", {"title": title[:200], "stage": "idea"})
            return {"key": res["key"]}
        raise UserError("Unbekannte Aktion.")

    # -- Offene Review-Punkte (0.18): lesen, exportieren, als Agenten-Auftrag
    def _find_mr(self, host, pid, iid):
        with self.cache_lock:
            data = self.cache or {}
        for it in (data.get("mine") or []) + (data.get("review") or []) + (data.get("assigned") or []):
            if it.get("iid") == iid and it.get("project_id") == pid and (it.get("host") or "gitlab") == host:
                return it
        return None

    def _data_class(self, pid):
        p = self.agents.project(pid)
        return agents.data_class(p) if p else "restricted"

    def review_topics(self, b):
        host = "github" if b.get("host") == "github" else "gitlab"
        try:
            pid, iid = int(b.get("project_id")), int(b.get("iid"))
        except (TypeError, ValueError):
            raise UserError("project_id und iid müssen Zahlen sein.")
        it = self._find_mr(host, pid, iid)
        if not it:
            raise UserError("Diesen %s kenne ich nicht (mehr). Einmal «Neu laden»." % ("PR" if host == "github" else "MR"))
        key = (host, pid, iid)
        hit = self._rv_cache.get(key)
        if hit and time.time() - hit[0] < 60 and not b.get("fresh"):
            return hit[1]
        mr = {"host": host, "project_id": pid, "iid": iid, "title": it.get("title", ""), "project": it.get("project", ""), "branch": it.get("branch", ""),
              "url": it.get("url", ""), "sha": it.get("sha", ""), "target_branch": "", "kind": it.get("kind", "")}
        note = ""
        try:
            if host == "gitlab" or self.demo:
                if not self.client:
                    raise UserError("GitLab ist nicht verbunden.")
                m, disc = self.client.review_threads(pid, iid)
                mr.update(target_branch=m.get("target_branch") or "", sha=m.get("sha") or mr["sha"], url=m.get("web_url") or mr["url"])
                topics = review.gitlab_topics(disc, mr["sha"])
                for t in topics:
                    t["url"] = "%s#note_%s" % (mr["url"], t["note_id"]) if mr["url"] and t.get("note_id") else ""
            else:
                if not self.github:
                    raise UserError("GitHub ist nicht verbunden.")
                pr, comments, revs = self.github.review_threads(it.get("project", ""), iid)
                mr.update(target_branch=(pr.get("base") or {}).get("ref") or "", sha=(pr.get("head") or {}).get("sha") or mr["sha"])
                topics = review.github_topics(comments, revs, mr["sha"])
                note = "GitHub zeigt über die REST-API nicht, ob ein Thread erledigt ist. Alle Threads sind dabei; wähle ab, was schon erledigt ist."
        except github.GitHubError as e:
            raise UserError(str(e))
        res = {"mr": mr, "topics": topics, "data_class": self._data_class(pid), "configured": self.agents.project(pid) is not None,
               "note": note, "fetched": time.time()}
        self._rv_cache[key] = (time.time(), res)
        log.info("Review-Punkte %s %s!%s: %d offen", host, pid, iid, len(topics))
        return res

    def _review_pick(self, b):
        res = self.review_topics(b)
        ids = b.get("ids")
        topics = [t for t in res["topics"] if ids is None or t["id"] in set(ids)]
        if not topics:
            raise UserError("Keine Punkte ausgewählt.")
        return res, topics

    def _review_template(self):
        try:
            return (BASE / "prompts" / "review-topics.md").read_text(encoding="utf-8")
        except OSError:
            return "Offene Review-Punkte zu {mr_ref}: {title}\n{workspace_line}\n{topics}\n"

    def review_export(self, b):
        """Markdown (als Prompt zum Kopieren) oder JSON (mit allen Zielangaben). Schreibt einen Eintrag in den Verlauf."""
        fmt = "json" if b.get("format") == "json" else "md"
        res, topics = self._review_pick(b)
        mr = res["mr"]
        if fmt == "json":
            text = review.dumps(review.to_json(mr, topics, res["data_class"]))
        else:
            text = review.to_markdown(mr, topics, self._review_template(), {"workspace_line": "", "ask_hint": "", "report_hint": ""})
        self.audit("review.export", "%s%s%s" % (mr["project_id"], "#" if mr["host"] == "github" else "!", mr["iid"]), format=fmt,
                   topics=len(topics), data_class=res["data_class"], branch=mr["branch"])
        name = "review-%s-%s.%s" % (review.context(mr)["mr_ref"].replace(" ", "").replace("!", "").replace("#", ""), time.strftime("%Y%m%d-%H%M"), fmt)
        return {"text": text, "format": fmt, "filename": name.lower(), "count": len(topics), "data_class": res["data_class"]}

    def review_prompt_extra(self, rv):
        """Platzhalter für prompts/review-topics.md, wenn ein Agent die Punkte bearbeitet."""
        res, topics = self._review_pick(rv)
        mr = res["mr"]
        ctx = review.context(mr)
        return dict(ctx, count=len(topics), topics=review.topics_block(mr, topics), ask_hint=" mit `tinyops-ask`", report_hint=", als Bericht mit `tinyops-report`"), mr

    # -- Prompts
    def prompt_names(self):
        d = BASE / "prompts"
        return sorted(p.stem for p in d.glob("*.md") if p.stem != "idea-triage")

    def _prompt_text(self, name):
        if not re.fullmatch(r"[a-z0-9-]+", name or ""):
            raise UserError("Ungültiger Prompt-Name.")
        path = BASE / "prompts" / (name + ".md")
        if not path.exists():
            raise UserError("Prompt nicht gefunden.")
        return path.read_text(encoding="utf-8")

    def _mr_vars(self, project_id, iid):
        proj = self.proj_cfg.get(project_id)
        if not proj:
            raise UserError("Projekt ist nicht in der config.json eingetragen.")
        mr = self.client.mr(project_id, iid)
        prefix = self.cfg["namespace_prefix"]
        namespace = ("%s-%s-%s" % (prefix, slug(proj.get("name", project_id), 20), iid))[:50].strip("-")
        sha8 = (mr["sha"] or "")[:8]
        tag_tpl = proj.get("tag_template", "{sha8}")
        tag = render(tag_tpl, {"sha8": sha8, "iid": iid, "branch_slug": slug(mr["branch"], 40)})
        keys = extract_keys("%s %s" % (mr["branch"], mr["title"]), self.jc.get("project_keys"))
        return proj, {
            "project": proj.get("name", str(project_id)), "branch": mr["branch"],
            "mr_iid": iid, "iid": iid, "mr_url": mr["url"], "title": mr["title"],
            "sha": mr["sha"], "sha8": sha8, "namespace": namespace, "release": namespace,
            "tag": tag, "chart": proj.get("chart", ""), "context": self.cfg["kube_context"],
            "ticket": keys[0] if keys else "",
        }

    def render_prompt(self, name, project_id, iid):
        _, vals = self._mr_vars(project_id, iid)
        return render(self._prompt_text(name), vals)

    def triage_prompt(self):
        ideas = [i for i in self.ideas.list() if i["status"] in ("neu", "geparkt") and not i["expired"]]
        if not ideas:
            raise UserError("Keine offenen Ideen.")
        lines = "\n".join("- (#%d, %d Tage alt) %s" % (i["id"], i["age_days"], i["text"].replace("\n", " ")) for i in ideas)
        return render((BASE / "prompts" / "idea-triage.md").read_text(encoding="utf-8"), {"ideas": lines})

    # -- Cluster
    def _check_cluster(self):
        if not self.cfg["kube_context"]:
            raise UserError("kube_context fehlt in der config.json (Schutz vor dem falschen Cluster).")

    def _guard_namespace(self, ns):
        prefix = self.cfg["namespace_prefix"] + "-"
        if not ns.startswith(prefix) or not re.fullmatch(r"[a-z0-9-]+", ns):
            raise UserError("Namespace %s liegt außerhalb von %s*, wird nicht angefasst." % (ns, prefix))

    def _argv(self, template, vals, extra=()):
        try:
            return [render(x, vals) for x in list(template) + list(extra)]
        except Exception as e:  # defensive: Konfig-Fehler als lesbare Meldung
            raise UserError("Befehl konnte nicht gebaut werden: %s" % e)

    def deploy(self, project_id, iid):
        self._check_cluster()
        proj, vals = self._mr_vars(project_id, iid)
        if not vals["chart"]:
            raise UserError("Für das Projekt fehlt 'chart' in der config.json.")
        self._guard_namespace(vals["namespace"])
        argv = self._argv(proj.get("deploy_command", self.cfg["deploy_command"]), vals, proj.get("extra_args", []))
        cwd = proj.get("repo_path") or BASE
        title = "Deploy %s !%s → %s (Tag %s)" % (vals["project"], iid, vals["namespace"], vals["tag"])
        self.audit("testenv.deploy", "%s!%s" % (project_id, iid), namespace=vals["namespace"], tag=vals["tag"])
        return self.jobs.start(title, argv, cwd)

    def teardown(self, project_id, iid):
        self._check_cluster()
        proj, vals = self._mr_vars(project_id, iid)
        self._guard_namespace(vals["namespace"])
        argv = self._argv(proj.get("teardown_command", self.cfg["teardown_command"]), vals)
        self.audit("testenv.teardown", "%s!%s" % (project_id, iid), namespace=vals["namespace"])
        return self.jobs.start("Abbauen %s" % vals["namespace"], argv, proj.get("repo_path") or BASE)

    def run_agent(self, name, project_id, iid):
        if not self.cfg["agent_command"]:
            raise UserError("agent_command ist nicht konfiguriert.")
        proj, vals = self._mr_vars(project_id, iid)
        if self.jira and self.over_limit:
            keys = set(extract_keys("%s %s" % (vals["branch"], vals["title"]), self.jc.get("project_keys")))
            if not (keys & self.inprogress_keys):
                raise UserError("Story-Limit überschritten: Agenten starten nur für Tickets, die schon in Arbeit sind.")
        repo = proj.get("repo_path")
        if not repo:
            raise UserError("Für den Agentenlauf fehlt 'repo_path' beim Projekt.")
        vals["prompt"] = render(self._prompt_text(name), vals)
        argv = self._argv(self.cfg["agent_command"], vals)
        return self.jobs.start("Agent '%s' für %s !%s" % (name, vals["project"], iid), argv, repo)


# ---------------------------------------------------------------- HTTP
def _eq(a, b):
    return hmac.compare_digest(str(a).encode("utf-8"), str(b).encode("utf-8"))


class _Cfg:
    """Liest immer die aktuelle Config der App (sie ändert sich, wenn Einstellungen gespeichert werden)."""

    def __init__(self, app):
        self._app = app

    def __getitem__(self, k):
        return self._app.cfg[k]

    def get(self, k, d=None):
        return self._app.cfg.get(k, d)


def _stored(app):
    def stored(name):
        try:
            return store.resolve(name, (app.cfg.get("secrets") or {}).get(name), _env_hints(app.cfg).get(name, ()))
        except store.SecretError:
            return None, ""
    return stored


def make_handler(app):
    cfg = _Cfg(app)
    html = (BASE / "static" / "index.html").read_bytes()
    token = app.access_token
    session = hashlib.sha256(("tinyops-session:" + token).encode("utf-8")).hexdigest() if token else ""

    class Handler(BaseHTTPRequestHandler):
        server_version = "tinyops"

        def log_message(self, fmt, *args):
            pass   # ersetzt durch log_request / Fehler-Logs unten

        def log_request(self, code="-", size="-"):
            # nur der Pfad, nie die Query: dort kann ?token=... stehen. Lesen im Takt (GET) nur im DEBUG-Log.
            path = scrub(urllib.parse.urlparse(self.path).path)
            ms = int((time.time() - getattr(self, "_t0", time.time())) * 1000)
            try:
                c = int(code)
            except (TypeError, ValueError):
                c = 0
            lvl = tlog.logging.WARNING if c >= 400 else (tlog.logging.DEBUG if self.command == "GET" else tlog.logging.INFO)
            hlog.log(lvl, "%s %s → %s (%d ms)", self.command, path, code, ms)

        # -- Antworten
        def _send(self, code, body, ctype="application/json", extra=None):
            if not isinstance(body, bytes):
                body = json.dumps(body, ensure_ascii=False).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", ctype + "; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Content-Security-Policy", "default-src 'self'; style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'")
            for k, v in (extra or {}).items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(body)

        def _err(self, code, msg):
            self._send(code, {"error": scrub(msg)})

        # -- Schutz: Host-Header (DNS-Rebinding), Zugriffstoken, Custom-Header
        def _gate(self, parsed):
            host = (self.headers.get("Host") or "").lower()
            host = host.rsplit(":", 1)[0] if not host.endswith("]") else host
            allowed = {"localhost", "127.0.0.1", "[::1]"} | {h.lower() for h in cfg["allowed_hosts"]}
            if host not in allowed:
                alog.warning("Abgelehnt: Host %r von %s nicht in allowed_hosts", host, self.client_address[0])
                self._err(403, "Host nicht erlaubt (allowed_hosts in der config.json).")
                return None
            if token:
                given = (urllib.parse.parse_qs(parsed.query).get("token") or [""])[0]
                if given and _eq(given, token):
                    # Token einmal gegen ein Cookie tauschen und aus der Adresszeile entfernen
                    self.send_response(302)
                    self.send_header("Location", "/")
                    self.send_header("Set-Cookie", "tinyops=%s; HttpOnly; SameSite=Strict; Path=/" % session)
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return None
                cookie_val = ""
                for part in self.headers.get("Cookie", "").split(";"):
                    k, _, v = part.strip().partition("=")
                    if k == "tinyops":
                        cookie_val = v
                if not cookie_val or not _eq(cookie_val, session):
                    alog.warning("Abgelehnt: kein gültiger Zugriffstoken von %s (%s)", self.client_address[0], self.command)
                    self._err(401, "Zugriffstoken fehlt: Seite einmal mit ?token=... öffnen.")
                    return None
            if self.command != "GET" and self.headers.get("X-Requested-With") != "tinyops":
                alog.warning("Abgelehnt: %s ohne X-Requested-With von %s", self.command, self.client_address[0])
                self._err(403, "Header X-Requested-With fehlt.")
                return None
            return {}

        def _body(self):
            n = int(self.headers.get("Content-Length") or 0)
            if n > 65536:
                raise UserError("Anfrage zu groß.")
            if not n:
                return {}
            try:
                return json.loads(self.rfile.read(n).decode("utf-8"))
            except ValueError:
                raise UserError("Ungültiges JSON.")

        def _route(self, method):
            self._t0 = time.time()
            parsed = urllib.parse.urlparse(self.path)
            if method == "GET" and parsed.path == "/healthz":   # für Kubernetes: ohne Token und Host-Prüfung, verrät nur die Version
                return self._send(200, {"ok": True, "version": VERSION})
            extra = self._gate(parsed)
            if extra is None:
                return
            path = parsed.path
            try:
                if method == "GET" and path == "/":
                    return self._send(200, html, "text/html", extra)
                if method == "GET" and path in ("/logo/jira", "/logo/gitlab"):
                    # Eigene Logo-Dateien des Nutzers: ~/.config/tinyops/logos/jira.svg|png (gitlab.svg|png). Fehlt eine, bleibt es beim Text.
                    name = path.rsplit("/", 1)[1]
                    for ext, ctype in (("svg", "image/svg+xml"), ("png", "image/png")):
                        f = store.home_dir() / "logos" / ("%s.%s" % (name, ext))
                        if f.is_file() and f.stat().st_size < 262144:
                            return self._send(200, f.read_bytes(), ctype, extra)
                    return self._err(404, "kein Logo hinterlegt")
                # -- Einstellungen: Anzeigen, Verbindung testen, Speichern
                if path.startswith("/api/settings"):
                    return self._settings(method, path)
                # -- vorerst ausgeblendete Funktionen
                needs = ("ideas" if path.startswith("/api/ideas") else
                         "ai" if path.startswith("/api/ai/") else
                         "testenv" if (path == "/api/agent" or path.startswith(("/api/jobs", "/api/deploy", "/api/teardown", "/api/prompt"))) else "")
                if needs and not app.has(needs):
                    return self._err(404, "Diese Funktion ist ausgeschaltet (Einstellungen → Weitere Funktionen).")
                if method == "POST" and path == "/api/links":
                    return self._send(200, app.link_ticket(self._body()))
                if method == "POST" and path == "/api/links/delete":
                    return self._send(200, app.unlink_ticket(self._body()))
                if method == "POST" and path.startswith("/api/pools"):
                    return self._send(200, app.pool_action(path.rsplit("/", 1)[1] if path != "/api/pools" else "create", self._body()))
                if method == "POST" and path.startswith("/api/board/"):
                    return self._send(200, app.board_action(path.rsplit("/", 1)[1], self._body()))
                if method == "POST" and path == "/api/ide/open":
                    return self._send(200, app.ide_open(self._body()))
                if method == "POST" and path == "/api/ide/close":
                    return self._send(200, app.ide_close(self._body()))
                if method == "GET" and path == "/api/qa":
                    return self._send(200, app.qa_view())
                if method == "POST" and path.startswith("/api/qa/"):
                    return self._send(200, app.qa_action(path.rsplit("/", 1)[1], self._body()))
                if method == "GET" and path == "/api/time/day":
                    q = {k: v[0] for k, v in urllib.parse.parse_qs(parsed.query).items()}
                    return self._send(200, app.time_day(q.get("date") or None))
                if method == "GET" and path == "/api/time/export":
                    q = {k: v[0] for k, v in urllib.parse.parse_qs(parsed.query).items()}
                    if not app.tc["enabled"]:
                        return self._err(400, "Die Zeiterfassung ist ausgeschaltet.")
                    return self._send(200, app.time_export(q.get("state", "bestätigt"), q.get("date") or None))
                if method == "POST" and path == "/api/time/result":
                    return self._send(200, app.time_result(self._body()))
                if method == "POST" and path.startswith("/api/time/"):
                    return self._send(200, app.time_action(path.rsplit("/", 1)[1], self._body()))
                if method == "POST" and path == "/api/review/topics":
                    return self._send(200, app.review_topics(self._body()))
                if method == "POST" and path == "/api/review/export":
                    return self._send(200, app.review_export(self._body()))
                if method == "GET" and path == "/api/audit":
                    ql = urllib.parse.parse_qs(parsed.query)
                    q = {k: v[0] for k, v in ql.items()}
                    return self._send(200, {"rows": app.audit_log.rows(target=ql.get("target") or None, action=q.get("action") or None,
                                                                        limit=max(1, min(int(q.get("limit") or 200), 2000))),
                                            "instance": app.audit_log.instance()})
                if method == "GET" and path == "/api/audit/verify":
                    return self._send(200, app.audit_log.verify())
                if method == "GET" and path == "/api/audit/export":
                    body = json.dumps({"exported": time.time(), "instance": app.audit_log.instance(), "verify": app.audit_log.verify(),
                                       "rows": app.audit_log.export()}, ensure_ascii=False, indent=1).encode("utf-8")
                    return self._send(200, body, "application/json",
                                      {"Content-Disposition": 'attachment; filename="tinyops-audit-%s.json"' % time.strftime("%Y%m%d-%H%M")})
                if method == "POST" and path.startswith("/api/flow/"):
                    return self._send(200, app.flow_action(path.rsplit("/", 1)[1], self._body()))
                if method == "POST" and path.startswith("/api/agents/"):
                    return self._send(200, app.agent_action(path.rsplit("/", 1)[1], self._body()))
                if method == "POST" and path.startswith("/api/ai/"):
                    return self._send(200, app.ai_action(path.rsplit("/", 1)[1], self._body()))
                if method == "POST" and path == "/api/ticket/draft":
                    return self._send(200, app.ticket_draft(self._body()))
                if method == "POST" and path == "/api/ticket/create":
                    return self._send(200, app.ticket_create(self._body()))
                if method == "POST" and path == "/api/refresh":
                    with app.cache_lock:
                        app.cache_t = 0.0
                    return self._send(200, {"started": app.start_sync(), "sync": app.sync_view()})
                if method == "GET" and path == "/api/sonar/report":
                    q = urllib.parse.parse_qs(parsed.query)
                    one = lambda k: (q.get(k) or [""])[0]
                    return self._send(200, app.sonar_report(int(one("project_id")), one("iid") or None, one("branch") or None))
                if method == "POST" and path == "/api/usage/push":
                    return self._send(200, app.usage_push(self._body()))
                if method == "GET" and path == "/api/usage":
                    v = app.usage_view(fresh="fresh=1" in (parsed.query or ""))
                    return self._send(200, {k: v[k] for k in ("enabled", "items", "fetched")})
                if method == "GET" and path == "/api/overview":
                    data = app.overview(wait=False)
                    data["ideas"] = app.ideas.list() if app.has("ideas") and app.ideas else []
                    data["idea_cap"] = cfg["idea_cap"]
                    data["jobs"] = app.jobs.summary() if app.has("testenv") else []
                    return self._send(200, data)
                if method == "GET" and path == "/api/log":
                    q = urllib.parse.parse_qs(parsed.query)
                    n = int((q.get("n") or ["200"])[0])
                    lvl = (q.get("level") or ["debug"])[0]
                    return self._send(200, {"file": str(tlog.log_file(cfg)), "level": cfg["log_level"],
                                            "lines": tlog.tail(cfg, n, lvl)})
                if method == "GET" and path == "/api/jobs":
                    return self._send(200, app.jobs.summary())
                m = re.fullmatch(r"/api/jobs/(\d+)", path)
                if method == "GET" and m:
                    job = app.jobs.get(int(m.group(1)))
                    if not job:
                        return self._err(404, "Job nicht gefunden.")
                    return self._send(200, job)
                if method == "POST" and path == "/api/ideas":
                    app.ideas.add(self._body().get("text"))
                    return self._send(200, {"ok": True})
                m = re.fullmatch(r"/api/ideas/(\d+)", path)
                if m and method == "PATCH":
                    app.ideas.set_status(int(m.group(1)), self._body().get("status"))
                    return self._send(200, {"ok": True})
                if m and method == "DELETE":
                    app.ideas.delete(int(m.group(1)))
                    return self._send(200, {"ok": True})
                m2 = re.fullmatch(r"/api/ideas/(\d+)/(assess|tiny)", path)
                if m2 and method == "POST":
                    fn = app.idea_assess if m2.group(2) == "assess" else app.idea_tiny
                    return self._send(200, fn(int(m2.group(1)), self._body()))
                if method == "GET" and path == "/api/ideas/triage-prompt":
                    return self._send(200, {"prompt": app.triage_prompt()})
                if method == "POST" and path == "/api/prompt":
                    b = self._body()
                    return self._send(200, {"prompt": app.render_prompt(b.get("name"), int(b["project_id"]), int(b["iid"]))})
                if method == "POST" and path == "/api/deploy":
                    b = self._body()
                    return self._send(200, {"job": app.deploy(int(b["project_id"]), int(b["iid"]))})
                if method == "POST" and path == "/api/teardown":
                    b = self._body()
                    return self._send(200, {"job": app.teardown(int(b["project_id"]), int(b["iid"]))})
                if method == "POST" and path == "/api/agent":
                    b = self._body()
                    return self._send(200, {"job": app.run_agent(b.get("name"), int(b["project_id"]), int(b["iid"]))})
                return self._err(404, "Nicht gefunden.")
            except UserError as e:
                hlog.warning("%s %s abgelehnt: %s", method, scrub(path), e)
                if e.data:
                    return self._send(400, dict(e.data, error=scrub(str(e))))
                return self._err(400, str(e))
            except (KeyError, TypeError, ValueError) as e:
                hlog.warning("%s %s: ungültige Anfrage (%s)", method, scrub(path), repr(e))
                return self._err(400, "Ungültige Anfrage.")
            except Exception as e:  # nie den Server abstürzen lassen
                hlog.exception("Unbehandelter Fehler bei %s %s", method, scrub(path))
                return self._err(500, "Interner Fehler, siehe Konsole.")

        def _settings(self, method, path):
            stored = _stored(app)
            if method == "GET" and path == "/api/settings":
                return self._send(200, dict(settings.view(app.cfg if not app.demo else load_config(None), app.config_path),
                                            demo=app.demo, problems=list(app.problems), configured=app.configured))
            if method != "POST":
                return self._err(404, "Nicht gefunden.")
            body = self._body()
            if path == "/api/settings/test/gitlab":
                res = settings.test_gitlab(body, stored)
                hlog.info("Test GitLab: %s", "ok" if res["ok"] else "; ".join("%s: %s" % (x["title"], x["detail"]) for x in res["steps"] if x["status"] == "fail"))
                return self._send(200, res)
            if path == "/api/settings/test/jira":
                res = settings.test_jira(body, stored)
                hlog.info("Test Jira: %s", "ok" if res["ok"] else "; ".join("%s: %s" % (x["title"], x["detail"]) for x in res["steps"] if x["status"] == "fail"))
                return self._send(200, res)
            if path == "/api/settings/test/sonar":
                res = settings.test_sonar(body, stored)
                hlog.info("Test Sonar: %s", "ok" if res["ok"] else "; ".join("%s: %s" % (x["title"], x["detail"]) for x in res["steps"] if x["status"] == "fail"))
                return self._send(200, res)
            if path == "/api/settings/test/github":
                res = settings.test_github(body, stored)
                hlog.info("Test GitHub: %s", "ok" if res["ok"] else "; ".join("%s: %s" % (x["title"], x["detail"]) for x in res["steps"] if x["status"] == "fail"))
                return self._send(200, res)
            if path == "/api/settings/github/repos":
                return self._send(200, settings.search_github(body, stored))
            if path == "/api/settings/test/agent":
                res = settings.test_agent(body, stored)
                hlog.info("Test Agent: %s", "ok" if res["ok"] else "; ".join("%s: %s" % (x["title"], x["detail"]) for x in res["steps"] if x["status"] == "fail"))
                return self._send(200, res)
            if path == "/api/settings/test/mcp":
                return self._send(200, settings.test_mcp(body, stored))
            if path == "/api/settings/test/llm":
                res = settings.test_llm(body, stored)
                hlog.info("Test KI: %s", "ok" if res["ok"] else "; ".join("%s: %s" % (x["title"], x["detail"]) for x in res["steps"] if x["status"] == "fail"))
                for x in res["steps"]:
                    if x["status"] == "warn":
                        hlog.warning("Test KI, Warnung bei «%s»: %s", x["title"], x["detail"])
                return self._send(200, res)
            if path == "/api/settings/projects":
                return self._send(200, settings.search_projects(body, stored))
            if path == "/api/settings/identity":
                return self._send(200, settings.suggest_identity(body, stored))
            if path == "/api/settings/save":
                if app.demo:
                    return self._err(400, "Im Demo-Modus werden keine Einstellungen gespeichert.")
                disk = {}
                if app.config_path.exists():
                    with open(app.config_path, encoding="utf-8") as f:
                        disk = json.load(f)
                new, errors = settings.build_config(disk, body)
                if errors:
                    return self._send(400, {"error": "Einige Angaben sind ungültig.", "errors": errors})
                where, serr = settings.save_secrets(body)
                if serr:
                    return self._send(400, {"error": "Secret konnte nicht gespeichert werden.", "errors": serr})
                settings.write_config(app.config_path, new)
                changed = sorted(k for k in set(disk) | set(new) if disk.get(k) != new.get(k))
                app.audit("settings.save", "", sections=changed, stored=sorted(where))
                log.info("Einstellungen gespeichert: GitLab %s, Jira %s, %d Projekt(e), Secrets neu: %s",
                         new.get("gitlab_url") or "-", (new.get("jira") or {}).get("url") or "-", len(new["projects"]),
                         ", ".join(where) or "keine")
                app.reload()
                return self._send(200, {"saved": True, "secrets": where, "problems": list(app.problems), "configured": app.configured})
            return self._err(404, "Nicht gefunden.")

        def do_GET(self):
            self._route("GET")

        def do_POST(self):
            self._route("POST")

        def do_PATCH(self):
            self._route("PATCH")

        def do_DELETE(self):
            self._route("DELETE")

    return Handler


# ---------------------------------------------------------------- Secrets beim Start
def _env_hints(cfg):
    return {"gitlab_token": [cfg.get("token_env")]}


def resolve_secrets(cfg, demo, show=False):
    """Löst die Secrets auf, die da sind. Fehlendes ist kein Abbruch (die Einstellungsseite behebt es).
    Nennt auf Wunsch die Quellen, nie die Werte."""
    spec = cfg.get("secrets") or {}
    jc = jira_cfg(cfg)
    names = [] if demo else ["gitlab_token"]
    if not demo and jc["url"]:
        names.append("jira_token" if jc["auth"] == "bearer" else "jira_password")
    names.append("access_token")
    if llm_cfg(cfg).get("enabled"):
        names.append("llm_key")
    if not demo and sonar_cfg(cfg).get("enabled"):
        names.append("sonar_token")
    if not demo and github_cfg(cfg).get("enabled"):
        names.append("github_token")
    if time_cfg(cfg).get("mcp_url"):
        names.append("mcp_token")
    out = {}
    for name in names:
        try:
            val, src = store.resolve(name, spec.get(name), _env_hints(cfg).get(name, ()))
        except store.SecretError as e:
            log.error("Secret %s: %s", name, e)
            if show:
                print("  %-14s FEHLER: %s" % (name, e))
            continue
        if val:
            out[name] = val
            log.info("Secret %s ← %s", name, src)
            if show:
                print("  %-14s ← %s" % (name, src))
        elif show and name not in ("access_token", "llm_key", "mcp_token"):
            print("  %-14s nicht gesetzt (Einstellungen im Browser)" % name)
    return out


def run_preflight(cfg, config_path, demo):
    """Prüft alles, was für einen echten Lauf nötig ist, und sagt bei Fehlern, was zu tun ist. Gibt 0 (alles gut) oder 1 zurück."""
    import types
    problems = [0]
    marks = {"ok": "  OK  ", "warn": " WARN ", "fail": " FAIL ", "skip": " skip ", "info": "      "}

    def line(status, title, detail=""):
        if status == "fail":
            problems[0] += 1
        print("%s%s%s" % (marks.get(status, "      "), title, (": " + str(detail)) if detail else ""))

    def steps(title, res):
        print("\n%s" % title)
        for st in res["steps"]:
            line(st["status"], st["title"], st["detail"])
            if st["status"] in ("fail", "warn") and st.get("hint"):
                print("        → %s" % st["hint"])

    print("tinyops %s Preflight (%s)" % (VERSION, "Demo" if demo else "Echtbetrieb"))
    print("\nBasis")
    line("ok" if Path(config_path).exists() else ("info" if demo else "warn"), "Config", str(config_path) if Path(config_path).exists() else "keine Datei: %s" % config_path)
    for what, d in (("Datenordner", data_dir(cfg)), ("Logordner", (tlog.log_file(cfg) or Path(".")).parent)):
        try:
            Path(d).mkdir(parents=True, exist_ok=True)
            probe = Path(d) / (".preflight-%d" % os.getpid())
            probe.write_text("x")
            probe.unlink()
            line("ok", what, "%s (beschreibbar)" % d)
        except OSError as e:
            line("fail", what, "%s nicht beschreibbar: %s" % (d, e.strerror or e))
    secrets = resolve_secrets(cfg, demo)
    if not demo:
        line("ok" if secrets.get("gitlab_token") else "fail", "GitLab-Token", "gefunden" if secrets.get("gitlab_token") else "fehlt (TINYOPS_GITLAB_TOKEN, --set-secret oder Einstellungen)")
    jc = jira_cfg(cfg)
    if sonar_cfg(cfg).get("enabled") and not demo:
        line("ok" if secrets.get("sonar_token") else "fail", "Sonar-Token", "gefunden" if secrets.get("sonar_token") else "fehlt (TINYOPS_SONAR_TOKEN, Einstellungen)")
    if github_cfg(cfg).get("enabled") and not demo:
        line("ok" if secrets.get("github_token") else "fail", "GitHub-Token", "gefunden" if secrets.get("github_token") else "fehlt (TINYOPS_GITHUB_TOKEN, Einstellungen)")
    if jc["url"] and not demo:
        n = "jira_token" if jc["auth"] == "bearer" else "jira_password"
        line("ok" if secrets.get(n) else "fail", "Jira-Zugang (%s)" % n, "gefunden" if secrets.get(n) else "fehlt")
    local = cfg["bind"] in LOOPBACK
    line("ok" if local or secrets.get("access_token") else "fail", "Zugriffsschutz",
         "nur lokal (%s)" % cfg["bind"] if local else ("bind %s mit Zugriffstoken, erlaubte Hosts: %s" % (cfg["bind"], ", ".join(cfg["allowed_hosts"]) or "nur localhost")
                                                       if secrets.get("access_token") else "bind %s ohne access_token: das Panel startet so nicht" % cfg["bind"]))
    if demo:
        line("info", "Demo", "GitLab/Jira-Prüfungen entfallen")
    else:
        stored = _stored(types.SimpleNamespace(cfg=cfg))
        if not cfg.get("gitlab_url"):
            line("fail", "GitLab", "keine Adresse in der Config (gitlab_url)")
        else:
            steps("GitLab", settings.test_gitlab({"url": cfg["gitlab_url"], "ca_bundle": cfg.get("ca_bundle", ""),
                                                  "projects": [p["id"] for p in cfg["projects"]]}, stored))
        if jc["url"]:
            steps("Jira", settings.test_jira({"url": jc["url"], "auth": jc["auth"], "username": jc.get("username", ""), "ca_bundle": cfg.get("ca_bundle", ""),
                                              "project_keys": jc.get("project_keys") or [], "issue_types": jc.get("wip_issue_types") or [],
                                              "jql": jc.get("jql_in_progress") or "", "story_limit": jc.get("story_limit", 2),
                                              "only_active_sprints": bool(jc.get("only_active_sprints", True))}, stored))
        else:
            print("\nJira\n%snicht eingerichtet" % marks["info"])
        uc = usage_cfg(cfg)
        if uc.get("claude") or uc.get("codex"):
            print("\nKI-Kontingent")
            for k in ("claude", "codex"):
                if uc.get(k):
                    r = usage.fetch(k, uc.get(k + "_file") or None)
                    line("ok" if r["ok"] else "warn", r["name"], ", ".join("%s: %s %% frei" % (w["label"], w["left_pct"]) for w in r["windows"]) if r["ok"] else r["error"])
        sc = sonar_cfg(cfg)
        if sc.get("enabled"):
            steps("Sonar", settings.test_sonar({"url": sc["url"], "ca_bundle": cfg.get("ca_bundle", ""),
                                                "projects": [{"id": p["id"], "name": p.get("name"), "sonar_key": p.get("sonar_key", "")} for p in cfg["projects"]]}, stored))
        lc = llm_cfg(cfg)
        if lc.get("enabled"):
            steps("Lokales Sprachmodell", settings.test_llm({"provider": lc["provider"], "url": lc["url"], "model": lc.get("model", ""),
                                                             "allow_remote": lc.get("allow_remote"), "timeout": lc.get("timeout", 120)}, stored))
    print("\nSynchronisation (ein echter Durchlauf, nur lesend)")
    if problems[0] and not demo:
        line("skip", "Durchlauf", "übersprungen, solange oben etwas fehlschlägt")
    else:
        app = App(cfg, demo, secrets, config_path)
        if not app.configured and not demo:
            line("fail", "Durchlauf", "; ".join(app.problems) or "nicht eingerichtet")
        else:
            t0 = time.time()

            def step(sid, title, status, detail=""):
                if status in ("ok", "err"):
                    line("ok" if status == "ok" else "fail", title, detail)
            try:
                data = app._refresh({"mine": [], "review": [], "assigned": [], "errors": [], "me": ""}, step)
            except Exception as e:   # auch ein Absturz ist ein Befund
                line("fail", "Durchlauf", "%s: %s" % (type(e).__name__, e))
            else:
                sq = data.get("sonar") or {}
                if sq.get("enabled"):
                    line("info", "Sonar", "%d Quality Gates geprüft, %d nicht bestanden" % (sq.get("checked", 0), sq.get("red", 0)))
                j = data.get("jira") or {}
                line("info", "Ergebnis", "%d eigene Einträge, %d Review, %d zugeteilt, %s in %.1f s" % (
                    len(data["mine"]), len(data["review"]), len(data["assigned"]),
                    "%d Stories in Arbeit" % len(j.get("stories", [])) if j.get("ok") else "Jira nicht verbunden", time.time() - t0))
    print("\n%s" % ("Alles bereit." if not problems[0] else "%d Problem(e). Details und Hinweise stehen oben." % problems[0]))
    return 1 if problems[0] else 0


def run_selftest(cfg):
    """Prüft die eigenen Teile (ohne deine Daten zu ändern) und spielt die Kernfunktionen mit Demo-Daten in einem leeren Ordner durch."""
    import shutil
    import tempfile
    steps = []
    step = lambda sid, title, status, detail="": steps.append({"id": sid, "title": title, "status": status, "detail": scrub(detail)})
    t0 = time.time()
    try:
        text = (BASE / "QA-CHECKLIST.md").read_text(encoding="utf-8")
    except OSError:
        text = ""
    qa.check_static(BASE, VERSION, text, agents.HELPERS, step)
    db = data_dir(cfg) / "tinyops.db"
    qa.check_db(db, audit.AuditLog(db), step)
    tmp = tempfile.mkdtemp(prefix="tinyops-selftest-")
    try:
        c = load_config(None)
        c.update(data_dir=tmp, log_level=cfg.get("log_level", "info"), log_dir=cfg.get("log_dir", ""))
        a = App(c, True, {}, Path(tmp) / "config.json", watchdog=False)
        ov = a.overview()
        cards = {x["id"]: x for x in ov["board"]["cards"]}
        step("demo", "Demo-Daten laden", "ok" if len(cards) >= 5 and ov.get("flow") else "fail", "%d Vorhaben, Ablauf %s" % (len(cards), "da" if ov.get("flow") else "fehlt"))
        a.board_action("stage", {"key": "DLP-104", "stage": "impl"})
        a.flow_action("complete", {"id": "DLP-104", "phase": 2})
        ph = a.overview()["flow"]["items"]["DLP-104"]["phase"]
        step("flow", "Station und «Schritt erledigt»", "ok" if ph >= 3 else "fail", "DLP-104 steht bei %s" % flow.PHASES[ph][1])
        v = a.audit_log.verify()
        step("audit_w", "Verlauf schreibt", "ok" if v["ok"] and v["count"] == 2 else "fail", "%d Einträge (erwartet 2), Kette %s" % (v["count"], "ok" if v["ok"] else "gebrochen"))
        a.flow_action("pin", {"id": "DLP-104"})
        now = time.time()
        a.timebook.stop()
        a.timebook.add_segment("DLP-104", "Installer: Upgrade-Test", now - 3000, now - 0)
        day = a.time_day()
        dr = next((x for x in day["drafts"] if x["ticket"] == "DLP-104"), None)
        ok = bool(dr) and dr["minutes"] in (45, 60)
        if ok:
            a.time_action("confirm", {"id": dr["id"]})
            ok = a.timebook.draft(dr["id"])["state"] == "bestätigt"
        step("time", "Zeitentwurf", "ok" if ok else "fail", "50 min → %s min, bestätigt ohne MCP" % (dr or {}).get("minutes", "?"))
        rv = a.review_topics({"host": "gitlab", "project_id": 1, "iid": 41})
        md = a.review_export({"host": "gitlab", "project_id": 1, "iid": 41})["text"]
        step("review", "Offene Review-Punkte", "ok" if len(rv["topics"]) == 3 and "### Punkt 3" in md else "fail", "%d Punkte, Prompt %d Zeichen" % (len(rv["topics"]), len(md)))
        a.ideas.add("Selbsttest: Export als CSV")
        iid = a.ideas.list()[0]["id"]
        ra = a.idea_assess(iid, {"manual": True, "recommendation": "später", "benefit": "2", "effort": "S", "category": "Feature"})
        td = a.ticket_draft({"idea_id": iid})
        ok = ra["recommendation"] == "später" and "h3. Akzeptanzkriterien" in td["draft"]["description"]
        step("idea", "Idee bewerten und Ticket-Entwurf", "ok" if ok else "fail", "Bewertung gespeichert, Entwurf mit Story und Akzeptanzkriterien")
        q = a.qa_view()
        step("qa", "Prüfliste lesen", "ok" if q["sections"] else "warn", "%d Abschnitte" % len(q["sections"]))
    except Exception as e:      # der Selbsttest meldet, statt abzustürzen
        log.exception("Selbsttest")
        step("smoke", "Kernfunktionen", "fail", "%s: %s" % (type(e).__name__, e))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return {"ok": not any(x["status"] == "fail" for x in steps), "steps": steps, "version": VERSION, "secs": round(time.time() - t0, 1)}


def run_audit_cli(cfg, verify, export_to):
    db = data_dir(cfg) / "tinyops.db"
    if not db.exists():
        print("Kein Verlauf: %s gibt es nicht." % db)
        return 1 if verify else 0
    al = audit.AuditLog(db)
    v = al.verify()
    if export_to:
        body = json.dumps({"exported": time.time(), "instance": al.instance(), "verify": v, "rows": al.export()}, ensure_ascii=False, indent=1)
        if export_to == "-":
            print(body)
        else:
            Path(export_to).write_text(body + "\n", encoding="utf-8")
            print("%d Einträge nach %s geschrieben." % (v["count"], export_to))
    if verify:
        if v["ok"]:
            print("Verlauf in Ordnung: %d Einträge, Instanz %s, letzter Hash %s" % (v["count"], al.instance(), v.get("last_hash", "")[:16]))
        else:
            print("Verlauf GEBROCHEN bei Eintrag %s: %s (%d Einträge)" % (v["broken_at"], v["reason"], v["count"]))
    return 0 if v["ok"] or not verify else 1


def main():
    ap = argparse.ArgumentParser(description="tinyops Arbeitspanel")
    ap.add_argument("--config", default=str(default_config_path()), help="Standard: ~/.config/tinyops/config.json (oder $TINYOPS_HOME)")
    ap.add_argument("--demo", action="store_true", help="erfundene Daten, weder GitLab noch Jira nötig")
    ap.add_argument("--set-secret", metavar="NAME", help="Secret sicher speichern (%s)" % ", ".join(store.NAMES))
    ap.add_argument("--delete-secret", metavar="NAME", help="Secret löschen")
    ap.add_argument("--list-secrets", action="store_true", help="zeigt, woher welches Secret kommt (nie den Wert)")
    ap.add_argument("--preflight", action="store_true", help="prüft Config, Secrets, GitLab, Jira und Sprachmodell und macht einen Probe-Durchlauf (Exit-Code 1 bei Problemen)")
    ap.add_argument("--version", action="version", version="tinyops " + VERSION)
    ap.add_argument("-v", "--verbose", action="store_true", help="Log auf DEBUG: jede Anfrage, jede Branch-Entscheidung")
    ap.add_argument("--log-level", choices=sorted(tlog.LEVELS), help="debug, info, warning oder error (sonst config.json, Standard info)")
    ap.add_argument("--show-log", nargs="?", const=100, type=int, metavar="N", help="letzte N Logzeilen zeigen und beenden")
    ap.add_argument("--selftest", action="store_true", help="prüft die eigenen Teile und spielt die Kernfunktionen mit Demo-Daten durch (Exit-Code 1 bei Fehlern)")
    ap.add_argument("--verify-audit", action="store_true", help="prüft die Hash-Kette des Verlaufs (Exit-Code 1, wenn sie gebrochen ist)")
    ap.add_argument("--export-audit", metavar="DATEI", help="Verlauf als JSON in DATEI schreiben (- = Standardausgabe)")
    args = ap.parse_args()
    migrated = migrate_legacy(args.config) if args.config == str(default_config_path()) else []
    path = args.config if Path(args.config).exists() else None
    level = "debug" if args.verbose else args.log_level

    if args.show_log is not None:
        cfg0 = load_config(path)
        lines = tlog.tail(cfg0, args.show_log)
        print("Log: %s" % tlog.log_file(cfg0))
        print("\n".join(lines) if lines else "(noch leer)")
        return

    if args.selftest:
        cfg0 = load_config(path)
        tlog.setup(cfg0, level, console=False)
        res = run_selftest(cfg0)
        for x in res["steps"]:
            print("  %-4s %-32s %s" % ({"ok": "OK", "warn": "WARN", "fail": "FAIL"}.get(x["status"], x["status"]), x["title"], x["detail"]))
        print("Selbsttest %s in %.1f s." % ("bestanden" if res["ok"] else "FEHLGESCHLAGEN", res["secs"]))
        raise SystemExit(0 if res["ok"] else 1)
    if args.verify_audit or args.export_audit:
        cfg0 = load_config(path)
        raise SystemExit(run_audit_cli(cfg0, args.verify_audit, args.export_audit))

    try:
        if args.set_secret:
            tlog.setup(load_config(path), level, console=False)
            value = store.read_secret_interactive(args.set_secret)
            where = store.set_secret(args.set_secret, value)
            log.info("Secret %s gespeichert in: %s", args.set_secret, where)
            print("%s gespeichert in: %s" % (args.set_secret, where))
            return
        if args.delete_secret:
            tlog.setup(load_config(path), level, console=False)
            removed = store.delete_secret(args.delete_secret)
            log.info("Secret %s gelöscht aus: %s", args.delete_secret, ", ".join(removed) or "nirgends")
            print("gelöscht aus: %s" % (", ".join(removed) if removed else "nirgends gefunden"))
            return
        if args.list_secrets:
            cfg = load_config(path)
            print("Secrets (Quellen, nie Werte):")
            print("\n".join(store.describe(cfg.get("secrets"), _env_hints(cfg))))
            return
    except store.SecretError as e:
        raise SystemExit(str(e))

    cfg = load_config(path)
    config_path = Path(path) if path else Path(args.config)
    if args.preflight:
        tlog.setup(cfg, level, console=False)
        raise SystemExit(run_preflight(cfg, config_path, args.demo))
    logfile = tlog.setup(cfg, level)
    for n in migrated:
        log.info(n)
        print(n)
    log.info("tinyops %s startet (Python %s, %s)", VERSION, sys.version.split()[0], "Demo" if args.demo else "Echtbetrieb")
    log.info("Config: %s, %d Projekt(e), Log: %s", path or "(keine, Ersteinrichtung im Browser)", len(cfg["projects"]), logfile or "nur Konsole")
    print("Secrets:")
    secrets = resolve_secrets(cfg, args.demo, show=True)
    if cfg["bind"] not in LOOPBACK and not secrets.get("access_token"):
        raise SystemExit("bind=%s ist nicht nur lokal erreichbar. Setze erst einen Zugriffstoken: "
                         "python3 server.py --set-secret access_token" % cfg["bind"])
    warn_plain_http(cfg["gitlab_url"], "GitLab")
    warn_plain_http(jira_cfg(cfg)["url"], "Jira")
    app = App(cfg, args.demo, secrets, config_path)
    srv = ThreadingHTTPServer((cfg["bind"], cfg["port"]), make_handler(app))
    log.info("Lauscht auf http://%s:%d (Zugriffstoken: %s, erlaubte Hosts: %s)", cfg["bind"], cfg["port"],
             "ja" if secrets.get("access_token") else "nein", ", ".join(cfg["allowed_hosts"]) or "nur lokal")
    print("tinyops läuft auf http://%s:%d %s" % (cfg["bind"], cfg["port"], "(Demo)" if args.demo else ""))
    if not app.configured and not args.demo:
        print("Noch nicht eingerichtet: Öffne die Adresse im Browser, dort liegt die Seite «Einstellungen» (GitLab und Jira verbinden).")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        log.info("Beendet (Ctrl+C)")


if __name__ == "__main__":
    main()
