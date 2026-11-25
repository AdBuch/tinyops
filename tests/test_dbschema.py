"""0.45: Datenbank mit Schema-Version und nummerierten Migrationen (dbschema.py).

- Eine frische Datei hat genau das Schema, das tinyops 0.44 angelegt hat (tests/db_schema_044.json).
- Eine Datei aus 0.25 (tests/db_025.sql) kommt auf denselben Stand, die Daten bleiben.
- Kein Modul legt mehr selbst Tabellen an."""
import json
import os
import re
import sqlite3
import sys
import tempfile
import threading
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("TINYOPS_HOME", tempfile.mkdtemp())
import audit  # noqa: E402
import dbschema  # noqa: E402
import ideas  # noqa: E402
import links  # noqa: E402
import qa  # noqa: E402
import timesheet  # noqa: E402
import ux  # noqa: E402

SNAP = json.loads((ROOT / "tests" / "db_schema_044.json").read_text(encoding="utf-8"))


def schema(path):
    c = sqlite3.connect(str(path))
    try:
        out = {}
        for typ, name, sql in c.execute("select type, name, sql from sqlite_master where name not like 'sqlite_%' order by type, name"):
            if typ == "table":
                out["table " + name] = [list(r[1:6]) for r in c.execute("pragma table_info(%s)" % name)]
            elif sql:
                out[typ + " " + name] = " ".join(sql.split())
        return out
    finally:
        c.close()


def cols(path, table):
    c = sqlite3.connect(str(path))
    try:
        return {r[1]: r for r in c.execute("pragma table_info(%s)" % table)}
    finally:
        c.close()


class Migrations(unittest.TestCase):
    def setUp(self):
        self.d = Path(tempfile.mkdtemp())
        self.db = self.d / "tinyops.db"

    def test_fresh_file_matches_044(self):
        self.assertEqual(dbschema.ensure(self.db), dbschema.LATEST)
        self.assertEqual(schema(self.db), SNAP)
        self.assertEqual(dbschema.version(self.db), dbschema.LATEST)

    def test_upgrade_from_025_keeps_data(self):
        c = sqlite3.connect(str(self.db))
        c.executescript((ROOT / "tests" / "db_025.sql").read_text(encoding="utf-8"))
        c.close()
        self.assertEqual(dbschema.version(self.db), 0)
        self.assertNotIn("findings", cols(self.db, "agent_runs"))
        dbschema.ensure(self.db)
        got = schema(self.db)
        self.assertEqual(sorted(got), sorted(SNAP), "dieselben Tabellen, Indizes und Trigger")
        for name, columns in SNAP.items():                  # Spalten gleich; die Reihenfolge darf abweichen
            if name.startswith("table "):
                self.assertEqual(sorted(map(tuple, got[name])), sorted(map(tuple, columns)), name)
        st = links.Store(self.db)
        c = sqlite3.connect(str(self.db))
        c.row_factory = sqlite3.Row
        try:
            r = c.execute("select * from agent_runs").fetchone()
            self.assertEqual((r["summary"], r["findings"], r["phase"]), ("Bericht aus 0.25", "", ""))
            self.assertEqual(c.execute("select ticket from links").fetchone()[0], "DLP-1")
            self.assertEqual(c.execute("select activity from time_seg").fetchone()[0], "")
        finally:
            c.close()
        self.assertEqual(st.links(), {"7:feature/DLP-1-x": "DLP-1"})
        self.assertEqual([i["text"] for i in ideas.Ideas(self.db, 50, 9999).list()], ["Idee aus 0.25"])

    def test_runs_once_and_survives_a_new_file(self):
        dbschema.ensure(self.db)
        c = sqlite3.connect(str(self.db))
        c.execute("drop table hd_seen")
        c.commit()
        c.close()
        dbschema.ensure(self.db)                            # gleiche Datei, schon migriert: nichts passiert
        self.assertNotIn("table hd_seen", schema(self.db))
        self.db.unlink()                                    # neue Datei am selben Ort (Test, Neuanfang): wird wieder angelegt
        dbschema.ensure(self.db)
        self.assertEqual(schema(self.db), SNAP)

    def test_newer_file_is_used_as_is(self):
        dbschema.ensure(self.db)
        c = sqlite3.connect(str(self.db))
        c.execute("create table later(x text)")
        c.execute("pragma user_version = %d" % (dbschema.LATEST + 5))
        c.commit()
        c.close()
        dbschema._done.clear()
        with self.assertLogs("tinyops", "WARNING") as w:
            self.assertEqual(dbschema.ensure(self.db), dbschema.LATEST + 5)
        self.assertIn("Neueres bleibt ungenutzt", w.output[0])
        self.assertEqual(dbschema.version(self.db), dbschema.LATEST + 5)
        self.assertEqual(links.Store(self.db).links(), {})

    def test_failed_migration_rolls_back(self):
        def boom(c):
            c.execute("create table halb(x text)")
            raise RuntimeError("kaputt")
        orig = dbschema.MIGRATIONS
        dbschema.MIGRATIONS = orig + ((dbschema.LATEST + 1, "Test", boom),)
        self.addCleanup(setattr, dbschema, "MIGRATIONS", orig)
        with self.assertRaises(RuntimeError):
            dbschema.ensure(self.db)
        self.assertEqual(dbschema.version(self.db), 0, "auch Migration 1 ist zurückgenommen, alles oder nichts")
        self.assertNotIn("table halb", schema(self.db))

    def test_parallel_first_start(self):
        errors = []

        def go():
            try:
                links.Store(self.db).link(7, "feature/x-%d" % threading.get_ident(), "DLP-2")
                timesheet.TimeBook(self.db)._conn().close()
            except Exception as e:                           # noqa: BLE001
                errors.append(e)
        dbschema._done.clear()
        ts = [threading.Thread(target=go) for _ in range(8)]
        for t in ts:
            t.start()
        for t in ts:
            t.join()
        self.assertEqual(errors, [])
        self.assertEqual(len(links.Store(self.db).links()), 8)

    def test_stores_work_on_a_fresh_file(self):
        st = links.Store(self.db)
        self.assertEqual(st.links(), {}, "lesen ohne Datei legt nichts an")
        self.assertFalse(self.db.exists())
        a = audit.AuditLog(self.db)
        a.add("test.eins", "DLP-1")
        self.assertTrue(a.verify()["ok"])
        qa.QaBook(self.db).states()
        ux.UxLog(self.db).add_batch("s1", [{"kind": "click", "target": "button"}])
        timesheet.TimeBook(self.db).bcs_targets()
        self.assertEqual(dbschema.version(self.db), dbschema.LATEST)

    def test_audit_stays_append_only(self):
        a = audit.AuditLog(self.db)
        a.add("test.eins", "DLP-1")
        c = sqlite3.connect(str(self.db))
        with self.assertRaises(sqlite3.DatabaseError):
            c.execute("delete from audit")
        c.close()


class OnePlace(unittest.TestCase):
    def test_no_module_creates_tables_itself(self):
        bad = []
        for p in sorted(ROOT.glob("*.py")):
            if p.name == "dbschema.py":
                continue
            src = p.read_text(encoding="utf-8")
            if re.search(r"(create table|alter table|create index|create trigger)", src, re.I):
                bad.append(p.name)
        self.assertEqual(bad, [], "Schema gehört in dbschema.MIGRATIONS")

    def test_migrations_numbered_without_gaps(self):
        self.assertEqual([m[0] for m in dbschema.MIGRATIONS], list(range(1, len(dbschema.MIGRATIONS) + 1)))


if __name__ == "__main__":
    unittest.main()
