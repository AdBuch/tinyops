#!/usr/bin/env python3
"""tinyops: kleines lokales Arbeitspanel (nur Python-Standardbibliothek).

Zeigt deine Branches/MRs mit Pipeline-Status, verknüpft sie mit Jira-Tickets, überwacht das Story-Limit,
die Review-Queue und den Helpdesk, startet Agenten und bucht Zeit über BCS. Kein Approve, kein Merge,
kein Push. Zugangsdaten liegen im Secret-Speicher (siehe secretstore.py), nie in der config.json.

Hier liegen Config, die App (Zustand und Aktionen) und der Start. Seit 0.37 eigene Module:
routes.py (HTTP, Zugang, Routentabelle), common.py, httpclient.py, gitlab_client.py, jira_client.py,
ideas.py, demo.py.
"""
import argparse
import http.client
import json
import os
import shutil
import ssl
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta
from http.server import ThreadingHTTPServer
from pathlib import Path

import agents
import audit
import focusplan
import helpdesk
import workspaces
import briefing
import m365
import bcs
import devices
import qa
import review
import timesheet
import ux
import flow
import github
import links
import sonar
import aiquota
import net
import secretstore as store
import settings
import tlog
from net import NoRedirect  # noqa: F401  (Wiederverwendung in Tests)
from secretstore import scrub
# 0.37: aus server.py gelöst; die Namen bleiben hier erreichbar (Tests, Werkzeuge)
import routes
from common import (LOOPBACK, HttpStatus, UserError, _age_key, _env_hints, _stored, age_days, extract_keys, hours_since,  # noqa: F401
                    ignored_branch, make_ssl, parse_ts, render, slug, warn_plain_http)
from demo import DemoClient, DemoHelpdesk, DemoJira, DemoSonar, demo_workspaces  # noqa: F401
from gitlab_client import (BRANCH_DEFAULTS, GitLabClient, branch_cfg, classify_commits, derive_state, identity,  # noqa: F401
                           ref_slug)
from httpclient import Http  # noqa: F401
from ideas import Ideas, similar  # noqa: F401
from jira_client import JiraClient, jira_auth_header  # noqa: F401

VERSION = "0.38.0"   # Semantic Versioning: neue Funktion = minor, Korrektur = patch. Bei jeder Änderung auch CHANGELOG.md pflegen (ein Test prüft das)
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

# 0.38: Die Aktionen von App liegen in Bereichen; App erbt sie.
from area_agents import AgentArea  # noqa: E402
from area_focus import FocusArea  # noqa: E402
from area_ide import IdeArea  # noqa: E402
from area_m365 import M365Area  # noqa: E402
from area_qa import QaArea  # noqa: E402
from area_sync import SyncArea  # noqa: E402
from area_tickets import TicketArea  # noqa: E402
from area_time import TimeArea  # noqa: E402
from area_workspaces import WorkspaceArea  # noqa: E402
# 0.38: Standardwerte und Config-Hilfen liegen in config.py; die Namen bleiben hier erreichbar.
from config import (DEFAULTS, GITHUB_DEFAULTS, JIRA_DEFAULTS, LLM_DEFAULTS, PLAIN_SECRET_KEYS, SONAR_DEFAULTS, TIME_DEFAULTS,  # noqa: E402,F401
                    USAGE_DEFAULTS, apply_env, feature, github_cfg, jira_cfg, llm_cfg, load_config, reject_plain_secrets, sonar_cfg,
                    time_cfg, usage_cfg)


class App(SyncArea, TicketArea, AgentArea, TimeArea, FocusArea, QaArea, WorkspaceArea, M365Area, IdeArea):
    """Zustand und Kern von tinyops: Config anwenden, Clients, Speicher, Audit. Die Aktionen liegen seit 0.38 in den Bereichen (area_*.py)."""

    @property
    def version(self):
        return VERSION

    @property
    def base(self):
        return BASE                    # zur Laufzeit gelesen: Tests setzen server.BASE um

    def data_dir(self):
        return data_dir(self.cfg)

    def selftest(self):
        return run_selftest(self.cfg)

    def __init__(self, cfg, demo, secrets, config_path=None, watchdog=True):
        self.demo = demo
        self.config_path = Path(config_path) if config_path else default_config_path()
        self.access_token = secrets.get("access_token") or ""
        self.cache_lock = threading.Lock()
        self._renv_live = set()          # Läufe, deren Review-Umgebungs-Befehl gerade läuft
        self.sync_lock = threading.Lock()
        self.sync = {"running": False, "steps": [], "started": 0.0, "finished": 0.0, "n": 0}
        self.partial, self.early_stories, self._sync_thread = None, None, None
        self.hd_lock = threading.Lock()
        self.ws_lock, self.ws_cache, self.ws_busy = threading.Lock(), None, False
        self.ideas = None
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
        if not hasattr(self, "devices"):
            self.devices = devices.Devices(self.store)            # 0.36: gekoppelte Handys; offene Codes überleben ein Speichern der Einstellungen
        self.devices.store = self.store
        self.audit_log = audit.AuditLog(data_dir(cfg) / "tinyops.db")
        if not hasattr(self, "_audit_ctx"):
            self._audit_ctx = threading.local()
        self._rv_cache = {}
        self.timebook = timesheet.TimeBook(data_dir(cfg) / "tinyops.db")
        self.qabook = qa.QaBook(data_dir(cfg) / "tinyops.db")
        self.uxlog = ux.UxLog(data_dir(cfg) / "tinyops.db")
        self.tc = time_cfg(cfg)
        self.fc = focusplan.cfg(cfg)
        self.wsc = workspaces.cfg(cfg)
        self.ws_cache = None
        self.bcsc = bcs.cfg(cfg)                 # BCS-Middleware (0.29)
        self.bcs, self.bcs_error = None, ""
        if self.demo:                                             # Demo: eigene Middleware
            self.bcs = bcs.Demo()
        elif self.bcsc["enabled"]:
            try:
                self.bcs = bcs.Client(self.bcsc["url"], secrets.get("bcs_token", ""), allow_lan=self.bcsc.get("allow_lan", False))
            except bcs.BcsError as e:
                self.bcs_error = str(e)
        self._bcs_prev = {}                      # draftId der Middleware → was tinyops dafür geprüft hat
        self._head_of = {}                       # Begleitticket → Task (0.30)
        self._bcs_lock = threading.Lock()
        self.ssl_ctx = ssl.create_default_context()
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
        self._briefs = {}                     # Ticket-Rohdaten für Aufträge an Agenten (0.26), kurz gemerkt
        self.hdj = None                       # Helpdesk-Jira (0.23)
        self.hdc = helpdesk.cfg(cfg)
        self.mc = m365.cfg(cfg)                # Microsoft 365 über Graph (0.28)
        self.m365 = m365.Client(self.mc, None, "http://localhost:%d/api/m365/callback" % int(cfg.get("port") or 8765), self._m365_store())
        self.m365_cache, self.m365_t = None, 0.0
        self.ghc = github_cfg(cfg)
        self.cache, self.cache_t = None, 0.0
        self.hd_cache, self.hd_t = None, 0.0
        self.over_limit = False
        self.inprogress_keys = set()
        self.proj_cfg = {p["id"]: p for p in cfg["projects"]}
        if (self.demo or feature(cfg, "ideas")) and self.ideas is None:
            self.ideas = Ideas(data_dir(cfg) / "tinyops.db", cfg["idea_cap"], cfg["idea_expire_days"])
        if self.demo:
            self.client = DemoClient(cfg)
            self.jira = DemoJira(self.jc)
            self.sonar = DemoSonar()
            self.hdj = DemoHelpdesk()
            self.hdc = dict(self.hdc, enabled=True, name="Servicedesk", queue_jql="demo")
            if not self.proj_cfg:
                self.proj_cfg = {1: {"id": 1, "name": "dlp-core"}}
            return
        try:
            ctx = make_ssl(cfg)
        except SystemExit as e:
            self.problems.append(str(e))
            ctx = ssl.create_default_context()
        self.ssl_ctx = ctx
        self.m365.ctx = ctx
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
        if self.hdc["enabled"]:
            need = helpdesk.secret_name(self.hdc)
            if not self.hdc["url"]:
                self.problems.append("Helpdesk-Jira: Adresse fehlt.")
            elif not secrets.get(need):
                self.problems.append("Helpdesk-Jira: %s fehlt." % ("Token" if need == "helpdesk_token" else "Passwort"))
            else:
                try:
                    self.hdj = JiraClient(dict(self.hdc), helpdesk.auth_header(self.hdc, secrets), ctx)
                except ValueError as e:
                    self.problems.append("Helpdesk-Jira: %s" % e)
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


    # -- Verknüpfungen und Pools (nur lokal gespeichert)
    def _local(self, fn, *a):
        try:
            return fn(*a)
        except links.LinkError as e:
            raise UserError(str(e))


    def _git(self, repo, *args, timeout=60, env=None):
        try:
            r = subprocess.run(["git", "-C", repo] + list(args), capture_output=True, text=True, timeout=timeout,
                               env=dict(os.environ, **env) if env else None, stdin=subprocess.DEVNULL)
        except FileNotFoundError:
            raise UserError("git ist auf diesem Rechner nicht installiert.")
        except subprocess.TimeoutExpired:
            raise UserError("git %s dauert zu lange (über %d s)." % (args[0], timeout))
        return r.returncode, r.stdout.strip(), scrub(r.stderr.strip())


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


# ---------------------------------------------------------------- HTTP (0.37: in routes.py)
def make_handler(app):
    return routes.make_handler(app, BASE, VERSION, load_config)


# ---------------------------------------------------------------- Secrets beim Start
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
    if not demo and bcs.cfg(cfg).get("enabled"):
        names.append("bcs_token")
    if not demo and helpdesk.cfg(cfg).get("enabled"):
        names.append(helpdesk.secret_name(helpdesk.cfg(cfg)))
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
        elif show and name not in ("access_token", "llm_key", "bcs_token"):
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
        hc = helpdesk.cfg(cfg)
        if hc.get("enabled") and hc.get("url"):
            steps(hc.get("name") or "Helpdesk", settings.test_helpdesk({"url": hc["url"], "auth": hc["auth"], "username": hc.get("username", ""),
                                                                        "ca_bundle": cfg.get("ca_bundle", ""), "assigned_jql": hc["assigned_jql"],
                                                                        "queue_jql": hc.get("queue_jql", ""), "watch_jql": hc.get("watch_jql", "")}, stored))
        uc = usage_cfg(cfg)
        if uc.get("claude") or uc.get("codex"):
            print("\nKI-Kontingent")
            for k in ("claude", "codex"):
                if uc.get(k):
                    r = aiquota.fetch(k, uc.get(k + "_file") or None)
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
        yday = (datetime.fromtimestamp(now) - timedelta(days=1)).replace(hour=10, minute=0, second=0, microsecond=0)   # gestern: unabhängig von der Uhrzeit
        a.timebook.add_segment("DLP-104", "Installer: Upgrade-Test", yday.timestamp(), yday.timestamp() + 3000)
        day = a.time_day(yday.strftime("%Y-%m-%d"))
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
        hd = (a.overview().get("flow") or {}).get("helpdesk") or []
        st = a.focus_action("start", {"area": "bb", "activity": "Betreuung Lernende", "minutes": 25})
        for m_ in (10, 20):            # das Panel fragt ab: Die Sitzung gilt als Lebenszeichen
            a.focus_state(st["session"]["start"] + m_ * 60)
        en = a.focus_action("end", {"result": "erledigt"}, now=st["session"]["start"] + 25 * 60)
        ok = len(hd) == 3 and en["ended"]["xp"] == 15 and any(x["id"] == "bb" for x in en["week"]["areas"])
        step("focus", "Helpdesk und Fokus-Sitzung", "ok" if ok else "fail", "%d Helpdesk-Tickets, Sitzung %d min, +%d XP" % (len(hd), en["ended"]["minutes"], en["ended"]["xp"]))
        w = a.workspaces_state()
        step("ws", "Workspaces", "ok" if w["totals"]["todo"] == 3 and a.overview()["workspaces"]["repos"] == 4 else "fail",
             "%d Repos, %d mit lokaler Arbeit" % (w["totals"]["repos"], w["totals"]["todo"]))
        try:                                   # BCS (0.29): Demo-Middleware, Vorschau und einmal bestätigen
            dd = timesheet.today()
            did_ = a.timebook.add_manual(dd, "DLP-999", 15, "Selbsttest")
            a.time_action("confirm", {"id": did_})
            a.bcs_action("map", {"ticket": "DLP-999", "task_id": "T-100", "name": "Entwicklung DLP"})
            pv = a.bcs_action("preview", {"date": dd})
            cm_ = a.bcs_action("commit", {"date": dd, "draft_id": pv["draft_id"]})
            ok = pv["status"] == "ready" and cm_["status"] == "committed" and a.timebook.draft(did_)["state"] == "gebucht"
            step("bcs", "BCS: prüfen und buchen (Demo)", "ok" if ok else "fail", "%s → %s" % (pv["status"], cm_["status"]))
        except Exception as e:     # Selbsttest: Fehler zeigen, nicht abbrechen
            step("bcs", "BCS: prüfen und buchen (Demo)", "fail", str(e))
        br = a.ticket_brief("DLP-101")
        txt = briefing.block(br, briefing.options(br, None))
        ok = len(briefing.parse_prompt(txt)) == 3 and br["masked"] >= 1 and "demo-geheim" not in txt
        step("brief", "Auftrag aus dem Ticket", "ok" if ok else "fail", "%d Akzeptanzkriterien, %d Geheimnis geschwärzt" % (len(br["criteria"]), br["masked"]))
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
