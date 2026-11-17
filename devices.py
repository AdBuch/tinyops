"""tinyops als App auf dem Handy (0.36): Geräte koppeln, ohne das Panel für das Netz zu öffnen.

* Am Rechner erzeugst du einen Kopplungscode (8 Zeichen, 5 Minuten gültig, höchstens 5 Fehlversuche).
* Auf dem Handy öffnest du <Adresse>/pair und tippst den Code ein. Das Handy bekommt ein eigenes Geräte-Token als Cookie.
* Gespeichert wird nur der SHA-256 des Tokens. Ein Gerät lässt sich jederzeit entfernen, dann gilt sein Cookie nicht mehr.
* Jede Anfrage, die nicht direkt von diesem Rechner kommt (anderer Host-Name, Proxy-Header, fremde Adresse), braucht
  ein gekoppeltes Gerät oder das Zugriffstoken. Gekoppelte Geräte dürfen keine Einstellungen ändern und keine weiteren Geräte koppeln.
"""
import hashlib
import ipaddress
import re
import secrets
import threading
import time
import urllib.parse

CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"     # ohne 0/O und 1/I
CODE_LEN = 8
CODE_TTL = 300
CODE_TRIES = 5
COOKIE = "tinyops_dev"
SEEN_EVERY = 300
PROXY_HEADERS = ("X-Forwarded-For", "Forwarded", "X-Real-IP", "X-Forwarded-Host", "Tailscale-User-Login")
LOCAL_NAMES = ("localhost", "127.0.0.1", "[::1]", "::1")


class DeviceError(Exception):
    pass


def phone_url(raw):
    """Adresse, unter der das Handy tinyops erreicht. Gibt (adresse, host, fehler) zurück."""
    s = str(raw or "").strip().rstrip("/")
    if not s:
        return "", "", ""
    u = urllib.parse.urlparse(s)
    if u.scheme not in ("http", "https") or not u.hostname or u.path not in ("", "/") or u.query or u.fragment or u.username:
        return "", "", "Adresse wie https://mein-rechner.tailnet.ts.net (ohne Pfad)."
    host = u.hostname.lower()
    if host in LOCAL_NAMES:
        return "", "", "Das ist dieser Rechner. Das Handy braucht die Adresse, unter der es den Rechner erreicht."
    try:
        ip = ipaddress.ip_address(host)
        if not (ip.is_private or ip.is_link_local):
            return "", "", "Keine öffentliche IP-Adresse. Nimm einen VPN- oder Tailscale-Namen oder eine Adresse im eigenen Netz."
    except ValueError:
        pass
    return "%s://%s" % (u.scheme, u.netloc.lower()), host, ""


def is_remote(client_ip, host_header, headers):
    """Kommt die Anfrage von woanders als diesem Rechner? Auch ein Proxy auf diesem Rechner (Tailscale serve, Caddy) zählt als «woanders»."""
    host = (host_header or "").lower()
    host = host.rsplit(":", 1)[0] if not host.endswith("]") else host
    if host not in LOCAL_NAMES:
        return True
    if any(headers.get(h) for h in PROXY_HEADERS):
        return True
    try:
        return not ipaddress.ip_address(client_ip).is_loopback
    except ValueError:
        return True


def _hash(tok):
    return hashlib.sha256(("tinyops-device:" + tok).encode("utf-8")).hexdigest()


def clean_name(s, ua=""):
    s = " ".join(str(s or "").split())[:40]
    if s:
        return re.sub(r"[<>\"'`]", "", s)
    ua = ua or ""
    for k, n in (("iPhone", "iPhone"), ("iPad", "iPad"), ("Android", "Android"), ("Windows", "Windows"), ("Macintosh", "Mac"), ("Linux", "Linux")):
        if k in ua:
            return n
    return "Gerät"


class Devices:
    def __init__(self, store, now=time.time):
        self.store, self.now = store, now
        self.lock = threading.Lock()
        self.codes = {}          # code -> {"until": ts, "tries": n}
        self.claims = []         # Zeitpunkte der letzten Einlöse-Versuche (alle Codes), gegen Durchprobieren

    # -- am Rechner
    def new_code(self):
        with self.lock:
            now = self.now()
            self.codes = {c: v for c, v in self.codes.items() if v["until"] > now}
            if len(self.codes) >= 3:
                raise DeviceError("Es laufen schon drei Codes. Warte, bis einer abläuft, oder koppel zuerst ein Gerät.")
            code = "".join(secrets.choice(CODE_ALPHABET) for _ in range(CODE_LEN))
            self.codes[code] = {"until": now + CODE_TTL, "tries": 0}
            return {"code": code[:4] + "-" + code[4:], "expires": int(now + CODE_TTL), "ttl": CODE_TTL}

    def list(self):
        return self.store.device_list()

    def revoke(self, did):
        if not self.store.device_revoke(int(did)):
            raise DeviceError("Dieses Gerät gibt es nicht (mehr).")

    # -- auf dem Handy
    def claim(self, code, name, ua=""):
        """Code einlösen. Gibt (cookie_wert, gerät) zurück. Falsche Codes zählen gegen alle offenen Codes."""
        c = re.sub(r"[^A-Z0-9]", "", str(code or "").upper())
        with self.lock:
            now = self.now()
            self.claims = [t for t in self.claims if now - t < 60] + [now]
            if len(self.claims) > 10:
                raise DeviceError("Zu viele Versuche. In einer Minute nochmals.")
            hit = self.codes.get(c)
            if not hit or hit["until"] < now:
                for v in self.codes.values():      # jeder Fehlversuch kostet jeden offenen Code einen Versuch
                    v["tries"] += 1
                self.codes = {k: v for k, v in self.codes.items() if v["tries"] < CODE_TRIES and v["until"] > now}
                raise DeviceError("Der Code stimmt nicht oder ist abgelaufen. Am Rechner einen neuen erzeugen.")
            del self.codes[c]
        tok = secrets.token_urlsafe(32)
        dev = self.store.device_add(clean_name(name, ua), _hash(tok), now)
        return "%d.%s" % (dev["id"], tok), dev

    def check(self, cookie_header):
        """Gültiges Gerät aus dem Cookie oder None. Merkt sich «zuletzt gesehen» höchstens alle 5 Minuten."""
        val = ""
        for part in (cookie_header or "").split(";"):
            k, _, v = part.strip().partition("=")
            if k == COOKIE:
                val = v
        did, _, tok = val.partition(".")
        if not did.isdigit() or len(tok) < 20:
            return None
        dev = self.store.device_get(int(did))
        if not dev or dev["revoked"] or not secrets.compare_digest(dev["hash"], _hash(tok)):
            return None
        if self.now() - (dev["last_seen"] or 0) > SEEN_EVERY:
            self.store.device_seen(dev["id"], self.now())
        return dev


def cookie(value, secure, clear=False):
    attrs = ["%s=%s" % (COOKIE, "" if clear else value), "HttpOnly", "SameSite=Lax", "Path=/", "Max-Age=%d" % (0 if clear else 365 * 86400)]
    if secure:
        attrs.append("Secure")
    return "; ".join(attrs)


PAIR_PAGE = """<!doctype html><html lang="de"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>tinyops koppeln</title><link rel="manifest" href="/manifest.webmanifest"><link rel="icon" href="/icon.svg"><meta name="theme-color" content="#2747d6">
<style>
:root{color-scheme:light dark;--ink:#161a21;--quiet:#596271;--line:#d8dce3;--bg:#eceef1;--surface:#fff;--accent:#2747d6;--bad:#bc2d26}
@media (prefers-color-scheme:dark){:root{--ink:#e8ebf1;--quiet:#9aa3b2;--line:#29303b;--bg:#0f1217;--surface:#171b22;--accent:#7d93ff;--bad:#ff8a80}}
body{margin:0;background:var(--bg);color:var(--ink);font:16px/1.5 system-ui,sans-serif;display:grid;place-items:center;min-height:100vh}
main{background:var(--surface);border:1px solid var(--line);border-radius:18px;padding:28px 22px;width:min(380px,calc(100vw - 32px));box-sizing:border-box}
h1{font-size:22px;margin:12px 0 6px}p{color:var(--quiet);margin:0 0 18px;font-size:15px}
label{display:block;font-size:13px;font-weight:600;margin:14px 0 6px}
input{width:100%;box-sizing:border-box;font:inherit;padding:12px;border:1px solid var(--line);border-radius:10px;background:var(--bg);color:var(--ink)}
#code{font:600 24px ui-monospace,monospace;letter-spacing:.15em;text-align:center;text-transform:uppercase}
button{margin-top:18px;width:100%;font:600 16px system-ui,sans-serif;padding:13px;border:0;border-radius:11px;background:var(--accent);color:#fff}
#msg{color:var(--bad);font-size:14px;min-height:20px;margin-top:10px}
</style></head><body><main>
<img src="/icon.svg" width="48" height="48" alt="">
<h1>Dieses Gerät mit tinyops koppeln</h1>
<p>Am Rechner: Einstellungen → App und Handy → «Code erzeugen». Der Code gilt 5 Minuten.</p>
<form id="f"><label for="code">Code</label><input id="code" autocomplete="one-time-code" inputmode="text" maxlength="9" placeholder="ABCD-EFGH" required autofocus>
<label for="name">Name dieses Geräts</label><input id="name" maxlength="40" placeholder="z. B. Mein Handy">
<button type="submit">Koppeln</button><div id="msg" role="status"></div></form>
</main><script>
document.getElementById('f').onsubmit = async ev => {
  ev.preventDefault();
  const m = document.getElementById('msg'); m.textContent = '';
  try {
    const r = await fetch('/api/pair/claim', { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-Requested-With': 'tinyops' },
      body: JSON.stringify({ code: document.getElementById('code').value, name: document.getElementById('name').value }) });
    const j = await r.json();
    if (!r.ok) { m.textContent = j.error || 'Hat nicht geklappt.'; return; }
    location.replace('/');
  } catch (e) { m.textContent = 'tinyops ist nicht erreichbar.'; }
};
</script></body></html>
"""

NOT_PAIRED_PAGE = """<!doctype html><html lang="de"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>tinyops</title><style>body{font:16px/1.5 system-ui,sans-serif;display:grid;place-items:center;min-height:100vh;margin:0}main{max-width:340px;padding:20px}
a{display:inline-block;margin-top:12px;padding:12px 18px;border-radius:11px;background:#2747d6;color:#fff;text-decoration:none;font-weight:600}</style></head>
<body><main><h1>Noch nicht gekoppelt</h1><p>Dieses Gerät darf tinyops erst sehen, wenn du es am Rechner gekoppelt hast.</p><a href="/pair">Jetzt koppeln</a></main></body></html>
"""

MANIFEST = {
    "name": "tinyops", "short_name": "tinyops", "description": "Dein Arbeitspanel: Fokus, Reviews, Agenten, Zeit.",
    "start_url": "/", "scope": "/", "display": "standalone", "background_color": "#eceef1", "theme_color": "#2747d6", "lang": "de",
    "icons": [{"src": "/icon.svg", "sizes": "any", "type": "image/svg+xml"},
              {"src": "/icon-192.png", "sizes": "192x192", "type": "image/png"},
              {"src": "/icon-512.png", "sizes": "512x512", "type": "image/png"},
              {"src": "/icon-maskable.png", "sizes": "512x512", "type": "image/png", "purpose": "maskable"}],
}

# Service Worker: nur die Hülle (Seite und Icons) für den Start ohne Netz. Daten (/api/…) nie im Cache, damit nichts auf dem Gerät liegen bleibt.
SERVICE_WORKER = """const C = 'tinyops-shell-%s';
const SHELL = ['/', '/icon.svg', '/icon-192.png'];
self.addEventListener('install', e => { e.waitUntil(caches.open(C).then(c => c.addAll(SHELL)).then(() => self.skipWaiting())); });
self.addEventListener('activate', e => { e.waitUntil(caches.keys().then(ks => Promise.all(ks.filter(k => k !== C).map(k => caches.delete(k)))).then(() => self.clients.claim())); });
self.addEventListener('fetch', e => {
  const u = new URL(e.request.url);
  if (e.request.method !== 'GET' || u.origin !== location.origin || u.pathname.startsWith('/api/') || u.pathname === '/pair') return;
  if (e.request.mode === 'navigate') {
    e.respondWith(fetch(e.request).then(r => { if (r.ok) { const cp = r.clone(); caches.open(C).then(c => c.put('/', cp)); } return r; }).catch(() => caches.match('/')));
    return;
  }
  if (SHELL.includes(u.pathname)) e.respondWith(caches.match(e.request).then(r => r || fetch(e.request)));
});
"""
