"""Lokale Zuordnungen, die nur im Panel gelten (nichts davon wird nach Jira oder GitLab geschrieben):

* Verknüpfungen: ein Branch/MR gehört zu einem Ticket, auch wenn der Name nicht passt (Sammel-Tickets für Bugs).
  Sie überstimmen die automatische Erkennung aus dem Branch-Namen und lassen sich wieder lösen.
* Pools: frei benannte Arbeitsbereiche («Agenten-VM», «Produkt X») mit Tickets und Branches/MRs, die ausserhalb von
  Sprint und Story-Limit stehen.

Die Datei liegt neben der Ideenbox (tinyops.db) und wird erst beim ersten Schreiben angelegt.
"""
import re
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path

TICKET_RE = re.compile(r"^[A-Z][A-Z0-9_]{1,19}-\d{1,9}$")


class LinkError(Exception):
    pass


def ref_of(project_id, branch):
    return "%d:%s" % (int(project_id), str(branch))


def norm_ticket(key):
    k = str(key or "").strip().upper()
    if not TICKET_RE.match(k):
        raise LinkError("«%s» ist kein Ticket-Key (erwartet zum Beispiel DLP-123)." % (key or "").strip()[:40])
    return k


# ---- KI-Konten: Abo-Limits mit Zeitfenster (z. B. 5 Stunden). Die Anbieter bieten dafür keine offizielle Abfrage; du trägst den Stand ein
AI_KINDS = ("claude", "chatgpt", "mistral", "local", "other")


def _num(v, name, lo=0.0, hi=1e9):
    try:
        x = float(v)
    except (TypeError, ValueError):
        raise LinkError("«%s» muss eine Zahl sein." % name)
    if not lo <= x <= hi:
        raise LinkError("«%s» muss zwischen %g und %g liegen." % (name, lo, hi))
    return x


def ai_view(row, now=None):
    now = now or time.time()
    win = row["window_hours"] * 3600
    running = row["window_start"] > 0 and now < row["window_start"] + win
    used = row["used"] if running else 0.0
    budget = row["budget"]
    left = max(budget - used, 0.0) if budget else None
    pct = min(100.0, 100.0 * used / budget) if budget else None
    state = "free" if not running else "ok"
    if budget and running:
        state = "empty" if used >= budget else ("low" if left <= 0.2 * budget else "ok")
    return {"id": row["id"], "name": row["name"], "kind": row["kind"], "window_hours": row["window_hours"], "budget": budget, "unit": row["unit"],
            "used": round(used, 2), "left": None if left is None else round(left, 2), "pct": None if pct is None else round(pct, 1),
            "running": running, "resets_at": row["window_start"] + win if running else 0, "secs_left": int(row["window_start"] + win - now) if running else 0,
            "state": state}


def _ai_roll(row, now):
    """Fenster abgelaufen: Zähler beginnt bei null."""
    if row["window_start"] > 0 and now >= row["window_start"] + row["window_hours"] * 3600:
        return 0.0, 0.0
    return row["used"], row["window_start"]


class _AiMixin:
    def ai_accounts(self):
        with self._conn() as c:
            return [] if c is None else [ai_view(r) for r in c.execute("select * from ai_accounts order by id")]

    def ai_save(self, ident, name, kind, window_hours, budget, unit):
        name = " ".join(str(name or "").split())
        if not name or len(name) > 40:
            raise LinkError("Der Name fehlt oder ist länger als 40 Zeichen.")
        if kind not in AI_KINDS:
            raise LinkError("Unbekannte Art.")
        wh = _num(window_hours, "Fenster (Stunden)", 0.1, 24 * 31)
        bud = _num(budget, "Budget", 0, 1e9)
        unit = " ".join(str(unit or "%").split())[:12] or "%"
        with self._conn(True) as c:
            try:
                if ident:
                    n = c.execute("update ai_accounts set name=?, kind=?, window_hours=?, budget=?, unit=? where id=?", (name, kind, wh, bud, unit, int(ident))).rowcount
                    if not n:
                        raise LinkError("Konto nicht gefunden.")
                    return int(ident)
                if c.execute("select count(*) from ai_accounts").fetchone()[0] >= 20:
                    raise LinkError("Höchstens 20 Konten.")
                return c.execute("insert into ai_accounts(name, kind, window_hours, budget, unit) values(?,?,?,?,?)", (name, kind, wh, bud, unit)).lastrowid
            except sqlite3.IntegrityError:
                raise LinkError("Ein Konto «%s» gibt es schon." % name)

    def ai_delete(self, ident):
        with self._conn(True) as c:
            if not c.execute("delete from ai_accounts where id=?", (int(ident),)).rowcount:
                raise LinkError("Konto nicht gefunden.")

    def ai_set(self, ident, used=None, resets_in_min=None, delta=None):
        """Stand eintragen: `used` (absolut) oder `delta` (dazu), `resets_in_min` = «Zurücksetzung in …» wie in der Anzeige des Anbieters."""
        now = time.time()
        with self._conn(True) as c:
            row = c.execute("select * from ai_accounts where id=?", (int(ident),)).fetchone()
            if not row:
                raise LinkError("Konto nicht gefunden.")
            cur, start = _ai_roll(row, now)
            if used is not None:
                cur = _num(used, "Verbraucht", 0, 1e9)
            if delta is not None:
                cur += _num(delta, "Schritt", -1e9, 1e9)
                cur = max(cur, 0.0)
            if resets_in_min is not None:
                m = _num(resets_in_min, "Zurücksetzung in (Minuten)", 0, row["window_hours"] * 60)
                start = now - (row["window_hours"] * 3600 - m * 60)
            elif start == 0:
                start = now   # das Fenster beginnt mit der ersten Nutzung
            c.execute("update ai_accounts set used=?, window_start=? where id=?", (cur, start, int(ident)))

    def ai_bump(self, kind="local", n=1):
        """Automatischer Zähler (lokales Modell): eigene Anfragen des Panels."""
        now = time.time()
        with self._conn(True) as c:
            for row in c.execute("select * from ai_accounts where kind=?", (kind,)).fetchall():
                cur, start = _ai_roll(row, now)
                c.execute("update ai_accounts set used=?, window_start=? where id=?", (cur + n, start or now, row["id"]))


# ---- Board: Workflow-Stufen pro Aufgabe. Nur lokal; nach Jira wird nichts geschrieben (kein Statuswechsel)
STAGES = ("idea", "planned", "impl", "review", "test", "tested", "done")
PROGRESS = ("impl", "review", "test")        # «in Arbeit»: erscheint im Jira-Panel
LOCAL_PREFIX = "LOC"                         # Aufgaben ohne Jira-Ticket heissen LOC-1, LOC-2 …


def is_local_key(key):
    return str(key).startswith(LOCAL_PREFIX + "-")


def is_ref_key(key):
    return bool(re.match(r"^\d+:.+", str(key)))


class _BoardMixin:
    def stages(self):
        with self._conn() as c:
            return {} if c is None else {r["key"]: {"stage": r["stage"], "updated": r["updated"]} for r in c.execute("select key, stage, updated from task_stage")}

    def tasks(self):
        with self._conn() as c:
            return [] if c is None else [{"key": "%s-%d" % (LOCAL_PREFIX, r["id"]), "title": r["title"]} for r in c.execute("select id, title from tasks order by id")]

    def staged_tickets(self):
        """Jira-Tickets, die einen eigenen Board-Status haben (müssen in Jira nachgeschlagen werden)."""
        return sorted(k for k in self.stages() if not is_local_key(k) and not is_ref_key(k))

    def _stage_key(self, c, key):
        key = str(key or "").strip()
        if is_ref_key(key):
            if len(key) > 300:
                raise LinkError("Ungültiger Branch-Verweis.")
            return key
        key = norm_ticket(key)
        if is_local_key(key) and not c.execute("select 1 from tasks where id=?", (int(key.split("-", 1)[1]),)).fetchone():
            raise LinkError("Aufgabe %s gibt es nicht." % key)
        return key

    @staticmethod
    def _check_stage(stage):
        if stage not in STAGES:
            raise LinkError("Unbekannte Stufe.")
        return stage

    def stage_set(self, key, stage):
        self._check_stage(stage)
        with self._conn(True) as c:
            key = self._stage_key(c, key)
            c.execute("insert into task_stage(key, stage, updated) values(?,?,?) on conflict(key) do update set stage=excluded.stage, updated=excluded.updated",
                      (key, stage, time.time()))
        return key

    def stage_clear(self, key):
        with self._conn(True) as c:
            return c.execute("delete from task_stage where key=?", (str(key),)).rowcount > 0

    def task_add(self, title, stage="planned"):
        title = " ".join(str(title or "").split())
        if not title or len(title) > 200:
            raise LinkError("Der Titel fehlt oder ist länger als 200 Zeichen.")
        self._check_stage(stage)
        with self._conn(True) as c:
            if c.execute("select count(*) from tasks").fetchone()[0] >= 500:
                raise LinkError("Höchstens 500 lokale Aufgaben.")
            tid = c.execute("insert into tasks(title, created) values(?,?)", (title, self._now())).lastrowid
            key = "%s-%d" % (LOCAL_PREFIX, tid)
            c.execute("insert into task_stage(key, stage, updated) values(?,?,?)", (key, stage, time.time()))
        return key

    def task_delete(self, key):
        key = norm_ticket(key)
        if not is_local_key(key):
            raise LinkError("Nur lokale Aufgaben (LOC-…) lassen sich löschen.")
        with self._conn(True) as c:
            if not c.execute("delete from tasks where id=?", (int(key.split("-", 1)[1]),)).rowcount:
                raise LinkError("Aufgabe %s gibt es nicht." % key)
            c.execute("delete from task_stage where key=?", (key,))
            c.execute("delete from links where ticket=?", (key,))
            c.execute("delete from pool_items where kind='ticket' and value=?", (key,))


class Store(_AiMixin, _BoardMixin):
    def __init__(self, path):
        self.path = Path(path)

    @contextmanager
    def _conn(self, write=False):
        if not write and not self.path.exists():
            yield None
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self.path))
        conn.row_factory = sqlite3.Row
        try:
            with conn:
                conn.execute("create table if not exists links(ref text primary key, ticket text not null, created text not null)")
                conn.execute("create table if not exists pools(id integer primary key autoincrement, name text not null unique, created text not null)")
                conn.execute("create table if not exists pool_items(pool_id integer not null, kind text not null, value text not null, created text not null,"
                             " primary key(pool_id, kind, value))")
                conn.execute("create table if not exists ai_accounts(id integer primary key autoincrement, name text not null unique, kind text not null,"
                             " window_hours real not null, budget real not null, unit text not null, used real not null default 0, window_start real not null default 0)")
                conn.execute("create table if not exists tasks(id integer primary key autoincrement, title text not null, created text not null)")
                conn.execute("create table if not exists task_stage(key text primary key, stage text not null, updated real not null)")
                yield conn
        finally:
            conn.close()

    @staticmethod
    def _now():
        return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime())

    # ---- Verknüpfungen
    def links(self):
        with self._conn() as c:
            return {} if c is None else {r["ref"]: r["ticket"] for r in c.execute("select ref, ticket from links")}

    def link(self, project_id, branch, ticket):
        if not str(branch or "").strip():
            raise LinkError("Branch fehlt.")
        t = norm_ticket(ticket)
        with self._conn(True) as c:
            c.execute("insert into links(ref, ticket, created) values(?,?,?) on conflict(ref) do update set ticket=excluded.ticket",
                      (ref_of(project_id, branch), t, self._now()))
        return t

    def unlink(self, project_id, branch):
        with self._conn(True) as c:
            return c.execute("delete from links where ref=?", (ref_of(project_id, branch),)).rowcount > 0

    # ---- Pools
    def pools(self):
        with self._conn() as c:
            if c is None:
                return []
            out = []
            for p in c.execute("select id, name from pools order by id"):
                items = [dict(r) for r in c.execute("select kind, value from pool_items where pool_id=? order by created, rowid", (p["id"],))]
                out.append({"id": p["id"], "name": p["name"], "items": items})
            return out

    def pool_tickets(self):
        return sorted({i["value"] for p in self.pools() for i in p["items"] if i["kind"] == "ticket"})

    def add_pool(self, name):
        name = " ".join(str(name or "").split())
        if not name or len(name) > 60:
            raise LinkError("Der Name fehlt oder ist länger als 60 Zeichen.")
        with self._conn(True) as c:
            if c.execute("select count(*) from pools").fetchone()[0] >= 30:
                raise LinkError("Höchstens 30 Pools.")
            try:
                cur = c.execute("insert into pools(name, created) values(?,?)", (name, self._now()))
            except sqlite3.IntegrityError:
                raise LinkError("Einen Pool «%s» gibt es schon." % name)
            return cur.lastrowid

    def rename_pool(self, pool_id, name):
        name = " ".join(str(name or "").split())
        if not name or len(name) > 60:
            raise LinkError("Der Name fehlt oder ist länger als 60 Zeichen.")
        with self._conn(True) as c:
            try:
                n = c.execute("update pools set name=? where id=?", (name, int(pool_id))).rowcount
            except sqlite3.IntegrityError:
                raise LinkError("Einen Pool «%s» gibt es schon." % name)
        if not n:
            raise LinkError("Pool nicht gefunden.")

    def delete_pool(self, pool_id):
        with self._conn(True) as c:
            c.execute("delete from pool_items where pool_id=?", (int(pool_id),))
            if not c.execute("delete from pools where id=?", (int(pool_id),)).rowcount:
                raise LinkError("Pool nicht gefunden.")

    def _check_pool(self, c, pool_id):
        if not c.execute("select 1 from pools where id=?", (int(pool_id),)).fetchone():
            raise LinkError("Pool nicht gefunden.")

    def add_item(self, pool_id, kind, value):
        if kind == "ticket":
            value = norm_ticket(value)
        elif kind == "ref":
            value = str(value or "")
            if not re.match(r"^\d+:.+", value) or len(value) > 300:
                raise LinkError("Ungültiger Branch-Verweis.")
        else:
            raise LinkError("Unbekannte Art.")
        with self._conn(True) as c:
            self._check_pool(c, pool_id)
            if c.execute("select count(*) from pool_items where pool_id=?", (int(pool_id),)).fetchone()[0] >= 200:
                raise LinkError("Ein Pool fasst höchstens 200 Einträge.")
            c.execute("insert or ignore into pool_items(pool_id, kind, value, created) values(?,?,?,?)", (int(pool_id), kind, value, self._now()))
        return value

    def remove_item(self, pool_id, kind, value):
        with self._conn(True) as c:
            return c.execute("delete from pool_items where pool_id=? and kind=? and value=?", (int(pool_id), kind, str(value))).rowcount > 0
