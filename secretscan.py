"""Geheimnis-Scan (0.27): sucht in neu hinzugefügten Zeilen eines Diffs nach Zugangsdaten, bevor etwas gepusht wird.

tinyops pusht nie selbst. Der Scan zeigt, was in ungepushten Commits, offenen Änderungen und im Ergebnis eines Agenten nach einem Geheimnis aussieht.
Er erkennt Muster, kein Wissen: Ein Fund ist ein Hinweis zum Nachsehen, kein Fund ist kein Freibrief. Gezeigt werden Datei, Zeile, Regel und die Länge des Werts, nie der Wert selbst.
Eine Zeile mit `tinyops:allow-secret` wird übersprungen (für Testdaten, die wie ein Geheimnis aussehen).
"""
import re

MAX_FINDINGS = 40
MAX_LINE = 2000
ALLOW = "tinyops:allow-secret"
SKIP_FILES = re.compile(r"(?:^|/)(?:package-lock\.json|yarn\.lock|pnpm-lock\.yaml|poetry\.lock|Cargo\.lock|go\.sum|composer\.lock|Pipfile\.lock)$|\.(?:min\.js|map|svg|png|jpg|jpeg|gif|pdf|ico|woff2?)$", re.I)
PLACEHOLDER = re.compile(r"(?i)^(?:x{3,}|\*{3,}|\.{3,}|changeme|change[-_]?me|example|beispiel|dummy|test|secret|password|passwort|geheim|todo|none|null|true|false|"
                         r"<[^>]*>|\$\{[^}]*\}|\{\{[^}]*\}\}|%\([^)]*\)s|\$[A-Z_][A-Z0-9_]*|your[-_a-z]*|dein[-_a-z]*|placeholder|redacted|entfernt)$")
LOOKUP = re.compile(r"(?i)(?:os\.environ|getenv|process\.env|System\.getenv|secrets\.|vault|keyring|config\.get|settings\.|props\.|\$\{|\{\{)")

RULES = [
    ("Privater Schlüssel", re.compile(r"-----BEGIN (?:RSA |EC |DSA |OPENSSH |PGP |ENCRYPTED )?PRIVATE KEY(?: BLOCK)?-----")),
    ("GitLab-Token", re.compile(r"\bgl(?:pat|dt|rt|cbt|ptt|soat)-[A-Za-z0-9_-]{16,}")),
    ("GitHub-Token", re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,})")),
    ("AWS-Zugangsschlüssel", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")),
    ("API-Schlüssel (sk-…)", re.compile(r"\bsk-(?:ant-|proj-)?[A-Za-z0-9_-]{24,}")),
    ("Slack-Token", re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{12,}")),
    ("JWT", re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{8,}")),
    ("Zugangsdaten in URL", re.compile(r"\b[a-z][a-z0-9+.-]{1,12}://[^/\s:@'\"]{1,60}:([^/\s:@'\"]{3,80})@[A-Za-z0-9.-]+")),
    ("Bearer-Token", re.compile(r"(?i)\bauthorization\b.{0,12}\b(?:bearer|basic)\s+([A-Za-z0-9._~+/=-]{20,})")),
    ("Passwort oder Token im Klartext", re.compile(r"(?i)\b[\w.-]{0,30}(?:passw(?:or[dt])?|passwd|pwd|kennwort|secret|token|api[_-]?key|access[_-]?key|private[_-]?key|client[_-]?secret)[\w.-]{0,20}"
                                                    r"[\"']?\s*[:=]\s*(?:\"([^\"\n]{6,200})\"|'([^'\n]{6,200})'|([^\s\"',;#]{8,200}))")),
]
GENERIC = RULES[-1][0]
HUNK = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@")


def _short(value):
    return "… (%d Zeichen)" % len(value.strip())


def check_line(line):
    """(Regel, gekürzte Fundstelle) oder None für eine Zeile."""
    if ALLOW in line or len(line) > MAX_LINE:
        return None
    for name, rx in RULES:
        m = rx.search(line)
        if not m:
            continue
        val = next((g for g in m.groups() if g), None) or m.group(0)
        if name == GENERIC:
            if PLACEHOLDER.match(val.strip()) or LOOKUP.search(val) or len(set(val)) < 5 or val.strip().endswith(("(", "{", "[")):
                continue
            if re.fullmatch(r"[A-Za-z_][\w.]*(?:\([^)]*\))?", val.strip()) and not re.search(r"\d", val):      # Verweis auf eine Variable oder Funktion
                continue
        elif name == "Zugangsdaten in URL" and PLACEHOLDER.match(val.strip()):
            continue
        return name, _short(val)
    return None


def scan_diff(text, where=""):
    """Hinzugefügte Zeilen eines Unified Diffs prüfen (auch `git log -p`: Zeilen «commit:<sha>» setzen den Ort). Gibt Funde zurück."""
    out, path, line_no, commit = [], "", 0, ""
    for raw in (text or "").splitlines():
        if raw.startswith("commit:"):
            commit = raw[7:].strip()[:12]
        elif raw.startswith("+++ "):
            path = raw[4:].strip()
            path = "" if path == "/dev/null" else (path[2:] if path[:2] in ("a/", "b/") else path)
        elif raw.startswith("@@"):
            m = HUNK.match(raw)
            line_no = int(m.group(1)) if m else 0
        elif raw.startswith("+") and not raw.startswith("+++"):
            if path and not SKIP_FILES.search(path):
                hit = check_line(raw[1:])
                if hit:
                    out.append({"file": path[:300], "line": line_no, "rule": hit[0], "excerpt": hit[1], "where": ("Commit " + commit) if commit else where})
                    if len(out) >= MAX_FINDINGS:
                        break
            line_no += 1
        elif raw.startswith(" "):
            line_no += 1
    return out


def summary(findings):
    n = len(findings)
    if not n:
        return ""
    files = sorted({f["file"] for f in findings})
    return "%d mögliche%s Geheimnis%s in %s" % (n, "s" if n == 1 else "", "" if n == 1 else "se", files[0] if len(files) == 1 else "%d Dateien" % len(files))
