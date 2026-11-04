"""Einstellungen: Verbindungstests für GitLab und Jira mit verständlichen Fehlern, Speichern von Config und Secrets.

Die Tests laufen Schritt für Schritt (Adresse, Namensauflösung, Verbindung, Zertifikat, API, Anmeldung, Rechte, ...)
und zeigen pro Schritt, was geklappt hat und woran es hängt. Ein Fehler stoppt die folgenden Schritte, weil sie
darauf aufbauen. Secrets werden nie zurückgegeben, nur ob und wo sie gespeichert sind.
"""
import json
import os
import re
import tempfile
import time
import urllib.parse
from pathlib import Path

import llm
import net
import secretstore as store
import sonar
import sprint
import tlog

log = tlog.get("settings")

_cool = {}   # (Jira-Adresse, Benutzer) → Zeitpunkt, bis zu dem nach einem Fehlversuch nicht erneut getestet wird
COOLDOWN_S = 30
JQL_DEFAULT = 'assignee = currentUser() AND statusCategory = "In Progress" ORDER BY updated DESC'
SECRET_FIELDS = ("gitlab_token", "jira_token", "jira_password", "llm_key", "sonar_token")
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
    return r.result(user={"username": me.get("username"), "name": me.get("name"), "email": me.get("email")} if me else None)


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
def _jira_headers(form, stored):
    auth = form.get("auth") or "bearer"
    name = "jira_token" if auth == "bearer" else "jira_password"
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


def test_sonar(form, stored):
    """Prüft SonarQube (nur lesend): Adresse, Verbindung, Anmeldung, Version und die Projektschlüssel der GitLab-Projekte.
    form: url, ca_bundle, secret/token, projects [{id, name, sonar_key}]."""
    r = Report()
    base, ok = _check_url(r, form.get("url"), "sonar")
    steps = (("api", "Sonar-API"), ("auth", "Anmeldung"), ("keys", "Projektschlüssel"))
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
    return r.result()


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
        "projects": [{"id": p["id"], "name": p.get("name", str(p["id"])), "sonar_key": p.get("sonar_key", "")} for p in cfg.get("projects", [])],
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
                  "claude_file": (cfg.get("usage") or {}).get("claude_file", ""), "codex_file": (cfg.get("usage") or {}).get("codex_file", ""),
                  "cache_seconds": (cfg.get("usage") or {}).get("cache_seconds", 120)},
        "sonar": {"enabled": bool((cfg.get("sonar") or {}).get("enabled", False)), "url": (cfg.get("sonar") or {}).get("url", ""),
                  "cache_seconds": (cfg.get("sonar") or {}).get("cache_seconds", 300), "max_items": (cfg.get("sonar") or {}).get("max_items", 40)},
        "features": {k: bool(feats.get(k, False)) for k in CONFIG_KEYS_FEATURES},
        "secrets": {n: secret_state(cfg, n, [cfg.get("token_env")] if n == "gitlab_token" else ()) for n in SECRET_FIELDS},
        "storage": {"keyring": bool(kr), "file": str(store.secrets_file()),
                    "text": "Schlüsselbund des Betriebssystems" if kr else
                            "Datei %s (Klartext, nur für deinen Benutzer lesbar)" % store.secrets_file()},
        "server": {"config": str(config_path), "log": str(tlog.log_file(cfg)), "bind": cfg.get("bind"), "port": cfg.get("port")},
        "jql_default": JQL_DEFAULT,
    }


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
        for k in ("claude", "codex"):
            uc[k] = bool(us.get(k, False))
            f = str(us.get(k + "_file") or "").strip()
            if len(f) > 300 or "\x00" in f:
                errors["usage.%s_file" % k] = "Ungültiger Pfad."
            uc[k + "_file"] = f
        uc["cache_seconds"] = _int(us.get("cache_seconds"), "usage.cache_seconds", 30, 3600, errors, 120)
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
        cfg["sonar"] = sc

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
