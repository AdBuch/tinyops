"""Review-Befunde aus dem Text eines Agenten (0.44.1).

Der Weg für Befunde ist `tinyops-finding` (eine JSON-Zeile je Befund). Nicht jeder Agent ruft das Hilfsprogramm auf:
manche schreiben die Punkte nur in ihren Bericht oder in die letzte Antwort. Dann liest tinyops sie dort, in dieser Reihenfolge:
1. ein Block ```findings mit einer Zeile je Befund: `pfad:zeile | schwere | text` (so steht es im Auftrag als Ausweg),
2. ein JSON-Block mit einer Liste von Objekten (path/file, line, text/message/comment/body, severity),
3. eine Markdown-Tabelle mit Spalten wie Datei, Zeile, Befund, Schwere,
4. Aufzählungspunkte, die eine Stelle `pfad:zeile` (oder «pfad, Zeile 42») nennen.
Was so gefunden wird, ist als «aus dem Bericht» markiert; du siehst und änderst es vor dem Anlegen in GitLab."""
import json
import re

SEVERITIES = ("hoch", "mittel", "klein")
_SEV = (("hoch", r"hoch|kritisch|critical|blocker|high|major|wichtig|security|sicherheit"),
        ("klein", r"klein|kleinigkeit|nit|nitpick|minor|low|niedrig|stil|style"),
        ("mittel", r"mittel|medium|normal|moderate"))
_PATH = r"(?:[\w.\-]+/)*[\w.\-]+\.[A-Za-z0-9]{1,8}"
_LOC = re.compile(r"`?(?P<path>%s)`?(?::(?P<line>\d{1,6})(?:[-–]\d+)?|,?\s*(?:Zeile|Zeilen|line|L)\.?\s*(?P<line2>\d{1,6}))?`?" % _PATH)
_BULLET = re.compile(r"^\s*(?:[-*+•]|\d{1,3}[.)])\s+(?P<rest>.+)$")
_SKIP_EXT = {"md": 0, "txt": 0}


def severity_of(text):
    low = (text or "").lower()
    for sev, rx in _SEV:
        if re.search(r"(?<![a-zäöü])(%s)(?![a-zäöü])" % rx, low):
            return sev
    return "mittel"


def clean_path(p):
    p = str(p or "").strip().strip("`'\"")
    while p.startswith(("./", "/")):
        p = p[2:] if p.startswith("./") else p[1:]
    if not p or ".." in p.split("/") or len(p) > 300 or " " in p:
        return ""
    return p


def _mk(path, line, text, sev=None, source="bericht"):
    path = clean_path(path)
    try:
        n = max(0, int(line or 0))
    except (TypeError, ValueError):
        n = 0
    text = " ".join(str(text or "").split())[:2000]
    text = re.sub(r"^[\s:–—\-|]+", "", text).strip()
    if not path or len(text) < 3:
        return None
    s = sev if sev in SEVERITIES else severity_of(sev or text)
    return {"path": path, "line": n, "text": text, "severity": s, "from": source}


def _blocks(text):
    return re.findall(r"```([\w-]*)[ \t]*\n(.*?)```", text or "", re.S)


def _from_findings_block(body):
    out = []
    for ln in body.splitlines():
        parts = [p.strip() for p in ln.split("|")]
        if len(parts) < 2 or not parts[0]:
            continue
        m = _LOC.fullmatch(parts[0].strip("`")) or _LOC.match(parts[0])
        if not m:
            continue
        sev = parts[1] if len(parts) >= 3 else None
        txt = " | ".join(parts[2:]) if len(parts) >= 3 else parts[1]
        f = _mk(m.group("path"), m.group("line") or m.group("line2"), txt, (sev or "").lower() or None)
        if f:
            out.append(f)
    return out


def _from_json(body):
    try:
        d = json.loads(body)
    except ValueError:
        return []
    if isinstance(d, dict):
        d = d.get("findings") or d.get("befunde") or d.get("comments") or []
    out = []
    for x in d if isinstance(d, list) else []:
        if not isinstance(x, dict):
            continue
        f = _mk(x.get("path") or x.get("file") or x.get("datei"), x.get("line") or x.get("zeile") or x.get("new_line"),
                x.get("text") or x.get("message") or x.get("comment") or x.get("body") or x.get("befund"),
                str(x.get("severity") or x.get("schwere") or x.get("priority") or "").lower() or None)
        if f:
            out.append(f)
    return out


def _from_table(text):
    out, cols = [], None
    for ln in (text or "").splitlines():
        if not ln.strip().startswith("|"):
            cols = None
            continue
        cells = [c.strip() for c in ln.strip().strip("|").split("|")]
        if all(re.fullmatch(r":?-{2,}:?", c) for c in cells if c):
            continue
        low = [c.lower() for c in cells]
        if cols is None:
            idx = lambda *names: next((i for i, c in enumerate(low) if any(n in c for n in names)), None)
            cols = {"path": idx("datei", "file", "pfad", "ort", "stelle", "location"), "line": idx("zeile", "line"),
                    "text": idx("befund", "finding", "kommentar", "comment", "problem", "beschreibung", "issue", "text"),
                    "sev": idx("schwere", "severity", "prio", "gewicht")}
            if cols["path"] is None or cols["text"] is None:
                cols = None
            continue
        get = lambda k: cells[cols[k]] if cols.get(k) is not None and cols[k] < len(cells) else ""
        m = _LOC.search(get("path"))
        if not m:
            continue
        f = _mk(m.group("path"), get("line") or m.group("line") or m.group("line2"), get("text"), get("sev").lower() or None)
        if f:
            out.append(f)
    return out


def _from_bullets(text):
    out = []
    for ln in (text or "").splitlines():
        b = _BULLET.match(ln)
        if not b:
            continue
        rest = b.group("rest")
        m = _LOC.search(rest)
        if not m or not (m.group("line") or m.group("line2")) and "`" not in rest[m.start():m.end() + 1]:
            continue                                        # ohne Zeile nur, wenn der Pfad als Code markiert ist
        if m.group("path").rsplit(".", 1)[-1].lower() in _SKIP_EXT and not (m.group("line") or m.group("line2")):
            continue
        before, after = rest[:m.start()], rest[m.end():]
        txt = (after if len(after.strip(" :–—-*")) >= 3 else before).strip()
        txt = re.sub(r"\*\*(?:hoch|mittel|klein|wichtig|kritisch|blocker|nit|minor|major)\*\*:?", "", txt, flags=re.I)
        f = _mk(m.group("path"), m.group("line") or m.group("line2"), txt.strip(" *_:–—-"), severity_of(before + " " + after[:40]))
        if f:
            out.append(f)
    return out


def from_report(*texts):
    """Befunde aus Bericht und letzter Antwort. Erster Weg, der etwas findet, gewinnt; Doppeltes fällt weg."""
    text = "\n\n".join(t for t in texts if t)
    if not text.strip():
        return []
    found = []
    for lang, body in _blocks(text):
        if lang.lower() in ("findings", "befunde", "tinyops-findings"):
            found += _from_findings_block(body)
    if not found:
        for lang, body in _blocks(text):
            if lang.lower() in ("json", "") and body.lstrip()[:1] in "[{":
                found += _from_json(body)
    if not found:
        plain = re.sub(r"```.*?```", "", text, flags=re.S)
        found = _from_table(plain) or _from_bullets(plain)
    seen, out = set(), []
    for f in found:
        k = (f["path"], f["line"], f["text"][:80].lower())
        if k not in seen:
            seen.add(k)
            out.append(f)
    return out[:100]


def clean_list(items):
    """Von der Oberfläche bearbeitete Befunde prüfen (Pfad, Zeile, Schwere, Text)."""
    out = []
    for x in (items or [])[:100]:
        if not isinstance(x, dict):
            continue
        f = _mk(x.get("path"), x.get("line"), x.get("text"), x.get("severity") if x.get("severity") in SEVERITIES else "mittel",
                source=x.get("from") if x.get("from") in ("agent", "bericht", "du") else "du")
        if f:
            out.append(f)
    return out
