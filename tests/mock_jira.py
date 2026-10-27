#!/usr/bin/env python3
"""Minimaler Fake-Jira 9.4 für Tests: python3 mock_jira.py 9102
Auth: Bearer jtoken ODER Basic jira-user:jpass. Zeitstempel im Jira-Format (+0000 ohne Doppelpunkt)."""
import base64
import json
import sys
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, unquote, urlparse

ISSUES = {
    "DLP-101": ("Vendex Retry", "In Progress", "Story"),
    "DLP-102": ("Helm Limits", "In Progress", "Story"),
    "DLP-103": ("Ein Bug", "In Progress", "Bug"),
    "DLP-110": ("Review-Ticket", "In Review", "Story"),
}
BASIC = "Basic " + base64.b64encode(b"jira-user:jpass").decode()


def issue(key):
    s, st, t = ISSUES[key]
    return {"key": key, "fields": {"summary": s, "status": {"name": st}, "issuetype": {"name": t}}}


def jira_time(hours_ago):
    t = datetime.now(timezone.utc) - timedelta(hours=hours_ago)
    return t.strftime("%Y-%m-%dT%H:%M:%S.000+0000")


class H(BaseHTTPRequestHandler):
    def _json(self, code, body):
        data = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        auth = self.headers.get("Authorization", "")
        if auth not in ("Bearer jtoken", BASIC):
            return self._json(401, {"errorMessages": ["Unauthorized"]})
        u = urlparse(self.path)
        q = parse_qs(u.query)
        if u.path == "/rest/api/2/myself":
            return self._json(200, {"name": "jira-user", "displayName": "Jira User"})
        if u.path.startswith("/rest/api/2/issue/"):
            key = unquote(u.path.rsplit("/", 1)[1])
            if key not in ISSUES:
                return self._json(404, {"errorMessages": ["Issue does not exist"]})
            return self._json(200, issue(key))
        if u.path == "/rest/api/2/search":
            jql = (q.get("jql") or [""])[0]
            if "HELP" in jql:
                issues = [{"key": "HELP-%d" % i, "fields": {"created": jira_time(h), "summary": "x"}}
                          for i, h in enumerate((5, 30, 80), 1)]
                return self._json(200, {"issues": issues, "total": 3})
            if "currentUser()" in jql:
                keys = list(ISSUES)[:3]
                return self._json(200, {"issues": [issue(k) for k in keys], "total": len(keys)})
            return self._json(400, {"errorMessages": ["unbekannte JQL im Mock"]})
        return self._json(404, {})

    def log_message(self, *a):
        pass


if __name__ == "__main__":
    HTTPServer(("127.0.0.1", int(sys.argv[1])), H).serve_forever()
