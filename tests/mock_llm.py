#!/usr/bin/env python3
"""Fake-Sprachmodell-Server: python3 mock_llm.py PORT. Spricht Ollama (/api/*) und OpenAI-kompatibel (/v1/*).
Authorization: bei /v1 muss 'Bearer lkey' kommen, wenn der Server mit LLM_KEY=1 startet. Modell 'broken' liefert Text statt JSON."""
import json
import os
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer

DRAFT = {"summary": "Retry bei HTTP 429 ergänzen", "description": "h3. Ausgangslage\nAdapter bricht bei 429 ab.\nh3. Ziel\nRetry mit Backoff.\nh3. Akzeptanzkriterien\n* Retry greift\nh3. Offene Fragen\n* Maximale Wartezeit?", "issue_type": "story"}
LAST = {}


class H(BaseHTTPRequestHandler):
    def _json(self, code, body):
        data = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _auth_ok(self):
        return not os.environ.get("LLM_KEY") or self.headers.get("Authorization") == "Bearer lkey"

    def do_GET(self):
        if not self._auth_ok():
            return self._json(401, {"error": "no key"})
        if self.path == "/api/tags":
            return self._json(200, {"models": [{"name": "llama3.2:3b"}, {"name": "broken"}]})
        if self.path == "/v1/models":
            return self._json(200, {"data": [{"id": "qwen2.5-7b"}]})
        if self.path == "/_last":
            return self._json(200, LAST)
        self._json(404, {})

    def do_POST(self):
        if not self._auth_ok():
            return self._json(401, {"error": "no key"})
        n = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(n) or b"{}")
        LAST.clear()
        LAST.update(body)
        text = "Das ist leider kein JSON." if body.get("model") == "broken" else "Hier der Entwurf:\n```json\n" + json.dumps(DRAFT) + "\n```"
        if self.path == "/api/chat":
            return self._json(200, {"message": {"role": "assistant", "content": text}})
        if self.path == "/v1/chat/completions":
            return self._json(200, {"choices": [{"message": {"role": "assistant", "content": text}}]})
        self._json(404, {})

    def log_message(self, *a):
        pass


if __name__ == "__main__":
    HTTPServer(("127.0.0.1", int(sys.argv[1])), H).serve_forever()
