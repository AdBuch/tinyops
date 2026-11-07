"""Fokusbereiche (0.23): Wie verteilt sich deine Zeit, und reicht sie für das, was du dir vorgenommen hast?

Ein Bereich hat ein Wochenziel in Prozent der Arbeitszeit (z. B. Berufsbildung 30 %), optional feste Wochenblöcke,
Tätigkeiten (für den Text der Zeitentwürfe) und ein Buchungsziel (Ticket oder Projectron-Position).
Zeit gehört zu einem Bereich, wenn sie dort gestartet wurde (Fokus-Sitzung, Block), wenn das Vorhaben in einer seiner
Kategorien liegt (pools) oder wenn es ein Helpdesk-Ticket ist. Alles andere zählt als Entwicklung.

«Soll bis jetzt» rechnet das Wochenziel anteilig auf die bisher vergangene Arbeitszeit der Woche (Arbeitstage, 08–17 Uhr).
Ein Rückstand heisst also: Bei gleichmässiger Verteilung wärst du jetzt weiter.
"""
import re
import time
from datetime import datetime, timedelta

DEFAULTS = {
    "week_hours": 42,
    "workdays": [1, 2, 3, 4, 5],          # ISO: 1 = Montag
    "day_start": "08:00",
    "day_end": "17:00",
    "areas": [
        {"id": "dev", "name": "Entwicklung", "target_pct": 0, "ticket": "", "pools": [], "activities": [], "blocks": []},
        {"id": "hd", "name": "Helpdesk", "target_pct": 0, "ticket": "", "pools": [], "activities": [], "blocks": []},
        {"id": "bb", "name": "Berufsbildung", "target_pct": 30, "ticket": "", "pools": ["Berufsbildung"],
         "activities": ["Betreuung Lernende", "Aufgaben vorbereiten", "Aufgaben reviewen", "Meeting", "Fortschritt prüfen", "Eigene Weiterbildung"],
         "blocks": []},
    ],
}
DAYS = {"mo": 1, "di": 2, "mi": 3, "do": 4, "fr": 5, "sa": 6, "so": 7}
DAY_NAMES = {v: k.capitalize() for k, v in DAYS.items()}
BLOCK_RE = re.compile(r"^\s*(mo|di|mi|do|fr|sa|so)\w*\s+(\d{1,2})[:.](\d{2})\s*[-–]\s*(\d{1,2})[:.](\d{2})\s*$", re.I)


def cfg(c):
    f = dict(DEFAULTS)
    f.update({k: v for k, v in (c.get("focus") or {}).items() if k != "areas"})
    areas = (c.get("focus") or {}).get("areas")
    f["areas"] = [dict(a) for a in (areas if areas else DEFAULTS["areas"])]
    if not any(a["id"] == "dev" for a in f["areas"]):
        f["areas"].insert(0, dict(DEFAULTS["areas"][0]))
    for a in f["areas"]:
        for k, v in (("target_pct", 0), ("ticket", ""), ("pools", []), ("activities", []), ("blocks", [])):
            a.setdefault(k, v)
    return f


def parse_blocks(text):
    """«Di 13:30-17:00, Do 13:30-17:00» → [{"day": 2, "from": "13:30", "to": "17:00"}]. Fehler: ValueError mit dem Teil."""
    out = []
    for part in [p for p in re.split(r"[,;\n]+", text or "") if p.strip()]:
        m = BLOCK_RE.match(part)
        if not m:
            raise ValueError("«%s» verstehe ich nicht. Beispiel: Di 13:30-17:00" % part.strip())
        d, h1, m1, h2, m2 = DAYS[m.group(1).lower()], int(m.group(2)), int(m.group(3)), int(m.group(4)), int(m.group(5))
        if not (0 <= h1 < 24 and 0 <= h2 <= 24 and m1 < 60 and m2 < 60) or (h2, m2) <= (h1, m1):
            raise ValueError("«%s»: Ende muss nach dem Beginn liegen." % part.strip())
        out.append({"day": d, "from": "%02d:%02d" % (h1, m1), "to": "%02d:%02d" % (h2, m2)})
    return out


def blocks_text(blocks):
    return ", ".join("%s %s-%s" % (DAY_NAMES[b["day"]], b["from"], b["to"]) for b in blocks or [])


def area(f, aid):
    return next((a for a in f["areas"] if a["id"] == aid), None)


def area_of_card(f, card):
    """Bereich eines Vorhabens aus seinen Kategorien (pools). Ohne Treffer: Entwicklung."""
    names = {(p.get("name") or "").lower() for p in (card or {}).get("pools") or []}
    for a in f["areas"]:
        if names & {x.lower() for x in a.get("pools") or []}:
            return a["id"]
    return "dev"


def booking_key(a):
    """Schlüssel für Zeit ohne Vorhaben (Block, Sitzung im Bereich): das Buchungsziel oder der Name des Bereichs."""
    return (a.get("ticket") or "").strip() or a["name"]


def _hm(s):
    h, m = s.split(":")
    return int(h) * 60 + int(m)


def week_start(now):
    d = datetime.fromtimestamp(now)
    return datetime(d.year, d.month, d.day) - timedelta(days=d.isoweekday() - 1)


def worked_fraction(f, now):
    """Anteil der Arbeitszeit dieser Woche, der schon vorbei ist (0..1)."""
    ws = week_start(now)
    days = [d for d in f["workdays"] if 1 <= d <= 7] or [1, 2, 3, 4, 5]
    a, b = _hm(f["day_start"]), _hm(f["day_end"])
    per_day = max(1, b - a)
    done = 0.0
    d = datetime.fromtimestamp(now)
    for wd in days:
        day = ws + timedelta(days=wd - 1)
        if day.date() < d.date():
            done += per_day
        elif day.date() == d.date():
            mins = d.hour * 60 + d.minute
            done += min(per_day, max(0, mins - a))
    return done / float(per_day * len(days))


def current_block(f, now):
    d = datetime.fromtimestamp(now)
    mins = d.hour * 60 + d.minute
    for a in f["areas"]:
        for b in a.get("blocks") or []:
            if b["day"] == d.isoweekday() and _hm(b["from"]) <= mins < _hm(b["to"]):
                return {"area": a["id"], "name": a["name"], "until": b["to"], "from": b["from"]}
    return None


def next_block(f, now):
    d = datetime.fromtimestamp(now)
    best = None
    for a in f["areas"]:
        for b in a.get("blocks") or []:
            for add in range(0, 8):
                day = d + timedelta(days=add)
                if day.isoweekday() != b["day"]:
                    continue
                start = datetime(day.year, day.month, day.day, *map(int, b["from"].split(":")))
                if start.timestamp() > now:
                    if best is None or start.timestamp() < best["ts"]:
                        best = {"area": a["id"], "name": a["name"], "ts": start.timestamp(), "label": "%s %s-%s" % (DAY_NAMES[b["day"]], b["from"], b["to"])}
                    break
    return best


def week_report(f, segs, now=None):
    """segs: Abschnitte der Woche mit area und secs. Je Bereich: Ist, Ziel, Soll bis jetzt, Rückstand."""
    now = now or time.time()
    frac = worked_fraction(f, now)
    total = sum(s["secs"] for s in segs)
    out = []
    for a in f["areas"]:
        secs = sum(s["secs"] for s in segs if (s.get("area") or "dev") == a["id"])
        target = a.get("target_pct", 0) / 100.0 * f["week_hours"] * 3600
        due = target * frac
        out.append({"id": a["id"], "name": a["name"], "secs": secs, "share_pct": round(100.0 * secs / total, 1) if total else 0.0,
                    "target_pct": a.get("target_pct", 0), "target_secs": int(target), "due_secs": int(due),
                    "behind_secs": int(max(0, due - secs)) if target else 0, "ahead_secs": int(max(0, secs - due)) if target else 0,
                    "activities": a.get("activities") or [], "has_blocks": bool(a.get("blocks"))})
    return {"areas": out, "total_secs": total, "worked_frac": round(frac, 3), "week_hours": f["week_hours"]}
