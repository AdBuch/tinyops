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
        if u.path == "/api/issues/search":
            if q.get("componentKeys") != "dlp-core":
                return self._json(404, {})
            pr, br = q.get("pullRequest"), q.get("branch")
            if pr == "8":
                allv = [{"component": "dlp-core:src/Repo.java", "line": 40 + n, "severity": "MAJOR", "type": "CODE_SMELL", "rule": "java:S100", "message": "Rename method %d" % n}
                        for n in range(250)]
                allv.insert(0, {"component": "dlp-core:src/Auth.java", "line": 7, "severity": "BLOCKER", "type": "VULNERABILITY", "rule": "java:S2068",
                                "impacts": [{"softwareQuality": "SECURITY", "severity": "HIGH"}, {"softwareQuality": "MAINTAINABILITY", "severity": "LOW"}],
                                "message": "Hard-coded   credential\nremove it " + "x" * 400})
                ps, p = int(q.get("ps", 100)), int(q.get("p", 1))
                return self._json(200, {"total": len(allv), "paging": {"pageIndex": p, "pageSize": ps, "total": len(allv)},
                                        "issues": allv[(p - 1) * ps:p * ps],
                                        "facets": [{"property": "impactSeverities", "values": [{"val": "HIGH", "count": 1}, {"val": "MEDIUM", "count": 250}]},
                                                   {"property": "impactSoftwareQualities", "values": [{"val": "SECURITY", "count": 1}, {"val": "MAINTAINABILITY", "count": 250}]},
                                                   {"property": "severities", "values": [{"val": "BLOCKER", "count": 1}, {"val": "MAJOR", "count": 250}]},
                                                   {"property": "types", "values": [{"val": "VULNERABILITY", "count": 1}, {"val": "CODE_SMELL", "count": 250}]}]})
            if pr == "7":
                return self._json(200, {"paging": {"total": 0}, "issues": [], "facets": []})
            if br == "kaputt":
                return self._json(500, {})
            return self._json(404, {})
        if u.path == "/api/project_pull_requests/list":
            return self._json(200 if q.get("project") == "dlp-core" else 404, {"pullRequests": [{"key": "7"}, {"key": "8"}]})
        if u.path == "/api/measures/search_history":
            if q.get("component") != "dlp-core":
                return self._json(404, {})
            if q.get("pullRequest") == "8":
                series = {"violations": [12, 9, 7, 3], "bugs": [3, 2, 2, 1], "vulnerabilities": [1, 1, 0, 0], "code_smells": [8, 6, 5, 2], "coverage": [50.5, 58.0, 61.2, 70.0]}
                dates = ["2026-11-01T09:00:00+0100", "2026-11-02T09:00:00+0100", "2026-11-03T09:00:00+0100", "2026-11-04T09:00:00+0100"]
                ms = [{"metric": m, "history": [{"date": d, "value": str(series[m][i])} for i, d in enumerate(dates)]} for m in q.get("metrics", "").split(",") if m in series]
                ms += [{"metric": "new_violations", "history": [{"date": d} for d in dates]}] if "new_violations" in q.get("metrics", "") else []   # Sonar liefert für new_* nur Daten
                return self._json(200, {"measures": ms})
            if q.get("pullRequest") == "7":
                return self._json(200, {"measures": [{"metric": "violations", "history": [{"date": "2026-11-04T09:00:00+0100", "value": "0"}]}]})
            if q.get("branch") == "kaputt":
                return self._json(500, {})
            return self._json(200, {"measures": []})
        if u.path == "/api/hotspots/search":
            if q.get("pullRequest") == "8":
                return self._json(200, {"paging": {"total": 1}, "hotspots": [{"component": "dlp-core:src/Crypto.java", "line": 12, "vulnerabilityProbability": "HIGH",
                                                                           "securityCategory": "weak-cryptography", "message": "Weak hash"}]})
            return self._json(403, {"errors": [{"msg": "Insufficient privileges"}]})
        self._json(404, {})

    def log_message(self, *a):
        pass


if __name__ == "__main__":
    HTTPServer(("127.0.0.1", int(sys.argv[1])), H).serve_forever()
