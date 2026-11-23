"""HTTP-Schicht von tinyops (0.37 aus server.py gelöst): Zugang (Host, Token, gekoppelte Geräte), Routen, Antworten."""
import hashlib
import hmac
import json
import re
import time
import urllib.parse
from html import escape as html_escape
from http.server import BaseHTTPRequestHandler

import devices
import qr
import ui
import secretstore as store
import settings
import timesheet
import tlog
from common import UserError, _stored
from secretstore import scrub

log = tlog.get("app")
hlog = tlog.get("http")
alog = tlog.get("access")


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


PUBLIC_GET = ("/manifest.webmanifest", "/sw.js", "/pair", "/icon.svg", "/icon-192.png", "/icon-512.png", "/icon-maskable.png")


# ---------------------------------------------------------------- Routen
class Resp:
    """Antwort, die nicht einfach JSON mit 200 ist (Seite, Datei, anderer Status)."""
    __slots__ = ("code", "body", "ctype", "headers")

    def __init__(self, code, body, ctype="application/json", headers=None):
        self.code, self.body, self.ctype, self.headers = code, body, ctype, headers


class Req:
    """Was eine Route von der Anfrage braucht: Körper (JSON) und Parameter."""

    def __init__(self, handler, method, path, query):
        self._h, self.method, self.path = handler, method, path
        self.query = urllib.parse.parse_qs(query or "")
        self.raw_query = query or ""

    def body(self):
        return self._h._body()

    def q(self, k, d=""):
        return (self.query.get(k) or [d])[0]


SETTINGS_TESTS = {"gitlab": ("GitLab", settings.test_gitlab), "jira": ("Jira", settings.test_jira), "helpdesk": ("Helpdesk", settings.test_helpdesk),
                  "sonar": ("Sonar", settings.test_sonar), "github": ("GitHub", settings.test_github), "agent": ("Agent", settings.test_agent),
                  "llm": ("KI", settings.test_llm)}


def _m365_callback(app, cfg, r):          # Rückleitung von Microsoft: einfache Seite, dann zurück ins Panel
    ok, msg = app.m365_callback(r.query)
    page = ('<!doctype html><meta charset="utf-8"><title>tinyops</title><body style="font:16px system-ui;padding:40px">'
            '<p>%s</p><p><a href="/#settings">Zurück zu tinyops</a></p><script>setTimeout(()=>location.replace("/#settings"),%d)</script>'
            % (html_escape(msg), 800 if ok else 8000))
    return Resp(200 if ok else 400, page.encode("utf-8"), "text/html")


def _audit_rows(app, cfg, r):
    return {"rows": app.audit_log.rows(target=r.query.get("target") or None, action=r.q("action") or None,
                                       limit=max(1, min(int(r.q("limit") or 200), 2000))),
            "instance": app.audit_log.instance()}


def _audit_export(app, cfg, r):
    body = json.dumps({"exported": time.time(), "instance": app.audit_log.instance(), "verify": app.audit_log.verify(),
                       "rows": app.audit_log.export()}, ensure_ascii=False, indent=1).encode("utf-8")
    return Resp(200, body, "application/json", {"Content-Disposition": 'attachment; filename="tinyops-audit-%s.json"' % time.strftime("%Y%m%d-%H%M")})


def _refresh(app, cfg, r):
    with app.cache_lock:
        app.cache_t = 0.0
    return {"started": app.start_sync(), "sync": app.sync_view()}


def _usage(app, cfg, r):
    v = app.usage_view(fresh="fresh=1" in r.raw_query)
    return {k: v[k] for k in ("enabled", "items", "fetched")}


def _overview(app, cfg, r):
    data = app.overview(wait=False)
    data["ideas"] = app.ideas.list() if app.has("ideas") and app.ideas else []
    data["idea_cap"] = cfg["idea_cap"]
    return data


def _log(app, cfg, r):
    return {"file": str(tlog.log_file(cfg)), "level": cfg["log_level"], "lines": tlog.tail(cfg, int(r.q("n", "200")), r.q("level", "debug"))}


def _idea_add(app, cfg, r):
    app.ideas.add(r.body().get("text"))
    return {"ok": True}


def _prompt(app, cfg, r):
    b = r.body()
    return {"prompt": app.render_prompt(b.get("name"), int(b["project_id"]), int(b["iid"]))}


# Genaue Pfade: (Methode, Pfad) → Funktion(app, cfg, req)
EXACT = {
    ("POST", "/api/links"): lambda app, cfg, r: app.link_ticket(r.body()),
    ("POST", "/api/links/delete"): lambda app, cfg, r: app.unlink_ticket(r.body()),
    ("POST", "/api/ide/open"): lambda app, cfg, r: app.ide_open(r.body()),
    ("POST", "/api/ide/close"): lambda app, cfg, r: app.ide_close(r.body()),
    ("GET", "/api/m365/callback"): _m365_callback,
    ("POST", "/api/groups"): lambda app, cfg, r: app.group_action(r.body()),
    ("GET", "/api/bcs/day"): lambda app, cfg, r: app.bcs_day(r.q("date") or timesheet.today()),
    ("GET", "/api/m365"): lambda app, cfg, r: app.m365_state() or {"enabled": False},
    ("GET", "/api/workspaces"): lambda app, cfg, r: app.workspaces_state("fresh=1" in r.raw_query),
    ("GET", "/api/focus/brief"): lambda app, cfg, r: app.focus_brief(r.q("key"), r.q("title")),     # 0.36: Ziel und Kriterien der Fokus-Aufgabe
    ("GET", "/api/helpdesk/ticket"): lambda app, cfg, r: app.helpdesk_ticket(r.q("key")),
    ("POST", "/api/helpdesk/seen"): lambda app, cfg, r: app.helpdesk_seen(r.body()),
    ("POST", "/api/ux/events"): lambda app, cfg, r: app.ux_events(r.body()),
    ("GET", "/api/ux/report"): lambda app, cfg, r: app.ux_report(r.q("days") or 7),
    ("POST", "/api/ux/wish"): lambda app, cfg, r: app.ux_wish(r.body()),
    ("POST", "/api/ux/clear"): lambda app, cfg, r: app.ux_clear(),
    ("POST", "/api/update/seen"): lambda app, cfg, r: app.update_seen(),
    ("GET", "/api/update/check"): lambda app, cfg, r: app.update_check(force=r.q("force") == "1"),
    ("POST", "/api/update/run"): lambda app, cfg, r: app.update_run(),
    ("POST", "/api/update/service"): lambda app, cfg, r: app.update_service(r.body()),
    ("GET", "/api/update/news"): lambda app, cfg, r: app.update_news(),
    ("GET", "/api/qa"): lambda app, cfg, r: app.qa_view(),
    ("GET", "/api/time/day"): lambda app, cfg, r: app.time_day(r.q("date") or None),
    ("POST", "/api/review/topics"): lambda app, cfg, r: app.review_topics(r.body()),
    ("POST", "/api/review/export"): lambda app, cfg, r: app.review_export(r.body()),
    ("GET", "/api/audit"): _audit_rows,
    ("GET", "/api/audit/verify"): lambda app, cfg, r: app.audit_log.verify(),
    ("GET", "/api/audit/export"): _audit_export,
    ("POST", "/api/ticket/draft"): lambda app, cfg, r: app.ticket_draft(r.body()),
    ("POST", "/api/ticket/create"): lambda app, cfg, r: app.ticket_create(r.body()),
    ("POST", "/api/refresh"): _refresh,
    ("GET", "/api/sonar/report"): lambda app, cfg, r: app.sonar_report(int(r.q("project_id")), r.q("iid") or None, r.q("branch") or None),
    ("POST", "/api/usage/push"): lambda app, cfg, r: app.usage_push(r.body()),
    ("GET", "/api/usage"): _usage,
    ("GET", "/api/overview"): _overview,
    ("GET", "/api/log"): _log,
    ("POST", "/api/ideas"): _idea_add,
    ("GET", "/api/ideas/triage-prompt"): lambda app, cfg, r: {"prompt": app.triage_prompt()},
    ("POST", "/api/prompt"): _prompt,
    ("POST", "/api/mr/env"): lambda app, cfg, r: app.mr_env(r.body()),          # 0.34: Review-Umgebung für einen MR
}

# Aktionen unter einem Präfix: die Aktion ist der letzte Pfadteil. «/api/pools» allein heisst «create».
PREFIX = [
    ("POST", "/api/pools", lambda app, cfg, r, a: app.pool_action(a, r.body())),
    ("POST", "/api/board/", lambda app, cfg, r, a: app.board_action(a, r.body())),
    ("POST", "/api/bcs/", lambda app, cfg, r, a: app.bcs_action(a, r.body())),
    ("POST", "/api/m365/", lambda app, cfg, r, a: app.m365_action(a, r.body())),
    ("POST", "/api/focus/", lambda app, cfg, r, a: app.focus_action(a, r.body())),
    ("POST", "/api/workspaces/", lambda app, cfg, r, a: app.workspaces_action(a, r.body())),
    ("POST", "/api/qa/", lambda app, cfg, r, a: app.qa_action(a, r.body())),
    ("POST", "/api/time/", lambda app, cfg, r, a: app.time_action(a, r.body())),
    ("POST", "/api/flow/", lambda app, cfg, r, a: app.flow_action(a, r.body())),
    ("POST", "/api/agents/", lambda app, cfg, r, a: app.agent_action(a, r.body())),
    ("POST", "/api/ai/", lambda app, cfg, r, a: app.ai_action(a, r.body())),
]


def _idea_patch(app, cfg, r, m):
    app.ideas.set_status(int(m.group(1)), r.body().get("status"))
    return {"ok": True}


def _idea_delete(app, cfg, r, m):
    app.ideas.delete(int(m.group(1)))
    return {"ok": True}


def _idea_run(app, cfg, r, m):
    fn = app.idea_assess if m.group(2) == "assess" else app.idea_tiny
    return fn(int(m.group(1)), r.body())


PATTERNS = [
    ("PATCH", re.compile(r"/api/ideas/(\d+)"), _idea_patch),
    ("DELETE", re.compile(r"/api/ideas/(\d+)"), _idea_delete),
    ("POST", re.compile(r"/api/ideas/(\d+)/(assess|tiny)"), _idea_run),
]


def find_route(method, path):
    """(funktion, argument) oder (None, None). Genaue Pfade zuerst, dann Präfixe, dann Muster."""
    fn = EXACT.get((method, path))
    if fn:
        return fn, None
    for m, prefix, fn in PREFIX:
        if m == method and path.startswith(prefix):
            return fn, ("create" if path == prefix and not prefix.endswith("/") else path.rsplit("/", 1)[1])
    for m, rx, fn in PATTERNS:
        hit = rx.fullmatch(path)
        if m == method and hit:
            return fn, hit
    return None, None


def make_handler(app, base, version, load_config):
    """Baut die Handler-Klasse für eine App. base, version und load_config kommen aus server.py (dort bleibt die Config)."""
    BASE, VERSION = base, version
    cfg = _Cfg(app)
    html = ui.page(BASE).encode("utf-8")   # 0.39: aus index.html, app.css und static/js zusammengesetzt
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
            self.send_header("Content-Type", ctype + ("; charset=utf-8" if ctype.startswith(("text/", "application/")) else ""))
            self.send_header("Content-Length", str(len(body)))
            if "Cache-Control" not in (extra or {}):
                self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Content-Security-Policy", "default-src 'self'; style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'")
            for k, v in dict(self._cors(), **(extra or {})).items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(body)

        def _cors(self):
            return devices.cors_headers(self.headers.get("Origin", ""), devices.app_origins((cfg.get("app") or {}).get("origins") or [])[0])

        def _err(self, code, msg):
            self._send(code, {"error": scrub(msg)})

        # -- Schutz: Host-Header (DNS-Rebinding), Zugriffstoken, Custom-Header
        def _gate(self, parsed):
            host = (self.headers.get("Host") or "").lower()
            host = host.rsplit(":", 1)[0] if not host.endswith("]") else host
            phone_host = devices.phone_url((cfg.get("app") or {}).get("phone_url"))[1]
            allowed = {"localhost", "127.0.0.1", "[::1]"} | {h.lower() for h in cfg["allowed_hosts"]} | ({phone_host} if phone_host else set())
            if host not in allowed:
                alog.warning("Abgelehnt: Host %r von %s nicht in allowed_hosts", host, self.client_address[0])
                self._err(403, "Host nicht erlaubt (allowed_hosts in der config.json).")
                return None
            self._remote = devices.is_remote(self.client_address[0], self.headers.get("Host"), self.headers)
            self._dev = None
            self._public = False
            if (self.command == "GET" and parsed.path in PUBLIC_GET) or (self.command == "POST" and parsed.path == "/api/pair/claim"):
                self._public = True             # 0.36: App-Hülle und Koppeln brauchen kein Login (verraten nichts)
                if self.command != "GET" and self.headers.get("X-Requested-With") != "tinyops":
                    self._err(403, "Header X-Requested-With fehlt.")
                    return None
                return {}
            self._dev = app.devices.check(self.headers.get("Cookie", ""), self.headers.get("Authorization", ""))
            if self._dev is None and self._remote and not token:
                # 0.36: von woanders (Handy, Proxy, anderer Host-Name) nur mit gekoppeltem Gerät
                alog.warning("Abgelehnt: %s %s von %s ohne gekoppeltes Gerät", self.command, parsed.path, self.client_address[0])
                if self.command == "GET" and parsed.path == "/":
                    self._send(401, devices.NOT_PAIRED_PAGE.encode("utf-8"), "text/html")
                else:
                    self._err(401, "Dieses Gerät ist nicht gekoppelt. Am Rechner: Einstellungen → App und Handy.")
                return None
            if token and self._dev is None:
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

        def _public_get(self, path):
            if path == "/manifest.webmanifest":
                return self._send(200, json.dumps(devices.MANIFEST, ensure_ascii=False).encode("utf-8"), "application/manifest+json")
            if path == "/sw.js":
                return self._send(200, (devices.SERVICE_WORKER % VERSION).encode("utf-8"), "text/javascript")
            if path == "/pair":
                return self._send(200, devices.PAIR_PAGE.encode("utf-8"), "text/html")
            f = BASE / "static" / path.lstrip("/")
            ctype = "image/svg+xml" if path.endswith(".svg") else "image/png"
            return self._send(200, f.read_bytes(), ctype, {"Cache-Control": "max-age=86400"})

        def _pair_route(self, method, path):
            """Koppeln (0.36). Codes erzeugen und Geräte verwalten nur am Rechner selbst, nie von einem gekoppelten Gerät aus."""
            if method == "POST" and path == "/api/pair/claim":
                b = self._body()
                try:
                    val, dev = app.devices.claim(b.get("code"), b.get("name"), self.headers.get("User-Agent", ""))
                except devices.DeviceError as e:
                    app.audit("device.pair", "", ok=False, error=str(e), ip=self.client_address[0])
                    return self._err(400, str(e))
                app.audit("device.pair", dev["name"], device=dev["id"], ip=self.client_address[0], mode="token" if b.get("mode") == "token" else "cookie")
                if b.get("mode") == "token":            # eigene App (E9/E11): Token im Körper, die App schickt es als «Authorization: Bearer …»
                    return self._send(200, {"ok": True, "device": dev["name"], "token": val, "version": VERSION})
                secure = (self.headers.get("X-Forwarded-Proto") or "").lower() == "https" or (cfg.get("app") or {}).get("phone_url", "").startswith("https://")
                return self._send(200, {"ok": True, "device": dev["name"]}, extra={"Set-Cookie": devices.cookie(val, secure)})
            if self._dev is not None:
                return self._err(403, "Gekoppelte Geräte dürfen keine weiteren koppeln. Das geht nur am Rechner.")
            if method == "GET" and path == "/api/pair/devices":
                return self._send(200, {"devices": app.devices.list(), "phone_url": (cfg.get("app") or {}).get("phone_url", "")})
            if method == "POST" and path == "/api/pair/start":
                try:
                    out = app.devices.new_code()
                except devices.DeviceError as e:
                    return self._err(400, str(e))
                app.audit("device.code", "", expires=out["expires"])
                phone = (cfg.get("app") or {}).get("phone_url", "")
                # 0.39: QR-Code mit Adresse und Code (nach #, geht nicht übers Netz und landet in keinem Log)
                link = phone.rstrip("/") + "/pair#code=" + out["code"] if phone else ""
                return self._send(200, dict(out, phone_url=phone, link=link, qr=qr.svg(link) if link else ""))
            if method == "POST" and path == "/api/pair/revoke":
                b = self._body()
                try:
                    app.devices.revoke(b.get("id"))
                except (devices.DeviceError, TypeError, ValueError) as e:
                    return self._err(400, str(e) or "Welches Gerät?")
                app.audit("device.revoke", str(b.get("id")))
                return self._send(200, {"devices": app.devices.list()})
            return self._err(404, "Nicht gefunden.")

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
                if self._public and method == "GET":        # 0.36: App-Hülle (Manifest, Service Worker, Icons) und Koppel-Seite
                    return self._public_get(path)
                if path.startswith("/api/pair/"):
                    return self._pair_route(method, path)
                if self._dev is not None and method != "GET" and (path.startswith("/api/settings") or path.startswith("/api/m365/") or path in ("/api/update/run", "/api/update/service")):
                    return self._err(403, "Einstellungen ändern geht nur am Rechner, nicht vom gekoppelten Gerät.")
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
                         "")
                if needs and not app.has(needs):
                    return self._err(404, "Diese Funktion ist ausgeschaltet (Einstellungen → Weitere Funktionen).")
                r = Req(self, method, path, parsed.query)
                fn, arg = find_route(method, path)
                if fn is None:
                    return self._err(404, "Nicht gefunden.")
                out = fn(app, cfg, r, arg) if arg is not None else fn(app, cfg, r)
                if isinstance(out, Resp):
                    return self._send(out.code, out.body, out.ctype, out.headers)
                return self._send(200, out)
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
                                            demo=app.demo, problems=list(app.problems), configured=app.configured, hints=app.settings_hints()))
            if method != "POST":
                return self._err(404, "Nicht gefunden.")
            body = self._body()
            kind = path[len("/api/settings/test/"):] if path.startswith("/api/settings/test/") else ""
            if kind in SETTINGS_TESTS:
                label, fn = SETTINGS_TESTS[kind]
                res = fn(body, stored)
                hlog.info("Test %s: %s", label, "ok" if res["ok"] else "; ".join("%s: %s" % (x["title"], x["detail"]) for x in res["steps"] if x["status"] == "fail"))
                if kind == "llm":
                    for x in res["steps"]:
                        if x["status"] == "warn":
                            hlog.warning("Test KI, Warnung bei «%s»: %s", x["title"], x["detail"])
                return self._send(200, res)
            if path == "/api/settings/github/repos":
                return self._send(200, settings.search_github(body, stored))
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
                if changed or where:                           # 0.35: Speichern ohne Änderung steht nicht im Verlauf
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

        def do_OPTIONS(self):
            """CORS-Vorabfrage der eigenen App (0.36.2). Nur für eingetragene Adressen und nur für /api/."""
            h = self._cors()
            path = urllib.parse.urlparse(self.path).path
            self.send_response(204 if h and path.startswith("/api/") else 403)
            for k, v in (h if path.startswith("/api/") else {}).items():
                self.send_header(k, v)
            self.send_header("Content-Length", "0")
            self.end_headers()

    return Handler
