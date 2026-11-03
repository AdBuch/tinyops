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


class Store:
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
