"""Fokus-Zeit und Zeitentwürfe (0.19).

Zeit läuft nur für das angeheftete Vorhaben (Fokus). Das Panel meldet sich jede Minute, solange du es benutzt («ping»).
Bleibt das länger als idle_minutes aus, endet der Abschnitt beim letzten Lebenszeichen; die Pause wird als **Lücke**
vorgeschlagen und zählt nur, wenn du sie annimmst. Agentenlaufzeit zählt nie.

Aus den Abschnitten eines Tages entstehen Entwürfe je Ticket (gerundet). Gebucht wird nichts von selbst:
erst «Bestätigen», dann geht der Entwurf an die Wrapper-API deines MCP (oder dein MCP holt ihn ab).

Zustände eines Entwurfs: offen → bestätigt → gebucht | abgelehnt | fehlgeschlagen (= bestätigt, nicht gebucht); verworfen.
"""
import hashlib
import json
import sqlite3
import threading
import time
from datetime import date as _date, datetime, timedelta
from pathlib import Path

STATES = ("offen", "bestätigt", "gebucht", "abgelehnt", "fehlgeschlagen", "verworfen", "unklar")    # unklar (0.29): Bestätigen in BCS brach ab, erst abgleichen
LOCKED = ("gebucht",)                       # nie mehr ändern
SENDABLE = ("bestätigt", "fehlgeschlagen")
CONTRACT = "tinyops.time-entry/1"
DEFAULTS = {
    "enabled": True,
    "round_minutes": 15,      # Entwürfe auf so viele Minuten runden
    "min_minutes": 5,         # darunter entsteht kein Entwurf
    "idle_minutes": 15,       # so lange ohne Panel-Aktivität: Abschnitt endet, die Pause wird als Lücke vorgeschlagen
    "mcp_url": "",            # Wrapper-API deines MCP, z. B. http://127.0.0.1:3100/time-entries (POST)
    "allow_remote": False,    # nur Adressen im eigenen Netz, ausser ausdrücklich erlaubt
    "send_on_confirm": True,  # «Bestätigen» schickt sofort; sonst holt dein MCP über GET /api/time/export ab
}


def day_bounds(d):
    """Lokaler Tag [start, end) als Zeitstempel."""
    dd = _date.fromisoformat(d) if isinstance(d, str) else d
    start = datetime(dd.year, dd.month, dd.day).timestamp()
    return start, (datetime(dd.year, dd.month, dd.day) + timedelta(days=1)).timestamp()


def today(now=None):
    return datetime.fromtimestamp(now or time.time()).strftime("%Y-%m-%d")


def round_minutes(secs, unit=15, minimum=5):
    """Auf `unit` Minuten runden (kaufmännisch). Ab `minimum` Minuten gibt es mindestens eine Einheit, darunter nichts."""
    m = secs / 60.0
    if m < minimum:
        return 0
    unit = max(1, int(unit))
    r = int((m + unit / 2.0) // unit) * unit
    return max(unit, r)


def _hhmm(ts):
    return datetime.fromtimestamp(ts).strftime("%H:%M")


class TimeBook:
    def __init__(self, path):
        self.path = Path(path)
        self.lock = threading.RLock()

    def _conn(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        c = sqlite3.connect(str(self.path), timeout=10)
        c.row_factory = sqlite3.Row
        c.execute("create table if not exists time_seg(id integer primary key autoincrement, key text not null, title text not null default '',"
                  " start real not null, end real, last_seen real not null, source text not null default 'fokus')")
        c.execute("create index if not exists time_seg_start on time_seg(start)")
        c.execute("create table if not exists time_gap(id integer primary key autoincrement, key text not null, title text not null default '',"
                  " start real not null, end real not null, state text not null default 'offen')")
        c.execute("create table if not exists time_draft(id text primary key, date text not null, ticket text not null, title text not null default '',"
                  " project_hint text not null default '', minutes integer not null, calc_minutes integer not null default 0, text text not null default '',"
                  " evidence text not null default '[]', state text not null default 'offen', edited integer not null default 0, manual integer not null default 0,"
                  " reference text not null default '', message text not null default '', attempts integer not null default 0, sent real,"
                  " merged_into text not null default '', updated real not null)")
        c.execute("create index if not exists time_draft_date on time_draft(date)")
        for t in ("time_seg", "time_gap"):                       # 0.23: Fokusbereich und Tätigkeit je Abschnitt
            have = {r[1] for r in c.execute("pragma table_info(%s)" % t)}
            for col in ("area", "activity"):
                if col not in have:
                    try:
                        c.execute("alter table %s add column %s text not null default ''" % (t, col))
                    except sqlite3.OperationalError as e:          # zwei Threads beim ersten Start: der andere war schneller
                        if "duplicate column" not in str(e):
                            raise
        c.execute("create table if not exists focus_session(id integer primary key autoincrement, key text not null, title text not null default '',"
                  " area text not null default '', activity text not null default '', planned_min integer not null, start real not null, end real,"
                  " parked integer not null default 0, result text not null default '', note text not null default '')")
        c.execute("create table if not exists bcs_target(pattern text primary key, task_id text not null, name text not null default '',"
                  " path text not null default '', updated real not null)")      # 0.29: Ticket oder Projekt → BCS-Aufgabe
        return c

    # -- BCS-Ziele (0.29): exaktes Ticket vor Projekt-Präfix («DLP-*»)
    def bcs_targets(self):
        c = self._conn()
        try:
            return {r["pattern"]: dict(r) for r in c.execute("select * from bcs_target")}
        finally:
            c.close()

    def bcs_target_set(self, pattern, task_id, name="", path="", now=None):
        with self.lock:
            c = self._conn()
            try:
                if task_id:
                    c.execute("insert into bcs_target(pattern, task_id, name, path, updated) values(?,?,?,?,?) on conflict(pattern) do update set "
                              "task_id=excluded.task_id, name=excluded.name, path=excluded.path, updated=excluded.updated", (pattern, task_id, name, path, now or time.time()))
                else:
                    c.execute("delete from bcs_target where pattern=?", (pattern,))
                c.commit()
            finally:
                c.close()

    # -- Abschnitte
    def current(self):
        c = self._conn()
        try:
            r = c.execute("select * from time_seg where end is null order by id desc limit 1").fetchone()
            return dict(r) if r else None
        finally:
            c.close()

    def _eff_end(self, seg, now, idle):
        if seg["end"] is not None:
            return seg["end"]
        return seg["last_seen"] if now - seg["last_seen"] > idle * 60 else now

    def start(self, key, title="", now=None, idle=15, area="", activity=""):
        """Zeit für `key` starten. Ein offener Abschnitt eines anderen Vorhabens (oder einer anderen Tätigkeit) endet,
        bei Leerlauf am letzten Lebenszeichen."""
        now = now or time.time()
        with self.lock:
            cur = self.current()
            if cur and cur["key"] == key and cur.get("activity", "") == (activity or "") and (not area or cur.get("area", "") == area):
                self.ping(now, idle)
                return self.current()
            self.stop(now, idle)
            c = self._conn()
            try:
                c.execute("insert into time_seg(key, title, start, last_seen, area, activity) values(?,?,?,?,?,?)",
                          (key, title[:200], now, now, area or "", (activity or "")[:80]))
                c.commit()
            finally:
                c.close()
            return self.current()

    def stop(self, now=None, idle=15):
        now = now or time.time()
        with self.lock:
            cur = self.current()
            if not cur:
                return None
            end = self._eff_end(cur, now, idle)
            c = self._conn()
            try:
                c.execute("update time_seg set end=? where id=?", (max(end, cur["start"]), cur["id"]))
                if end < now - 60 and now - cur["last_seen"] > idle * 60:
                    c.execute("insert into time_gap(key, title, start, end, area, activity) values(?,?,?,?,?,?)",
                              (cur["key"], cur["title"], cur["last_seen"], now, cur.get("area", ""), cur.get("activity", "")))
                c.commit()
            finally:
                c.close()
            return cur["id"]

    def ping(self, now=None, idle=15):
        """Lebenszeichen aus dem Panel. Nach einer Pause über `idle` Minuten: Abschnitt endet beim letzten Lebenszeichen,
        die Pause wird Lücke, ein neuer Abschnitt beginnt jetzt."""
        now = now or time.time()
        with self.lock:
            cur = self.current()
            if not cur:
                return None
            c = self._conn()
            try:
                if now - cur["last_seen"] > idle * 60:
                    c.execute("update time_seg set end=? where id=?", (cur["last_seen"], cur["id"]))
                    c.execute("insert into time_gap(key, title, start, end, area, activity) values(?,?,?,?,?,?)",
                              (cur["key"], cur["title"], cur["last_seen"], now, cur.get("area", ""), cur.get("activity", "")))
                    c.execute("insert into time_seg(key, title, start, last_seen, area, activity) values(?,?,?,?,?,?)",
                              (cur["key"], cur["title"], now, now, cur.get("area", ""), cur.get("activity", "")))
                else:
                    c.execute("update time_seg set last_seen=? where id=?", (now, cur["id"]))
                c.commit()
            finally:
                c.close()
            return self.current()

    def segments(self, d, now=None, idle=15):
        now = now or time.time()
        a, b = day_bounds(d)
        c = self._conn()
        try:
            rows = [dict(r) for r in c.execute("select * from time_seg where start < ? and (end is null or end > ?) order by start", (b, a))]
        finally:
            c.close()
        out = []
        for r in rows:
            end = self._eff_end(r, now, idle)
            s, e = max(r["start"], a), min(end, b)
            if e > s:
                out.append(dict(r, s=s, e=e, secs=int(e - s), open=r["end"] is None, from_=_hhmm(s), to=_hhmm(e)))
        return out

    def totals(self, d, now=None, idle=15):
        t = {}
        for s in self.segments(d, now, idle):
            x = t.setdefault(s["key"], {"secs": 0, "title": s["title"], "segments": 0, "activities": [], "area": ""})
            x["secs"] += s["secs"]
            x["segments"] += 1
            x["title"] = s["title"] or x["title"]
            x["area"] = s.get("area") or x["area"]
            if s.get("activity") and s["activity"] not in x["activities"]:
                x["activities"].append(s["activity"])
        return t

    def range_segments(self, a, b, now=None, idle=15):
        """Abschnitte zwischen zwei Zeitpunkten, auf [a, b) zugeschnitten (für Wochenauswertungen)."""
        now = now or time.time()
        c = self._conn()
        try:
            rows = [dict(r) for r in c.execute("select * from time_seg where start < ? and (end is null or end > ?) order by start", (b, a))]
        finally:
            c.close()
        out = []
        for r in rows:
            s_, e_ = max(r["start"], a), min(self._eff_end(r, now, idle), b)
            if e_ > s_:
                out.append(dict(r, secs=int(e_ - s_)))
        return out

    def add_segment(self, key, title, start, end, source="manuell", area="", activity=""):
        c = self._conn()
        try:
            c.execute("insert into time_seg(key, title, start, end, last_seen, source, area, activity) values(?,?,?,?,?,?,?,?)",
                      (key, title[:200], start, end, end, source, area or "", activity or ""))
            c.commit()
        finally:
            c.close()

    # -- Lücken
    def gaps(self, d, state="offen"):
        a, b = day_bounds(d)
        c = self._conn()
        try:
            rows = [dict(r) for r in c.execute("select * from time_gap where start < ? and end > ? and state=? order by start", (b, a, state))]
        finally:
            c.close()
        for r in rows:
            r.update(minutes=int((r["end"] - r["start"]) // 60), from_=_hhmm(r["start"]), to=_hhmm(r["end"]))
        return rows

    def gap_set(self, gid, count):
        with self.lock:
            c = self._conn()
            try:
                g = c.execute("select * from time_gap where id=? and state='offen'", (gid,)).fetchone()
                if not g:
                    return None
                c.execute("update time_gap set state=? where id=?", ("gezählt" if count else "verworfen", gid))
                c.commit()
            finally:
                c.close()
            if count:
                self.add_segment(g["key"], g["title"], g["start"], g["end"], "lücke", g["area"], g["activity"])
            return dict(g)

    # -- Fokus-Sitzungen (0.23)
    def session(self):
        c = self._conn()
        try:
            r = c.execute("select * from focus_session where end is null order by id desc limit 1").fetchone()
            return dict(r) if r else None
        finally:
            c.close()

    def session_start(self, key, title, area, activity, minutes, now=None):
        now = now or time.time()
        with self.lock:
            c = self._conn()
            try:
                c.execute("update focus_session set end=?, result=case when result='' then 'abgelöst' else result end where end is null", (now,))
                sid = c.execute("insert into focus_session(key, title, area, activity, planned_min, start) values(?,?,?,?,?,?)",
                                (key, title[:200], area or "", activity or "", int(minutes), now)).lastrowid
                c.commit()
                return sid
            finally:
                c.close()

    def session_update(self, sid, **kw):
        with self.lock:
            c = self._conn()
            try:
                c.execute("update focus_session set %s where id=?" % ", ".join("%s=?" % k for k in kw), list(kw.values()) + [sid])
                c.commit()
            finally:
                c.close()

    def sessions(self, a, b):
        c = self._conn()
        try:
            return [dict(r) for r in c.execute("select * from focus_session where start >= ? and start < ? order by start", (a, b))]
        finally:
            c.close()

    # -- Entwürfe
    def drafts(self, d=None, state=None):
        c = self._conn()
        try:
            q, a = "select * from time_draft", []
            w = []
            if d:
                w.append("date=?")
                a.append(d)
            if state:
                w.append("state=?")
                a.append(state)
            if w:
                q += " where " + " and ".join(w)
            q += " order by date, ticket"
            out = []
            for r in c.execute(q, a):
                x = dict(r)
                x["evidence"] = json.loads(x["evidence"] or "[]")
                out.append(x)
            return out
        finally:
            c.close()

    def draft(self, did):
        r = [x for x in self.drafts() if x["id"] == did]
        return r[0] if r else None

    def sync_auto(self, d, composed, now=None):
        """Automatische Entwürfe des Tages nachführen. Bearbeitete, bestätigte und gebuchte bleiben, wie sie sind;
        bei bearbeiteten wird nur die gemessene Zeit (calc_minutes) aktualisiert."""
        now = now or time.time()
        with self.lock:
            c = self._conn()
            try:
                have = {r["id"]: dict(r) for r in c.execute("select * from time_draft where date=?", (d,))}
                for x in composed:
                    did = "td-%s-%s" % (d, x["ticket"])
                    old = have.get(did)
                    ev = json.dumps(x["evidence"], ensure_ascii=False)
                    if not old:
                        if x["minutes"] <= 0:
                            continue
                        c.execute("insert into time_draft(id, date, ticket, title, project_hint, minutes, calc_minutes, text, evidence, updated)"
                                  " values(?,?,?,?,?,?,?,?,?,?)", (did, d, x["ticket"], x["title"], x["project_hint"], x["minutes"], x["minutes"], x["text"], ev, now))
                    elif old["state"] == "offen" and not old["edited"] and not old["manual"]:
                        c.execute("update time_draft set minutes=?, calc_minutes=?, text=?, evidence=?, title=?, project_hint=?, updated=? where id=?",
                                  (x["minutes"], x["minutes"], x["text"], ev, x["title"], x["project_hint"], now, did))
                    elif old["state"] not in LOCKED:
                        c.execute("update time_draft set calc_minutes=?, updated=? where id=?", (x["minutes"], now, did))
                c.commit()
            finally:
                c.close()

    def add_manual(self, d, ticket, minutes, text, title="", project_hint="", now=None):
        now = now or time.time()
        base = "td-%s-%s" % (d, ticket)
        with self.lock:
            c = self._conn()
            try:
                n, did = 1, base + "-m1"
                while c.execute("select 1 from time_draft where id=?", (did,)).fetchone():
                    n += 1
                    did = "%s-m%d" % (base, n)
                c.execute("insert into time_draft(id, date, ticket, title, project_hint, minutes, calc_minutes, text, evidence, manual, edited, updated)"
                          " values(?,?,?,?,?,?,0,?,'[]',1,1,?)", (did, d, ticket, title, project_hint, int(minutes), text, now))
                c.commit()
            finally:
                c.close()
            return did

    def update(self, did, now=None, **kw):
        now = now or time.time()
        allowed = {"minutes", "text", "ticket", "project_hint", "state", "reference", "message", "attempts", "sent", "merged_into", "edited", "evidence"}
        bad = set(kw) - allowed
        if bad:
            raise ValueError("unbekannte Felder: %s" % ", ".join(sorted(bad)))
        if "evidence" in kw and not isinstance(kw["evidence"], str):
            kw["evidence"] = json.dumps(kw["evidence"], ensure_ascii=False)
        with self.lock:
            c = self._conn()
            try:
                c.execute("update time_draft set %s, updated=? where id=?" % ", ".join("%s=?" % k for k in kw), list(kw.values()) + [now, did])
                c.commit()
            finally:
                c.close()


def compose(d, totals, meta, events, accs, unit=15, minimum=5):
    """Entwürfe je Ticket aus den Zeiten eines Tages.
    meta: {key: {"title", "project_hint"}}; events: [{"key", "text", "ts"}] (Stationen, Teilschritte); accs: [{"key", "label", "sha", "ts"}]."""
    out = []
    for key, t in sorted(totals.items()):
        m = meta.get(key) or {}
        title = m.get("title") or t.get("title") or key
        evs = [e for e in events if e.get("key") == key]
        ev = ["%s %s" % (e["text"], _hhmm(e["ts"])) for e in evs][:12]
        ev += ["Abnahme %s @ %s" % (a.get("label") or a.get("ref", ""), (a.get("sha") or "?")[:8]) for a in accs if a.get("key") == key][:6]
        done = (list(t.get("activities") or []) + [e["text"] for e in evs if e.get("kind") == "check"])[:6]
        text = title + (": " + ", ".join(done) if done else "")
        out.append({"ticket": key, "title": title, "project_hint": m.get("project_hint", ""), "minutes": round_minutes(t["secs"], unit, minimum),
                    "secs": t["secs"], "text": text[:300], "evidence": ev})
    return out


def payload(dr):
    """Vertrag mit der Wrapper-API des MCP (Vorschlag, Version 1)."""
    body = {"schema": CONTRACT, "id": dr["id"], "date": dr["date"], "ticket": dr["ticket"], "project_hint": dr["project_hint"],
            "minutes": int(dr["minutes"]), "text": dr["text"], "evidence": dr["evidence"]}
    body["idempotency_key"] = idem_key(body)
    return body


def idem_key(body):
    """Gleicher Inhalt → gleicher Schlüssel: doppelt senden bucht einmal. Geänderter Inhalt nach einem Fehlschlag → neuer Schlüssel."""
    h = hashlib.sha256(json.dumps({k: body[k] for k in ("id", "date", "ticket", "minutes", "text")}, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:10]
    return "%s-%s" % (body["id"], h)
