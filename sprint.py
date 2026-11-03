"""Sprint-Hilfen für Jira Software: JQL um «nur aktive Sprints» erweitern, Sprint-Feld lesen."""
import re

ORDER_RE = re.compile(r"\border\s+by\b", re.I)
HAS_SPRINT_RE = re.compile(r"\bsprint\s*(=|!=|~|in\b|not\b|is\b)", re.I)
ACTIVE = "sprint in openSprints()"


def effective_jql(jql, only_active):
    """Hängt «sprint in openSprints()» an, vor ORDER BY. Hat die JQL schon eine eigene Sprint-Bedingung, bleibt sie unverändert."""
    jql = (jql or "").strip()
    if not only_active or HAS_SPRINT_RE.search(jql):
        return jql
    m = ORDER_RE.search(jql)
    head, tail = (jql[:m.start()].strip(), jql[m.start():]) if m else (jql, "")
    head = "(%s) AND %s" % (head, ACTIVE) if head else ACTIVE
    return head + ((" " + tail) if tail else "")


def parse_sprints(value):
    """Liest den Wert des Sprint-Feldes. Jira 9 liefert Texte wie
    'com.atlassian.greenhopper.service.sprint.Sprint@1a2b[id=12,state=ACTIVE,name=Sprint 12,endDate=2026-11-13T09:00:00.000+01:00]',
    neuere Versionen Objekte. Ergebnis: Liste aus {name, state, end}."""
    out = []
    if value is None:
        return out
    if not isinstance(value, list):
        value = [value]
    for v in value:
        if isinstance(v, dict):
            out.append({"name": str(v.get("name") or ""), "state": str(v.get("state") or "").lower(),
                        "end": str(v.get("endDate") or "") if v.get("endDate") not in (None, "<null>") else ""})
        elif isinstance(v, str):
            st = re.search(r"state=(\w+)", v)
            nm = re.search(r"name=(.*?)(?:,\w+=|\])", v)
            en = re.search(r"endDate=([^,\]]+)", v)
            end = en.group(1) if en else ""
            out.append({"name": nm.group(1) if nm else "", "state": (st.group(1) if st else "").lower(),
                        "end": "" if end == "<null>" else end})
    return out


def active_sprint(value):
    """Der aktive Sprint aus dem Feldwert oder None."""
    for s in parse_sprints(value):
        if s["state"] == "active":
            return s
    return None
