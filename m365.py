"""Microsoft 365 über Graph (0.28): Mail, Kalender und Teams-Chats lesen, auf Wunsch Fokuszeit im Kalender eintragen.

Anmeldung
* Delegiert, als du selbst: OAuth 2.0 mit PKCE im Browser (die 2FA macht Microsoft), Rückleitung auf http://localhost:<port>/api/m365/callback.
  Ersatzweise Gerätecode (Code auf microsoft.com/devicelogin eingeben). Kein Client-Secret: tinyops ist ein öffentlicher Client.
* Gespeichert wird nur das Refresh-Token (Schlüsselbund oder secrets.json). Das Access-Token liegt nur im Speicher.
* Rechte: User.Read, Mail.Read, Calendars.Read (oder Calendars.ReadWrite, wenn Eintragen erlaubt ist), Chat.Read, offline_access.

Lesen
* Mail: Posteingang der letzten Tage. «Wartet auf dich» = direkt an dich, nicht von dir, nicht automatisch, noch nicht beantwortet
  (Exchange merkt sich die letzte Aktion: PidTagLastVerbExecuted 0x1081) – plus alles mit Fähnchen.
* Kalender: heute und morgen, ohne abgesagte Termine.
* Teams: Chats, deren letzte Nachricht nach deinem letzten Lesen kam und nicht von dir ist.

Schreiben
* Nur ein Termin «Fokus: …» für eine Fokus-Sitzung, nur wenn eingeschaltet, nur auf deinen Haken, mit Eintrag im Protokoll.
"""
import base64
import hashlib
import json
import re
import secrets as _rnd
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

LOGIN = "https://login.microsoftonline.com"
GRAPH = "https://graph.microsoft.com/v1.0"
DEFAULTS = {"enabled": False, "tenant": "", "client_id": "", "mail": True, "calendar": True, "teams": True, "calendar_write": False,
            "reply_days": 3, "refresh_minutes": 5}
GUID_RE = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")
TENANT_RE = re.compile(r"^(?:[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}|[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+|organizations)$")
AUTO_FROM = re.compile(r"(?i)(?:no-?reply|do-?not-?reply|notification|mailer-daemon|postmaster|jira@|gitlab@|github\.com|noreply|automat|bounce)")
KEY_RE = re.compile(r"\b[A-Z][A-Z0-9_]{1,15}-\d{1,7}\b")
SECRET = "m365_refresh"
VERB_PROP = "Integer 0x1081"          # PidTagLastVerbExecuted: 102 Antwort, 103 Allen antworten, 104 Weitergeleitet


class GraphError(Exception):
    def __init__(self, msg, code=0):
        super().__init__(msg)
        self.code = code


def cfg(c):
    out = dict(DEFAULTS)
    out.update(c.get("m365") or {})
    return out


def scopes(conf):
    s = ["offline_access", "User.Read"]
    if conf.get("mail"):
        s.append("Mail.Read")
    if conf.get("calendar"):
        s.append("Calendars.ReadWrite" if conf.get("calendar_write") else "Calendars.Read")
    if conf.get("teams"):
        s.append("Chat.Read")
    return s


def _pkce():
    verifier = base64.urlsafe_b64encode(_rnd.token_bytes(48)).rstrip(b"=").decode()
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    return verifier, challenge


def _iso(dt):
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _ts(s):
    """Graph-Zeit (UTC, mit oder ohne Z, bis zu 7 Nachkommastellen) als Unix-Zeit."""
    if not s:
        return 0.0
    s = s.rstrip("Z")
    if "." in s:
        a, b = s.split(".", 1)
        s = a + "." + b[:6]
    try:
        return datetime.fromisoformat(s).replace(tzinfo=timezone.utc).timestamp()
    except ValueError:
        return 0.0


def _addr(x):
    e = (x or {}).get("emailAddress") or {}
    return (e.get("address") or "").lower(), e.get("name") or e.get("address") or ""


class Client:
    """Graph-Zugriff für einen Benutzer. login/graph sind für Tests austauschbar."""

    def __init__(self, conf, ctx=None, redirect="", store=None, login=LOGIN, graph=GRAPH):
        self.conf, self.ctx, self.redirect = conf, ctx, redirect
        self.login, self.graph = login.rstrip("/"), graph.rstrip("/")
        self.store = store                     # (get, set, delete) für das Refresh-Token
        self.lock = threading.RLock()
        self.access, self.access_exp = "", 0.0
        self.pending = {}                      # state -> (verifier, ts)
        self.device = None                     # laufender Gerätecode-Ablauf
        self.me = None
        self.last_error = ""

    # -- HTTP
    def _open(self, req, timeout=20):
        opener = urllib.request.build_opener(urllib.request.HTTPSHandler(context=self.ctx)) if self.ctx else urllib.request.build_opener()
        return opener.open(req, timeout=timeout)

    def _token_call(self, form):
        url = "%s/%s/oauth2/v2.0/token" % (self.login, urllib.parse.quote(self.conf["tenant"]))
        req = urllib.request.Request(url, data=urllib.parse.urlencode(form).encode(), method="POST",
                                     headers={"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"})
        try:
            with self._open(req) as r:
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            try:
                d = json.loads(e.read(8000).decode("utf-8"))
            except ValueError:
                d = {}
            raise GraphError(d.get("error") or "HTTP %s" % e.code, e.code) if d.get("error") in ("authorization_pending", "slow_down") else \
                GraphError(_explain(d.get("error"), d.get("error_description") or "HTTP %s" % e.code), e.code)
        except (urllib.error.URLError, OSError) as e:
            raise GraphError("Microsoft-Anmeldung nicht erreichbar: %s" % getattr(e, "reason", e))

    def _take(self, d):
        if not d.get("access_token"):
            raise GraphError("Microsoft hat kein Token geliefert.")
        with self.lock:
            self.access = d["access_token"]
            self.access_exp = time.time() + int(d.get("expires_in") or 3600) - 120
            if d.get("refresh_token") and self.store:
                self.store[1](d["refresh_token"])      # Refresh-Tokens wechseln bei jeder Nutzung: immer das neueste speichern
        self.last_error = ""

    # -- Anmeldung im Browser (PKCE)
    def auth_url(self):
        if not self.ready():
            raise GraphError("Tenant und Client-ID fehlen (Einstellungen → Microsoft 365).")
        verifier, challenge = _pkce()
        state = _rnd.token_urlsafe(24)
        with self.lock:
            now = time.time()
            self.pending = {k: v for k, v in self.pending.items() if now - v[1] < 600}
            self.pending[state] = (verifier, now)
        q = {"client_id": self.conf["client_id"], "response_type": "code", "redirect_uri": self.redirect, "response_mode": "query",
             "scope": " ".join(scopes(self.conf)), "state": state, "code_challenge": challenge, "code_challenge_method": "S256", "prompt": "select_account"}
        return "%s/%s/oauth2/v2.0/authorize?%s" % (self.login, urllib.parse.quote(self.conf["tenant"]), urllib.parse.urlencode(q))

    def callback(self, code, state):
        with self.lock:
            p = self.pending.pop(state or "", None)
        if not p or time.time() - p[1] > 600:
            raise GraphError("Die Anmeldung ist abgelaufen oder kam nicht von diesem tinyops. Bitte noch einmal «Anmelden».")
        self._take(self._token_call({"client_id": self.conf["client_id"], "grant_type": "authorization_code", "code": code,
                                     "redirect_uri": self.redirect, "code_verifier": p[0], "scope": " ".join(scopes(self.conf))}))
        self.me = None
        return self.whoami()

    # -- Anmeldung mit Gerätecode (falls die Rückleitung auf localhost nicht geht)
    def device_start(self):
        if not self.ready():
            raise GraphError("Tenant und Client-ID fehlen (Einstellungen → Microsoft 365).")
        url = "%s/%s/oauth2/v2.0/devicecode" % (self.login, urllib.parse.quote(self.conf["tenant"]))
        req = urllib.request.Request(url, data=urllib.parse.urlencode({"client_id": self.conf["client_id"], "scope": " ".join(scopes(self.conf))}).encode(),
                                     method="POST", headers={"Content-Type": "application/x-www-form-urlencoded"})
        try:
            with self._open(req) as r:
                d = json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            try:
                j = json.loads(e.read(8000).decode("utf-8"))
            except ValueError:
                j = {}
            raise GraphError(_explain(j.get("error"), j.get("error_description") or "HTTP %s" % e.code), e.code)
        except (urllib.error.URLError, OSError) as e:
            raise GraphError("Microsoft-Anmeldung nicht erreichbar: %s" % getattr(e, "reason", e))
        dev = {"user_code": d.get("user_code", ""), "uri": d.get("verification_uri", "https://microsoft.com/devicelogin"),
               "expires": time.time() + int(d.get("expires_in") or 900), "state": "wartet", "error": ""}
        with self.lock:
            self.device = dev
        threading.Thread(target=self._device_poll, args=(d.get("device_code", ""), int(d.get("interval", 5)), dev), name="tinyops-m365-device", daemon=True).start()
        return dict(dev)

    def _device_poll(self, code, interval, dev, sleep=time.sleep):
        while time.time() < dev["expires"] and dev["state"] == "wartet":
            sleep(interval)
            try:
                self._take(self._token_call({"client_id": self.conf["client_id"], "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
                                             "device_code": code}))
                self.me = None
                dev["state"] = "fertig"
                return
            except GraphError as e:
                if str(e) == "slow_down":
                    interval += 5
                elif str(e) != "authorization_pending":
                    dev.update(state="fehler", error=str(e))
                    return
        if dev["state"] == "wartet":
            dev.update(state="fehler", error="Der Code ist abgelaufen. Bitte neu anfordern.")

    def device_state(self):
        with self.lock:
            return dict(self.device) if self.device else None

    def logout(self):
        with self.lock:
            self.access, self.access_exp, self.me = "", 0.0, None
            if self.store:
                self.store[2]()

    # -- Token
    def ready(self):
        return bool(self.conf.get("enabled") and TENANT_RE.fullmatch(self.conf.get("tenant") or "") and GUID_RE.fullmatch(self.conf.get("client_id") or ""))

    def has_login(self):
        return bool(self.access and time.time() < self.access_exp) or bool(self.store and self.store[0]())

    def token(self):
        with self.lock:
            if self.access and time.time() < self.access_exp:
                return self.access
            rt = self.store[0]() if self.store else ""
            if not rt:
                raise GraphError("Nicht angemeldet. Einstellungen → Microsoft 365 → «Anmelden».", 401)
            try:
                self._take(self._token_call({"client_id": self.conf["client_id"], "grant_type": "refresh_token", "refresh_token": rt,
                                             "scope": " ".join(scopes(self.conf))}))
            except GraphError as e:
                if e.code in (400, 401):             # Refresh-Token abgelaufen oder widerrufen: neu anmelden
                    self.last_error = str(e)
                raise
            return self.access

    # -- Graph
    def get(self, path, params=None, headers=None):
        url = path if path.startswith("http") else self.graph + path
        if params:
            url += ("&" if "?" in url else "?") + urllib.parse.urlencode(params, safe="$,/:'()", quote_via=urllib.parse.quote)
        req = urllib.request.Request(url, headers=dict({"Authorization": "Bearer " + self.token(), "Accept": "application/json"}, **(headers or {})))
        return self._call(req)

    def post(self, path, body):
        req = urllib.request.Request(self.graph + path, data=json.dumps(body).encode("utf-8"), method="POST",
                                     headers={"Authorization": "Bearer " + self.token(), "Content-Type": "application/json", "Accept": "application/json"})
        return self._call(req)

    def _call(self, req):
        try:
            with self._open(req) as r:
                raw = r.read().decode("utf-8")
                return json.loads(raw) if raw else {}
        except urllib.error.HTTPError as e:
            try:
                j = json.loads(e.read(8000).decode("utf-8"))
                msg = (j.get("error") or {}).get("message") or ""
            except ValueError:
                msg = ""
            hint = {401: "Anmeldung abgelaufen", 403: "Recht fehlt (in der App-Registrierung erteilt und zugestimmt?)", 429: "zu viele Anfragen, später wieder"}.get(e.code, "")
            raise GraphError("Graph: HTTP %s%s%s" % (e.code, " (%s)" % hint if hint else "", ": " + msg[:200] if msg else ""), e.code)
        except (urllib.error.URLError, OSError) as e:
            raise GraphError("Graph nicht erreichbar: %s" % getattr(e, "reason", e))

    def whoami(self):
        if self.me is None:
            d = self.get("/me", {"$select": "id,displayName,mail,userPrincipalName"})
            self.me = {"id": d.get("id", ""), "name": d.get("displayName", ""), "mail": (d.get("mail") or d.get("userPrincipalName") or "").lower(),
                       "upn": (d.get("userPrincipalName") or "").lower()}
        return self.me

    # -- Lesen
    def fetch(self, now=None):
        """Alles, was das Panel zeigt. Ein Teil darf fehlschlagen, ohne die anderen zu verhindern."""
        now = now or time.time()
        me = self.whoami()
        out = {"ok": True, "ts": now, "me": me["name"] or me["mail"], "errors": {}}
        for part, fn in (("mail", self.mail), ("calendar", self.calendar), ("teams", self.teams)):
            if not self.conf.get(part):
                out[part] = None
                continue
            try:
                out[part] = fn(me, now)
            except GraphError as e:
                out[part] = None
                out["errors"][part] = str(e)
        return out

    def mail(self, me, now):
        since = datetime.fromtimestamp(now, timezone.utc) - timedelta(days=int(self.conf.get("reply_days") or 3))
        d = self.get("/me/mailFolders/inbox/messages", {
            "$filter": "receivedDateTime ge %s" % _iso(since), "$orderby": "receivedDateTime desc", "$top": "50",
            "$select": "id,subject,from,toRecipients,receivedDateTime,isRead,flag,webLink,importance,bodyPreview,conversationId",
            "$expand": "singleValueExtendedProperties($filter=id eq '%s')" % VERB_PROP})
        flagged = self.get("/me/messages", {"$filter": "flag/flagStatus eq 'flagged'", "$top": "20",
                                             "$select": "id,subject,from,toRecipients,receivedDateTime,isRead,flag,webLink,importance,bodyPreview,conversationId"})
        return classify_mail(d.get("value") or [], flagged.get("value") or [], me, now)

    def calendar(self, me, now):
        day0 = datetime.fromtimestamp(now).replace(hour=0, minute=0, second=0, microsecond=0)
        d = self.get("/me/calendarView", {"startDateTime": _iso(day0), "endDateTime": _iso(day0 + timedelta(days=2)), "$top": "60",
                                          "$orderby": "start/dateTime",
                                          "$select": "id,subject,start,end,isAllDay,isCancelled,showAs,location,isOnlineMeeting,onlineMeeting,webLink,responseStatus,organizer,categories"},
                     headers={"Prefer": 'outlook.timezone="UTC"'})
        return classify_events(d.get("value") or [], me, now)

    def teams(self, me, now):
        d = self.get("/me/chats", {"$expand": "lastMessagePreview", "$top": "50", "$orderby": "lastMessagePreview/createdDateTime desc"})
        return classify_chats(d.get("value") or [], me, now)

    # -- Schreiben
    def block(self, subject, start, end, body=""):
        """Termin «beschäftigt» im eigenen Kalender. Nur für Fokus-Sitzungen, nur wenn calendar_write an ist."""
        if not self.conf.get("calendar_write"):
            raise GraphError("Kalender eintragen ist ausgeschaltet (Einstellungen → Microsoft 365).")
        ev = self.post("/me/events", {"subject": subject[:200], "showAs": "busy", "isReminderOn": False, "categories": ["tinyops"],
                                      "body": {"contentType": "text", "content": body[:1000]},
                                      "start": {"dateTime": datetime.fromtimestamp(start, timezone.utc).strftime("%Y-%m-%dT%H:%M:%S"), "timeZone": "UTC"},
                                      "end": {"dateTime": datetime.fromtimestamp(end, timezone.utc).strftime("%Y-%m-%dT%H:%M:%S"), "timeZone": "UTC"}})
        return {"id": ev.get("id", ""), "url": ev.get("webLink", "")}


def _explain(code, desc):
    desc = re.sub(r"\s*Trace ID:.*$", "", str(desc or ""), flags=re.S).strip()
    hints = {
        "invalid_client": "Client-ID stimmt nicht, oder in der App-Registrierung ist «Öffentliche Clientflows zulassen» aus.",
        "unauthorized_client": "Die App-Registrierung erlaubt diesen Ablauf nicht (Plattform «Mobile- und Desktopanwendungen» mit http://localhost fehlt).",
        "invalid_grant": "Anmeldung abgelaufen oder widerrufen. Bitte neu «Anmelden».",
        "interaction_required": "Microsoft verlangt eine neue Anmeldung (z. B. wegen Conditional Access). Bitte «Anmelden».",
        "consent_required": "Für die Rechte fehlt die Zustimmung. Ein Admin muss sie in der App-Registrierung erteilen.",
        "access_denied": "Anmeldung abgebrochen oder verweigert.",
        "expired_token": "Der Code ist abgelaufen. Bitte neu anfordern.",
    }
    first = desc.split("\n")[0][:300]
    return "%s%s" % (hints.get(code, ""), (" (" + first + ")") if first else "") if code in hints else (first or str(code))


def _verb(m):
    for p in m.get("singleValueExtendedProperties") or []:
        try:
            return int(p.get("value") or 0)
        except (TypeError, ValueError):
            return 0
    return 0


def classify_mail(recent, flagged, me, now):
    mine = {me.get("mail", ""), me.get("upn", "")} - {""}
    waiting, unread, seen = [], 0, set()
    for m in sorted(recent, key=lambda x: x.get("receivedDateTime") or "", reverse=True):     # neueste zuerst: je Unterhaltung zählt die letzte Mail
        frm, name = _addr(m.get("from"))
        if frm in mine:
            continue
        if not m.get("isRead"):
            unread += 1
        to = {_addr(x)[0] for x in m.get("toRecipients") or []}
        direct = bool(to & mine)
        replied = _verb(m) in (102, 103)
        if direct and not replied and not AUTO_FROM.search(frm or name) and m.get("conversationId") not in seen:
            seen.add(m.get("conversationId"))
            waiting.append(_mail_row(m, name, now, "direkt an dich"))
    flags = [_mail_row(m, _addr(m.get("from"))[1], now, "markiert") for m in flagged if m.get("id") not in {w["id"] for w in waiting}]
    waiting.sort(key=lambda x: x["ts"])
    return {"waiting": waiting[:15], "flagged": flags[:10], "waiting_total": len(waiting), "flagged_total": len(flagged), "unread": unread}


def _mail_row(m, name, now, why):
    ts = _ts(m.get("receivedDateTime"))
    return {"id": m.get("id", ""), "subject": (m.get("subject") or "(ohne Betreff)")[:200], "from": name[:80], "ts": ts, "age_h": round((now - ts) / 3600, 1) if ts else None,
            "read": bool(m.get("isRead")), "important": m.get("importance") == "high", "url": m.get("webLink", ""), "why": why,
            "preview": " ".join((m.get("bodyPreview") or "").split())[:160], "key": (KEY_RE.search(m.get("subject") or "") or [""])[0] if m.get("subject") else ""}


def classify_events(events, me, now):
    rows = []
    for e in events:
        if e.get("isCancelled"):
            continue
        s, en = _ts((e.get("start") or {}).get("dateTime")), _ts((e.get("end") or {}).get("dateTime"))
        resp = ((e.get("responseStatus") or {}).get("response") or "").lower()
        if resp == "declined":
            continue
        org = _addr((e.get("organizer") or {}))
        rows.append({"id": e.get("id", ""), "subject": (e.get("subject") or "(ohne Titel)")[:200], "start": s, "end": en, "all_day": bool(e.get("isAllDay")),
                     "show_as": e.get("showAs") or "", "location": ((e.get("location") or {}).get("displayName") or "")[:100],
                     "online": bool(e.get("isOnlineMeeting")), "join": ((e.get("onlineMeeting") or {}).get("joinUrl") or ""), "url": e.get("webLink", ""),
                     "response": resp, "organizer": org[1][:80], "mine": org[0] in ({me.get("mail"), me.get("upn")} - {""}),
                     "tinyops": "tinyops" in (e.get("categories") or []), "key": (KEY_RE.search(e.get("subject") or "") or [""])[0] if e.get("subject") else ""})
    day_end = datetime.fromtimestamp(now).replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
    today = [r for r in rows if r["start"] < day_end.timestamp()]
    timed = [r for r in today if not r["all_day"]]
    nxt = next((r for r in timed if r["start"] > now and not r["tinyops"]), None)
    cur = [r for r in timed if r["start"] <= now < r["end"] and not r["tinyops"]]
    busy = sum(max(0, r["end"] - r["start"]) for r in timed if r["show_as"] in ("busy", "oof", "tentative", "workingElsewhere") and not r["tinyops"])
    return {"today": today[:30], "tomorrow": [r for r in rows if r["start"] >= day_end.timestamp()][:20], "next": nxt, "now": cur[:3],
            "meeting_minutes": int(busy // 60), "past_unbooked": [r for r in timed if r["end"] <= now and not r["tinyops"] and r["response"] != "notresponded"][:15]}


def classify_chats(chats, me, now):
    out = []
    for c in chats:
        lm = c.get("lastMessagePreview") or {}
        frm = ((lm.get("from") or {}).get("user") or {})
        if not lm or frm.get("id") == me.get("id") or lm.get("isDeleted"):
            continue
        sent = _ts(lm.get("createdDateTime"))
        read = _ts(((c.get("viewpoint") or {}).get("lastMessageReadDateTime")))
        if sent <= read:
            continue
        body = re.sub(r"<[^>]+>", " ", ((lm.get("body") or {}).get("content") or ""))
        body = " ".join(body.replace("&nbsp;", " ").split())[:160]
        out.append({"id": c.get("id", ""), "topic": (c.get("topic") or frm.get("displayName") or "Chat")[:100], "from": (frm.get("displayName") or "")[:80],
                    "ts": sent, "age_h": round((now - sent) / 3600, 1) if sent else None, "kind": c.get("chatType") or "", "url": c.get("webUrl", ""), "preview": body})
    return {"unread": out[:15], "unread_total": len(out)}


def demo(now=None):
    """Erfundene Daten für die Demo."""
    now = now or time.time()
    d0 = datetime.fromtimestamp(now).replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
    ev = lambda i, h, m, mins, subj, **k: dict({"id": "ev%d" % i, "subject": subj, "start": d0 + h * 3600 + m * 60, "end": d0 + h * 3600 + m * 60 + mins * 60,
                                                "all_day": False, "show_as": "busy", "location": "", "online": True, "join": "https://teams.example/join", "url": "https://outlook.example/ev",
                                                "response": "accepted", "organizer": "Mara Keller", "mine": False, "tinyops": False, "key": (KEY_RE.search(subj) or [""])[0]}, **k)
    today = [ev(1, 8, 45, 15, "Daily DLP"), ev(2, 10, 0, 60, "Refinement DLP-120 Quarantäne-API"), ev(3, 13, 30, 90, "Lernende: Wochengespräch", organizer="du", mine=True),
             ev(4, 16, 0, 30, "Abstimmung Labelo")]
    nxt = next((r for r in today if r["start"] > now), None)
    return {"ok": True, "ts": now, "me": "Demo Benutzer", "errors": {}, "demo": True,
            "mail": {"waiting": [{"id": "m1", "subject": "Frage zum Retry im Vendex-Adapter", "from": "Mara Keller", "ts": now - 26 * 3600, "age_h": 26.0, "read": True,
                                  "important": False, "url": "https://outlook.example/m1", "why": "direkt an dich", "preview": "Kannst du mir sagen, ob 5 Versuche reichen?", "key": ""},
                                 {"id": "m2", "subject": "Lernende: Bewertung Projektarbeit", "from": "Lea Graf", "ts": now - 5 * 3600, "age_h": 5.0, "read": False,
                                  "important": True, "url": "https://outlook.example/m2", "why": "direkt an dich", "preview": "Bis Freitag bräuchte ich deine Einschätzung.", "key": ""}],
                     "flagged": [{"id": "m3", "subject": "Offerte Lizenzen 2027", "from": "Einkauf", "ts": now - 72 * 3600, "age_h": 72.0, "read": True, "important": False,
                                  "url": "https://outlook.example/m3", "why": "markiert", "preview": "", "key": ""}],
                     "waiting_total": 2, "flagged_total": 1, "unread": 7},
            "calendar": {"today": today, "tomorrow": [], "next": nxt, "now": [r for r in today if r["start"] <= now < r["end"]], "meeting_minutes": 195,
                         "past_unbooked": [r for r in today if r["end"] <= now]},
            "teams": {"unread": [{"id": "c1", "topic": "DLP Dev", "from": "Nico Brunner", "ts": now - 1800, "age_h": 0.5, "kind": "group", "url": "https://teams.example/c1",
                                  "preview": "Pipeline auf main ist wieder grün"}], "unread_total": 1}}
