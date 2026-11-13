"""Tickets zu Tasks gruppieren (0.30).

Ein Task ist, woran du wirklich arbeitest. Oft ist das ein einzelnes Ticket. Manchmal gehören mehrere Jira-Tickets zusammen:
* ein Bug und sein Begleitticket (Story/Aufgabe für Doku, Test oder Auslieferung): der Bug ist der Task,
* eine Story und ihre Unteraufgaben: die Story ist der Task.

Zusammen gehören Tickets in Arbeit, wenn sie in Jira miteinander verknüpft sind (Issue-Links, optional nur bestimmte Link-Typen),
eines das Elternticket des anderen ist, oder du sie von Hand gruppiert hast. Von Hand gilt immer vor der Erkennung.
"""
import re

BUG_TYPES = ("bug", "fehler", "defect", "defekt", "störung", "incident")
KEY_RE = re.compile(r"^[A-Z][A-Z0-9_]{0,30}-\d{1,9}$")


def is_bug(t):
    return (t.get("type") or "").strip().lower() in BUG_TYPES


def _key_order(k):
    p, _, n = k.rpartition("-")
    return (p, int(n) if n.isdigit() else 0)


def build(tickets, manual=None, link_types=(), counted=()):
    """tickets: Tickets in Arbeit (key, type, links=[{key, type}], parent). manual: {key: head} – head «» heisst «eigenständig».
    Gibt (heads, head_of) zurück: heads sind die Tasks mit «companions», head_of bildet jedes Begleitticket auf seinen Task ab."""
    manual = manual or {}
    lt = {x.strip().lower() for x in link_types or () if x and x.strip()}
    ct = {x.strip().lower() for x in counted or () if x and x.strip()}
    by = {t["key"]: t for t in tickets}
    parent = {k: k for k in by}

    def find(k):
        while parent[k] != k:
            parent[k] = parent[parent[k]]
            k = parent[k]
        return k

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra
    alone = {k for k, h in manual.items() if h == "" and k in by}
    for t in tickets:
        k = t["key"]
        if k in alone or k in manual:
            continue                                   # von Hand gesetzt: keine Erkennung für dieses Ticket
        for ln in t.get("links") or []:
            o = ln.get("key")
            if o in by and o not in alone and o not in manual and (not lt or (ln.get("type") or "").lower() in lt):
                union(k, o)
        p = t.get("parent")
        if p in by and p not in alone and p not in manual:
            union(p, k)
    for k, h in manual.items():
        if k in by and h and h in by and h != k:
            union(h, k)
    comps = {}
    for k in by:
        comps.setdefault(find(k), []).append(k)
    heads, head_of = [], {}
    for members in comps.values():
        members.sort(key=_key_order)
        forced = [manual[k] for k in members if manual.get(k) in members]
        subtask_parents = [by[k].get("parent") for k in members if by[k].get("parent") in members]
        head = (forced[0] if forced else next((k for k in members if is_bug(by[k])), None)
                or (subtask_parents[0] if subtask_parents else None)
                or next((k for k in members if (by[k].get("type") or "").lower() in ct), None) or members[0])
        h = dict(by[head])
        h["companions"] = [dict(by[k], why=_why(by[head], by[k], manual)) for k in members if k != head]
        h["counts"] = (not ct) or any((by[k].get("type") or "").lower() in ct for k in members)
        h["grouped_by_hand"] = bool(forced) or any(manual.get(k) == head for k in members)
        for k in members:
            if k != head:
                head_of[k] = head
        heads.append(h)
    heads.sort(key=lambda h: _key_order(h["key"]))
    return heads, head_of


def _why(head, t, manual):
    if manual.get(t["key"]) == head["key"]:
        return "von Hand"
    if t.get("parent") == head["key"]:
        return "Unteraufgabe"
    ln = next((x for x in t.get("links") or [] if x.get("key") == head["key"]), None) or \
        next((x for x in head.get("links") or [] if x.get("key") == t["key"]), None)
    if ln:
        return "Begleitticket (%s)" % ln.get("type") if is_bug(head) else "verknüpft (%s)" % ln.get("type")
    return "über ein anderes Ticket verknüpft"


def links_of(fields):
    """Issue-Links aus den Jira-Feldern: [{key, type}], Richtung egal."""
    out = []
    for ln in (fields or {}).get("issuelinks") or []:
        o = ln.get("outwardIssue") or ln.get("inwardIssue") or {}
        tp = (ln.get("type") or {})
        name = tp.get("outward") if ln.get("outwardIssue") else tp.get("inward")
        if o.get("key"):
            out.append({"key": o["key"], "type": tp.get("name") or name or ""})
    return out
