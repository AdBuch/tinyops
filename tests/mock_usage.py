"""Fake für die Kontingent-Schnittstellen von Claude (/api/oauth/usage) und Codex (/backend-api/wham/usage)."""
import json
import sys
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

CALLS = []


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, obj):
        b = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def do_GET(self):
        auth = self.headers.get("Authorization", "")
        if self.path == "/_calls":
            return self._send(200, CALLS)
        CALLS.append({"path": self.path, "method": "GET", "auth": auth, "account": self.headers.get("ChatGPT-Account-ID", ""), "beta": self.headers.get("anthropic-beta", "")})
        now = time.time()
        iso = lambda s: time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now + s))
        if self.path == "/claude/usage":
            if auth != "Bearer claude-ok":
                return self._send(401, {"error": "unauthorized"})
            return self._send(200, {"five_hour": {"utilization": 37.5, "resets_at": iso(2 * 3600)}, "seven_day": None, "seven_day_opus": None})
        if self.path == "/codex/usage":
            if auth != "Bearer codex-ok":
                return self._send(403, {})
            return self._send(200, {"rate_limit": {"primary_window": {"used_percent": 20, "limit_window_seconds": 18000, "reset_at": int(now + 3600)},
                                                   "secondary_window": {"used_percent": 64, "limit_window_seconds": 604800, "reset_at": int(now + 86400)}}})
        if self.path == "/broken/usage":
            return self._send(200, {"hello": "world"})
        self._send(404, {})

    def do_POST(self):
        CALLS.append({"path": self.path, "method": "POST"})
        self._send(405, {})

    do_PUT = do_DELETE = do_PATCH = do_POST


if __name__ == "__main__":
    HTTPServer(("127.0.0.1", int(sys.argv[1])), H).serve_forever()
