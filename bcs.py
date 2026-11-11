"""BCS-Buchungen über deine lokale Middleware (0.29), Workflow-API /api/v1.

Ablauf, wie die Middleware ihn vorgibt
1. Tag lesen (GET /days/{date}): was in BCS schon steht, Warnungen, Summen.
2. Vorschau (POST /drafts/preview): alle Buchungen eines Tages gemeinsam prüfen. Nur «ready» liefert eine draftId, sie gilt 15 Minuten.
3. Bestätigen (POST /drafts/commit, confirm: true): einmal, nur nach deinem Klick. Nur «committed» heisst gebucht; «dry_run» schreibt nichts.
   Bricht die Verbindung beim Bestätigen ab, ist unklar, ob gebucht wurde: dann nie automatisch wiederholen, sondern erst den Tag lesen.

tinyops spricht nur mit einer Adresse auf diesem Rechner (Loopback) und schickt keine BCS-Zugangsdaten mit, höchstens das Token der Middleware.
"""
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

DEFAULTS = {"enabled": False, "url": "http://127.0.0.1:3210", "apprentices": True}
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
HHMM_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
LOOPBACK = ("127.0.0.1", "localhost", "::1", "[::1]")
TASK_ID_MAX, DESC_MAX = 160, 2000
SECRET = "bcs_token"


class BcsError(Exception):
    def __init__(self, msg, code=0, uncertain=False):
        super().__init__(msg)
        self.code, self.uncertain = code, uncertain


def cfg(c):
    out = dict(DEFAULTS)
    out.update(((c.get("time") or {}).get("bcs")) or {})
    return out


def check_url(url):
    """Nur http(s) auf Loopback. Die Middleware nimmt laut Spezifikation ohnehin nur lokale Anfragen an."""
    u = urllib.parse.urlparse((url or "").strip())
    if u.scheme not in ("http", "https") or not u.hostname:
        raise BcsError("Adresse wie http://127.0.0.1:3210 erwartet.")
    if u.hostname not in LOOPBACK and u.hostname != "::1":
        raise BcsError("Die BCS-Middleware muss auf diesem Rechner laufen (127.0.0.1 oder localhost), nicht auf «%s»." % u.hostname)
    if u.username or u.password or u.query or u.fragment:
        raise BcsError("Adresse ohne Benutzer, Parameter oder Anker angeben.")
    return "%s://%s%s" % (u.scheme, u.netloc, u.path.rstrip("/"))


class Client:
    def __init__(self, url, token="", timeout=20):
        self.base = check_url(url)
        self.token, self.timeout = token or "", timeout

    def _call(self, method, path, params=None, body=None, timeout=None, write=False):
        url = self.base + path + ("?" + urllib.parse.urlencode(params) if params else "")
        headers = {"Accept": "application/json", "User-Agent": "tinyops"}
        data = None
        if body is not None:
            data = json.dumps(body, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json"
        if self.token:
            headers["Authorization"] = "Bearer " + self.token
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))      # Loopback nie über einen Proxy
        try:
            with opener.open(req, timeout=timeout or self.timeout) as r:
                raw = r.read(4 << 20).decode("utf-8")
        except urllib.error.HTTPError as e:
            try:
                j = json.loads(e.read(1 << 16).decode("utf-8") or "{}")
            except ValueError:
                j = {}
            msg = str(j.get("error") or j.get("message") or "")[:300]
            hint = {400: "Ungültige Eingabe", 401: "Token fehlt oder ist ungültig (BCS_API_TOKEN der Middleware als bcs_token eintragen)",
                    403: "Die Middleware nimmt die Anfrage nicht an (nicht lokal oder fremde Origin)", 404: "Unbekannte Route: passt die Version der Middleware?",
                    502: "BCS oder die Middleware ist gerade nicht verfügbar"}.get(e.code, "HTTP %s" % e.code)
            raise BcsError("%s%s" % (hint, ": " + msg if msg and msg not in hint else ""), e.code, uncertain=write and e.code == 502)
        except (urllib.error.URLError, OSError, TimeoutError) as e:
            raise BcsError("BCS-Middleware nicht erreichbar (%s). Läuft sie auf %s?" % (getattr(e, "reason", e), self.base), 0, uncertain=write)
        try:
            return json.loads(raw) if raw else {}
        except ValueError:
            raise BcsError("Antwort der Middleware ist kein JSON.", 0, uncertain=write)

    @staticmethod
    def _date(d):
        if not DATE_RE.match(str(d or "")):
            raise BcsError("Datum im Format JJJJ-MM-TT.")
        return d

    # -- lesen
    def day(self, d):
        return self._call("GET", "/api/v1/days/%s" % self._date(d))

    def overview(self, d, scope="week"):
        return self._call("GET", "/api/v1/overviews", {"date": self._date(d), "scope": scope if scope in ("week", "month") else "week"})

    def targets(self, d, query):
        q = " ".join(str(query or "").split())[:200]
        if len(q) < 2:
            raise BcsError("Mindestens zwei Zeichen suchen.")
        return (self._call("GET", "/api/v1/booking-targets", {"date": self._date(d), "query": q}).get("items") or [])[:50]

    def suggestions(self, d):
        return self._call("GET", "/api/v1/suggestions", {"date": self._date(d)})

    def time_balance(self):
        return self._call("GET", "/api/v1/reports/time-balance")

    def apprentices(self):
        return self._call("GET", "/api/v1/reports/apprentices")

    def dashboard(self, member_id=""):
        return self._call("GET", "/api/v1/reports/dashboard", {"memberId": member_id} if member_id else None)

    # -- schreiben in zwei Schritten
    def preview(self, d, changes):
        return self._call("POST", "/api/v1/drafts/preview", body={"date": self._date(d), "changes": changes})

    def commit(self, d, draft_id):
        """Genau ein Versuch. Bei Abbruch: BcsError mit uncertain=True."""
        try:
            uuid.UUID(str(draft_id))
        except ValueError:
            raise BcsError("Ungültige Entwurfs-ID der Middleware.")
        return self._call("POST", "/api/v1/drafts/commit", body={"date": self._date(d), "draftId": str(draft_id), "confirm": True}, timeout=60, write=True)


def change_for(draft, task_id):
    """Ein Zeitentwurf von tinyops als Buchung für BCS: Arbeit, Dauer, Text mit Ticket vorne, Aufgabe per ID."""
    text = " ".join(str(draft.get("text") or "").split())
    ticket = draft.get("ticket") or ""
    desc = text if not ticket or text.startswith(ticket) else ("%s %s" % (ticket, text)).strip()
    return {"action": "add", "kind": "work", "durationMinutes": int(draft["minutes"]), "description": desc[:DESC_MAX], "taskId": str(task_id)[:TASK_ID_MAX]}


def matches(entry, change):
    """Steht dieser Eintrag in BCS für diese Buchung? (für den Abgleich nach einem unklaren Bestätigen)"""
    task = (entry.get("task") or {}).get("id") or ""
    return (entry.get("kind") in ("work", None, "") and task == change["taskId"] and int(entry.get("durationMinutes") or -1) == change["durationMinutes"]
            and " ".join((entry.get("description") or "").split()) == change["description"])


def prefix_of(ticket):
    m = re.match(r"^([A-Z][A-Z0-9_]{0,30})-\d+$", ticket or "")
    return m.group(1) + "-*" if m else ""


def day_summary(day):
    t = day.get("totals") or {}
    work = [e for e in day.get("entries") or [] if e.get("kind") == "work"]
    return {"date": day.get("date"), "closed": bool(day.get("closedDate")), "closed_date": day.get("closedDate"), "work_minutes": t.get("workMinutes", 0),
            "attendance_minutes": t.get("attendanceMinutes", 0), "pause_minutes": t.get("pauseMinutes", 0), "unallocated_minutes": t.get("unallocatedMinutes", 0),
            "issues": [(i.get("message") or i.get("text") or json.dumps(i, ensure_ascii=False))[:200] for i in day.get("issues") or []][:10],
            "entries": [{"id": e.get("id"), "kind": e.get("kind"), "start": e.get("startTime"), "end": e.get("endTime"), "minutes": e.get("durationMinutes"),
                         "description": (e.get("description") or "")[:200], "task": ((e.get("task") or {}).get("name") or ""),
                         "path": " › ".join((e.get("task") or {}).get("path") or []), "open": bool(e.get("open"))} for e in day.get("entries") or []][:60],
            "absences": len(day.get("absences") or []), "work_entries": len(work), "sync": (day.get("shadowSync") or {}).get("status", "")}


class Demo:
    """Erfundene Middleware für Demo und Selbsttest. Verhält sich wie die echte: Vorschau, draftId 15 Minuten, einmal bestätigen."""
    TASKS = [{"id": "T-100", "name": "Entwicklung DLP", "path": ["Produkte", "DLP", "Entwicklung"], "favorite": True},
             {"id": "T-200", "name": "Berufsbildung", "path": ["Intern", "Berufsbildung"], "favorite": True},
             {"id": "T-210", "name": "Betreuung Lernende", "path": ["Intern", "Berufsbildung", "Betreuung"], "favorite": False},
             {"id": "T-300", "name": "Support Helpdesk", "path": ["Betrieb", "Helpdesk"], "favorite": False},
             {"id": "T-900", "name": "Meetings intern", "path": ["Intern", "Meetings"], "favorite": False}]

    def __init__(self):
        self.base = "demo"
        self.days, self.drafts, self.committed = {}, {}, []

    def _task(self, tid):
        return next((t for t in self.TASKS if t["id"] == tid), None)

    def day(self, d):
        e = self.days.setdefault(d, [{"id": "e-att", "kind": "attendance", "startTime": "08:00", "endTime": "17:00", "durationMinutes": 540, "description": "", "task": None, "open": False},
                                     {"id": "e-p", "kind": "pause", "startTime": "12:00", "endTime": "12:45", "durationMinutes": 45, "description": "", "task": None, "open": False},
                                     {"id": "e-1", "kind": "work", "startTime": None, "endTime": None, "durationMinutes": 60, "description": "Daily und Planung",
                                      "task": self._task("T-900"), "open": False}])
        work = sum(x["durationMinutes"] or 0 for x in e if x["kind"] == "work")
        return {"date": d, "closedDate": None, "entries": e, "absences": [], "issues": [], "issuesAvailable": True,
                "totals": {"workMinutes": work, "attendanceMinutes": 540, "pauseMinutes": 45, "unallocatedMinutes": max(0, 495 - work), "workEntries": 1, "issues": 0},
                "shadowSync": {"status": "synced", "count": len(e)}}

    def overview(self, d, scope="week"):
        return {"scope": scope, "actualMinutes": 1980, "workMinutes": 1860, "targetMinutes": 2520, "differenceMinutes": -540, "through": d, "actualComplete": False, "days": []}

    def targets(self, d, query):
        q = query.lower()
        return [t for t in self.TASKS if q in t["name"].lower() or any(q in p.lower() for p in t["path"])] or self.TASKS[:2]

    def suggestions(self, d):
        return {"daysRead": 20, "suggestions": [{"task": self.TASKS[0], "days": 14, "duration": 240}, {"task": self.TASKS[1], "days": 6, "duration": 120}]}

    def time_balance(self):
        return {"recognized": True, "months": [{"month": "2026-10", "actualMinutes": 10080, "targetMinutes": 10080, "balanceWithoutOvertimeMinutes": 0}], "existingOvertimeMinutes": 750}

    def apprentices(self):
        return {"configured": True, "recognized": True, "members": [{"id": "m1", "name": "Lea Graf"}, {"id": "m2", "name": "Jonas Meier"}]}

    def dashboard(self, member_id=""):
        names = {"m1": "Lea Graf", "m2": "Jonas Meier"}
        bal = {"m1": -95, "m2": 210}.get(member_id, 0)
        return {"status": "available", "asOf": time.strftime("%Y-%m-%d"), "member": {"id": member_id, "name": names.get(member_id, "?")},
                "ytd": {"period": "2026", "balanceMinutes": bal * 4, "source": "soap"}, "vacation": {"remainingDays": {"m1": 8.5, "m2": 14}.get(member_id), "usedDays": 12},
                "currentWeek": {"days": [{"date": "x", "targetMinutes": 504, "actualMinutes": 504 + bal // 5, "balanceMinutes": bal // 5}] * 3}}

    def preview(self, d, changes):
        warn, ents = [], []
        for i, c in enumerate(changes):
            if not self._task(c.get("taskId")):
                warn.append({"index": i, "message": "Aufgabe %s unbekannt" % c.get("taskId"), "candidates": self.TASKS[:2]})
            ents.append({"id": "neu-%d" % i, "kind": "work", "startTime": None, "endTime": None, "durationMinutes": c["durationMinutes"], "description": c["description"],
                         "task": self._task(c.get("taskId")), "open": False})
        if warn:
            return {"status": "blocked", "date": d, "draftId": None, "entries": ents, "deletions": [], "warnings": warn, "dryRun": False, "message": "Nicht buchbar"}
        did = str(uuid.uuid4())
        self.drafts[did] = (d, changes, time.time())
        return {"status": "ready", "date": d, "draftId": did, "entries": ents, "deletions": [], "warnings": [], "dryRun": False,
                "expiresAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() + 900)), "message": "Bereit"}

    def commit(self, d, draft_id):
        hit = self.drafts.pop(draft_id, None)
        if not hit:
            return {"status": "invalid_draft", "date": d, "message": "Entwurf unbekannt oder schon verwendet"}
        if time.time() - hit[2] > 900:
            return {"status": "stale_draft", "date": d, "message": "Entwurf abgelaufen"}
        day = self.day(d)["entries"]
        for i, c in enumerate(hit[1]):
            day.append({"id": "e-%d" % (len(day) + 1), "kind": "work", "startTime": None, "endTime": None, "durationMinutes": c["durationMinutes"],
                        "description": c["description"], "task": self._task(c["taskId"]), "open": False})
        self.committed.append(hit)
        return {"status": "committed", "date": d, "message": "%d Buchung%s gespeichert" % (len(hit[1]), "" if len(hit[1]) == 1 else "en"), "entries": day, "refreshRequired": False}
