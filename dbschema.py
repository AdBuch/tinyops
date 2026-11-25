"""Schema der Datenbank `tinyops.db` mit Version (0.45).

Bis 0.44 legte jedes Modul seine Tabellen selbst an, bei jeder Verbindung, und ergänzte fehlende Spalten mit `alter table`.
Jetzt steht das Schema an einer Stelle: nummerierte Migrationen, die Version in `pragma user_version`.
- `ensure(pfad)` bringt eine Datei einmal je Prozess auf den neuesten Stand, in einer Transaktion (`begin immediate`):
  zwei Threads oder zwei Prozesse beim ersten Start warten aufeinander, statt doppelt Spalten anzulegen.
- Migration 1 ist der Stand von 0.44. Sie legt nur an, was fehlt, und taugt deshalb für jede ältere Datenbank (getestet ab 0.25).
- Eine neue Tabelle oder Spalte ist eine neue Migration am Ende von MIGRATIONS. Bestehende Migrationen ändert man nicht.
- Migrationen fügen nur hinzu. Darum läuft nach einem Rückfall (start.py nimmt bei einem fehlgeschlagenen Selbsttest die vorige
  Version) auch eine ältere tinyops mit der neueren Datei; sie lässt Neues ungenutzt.
"""
import logging
import os
import sqlite3
import threading
from pathlib import Path

log = logging.getLogger("tinyops")


def _add_columns(c, table, cols):
    have = {r[1] for r in c.execute("pragma table_info(%s)" % table)}
    for col in cols:
        if col not in have:
            c.execute("alter table %s add column %s text not null default ''" % (table, col))


def _m1_baseline(c):
    """Stand 0.44: alle Tabellen von links, audit, timesheet, qa, ux und ideas, mit den Spalten, die bis dahin dazukamen."""
    # links.Store
    c.execute("create table if not exists links(ref text primary key, ticket text not null, created text not null)")
    c.execute("create table if not exists pools(id integer primary key autoincrement, name text not null unique, created text not null)")
    c.execute("create table if not exists pool_items(pool_id integer not null, kind text not null, value text not null, created text not null,"
              " primary key(pool_id, kind, value))")
    c.execute("create table if not exists ai_accounts(id integer primary key autoincrement, name text not null unique, kind text not null,"
              " window_hours real not null, budget real not null, unit text not null, used real not null default 0, window_start real not null default 0)")
    c.execute("create table if not exists tasks(id integer primary key autoincrement, title text not null, created text not null)")
    c.execute("create table if not exists task_stage(key text primary key, stage text not null, updated real not null)")
    c.execute("create table if not exists sonar_snap(scope text not null, ts real not null, vals text not null)")
    c.execute("create index if not exists sonar_snap_scope on sonar_snap(scope, ts)")
    c.execute("create table if not exists agent_runs(id integer primary key autoincrement, agent text not null, ticket text not null, project_id integer,"
              " branch text not null default '', title text not null default '', status text not null, workdir text not null default '',"
              " prompt text not null default '', note text not null default '', exit_code integer, created real not null,"
              " started real, finished real)")
    c.execute("create index if not exists agent_runs_ticket on agent_runs(ticket)")
    _add_columns(c, "agent_runs", (
        "mode", "out_branch", "wt", "taken",                                   # 0.16: Isolation je Lauf
        "question", "answered", "qa", "summary", "checks", "ack",              # 0.18: Rückfragen und Bericht
        "criteria", "ak", "result",                                            # 0.26: Akzeptanzkriterien und Änderungen je Lauf
        "phase", "parent", "gate", "gate_note", "msteps", "mchecks", "renv",   # 0.31: Zyklus, Freigaben, manuelle Prüfpunkte
        "session", "resume_of", "next_run", "ask", "reply", "fresh",           # 0.40: Sitzung fortsetzen, Gespräch
        "mr", "findings"))                                                     # 0.42: Review eines MR, Befunde mit Datei und Zeile
    c.execute("create table if not exists flow_state(key text primary key, phase integer not null, max_phase integer not null, ts real not null)")
    c.execute("create table if not exists flow_events(id integer primary key autoincrement, ref text not null default '', key text not null,"
              " title text not null default '', kind text not null, phase integer not null, xp integer not null, text text not null default '', ts real not null)")
    c.execute("create index if not exists flow_events_ref on flow_events(ref)")
    c.execute("create table if not exists acceptance(key text not null, ref text not null, sha text not null, ts real not null,"
              " note text not null default '', env text not null default '', primary key(key, ref))")
    c.execute("create table if not exists pin(id integer primary key check (id = 1), key text not null, ts real not null)")
    c.execute("create table if not exists hd_seen(key text primary key, ts real not null)")
    c.execute("create table if not exists ide_wt(ref text primary key, host text not null, project_id integer not null, iid integer not null,"
              " sha text not null, path text not null, repo text not null, ts real not null)")
    c.execute("create table if not exists review_env(key text primary key, state text not null, ts real not null)")          # 0.34
    c.execute("create table if not exists hd_jira(hd_key text primary key, jira_key text not null, ts real not null)")       # 0.36
    c.execute("create table if not exists devices(id integer primary key autoincrement, name text not null, hash text not null, "
              "created real not null, last_seen real, revoked integer not null default 0)")                                  # 0.36
    c.execute("create table if not exists checklist(id integer primary key autoincrement, key text not null, text text not null,"
              " done integer not null default 0, pos integer not null, created real not null, done_ts real)")
    c.execute("create table if not exists ticket_group(key text primary key, head text not null, ts real not null)")         # 0.30
    c.execute("create table if not exists review_drafts(project_id integer not null, iid integer not null, draft_id integer not null,"
              " run integer not null default 0, sha text not null default '', ts real not null, primary key(project_id, iid, draft_id))")
    c.execute("create table if not exists ticket_checks(key text not null, id text not null, text text not null, source text not null,"
              " state text not null default '', note text not null default '', sha text not null default '', ts real not null,"
              " pos integer not null default 0, primary key(key, id))")                                                         # 0.42
    # audit.AuditLog: nur anhängend
    c.execute("create table if not exists audit(id integer primary key autoincrement, ts real not null, instance text not null, actor text not null,"
              " action text not null, target text not null default '', detail text not null default '{}', ok integer not null, prev text not null, hash text not null)")
    c.execute("create index if not exists audit_target on audit(target, id)")
    c.execute("create table if not exists audit_meta(key text primary key, value text not null)")
    c.execute("create trigger if not exists audit_no_update before update on audit begin select raise(abort, 'audit ist nur anhängend'); end")
    c.execute("create trigger if not exists audit_no_delete before delete on audit begin select raise(abort, 'audit ist nur anhängend'); end")
    # qa.QaBook
    c.execute("create table if not exists qa_check(id text primary key, status text not null, note text not null default '',"
              " version text not null default '', hash text not null default '', ts real not null)")
    # timesheet.TimeBook
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
    for t in ("time_seg", "time_gap"):
        _add_columns(c, t, ("area", "activity"))                               # 0.23: Fokusbereich und Tätigkeit je Abschnitt
    c.execute("create table if not exists focus_session(id integer primary key autoincrement, key text not null, title text not null default '',"
              " area text not null default '', activity text not null default '', planned_min integer not null, start real not null, end real,"
              " parked integer not null default 0, result text not null default '', note text not null default '')")
    c.execute("create table if not exists bcs_target(pattern text primary key, task_id text not null, name text not null default '',"
              " path text not null default '', updated real not null)")                                                        # 0.29
    # ux.UxLog
    c.execute("create table if not exists ux_event(id integer primary key autoincrement, ts real not null, sess text not null, view text not null default '',"
              " kind text not null, target text not null default '', ctx text not null default '', x real, y real, extra text not null default '')")
    c.execute("create index if not exists ux_event_ts on ux_event(ts)")
    # ideas.Ideas
    c.execute("create table if not exists ideas(id integer primary key autoincrement, text text not null,"
              "status text not null default 'neu', created text not null)")
    _add_columns(c, "ideas", ("assessment", "ticket", "draft"))                # 0.20: Bewertung, Ticket aus der Idee


# (Nummer, was sie tut, Funktion). Nur anhängen, nie ändern.
MIGRATIONS = (
    (1, "Stand 0.44: alle Tabellen an einer Stelle, fehlende Spalten älterer Versionen", _m1_baseline),
)
LATEST = MIGRATIONS[-1][0]

_lock = threading.Lock()
_done = {}          # Pfad → (Gerät, Inode) der Datei, die schon auf dem neuesten Stand ist


def _ident(p):
    try:
        st = os.stat(p)
        return (st.st_dev, st.st_ino)
    except OSError:
        return None


def version(path):
    """Schema-Version einer Datei, ohne etwas zu ändern (0: noch nie migriert oder es gibt sie nicht)."""
    if not Path(path).is_file():
        return 0
    c = sqlite3.connect("file:%s?mode=ro" % Path(path), uri=True, timeout=10)
    try:
        return c.execute("pragma user_version").fetchone()[0]
    finally:
        c.close()


def ensure(path):
    """Legt die Datei an, falls nötig, und führt fehlende Migrationen aus. Gibt die Version danach zurück."""
    p = str(Path(path))
    ident = _ident(p)
    if ident is not None and _done.get(p) == ident:
        return LATEST
    with _lock:
        ident = _ident(p)
        if ident is not None and _done.get(p) == ident:
            return LATEST
        Path(p).parent.mkdir(parents=True, exist_ok=True)
        c = sqlite3.connect(p, timeout=30, isolation_level=None)
        try:
            c.execute("begin immediate")
            try:
                v = c.execute("pragma user_version").fetchone()[0]
                if v > LATEST:
                    log.warning("Datenbank %s hat Schema %d, diese Version kennt bis %d: Neueres bleibt ungenutzt.", p, v, LATEST)
                for n, what, fn in MIGRATIONS:
                    if n > v:
                        fn(c)
                        c.execute("pragma user_version = %d" % n)
                        log.info("Datenbank: Migration %d (%s)", n, what)
                c.execute("commit")
            except BaseException:
                c.execute("rollback")
                raise
            v = max(v, LATEST)
        finally:
            c.close()
        _done[p] = _ident(p)
        return v
