"""Gemeinsame Bausteine von tinyops (0.37 aus server.py gelöst): Fehlerarten, Zeit- und Textwerkzeuge, Jira-Keys, Secrets auflösen."""
import fnmatch
import re
import sys
import urllib.parse
from datetime import datetime, timezone

import net
import secretstore as store

LOOPBACK = ("127.0.0.1", "localhost", "::1")


class UserError(Exception):
    data = None         # optional: weitere Felder für die Antwort (z. B. duplicate)


class HttpStatus(UserError):
    def __init__(self, msg, code):
        super().__init__(msg)
        self.code = code


def ignored_branch(name, patterns):
    """Passt der Branch auf eines der Muster (zum Beispiel release/*)? Groß-/Kleinschreibung zählt."""
    return any(fnmatch.fnmatchcase(name, p) for p in patterns if p)


def slug(text, limit=30):
    s = re.sub(r"[^a-z0-9]+", "-", str(text).lower()).strip("-")[:limit].strip("-")
    return s or "x"


def parse_ts(iso):
    if not iso:
        return None
    s = str(iso).replace("Z", "+00:00")
    s = re.sub(r"([+-]\d\d)(\d\d)$", r"\1:\2", s)   # Jira liefert +0200 statt +02:00
    try:
        return datetime.fromisoformat(s)
    except ValueError:
        return None


def _delta_seconds(iso):
    ts = parse_ts(iso)
    if ts is None:
        return 0.0
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return max(0.0, (datetime.now(timezone.utc) - ts).total_seconds())


def age_days(iso):
    return int(_delta_seconds(iso) // 86400)


def hours_since(iso):
    return _delta_seconds(iso) / 3600.0


def _age_key(iso):
    """Sortierschlüssel: neueste zuerst, unbekannte Daten ans Ende."""
    return _delta_seconds(iso) if parse_ts(iso) else 1e12


def render(template, values):
    """Ersetzt nur bekannte {name}-Platzhalter, Klammern im Rest bleiben."""
    return re.sub(r"\{(\w+)\}", lambda m: str(values.get(m.group(1), m.group(0))), template)


KEY_RE = re.compile(r"(?<![A-Za-z0-9])([A-Za-z][A-Za-z0-9]{1,9}-\d{1,7})(?![A-Za-z0-9])")
DENY_PREFIXES = {"UTF", "SHA", "MD", "ISO", "TLS", "SSL", "AES", "RSA", "HTTP", "HTTPS",
                 "RFC", "CVE", "CWE", "JDK", "JAVA", "PR", "MR"}


def extract_keys(text, allowed=None):
    """Jira-Keys (z. B. DLP-123) aus Branchnamen und Titeln.

    Mit `allowed` (jira.project_keys) zählen nur diese Projekte, auch kleingeschrieben (feature/dlp-123).
    Ohne `allowed` zählen nur GROSS geschriebene Keys, sonst würde 'sonar-wave-1' als Ticket gelten."""
    allowed = {a.upper() for a in (allowed or [])}
    out = []
    for m in KEY_RE.finditer(text or ""):
        key = m.group(1).upper()
        prefix = key.rsplit("-", 1)[0]
        if allowed:
            if prefix not in allowed:
                continue
        elif not m.group(1).isupper() or prefix in DENY_PREFIXES:
            continue
        if key not in out:
            out.append(key)
    return out


def make_ssl(cfg):
    try:
        return net.make_ssl_ca(cfg.get("ca_bundle"))
    except ValueError as e:
        raise SystemExit(str(e))


def warn_plain_http(url, label):
    host = urllib.parse.urlparse(url).hostname or ""
    if url.lower().startswith("http://") and host not in LOOPBACK:
        sys.stderr.write("Warnung: %s läuft über http://. Der Zugangstoken geht unverschlüsselt über das Netz.\n" % label)


def _env_hints(cfg):
    return {"gitlab_token": [cfg.get("token_env")]}


def _stored(app):
    def stored(name):
        try:
            return store.resolve(name, (app.cfg.get("secrets") or {}).get(name), _env_hints(app.cfg).get(name, ()))
        except store.SecretError:
            return None, ""
    return stored
