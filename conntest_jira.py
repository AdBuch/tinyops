"""Verbindungstests für Jira und das Helpdesk-Jira (0.45 aus settings.py gelöst), Schritt für Schritt wie in `conntest`."""
import time

import net
import secretstore as store
import sprint
from conntest import COOLDOWN_S, JQL_DEFAULT, Report, _check_connection, _check_url, _cool, _get, _msg, _redirect_hint, _token, net_hint


# ------------------------------------------------------------ Jira
def _jira_headers(form, stored, prefix="jira", default_auth="bearer"):
    auth = form.get("auth") or default_auth
    name = prefix + ("_token" if auth == "bearer" else "_password")
    sec, src = _token(form, stored, name)
    if not sec:
        return None, src, "Kein %s eingegeben und keiner gespeichert." % ("Token" if auth == "bearer" else "Passwort")
    if auth == "bearer":
        return {"Authorization": "Bearer " + sec, "Accept": "application/json"}, src, ""
    user = (form.get("username") or "").strip()
    if not user:
        return None, src, "Bei «basic» fehlt der Benutzername."
    import base64
    raw = base64.b64encode(("%s:%s" % (user, sec)).encode("utf-8")).decode("ascii")
    store.register(raw)
    return {"Authorization": "Basic " + raw, "Accept": "application/json"}, src, ""


def test_jira(form, stored):
    """form: url, auth, username, secret, ca_bundle, project_keys, issue_types, jql, story_limit."""
    r = Report()
    base, ok = _check_url(r, form.get("url"), "jira")
    if not ok:
        return r.result()
    if "atlassian.net" in base:
        r.add("cloud", "Jira Cloud", "warn", "Das ist Jira Cloud.",
              "Cloud verlangt E-Mail-Adresse + API-Token mit Anmeldeart «basic» und nutzt andere Schnittstellen. tinyops ist für Jira Server/Data Center gebaut.")
    ctx = _check_connection(r, base, form.get("ca_bundle"))
    steps = (("api", "Jira-API"), ("auth", "Anmeldung"), ("projects", "Projekte"), ("types", "Vorgangstypen"),
             ("sprintfield", "Sprints"), ("jql", "JQL «in Arbeit»"))
    if ctx is None:
        for sid, t in steps:
            r.skip(sid, t)
        return r.result()

    # Ist es Jira?
    try:
        resp = _get(base, "/rest/api/2/serverInfo", {"Accept": "application/json"}, ctx)
        d, st = net.parse_json(resp), resp["status"]
        if st == 200 and isinstance(d, dict) and d.get("version"):
            r.add("api", "Jira-API", "ok", "%s %s (%d ms)" % (d.get("serverTitle", "Jira"), d["version"], resp["ms"]))
        elif st in (401, 403) and not net.looks_html(resp):
            r.add("api", "Jira-API", "ok", "Jira-API antwortet (HTTP %d ohne Anmeldung, das ist üblich)" % st)
        elif st in (301, 302, 303, 307, 308):
            loc = resp["headers"].get("location", "")
            sso = any(w in loc.lower() for w in ("login", "sso", "saml", "oauth", "auth"))
            r.add("api", "Jira-API", "fail", "HTTP %d: Weiterleitung nach %s" % (st, loc or "?"),
                  ("Das sieht nach einer Anmeldeseite (SSO) aus. Die API-Zugriffe laufen mit einem Personal Access Token trotzdem, "
                   "aber nur auf der Adresse, die direkt Jira bedient. ") if sso else _redirect_hint(resp, base))
        elif st == 404:
            r.add("api", "Jira-API", "fail", "HTTP 404: unter %s/rest/api/2 gibt es keine Jira-API." % base,
                  "Läuft Jira unter einem Kontextpfad (zum Beispiel https://host/jira)? Dann gehört der Pfad in die Adresse.")
        elif net.looks_html(resp):
            r.add("api", "Jira-API", "fail", "HTTP %d: eine HTML-Seite statt JSON." % st,
                  "Kein Jira unter dieser Adresse, oder ein Proxy zeigt eine Anmeldeseite. Stimmt die Adresse?")
        else:
            r.add("api", "Jira-API", "fail", "HTTP %d: %s" % (st, _msg(resp)))
    except net.NetError as e:
        r.add("api", "Jira-API", "fail", e.detail, net_hint(e.kind))
    if r.blocked:
        for sid, t in steps[1:]:
            r.skip(sid, t)
        return r.result()

    # Anmeldung
    hdr, src, problem = _jira_headers(form, stored)
    auth = form.get("auth") or "bearer"
    if hdr is None:
        r.add("auth", "Anmeldung", "fail", problem,
              ("Personal Access Token anlegen: %s/secure/ViewProfile.jspa → Personal Access Tokens." % base) if auth == "bearer"
              else "Benutzername und Passwort eingeben.")
        for sid, t in steps[2:]:
            r.skip(sid, t)
        return r.result()
    user = None
    ck = (base, (form.get("username") or "").strip().lower())
    if auth == "basic" and _cool.get(ck, 0) > time.time():
        r.add("auth", "Anmeldung", "fail", "Pause nach dem letzten Fehlversuch (noch %d s)." % (_cool[ck] - time.time()),
              "tinyops wartet absichtlich: Mehrere falsche Passwörter in Folge sperren das Konto in Jira oder lösen ein CAPTCHA aus. "
              "Prüfe das Passwort in Ruhe (zum Beispiel durch Anmelden im Browser) und teste dann erneut.")
        for sid, t in steps[2:]:
            r.skip(sid, t)
        return r.result()
    try:
        resp = _get(base, "/rest/api/2/myself", hdr, ctx)
        st, d = resp["status"], net.parse_json(resp)
        reason = resp["headers"].get("x-seraph-loginreason", "")
        denied = resp["headers"].get("x-authentication-denied-reason", "")
        if st == 200 and isinstance(d, dict) and d.get("name") and resp["headers"].get("x-ausername", "").lower() != "anonymous":
            user = d
            r.add("auth", "Anmeldung", "ok", "Angemeldet als %s (%s), %s aus: %s" % (
                d["name"], d.get("displayName", ""), "Token" if auth == "bearer" else "Passwort", src))
        elif "captcha" in denied.lower() or "captcha" in reason.lower():
            r.add("auth", "Anmeldung", "fail", "Jira verlangt ein CAPTCHA (zu viele falsche Anmeldungen).",
                  "Einmal im Browser bei Jira anmelden und das CAPTCHA lösen, danach hier nochmal testen. "
                  "Vorher kein weiterer Test mit falschem Passwort, sonst sperrt Jira wieder.")
        elif st == 200:
            r.add("auth", "Anmeldung", "fail", "Jira antwortet, behandelt dich aber als anonym.",
                  "Die Zugangsdaten wurden nicht angewendet. Bearer-Token: stimmt die Anmeldeart? "
                  "Basic: ist die Basic-Anmeldung in Jira erlaubt?")
        elif st == 401:
            if auth == "basic":
                _cool[ck] = time.time() + COOLDOWN_S
            if auth == "bearer":
                hint = ("Personal Access Token falsch, abgelaufen oder gelöscht? Neu anlegen unter %s/secure/ViewProfile.jspa → "
                        "Personal Access Tokens. Wenn du stattdessen Benutzername und Passwort hast, stelle die Anmeldeart auf «basic»." % base)
            else:
                hint = ("Benutzername oder Passwort falsch. Jira erwartet meist den Benutzernamen, nicht die E-Mail-Adresse. "
                        "Hast du ein Personal Access Token, stelle die Anmeldeart auf «bearer».")
            r.add("auth", "Anmeldung", "fail", "HTTP 401: Zugangsdaten werden nicht akzeptiert%s." % ((" (" + reason + ")") if reason else ""), hint)
        elif st == 403:
            r.add("auth", "Anmeldung", "fail", "HTTP 403: %s%s" % (_msg(resp), (" (" + (reason or denied) + ")") if (reason or denied) else ""),
                  "Das Konto ist gesperrt, hat keinen Jira-Zugriff oder ein Proxy blockiert. Funktioniert die Anmeldung im Browser?")
        elif st in (301, 302, 303, 307, 308):
            r.add("auth", "Anmeldung", "fail", "HTTP %d: Weiterleitung nach %s" % (st, resp["headers"].get("location", "?")),
                  "Jira schickt dich zur Anmeldeseite: Die Zugangsdaten kamen nicht an.")
        else:
            r.add("auth", "Anmeldung", "fail", "HTTP %d: %s" % (st, _msg(resp)))
    except net.NetError as e:
        r.add("auth", "Anmeldung", "fail", e.detail, net_hint(e.kind))
    if r.blocked:
        for sid, t in steps[2:]:
            r.skip(sid, t)
        return r.result()

    # Projekte
    keys, wanted = [], [k.strip().upper() for k in (form.get("project_keys") or []) if k.strip()]
    try:
        resp = _get(base, "/rest/api/2/project", hdr, ctx)
        if resp["status"] == 200:
            keys = sorted(p["key"] for p in (net.parse_json(resp) or []) if "key" in p)
            missing = [k for k in wanted if k not in keys]
            shown = ", ".join(keys[:40]) + (" ..." if len(keys) > 40 else "")
            if missing:
                r.add("projects", "Projekte", "warn", "%d Projekte sichtbar. Nicht sichtbar: %s" % (len(keys), ", ".join(missing)),
                      "Tippfehler oder fehlende Rechte? Sichtbar sind: " + shown)
            elif not wanted:
                r.add("projects", "Projekte", "warn", "%d Projekte sichtbar: %s" % (len(keys), shown),
                      "Trage deine Projekt-Keys ein. Ohne sie erkennt tinyops nur GROSS geschriebene Ticket-Nummern in Branch-Namen.")
            else:
                r.add("projects", "Projekte", "ok", "Alle Keys gefunden: %s" % ", ".join(wanted))
        else:
            r.add("projects", "Projekte", "warn", "Liste nicht lesbar (HTTP %d: %s)" % (resp["status"], _msg(resp)))
    except net.NetError as e:
        r.add("projects", "Projekte", "warn", e.detail)

    # Vorgangstypen
    types = []
    try:
        resp = _get(base, "/rest/api/2/issuetype", hdr, ctx)
        if resp["status"] == 200:
            types = sorted({t["name"] for t in (net.parse_json(resp) or []) if "name" in t})
            want = [t.strip() for t in (form.get("issue_types") or []) if t.strip()]
            missing = [t for t in want if t.lower() not in {x.lower() for x in types}]
            if missing:
                r.add("types", "Vorgangstypen", "warn", "Unbekannt: %s" % ", ".join(missing),
                      "In deinem Jira gibt es: %s. (Deutsche Instanzen heißen oft «Aufgabe», «Fehler».)" % ", ".join(types))
            else:
                r.add("types", "Vorgangstypen", "ok", ("Zählt: %s. " % ", ".join(want) if want else "Alle Typen zählen. ") + "Vorhanden: " + ", ".join(types))
        else:
            r.add("types", "Vorgangstypen", "skip", "nicht lesbar (HTTP %d)" % resp["status"])
    except net.NetError as e:
        r.add("types", "Vorgangstypen", "skip", e.detail)

    # Sprint-Feld
    only_active = bool(form.get("only_active_sprints", True))
    sf = ""
    try:
        resp = _get(base, "/rest/api/2/field", hdr, ctx)
        if resp["status"] == 200:
            for f in net.parse_json(resp) or []:
                if f.get("name") == "Sprint" and "gh-sprint" in str((f.get("schema") or {}).get("custom", "")):
                    sf = f["id"]
                    break
        if sf:
            r.add("sprintfield", "Sprints", "ok", "Sprint-Feld gefunden (%s). Jira Software ist aktiv." % sf)
        elif only_active:
            r.add("sprintfield", "Sprints", "warn", "Kein Sprint-Feld gefunden.",
                  "Ohne Jira Software gibt es keine Sprints, und «nur aktive Sprints» findet dann nichts oder meldet einen Fehler. "
                  "Schalte die Option aus, wenn ihr keine Sprints nutzt.")
        else:
            r.add("sprintfield", "Sprints", "skip", "Kein Sprint-Feld (nicht nötig, «nur aktive Sprints» ist aus).")
    except net.NetError as e:
        r.add("sprintfield", "Sprints", "skip", e.detail)

    # JQL
    jql_user = (form.get("jql") or "").strip() or JQL_DEFAULT
    jql = sprint.effective_jql(jql_user, only_active)
    statuses = []
    try:
        sr = _get(base, "/rest/api/2/status", hdr, ctx)
        if sr["status"] == 200:
            statuses = sorted({s["name"] for s in (net.parse_json(sr) or []) if "name" in s})
    except net.NetError:
        pass
    try:
        fields = "summary,status,issuetype" + ("," + sf if sf else "")
        resp = _get(base, "/rest/api/2/search", hdr, ctx, {"jql": jql, "fields": fields, "maxResults": 50})
        st, d = resp["status"], net.parse_json(resp)
        used = ("Abgefragt wird: %s\n" % jql) if jql != jql_user else ""
        if st == 200 and isinstance(d, dict):
            total = int(d.get("total", 0))
            issues = d.get("issues", [])
            want = {t.strip().lower() for t in (form.get("issue_types") or []) if t.strip()}
            counted = [i for i in issues if not want or ((i.get("fields") or {}).get("issuetype") or {}).get("name", "").lower() in want]

            def line(i):
                f = i.get("fields") or {}
                sp = sprint.active_sprint(f.get(sf)) if sf else None
                return "%s · %s · %s · %s%s" % (i["key"], (f.get("issuetype") or {}).get("name", ""), (f.get("status") or {}).get("name", ""),
                                               (f.get("summary") or "")[:50], (" · " + sp["name"]) if sp else "")
            limit = int(form.get("story_limit") or 2)
            det = used + "%d Treffer, davon %d zählen beim Limit (%d)." % (total, len(counted), limit)
            lines = [line(i) for i in issues[:6]]
            det += ("\n" + "\n".join(lines)) if lines else ""
            if len(counted) > limit:
                r.add("jql", "JQL «in Arbeit»", "warn", det, "Über dem Limit: Das Panel zeigt dann ein rotes Banner.")
            elif total == 0:
                r.add("jql", "JQL «in Arbeit»", "warn", det,
                      "0 Treffer: Stimmt das, oder heißt der Status anders? Status in deinem Jira: %s.%s" % (
                          ", ".join(statuses) or "nicht lesbar",
                          " Ist gerade ein Sprint aktiv und sind die Tickets darin?" if only_active else ""))
            else:
                r.add("jql", "JQL «in Arbeit»", "ok", det)
        elif st == 400:
            hint = "Teste die Abfrage im Jira-Suchfeld (Erweitert). Status in deinem Jira: %s." % (", ".join(statuses) or "nicht lesbar")
            if only_active and "sprint" in _msg(resp).lower():
                hint = ("Die Funktion openSprints() gibt es nur mit Jira Software. Schalte «nur aktive Sprints» aus, wenn ihr keine Sprints nutzt. "
                        + hint)
            r.add("jql", "JQL «in Arbeit»", "fail", used + "Jira weist die JQL ab: %s" % _msg(resp), hint)
        else:
            r.add("jql", "JQL «in Arbeit»", "fail", "HTTP %d: %s" % (st, _msg(resp)))
    except net.NetError as e:
        r.add("jql", "JQL «in Arbeit»", "fail", e.detail)
    return r.result(projects=keys, types=types, statuses=statuses,
                    user={"name": user.get("name"), "displayName": user.get("displayName")} if user else None)


def test_helpdesk(form, stored):
    """Helpdesk-Jira (nur lesend): API, Anmeldung, «Mir zugewiesen», Queue. form: url, auth, username, secret, ca_bundle, assigned_jql, queue_jql."""
    r = Report()
    base, ok = _check_url(r, form.get("url"), "helpdesk")
    if not ok:
        return r.result()
    ctx = _check_connection(r, base, form.get("ca_bundle"))
    steps = (("api", "Jira-API"), ("auth", "Anmeldung"), ("assigned", "Mir zugewiesen"), ("queue", "Queue"), ("watch", "Ich beobachte"))
    if ctx is None:
        for sid, t in steps:
            r.skip(sid, t)
        return r.result()
    try:
        resp = _get(base, "/rest/api/2/serverInfo", {"Accept": "application/json"}, ctx, svc="Helpdesk")
        d, st = net.parse_json(resp), resp["status"]
        if st == 200 and isinstance(d, dict) and d.get("version"):
            old = d["version"].split(".")[:2]
            r.add("api", "Jira-API", "ok", "%s %s (%d ms)" % (d.get("serverTitle", "Jira"), d["version"], resp["ms"]))
            if (form.get("auth") or "basic") == "bearer" and old and old[0].isdigit() and (int(old[0]), int(old[1] if len(old) > 1 and old[1].isdigit() else 0)) < (8, 14):
                r.add("pat", "Personal Access Token", "warn", "Jira %s kennt noch keine Personal Access Tokens (erst ab 8.14)." % d["version"],
                      "Stelle die Anmeldeart auf «basic» und nimm Benutzername und Passwort.")
        elif st in (401, 403) and not net.looks_html(resp):
            r.add("api", "Jira-API", "ok", "Jira-API antwortet (HTTP %d ohne Anmeldung)" % st)
        elif net.looks_html(resp) or st in (301, 302, 303, 307, 308, 404):
            r.add("api", "Jira-API", "fail", "HTTP %d: keine Jira-API unter %s/rest/api/2." % (st, base),
                  "Stimmt die Adresse? Läuft Jira unter einem Kontextpfad (z. B. https://host/jira)?")
        else:
            r.add("api", "Jira-API", "fail", "HTTP %d: %s" % (st, _msg(resp)))
    except net.NetError as e:
        r.add("api", "Jira-API", "fail", e.detail, net_hint(e.kind))
    if r.blocked:
        for sid, t in steps[1:]:
            r.skip(sid, t)
        return r.result()
    hdr, src, problem = _jira_headers(form, stored, "helpdesk", "basic")
    auth = form.get("auth") or "basic"
    if hdr is None:
        r.add("auth", "Anmeldung", "fail", problem, "Benutzername und Passwort eingeben." if auth == "basic" else "Personal Access Token eingeben.")
        for sid, t in steps[2:]:
            r.skip(sid, t)
        return r.result()
    ck = (base, (form.get("username") or "").strip().lower())
    if auth == "basic" and _cool.get(ck, 0) > time.time():
        r.add("auth", "Anmeldung", "fail", "Pause nach dem letzten Fehlversuch (noch %d s)." % (_cool[ck] - time.time()),
              "Mehrere falsche Passwörter in Folge sperren das Konto oder lösen ein CAPTCHA aus. Erst im Browser prüfen, dann erneut testen.")
        for sid, t in steps[2:]:
            r.skip(sid, t)
        return r.result()
    user = None
    try:
        resp = _get(base, "/rest/api/2/myself", hdr, ctx, svc="Helpdesk")
        st, d = resp["status"], net.parse_json(resp)
        denied = resp["headers"].get("x-authentication-denied-reason", "") + resp["headers"].get("x-seraph-loginreason", "")
        if st == 200 and isinstance(d, dict) and d.get("name"):
            user = d
            r.add("auth", "Anmeldung", "ok", "Angemeldet als %s (%s), %s aus: %s" % (d["name"], d.get("displayName", ""), "Token" if auth == "bearer" else "Passwort", src))
        elif "captcha" in denied.lower():
            r.add("auth", "Anmeldung", "fail", "Jira verlangt ein CAPTCHA.", "Einmal im Browser anmelden und das CAPTCHA lösen, dann erneut testen.")
        elif st == 401:
            if auth == "basic":
                _cool[ck] = time.time() + COOLDOWN_S
            r.add("auth", "Anmeldung", "fail", "HTTP 401: Zugangsdaten werden nicht akzeptiert.",
                  "Benutzername (nicht E-Mail) und Passwort prüfen." if auth == "basic" else "Token falsch oder abgelaufen?")
        else:
            r.add("auth", "Anmeldung", "fail", "HTTP %d: %s" % (st, _msg(resp)))
    except net.NetError as e:
        r.add("auth", "Anmeldung", "fail", e.detail, net_hint(e.kind))
    if r.blocked:
        for sid, t in steps[2:]:
            r.skip(sid, t)
        return r.result()
    import helpdesk as hdmod
    for sid, title, jql in (("assigned", "Mir zugewiesen", (form.get("assigned_jql") or "").strip() or hdmod.DEFAULTS["assigned_jql"]),
                            ("queue", "Queue", (form.get("queue_jql") or "").strip()),
                            ("watch", "Ich beobachte", (form.get("watch_jql") or "").strip())):
        if not jql:
            r.skip(sid, title, "keine JQL eingetragen")
            continue
        try:
            resp = _get(base, "/rest/api/2/search", hdr, ctx, {"jql": jql, "fields": "summary,status,priority", "maxResults": 5}, svc="Helpdesk")
            st, d = resp["status"], net.parse_json(resp)
            if st == 200 and isinstance(d, dict):
                lines = ["%s · %s · %s" % (i["key"], ((i.get("fields") or {}).get("status") or {}).get("name", ""),
                                            ((i.get("fields") or {}).get("summary") or "")[:50]) for i in d.get("issues", [])[:5]]
                r.add(sid, title, "ok", "%d Tickets.%s" % (int(d.get("total", 0)), ("\n" + "\n".join(lines)) if lines else ""))
            elif st == 400:
                r.add(sid, title, "fail", "Jira weist die JQL ab: %s" % _msg(resp), "Teste die Abfrage im Jira-Suchfeld (Erweitert).")
            else:
                r.add(sid, title, "fail", "HTTP %d: %s" % (st, _msg(resp)))
        except net.NetError as e:
            r.add(sid, title, "fail", e.detail)
    return r.result(user={"name": user.get("name"), "displayName": user.get("displayName")} if user else None)
