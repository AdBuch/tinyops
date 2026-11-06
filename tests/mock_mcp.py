#!/usr/bin/env python3
"""Fake-Wrapper-API eines MCP für Projectron: python3 mock_mcp.py PORT. Token: mcptoken (Bearer).
POST /time-entries bucht (Referenz PRJ-<n>), gleicher Idempotency-Key → gleiche Buchung. Ticket REJ-1 wird abgelehnt,
Ticket BAD-1 bekommt eine Antwort ohne status, Ticket ERR-1 einen HTTP 500. GET /_log zeigt alle Anfragen."""
import json
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer

LOG, BOOKED = [], {}


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _json(self, code, body):
        data = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path == "/_log":
            return self._json(200, {"log": LOG, "booked": BOOKED})
        LOG.append({"method": "GET", "path": self.path})
        if self.headers.get("Authorization") != "Bearer mcptoken":
            return self._json(401, {"message": "Token fehlt"})
        return self._json(405, {"message": "nur POST"})

    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(n) or b"{}")
        key = self.headers.get("Idempotency-Key", "")
        LOG.append({"method": "POST", "path": self.path, "key": key, "ticket": body.get("ticket"), "minutes": body.get("minutes"), "schema": body.get("schema")})
        if self.headers.get("Authorization") != "Bearer mcptoken":
            return self._json(401, {"message": "Token fehlt"})
        t = body.get("ticket")
        if t == "REJ-1":
            return self._json(422, {"status": "rejected", "message": "Ticket in Projectron unbekannt"})
        if t == "BAD-1":
            return self._json(200, {"ok": True})
        if t == "ERR-1":
            return self._json(500, {"message": "intern"})
        if key not in BOOKED:
            BOOKED[key] = "PRJ-%d" % (len(BOOKED) + 1)
        return self._json(200, {"id": body.get("id"), "status": "booked", "reference": BOOKED[key], "message": "gebucht"})


if __name__ == "__main__":
    HTTPServer(("127.0.0.1", int(sys.argv[1])), H).serve_forever()
