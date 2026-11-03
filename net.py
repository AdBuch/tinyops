"""Netzwerk-Grundlagen für tinyops: TLS-Kontext, Anfragen ohne Weiterleitung, klare Fehlerarten.

Folgt nie einer Weiterleitung (Zugangsdaten gehen so nie an einen anderen Host) und schaltet die
Zertifikatsprüfung nie ab.
"""
import json
import socket
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path


class NoRedirect(urllib.request.HTTPRedirectHandler):
    """Folgt keinen Weiterleitungen: Zugangsdaten gehen so nie an einen anderen Host."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class NetError(Exception):
    """kind: dns, refused, timeout, unreachable, tls_verify, tls_hostname, tls_expired, tls, reset, other."""

    def __init__(self, kind, detail):
        super().__init__(detail)
        self.kind = kind
        self.detail = detail


def make_ssl_ca(ca):
    """TLS-Kontext mit Systemzertifikaten, optional mit eigener CA-Datei (PEM). Gibt ValueError bei Problemen."""
    if ca:
        p = Path(ca).expanduser()
        if not p.is_file():
            raise ValueError("CA-Datei %s nicht gefunden." % ca)
        try:
            return ssl.create_default_context(cafile=str(p))
        except (ssl.SSLError, OSError) as e:
            raise ValueError("CA-Datei %s lässt sich nicht laden (kein gültiges PEM?): %s" % (ca, e))
    return ssl.create_default_context()


def classify(exc):
    """Übersetzt eine Python-Ausnahme in (kind, Klartext)."""
    r = exc.reason if isinstance(exc, urllib.error.URLError) else exc
    if isinstance(r, ssl.SSLCertVerificationError):
        msg = (getattr(r, "verify_message", "") or str(r)).strip()
        low = msg.lower()
        if "hostname" in low or "doesn't match" in low or "ip address mismatch" in low:
            return "tls_hostname", "Das Zertifikat gilt nicht für diesen Namen (%s)." % msg
        if "expired" in low:
            return "tls_expired", "Das Zertifikat ist abgelaufen (%s)." % msg
        return "tls_verify", "Das Zertifikat wird nicht als vertrauenswürdig erkannt (%s)." % msg
    if isinstance(r, ssl.SSLError):
        return "tls", "TLS-Verbindung fehlgeschlagen: %s" % r
    if isinstance(r, socket.gaierror):
        return "dns", "Der Name lässt sich nicht auflösen (%s)." % (r.strerror or r)
    if isinstance(r, ConnectionRefusedError):
        return "refused", "Die Verbindung wurde abgelehnt: an dieser Adresse und diesem Port lauscht nichts."
    if isinstance(r, (socket.timeout, TimeoutError)):
        return "timeout", "Zeitüberschreitung: keine Antwort."
    if isinstance(r, ConnectionResetError):
        return "reset", "Die Gegenstelle hat die Verbindung abgebrochen."
    if isinstance(r, OSError) and getattr(r, "errno", None) in (101, 113):
        return "unreachable", "Der Server ist von hier nicht erreichbar (keine Route, Firewall oder VPN fehlt)."
    return "other", str(r)


def probe(url, headers=None, ctx=None, timeout=8, max_body=262144):
    """GET ohne Weiterleitung. Liefert dict(status, headers, body, ms). Fehlerhafte HTTP-Status sind normale Antworten.
    Netzwerkfehler werden zu NetError."""
    req = urllib.request.Request(url, headers=headers or {})
    opener = urllib.request.build_opener(NoRedirect, urllib.request.HTTPSHandler(context=ctx or ssl.create_default_context()))
    t0 = time.time()
    try:
        with opener.open(req, timeout=timeout) as r:
            body = r.read(max_body)
            return {"status": r.status, "headers": {k.lower(): v for k, v in r.headers.items()}, "body": body,
                    "ms": int((time.time() - t0) * 1000)}
    except urllib.error.HTTPError as e:
        try:
            body = e.read(max_body)
        except Exception:
            body = b""
        return {"status": e.code, "headers": {k.lower(): v for k, v in (e.headers or {}).items()}, "body": body,
                "ms": int((time.time() - t0) * 1000)}
    except (urllib.error.URLError, OSError) as e:
        kind, detail = classify(e)
        raise NetError(kind, detail)


def parse_json(resp):
    try:
        return json.loads(resp["body"].decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return None


def looks_html(resp):
    ct = resp["headers"].get("content-type", "").lower()
    head = resp["body"][:200].lstrip().lower()
    return "html" in ct or head.startswith(b"<!doctype html") or head.startswith(b"<html")


def check_dns(host, port):
    """Gibt (Adressen, ms) zurück oder wirft NetError."""
    t0 = time.time()
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except socket.gaierror as e:
        raise NetError("dns", "Der Name «%s» lässt sich nicht auflösen (%s)." % (host, e.strerror or e))
    ips = []
    for i in infos:
        if i[4][0] not in ips:
            ips.append(i[4][0])
    return ips, int((time.time() - t0) * 1000)


def check_tcp(host, port, timeout=5):
    t0 = time.time()
    try:
        with socket.create_connection((host, port), timeout=timeout):
            pass
    except OSError as e:
        kind, detail = classify(e)
        raise NetError(kind, detail)
    return int((time.time() - t0) * 1000)


def check_tls(host, port, ctx, timeout=6):
    """TLS-Handshake mit Prüfung. Gibt Zertifikatsinfos zurück oder wirft NetError."""
    try:
        with socket.create_connection((host, port), timeout=timeout) as raw:
            with ctx.wrap_socket(raw, server_hostname=host) as s:
                cert = s.getpeercert() or {}
                ver = s.version()
    except (ssl.SSLError, OSError) as e:
        kind, detail = classify(e)
        raise NetError(kind, detail)

    def name(seq):
        d = {k: v for rdn in (seq or ()) for k, v in rdn}
        return d.get("commonName") or d.get("organizationName") or "?"
    days = None
    exp = cert.get("notAfter")
    if exp:
        try:
            days = int((ssl.cert_time_to_seconds(exp) - time.time()) // 86400)
        except ValueError:
            pass
    return {"subject": name(cert.get("subject")), "issuer": name(cert.get("issuer")), "days_left": days, "version": ver,
            "san": [v for k, v in cert.get("subjectAltName", ()) if k == "DNS"][:6]}


def host_port(url):
    u = urllib.parse.urlparse(url)
    port = u.port or (443 if u.scheme == "https" else 80)
    return u.hostname, port, u.scheme
