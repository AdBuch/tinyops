"""Qualität (0.19): Prüfliste zum Abhaken und Selbsttest.

Prüfliste: `QA-CHECKLIST.md`. Je Release kommt ein Abschnitt dazu, nur mit dem, was sich geändert hat; die Grundprüfung deckt
alle Funktionen ab. Zeilen haben die Form `- [ ] \\`id\\` Aufgabe → erwartet`. Der Stand (ok, Fehler mit Notiz, übersprungen)
liegt in tinyops.db, nicht in der Datei. Ändert sich der Text einer Aufgabe, gilt sie wieder als offen.

Selbsttest: prüft die eigenen Teile ohne deine Daten anzufassen (Vorlagen, Hilfsskripte, Datenbank, Kette des Verlaufs)
und spielt die Kernfunktionen einmal mit Demo-Daten in einem leeren Ordner durch.
"""
import hashlib
import re
import shutil
import sqlite3
import subprocess
import threading
import time
from pathlib import Path

LINE = re.compile(r"^\s*- \[[ xX]\] `([a-z0-9][a-z0-9.\-]{0,30})` (.+?)\s*$")
HEAD = re.compile(r"^##\s+(.+?)\s*$")
STATES = ("ok", "fehler", "übersprungen")


def parse_checklist(text):
    """[{title, version, items: [{id, text, expect}]}]. version ist z. B. «0.19.0» bei Release-Abschnitten, sonst ''."""
    sections, cur, seen = [], None, set()
    for ln in (text or "").splitlines():
        h = HEAD.match(ln)
        if h:
            title = h.group(1)
            v = re.match(r"^(\d+\.\d+\.\d+)\b", title)
            cur = {"title": title, "version": v.group(1) if v else "", "items": []}
            sections.append(cur)
            continue
        m = LINE.match(ln)
        if m and cur is not None:
            iid, body = m.group(1), m.group(2)
            if iid in seen:
                raise ValueError("Prüfpunkt «%s» steht doppelt in der Prüfliste." % iid)
            seen.add(iid)
            task, _, expect = body.rpartition(" → ") if " → " in body else (body, "", "")
            cur["items"].append({"id": iid, "text": task.strip(), "expect": expect.strip(), "hash": hashlib.sha256(body.encode()).hexdigest()[:12]})
    return [s for s in sections if s["items"]]


class QaBook:
    def __init__(self, path):
        self.path = Path(path)
        self.lock = threading.Lock()

    def _conn(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        c = sqlite3.connect(str(self.path), timeout=10)
        c.row_factory = sqlite3.Row
        c.execute("create table if not exists qa_check(id text primary key, status text not null, note text not null default '',"
                  " version text not null default '', hash text not null default '', ts real not null)")
        return c

    def states(self):
        c = self._conn()
        try:
            return {r["id"]: dict(r) for r in c.execute("select * from qa_check")}
        finally:
            c.close()

    def set(self, iid, status, note, version, h):
        with self.lock:
            c = self._conn()
            try:
                if status in (None, "", "offen"):
                    c.execute("delete from qa_check where id=?", (iid,))
                else:
                    c.execute("insert into qa_check(id, status, note, version, hash, ts) values(?,?,?,?,?,?) on conflict(id) do update set "
                              "status=excluded.status, note=excluded.note, version=excluded.version, hash=excluded.hash, ts=excluded.ts",
                              (iid, status, note[:1000], version, h, time.time()))
                c.commit()
            finally:
                c.close()


def view(sections, states):
    """Prüfliste mit Stand. Ein Punkt, dessen Text sich seit dem Abhaken geändert hat, ist wieder offen («geändert»)."""
    out = []
    for s in sections:
        items = []
        for it in s["items"]:
            st = states.get(it["id"])
            changed = bool(st and st["hash"] != it["hash"])
            items.append(dict(it, status="offen" if not st or changed else st["status"], note=(st or {}).get("note", ""),
                              checked_in=(st or {}).get("version", ""), ts=(st or {}).get("ts"), changed=changed))
        n = len(items)
        out.append(dict(s, items=items, done=sum(1 for i in items if i["status"] != "offen"), fails=sum(1 for i in items if i["status"] == "fehler"), total=n))
    return out


def report_md(sections, version):
    """Ergebnis zum Zurückgeben: Fehler mit Notiz zuerst, dann was offen ist."""
    fails = [(s, i) for s in sections for i in s["items"] if i["status"] == "fehler"]
    open_ = [(s, i) for s in sections for i in s["items"] if i["status"] == "offen"]
    lines = ["# Prüfliste tinyops %s" % version, "",
             "%d geprüft, %d Fehler, %d offen." % (sum(s["done"] for s in sections), len(fails), len(open_)), ""]
    if fails:
        lines.append("## Fehler")
        for s, i in fails:
            lines.append("- `%s` %s%s" % (i["id"], i["text"], (" → erwartet: " + i["expect"]) if i["expect"] else ""))
            if i["note"]:
                lines.extend("  > " + ln for ln in i["note"].splitlines())
        lines.append("")
    if open_:
        lines.append("## Offen")
        lines.extend("- `%s` %s" % (i["id"], i["text"]) for s, i in open_)
    return "\n".join(lines).strip() + "\n"


# ------------------------------------------------------------------ Selbsttest: statische Teile
def check_static(base, version, checklist_text, helpers, step):
    base = Path(base)
    ui = base / "static" / "index.html"
    try:
        size = ui.stat().st_size
        step("ui", "Oberfläche", "ok" if size > 20000 else "fail", "%s, %d KB" % (ui.name, size // 1024))
    except OSError:
        step("ui", "Oberfläche", "fail", "static/index.html fehlt")

    class D(dict):
        def __missing__(self, k):
            return "x"
    bad = []
    for name in ("agent-task", "agent-followup", "agent-tools", "review-topics"):
        f = base / "prompts" / ("%s.md" % name)
        try:
            f.read_text(encoding="utf-8").format_map(D())
        except (OSError, ValueError, KeyError, IndexError) as e:
            bad.append("%s (%s)" % (f.name, e))
    step("prompts", "Prompt-Vorlagen", "fail" if bad else "ok", ", ".join(bad) or "agent-task, agent-followup, agent-tools, review-topics lesbar")
    sh = shutil.which("sh")
    if not sh:
        step("helpers", "Hilfsskripte für Agenten", "warn", "kein sh auf diesem Rechner (Windows ohne Git for Windows?). Remote laufen sie trotzdem.")
    else:
        bad = []
        for name, body in helpers.items():
            r = subprocess.run([sh, "-n"], input=body, text=True, capture_output=True, timeout=10)
            if r.returncode:
                bad.append("%s: %s" % (name, r.stderr.strip()[:120]))
        step("helpers", "Hilfsskripte für Agenten", "fail" if bad else "ok", "; ".join(bad) or ", ".join(helpers) + ": Syntax ok")
    try:
        secs = parse_checklist(checklist_text)
        n = sum(len(s["items"]) for s in secs)
        has = any(s["version"] == version for s in secs)
        step("checklist", "Prüfliste", "ok" if has else "warn", "%d Punkte in %d Abschnitten%s" % (n, len(secs), "" if has else "; kein Abschnitt für %s" % version))
    except ValueError as e:
        step("checklist", "Prüfliste", "fail", str(e))


def check_db(db, audit_log, step):
    if not Path(db).exists():
        step("db", "Datenbank", "ok", "noch keine (wird beim ersten Speichern angelegt)")
        return
    try:
        c = sqlite3.connect("file:%s?mode=ro" % db, uri=True, timeout=10)
        try:
            res = c.execute("pragma integrity_check").fetchone()[0]
        finally:
            c.close()
        step("db", "Datenbank", "ok" if res == "ok" else "fail", "%s: %s" % (Path(db).name, res))
    except sqlite3.Error as e:
        step("db", "Datenbank", "fail", str(e))
    v = audit_log.verify()
    step("audit", "Kette des Verlaufs", "ok" if v["ok"] else "fail",
         "%d Einträge in Ordnung" % v["count"] if v["ok"] else "gebrochen bei %s: %s" % (v["broken_at"], v["reason"]))
