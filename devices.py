"""Apps koppeln (0.35.2): Einmal-Code aus dem QR-Code gegen ein Geräte-Token tauschen.

Ablauf:
1. Das Panel fordert einen Einmal-Code an (pair_start). Er gilt wenige Minuten, immer nur einer zur selben Zeit.
2. Die App schickt den Code (pair_finish) und bekommt ein eigenes Token. Der Code ist danach verbraucht.
3. Jede Anfrage der App trägt das Token (check). In der Datenbank liegt nur sein SHA-256; widerrufen geht je Gerät.

Das Token steht nie im QR-Code. Wer den QR-Code später findet, kann damit nichts anfangen.
Die Verschlüsselung auf der Leitung ist Sache von HTTPS (E10); dieses Modul ersetzt sie nicht."""
import hashlib
import hmac
import secrets
import sqlite3
import threading
import time
import urllib.parse
from pathlib import Path

CODE_TTL = 300                  # Sekunden, die ein Einmal-Code gilt
CODE_TRIES = 5                  # falsche Versuche, danach ist der Code ungültig
CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"      # ohne 0/O und 1/I
SEEN_STEP = 60                  # «zuletzt gesehen» höchstens einmal je Minute schreiben
MAX_DEVICES = 20


class PairError(Exception):
    """Kopplung abgelehnt; die Meldung darf der Nutzer sehen."""


def _hash(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def normalize_code(code):
    return "".join(ch for ch in str(code or "").upper() if ch in CODE_ALPHABET)


def clean_origin(url):
    """«http://host:port» aus einer Adresse, oder '' wenn es keine http(s)-Adresse ist."""
    try:
        p = urllib.parse.urlsplit(str(url or "").strip())
    except ValueError:
        return ""
    if p.scheme not in ("http", "https") or not p.hostname or p.username or p.password:
        return ""
    return "%s://%s" % (p.scheme, p.netloc.lower())


def pair_link(app_url, instance_url, code):
    """Der Link im QR-Code. Code und Adresse stehen hinter «#»: Dieser Teil geht nie an einen Server und in kein Zugriffslog."""
    return "%s/#pair=%s@%s" % (app_url.rstrip("/"), code, urllib.parse.quote(instance_url, safe=""))


class Devices:
    def __init__(self, path):
        self.path = Path(path)
        self._lock = threading.Lock()
        self._pending = None            # {"hash", "expires", "tries"}: bewusst nur im Speicher, ein Neustart verwirft offene Codes
        self._seen = {}

    def _conn(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self.path))
        conn.row_factory = sqlite3.Row
        conn.execute("create table if not exists app_devices(id integer primary key autoincrement, name text not null, token_hash text not null unique,"
                     " created real not null, last_seen real not null default 0, revoked real not null default 0)")
        return conn

    # -- Kopplung
    def pair_start(self, now=None):
        now = now or time.time()
        raw = "".join(secrets.choice(CODE_ALPHABET) for _ in range(8))
        with self._lock:
            self._pending = {"hash": _hash(raw), "expires": now + CODE_TTL, "tries": 0}
        return {"code": raw[:4] + "-" + raw[4:], "expires": now + CODE_TTL, "ttl": CODE_TTL}

    def pair_cancel(self):
        with self._lock:
            self._pending = None

    def pending(self, now=None):
        now = now or time.time()
        with self._lock:
            return bool(self._pending and self._pending["expires"] > now)

    def pair_finish(self, code, name, now=None):
        now = now or time.time()
        code = normalize_code(code)
        name = " ".join(str(name or "").split())[:60] or "App"
        with self._lock:
            p = self._pending
            if not p or p["expires"] <= now:
                self._pending = None
                raise PairError("Kein gültiger Code. In tinyops unter Einstellungen → «App koppeln» einen neuen QR-Code erzeugen.")
            if not hmac.compare_digest(_hash(code), p["hash"]):
                p["tries"] += 1
                if p["tries"] >= CODE_TRIES:
                    self._pending = None
                    raise PairError("Zu viele falsche Versuche. Der Code ist ungültig, bitte einen neuen erzeugen.")
                raise PairError("Der Code stimmt nicht.")
            self._pending = None            # verbraucht, auch wenn danach etwas schiefgeht
        token = secrets.token_urlsafe(32)
        conn = self._conn()
        try:
            with conn:
                active = conn.execute("select count(*) from app_devices where revoked = 0").fetchone()[0]
                if active >= MAX_DEVICES:
                    raise PairError("Es sind schon %d Geräte gekoppelt. Bitte zuerst eines entfernen." % MAX_DEVICES)
                cur = conn.execute("insert into app_devices(name, token_hash, created) values(?,?,?)", (name, _hash(token), now))
                dev_id = cur.lastrowid
        finally:
            conn.close()
        return token, {"id": dev_id, "name": name}

    # -- Zugriff
    def check(self, token, now=None):
        """Das Gerät zu einem Token, oder None. Widerrufene Geräte gelten als unbekannt."""
        if not token or len(token) > 200 or not self.path.exists():
            return None
        now = now or time.time()
        conn = self._conn()
        try:
            r = conn.execute("select id, name from app_devices where token_hash = ? and revoked = 0", (_hash(token),)).fetchone()
            if r is None:
                return None
            if now - self._seen.get(r["id"], 0) >= SEEN_STEP:
                self._seen[r["id"]] = now
                with conn:
                    conn.execute("update app_devices set last_seen = ? where id = ?", (now, r["id"]))
            return {"id": r["id"], "name": r["name"]}
        finally:
            conn.close()

    def list(self):
        if not self.path.exists():
            return []
        conn = self._conn()
        try:
            rows = conn.execute("select id, name, created, last_seen from app_devices where revoked = 0 order by id").fetchall()
            return [dict(r) for r in rows]          # nie der Token-Hash
        finally:
            conn.close()

    def revoke(self, dev_id, now=None):
        conn = self._conn()
        try:
            with conn:
                r = conn.execute("select name from app_devices where id = ? and revoked = 0", (int(dev_id),)).fetchone()
                if r is None:
                    return None
                conn.execute("update app_devices set revoked = ? where id = ?", (now or time.time(), int(dev_id)))
                return r["name"]
        finally:
            conn.close()


# -- Was die App sieht: Fokus und Tickets, nur lesend
_KIND_ORDER = {"blocked": 0, "do": 1, "wait": 2}


def focus_payload(ov, instance):
    """Kurzfassung der Übersicht für die App. Bewusst schmal: keine Tokens, keine Pfade, keine Befehle zum Kopieren."""
    flow = ov.get("flow") or {}
    cards = {c["id"]: c for c in ((ov.get("board") or {}).get("cards") or [])}
    phases = {p["id"]: p["label"] for p in flow.get("phases") or []}
    pinned = flow.get("pinned")
    items = []
    for key, it in (flow.get("items") or {}).items():
        card = cards.get(key) or {}
        nxt = it.get("next") or {}
        if it.get("phase_id") == "done":
            continue
        items.append({
            "key": key,
            "title": card.get("title") or key,
            "url": card.get("url") or "",
            "phase": phases.get(it.get("phase_id"), it.get("phase_id") or ""),
            "kind": nxt.get("kind") or "",
            "next": nxt.get("label") or "",
            "why": nxt.get("why") or "",
            "owner": nxt.get("owner") or "",
            "pinned": key == pinned,
            "_prio": it.get("prio", 0),
        })
    items.sort(key=lambda x: (not x["pinned"], _KIND_ORDER.get(x["kind"], 3), -x["_prio"], x["key"]))
    for x in items:
        del x["_prio"]
    helpdesk = [{"key": h.get("key", ""), "title": h.get("title", ""), "url": h.get("url", ""), "priority": h.get("priority", ""),
                 "over_sla": bool(h.get("over_sla")), "next": (h.get("next") or {}).get("label", ""), "pinned": h.get("id") == pinned}
                for h in flow.get("helpdesk") or []]
    ses = (ov.get("focus") or {}).get("session")
    session = {"title": ses.get("title", ""), "area": ses.get("area_name", ""), "left_secs": ses.get("left_secs", 0)} if ses else None
    return {"instance": instance, "fetched": ov.get("fetched") or time.time(), "loading": bool(ov.get("loading")),
            "configured": bool(ov.get("configured", True)), "errors": len(ov.get("errors") or []),
            "pinned": pinned, "session": session, "items": items, "helpdesk": helpdesk}
