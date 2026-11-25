"""Lokale Zuordnungen, die nur im Panel gelten (nichts davon wird nach Jira oder GitLab geschrieben):

* Verknüpfungen: ein Branch/MR gehört zu einem Ticket, auch wenn der Name nicht passt (Sammel-Tickets für Bugs).
  Sie überstimmen die automatische Erkennung aus dem Branch-Namen und lassen sich wieder lösen.
* Pools: frei benannte Arbeitsbereiche («Agenten-VM», «Produkt X») mit Tickets und Branches/MRs, die ausserhalb von
  Sprint und Story-Limit stehen.

Die Datei liegt neben der Ideenbox (tinyops.db) und wird erst beim ersten Schreiben angelegt.
"""
import json
import re
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path

import dbschema

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

    def pools_of(self, key):
        """Kategorien (Pools) einer Aufgabe oder eines Branches."""
        with self._conn() as c:
            if c is None:
                return []
            return [r["pool_id"] for r in c.execute("select pool_id from pool_items where value=? and kind in ('ticket','ref')", (str(key),))]

    def stage_set(self, key, stage):
        self._check_stage(stage)
        with self._conn(True) as c:
            key = self._stage_key(c, key)
            if is_local_key(key) and stage != "idea" and not c.execute("select 1 from pool_items where kind='ticket' and value=?", (key,)).fetchone():
                raise LinkError("%s braucht zuerst eine Kategorie (Pool), sonst bleibt die Aufgabe im Ideenpool." % key)
            c.execute("insert into task_stage(key, stage, updated) values(?,?,?) on conflict(key) do update set stage=excluded.stage, updated=excluded.updated",
                      (key, stage, time.time()))
        return key

    def stage_clear(self, key):
        with self._conn(True) as c:
            return c.execute("delete from task_stage where key=?", (str(key),)).rowcount > 0

    def task_add(self, title, stage="idea", pool_id=None):
        title = " ".join(str(title or "").split())
        if not title or len(title) > 200:
            raise LinkError("Der Titel fehlt oder ist länger als 200 Zeichen.")
        self._check_stage(stage)
        if stage != "idea" and not pool_id:
            raise LinkError("Ab «Geplant» braucht eine Aufgabe ohne Jira eine Kategorie (Pool). Ohne Kategorie bleibt sie im Ideenpool.")
        with self._conn(True) as c:
            if pool_id:
                self._check_pool(c, pool_id)
            if c.execute("select count(*) from tasks").fetchone()[0] >= 500:
                raise LinkError("Höchstens 500 lokale Aufgaben.")
            tid = c.execute("insert into tasks(title, created) values(?,?)", (title, self._now())).lastrowid
            key = "%s-%d" % (LOCAL_PREFIX, tid)
            c.execute("insert into task_stage(key, stage, updated) values(?,?,?)", (key, stage, time.time()))
            if pool_id:
                c.execute("insert or ignore into pool_items(pool_id, kind, value, created) values(?,?,?,?)", (int(pool_id), "ticket", key, self._now()))
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


class _SnapMixin:
    """Lokaler Verlauf der Sonar-Gate-Werte je MR/Branch. Das ist der Ersatz, wenn Sonar für einen MR keinen Verlauf liefert, und er entsteht ohne
    zusätzliche Anfrage aus den Werten, die der Abgleich ohnehin bekommt. Gespeichert wird nur bei Änderung."""
    def snap_add(self, scope, values, ts=None):
        ts = ts or time.time()
        if not values:
            return False
        blob = json.dumps(values, sort_keys=True)
        with self._conn(True) as c:
            last = c.execute("select vals from sonar_snap where scope=? order by ts desc limit 1", (scope,)).fetchone()
            if last and last["vals"] == blob:
                return False
            c.execute("insert into sonar_snap(scope, ts, vals) values(?,?,?)", (scope, ts, blob))
            c.execute("delete from sonar_snap where scope=? and ts not in (select ts from sonar_snap where scope=? order by ts desc limit 100)", (scope, scope))
            c.execute("delete from sonar_snap where ts < ?", (ts - 120 * 86400,))
        return True

    def snap_rows(self, scope, limit=60):
        with self._conn() as c:
            if c is None:
                return []
            rows = c.execute("select ts, vals from sonar_snap where scope=? order by ts desc limit ?", (scope, limit)).fetchall()
        return [(r["ts"], json.loads(r["vals"])) for r in reversed(rows)]


class _AgentMixin:
    """Zuweisungen und Läufe von Coding-Agenten an Tickets (siehe agents.py). Der Prompt wird mitgespeichert, damit man sieht, was beauftragt wurde."""
    _COLS = ("agent", "ticket", "project_id", "branch", "title", "status", "workdir", "prompt", "note", "exit_code", "created", "started", "finished",
             "mode", "out_branch", "wt", "taken", "question", "answered", "qa", "summary", "checks", "ack", "criteria", "ak", "result",
             "phase", "parent", "gate", "gate_note", "msteps", "mchecks", "renv", "session", "resume_of", "next_run", "ask", "reply", "fresh", "mr", "findings")

    def agent_run_add(self, agent, ticket, project_id, branch, title):
        with self._conn(True) as c:
            if c.execute("select count(*) from agent_runs").fetchone()[0] >= 2000:
                c.execute("delete from agent_runs where status not in ('zugewiesen','l\u00e4uft') and id in (select id from agent_runs order by id limit 500)")
            cur = c.execute("insert into agent_runs(agent, ticket, project_id, branch, title, status, created) values(?,?,?,?,?,'zugewiesen',?)",
                            (agent, ticket, project_id, branch, title, time.time()))
            return cur.lastrowid

    def agent_run(self, rid):
        with self._conn() as c:
            if c is None:
                return None
            r = c.execute("select * from agent_runs where id=?", (rid,)).fetchone()
            return dict(r) if r else None

    def agent_runs(self, ticket=None, status=None, limit=500):
        q, a = "select * from agent_runs", []
        w = []
        if ticket is not None:
            w.append("ticket=?")
            a.append(ticket)
        if status is not None:
            w.append("status=?")
            a.append(status)
        if w:
            q += " where " + " and ".join(w)
        q += " order by id desc limit ?"
        a.append(limit)
        with self._conn() as c:
            return [] if c is None else [dict(r) for r in c.execute(q, a)]

    def agent_run_update(self, rid, **kw):
        bad = [k for k in kw if k not in self._COLS]
        if bad:
            raise ValueError("unbekannte Spalte: %s" % bad)
        if not kw:
            return
        with self._conn(True) as c:
            c.execute("update agent_runs set %s where id=?" % ", ".join("%s=?" % k for k in kw), list(kw.values()) + [rid])

    def agent_run_delete(self, rid):
        with self._conn(True) as c:
            c.execute("delete from agent_runs where id=?", (rid,))

    def agent_run_drop_ticket(self, ticket):
        with self._conn(True) as c:
            c.execute("delete from agent_runs where ticket=? and status not in ('l\u00e4uft')", (ticket,))


class _FlowMixin:
    """Fortschritt je Vorhaben (höchste je erreichte Station), Erfolge für den Spielstand und Teilschritte (Checkliste)."""
    def flow_states(self):
        with self._conn() as c:
            return {} if c is None else {r["key"]: dict(r) for r in c.execute("select * from flow_state")}

    def flow_record(self, rows, now=None):
        """rows: (id, key, title, phase). Neue Karten zählen nicht; Punkte nur für eine Station, die noch nie erreicht wurde."""
        now = now or time.time()
        events = []
        with self._conn(True) as c:
            seen = {r["key"]: dict(r) for r in c.execute("select * from flow_state")}
            for cid, key, title, phase in rows:
                s = seen.get(cid)
                if s is None:
                    c.execute("insert into flow_state(key, phase, max_phase, ts) values(?,?,?,?)", (cid, phase, phase, now))
                    continue
                if phase > s["max_phase"]:
                    xp = 10 * (phase - s["max_phase"]) + (30 if phase == 7 else 0)
                    c.execute("insert into flow_events(ref, key, title, kind, phase, xp, text, ts) values(?,?,?,?,?,?,?,?)",
                              ("", key or cid, title, "phase", phase, xp, "", now))
                    events.append((cid, phase, xp))
                    c.execute("update flow_state set phase=?, max_phase=?, ts=? where key=?", (phase, phase, now, cid))
                elif phase != s["phase"]:
                    c.execute("update flow_state set phase=?, ts=? where key=?", (phase, now, cid))
            c.execute("delete from flow_events where ts < ?", (now - 400 * 86400,))
        return events

    def flow_events_between(self, a, b):
        with self._conn() as c:
            if c is None:
                return []
            return [dict(r) for r in c.execute("select * from flow_events where ts >= ? and ts < ? order by ts", (a, b))]

    def flow_event_once(self, ref, key, title, kind, phase, xp, text, now=None):
        with self._conn(True) as c:
            if c.execute("select 1 from flow_events where ref=?", (ref,)).fetchone():
                return False
            c.execute("insert into flow_events(ref, key, title, kind, phase, xp, text, ts) values(?,?,?,?,?,?,?,?)",
                      (ref, key, title, kind, phase, xp, text, now or time.time()))
            return True

    def flow_stats(self, goal=3, now=None):
        now = now or time.time()
        day = lambda ts: time.strftime("%Y-%m-%d", time.localtime(ts))
        with self._conn() as c:
            rows = [] if c is None else [dict(r) for r in c.execute("select * from flow_events order by id desc limit 5000")]
        today = day(now)
        t_rows = [r for r in rows if day(r["ts"]) == today]
        days = {day(r["ts"]) for r in rows}
        streak, d = 0, now
        if today not in days:
            d -= 86400          # heute noch nichts: die Serie zählt bis gestern und reisst erst morgen
        while day(d) in days:
            streak += 1
            d -= 86400
        week = []
        for i in range(6, -1, -1):
            ds = day(now - i * 86400)
            week.append({"day": ds, "n": sum(1 for r in rows if day(r["ts"]) == ds)})
        total = sum(r["xp"] for r in rows)
        steps = len(t_rows)          # jeder Haken zählt: kleine Schritte sollen sich lohnen
        return {"today_xp": sum(r["xp"] for r in t_rows), "today_steps": steps, "goal": goal, "goal_met": steps >= goal,
                "streak": streak, "week": week, "total_xp": total, "level": 1 + total // 200, "level_xp": total % 200, "level_size": 200,
                "last_id": rows[0]["id"] if rows else 0,
                "recent": [{"id": r["id"], "key": r["key"], "title": r["title"], "kind": r["kind"], "phase": r["phase"], "xp": r["xp"],
                            "text": r["text"], "ts": r["ts"]} for r in rows[:8]]}

    # ---- Teilschritte
    def checklists(self):
        with self._conn() as c:
            if c is None:
                return {}
            out = {}
            for r in c.execute("select * from checklist order by key, pos, id"):
                out.setdefault(r["key"], []).append(dict(r))
            return out

    def check_add(self, key, text):
        text = " ".join(str(text or "").split())
        if not text or len(text) > 200:
            raise LinkError("Der Teilschritt fehlt oder ist länger als 200 Zeichen.")
        if not key or len(key) > 200:
            raise LinkError("Die Karte fehlt.")
        with self._conn(True) as c:
            n = c.execute("select count(*), coalesce(max(pos), 0) from checklist where key=?", (key,)).fetchone()
            if n[0] >= 30:
                raise LinkError("Höchstens 30 Teilschritte je Karte. Teil die Aufgabe lieber auf.")
            return c.execute("insert into checklist(key, text, done, pos, created) values(?,?,0,?,?)", (key, text, n[1] + 1, time.time())).lastrowid

    def check_toggle(self, cid, done=None):
        with self._conn(True) as c:
            r = c.execute("select * from checklist where id=?", (cid,)).fetchone()
            if not r:
                raise LinkError("Diesen Teilschritt gibt es nicht (mehr).")
            new = (not r["done"]) if done is None else bool(done)
            c.execute("update checklist set done=?, done_ts=? where id=?", (int(new), time.time() if new else None, cid))
            r = dict(r)
            r["done"] = int(new)
            return r

    def check_delete(self, cid):
        with self._conn(True) as c:
            c.execute("delete from checklist where id=?", (cid,))


class _AcceptMixin:
    """Manuelle Abnahme je Vorhaben und MR/PR, gebunden an den Head-Commit zum Zeitpunkt der Abnahme."""
    def accept_set(self, key, refs, note="", env="", now=None):
        """refs: [(ref, sha)]. Überschreibt frühere Abnahmen derselben MRs."""
        now = now or time.time()
        note = " ".join(str(note or "").split())[:500]
        env = " ".join(str(env or "").split())[:120]
        with self._conn(True) as c:
            for ref, sha in refs:
                c.execute("insert into acceptance(key, ref, sha, ts, note, env) values(?,?,?,?,?,?) on conflict(key, ref) do update set "
                          "sha=excluded.sha, ts=excluded.ts, note=excluded.note, env=excluded.env", (key, ref, sha or "", now, note, env))
        return len(refs)

    def acceptances(self):
        with self._conn() as c:
            if c is None:
                return {}
            out = {}
            for r in c.execute("select * from acceptance"):
                out.setdefault(r["key"], {})[r["ref"]] = dict(r)
            return out


class _PinMixin:
    """Höchstens ein angehefteter Fokus."""
    def pin_get(self):
        with self._conn() as c:
            if c is None:
                return None
            r = c.execute("select key from pin where id=1").fetchone()
            return r["key"] if r else None

    def pin_set(self, key):
        with self._conn(True) as c:
            if key:
                c.execute("insert into pin(id, key, ts) values(1,?,?) on conflict(id) do update set key=excluded.key, ts=excluded.ts", (str(key)[:300], time.time()))
            else:
                c.execute("delete from pin where id=1")


class _IdeMixin:
    """IntelliJ-Worktrees auf dem Head-Commit eines MR (0.20). Je MR höchstens einer."""
    def ide_set(self, ref, host, project_id, iid, sha, path, repo):
        with self._conn(True) as c:
            c.execute("insert into ide_wt(ref, host, project_id, iid, sha, path, repo, ts) values(?,?,?,?,?,?,?,?) on conflict(ref) do update set "
                      "host=excluded.host, project_id=excluded.project_id, iid=excluded.iid, sha=excluded.sha, path=excluded.path, repo=excluded.repo, ts=excluded.ts",
                      (ref, host, int(project_id), int(iid), sha, path, repo, time.time()))

    def renv_set(self, key, st):
        with self._conn(True) as c:
            c.execute("insert into review_env(key, state, ts) values(?,?,?) on conflict(key) do update set state=excluded.state, ts=excluded.ts",
                      (key, json.dumps(st, ensure_ascii=False), time.time()))

    def device_add(self, name, h, now):
        with self._conn(True) as c:
            cur = c.execute("insert into devices(name, hash, created, last_seen) values(?,?,?,?)", (name, h, now, now))
            return {"id": cur.lastrowid, "name": name, "created": now}

    def device_get(self, did):
        with self._conn() as c:
            if c is None:
                return None
            r = c.execute("select id, name, hash, created, last_seen, revoked from devices where id=?", (did,)).fetchone()
            return dict(zip(("id", "name", "hash", "created", "last_seen", "revoked"), r)) if r else None

    def device_seen(self, did, now):
        with self._conn(True) as c:
            c.execute("update devices set last_seen=? where id=?", (now, did))

    def device_list(self):
        with self._conn() as c:
            if c is None:
                return []
            return [dict(zip(("id", "name", "created", "last_seen"), r)) for r in
                    c.execute("select id, name, created, last_seen from devices where revoked=0 order by created desc")]

    def device_revoke(self, did):
        with self._conn(True) as c:
            return c.execute("update devices set revoked=1 where id=? and revoked=0", (did,)).rowcount > 0

    def hd_jira_set(self, hd_key, jira_key):
        with self._conn(True) as c:
            c.execute("insert into hd_jira(hd_key, jira_key, ts) values(?,?,?) on conflict(hd_key) do update set jira_key=excluded.jira_key, ts=excluded.ts",
                      (hd_key, jira_key, time.time()))

    def hd_jira_map(self):
        with self._conn() as c:
            if c is None:
                return {}
            return {r[0]: r[1] for r in c.execute("select hd_key, jira_key from hd_jira")}

    def renv_get(self, key):
        with self._conn() as c:
            if c is None:
                return None
            r = c.execute("select state from review_env where key=?", (key,)).fetchone()
            try:
                return json.loads(r["state"]) if r else None
            except ValueError:
                return None

    def ide_get(self, ref):
        with self._conn() as c:
            if c is None:
                return None
            r = c.execute("select * from ide_wt where ref=?", (ref,)).fetchone()
            return dict(r) if r else None

    def ide_all(self):
        with self._conn() as c:
            if c is None:
                return {}
            return {r["ref"]: dict(r) for r in c.execute("select * from ide_wt")}

    def ide_delete(self, ref):
        with self._conn(True) as c:
            c.execute("delete from ide_wt where ref=?", (ref,))


class _HdMixin:
    """Gesehene Tickets der Helpdesk-Queue (0.23)."""
    def hd_seen(self):
        with self._conn() as c:
            if c is None:
                return set()
            return {r["key"] for r in c.execute("select key from hd_seen")}

    def hd_seen_ts(self):
        with self._conn() as c:
            if c is None:
                return {}
            return {r["key"]: r["ts"] for r in c.execute("select key, ts from hd_seen")}

    def hd_seen_add(self, keys):
        """Merkt «gesehen» mit Zeit. Ein erneutes Sehen setzt die Zeit neu (für beobachtete Tickets: geändert seit dem letzten Blick)."""
        if not keys:
            return
        with self._conn(True) as c:
            c.executemany("insert into hd_seen(key, ts) values(?,?) on conflict(key) do update set ts = excluded.ts", [(k, time.time()) for k in keys])


class _TestMixin:
    """0.42: Prüfliste je Ticket. Stand je Punkt (ok, fail, offen) mit Notiz; eigene Punkte mit source «du»."""
    def tcheck_list(self, key):
        with self._conn() as c:
            return [] if c is None else [dict(r) for r in c.execute("select * from ticket_checks where key=? order by pos, ts", (key,))]

    def tcheck_set(self, key, iid, text, source, state=None, note=None, sha="", pos=None):
        with self._conn(True) as c:
            row = c.execute("select * from ticket_checks where key=? and id=?", (key, iid)).fetchone()
            if row is None:
                n = c.execute("select coalesce(max(pos), 0) + 1 from ticket_checks where key=?", (key,)).fetchone()[0]
                c.execute("insert into ticket_checks(key, id, text, source, state, note, sha, ts, pos) values(?,?,?,?,?,?,?,?,?)",
                          (key, iid, text, source, state or "", note or "", sha or "", time.time(), pos if pos is not None else n))
            else:
                c.execute("update ticket_checks set state=?, note=?, sha=?, ts=? where key=? and id=?",
                          (row["state"] if state is None else state, row["note"] if note is None else note, sha or row["sha"], time.time(), key, iid))

    def tcheck_delete(self, key, iid):
        with self._conn(True) as c:
            return c.execute("delete from ticket_checks where key=? and id=? and source='du'", (key, iid)).rowcount > 0


class _DraftMixin:
    """0.42 (E14): welche Entwurfs-Kommentare in GitLab tinyops selbst angelegt hat. Nur diese ändert oder löscht es."""
    def drafts_of(self, project_id, iid):
        with self._conn() as c:
            return [] if c is None else [dict(r) for r in c.execute("select * from review_drafts where project_id=? and iid=? order by draft_id", (int(project_id), int(iid)))]

    def draft_add(self, project_id, iid, draft_id, run, sha):
        with self._conn(True) as c:
            c.execute("insert or replace into review_drafts(project_id, iid, draft_id, run, sha, ts) values(?,?,?,?,?,?)",
                      (int(project_id), int(iid), int(draft_id), int(run or 0), sha or "", time.time()))

    def draft_forget(self, project_id, iid, draft_id):
        with self._conn(True) as c:
            c.execute("delete from review_drafts where project_id=? and iid=? and draft_id=?", (int(project_id), int(iid), int(draft_id)))


class Store(_AiMixin, _BoardMixin, _SnapMixin, _AgentMixin, _FlowMixin, _AcceptMixin, _PinMixin, _IdeMixin, _HdMixin, _TestMixin, _DraftMixin):
    def __init__(self, path):
        self.path = Path(path)

    @contextmanager
    def _conn(self, write=False):
        if not write and not self.path.exists():
            yield None
            return
        dbschema.ensure(self.path)                  # 0.45: Schema an einer Stelle, einmal je Prozess
        conn = sqlite3.connect(str(self.path))
        conn.row_factory = sqlite3.Row
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    # ---- Tickets zu Tasks gruppieren (0.30): head «» = eigenständig, nie automatisch gruppieren
    def groups(self):
        with self._conn() as c:
            return {} if c is None else {r["key"]: r["head"] for r in c.execute("select key, head from ticket_group")}

    def group_set(self, key, head):
        with self._conn(True) as c:
            if head is None:
                c.execute("delete from ticket_group where key=?", (key,))
            else:
                c.execute("insert into ticket_group(key, head, ts) values(?,?,?) on conflict(key) do update set head=excluded.head, ts=excluded.ts",
                          (key, head, time.time()))

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
