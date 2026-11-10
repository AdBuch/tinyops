"""UI-Nutzung (0.22): Klicks, Mausbewegung, Tasten und Ansichten lokal erfassen, auswerten und als Bericht ausgeben.

Zweck: die Oberfläche verbessern. Der Bericht ist zum Kopieren gedacht (z. B. zurück an Claude), sonst verlässt nichts den Rechner.

Was erfasst wird, und was nicht:
* Klicks mit einer Beschreibung des Elements (Art, id, data-Attribut, kurze Beschriftung von Knöpfen; Ziffern als #),
  Position relativ zum Fenster, Zögern (Zeit vom Hovern bis zum Klick), Ansicht und umgebender Dialog/Bereich.
* Klicks ins Leere («tote Klicks»), Tasten ausserhalb von Eingabefeldern, Ansichtswechsel, Dialoge auf/zu,
  Mausweg und eine grobe Verteilung je Ansicht (12 × 8 Felder), Fenstergrösse, JavaScript-Fehler.
* Nie: Text aus Eingabefeldern, Inhalte von Zeilen und Karten (Ticket-Titel), Tastendrücke in Feldern (nur «getippt in»).
"""
import json
import re
import sqlite3
import threading
import time
from collections import Counter, defaultdict
from pathlib import Path

import secretstore as store

KINDS = {"click", "dead", "key", "type", "view", "dialog", "move", "env", "error"}
GRID_W, GRID_H = 12, 8
MAX_BATCH = 600
SHADES = " .:-=+*#%@"


def _txt(v, n=120):
    s = store.scrub_all(" ".join(str(v or "").split()))
    return s[:n]


class UxLog:
    def __init__(self, path):
        self.path = Path(path)
        self.lock = threading.Lock()
        self._pruned = 0.0

    def _conn(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        c = sqlite3.connect(str(self.path), timeout=10)
        c.row_factory = sqlite3.Row
        c.execute("create table if not exists ux_event(id integer primary key autoincrement, ts real not null, sess text not null, view text not null default '',"
                  " kind text not null, target text not null default '', ctx text not null default '', x real, y real, extra text not null default '')")
        c.execute("create index if not exists ux_event_ts on ux_event(ts)")
        return c

    def add_batch(self, sess, events, days=30, now=None):
        now = now or time.time()
        sess = re.sub(r"[^a-z0-9]", "", str(sess or "").lower())[:16] or "x"
        rows = []
        for e in (events or [])[:MAX_BATCH]:
            if not isinstance(e, dict) or e.get("k") not in KINDS:
                continue
            try:
                ts = float(e.get("ts") or now)
            except (TypeError, ValueError):
                ts = now
            if abs(ts - now) > 3 * 86400:          # Uhr verstellt oder Unsinn
                ts = now
            x, y = e.get("x"), e.get("y")
            x = min(1.0, max(0.0, float(x))) if isinstance(x, (int, float)) else None
            y = min(1.0, max(0.0, float(y))) if isinstance(y, (int, float)) else None
            extra = e.get("e")
            extra = json.dumps(extra, ensure_ascii=False)[:4000] if isinstance(extra, (dict, list)) else _txt(extra, 200) if extra else ""
            rows.append((ts, sess, _txt(e.get("v"), 20), e["k"], _txt(e.get("t")), _txt(e.get("c"), 40), x, y, extra))
        if not rows:
            return 0
        with self.lock:
            c = self._conn()
            try:
                c.executemany("insert into ux_event(ts, sess, view, kind, target, ctx, x, y, extra) values(?,?,?,?,?,?,?,?,?)", rows)
                if days and now - self._pruned > 3600:
                    c.execute("delete from ux_event where ts < ?", (now - days * 86400,))
                    self._pruned = now
                c.commit()
            finally:
                c.close()
        return len(rows)

    def clear(self):
        with self.lock:
            c = self._conn()
            try:
                n = c.execute("delete from ux_event").rowcount
                c.commit()
                return n
            finally:
                c.close()

    def events(self, since):
        c = self._conn()
        try:
            out = []
            for r in c.execute("select * from ux_event where ts >= ? order by ts, id", (since,)):
                d = dict(r)
                try:
                    d["extra"] = json.loads(d["extra"]) if d["extra"][:1] in ("{", "[") else d["extra"]
                except ValueError:
                    pass
                out.append(d)
            return out
        finally:
            c.close()

    def count(self):
        c = self._conn()
        try:
            r = c.execute("select count(*), min(ts) from ux_event").fetchone()
            return {"events": r[0], "since": r[1]}
        finally:
            c.close()


# ------------------------------------------------------------------ Auswertung
def _median(xs):
    xs = sorted(xs)
    return xs[len(xs) // 2] if xs else None


CLOSE_RE = re.compile(r"schlie|close|abbrech|×|esc$", re.I)


def analyse(evs, now=None):
    now = now or time.time()
    by_sess = defaultdict(list)
    for e in evs:
        by_sess[e["sess"]].append(e)
    clicks = [e for e in evs if e["kind"] == "click"]
    dead = [e for e in evs if e["kind"] == "dead"]
    # aktive Zeit: Abstände unter 2 min zählen
    active = 0.0
    view_time = Counter()
    trans = Counter()
    for s, es in by_sess.items():
        es.sort(key=lambda e: e["ts"])
        cur = None
        for a, b in zip(es, es[1:]):
            gap = b["ts"] - a["ts"]
            if gap < 120:
                active += gap
                view_time[a["view"] or "?"] += gap
        for e in es:
            if e["kind"] == "view":
                if cur and cur != e["target"]:
                    trans["%s → %s" % (cur, e["target"])] += 1
                cur = e["target"]
    # Aktionen
    act = defaultdict(lambda: {"n": 0, "hes": [], "views": Counter(), "keys": 0})
    for e in clicks:
        a = act[e["target"]]
        a["n"] += 1
        a["views"][e["view"]] += 1
        h = (e["extra"] or {}).get("h") if isinstance(e["extra"], dict) else None
        if isinstance(h, (int, float)) and 0 < h < 60000:
            a["hes"].append(h)
    keys = Counter(e["target"] for e in evs if e["kind"] == "key")
    typed = Counter()
    for e in evs:
        if e["kind"] == "type":
            n = (e["extra"] or {}).get("n", 1) if isinstance(e["extra"], dict) else 1
            typed[e["target"]] += int(n or 1)
    # Wutklicks: 3+ Klicks aufs gleiche Ziel in 1.5 s
    rage = Counter()
    for s, es in by_sess.items():
        cs = [e for e in es if e["kind"] in ("click", "dead")]
        i = 0
        while i < len(cs):
            j = i
            while j + 1 < len(cs) and cs[j + 1]["target"] == cs[i]["target"] and cs[j + 1]["ts"] - cs[i]["ts"] <= 1.5:
                j += 1
            if j - i >= 2:
                rage[cs[i]["target"]] += 1
            i = j + 1
    # Dialoge: aufgegangen und ohne Aktion darin wieder zu
    dlg = defaultdict(lambda: {"open": 0, "abandoned": 0, "secs": []})
    for s, es in by_sess.items():
        opened = {}
        acted = defaultdict(bool)
        for e in es:
            if e["kind"] == "dialog":
                state = (e["extra"] if isinstance(e["extra"], str) else (e["extra"] or {}).get("s")) or ""
                if state == "open":
                    opened[e["target"]] = e["ts"]
                    acted[e["target"]] = False
                    dlg[e["target"]]["open"] += 1
                elif state == "close" and e["target"] in opened:
                    dlg[e["target"]]["secs"].append(e["ts"] - opened.pop(e["target"]))
                    if not acted[e["target"]]:
                        dlg[e["target"]]["abandoned"] += 1
            elif e["kind"] == "click" and e["ctx"] in opened and not CLOSE_RE.search(e["target"]):
                acted[e["ctx"]] = True
    # Maus
    mouse = defaultdict(lambda: {"dist": 0.0, "grid": Counter()})
    for e in evs:
        if e["kind"] == "move" and isinstance(e["extra"], dict):
            m = mouse[e["view"] or "?"]
            m["dist"] += float(e["extra"].get("d") or 0)
            for k, n in (e["extra"].get("g") or {}).items():
                m["grid"][k] += int(n)
    for e in clicks + dead:
        if e["x"] is not None:
            mouse[e["view"] or "?"]["clicks"] = mouse[e["view"] or "?"].get("clicks", 0) + 1
    envs = [e["extra"] for e in evs if e["kind"] == "env" and isinstance(e["extra"], dict)]
    errors = Counter(e["target"] for e in evs if e["kind"] == "error")
    return {"sessions": len(by_sess), "events": len(evs), "active_min": round(active / 60), "views": view_time, "transitions": trans,
            "actions": act, "dead": dead, "rage": rage, "keys": keys, "typed": typed, "dialogs": dlg, "mouse": mouse, "envs": envs, "errors": errors,
            "first": min((e["ts"] for e in evs), default=None), "last": max((e["ts"] for e in evs), default=None)}


def heat(grid, w=GRID_W, h=GRID_H):
    mx = max(grid.values(), default=0)
    if not mx:
        return []
    out = []
    for y in range(h):
        row = ""
        for x in range(w):
            n = grid.get("%d,%d" % (x, y), 0)
            row += SHADES[min(len(SHADES) - 1, int(round((len(SHADES) - 1) * (n / mx) ** 0.5)))] if n else " "
        out.append("|" + row + "|")
    return out


def hints(a):
    """Ein paar automatische Beobachtungen. Keine Urteile, nur Auffälligkeiten mit Zahlen."""
    out = []
    dead_t = Counter((e["view"], e["target"]) for e in a["dead"])
    for (v, t), n in dead_t.most_common(3):
        if n >= 3:
            out.append("%d tote Klicks auf «%s» in %s: sieht klickbar aus, ist es nicht." % (n, t, v or "?"))
    for t, n in a["rage"].most_common(3):
        out.append("%d× Wutklick auf «%s»: reagiert zu langsam oder unklar." % (n, t))
    slow = [(t, _median(x["hes"]), x["n"]) for t, x in a["actions"].items() if len(x["hes"]) >= 3]
    for t, m, n in sorted(slow, key=lambda z: -z[1])[:3]:
        if m and m >= 1500:
            out.append("Vor «%s» wird lange gezögert (Median %.1f s bei %d Klicks): schwer zu finden oder unklar beschriftet." % (t, m / 1000.0, n))
    for d, x in a["dialogs"].items():
        if x["open"] >= 3 and x["abandoned"] / float(x["open"]) >= 0.5:
            out.append("Dialog %s geht oft ohne Aktion wieder zu (%d von %d)." % (d, x["abandoned"], x["open"]))
    for t, n in a["transitions"].most_common(4):
        back = " → ".join(reversed(t.split(" → ")))
        if n >= 5 and a["transitions"].get(back, 0) >= 5:
            out.append("Oft hin und her: %s (%d×) und zurück (%d×). Gehört die Information zusammen?" % (t, n, a["transitions"][back]))
            break
    if a["errors"]:
        out.append("%d JavaScript-Fehler, siehe unten." % sum(a["errors"].values()))
    return out


def report_md(a, days, version):
    from datetime import datetime
    f = lambda ts: datetime.fromtimestamp(ts).strftime("%d.%m. %H:%M") if ts else "–"
    L = ["# tinyops UI-Nutzung %s" % version, "",
         "Lokal erfasst, %s bis %s (letzte %d Tage): %d Sitzungen, etwa %d aktive Minuten, %d Ereignisse." % (f(a["first"]), f(a["last"]), days, a["sessions"], a["active_min"], a["events"]),
         "Keine Eingaben, keine Ticket-Titel. Ziel: die Oberfläche verbessern.", ""]
    if a["envs"]:
        sizes = Counter("%s×%s" % (e.get("w"), e.get("h")) for e in a["envs"])
        L.append("Fenster: " + ", ".join("%s (%d×)" % kv for kv in sizes.most_common(4)) + "; Pixeldichte " + ", ".join(sorted({str(e.get("dpr")) for e in a["envs"]})))
        L.append("")
    h = hints(a)
    if h:
        L += ["## Auffällig"] + ["- " + x for x in h] + [""]
    if a["views"]:
        tot = float(sum(a["views"].values())) or 1.0
        L += ["## Ansichten (Anteil aktive Zeit)"] + ["- %s: %d %% (%d min)" % (v, round(100 * s / tot), round(s / 60)) for v, s in a["views"].most_common()] + [""]
    if a["transitions"]:
        L += ["## Wechsel (häufigste)"] + ["- %s: %d×" % kv for kv in a["transitions"].most_common(8)] + [""]
    if a["actions"]:
        L += ["## Aktionen (Klicks)", "| Ziel | Klicks | Zögern Median | Ansichten |", "|---|---|---|---|"]
        for t, x in sorted(a["actions"].items(), key=lambda kv: -kv[1]["n"])[:30]:
            m = _median(x["hes"])
            L.append("| %s | %d | %s | %s |" % (t.replace("|", "/"), x["n"], ("%.1f s" % (m / 1000.0)) if m else "–", ", ".join("%s %d" % kv for kv in x["views"].most_common(3))))
        L.append("")
    if a["dead"]:
        dc = Counter((e["view"], e["target"], e.get("ctx") or "") for e in a["dead"])
        L += ["## Tote Klicks (ins Leere)"] + ["- %s in %s%s: %d×" % (t, v or "?", (" / " + c) if c else "", n) for (v, t, c), n in dc.most_common(14)] + [""]
    if a["rage"]:
        L += ["## Wutklicks (3+ Klicks in 1.5 s)"] + ["- %s: %d×" % kv for kv in a["rage"].most_common(8)] + [""]
    if a["keys"]:
        L += ["## Tasten (ausserhalb von Feldern)"] + [", ".join("%s %d×" % kv for kv in a["keys"].most_common(16)), ""]
    if a["typed"]:
        L += ["## Eingaben (nur Anzahl Tasten, kein Inhalt)"] + ["- %s: %d" % kv for kv in a["typed"].most_common(8)] + [""]
    if a["dialogs"]:
        L += ["## Dialoge", "| Dialog | geöffnet | ohne Aktion zu | Dauer Median |", "|---|---|---|---|"]
        for d, x in sorted(a["dialogs"].items(), key=lambda kv: -kv[1]["open"]):
            m = _median(x["secs"])
            L.append("| %s | %d | %d | %s |" % (d, x["open"], x["abandoned"], ("%d s" % m) if m is not None else "–"))
        L.append("")
    mv = sorted(a["mouse"].items(), key=lambda kv: -kv[1]["dist"])
    if mv:
        L += ["## Maus (Weg in Bildschirmbreiten, Verteilung %d × %d, dunkel = oft)" % (GRID_W, GRID_H)]
        for v, m in mv[:4]:
            L.append("%s: %.0f Bildschirmbreiten Weg, %d Klicks" % (v, m["dist"], m.get("clicks", 0)))
            hm = heat(m["grid"])
            if hm:
                L += ["```"] + hm + ["```"]
        L.append("")
    if a["errors"]:
        L += ["## JavaScript-Fehler"] + ["- %s: %d×" % kv for kv in a["errors"].most_common(8)] + [""]
    return "\n".join(L).strip() + "\n"
