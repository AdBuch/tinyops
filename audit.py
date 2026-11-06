"""Audit-Trail: wer hat wann was ausgelöst, nur anhängend und mit Hash-Kette.

* Jeder Eintrag enthält den Hash des vorherigen. Ändert jemand eine Zeile direkt in der Datenbank, passt die Kette nicht mehr, und
  `python3 server.py --verify-audit` (oder «Kette prüfen» im Log) zeigt den ersten kaputten Eintrag.
* UPDATE und DELETE auf der Tabelle verhindern Trigger in SQLite. Wer die Datei selbst bearbeitet, kann das umgehen. Darum gibt es die Kette:
  Sie macht Änderungen sichtbar, verhindert sie aber nicht. Wer die ganze Kette neu berechnet, fällt nur auf, wenn der letzte Hash
  ausserhalb aufbewahrt wurde (Export oder `--verify-audit` zeigt ihn). Die Kette ist ein Manipulationshinweis, kein Beweis gegen Angreifer mit Schreibzugriff.
* Keine Secrets: Schlüssel mit token/password/secret im Namen fallen weg, Texte laufen durch das Schwärzen. Prompts stehen nur als Hash drin.
"""
import hashlib
import json
import re
import sqlite3
import threading
import time
import uuid
from pathlib import Path

import secretstore as store
import tlog

log = tlog.get("audit")
SECRETISH = re.compile(r"token|passw|secret|credential|authorization", re.I)

LABELS = {
    "jira.create": "Jira-Ticket angelegt",
    "board.stage": "Station gesetzt", "board.add": "Aufgabe angelegt", "board.remove": "Aufgabe gelöscht oder Station zurückgesetzt",
    "board.plan_idea": "Idee eingeplant", "board.assign": "In Kategorie gelegt", "board.unassign": "Aus Kategorie genommen",
    "pool.create": "Kategorie angelegt", "pool.rename": "Kategorie umbenannt", "pool.delete": "Kategorie gelöscht",
    "link.set": "Branch mit Ticket verknüpft", "link.delete": "Verknüpfung gelöst",
    "flow.accept": "Abgenommen", "flow.complete": "Schritt erledigt", "flow.tiny": "tiny-Ticket angelegt", "flow.pin": "Fokus geändert",
    "agent.assign": "Agent zugewiesen", "agent.start": "Agent gestartet", "agent.stop": "Agent gestoppt",
    "agent.expire": "Agent nach Zeitlimit beendet", "agent.finish": "Agent fertig", "agent.remove": "Agentenlauf entfernt",
    "agent.question": "Agent fragt", "agent.answer": "Agent geantwortet", "review.export": "Review-Punkte exportiert",
        "agent.takeover": "Agenten-Ergebnis übernommen", "agent.retention": "Alte Agenten-Logs gelöscht",
    "settings.save": "Einstellungen gespeichert", "testenv.deploy": "Testumgebung deployt", "testenv.teardown": "Testumgebung abgebaut",
    "time.pause": "Zeit pausiert", "time.gap": "Lücke entschieden", "time.add": "Zeit von Hand erfasst", "time.edit": "Zeitentwurf geändert",
    "time.discard": "Zeitentwurf verworfen", "time.merge": "Zeitentwürfe zusammengelegt", "time.confirm": "Zeitentwurf bestätigt",
    "time.send": "Zeit an MCP gesendet", "time.result": "Buchung vom MCP gemeldet",
    "qa.check": "Prüfpunkt abgehakt", "qa.selftest": "Selbsttest",
    "idea.assess": "Idee bewertet", "idea.ticket": "Ticket aus Idee", "ide.open": "In IntelliJ geöffnet", "ide.close": "IntelliJ-Worktree entfernt",
}


MAX_DETAIL = 4000


def clean(v, depth=0):
    """Details ohne Secrets und in vernünftiger Grösse."""
    if depth > 4:
        return "…"
    if isinstance(v, dict):
        return {str(k)[:40]: clean(x, depth + 1) for k, x in list(v.items())[:40] if not SECRETISH.search(str(k))}
    if isinstance(v, (list, tuple)):
        return [clean(x, depth + 1) for x in list(v)[:40]]
    if isinstance(v, str):
        return store.scrub_all(v)[:500]
    if isinstance(v, (int, float, bool)) or v is None:
        return v
    return store.scrub_all(str(v))[:200]


def prompt_hash(text):
    return "sha256:" + hashlib.sha256((text or "").encode("utf-8")).hexdigest()[:16]


def _digest(prev, ts, instance, actor, action, target, detail, ok):
    raw = "|".join([prev, "%.6f" % ts, instance, actor, action, target, detail, "1" if ok else "0"])
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class AuditLog:
    def __init__(self, path):
        self.path = Path(path)
        self.lock = threading.Lock()
        self._instance = None

    def _conn(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        c = sqlite3.connect(str(self.path), timeout=10, isolation_level=None)
        c.row_factory = sqlite3.Row
        c.execute("create table if not exists audit(id integer primary key autoincrement, ts real not null, instance text not null, actor text not null,"
                  " action text not null, target text not null default '', detail text not null default '{}', ok integer not null, prev text not null, hash text not null)")
        c.execute("create index if not exists audit_target on audit(target, id)")
        c.execute("create table if not exists audit_meta(key text primary key, value text not null)")
        c.execute("create trigger if not exists audit_no_update before update on audit begin select raise(abort, 'audit ist nur anhängend'); end")
        c.execute("create trigger if not exists audit_no_delete before delete on audit begin select raise(abort, 'audit ist nur anhängend'); end")
        return c

    def instance(self):
        """Kennung dieser tinyops-Instanz (für später: mehrere Instanzen, zentrale Datenbank)."""
        if self._instance:
            return self._instance
        c = self._conn()
        try:
            r = c.execute("select value from audit_meta where key='instance'").fetchone()
            if r:
                self._instance = r["value"]
            else:
                self._instance = uuid.uuid4().hex[:12]
                c.execute("insert or ignore into audit_meta(key, value) values('instance', ?)", (self._instance,))
                self._instance = c.execute("select value from audit_meta where key='instance'").fetchone()["value"]
        finally:
            c.close()
        return self._instance

    def add(self, action, target="", ok=True, actor="du", detail=None, now=None):
        inst = self.instance()
        det = clean(detail or {})
        d = json.dumps(det, ensure_ascii=False, sort_keys=True)
        if len(d) > MAX_DETAIL:      # nie abschneiden (kaputtes JSON), sondern auf kurze Felder reduzieren
            short = {k: v for k, v in det.items() if not isinstance(v, (list, dict)) and len(str(v)) <= 200}
            short["gekuerzt"] = sorted(k for k in det if k not in short)
            d = json.dumps(short, ensure_ascii=False, sort_keys=True)[:MAX_DETAIL]
            if not d.endswith("}"):
                d = json.dumps({"gekuerzt": True}, ensure_ascii=False)
        target = store.scrub_all(str(target or ""))[:300]
        ts = now or time.time()
        with self.lock:
            c = self._conn()
            try:
                c.execute("begin immediate")
                r = c.execute("select hash from audit order by id desc limit 1").fetchone()
                prev = r["hash"] if r else "0" * 64
                h = _digest(prev, ts, inst, actor, action, target, d, ok)
                cur = c.execute("insert into audit(ts, instance, actor, action, target, detail, ok, prev, hash) values(?,?,?,?,?,?,?,?,?)",
                                (ts, inst, actor, action, target, d, 1 if ok else 0, prev, h))
                c.execute("insert or replace into audit_meta(key, value) values('head', ?)", ("%d:%s" % (cur.lastrowid, h),))
                c.execute("commit")
                return cur.lastrowid
            except Exception:
                c.execute("rollback")
                raise
            finally:
                c.close()

    def rows(self, target=None, limit=200, action=None, since=None):
        """Neueste zuerst. target darf eine Liste sein (alle Kennungen eines Vorhabens: Ticket, Branches)."""
        c = self._conn()
        try:
            q, a, w = "select * from audit", [], []
            if target:
                ts_ = [str(t) for t in (target if isinstance(target, (list, tuple, set)) else [target]) if t][:50]
                w.append("target in (%s)" % ",".join("?" * len(ts_)))
                a.extend(ts_)
            if action:
                w.append("action=?")
                a.append(action)
            if since:
                w.append("ts>=?")
                a.append(since)
            if w:
                q += " where " + " and ".join(w)
            q += " order by id desc limit ?"
            a.append(int(limit))
            out = []
            for r in c.execute(q, a):
                x = dict(r)
                x["detail"] = json.loads(x["detail"] or "{}")
                x["ok"] = bool(x["ok"])
                x["label"] = LABELS.get(x["action"], x["action"])
                out.append(x)
            return out
        finally:
            c.close()

    def export(self):
        return list(reversed(self.rows(limit=10 ** 9)))

    def verify(self):
        """Prüft die ganze Kette. {ok, count, broken_at, reason}."""
        c = self._conn()
        try:
            prev, n = "0" * 64, 0
            for r in c.execute("select * from audit order by id"):
                n += 1
                if r["prev"] != prev:
                    return {"ok": False, "count": n, "broken_at": r["id"], "reason": "Verweis auf den vorherigen Eintrag passt nicht (Eintrag davor geändert oder gelöscht)."}
                h = _digest(r["prev"], r["ts"], r["instance"], r["actor"], r["action"], r["target"], r["detail"], bool(r["ok"]))
                if h != r["hash"]:
                    return {"ok": False, "count": n, "broken_at": r["id"], "reason": "Inhalt passt nicht zum gespeicherten Hash (Eintrag geändert)."}
                prev = r["hash"]
            head = c.execute("select value from audit_meta where key='head'").fetchone()
            if head and n:
                hid, _, hh = head["value"].partition(":")
                if hh != prev:
                    return {"ok": False, "count": n, "broken_at": int(hid) if hid.isdigit() else None,
                            "reason": "Die letzten Einträge fehlen (der zuletzt geschriebene Eintrag %s ist nicht mehr da)." % hid}
            elif head and not n:
                return {"ok": False, "count": 0, "broken_at": None, "reason": "Alle Einträge wurden gelöscht."}
            return {"ok": True, "count": n, "broken_at": None, "reason": "", "last_hash": prev}
        finally:
            c.close()
