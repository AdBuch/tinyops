"""Ideen festhalten und ähnliche finden (0.37 aus server.py gelöst)."""
import json
import re
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from common import UserError, age_days
import dbschema


class Ideas:
    def __init__(self, path, cap, expire_days):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.path = str(path)
        self.cap = cap
        self.expire_days = expire_days
        dbschema.ensure(self.path)                  # 0.45: Tabelle in dbschema

    @contextmanager
    def _conn(self):
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def list(self):
        with self._conn() as c:
            rows = [dict(r) for r in c.execute("select * from ideas order by id desc")]
        for r in rows:
            r["age_days"] = age_days(r["created"])
            r["expired"] = r["status"] == "neu" and r["age_days"] >= self.expire_days
            try:
                r["assessment"] = json.loads(r.get("assessment") or "null")
            except ValueError:
                r["assessment"] = None
            try:
                r["draft"] = json.loads(r.get("draft") or "null")
            except ValueError:
                r["draft"] = None
        return rows

    def get(self, idea_id):
        return next((i for i in self.list() if i["id"] == int(idea_id)), None)

    def set_field(self, idea_id, **kw):
        bad = set(kw) - {"assessment", "ticket", "draft", "status"}
        if bad:
            raise UserError("Unbekannte Felder.")
        vals = [json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else ("" if v is None else str(v)) for v in kw.values()]
        with self._conn() as c:
            c.execute("update ideas set %s where id=?" % ", ".join("%s=?" % k for k in kw), vals + [int(idea_id)])

    def open_count(self):
        return sum(1 for r in self.list() if r["status"] in ("neu", "geparkt") and not r["expired"])

    def add(self, text):
        text = (text or "").strip()
        if not text:
            raise UserError("Leere Idee.")
        if len(text) > 2000:
            raise UserError("Idee ist zu lang (max. 2000 Zeichen).")
        if self.open_count() >= self.cap:
            raise UserError("Ideenbox voll (%d). Erst triagieren oder verwerfen." % self.cap)
        now = datetime.now(timezone.utc).isoformat()
        with self._conn() as c:
            cur = c.execute("insert into ideas(text, created) values(?, ?)", (text, now))
            return cur.lastrowid

    def set_status(self, idea_id, status):
        if status not in ("neu", "geparkt", "verworfen", "erledigt"):
            raise UserError("Unbekannter Status.")
        with self._conn() as c:
            c.execute("update ideas set status=? where id=?", (status, idea_id))

    def delete(self, idea_id):
        with self._conn() as c:
            c.execute("delete from ideas where id=?", (idea_id,))


STOPWORDS = set("und oder der die das ein eine einen dem den des mit für von zu im in am an auf aus bei ist sind wird werden nicht noch auch nur als wie "
                "mehr neue neuer neues soll sollte kann können machen einbauen bauen the and for with".split())


def _words(t):
    return {w for w in re.findall(r"[a-zäöüß0-9]{3,}", (t or "").lower()) if w not in STOPWORDS}


def similar(text, candidates, threshold=0.34, limit=5):
    """Ähnliche Ideen oder Vorhaben, ohne Modell: Anteil gemeinsamer Wörter (Jaccard). candidates: [(id, text)]."""
    a = _words(text)
    out = []
    if not a:
        return out
    for cid, t in candidates:
        b = _words(t)
        if not b:
            continue
        score = len(a & b) / float(len(a | b))
        if score >= threshold:
            out.append({"id": cid, "label": " ".join(str(t).split())[:120], "score": round(score, 2)})
    return sorted(out, key=lambda x: -x["score"])[:limit]
