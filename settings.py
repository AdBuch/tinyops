"""Einstellungen: Verbindungstests für GitLab und Jira mit verständlichen Fehlern, Speichern von Config und Secrets.

Die Tests laufen Schritt für Schritt (Adresse, Namensauflösung, Verbindung, Zertifikat, API, Anmeldung, Rechte, ...)
und zeigen pro Schritt, was geklappt hat und woran es hängt. Ein Fehler stoppt die folgenden Schritte, weil sie
darauf aufbauen. Secrets werden nie zurückgegeben, nur ob und wo sie gespeichert sind.
"""
import json
import os
import re
import shlex
import tempfile
import time
import urllib.parse
from pathlib import Path

import agents
import github
import llm
import net
import secretstore as store
import sonar
import usage
import focusplan
import helpdesk
import sprint
import timesheet
import tlog

log = tlog.get("settings")

_cool = {}   # (Jira-Adresse, Benutzer) → Zeitpunkt, bis zu dem nach einem Fehlversuch nicht erneut getestet wird
COOLDOWN_S = 30
JQL_DEFAULT = 'assignee = currentUser() AND statusCategory = "In Progress" ORDER BY updated DESC'
SECRET_FIELDS = ("gitlab_token", "jira_token", "jira_password", "llm_key", "sonar_token", "github_token", "mcp_token",
                 "helpdesk_token", "helpdesk_password")
KEY_RE = re.compile(r"^[A-Z][A-Z0-9_]{1,19}$")
CONFIG_KEYS_FEATURES = ("ideas", "testenv", "ai")


# ------------------------------------------------------------ Bericht
class Report:
    def __init__(self):
        self.steps = []
        self.blocked = False

    def add(self, sid, title, status, detail="", hint=""):
        self.steps.append({"id": sid, "title": title, "status": status, "detail": detail, "hint": hint})
        if status == "fail":
            self.blocked = True

    def skip(self, sid, title, why="übersprungen, weil ein früherer Schritt fehlgeschlagen ist"):
        self.steps.append({"id": sid, "title": title, "status": "skip", "detail": why, "hint": ""})

    def result(self, **extra):
        out = {"ok": not any(s["status"] == "fail" for s in self.steps), "steps": self.steps}
        out.update(extra)
        return json.loads(store.scrub(json.dumps(out, ensure_ascii=False)))


def net_hint(kind, scheme="https"):
    return {
        "dns": "Tippfehler im Namen? Interne Namen lösen oft nur im Firmennetz auf: VPN verbunden? Ein Test mit der IP-Adresse zeigt, ob es am DNS liegt.",
        "refused": "Stimmt der Port? https nutzt normalerweise 443, http 80. Läuft der Dienst auf einem eigenen Port (zum Beispiel https://host:8443)?",
        "timeout": "Firewall, fehlendes VPN oder ein Proxy, der nicht antwortet. Ist der Dienst vom Browser dieses Rechners aus erreichbar?",
        "unreachable": "Keine Route zum Server: VPN oder Netzwerk prüfen. Läuft tinyops auf dem Rechner, der den Server sehen darf?",
        "reset": "Oft ein Proxy oder eine Firewall, die die Verbindung kappt, oder http/https verwechselt (http auf einem https-Port).",
        "tls_verify": ("Typisch bei einer Firmen-CA: Das Wurzelzertifikat als PEM-Datei speichern und den Pfad bei «CA-Datei» eintragen. "
                       "Die Kette zeigt: openssl s_client -showcerts -connect HOST:PORT. Die Prüfung abzuschalten ist absichtlich nicht möglich."),
        "tls_hostname": "Die Adresse muss genau dem Namen im Zertifikat entsprechen (nicht die IP, nicht ein Alias). Frag, unter welchem Namen das Zertifikat ausgestellt ist.",
        "tls_expired": "Das Serverzertifikat ist abgelaufen. Das muss der Betreiber des Servers erneuern.",
        "tls": "Meist verwechselte Protokolle (https auf einem http-Port) oder ein sehr altes TLS auf dem Server.",
    }.get(kind, "")


def _base(url):
    """Normalisiert die Basisadresse und gibt (Adresse, Hinweis) zurück."""
    url = (url or "").strip().rstrip("/")
    note = ""
    if "/-/" in url:
        url = url.split("/-/")[0]
        note = "Das sah nach einer Seiten-Adresse aus; verwendet wird nur die Basisadresse."
    if url.endswith("/api/v4"):
        url = url[:-len("/api/v4")]
        note = "«/api/v4» gehört nicht in die Adresse, es wird ergänzt."
    if url.endswith("/rest/api/2"):
        url = url[:-len("/rest/api/2")]
        note = "«/rest/api/2» gehört nicht in die Adresse, es wird ergänzt."
    return url.rstrip("/"), note


def _check_url(r, url, what):
    """Schritt «Adresse». Gibt (Basisadresse, ok) zurück."""
    base, note = _base(url)
    if not base:
        r.add("url", "Adresse", "fail", "Keine Adresse eingegeben.", "Zum Beispiel https://%s.firma.example" % what)
        return "", False
    u = urllib.parse.urlparse(base)
    if u.scheme not in ("http", "https") or not u.hostname:
        r.add("url", "Adresse", "fail", "«%s» ist keine gültige Adresse." % base,
              "Sie muss mit https:// (oder http://) beginnen, gefolgt vom Servernamen.")
        return "", False
    if u.query or u.fragment:
        r.add("url", "Adresse", "warn", base, "Parameter (?...) gehören nicht in die Adresse.")
    elif u.scheme == "http" and u.hostname not in ("localhost", "127.0.0.1", "::1"):
        r.add("url", "Adresse", "warn", base + " (unverschlüsselt)",
              "Mit http:// geht der Token im Klartext durchs Netz. Nutze https://, wenn der Server es anbietet.")
    else:
        r.add("url", "Adresse", "ok", base + ((" · " + note) if note else ""))
    if note and u.scheme in ("http", "https"):
        r.steps[-1]["detail"] = base + " · " + note
    return base, True


def _check_connection(r, base, ca):
    """Schritte CA-Datei, Namensauflösung, Verbindung, Zertifikat. Gibt den TLS-Kontext zurück oder None."""
    try:
        ctx = net.make_ssl_ca((ca or "").strip())
    except ValueError as e:
        r.add("ca", "CA-Datei", "fail", str(e), "Pfad prüfen (auf dem Rechner, auf dem tinyops läuft) und eine PEM-Datei angeben.")
        return None
    if (ca or "").strip():
        r.add("ca", "CA-Datei", "ok", ca.strip())
    host, port, scheme = net.host_port(base)
    try:
        ips, ms = net.check_dns(host, port)
        r.add("dns", "Name auflösen", "ok", "%s → %s (%d ms)" % (host, ", ".join(ips[:3]), ms))
    except net.NetError as e:
        r.add("dns", "Name auflösen", "fail", e.detail, net_hint("dns"))
        return None
    try:
        ms = net.check_tcp(host, port)
        r.add("tcp", "Verbindung", "ok", "%s:%d antwortet (%d ms)" % (host, port, ms))
    except net.NetError as e:
        r.add("tcp", "Verbindung", "fail", e.detail, net_hint(e.kind))
        return None
    if scheme == "https":
        try:
            c = net.check_tls(host, port, ctx)
            d = "%s, ausgestellt von %s, %s" % (c["subject"], c["issuer"], c["version"])
            if c["days_left"] is not None:
                d += ", noch %d Tage gültig" % c["days_left"]
            if c["days_left"] is not None and c["days_left"] < 14:
                r.add("tls", "Zertifikat", "warn", d, "Läuft bald ab. Das muss der Betreiber des Servers erneuern.")
            else:
                r.add("tls", "Zertifikat", "ok", d)
        except net.NetError as e:
            r.add("tls", "Zertifikat", "fail", e.detail, net_hint(e.kind))
            return None
    else:
        r.add("tls", "Zertifikat", "skip", "kein TLS (http)")
    return ctx


def _msg(resp):
    """Kurze Fehlermeldung aus einer JSON- oder Textantwort."""
    data = net.parse_json(resp)
    if isinstance(data, dict):
        for k in ("message", "error_description", "error"):
            v = data.get(k)
            if v:
                return str(v)[:200] if not isinstance(v, (dict, list)) else json.dumps(v, ensure_ascii=False)[:200]
        errs = data.get("errorMessages")
        if errs:
            return "; ".join(str(x) for x in errs)[:300]
    if net.looks_html(resp):
        return "HTML-Seite statt JSON"
    return resp["body"][:120].decode("utf-8", "replace").strip()


def _redirect_hint(resp, base):
    loc = resp["headers"].get("location", "")
    if not loc:
        return "Der Server leitet um."
    return ("Der Server leitet nach %s um. Trage diese Adresse (ohne Pfad ab /api oder /rest) in das Feld ein; "
            "häufig ist es http→https oder ein anderer Hostname." % loc)


def _get(base, path, headers, ctx, params=None, timeout=10):
    url = base + path + (("?" + urllib.parse.urlencode(params)) if params else "")
    return net.probe(url, headers, ctx, timeout=timeout)


def _token(form, stored, name):
    raw = form.get("secret") if form.get("secret") is not None else form.get("token")
    tok = (raw or "").strip()
    if tok:
        src = "gerade eingegeben"
    else:
        tok, src = stored(name)
        tok = (tok or "").strip()
    if tok:
        store.register(tok)
    return tok, src


# ------------------------------------------------------------ GitLab
def test_gitlab(form, stored):
    """form: url, ca_bundle, token (optional), projects (IDs). stored(name) → (Wert, Quelle)."""
    r = Report()
    base, ok = _check_url(r, form.get("url"), "gitlab")
    if not ok:
        return r.result()
    ctx = _check_connection(r, base, form.get("ca_bundle"))
    if ctx is None:
        for sid, t in (("api", "GitLab-API"), ("auth", "Anmeldung"), ("scopes", "Token-Rechte"), ("version", "Version"), ("projects", "Projekte")):
            r.skip(sid, t)
        return r.result()

    # API vorhanden?
    try:
        resp = _get(base, "/api/v4/version", {"Accept": "application/json"}, ctx)
        data = net.parse_json(resp)
        st = resp["status"]
        if st == 200 and isinstance(data, dict) and "version" in data:
            r.add("api", "GitLab-API", "ok", "GitLab %s (%d ms)" % (data["version"], resp["ms"]))
        elif st == 401 and isinstance(data, dict):
            r.add("api", "GitLab-API", "ok", "GitLab-API antwortet und verlangt Anmeldung (%d ms)" % resp["ms"])
        elif st in (301, 302, 303, 307, 308):
            r.add("api", "GitLab-API", "fail", "HTTP %d: Weiterleitung nach %s" % (st, resp["headers"].get("location", "?")),
                  _redirect_hint(resp, base))
        elif st == 404:
            r.add("api", "GitLab-API", "fail", "HTTP 404: unter %s/api/v4 gibt es keine GitLab-API." % base,
                  "Läuft GitLab unter einem Unterpfad (zum Beispiel https://host/gitlab)? Dann gehört der Pfad in die Adresse. "
                  "Oder ist es gar nicht GitLab?")
        elif st == 403:
            r.add("api", "GitLab-API", "fail", "HTTP 403: %s" % _msg(resp),
                  "Eine Firewall, ein Reverse-Proxy oder eine IP-Sperre blockiert die Anfrage, bevor GitLab sie sieht.")
        elif st >= 500:
            r.add("api", "GitLab-API", "fail", "HTTP %d: %s" % (st, _msg(resp)),
                  "Server oder Proxy meldet einen Fehler: GitLab startet gerade neu oder ist im Wartungsmodus. Später nochmal versuchen.")
        else:
            r.add("api", "GitLab-API", "fail", "HTTP %d: %s" % (st, _msg(resp)),
                  "Das sieht nicht wie die GitLab-API aus (Login-Seite eines Proxys? falsche Adresse?).")
    except net.NetError as e:
        r.add("api", "GitLab-API", "fail", e.detail, net_hint(e.kind))
    if r.blocked:
        for sid, t in (("auth", "Anmeldung"), ("scopes", "Token-Rechte"), ("version", "Version"), ("projects", "Projekte")):
            r.skip(sid, t)
        return r.result()

    # Anmeldung
    tok, src = _token(form, stored, "gitlab_token")
    if not tok:
        r.add("auth", "Anmeldung", "fail", "Kein Token eingegeben und keiner gespeichert.",
              "Token anlegen: %s/-/user_settings/personal_access_tokens (Scope «read_api»), dann hier einfügen." % base)
        for sid, t in (("scopes", "Token-Rechte"), ("version", "Version"), ("projects", "Projekte")):
            r.skip(sid, t)
        return r.result()
    hdr = {"PRIVATE-TOKEN": tok, "Accept": "application/json"}
    me = None
    try:
        resp = _get(base, "/api/v4/user", hdr, ctx)
        st, data = resp["status"], net.parse_json(resp)
        if st == 200 and isinstance(data, dict) and data.get("username"):
            me = data
            r.add("auth", "Anmeldung", "ok", "Angemeldet als %s (%s, %s), Token aus: %s" % (
                data["username"], data.get("name", ""), data.get("email") or "E-Mail nicht sichtbar", src))
        elif st == 401:
            r.add("auth", "Anmeldung", "fail", "HTTP 401: Der Token wird nicht akzeptiert (%s)." % _msg(resp),
                  "Token ungültig, abgelaufen oder widerrufen? Kopierfehler (Leerzeichen, Zeilenumbruch, unvollständig)? "
                  "Neuen Token anlegen: %s/-/user_settings/personal_access_tokens, Scope «read_api»." % base)
        elif st == 403:
            r.add("auth", "Anmeldung", "fail", "HTTP 403: %s" % _msg(resp),
                  "Der Token ist bekannt, darf aber die API nicht nutzen: Scope «read_api» fehlt, oder das Konto ist gesperrt.")
        else:
            r.add("auth", "Anmeldung", "fail", "HTTP %d: %s" % (st, _msg(resp)), "Unerwartete Antwort von GitLab.")
    except net.NetError as e:
        r.add("auth", "Anmeldung", "fail", e.detail, net_hint(e.kind))
    if r.blocked:
        for sid, t in (("scopes", "Token-Rechte"), ("version", "Version"), ("projects", "Projekte")):
            r.skip(sid, t)
        return r.result()

    # Token-Rechte
    try:
        resp = _get(base, "/api/v4/personal_access_tokens/self", hdr, ctx)
        d = net.parse_json(resp)
        if resp["status"] == 200 and isinstance(d, dict):
            scopes = d.get("scopes") or []
            more = sorted(set(scopes) - {"read_api", "read_user", "read_repository"})
            exp = d.get("expires_at")
            det = "Scopes: %s; %s" % (", ".join(scopes) or "keine", ("läuft ab am " + exp) if exp else "läuft nie ab")
            hint = ""
            status = "ok"
            if more:
                status, hint = "warn", "Der Token darf mehr als nötig (%s). tinyops liest nur; «read_api» genügt und ist sicherer." % ", ".join(more)
            elif not scopes or ("read_api" not in scopes and "api" not in scopes):
                status, hint = "warn", "«read_api» fehlt: ohne ihn lassen sich MRs und Branches nicht lesen."
            if not exp:
                status = "warn"
                hint = (hint + " " if hint else "") + "Ein Ablaufdatum begrenzt den Schaden, falls der Token mal verloren geht."
            r.add("scopes", "Token-Rechte", status, det, hint)
        else:
            r.add("scopes", "Token-Rechte", "skip", "Nicht lesbar (HTTP %d). Kein Problem, nur eine Zusatzinfo." % resp["status"])
    except net.NetError as e:
        r.add("scopes", "Token-Rechte", "skip", e.detail)

    # Version
    try:
        resp = _get(base, "/api/v4/version", hdr, ctx)
        d = net.parse_json(resp)
        if resp["status"] == 200 and isinstance(d, dict) and d.get("version"):
            r.add("version", "Version", "ok", "GitLab %s" % d["version"])
        else:
            r.add("version", "Version", "skip", "nicht lesbar (HTTP %d)" % resp["status"])
    except net.NetError as e:
        r.add("version", "Version", "skip", e.detail)

    # Projekte
    ids = [str(x) for x in (form.get("projects") or [])]
    if not ids:
        r.add("projects", "Projekte", "warn", "Noch kein Projekt gewählt.",
              "Ohne Projekte zeigt tinyops nur die Review-Queue und dir zugeteilte MRs. Projekte unten suchen und hinzufügen.")
    for pid in ids[:20]:
        try:
            resp = _get(base, "/api/v4/projects/%s" % urllib.parse.quote(pid, safe=""), hdr, ctx)
            d = net.parse_json(resp)
            if resp["status"] == 200 and isinstance(d, dict):
                r.add("project-%s" % pid, "Projekt %s" % pid, "ok", "%s, Default-Branch: %s" % (d.get("path_with_namespace"), d.get("default_branch")))
            elif resp["status"] == 404:
                r.add("project-%s" % pid, "Projekt %s" % pid, "fail", "HTTP 404: nicht gefunden.",
                      "Falsche ID oder dein Konto darf das Projekt nicht sehen. Die ID steht auf der Projektseite unter ⋮ → «Projekt-ID kopieren».")
            else:
                r.add("project-%s" % pid, "Projekt %s" % pid, "fail", "HTTP %d: %s" % (resp["status"], _msg(resp)))
        except net.NetError as e:
            r.add("project-%s" % pid, "Projekt %s" % pid, "fail", e.detail)
    _check_mr_fields(r, base, hdr, ctx, ids[:20])
    return r.result(user={"username": me.get("username"), "name": me.get("name"), "email": me.get("email")} if me else None)


def _check_mr_fields(r, base, hdr, ctx, ids):
    """Liefert diese GitLab-Instanz, was der Ablauf für Review und Merge braucht? Prüft an einem offenen MR (nur lesend)."""
    for pid in ids:
        try:
            resp = _get(base, "/api/v4/projects/%s/merge_requests" % urllib.parse.quote(pid, safe=""), hdr, ctx, {"state": "opened", "per_page": 1})
        except net.NetError:
            continue
        mrs = net.parse_json(resp) if resp["status"] == 200 else None
        if not mrs or not isinstance(mrs, list):
            continue
        mr = mrs[0]
        fields = ("detailed_merge_status", "reviewers", "upvotes")
        have = [f for f in fields if f in mr]
        miss = [f for f in fields if f not in mr]
        try:
            ap = _get(base, "/api/v4/projects/%s/merge_requests/%s/approvals" % (urllib.parse.quote(pid, safe=""), mr.get("iid")), hdr, ctx)
            ap_ok = ap["status"] == 200
            ap_txt = "Freigaben lesbar" if ap_ok else "Freigaben nicht lesbar (HTTP %d)" % ap["status"]
        except net.NetError as e:
            ap_ok, ap_txt = False, "Freigaben nicht lesbar (%s)" % e.detail
        det = "geprüft an !%s in Projekt %s: %s%s; %s" % (mr.get("iid"), pid, ", ".join(have) or "keines der Felder",
                                                         (" · fehlt: " + ", ".join(miss)) if miss else "", ap_txt)
        if not miss and ap_ok:
            r.add("mrfields", "Review-Felder", "ok", det)
        else:
            r.add("mrfields", "Review-Felder", "warn", det,
                  "Ohne diese Angaben zeigt tinyops «Freigabe prüfen» statt einer automatischen Prüfung. detailed_merge_status gibt es ab GitLab 15.6, "
                  "/approvals braucht mindestens Reporter-Rechte im Projekt.")
        return
    r.add("mrfields", "Review-Felder", "skip", "kein offener MR in den gewählten Projekten, an dem sich das prüfen liesse")


def search_projects(form, stored):
    base, _ = _base(form.get("url"))
    tok, _src = _token(form, stored, "gitlab_token")
    q = (form.get("q") or "").strip()
    try:
        ctx = net.make_ssl_ca((form.get("ca_bundle") or "").strip())
        hdr = {"PRIVATE-TOKEN": tok, "Accept": "application/json"}
        if q.isdigit():
            resp = _get(base, "/api/v4/projects/%s" % q, hdr, ctx)
            items = [net.parse_json(resp)] if resp["status"] == 200 else []
        else:
            resp = _get(base, "/api/v4/projects", hdr, ctx, {"membership": "true", "search": q, "simple": "true", "per_page": 15,
                                                          "order_by": "last_activity_at"})
            items = net.parse_json(resp) if resp["status"] == 200 else []
        if resp["status"] not in (200, 404):
            return {"error": "HTTP %d: %s" % (resp["status"], _msg(resp)), "items": []}
        return {"items": [{"id": p["id"], "name": p.get("path") or p.get("name"), "full": p.get("path_with_namespace")}
                          for p in (items or []) if isinstance(p, dict) and "id" in p]}
    except (net.NetError, ValueError) as e:
        return {"error": getattr(e, "detail", str(e)), "items": []}


def suggest_identity(form, stored):
    """Autoren der letzten Commits eines Projekts, damit du «ich» und «Agent» ankreuzen kannst."""
    base, _ = _base(form.get("url"))
    tok, _src = _token(form, stored, "gitlab_token")
    pid = str(form.get("project_id") or "").strip()
    if not pid:
        return {"error": "Zuerst ein Projekt hinzufügen."}
    try:
        ctx = net.make_ssl_ca((form.get("ca_bundle") or "").strip())
        hdr = {"PRIVATE-TOKEN": tok, "Accept": "application/json"}
        me = net.parse_json(_get(base, "/api/v4/user", hdr, ctx)) or {}
        resp = _get(base, "/api/v4/projects/%s/repository/commits" % urllib.parse.quote(pid, safe=""), hdr, ctx,
                    {"all": "true", "per_page": 100})
        if resp["status"] != 200:
            return {"error": "HTTP %d: %s" % (resp["status"], _msg(resp))}
        commits = net.parse_json(resp) or []
    except (net.NetError, ValueError) as e:
        return {"error": getattr(e, "detail", str(e))}
    people, trailers = {}, {}
    for c in commits:
        key = ((c.get("author_name") or ""), (c.get("author_email") or "").lower())
        people[key] = people.get(key, 0) + 1
        for line in (c.get("message") or "").splitlines():
            if line.lower().startswith("co-authored-by:"):
                n = normalize_trailer(line)
                trailers[n] = trailers.get(n, 0) + 1
    me_mail = (me.get("email") or "").lower()
    authors = [{"name": n, "email": e, "count": k, "is_me": bool(e and e == me_mail)}
               for (n, e), k in sorted(people.items(), key=lambda x: -x[1])[:12]]
    return {"authors": authors, "trailers": [{"pattern": p, "count": k} for p, k in sorted(trailers.items(), key=lambda x: -x[1])[:8]],
            "me": {"name": me.get("name"), "email": me.get("email")}, "commits": len(commits)}


def normalize_trailer(line):
    """«Co-Authored-By: Claude Sonnet 5.5 <x>» wird zu «Co-Authored-By: Claude»: überlebt Modellwechsel."""
    body = line.split(":", 1)[1].strip().split("<")[0].strip()
    first = body.split()[0] if body.split() else body
    return "Co-Authored-By: " + first


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


def test_llm(form, stored):
    """Prüft den lokalen Sprachmodell-Server: Adresse (nur eigenes Netz), Antwort, Modell, Testentwurf."""
    cfg = {"provider": form.get("provider") or "ollama", "url": (form.get("url") or "").strip(), "model": (form.get("model") or "").strip(),
           "allow_remote": bool(form.get("allow_remote")), "timeout": _int(form.get("timeout"), "timeout", 10, 900, {}, 120)}
    key = (form.get("secret") or "").strip() or (stored("llm_key")[0] or "")
    if key:
        store.register(key)
    steps, models = llm.test(cfg, key)
    r = Report()
    for status, title, detail, hint in steps:
        r.add(title.lower(), title, status, detail, hint)
    return r.result(models=models[:40])


def test_mcp(form, stored):
    """Prüft die Wrapper-API deines MCP, ohne etwas zu buchen: Adresse im eigenen Netz, erreichbar (GET), Token angenommen."""
    r = Report()
    url = (form.get("url") or "").strip()
    u = urllib.parse.urlparse(url)
    if u.scheme not in ("http", "https") or not u.hostname:
        r.add("url", "Adresse", "fail", "Keine gültige Adresse.", "Zum Beispiel http://127.0.0.1:3100/time-entries")
        r.skip("reach", "Erreichbar")
        return r.result()
    if not form.get("allow_remote") and not llm.is_local(url):
        r.add("url", "Adresse", "fail", "«%s» liegt nicht im eigenen Netz." % u.hostname, "Nur mit «Externe Adresse erlauben».")
        r.skip("reach", "Erreichbar")
        return r.result()
    r.add("url", "Adresse", "ok", url)
    tok = (form.get("secret") or "").strip() or (stored("mcp_token")[0] or "")
    if tok:
        store.register(tok)
    h = {"Accept": "application/json", "User-Agent": "tinyops"}
    if tok:
        h["Authorization"] = "Bearer " + tok
    try:
        resp = net.probe(url, h, None, timeout=8)
    except net.NetError as e:
        r.add("reach", "Erreichbar", "fail", e.detail, net_hint(e.kind, u.scheme) if hasattr(e, "kind") else "")
        return r.result()
    st = resp["status"]
    if st in (401, 403):
        r.add("reach", "Erreichbar", "fail", "HTTP %s: Token fehlt oder wird abgelehnt." % st, "Token unten eintragen (wird als mcp_token gespeichert).")
    else:
        r.add("reach", "Erreichbar", "ok", "HTTP %s auf GET (gebucht wird nur per POST nach «Bestätigen»)." % st)
    return r.result()


def test_sonar(form, stored):
    """Prüft SonarQube (nur lesend): Adresse, Verbindung, Anmeldung, Version und die Projektschlüssel der GitLab-Projekte.
    form: url, ca_bundle, secret/token, projects [{id, name, sonar_key}]."""
    r = Report()
    base, ok = _check_url(r, form.get("url"), "sonar")
    steps = (("api", "Sonar-API"), ("auth", "Anmeldung"), ("keys", "Projektschlüssel"), ("prs", "Pull-Request-Analyse"))
    if not ok:
        return r.result()
    ctx = _check_connection(r, base, form.get("ca_bundle"))
    if ctx is None:
        for sid, t in steps:
            r.skip(sid, t)
        return r.result()
    try:
        resp = _get(base, "/api/system/status", {"Accept": "application/json"}, ctx)
        data = net.parse_json(resp)
        if resp["status"] == 200 and isinstance(data, dict) and "version" in data:
            r.add("api", "Sonar-API", "ok", "SonarQube %s (%s)" % (data["version"], data.get("status", "?")))
        elif resp["status"] in (301, 302, 303, 307, 308):
            r.add("api", "Sonar-API", "fail", "HTTP %d: Weiterleitung nach %s" % (resp["status"], resp["headers"].get("location", "?")), _redirect_hint(resp, base))
        else:
            r.add("api", "Sonar-API", "fail", "HTTP %d: %s" % (resp["status"], _msg(resp)),
                  "Kein SonarQube unter dieser Adresse? Läuft es unter einem Kontextpfad (https://host/sonar)? Dann gehört der Pfad in die Adresse.")
    except net.NetError as e:
        r.add("api", "Sonar-API", "fail", e.detail, net_hint(e.kind))
    if r.blocked:
        for sid, t in steps[1:]:
            r.skip(sid, t)
        return r.result()
    tok, src = _token(form, stored, "sonar_token")
    if not tok:
        r.add("auth", "Anmeldung", "fail", "Kein Token eingegeben oder gespeichert.",
              "In Sonar: Mein Konto → Sicherheit → Token erzeugen (Typ «User Token»). Er braucht «Browse» auf den Projekten.")
        r.skip("keys", "Projektschlüssel")
        return r.result()
    hdr = sonar.headers(tok)
    try:
        resp = net.probe(base + "/api/authentication/validate", hdr, ctx, timeout=10)
        data = net.parse_json(resp)
        if resp["status"] == 200 and isinstance(data, dict) and data.get("valid"):
            r.add("auth", "Anmeldung", "ok", "Token gilt (%s)" % src)
        else:
            r.add("auth", "Anmeldung", "fail", "Token wird abgelehnt (HTTP %d)." % resp["status"],
                  "Token abgelaufen oder falsch kopiert? Es muss ein Benutzer-Token sein, kein Passwort.")
    except net.NetError as e:
        r.add("auth", "Anmeldung", "fail", e.detail, net_hint(e.kind))
    if r.blocked:
        r.skip("keys", "Projektschlüssel")
        return r.result()
    mapped = [(p.get("name") or p.get("id"), (p.get("sonar_key") or "").strip()) for p in (form.get("projects") or []) if (p.get("sonar_key") or "").strip()]
    if not mapped:
        r.add("keys", "Projektschlüssel", "warn", "Bei keinem GitLab-Projekt ist ein Sonar-Schlüssel eingetragen.",
              "Ohne Schlüssel zeigt das Panel nichts von Sonar. Der Schlüssel steht in Sonar unter Projekt → Projektinformationen.")
        return r.result()
    bad, good = [], []
    for name, key in mapped:
        try:
            resp = net.probe(base + "/api/components/show?" + urllib.parse.urlencode({"component": key}), hdr, ctx, timeout=10)
        except net.NetError as e:
            r.add("keys", "Projektschlüssel", "fail", e.detail, net_hint(e.kind))
            return r.result()
        (good if resp["status"] == 200 else bad).append("%s → %s%s" % (name, key, "" if resp["status"] == 200 else " (HTTP %d)" % resp["status"]))
    if bad:
        r.add("keys", "Projektschlüssel", "warn", "Nicht gefunden oder nicht sichtbar: %s" % "; ".join(bad),
              "Schlüssel genau wie in Sonar schreiben (Gross-/Kleinschreibung zählt). Der Token braucht «Browse» auf dem Projekt.")
    else:
        r.add("keys", "Projektschlüssel", "ok", "; ".join(good))
    # Pull-Request-Analyse (ab Developer Edition): ohne sie gibt es für MRs nie ein Quality Gate
    ok_keys = [k for n, k in mapped if not any(b.startswith("%s → %s " % (n, k)) for b in bad)]
    parts, unavailable = [], []
    for key in ok_keys:
        try:
            prs = sonar.Client(base, tok, ctx).pull_requests(key)
        except sonar.SonarError:
            prs = None
        if prs is None:
            unavailable.append(key)
        else:
            nums = sorted((int(p["key"]) for p in prs if str(p.get("key", "")).isdigit()), reverse=True)
            parts.append("%s: %d analysiert%s" % (key, len(prs), " (zuletzt !%d)" % nums[0] if nums else ""))
    if unavailable and not parts:
        r.add("prs", "Pull-Request-Analyse", "warn", "Nicht verfügbar für: %s" % ", ".join(unavailable),
              "Pull-Request-Analyse gibt es erst ab der Developer Edition. Ohne sie bleibt für MRs «keine Analyse»; Branches funktionieren nur mit mehreren analysierten Branches.")
    elif unavailable:
        r.add("prs", "Pull-Request-Analyse", "warn", "; ".join(parts) + "; nicht verfügbar für: " + ", ".join(unavailable))
    elif parts:
        r.add("prs", "Pull-Request-Analyse", "ok", "; ".join(parts) + ". Die MR-Nummer von GitLab muss als «sonar.pullrequest.key» an Sonar gehen (Standard in der CI-Anbindung).")
    else:
        r.skip("prs", "Pull-Request-Analyse")
    return r.result()


def test_agent(form, stored):
    """Prüft einen Agenten: Verbindung (bei SSH), tmux, Arbeitsordner und das Programm des Agenten. Schreibt nur ~/.tinyops/runs auf dem Zielhost.
    form: connection {name, host, user, port, identity_file, host_key} oder leer für lokal, agent {kind, workspace_root, extra_args}."""
    r = Report()
    errs = {}
    conns = agents.clean_connections([form["connection"]] if form.get("connection") else [], errs)
    a = form.get("agent") or {}
    kind = a.get("kind") if a.get("kind") in agents.KINDS else "claude"
    conn = conns[0] if conns else None
    steps = (("conn", "Verbindung"), ("tmux", "tmux"), ("ws", "Arbeitsordner"), ("bin", "Agent-Programm"))
    if form.get("connection") and (errs or conn is None):
        r.add("conn", "Verbindung", "fail", "; ".join(errs.values()) or "Angaben unvollständig.", "Name, Rechner und Port ausfüllen.")
        for sid, t in steps[1:]:
            r.skip(sid, t)
        return r.result()
    root = str(a.get("workspace_root") or "").strip()
    if not root or len(root) > 300 or "\n" in root or root.startswith("-"):
        r.add("ws", "Arbeitsordner", "fail", "Arbeitsordner fehlt oder ist ungültig.")
        return r.result()
    agent = {"kind": kind, "workspace_root": root, "connection": conn["id"] if conn else "local", "extra_args": ""}
    try:
        facts = agents.probe(agent, conn)
    except agents.AgentError as e:
        r.add("conn", "Verbindung", "fail", str(e))
        for sid, t in steps[1:]:
            r.skip(sid, t)
        return r.result()
    r.add("conn", "Verbindung", "ok", ("lokal (%s)" % facts["os"]) if conn is None else "%s antwortet (%s)" % (conn["host"], facts["os"]))
    if conn is None:
        r.add("tmux", "tmux", "ok", "wird lokal nicht gebraucht (losgelöster Prozess)")
    elif facts["tmux"]:
        r.add("tmux", "tmux", "ok", "gefunden")
    else:
        r.add("tmux", "tmux", "fail", "auf dem Zielhost nicht installiert", "Installieren, z. B. «sudo apt install tmux».")
    if not facts["writable"]:
        r.add("ws", "Arbeitsordner", "fail", "~/.tinyops/runs ist nicht beschreibbar", "Schreibrechte im Home-Verzeichnis des Benutzers prüfen.")
    elif facts["workspace"]:
        r.add("ws", "Arbeitsordner", "ok", "%s vorhanden (Repositories liegen darunter)" % root)
    else:
        r.add("ws", "Arbeitsordner", "fail", "%s existiert nicht" % root, "Ordner anlegen und die Repositories dort klonen.")
    if facts["bin"] is None:
        r.add("bin", "Agent-Programm", "ok", "eigener Befehl: nur in der config.json setzbar, hier nicht prüfbar")
    elif facts["bin"]:
        r.add("bin", "Agent-Programm", "ok", "%s: %s" % (agents.KINDS[kind]["bin"], facts["bin"]))
    else:
        r.add("bin", "Agent-Programm", "fail", "«%s» ist im PATH nicht zu finden" % agents.KINDS[kind]["bin"],
              "Anmelden und Programm installieren; getestet wird mit der Login-Shell des Benutzers (wie beim Start).")
    if facts["git"] and facts["sh"]:
        r.add("git", "Isolation", "ok", "git vorhanden: jeder Lauf bekommt einen eigenen Worktree (oder Export)")
    else:
        r.add("git", "Isolation", "fail", "git fehlt" if not facts["git"] else "sh fehlt",
              "Für Worktree und Export braucht der Agent git (und lokal unter Windows sh aus Git for Windows im PATH); sonst beim Agenten «gemeinsamer Ordner».")
    if conn is None:
        r.add("rights", "Rechte", "warn", "lokal läuft der Agent mit deinen Rechten und deinen Git-Zugangsdaten",
              "Für restricted-Repos lieber eine SSH-Verbindung zu einem eigenen Agent-Benutzer (ohne sudo, ohne Push auf geschützte Branches).")
    else:
        bad = [x for x, on in (("läuft als root", facts["root"]), ("sudo ohne Passwort", facts["sudo"]), ("Zugriff auf den Docker-Socket (= root)", facts["docker"])) if on]
        if bad:
            r.add("rights", "Rechte", "warn", "Benutzer %s: %s" % (facts["user"], ", ".join(bad)),
                  "Einen eigenen Agent-Benutzer ohne sudo und ohne Docker-Gruppe anlegen. Push auf geschützte Branches verhindert GitLab (Protected Branches), nicht tinyops.")
        else:
            r.add("rights", "Rechte", "ok", "Benutzer %s: kein root, kein sudo ohne Passwort, kein Docker-Socket" % facts["user"])
    return r.result(cloud=bool(agents.KINDS[kind]["provider"] and kind != "custom"))


def test_github(form, stored):
    """Prüft GitHub (nur lesend): Adresse, Verbindung, Anmeldung, Anfragelimit und Zugriff auf die gewählten Repos.
    form: api_url, ca_bundle, secret/token, repos [{full}]."""
    r = Report()
    base, ok = _check_url(r, form.get("api_url") or github.API_DEFAULT, "api.github")
    steps = (("auth", "Anmeldung"), ("rate", "Anfragelimit"), ("repos", "Repos"))
    if not ok:
        return r.result()
    ctx = _check_connection(r, base, form.get("ca_bundle"))
    if ctx is None:
        for sid, t in steps:
            r.skip(sid, t)
        return r.result()
    tok, src = _token(form, stored, "github_token")
    if not tok:
        r.add("auth", "Anmeldung", "fail", "Kein Token eingegeben oder gespeichert.",
              "Auf GitHub unter Settings → Developer settings → Fine-grained tokens anlegen: nur Lesen (Metadata, Contents, Pull requests, Commit statuses, Checks).")
        for sid, t in steps[1:]:
            r.skip(sid, t)
        return r.result()
    store.register(tok)
    hdr = github.headers(tok)
    try:
        resp = _get(base, "/user", hdr, ctx)
    except net.NetError as e:
        r.add("auth", "Anmeldung", "fail", e.detail)
        return r.result()
    data = net.parse_json(resp)
    if resp["status"] == 200 and isinstance(data, dict) and data.get("login"):
        scopes = resp["headers"].get("x-oauth-scopes")
        note = ""
        if scopes is not None:
            note = " · klassischer Token, Scopes: %s" % (scopes or "keine")
            if any(x.strip() in ("repo", "admin:org", "delete_repo", "workflow") for x in scopes.split(",")):
                r.add("auth", "Anmeldung", "warn", "angemeldet als %s (%s)%s" % (data["login"], src, note),
                      "Der Token darf mehr als lesen. tinyops liest nur; ein feingranularer Token mit Leserechten ist sicherer.")
            else:
                r.add("auth", "Anmeldung", "ok", "angemeldet als %s (%s)%s" % (data["login"], src, note))
        else:
            r.add("auth", "Anmeldung", "ok", "angemeldet als %s (%s, feingranularer Token)" % (data["login"], src))
    else:
        r.add("auth", "Anmeldung", "fail", "HTTP %d: %s" % (resp["status"], _msg(resp)),
              "Token falsch oder abgelaufen? Bei GitHub Enterprise: API-Adresse https://host/api/v3.")
        for sid, t in steps[1:]:
            r.skip(sid, t)
        return r.result()
    left, limit = resp["headers"].get("x-ratelimit-remaining"), resp["headers"].get("x-ratelimit-limit")
    if left is not None:
        r.add("rate", "Anfragelimit", "ok" if int(left) > 200 else "warn", "%s von %s Anfragen in dieser Stunde frei" % (left, limit),
              "" if int(left) > 200 else "Knapp. Ein Abgleich braucht je Repo und PR einige Anfragen.")
    else:
        r.add("rate", "Anfragelimit", "ok", "keine Angabe (Enterprise ohne Limit?)")
    repos = [x.get("full") for x in (form.get("repos") or []) if x.get("full")]
    if not repos:
        r.add("repos", "Repos", "warn", "Noch kein Repo gewählt.", "Unten suchen und hinzufügen.")
        return r.result(user=data["login"])
    bad, okn, ids = [], 0, {}
    for full in repos[:30]:
        try:
            rr = _get(base, "/repos/%s" % full, hdr, ctx)
        except net.NetError as e:
            bad.append("%s (%s)" % (full, e.detail))
            continue
        jd = net.parse_json(rr) or {}
        if rr["status"] == 200:
            okn += 1
            ids[full] = jd.get("id")
        else:
            bad.append("%s (HTTP %d)" % (full, rr["status"]))
    if bad:
        r.add("repos", "Repos", "fail", "%d lesbar, nicht lesbar: %s" % (okn, ", ".join(bad)),
              "Feingranularer Token: das Repo unter «Repository access» freigeben. 404 heisst bei GitHub oft «kein Zugriff».")
    else:
        r.add("repos", "Repos", "ok", "alle %d lesbar" % okn)
    return r.result(user=data["login"], ids=ids)


def search_github(form, stored):
    tok, _src = _token(form, stored, "github_token")
    if not tok:
        return {"error": "Kein GitHub-Token. Erst eingeben (oder speichern) und testen.", "items": []}
    try:
        ctx = net.make_ssl_ca((form.get("ca_bundle") or "").strip())
        c = github.Client(form.get("api_url") or github.API_DEFAULT, tok, ctx, timeout=10)
        return {"items": c.search_repos(form.get("q"))}
    except (github.GitHubError, ValueError) as e:
        return {"error": str(e), "items": []}


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
        resp = _get(base, "/rest/api/2/serverInfo", {"Accept": "application/json"}, ctx)
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
        resp = _get(base, "/rest/api/2/myself", hdr, ctx)
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
            resp = _get(base, "/rest/api/2/search", hdr, ctx, {"jql": jql, "fields": "summary,status,priority", "maxResults": 5})
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


# ------------------------------------------------------------ Lesen und Speichern
def _lst(v, what, errors, limit=60, upper=False):
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


def _int(v, what, lo, hi, errors, default):
    if v in (None, ""):
        return default
    try:
        n = int(v)
    except (TypeError, ValueError):
        errors[what] = "Bitte eine ganze Zahl."
        return default
    if not lo <= n <= hi:
        errors[what] = "Erlaubt: %d bis %d." % (lo, hi)
        return default
    return n


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
                      "repo_path": p.get("repo_path", "")}
                     for p in cfg.get("projects", [])],
        "connections": [dict(c) for c in cfg.get("connections") or []],
        "github": {"enabled": bool((cfg.get("github") or {}).get("enabled", False)), "api_url": (cfg.get("github") or {}).get("api_url") or github.API_DEFAULT,
                   "repos": [dict(r, data_class=agents.data_class(r), cloud_paths=list(r.get("cloud_paths") or []))
                             for r in (cfg.get("github") or {}).get("repos") or []]},
        "agents": [{k: v for k, v in a.items() if k != "command"} | {"has_command": bool(a.get("command"))} for a in cfg.get("agents") or []],
        "agent_log_days": int(cfg.get("agent_log_days", 30)),
        "ux": dict({"enabled": True, "days": 30}, **(cfg.get("ux") or {})),
        "ide_command": cfg.get("ide_command") or "idea {path}",
        "time": dict(timesheet.DEFAULTS, **(cfg.get("time") or {})),
        "helpdesk": helpdesk.cfg(cfg),
        "focus": _focus_view(cfg),
        "agent_kinds": [{"id": k, "label": v["label"], "provider": v["provider"], "local": bool(v.get("local"))} for k, v in agents.KINDS.items()],
        "data_classes": [{"id": c, "label": agents.CLASS_LABEL[c]} for c in agents.CLASSES],
        "branch_filter": {
            "emails": sorted(set(bf.get("emails", [])) | set(cfg.get("my_emails", []))), "names": bf.get("names", []),
            "agent_emails": bf.get("agent_emails", []), "agent_names": bf.get("agent_names", []),
            "agent_message_patterns": bf.get("agent_message_patterns", ["Co-Authored-By: Claude"]),
            "max_branches": bf.get("max_branches", 40), "max_age_days": bf.get("max_age_days", 90),
            "ignore_branches": bf.get("ignore_branches", ["release/*"])},
        "jira": {"url": jc.get("url", ""), "auth": jc.get("auth", "bearer"), "username": jc.get("username", ""),
                 "project_keys": jc.get("project_keys", []), "story_limit": jc.get("story_limit", 2),
                 "wip_issue_types": jc.get("wip_issue_types", ["Story"]), "jql_in_progress": jc.get("jql_in_progress") or JQL_DEFAULT,
                 "only_active_sprints": bool(jc.get("only_active_sprints", True)),
                 "allow_create": bool(jc.get("allow_create", False)), "create_type": jc.get("create_type", "Story")},
        "llm": {"enabled": bool((cfg.get("llm") or {}).get("enabled", False)), "provider": (cfg.get("llm") or {}).get("provider", "ollama"),
                "url": (cfg.get("llm") or {}).get("url", "http://127.0.0.1:11434"), "model": (cfg.get("llm") or {}).get("model", ""),
                "allow_remote": bool((cfg.get("llm") or {}).get("allow_remote", False)),
                "timeout": (cfg.get("llm") or {}).get("timeout", 120),
                "providers": [{"id": k, "label": v.label, "url": v.default_url} for k, v in llm.PROVIDERS.items()]},
        "usage": {"claude": bool((cfg.get("usage") or {}).get("claude")), "codex": bool((cfg.get("usage") or {}).get("codex")),
                  "mistral": bool((cfg.get("usage") or {}).get("mistral")), "bookmarklet_src": usage.BOOKMARKLET_JS,
                  "claude_file": (cfg.get("usage") or {}).get("claude_file", ""), "codex_file": (cfg.get("usage") or {}).get("codex_file", ""),
                  "cache_seconds": (cfg.get("usage") or {}).get("cache_seconds", 300)},
        "sonar": {"enabled": bool((cfg.get("sonar") or {}).get("enabled", False)), "url": (cfg.get("sonar") or {}).get("url", ""),
                  "cache_seconds": (cfg.get("sonar") or {}).get("cache_seconds", 300), "max_items": (cfg.get("sonar") or {}).get("max_items", 40),
                  "report_max": (cfg.get("sonar") or {}).get("report_max", 200)},
        "features": {k: bool(feats.get(k, False)) for k in CONFIG_KEYS_FEATURES},
        "secrets": {n: secret_state(cfg, n, [cfg.get("token_env")] if n == "gitlab_token" else ()) for n in SECRET_FIELDS},
        "storage": {"keyring": bool(kr), "file": str(store.secrets_file()),
                    "text": "Schlüsselbund des Betriebssystems" if kr else
                            "Datei %s (Klartext, nur für deinen Benutzer lesbar)" % store.secrets_file()},
        "server": {"config": str(config_path), "log": str(tlog.log_file(cfg)), "bind": cfg.get("bind"), "port": cfg.get("port")},
        "jql_default": JQL_DEFAULT,
    }


def _focus_view(cfg):
    f = focusplan.cfg(cfg)
    return {"week_hours": f["week_hours"], "day_start": f["day_start"], "day_end": f["day_end"],
            "areas": [dict(a, blocks_text=focusplan.blocks_text(a.get("blocks"))) for a in f["areas"]]}


def _clean_focus(p, errors):
    f = dict(focusplan.DEFAULTS)
    f["week_hours"] = _int(p.get("week_hours"), "focus.week_hours", 1, 80, errors, focusplan.DEFAULTS["week_hours"])
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
    bf["max_branches"] = _int(b.get("max_branches"), "branch_filter.max_branches", 1, 200, errors, 40)
    bf["max_age_days"] = _int(b.get("max_age_days"), "branch_filter.max_age_days", 0, 3650, errors, 90)
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
        jc["story_limit"] = _int(j.get("story_limit"), "jira.story_limit", 1, 20, errors, 2)
        jc["wip_issue_types"] = _lst(j.get("wip_issue_types"), "jira.wip_issue_types", errors)
        jc["only_active_sprints"] = bool(j.get("only_active_sprints", True))
        jc["allow_create"] = bool(j.get("allow_create", False))
        jc["create_type"] = (j.get("create_type") or "Story").strip()[:60] or "Story"
        jql = (j.get("jql_in_progress") or "").strip() or JQL_DEFAULT
        if len(jql) > 2000:
            errors["jira.jql_in_progress"] = "Zu lang."
        jc["jql_in_progress"] = jql
        jc.pop("helpdesk", None)
        cfg["jira"] = jc

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
        lc["timeout"] = _int(m.get("timeout"), "llm.timeout", 10, 900, errors, 120)
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
        uc["cache_seconds"] = _int(us.get("cache_seconds"), "usage.cache_seconds", 30, 3600, errors, 300)
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
        sc["cache_seconds"] = _int(sq.get("cache_seconds"), "sonar.cache_seconds", 30, 3600, errors, 300)
        sc["max_items"] = _int(sq.get("max_items"), "sonar.max_items", 1, 200, errors, 40)
        sc["report_max"] = _int(sq.get("report_max"), "sonar.report_max", 10, 1000, errors, 200)
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
        tc["send_on_confirm"] = bool(t.get("send_on_confirm", tc["send_on_confirm"]))
        tc["allow_remote"] = bool(t.get("allow_remote", tc["allow_remote"]))
        for k, lo, hi in (("round_minutes", 1, 60), ("min_minutes", 0, 60), ("idle_minutes", 3, 240)):
            if k in t:
                try:
                    v = int(t[k])
                    if not lo <= v <= hi:
                        raise ValueError
                    tc[k] = v
                except (TypeError, ValueError):
                    errors["time." + k] = "Ganze Zahl von %d bis %d." % (lo, hi)
        url = str(t.get("mcp_url", tc["mcp_url"]) or "").strip()
        if url:
            u = urllib.parse.urlparse(url)
            if u.scheme not in ("http", "https") or not u.hostname:
                errors["time.mcp_url"] = "Erwartet eine Adresse wie http://127.0.0.1:3100/time-entries."
            elif not tc["allow_remote"] and not llm.is_local(url):
                errors["time.mcp_url"] = "«%s» liegt nicht im eigenen Netz. Nur mit «Externe Adresse erlauben»." % u.hostname
        tc["mcp_url"] = url
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
        hc["sla_hours"] = _int(h.get("sla_hours"), "helpdesk.sla_hours", 1, 720, errors, hc["sla_hours"])
        hc["area"] = re.sub(r"[^a-z0-9_-]", "", str(h.get("area", hc["area"]) or "hd").lower())[:20] or "hd"
        cfg["helpdesk"] = hc
    if isinstance(p.get("focus"), dict):
        cfg["focus"] = _clean_focus(p["focus"], errors)
    if isinstance(p.get("ux"), dict):
        u = dict({"enabled": True, "days": 30}, **(cfg.get("ux") or {}))
        u["enabled"] = bool(p["ux"].get("enabled", u["enabled"]))
        try:
            d = int(p["ux"].get("days", u["days"]))
            if not 1 <= d <= 365:
                raise ValueError
            u["days"] = d
        except (TypeError, ValueError):
            errors["ux.days"] = "Ganze Zahl von 1 bis 365."
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
    if "agent_log_days" in p:
        try:
            d = int(p.get("agent_log_days"))
            if not 0 <= d <= 3650:
                raise ValueError
            cfg["agent_log_days"] = d
        except (TypeError, ValueError):
            errors["agent_log_days"] = "Ganze Zahl von 0 bis 3650 (0 = nie löschen)."
    if "connections" in p or "agents" in p:
        conns = agents.clean_connections(p.get("connections") if "connections" in p else cfg.get("connections"), errors)
        cfg["connections"] = conns
        cfg["agents"] = agents.clean_agents(p.get("agents") if "agents" in p else cfg.get("agents"), {c["id"] for c in conns}, current.get("agents"), errors)

    f = p.get("features") or {}
    cfg["features"] = {k: bool(f.get(k, False)) for k in CONFIG_KEYS_FEATURES}
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
