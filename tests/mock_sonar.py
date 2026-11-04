#!/usr/bin/env python3
"""Fake-SonarQube für Tests: python3 mock_sonar.py PORT. Token: sqtoken (Basic sqtoken:). Projekt dlp-core.
MR 7: Gate OK. MR 8: ERROR (Abdeckung). Branch feature-b: WARN. MR 9: 404 (keine Analyse). Branch 'kaputt': HTTP 500."""
import base64
import json
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse

TOKEN = "sqtoken"
CALLS = []


def gate(status, conds=()):
    return {"projectStatus": {"status": status, "conditions": list(conds)}}


COND_COV = {"status": "ERROR", "metricKey": "new_coverage", "comparator": "LT", "errorThreshold": "80", "actualValue": "61.2"}
COND_VUL = {"status": "ERROR", "metricKey": "new_vulnerabilities", "comparator": "GT", "errorThreshold": "0", "actualValue": "2"}


class H(BaseHTTPRequestHandler):
    def _json(self, code, body):
        data = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _auth(self):
        a = self.headers.get("Authorization", "")
        return a == "Basic " + base64.b64encode((TOKEN + ":").encode()).decode()

    def do_GET(self):
        u = urlparse(self.path)
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        if u.path == "/_calls":
            return self._json(200, CALLS)
        CALLS.append(self.path)
        if u.path == "/api/system/status":
            return self._json(200, {"id": "x", "version": "10.6.0", "status": "UP"})
        if not self._auth():
            return self._json(401, {"errors": [{"msg": "Authentication required"}]})
        if u.path == "/api/authentication/validate":
            return self._json(200, {"valid": True})
        if u.path == "/api/components/show":
            return self._json(200 if q.get("component") == "dlp-core" else 404, {"component": {"key": q.get("component")}})
        if u.path == "/api/qualitygates/project_status":
            if q.get("projectKey") != "dlp-core":
                return self._json(404, {"errors": [{"msg": "Project not found"}]})
            pr, br = q.get("pullRequest"), q.get("branch")
            if pr == "7":
                return self._json(200, gate("OK"))
            if pr == "8":
                return self._json(200, gate("ERROR", [COND_COV, COND_VUL, {"status": "OK", "metricKey": "new_bugs", "comparator": "GT", "errorThreshold": "0", "actualValue": "0"}]))
            if br == "feature-b":
                return self._json(200, gate("WARN", [{"status": "WARN", "metricKey": "new_duplicated_lines_density", "comparator": "GT", "errorThreshold": "3", "actualValue": "4.1"}]))
            if br == "kaputt":
                return self._json(500, {"errors": [{"msg": "boom"}]})
            return self._json(404, {"errors": [{"msg": "not found"}]})
        self._json(404, {})

    def log_message(self, *a):
        pass


if __name__ == "__main__":
    HTTPServer(("127.0.0.1", int(sys.argv[1])), H).serve_forever()
