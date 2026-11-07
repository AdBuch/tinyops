"""Helpdesk-Jira (0.23): eine zweite Jira-Instanz, nur lesend.

* Mir zugewiesene Tickets erscheinen im Fokus unter «Du bist dran», mit Wartezeit und SLA.
* Eine Queue (JQL, z. B. nicht zugewiesene Tickets) meldet Neues, bis du es als gesehen markierst.
* Angeheftet läuft die Zeit auf das Helpdesk-Ticket (Bereich Helpdesk) und landet in den Zeitentwürfen.

Jira 8.5 kennt keine Personal Access Tokens: Standard ist Basic Auth mit Benutzername und Passwort (Secret helpdesk_password).
Neuere Instanzen gehen auch mit Bearer-Token (Secret helpdesk_token). Geschrieben wird nichts.
"""
import base64
import time
from datetime import datetime

import secretstore as store

DEFAULTS = {
    "enabled": False,
    "name": "Helpdesk",
    "url": "",
    "auth": "basic",                       # basic (Jira 8.x) oder bearer (Personal Access Token ab 8.14)
    "username": "",
    "assigned_jql": "assignee = currentUser() AND resolution = Unresolved ORDER BY priority DESC, updated ASC",
    "queue_jql": "",                       # z. B. project = SD AND assignee is EMPTY AND resolution = Unresolved
    "sla_hours": 24,
    "area": "hd",                          # Fokusbereich für die Zeit
}
FIELDS = ["summary", "status", "priority", "created", "updated", "reporter", "duedate"]
PRIO_RANK = {"blocker": 5, "highest": 5, "critical": 4, "high": 4, "major": 3, "medium": 3, "normal": 3, "minor": 2, "low": 2, "trivial": 1, "lowest": 1}


def cfg(c):
    out = dict(DEFAULTS)
    out.update(c.get("helpdesk") or {})
    return out


def secret_name(hc):
    return "helpdesk_token" if hc.get("auth") == "bearer" else "helpdesk_password"


def auth_header(hc, secrets):
    if hc.get("auth") == "bearer":
        return "Bearer " + secrets["helpdesk_token"]
    if not hc.get("username"):
        raise ValueError("helpdesk.username fehlt (nötig bei Basic Auth).")
    raw = base64.b64encode(("%s:%s" % (hc["username"], secrets["helpdesk_password"])).encode("utf-8")).decode("ascii")
    store.register(raw)
    return "Basic " + raw


def _age_h(ts, now):
    if not ts:
        return None
    try:
        t = datetime.strptime(ts[:19], "%Y-%m-%dT%H:%M:%S")
        off = ts[23:] if len(ts) > 23 else "+0000"
        sign = 1 if off[:1] != "-" else -1
        secs = sign * (int(off[1:3]) * 3600 + int(off[3:5]) * 60) if len(off) >= 5 else 0
        epoch = (t - datetime(1970, 1, 1)).total_seconds() - secs
        return max(0.0, (now - epoch) / 3600.0)
    except (ValueError, IndexError):
        return None


def item(base, i, sla, now):
    f = i.get("fields") or {}
    age = _age_h(f.get("created"), now)
    upd = _age_h(f.get("updated"), now)
    prio = (f.get("priority") or {}).get("name", "")
    return {"key": i["key"], "title": f.get("summary", ""), "status": (f.get("status") or {}).get("name", ""), "priority": prio,
            "prio_rank": PRIO_RANK.get(prio.lower(), 2), "age_h": round(age, 1) if age is not None else None,
            "idle_h": round(upd, 1) if upd is not None else None, "reporter": (f.get("reporter") or {}).get("displayName", ""),
            "due": f.get("duedate") or "", "url": "%s/browse/%s" % (base, i["key"]), "over_sla": bool(age is not None and age >= sla)}


def fetch(client, hc, now=None):
    """client: JiraClient auf die Helpdesk-Instanz. Gibt zugewiesene Tickets und die Queue zurück."""
    now = now or time.time()
    sla = float(hc.get("sla_hours") or 24)
    issues, total = client._search(hc["assigned_jql"], FIELDS, 100)
    out = {"assigned": [item(client.base, i, sla, now) for i in issues], "assigned_total": total, "queue": [], "queue_total": 0,
           "name": hc.get("name") or "Helpdesk", "url": client.base, "sla_hours": sla, "ok": True, "ts": now}
    if hc.get("queue_jql"):
        q, qt = client._search(hc["queue_jql"], FIELDS, 50)
        out["queue"], out["queue_total"] = [item(client.base, i, sla, now) for i in q], qt
    return out


def entries(hd, seen):
    """Einträge für den Fokus: zugewiesene Tickets mit nächstem Schritt; Queue-Tickets, die du noch nicht gesehen hast."""
    if not hd:
        return [], []
    sla = hd.get("sla_hours", 24)
    out = []
    for t in hd.get("assigned") or []:
        why = []
        if t["age_h"] is not None:
            why.append("offen seit %s" % _dur(t["age_h"]))
        if t["over_sla"]:
            why.append("über dem SLA von %d h" % sla)
        if t["idle_h"] is not None and t["idle_h"] >= 24:
            why.append("seit %s ohne Bewegung" % _dur(t["idle_h"]))
        prio = 120 + t["prio_rank"] * 12 + (60 if t["over_sla"] else 0) + min(int((t["age_h"] or 0) // 8), 20)
        out.append(dict(t, id="hd:" + t["key"], prio=prio, outdated=bool(hd.get("outdated")),
                        next={"kind": "do", "id": "hd_work", "label": "Helpdesk bearbeiten" if t["status"].lower() not in ("waiting for customer", "warten auf kunde") else "Antwort prüfen",
                              "why": ("%s (%s). " % (t["status"], t["priority"] or "ohne Priorität")) + (", ".join(why) + "." if why else ""),
                              "owner": "me", "action": {"url": t["url"], "pin": "hd:" + t["key"]}}))
    queue = [dict(t, new=t["key"] not in seen) for t in hd.get("queue") or []]
    return out, queue


def _dur(h):
    if h < 1:
        return "%d min" % max(1, int(h * 60))
    if h < 48:
        return "%d h" % int(h)
    return "%d Tagen" % int(h // 24)
