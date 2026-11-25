"""Einstellungen: anzeigen, prüfen und speichern (Config und Secrets).

Secrets werden nie zurückgegeben, nur ob und wo sie gespeichert sind. Die Verbindungstests stehen seit 0.45 in `conntest.py`;
ihre Namen sind hier weiter erreichbar (`settings.test_gitlab` …), damit Routen und Tests gleich bleiben.
"""
import json
import os
import re
import shlex
import tempfile
import urllib.parse
from pathlib import Path

import agents
import devices
import github
import llm
import voice
import secretstore as store
import aiquota
import focusplan
import helpdesk
import m365
import bcs
import workspaces
import timesheet
import tlog
import reviewenv
import settings_schema as S
from settings_schema import int_ as _int, lst as _lst
from conntest import (JQL_DEFAULT, _base, search_github, search_projects, suggest_identity, test_agent,  # noqa: F401
                      test_github, test_gitlab, test_llm, test_sonar, test_voice)
from conntest_jira import test_helpdesk, test_jira  # noqa: F401

log = tlog.get("settings")

SECRET_FIELDS = ("gitlab_token", "gitlab_review_token", "jira_token", "jira_password", "llm_key", "sonar_token", "github_token",
                 "helpdesk_token", "helpdesk_password", "bcs_token", "voice_key")
KEY_RE = re.compile(r"^[A-Z][A-Z0-9_]{1,19}$")
CONFIG_KEYS_FEATURES = ("ideas", "ai", "score")      # 0.34: «testenv» entfällt (E2); 0.35: «score» (E3)
FEATURE_DEFAULTS = {"score": True}                   # fehlt der Schlüssel, bleibt der Spielstand an (wie vor 0.35)


# ------------------------------------------------------------ Bericht
def secret_state(cfg, name, extra_env=()):
    try:
        val, src = store.resolve(name, (cfg.get("secrets") or {}).get(name), extra_env)
    except store.SecretError as e:
        return {"set": False, "source": "", "error": str(e)}
    return {"set": bool(val), "source": src or "", "error": ""}


def view(cfg, config_path, features_default=None):
    jc = cfg.get("jira") or {}
    bf = cfg.get("branch_filter") or {}
    feats = cfg.get("features") or {}
    kr = store._keyring()
    return {
        "gitlab": {"url": cfg.get("gitlab_url", ""), "ca_bundle": cfg.get("ca_bundle", "")},
        "projects": [{"id": p["id"], "name": p.get("name", str(p["id"])), "sonar_key": p.get("sonar_key", ""),
                      "agent_dir": p.get("agent_dir", ""), "data_class": agents.data_class(p), "cloud_paths": list(p.get("cloud_paths") or []),
                      "repo_path": p.get("repo_path", ""), "review_env": p.get("review_env")}
                     for p in cfg.get("projects", [])],
        "review_kinds": [{"id": k, **v} for k, v in reviewenv.KINDS.items()],
        "connections": [dict(c) for c in cfg.get("connections") or []],
        "github": {"enabled": bool((cfg.get("github") or {}).get("enabled", False)), "api_url": (cfg.get("github") or {}).get("api_url") or github.API_DEFAULT,
                   "repos": [dict(r, data_class=agents.data_class(r), cloud_paths=list(r.get("cloud_paths") or []))
                             for r in (cfg.get("github") or {}).get("repos") or []]},
        "agents": [{k: v for k, v in a.items() if k != "command"} | {"has_command": bool(a.get("command"))} for a in cfg.get("agents") or []],
        "agent_log_days": int(S.get(cfg, "agent_log_days")),
        "agent_guards": agents.guards_cfg(cfg),
        "ux": dict({"enabled": True, "days": S.NUMBERS["ux.days"].default}, **(cfg.get("ux") or {})),
        "ide_command": cfg.get("ide_command") or "idea {path}",
        "time": dict(timesheet.DEFAULTS, **dict(cfg.get("time") or {}, bcs=bcs.cfg(cfg))),
        "helpdesk": helpdesk.cfg(cfg),
        "m365": dict(m365.cfg(cfg), redirect="http://localhost:%d/api/m365/callback" % int(cfg.get("port") or 8765),
                     scopes=m365.scopes(m365.cfg(cfg))),
        "workspaces": dict(workspaces.cfg(cfg), found=workspaces.roots_of(cfg)),
        "app": {"phone_url": (cfg.get("app") or {}).get("phone_url", ""), "origins": list((cfg.get("app") or {}).get("origins") or []),
                "bind": cfg.get("bind") or "127.0.0.1"},
        "focus": _focus_view(cfg),
        "agent_kinds": [{"id": k, "label": v["label"], "provider": v["provider"], "local": bool(v.get("local"))} for k, v in agents.KINDS.items()],
        "data_classes": [{"id": c, "label": agents.CLASS_LABEL[c]} for c in agents.CLASSES],
        "branch_filter": {
            "emails": sorted(set(bf.get("emails", [])) | set(cfg.get("my_emails", []))), "names": bf.get("names", []),
            "agent_emails": bf.get("agent_emails", []), "agent_names": bf.get("agent_names", []),
            "agent_message_patterns": bf.get("agent_message_patterns", ["Co-Authored-By: Claude"]),
            "max_branches": bf.get("max_branches", S.NUMBERS["branch_filter.max_branches"].default),
            "max_age_days": bf.get("max_age_days", S.NUMBERS["branch_filter.max_age_days"].default),
            "ignore_branches": bf.get("ignore_branches", ["release/*"])},
        "jira": {"url": jc.get("url", ""), "auth": jc.get("auth", "bearer"), "username": jc.get("username", ""),
                 "project_keys": jc.get("project_keys", []), "story_limit": jc.get("story_limit", S.NUMBERS["jira.story_limit"].default),
                 "wip_issue_types": jc.get("wip_issue_types", ["Story"]), "group_link_types": jc.get("group_link_types") or [], "jql_in_progress": jc.get("jql_in_progress") or JQL_DEFAULT,
                 "only_active_sprints": bool(jc.get("only_active_sprints", True)),
                 "allow_create": bool(jc.get("allow_create", False)), "create_type": jc.get("create_type", "Story")},
        "voice": voice.view(cfg),
        "llm": {"enabled": bool((cfg.get("llm") or {}).get("enabled", False)), "provider": (cfg.get("llm") or {}).get("provider", "ollama"),
                "url": (cfg.get("llm") or {}).get("url", "http://127.0.0.1:11434"), "model": (cfg.get("llm") or {}).get("model", ""),
                "allow_remote": bool((cfg.get("llm") or {}).get("allow_remote", False)),
                "timeout": S.get(cfg, "llm.timeout"),
                "providers": [{"id": k, "label": v.label, "url": v.default_url} for k, v in llm.PROVIDERS.items()]},
        "usage": {"claude": bool((cfg.get("usage") or {}).get("claude")), "codex": bool((cfg.get("usage") or {}).get("codex")),
                  "mistral": bool((cfg.get("usage") or {}).get("mistral")), "bookmarklet_src": aiquota.BOOKMARKLET_JS,
                  "claude_file": (cfg.get("usage") or {}).get("claude_file", ""), "codex_file": (cfg.get("usage") or {}).get("codex_file", ""),
                  "cache_seconds": S.get(cfg, "usage.cache_seconds")},
        "sonar": {"enabled": bool((cfg.get("sonar") or {}).get("enabled", False)), "url": (cfg.get("sonar") or {}).get("url", ""),
                  "cache_seconds": S.get(cfg, "sonar.cache_seconds"), "max_items": S.get(cfg, "sonar.max_items"),
                  "report_max": S.get(cfg, "sonar.report_max")},
        "features": {k: bool(feats.get(k, FEATURE_DEFAULTS.get(k, False))) for k in CONFIG_KEYS_FEATURES},
        "secrets": {n: secret_state(cfg, n, [cfg.get("token_env")] if n == "gitlab_token" else ()) for n in SECRET_FIELDS},
        "storage": {"keyring": bool(kr), "file": str(store.secrets_file()),
                    "text": "Schlüsselbund des Betriebssystems" if kr else
                            "Datei %s (Klartext, nur für deinen Benutzer lesbar)" % store.secrets_file()},
        "server": {"config": str(config_path), "log": str(tlog.log_file(cfg)), "bind": cfg.get("bind"), "port": cfg.get("port")},
        "jql_default": JQL_DEFAULT,
        "schema": S.public(),               # 0.45: Grenzen und Standard der Zahlenfelder für die Oberfläche
    }


def _focus_view(cfg):
    f = focusplan.cfg(cfg)
    return {"week_hours": f["week_hours"], "day_start": f["day_start"], "day_end": f["day_end"],
            "areas": [dict(a, blocks_text=focusplan.blocks_text(a.get("blocks"))) for a in f["areas"]]}


def _clean_focus(p, errors):
    f = dict(focusplan.DEFAULTS)
    f["week_hours"] = S.number("focus.week_hours", p.get("week_hours"), errors)
    for k in ("day_start", "day_end"):
        v = str(p.get(k) or focusplan.DEFAULTS[k]).strip()
        if not re.fullmatch(r"([01]?\d|2[0-3]):[0-5]\d", v):
            errors["focus." + k] = "Uhrzeit wie 08:00."
        else:
            f[k] = "%02d:%s" % (int(v.split(":")[0]), v.split(":")[1])
    if f["day_start"] >= f["day_end"]:
        errors["focus.day_end"] = "Ende muss nach dem Beginn liegen."
    areas, seen, total = [], set(), 0
    for i, a in enumerate(p.get("areas") or []):
        name = str(a.get("name") or "").strip()[:40]
        aid = re.sub(r"[^a-z0-9_-]", "", str(a.get("id") or "").lower())[:20] or re.sub(r"[^a-z0-9]", "", name.lower())[:20]
        if not name or not aid:
            errors["focus.areas"] = "Jeder Bereich braucht einen Namen."
            continue
        if aid in seen:
            errors["focus.areas"] = "Bereich «%s» doppelt." % name
            continue
        seen.add(aid)
        pct = _int(a.get("target_pct"), "focus.areas.%d.target_pct" % i, 0, 100, errors, 0)
        total += pct
        try:
            blocks = focusplan.parse_blocks(a.get("blocks_text") if "blocks_text" in a else focusplan.blocks_text(a.get("blocks")))
        except ValueError as e:
            errors["focus.areas.%d.blocks" % i] = str(e)
            blocks = []
        ticket = str(a.get("ticket") or "").strip()[:80]
        areas.append({"id": aid, "name": name, "target_pct": pct, "ticket": ticket,
                      "pools": _lst(a.get("pools"), "focus.areas.%d.pools" % i, errors, 20),
                      "activities": _lst(a.get("activities"), "focus.areas.%d.activities" % i, errors, 20), "blocks": blocks})
    if total > 100:
        errors["focus.areas"] = "Die Ziele ergeben zusammen %d %%, höchstens 100 %%." % total
    if not any(a["id"] == "dev" for a in areas):
        areas.insert(0, dict(focusplan.DEFAULTS["areas"][0]))
    f["areas"] = areas
    return f


def _clean_class(item, entry, errors, errkey):
    """Datenklasse und freigegebene Pfade übernehmen; die alte Freigabe «Cloud-Agent erlaubt» (bis 0.15) wird dabei ersetzt."""
    if "data_class" not in item and "allow_cloud_agents" not in item:
        return
    cls = item.get("data_class")
    if cls is None:
        cls = "internal" if item.get("allow_cloud_agents") else "restricted"
    if cls not in agents.CLASSES:
        errors[errkey] = "Unbekannte Datenklasse «%s»." % str(cls)[:20]
        cls = "restricted"
    entry.pop("allow_cloud_agents", None)
    entry["data_class"] = cls
    paths, err = agents.clean_paths(item.get("cloud_paths") or [])
    if err:
        errors[errkey] = err
    if cls == "internal" and paths:
        entry["cloud_paths"] = paths
    else:
        entry.pop("cloud_paths", None)


def _clean_review_env(item, entry, errors, errkey):
    """Review-Umgebung je Projekt (0.32): Docker Compose, Kubernetes oder eigene Befehle. Leer = keine."""
    if "review_env" not in item:
        return
    env, err = reviewenv.clean(item.get("review_env"))
    if err:
        errors[errkey] = err
    elif env:
        entry["review_env"] = env
    else:
        entry.pop("review_env", None)


def _clean_repo_path(item, entry, errors, errkey):
    """Lokaler Checkout für «In IntelliJ öffnen» (0.20). Absolut oder mit ~, ohne Zeilenumbruch."""
    if "repo_path" not in item:
        return
    rp = str(item.get("repo_path") or "").strip()
    if not rp:
        entry.pop("repo_path", None)
    elif len(rp) > 400 or "\n" in rp or not (os.path.isabs(os.path.expanduser(rp))):
        errors[errkey] = "Der Repo-Pfad «%s» muss absolut sein (oder mit ~ beginnen)." % rp[:60]
    else:
        entry["repo_path"] = rp


def build_config(current, p):
    """Baut aus der bisherigen Config und den Eingaben eine neue. Gibt (Config, Fehler) zurück. Schreibt nichts."""
    errors = {}
    cfg = json.loads(json.dumps(current))   # tiefe Kopie
    g = p.get("gitlab") or {}
    url = (g.get("url") or "").strip().rstrip("/")
    if url:
        u = urllib.parse.urlparse(url)
        if u.scheme not in ("http", "https") or not u.hostname:
            errors["gitlab.url"] = "Muss mit https:// (oder http://) beginnen."
    cfg["gitlab_url"] = url
    cfg["ca_bundle"] = (g.get("ca_bundle") or "").strip()

    old = {p_["id"]: p_ for p_ in cfg.get("projects", [])}
    projects = []
    for item in p.get("projects") or []:
        try:
            pid = int(item.get("id"))
        except (TypeError, ValueError):
            errors["projects"] = "Projekt-ID muss eine Zahl sein."
            continue
        entry = dict(old.get(pid, {}))
        entry["id"] = pid
        entry["name"] = (str(item.get("name") or pid).strip() or str(pid))[:80]
        if "sonar_key" in item:
            sk = str(item.get("sonar_key") or "").strip()
            if sk and not re.fullmatch(r"[A-Za-z0-9_.:\-]{1,400}", sk):
                errors["projects"] = "Der Sonar-Projektschlüssel «%s» enthält unerlaubte Zeichen (erlaubt: Buchstaben, Ziffern, - _ . :)." % sk[:40]
            elif sk:
                entry["sonar_key"] = sk
            else:
                entry.pop("sonar_key", None)
        if "agent_dir" in item:
            ad = str(item.get("agent_dir") or "").strip()
            if not agents.valid_agent_dir(ad):
                errors["projects"] = "Der Agent-Ordner «%s» ist ungültig (relativ, ohne «..», nur Buchstaben, Ziffern und . _ - /)." % ad[:40]
            elif ad:
                entry["agent_dir"] = ad
            else:
                entry.pop("agent_dir", None)
        _clean_repo_path(item, entry, errors, "projects")
        _clean_review_env(item, entry, errors, "projects")
        _clean_class(item, entry, errors, "projects")
        if pid not in [x["id"] for x in projects]:
            projects.append(entry)
    cfg["projects"] = projects

    b = p.get("branch_filter") or {}
    bf = dict(cfg.get("branch_filter") or {})
    bf["emails"] = [e.lower() for e in _lst(b.get("emails"), "branch_filter.emails", errors)]
    bf["names"] = _lst(b.get("names"), "branch_filter.names", errors)
    bf["agent_emails"] = [e.lower() for e in _lst(b.get("agent_emails"), "branch_filter.agent_emails", errors)]
    bf["agent_names"] = _lst(b.get("agent_names"), "branch_filter.agent_names", errors)
    bf["agent_message_patterns"] = _lst(b.get("agent_message_patterns"), "branch_filter.agent_message_patterns", errors)
    bf["max_branches"] = S.number("branch_filter.max_branches", b.get("max_branches"), errors)
    bf["max_age_days"] = S.number("branch_filter.max_age_days", b.get("max_age_days"), errors)
    bf["ignore_branches"] = _lst(b.get("ignore_branches", ["release/*"]), "branch_filter.ignore_branches", errors)
    cfg["branch_filter"] = bf
    cfg["my_emails"] = bf["emails"]

    j = p.get("jira") or {}
    jc = dict(cfg.get("jira") or {})
    jurl = (j.get("url") or "").strip().rstrip("/")
    if not jurl:
        cfg["jira"] = {}
    else:
        u = urllib.parse.urlparse(jurl)
        if u.scheme not in ("http", "https") or not u.hostname:
            errors["jira.url"] = "Muss mit https:// (oder http://) beginnen."
        jc["url"] = jurl
        jc["auth"] = j.get("auth") or "bearer"
        if jc["auth"] not in ("bearer", "basic"):
            errors["jira.auth"] = "bearer oder basic."
        jc["username"] = (j.get("username") or "").strip() if jc["auth"] == "basic" else ""
        if jc["auth"] == "basic" and not jc["username"]:
            errors["jira.username"] = "Bei basic nötig."
        keys = _lst(j.get("project_keys"), "jira.project_keys", errors, upper=True)
        bad = [k for k in keys if not KEY_RE.match(k)]
        if bad:
            errors["jira.project_keys"] = "Ungültig: %s (erwartet zum Beispiel DLP)." % ", ".join(bad)
        jc["project_keys"] = keys
        jc["story_limit"] = S.number("jira.story_limit", j.get("story_limit"), errors)
        jc["wip_issue_types"] = _lst(j.get("wip_issue_types"), "jira.wip_issue_types", errors)
        if "group_link_types" in j:
            jc["group_link_types"] = _lst(j.get("group_link_types"), "jira.group_link_types", errors)
        jc["only_active_sprints"] = bool(j.get("only_active_sprints", True))
        jc["allow_create"] = bool(j.get("allow_create", False))
        jc["create_type"] = (j.get("create_type") or "Story").strip()[:60] or "Story"
        jql = (j.get("jql_in_progress") or "").strip() or JQL_DEFAULT
        if len(jql) > 2000:
            errors["jira.jql_in_progress"] = "Zu lang."
        jc["jql_in_progress"] = jql
        jc.pop("helpdesk", None)
        cfg["jira"] = jc

    if p.get("voice") is not None:           # 0.43: Spracherkennung, Regeln in voice.py
        voice.clean(p["voice"], cfg, errors)

    m = p.get("llm")
    if m is not None:
        lc = dict(cfg.get("llm") or {})
        lc["enabled"] = bool(m.get("enabled", False))
        lc["provider"] = m.get("provider") or "ollama"
        if lc["provider"] not in llm.PROVIDERS:
            errors["llm.provider"] = "Unbekannt. Erlaubt: %s." % ", ".join(llm.PROVIDERS)
        lc["url"] = (m.get("url") or "").strip().rstrip("/")
        lc["model"] = (m.get("model") or "").strip()[:100]
        lc["allow_remote"] = bool(m.get("allow_remote", False))
        lc["timeout"] = S.number("llm.timeout", m.get("timeout"), errors)
        if lc["enabled"]:
            try:
                llm.check_url(lc)
            except llm.LlmError as e:
                errors["llm.url"] = str(e)
        cfg["llm"] = lc

    us = p.get("usage")
    if us is not None:
        uc = dict(cfg.get("usage") or {})
        uc["mistral"] = bool(us.get("mistral", False))
        for k in ("claude", "codex"):
            uc[k] = bool(us.get(k, False))
            f = str(us.get(k + "_file") or "").strip()
            if len(f) > 300 or "\x00" in f:
                errors["usage.%s_file" % k] = "Ungültiger Pfad."
            uc[k + "_file"] = f
        uc["cache_seconds"] = S.number("usage.cache_seconds", us.get("cache_seconds"), errors)   # 0.45: Fehler am Feld (vorher «aiquota.…»)
        cfg["usage"] = uc

    sq = p.get("sonar")
    if sq is not None:
        sc = dict(cfg.get("sonar") or {})
        sc["enabled"] = bool(sq.get("enabled", False))
        url, _ = _base(sq.get("url"))
        u = urllib.parse.urlparse(url)
        if url and (u.scheme not in ("http", "https") or not u.hostname):
            errors["sonar.url"] = "Muss mit https:// (oder http://) beginnen."
        elif sc["enabled"] and not url:
            errors["sonar.url"] = "Zum Einschalten fehlt die Adresse."
        sc["url"] = url
        sc["cache_seconds"] = S.number("sonar.cache_seconds", sq.get("cache_seconds"), errors)
        sc["max_items"] = S.number("sonar.max_items", sq.get("max_items"), errors)
        sc["report_max"] = S.number("sonar.report_max", sq.get("report_max"), errors)
        cfg["sonar"] = sc

    if "github" in p:
        gh = p.get("github") or {}
        g = dict(cfg.get("github") or {})
        g["enabled"] = bool(gh.get("enabled"))
        api = (gh.get("api_url") or github.API_DEFAULT).strip().rstrip("/")
        u = urllib.parse.urlparse(api)
        if not u.hostname or not (u.scheme == "https" or (u.scheme == "http" and u.hostname in ("127.0.0.1", "localhost"))):
            errors["github.api_url"] = "Muss mit https:// beginnen (github.com: https://api.github.com, Enterprise: https://host/api/v3)."
        g["api_url"] = api
        repos, seen = [], set()
        for x in gh.get("repos") or []:
            full = str((x or {}).get("full") or "").strip()
            if not github.REPO_RE.fullmatch(full):
                errors["github.repos"] = "«%s» ist kein Repo der Form owner/name." % full[:60]
                continue
            if full.lower() in seen:
                continue
            seen.add(full.lower())
            e = {"full": full}
            try:
                if x.get("id") not in (None, ""):
                    e["id"] = int(x["id"])
            except (TypeError, ValueError):
                errors["github.repos"] = "Repo-ID von %s ist keine Zahl." % full
            ad = str(x.get("agent_dir") or "").strip()
            if ad and not agents.valid_agent_dir(ad):
                errors["github.repos"] = "Der Agent-Ordner «%s» ist ungültig." % ad[:40]
            elif ad:
                e["agent_dir"] = ad
            _clean_repo_path(x, e, errors, "github.repos")
            _clean_class(x, e, errors, "github.repos")
            repos.append(e)
        if len(repos) > 30:
            errors["github.repos"] = "Höchstens 30 Repos."
        g["repos"] = repos[:30]
        if g["enabled"] and not repos:
            errors["github.repos"] = "Zum Einschalten mindestens ein Repo wählen."
        cfg["github"] = g

    if isinstance(p.get("time"), dict):
        t, tc = p["time"], dict(timesheet.DEFAULTS, **(cfg.get("time") or {}))
        tc["enabled"] = bool(t.get("enabled", tc["enabled"]))
        for old in ("mcp_url", "send_on_confirm", "allow_remote"):      # 0.34 (E1): nur noch BCS, der Projectron-Export entfällt
            tc.pop(old, None)
        for k in ("round_minutes", "min_minutes", "idle_minutes"):
            tc[k] = S.number("time." + k, t.get(k), errors, tc[k])
        if isinstance(t.get("bcs"), dict):            # 0.29: BCS-Middleware auf diesem Rechner
            bb, bc = t["bcs"], bcs.cfg(cfg)
            bc["enabled"] = bool(bb.get("enabled", bc["enabled"]))
            bc["apprentices"] = bool(bb.get("apprentices", bc["apprentices"]))
            bc["allow_lan"] = bool(bb.get("allow_lan", bc["allow_lan"]))      # 0.35.1: Middleware z. B. auf dem Windows-Host
            u = str(bb.get("url", bc["url"]) or "").strip()
            try:
                bc["url"] = bcs.check_url(u, bc["allow_lan"]) if u else ""
            except bcs.BcsError as e:
                errors["time.bcs.url"] = str(e)
                bc["url"] = u
            if bc["enabled"] and not bc["url"]:
                errors["time.bcs.url"] = "Adresse der Middleware eintragen, z. B. http://127.0.0.1:3210."
            tc["bcs"] = bc
        cfg["time"] = tc
    if isinstance(p.get("helpdesk"), dict):
        h, hc = p["helpdesk"], helpdesk.cfg(cfg)
        hc["enabled"] = bool(h.get("enabled", hc["enabled"]))
        url = str(h.get("url", hc["url"]) or "").strip().rstrip("/")
        if url:
            u = urllib.parse.urlparse(url)
            if u.scheme not in ("http", "https") or not u.hostname:
                errors["helpdesk.url"] = "Muss mit https:// (oder http://) beginnen."
        elif hc["enabled"]:
            errors["helpdesk.url"] = "Zum Einschalten die Adresse eintragen."
        hc["url"] = url
        auth = h.get("auth", hc["auth"])
        if auth not in ("basic", "bearer"):
            errors["helpdesk.auth"] = "basic oder bearer."
        else:
            hc["auth"] = auth
        hc["username"] = str(h.get("username", hc["username"]) or "").strip()[:120]
        if hc["enabled"] and hc["auth"] == "basic" and not hc["username"]:
            errors["helpdesk.username"] = "Bei «basic» den Benutzernamen eintragen."
        hc["name"] = (str(h.get("name", hc["name"]) or "").strip() or "Helpdesk")[:40]
        for k in ("assigned_jql", "queue_jql", "watch_jql"):
            v = " ".join(str(h.get(k, hc[k]) or "").split())
            if len(v) > 1000:
                errors["helpdesk." + k] = "JQL zu lang."
            else:
                hc[k] = v or (helpdesk.DEFAULTS[k] if k == "assigned_jql" else "")
        hc["sla_hours"] = S.number("helpdesk.sla_hours", h.get("sla_hours"), errors, hc["sla_hours"])
        hc["area"] = re.sub(r"[^a-z0-9_-]", "", str(h.get("area", hc["area"]) or "hd").lower())[:20] or "hd"
        cfg["helpdesk"] = hc
    if isinstance(p.get("m365"), dict):
        m, mc = p["m365"], m365.cfg(cfg)
        mc["enabled"] = bool(m.get("enabled", mc["enabled"]))
        for k in ("mail", "calendar", "teams", "calendar_write"):
            mc[k] = bool(m.get(k, mc[k]))
        if mc["calendar_write"] and not mc["calendar"]:
            mc["calendar_write"] = False
        t = str(m.get("tenant", mc["tenant"]) or "").strip()
        cid = str(m.get("client_id", mc["client_id"]) or "").strip()
        if t and not m365.TENANT_RE.fullmatch(t):
            errors["m365.tenant"] = "Tenant-ID (GUID) oder Domäne wie firma.onmicrosoft.com."
        if cid and not m365.GUID_RE.fullmatch(cid):
            errors["m365.client_id"] = "Client-ID ist eine GUID wie 1234abcd-…, aus der App-Registrierung."
        if mc["enabled"] and not (t and cid):
            errors["m365.client_id" if t else "m365.tenant"] = "Zum Einschalten Tenant und Client-ID eintragen."
        mc["tenant"], mc["client_id"] = t, cid
        mc["reply_days"] = S.number("m365.reply_days", m.get("reply_days"), errors, mc["reply_days"])
        mc["refresh_minutes"] = S.number("m365.refresh_minutes", m.get("refresh_minutes"), errors, mc["refresh_minutes"])
        cfg["m365"] = mc
    if isinstance(p.get("focus"), dict):
        cfg["focus"] = _clean_focus(p["focus"], errors)
    if isinstance(p.get("app"), dict):          # 0.36: Adresse fürs Handy (ihr Host gilt dann als erlaubter Host)
        url, _, err = devices.phone_url(p["app"].get("phone_url"))
        if err:
            errors["app.phone_url"] = err
        else:
            cfg["app"] = dict(cfg.get("app") or {}, phone_url=url)
        if "origins" in p["app"]:                # 0.36.2: Adressen der eigenen App (React-PWA), die tinyops aufrufen darf
            origins, err = devices.app_origins(p["app"].get("origins"))
            if err:
                errors["app.origins"] = err
            else:
                cfg["app"] = dict(cfg.get("app") or {}, origins=origins)
    if isinstance(p.get("workspaces"), dict):
        w, wc = p["workspaces"], workspaces.cfg(cfg)
        wc["enabled"] = bool(w.get("enabled", wc["enabled"]))
        roots = w.get("roots", wc["roots"])
        if isinstance(roots, str):
            roots = [x.strip() for x in re.split(r"[\n;]+", roots)]
        clean = []
        for r in roots or []:
            r = str(r).strip()
            if not r:
                continue
            if len(r) > 400 or "\0" in r or not (r.startswith(("/", "~")) or re.match(r"^[A-Za-z]:[\\/]", r)):
                errors["workspaces.roots"] = "«%s»: bitte einen absoluten Pfad (z. B. ~/work oder C:\\work)." % r[:60]
                continue
            if r not in clean:
                clean.append(r)
        wc["roots"] = clean[:20]
        wc["depth"] = S.number("workspaces.depth", w.get("depth"), errors, wc["depth"])
        wc["stale_days"] = S.number("workspaces.stale_days", w.get("stale_days"), errors, wc["stale_days"])
        wc["scan_minutes"] = S.number("workspaces.scan_minutes", w.get("scan_minutes"), errors, wc["scan_minutes"])
        wc.pop("found", None)
        cfg["workspaces"] = wc
    if isinstance(p.get("ux"), dict):
        u = dict({"enabled": True, "days": 30}, **(cfg.get("ux") or {}))
        u["enabled"] = bool(p["ux"].get("enabled", u["enabled"]))
        u["days"] = S.number("ux.days", p["ux"].get("days"), errors, u["days"])
        cfg["ux"] = u
    if "ide_command" in p:
        cmd = " ".join(str(p.get("ide_command") or "").split())
        try:
            parts = shlex.split(cmd)
        except ValueError:
            parts = []
        if not cmd:
            cfg.pop("ide_command", None)
        elif not parts or len(cmd) > 300 or "\n" in cmd:
            errors["ide_command"] = "Befehl unlesbar (Anführungszeichen prüfen)."
        else:
            cfg["ide_command"] = cmd
    if "agent_guards" in p:                 # Leitplanken für jeden Agenten-Prompt (0.31)
        g = p.get("agent_guards") if isinstance(p.get("agent_guards"), dict) else {}
        out = {}
        old_g = agents.guards_cfg(cfg)
        for k in ("max_files", "max_lines"):
            out[k] = S.number("agent_guards." + k, g.get(k), errors, old_g[k])
        ex = " ".join(str(g.get("extra") or "").split())
        if len(ex) > 600:
            errors["agent_guards.extra"] = "Höchstens 600 Zeichen."
        out["extra"] = ex[:600]
        if not any(k.startswith("agent_guards.") for k in errors):
            cfg["agent_guards"] = out
    if "agent_log_days" in p:
        cfg["agent_log_days"] = S.number("agent_log_days", p.get("agent_log_days"), errors, S.get(cfg, "agent_log_days"))
    if "connections" in p or "agents" in p:
        conns = agents.clean_connections(p.get("connections") if "connections" in p else cfg.get("connections"), errors)
        cfg["connections"] = conns
        cfg["agents"] = agents.clean_agents(p.get("agents") if "agents" in p else cfg.get("agents"), {c["id"] for c in conns}, current.get("agents"), errors)

    f = p.get("features") or {}
    cfg["features"] = {k: bool(f.get(k, FEATURE_DEFAULTS.get(k, False))) for k in CONFIG_KEYS_FEATURES}
    return cfg, errors


def write_config(path, cfg):
    path = Path(path)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".config.", suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)
        f.write("\n")
    os.chmod(tmp, 0o600)
    os.replace(tmp, str(path))


def save_secrets(p):
    """Speichert eingegebene Secrets. Gibt (Orte, Fehler) zurück."""
    where, errors = {}, {}
    for name, value in (p.get("secrets") or {}).items():
        if name not in SECRET_FIELDS:
            errors[name] = "Unbekanntes Secret."
            continue
        value = (value or "").strip()
        if not value:
            continue
        if re.search(r"\s", value):
            errors[name] = "Enthält Leerzeichen oder Zeilenumbrüche (Kopierfehler?)."
            continue
        try:
            where[name] = store.set_secret(name, value)
            log.info("Secret %s gespeichert in: %s", name, where[name])
        except store.SecretError as e:
            errors[name] = str(e)
    for name in p.get("delete_secrets") or []:
        if name in SECRET_FIELDS:
            try:
                removed = store.delete_secret(name)
                log.info("Secret %s gelöscht aus: %s", name, ", ".join(removed) or "nirgends")
            except store.SecretError as e:
                errors[name] = str(e)
    return where, errors
