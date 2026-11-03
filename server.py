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

import fnmatch
import links
import llm
import net
import secretstore as store
import settings
import sprint
import tlog
from net import NoRedirect  # noqa: F401  (Wiederverwendung in Tests)
from secretstore import scrub

VERSION = "1.5"
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
    "cache_seconds": 30,
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
    pass


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
    return cfg


def jira_cfg(cfg):
    j = dict(JIRA_DEFAULTS)
    j.update(cfg.get("jira") or {})
    return j


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
        return rows

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


# ---------------------------------------------------------------- GitLab
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
        item = {
            "kind": kind, "project_id": pid,
            "project": project_name, "title": mr["title"],
            "branch": mr["source_branch"], "iid": mr["iid"], "url": mr["web_url"],
            "draft": bool(mr.get("draft") or mr.get("work_in_progress")),
            "pipeline": pipeline, "pipeline_url": purl,
            "updated_at": mr.get("updated_at", ""), "sha": mr.get("sha", ""),
            "author": (mr.get("author") or {}).get("username", ""),
            "can_deploy": pid in self.proj_cfg,
        }
        item["age_days"] = age_days(item["updated_at"])
        item["state"] = derive_state(item) if kind == "mr" else "review"
        return item

    def _identity(self, me):
        bf = branch_cfg(self.cfg)

        def low(xs):
            return {str(x).strip().lower() for x in xs if str(x).strip()}

        emails = low(list(self.cfg["my_emails"]) + list(bf["emails"]) +
                     [me.get("email") or "", me.get("public_email") or "", me.get("commit_email") or ""])
        names = low(list(bf["names"]) + [me.get("name") or ""])
        return {"emails": emails, "names": names,
                "agent_emails": low(bf["agent_emails"]), "agent_names": low(bf["agent_names"]),
                "patterns": [p.lower() for p in bf["agent_message_patterns"] if p]}

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
                    })
                glog.info("%s: %d eigene MRs (%d ignoriert), %d Branches geprüft, %d angezeigt, %d zu alt", name, len(mrs),
                          ignored_mrs, checked, shown_b, skipped)
                return "ok", "%d MR, %d Branches" % (len(mrs) - ignored_mrs, shown_b)
            except UserError as e:
                glog.error("%s: %s", name, e)
                errors.append("%s: %s" % (name, e))
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
        sink.update(me="demo", errors=[])
        sink.setdefault("mine", []).extend(mine[:4])
        pause("gl-1", "Projekt dlp-core", "4 MR")
        sink["mine"].extend(mine[4:])
        sink.setdefault("review", []).extend(review)
        pause("gl-2", "Projekt dlp-ui", "3 Branches")
        pause("gl-review", "Review-Queue", "%d MR" % len(review))
        sink.setdefault("assigned", []).extend(assigned)
        pause("gl-assigned", "Mir zugeteilte MRs", "%d MR" % len(assigned))
        return sink

    def mr(self, project_id, iid):
        return {"title": "Demo-MR %s" % iid, "branch": "feature/DLP-101-demo-%s" % iid,
                "sha": "a1b2c3d4e5f60718", "url": "https://gitlab.example/demo/%s" % iid}


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
    def __init__(self, cfg, demo, secrets, config_path=None):
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

    def apply(self, cfg, secrets):
        """Baut Clients und Zwischenspeicher aus Config und Secrets neu. Läuft beim Start und nach dem Speichern der Einstellungen.
        Fehlende oder falsche Angaben stoppen nichts: Sie erscheinen als «problems», damit man sie in den Einstellungen beheben kann."""
        self.cfg = cfg
        self.jc = jira_cfg(cfg)
        self.lc = llm_cfg(cfg)
        self.llm_key = secrets.get("llm_key", "")
        self.store = links.Store(data_dir(cfg) / "tinyops.db")
        self._types_cache = {}
        self._by_key = {}
        self.problems = []
        self.client, self.jira = None, None
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
            if not self.proj_cfg:
                self.proj_cfg = {1: {"id": 1, "name": "dlp-core", "chart": "./helm/dlp-core"}}
            return
        try:
            ctx = make_ssl(cfg)
        except SystemExit as e:
            self.problems.append(str(e))
            ctx = ssl.create_default_context()
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
        for pr in self.problems:
            log.warning("Konfiguration unvollständig: %s", pr)

    @property
    def configured(self):
        return self.client is not None

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
            allowed = self.jc.get("project_keys")
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
            steps = sorted((dict(x) for x in sy["steps"]), key=lambda x: x["id"] == "ji-link")   # Verknüpfen kommt zuletzt
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
                 "draft": bool(it.get("draft")), "ref": it.get("ref", ""), "author": it.get("author", "")}
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
        pools = {}
        for p in self.store.pools():
            for i in p["items"]:
                pools.setdefault(i["value"], []).append(p["name"])
        jira_prog = {st["key"] for st in (j or {}).get("stories", [])}
        keys = set(jira_prog) | set(known) | {k for k in stages if not links.is_ref_key(k)} | set(self.store.pool_tickets())

        mine_keys = {k for it in data["mine"] for k in it.get("keys", [])}

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
            card = {"id": k, "key": k, "title": (tk or {}).get("summary", ""), "status": (tk or {}).get("status", ""), "url": (tk or {}).get("url", ""),
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
        board = {"cards": [c for c in cards if c["id"] not in hide], "done_hidden": len(hide), "stages": list(links.STAGES)}
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
                "project_id": it["project_id"], "manual": False, "draft": bool(it.get("draft")), "ref": it.get("ref", ""), "author": it.get("author", "")}

    def board_action(self, action, body):
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
            return {"key": self._local(st.stage_set, key, body.get("stage"))}
        if action == "add":
            title = str(body.get("title") or "").strip()
            stage = body.get("stage") or "planned"
            if re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{1,19}-\d{1,9}", title):   # ein Jira-Key: Ticket aufs Board holen
                key = self._local(links.norm_ticket, title)
                self._check_ticket_exists(key)
                self._learn(key)
                return {"key": self._local(st.stage_set, key, stage)}
            self.cache_t = 0.0
            return {"key": self._local(st.task_add, title, stage)}
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
            key = self._local(st.task_add, idea["text"].split("\n")[0][:200], body.get("stage") or "planned")
            self.ideas.set_status(iid, "erledigt")
            self.cache_t = 0.0
            return {"key": key}
        raise UserError("Unbekannte Aktion.")

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

        def pre():
            pre_thread.join()
            if "e" in pre_holder:
                raise pre_holder["e"]
            return pre_holder["v"]
        try:
            data = self.client.fetch(sink, step)
        except UserError as e:
            rlog.error("GitLab-Abfrage fehlgeschlagen: %s", e)
            step("gl-user", "Bei GitLab anmelden", "err", str(e))
            data = sink if sink is not None else {}
            data.setdefault("me", "")
            for k in ("mine", "review", "assigned"):
                data.setdefault(k, [])
            data.setdefault("errors", []).append(str(e))
        for it in data["mine"] + data["review"] + data["assigned"]:
            it["ref"] = links.ref_of(it["project_id"], it["branch"])
        if self.jira:
            step("ji-link", "Tickets mit Branches verknüpfen", "run")
            data["jira"] = self._jira_data(data, pre)
            j = data["jira"]
            step("ji-link", "Tickets mit Branches verknüpfen", "err" if not j["ok"] else "ok", j.get("error", "") if not j["ok"] else "")
            if not j["ok"]:
                self._by_key = {}
        else:
            data["jira"] = None
        rlog.info("Auffrischen #%d fertig in %.1f s: %d eigene Einträge, %d Review, %d zugeteilt, %d Fehler",
                  self.refresh_no, time.time() - t0, len(data["mine"]), len(data["review"]), len(data["assigned"]),
                  len(data["errors"]))
        return data

    def _partial_view(self):
        """Zwischenstand während der ersten Synchronisation: schon geladene Listen, Jira-Stories ohne Zuordnung."""
        p = self.partial or {}
        data = {"me": p.get("me", ""), "mine": [dict(i) for i in p.get("mine", [])], "review": [dict(i) for i in p.get("review", [])],
                "assigned": [dict(i) for i in p.get("assigned", [])], "errors": list(p.get("errors", [])), "partial": True}
        for it in data["mine"] + data["review"] + data["assigned"]:
            it["ref"] = links.ref_of(it["project_id"], it["branch"])
            it["keys"] = extract_keys("%s %s" % (it["branch"], it["title"]), self.jc.get("project_keys")) if self.jira else []
        if self.jira:
            st = self.early_stories
            data["jira"] = {"enabled": True, "ok": st is not None, "loading": st is None, "partial": True, "limit": int(self.jc["story_limit"]),
                            "count": len(st or []), "over": False, "url": self.jira.base, "error": "", "sprints": [],
                            "only_active": bool(self.jc.get("only_active_sprints", True)),
                            "stories": [dict(x, items=[], no_mr=False, in_progress=True) for x in (st or [])]}
        else:
            data["jira"] = None
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
        pid, branch = self._ref(body)
        key = self._local(links.norm_ticket, body.get("ticket"))
        self._check_ticket_exists(key)
        self._local(self.store.link, pid, branch, key)
        log.info("Verknüpfung gesetzt: %s:%s → %s", pid, branch, key)
        self.cache_t = 0.0
        return {"ticket": key}

    def unlink_ticket(self, body):
        pid, branch = self._ref(body)
        removed = self._local(self.store.unlink, pid, branch)
        log.info("Verknüpfung gelöst: %s:%s", pid, branch)
        self.cache_t = 0.0
        return {"removed": removed}

    def pool_action(self, action, body):
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
        res = self.jira.create_issue(project, itype, summary, description)
        jlog.info("Ticket %s angelegt (%s, %d Zeichen Beschreibung)", res["key"], itype, len(description))
        self.cache_t = 0.0   # beim nächsten Abruf neu lesen
        return res

    # -- Übersicht
    def overview(self, wait=True):
        """wait=True wartet auf eine frische Synchronisation (Tests, Skripte). wait=False liefert sofort, was da ist: den Zwischenspeicher
        oder, solange noch nichts vollständig geladen ist, den Zwischenstand."""
        if not self.configured:
            return {"configured": False, "problems": list(self.problems), "me": "", "mine": [], "review": [], "assigned": [],
                    "errors": [], "jira": None, "wip": 0, "wip_limit": self.cfg["wip_limit"], "stale_days": self.cfg["stale_days"],
                    "demo": self.demo, "features": {k: self.has(k) for k in settings.CONFIG_KEYS_FEATURES},
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
        for it in data["mine"] + data["review"] + data["assigned"]:
            it["stale"] = it["age_days"] >= stale
        data["board"] = self._board(data)
        data.update({
            "wip": len(data["mine"]), "wip_limit": self.cfg["wip_limit"],
            "stale_days": stale, "demo": self.demo, "agent_enabled": bool(self.cfg["agent_command"]),
            "prompts": self.prompt_names() if self.has("testenv") else [], "fetched": time.time(),
            "helpdesk": self.helpdesk(), "configured": True, "problems": list(self.problems),
            "features": {k: self.has(k) for k in settings.CONFIG_KEYS_FEATURES},
            "ignore_patterns": list(branch_cfg(self.cfg).get("ignore_branches") or []),
            "ticket": self.ticket_meta(),
            "pools": self.pools_view(data),
            "ai": self.store.ai_accounts() if self.has("ai") else [],
        })
        return data

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
        return self.jobs.start(title, argv, cwd)

    def teardown(self, project_id, iid):
        self._check_cluster()
        proj, vals = self._mr_vars(project_id, iid)
        self._guard_namespace(vals["namespace"])
        argv = self._argv(proj.get("teardown_command", self.cfg["teardown_command"]), vals)
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
                         "testenv" if path.startswith(("/api/jobs", "/api/deploy", "/api/teardown", "/api/agent", "/api/prompt")) else "")
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
        elif show and name not in ("access_token", "llm_key"):
            print("  %-14s nicht gesetzt (Einstellungen im Browser)" % name)
    return out


def main():
    ap = argparse.ArgumentParser(description="tinyops Arbeitspanel")
    ap.add_argument("--config", default=str(default_config_path()), help="Standard: ~/.config/tinyops/config.json (oder $TINYOPS_HOME)")
    ap.add_argument("--demo", action="store_true", help="erfundene Daten, weder GitLab noch Jira nötig")
    ap.add_argument("--set-secret", metavar="NAME", help="Secret sicher speichern (%s)" % ", ".join(store.NAMES))
    ap.add_argument("--delete-secret", metavar="NAME", help="Secret löschen")
    ap.add_argument("--list-secrets", action="store_true", help="zeigt, woher welches Secret kommt (nie den Wert)")
    ap.add_argument("-v", "--verbose", action="store_true", help="Log auf DEBUG: jede Anfrage, jede Branch-Entscheidung")
    ap.add_argument("--log-level", choices=sorted(tlog.LEVELS), help="debug, info, warning oder error (sonst config.json, Standard info)")
    ap.add_argument("--show-log", nargs="?", const=100, type=int, metavar="N", help="letzte N Logzeilen zeigen und beenden")
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
