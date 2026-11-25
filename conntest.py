"""Verbindungstests der Einstellungen (0.45 aus settings.py gelöst): GitLab, Jira, Helpdesk, Sonar, GitHub, lokales Modell,
Spracherkennung und Agenten, mit verständlichen Fehlern.

Die Tests laufen Schritt für Schritt (Adresse, Namensauflösung, Verbindung, Zertifikat, API, Anmeldung, Rechte, ...)
und zeigen pro Schritt, was geklappt hat und woran es hängt. Ein Fehler stoppt die folgenden Schritte, weil sie
darauf aufbauen. Secrets werden nie zurückgegeben. Jeder Aufruf geht über `net` und steht in `apicalls.CALLS`.
"""
import json
import urllib.parse

import agents
import github
import llm
import net
import secretstore as store
import sonar
import voice
from settings_schema import int_ as _int

_cool = {}   # (Jira-Adresse, Benutzer) → Zeitpunkt, bis zu dem nach einem Fehlversuch nicht erneut getestet wird
COOLDOWN_S = 30
JQL_DEFAULT = 'assignee = currentUser() AND statusCategory = "In Progress" ORDER BY updated DESC'


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


def _svc(path):
    return "GitLab" if path.startswith("/api/v4") else "Jira" if path.startswith("/rest/api/2") else "Sonar" if path.startswith("/api/") else "GitHub"


def _get(base, path, headers, ctx, params=None, timeout=10, svc=None):
    url = base + path + (("?" + urllib.parse.urlencode(params)) if params else "")
    return net.probe(url, headers, ctx, timeout=timeout, svc=svc or _svc(path))


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


def test_voice(form, stored):
    """0.43: Spracherkennung im eigenen Netz: Adresse, eine Sekunde Stille erkennen lassen."""
    key = (form.get("secret") or "").strip() or (stored("voice_key")[0] or "")
    if key:
        store.register(key)
    r = Report()
    for status, title, detail, hint in voice.test(form, key):
        r.add(title.lower(), title, status, detail, hint)
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
        resp = net.probe(base + "/api/authentication/validate", hdr, ctx, timeout=10, svc="Sonar")
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
            resp = net.probe(base + "/api/components/show?" + urllib.parse.urlencode({"component": key}), hdr, ctx, timeout=10, svc="Sonar")
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
