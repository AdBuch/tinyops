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
    "DLP-120": ("Backlog-Ticket", "In Progress", "Story"),   # nicht im aktiven Sprint
}
ACTIVE_SPRINT = ["com.atlassian.greenhopper.service.sprint.Sprint@1[id=11,rapidViewId=3,state=CLOSED,name=Sprint 11,endDate=2026-10-01T09:00:00.000+0000]",
                 "com.atlassian.greenhopper.service.sprint.Sprint@2[id=12,rapidViewId=3,state=ACTIVE,name=Sprint 12,endDate=2099-11-13T09:00:00.000+0000]"]
LAST = {}
NO_SPRINT = {"DLP-120"}
BASIC = "Basic " + base64.b64encode(b"jira-user:jpass").decode()
VERSION = sys.argv[2] if len(sys.argv) > 2 else "9.4.14"     # Helpdesk-Tests: 8.5.1
SD = [("SD-1", "Drucker spinnt", "Open", "High", 30, 2), ("SD-2", "VPN", "Waiting for customer", "Low", 3, 30),
      ("SD-3", "Neue Lernende", "Open", "Medium", 1, 1)]


def sd_issue(k, s, st, pr, age, upd):
    return {"key": k, "fields": {"summary": s, "status": {"name": st}, "priority": {"name": pr}, "created": jira_time(age),
                                 "updated": jira_time(upd), "reporter": {"displayName": "Kollegin"}, "duedate": None}}


def issue(key):
    s, st, t = ISSUES[key]
    return {"key": key, "fields": {"summary": s, "status": {"name": st}, "issuetype": {"name": t},
                                   "customfield_10020": None if key in NO_SPRINT else ACTIVE_SPRINT}}


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
        if self.path.startswith("/rest/api/2/serverInfo"):
            return self._json(200, {"version": VERSION, "serverTitle": "Mock Jira"})
        if self.path == "/_last":
            return self._json(200, LAST)
        if auth not in ("Bearer jtoken", BASIC):
            return self._json(401, {"errorMessages": ["Unauthorized"]})
        u = urlparse(self.path)
        q = parse_qs(u.query)
        if u.path == "/rest/api/2/field":
            return self._json(200, [{"id": "summary", "name": "Summary"},
                                    {"id": "customfield_10020", "name": "Sprint", "schema": {"custom": "com.pyxis.greenhopper.jira:gh-sprint"}}])
        if u.path == "/rest/api/2/project":
            return self._json(200, [{"key": "DLP"}, {"key": "OPS"}])
        if u.path == "/rest/api/2/project/DLP":
            return self._json(200, {"key": "DLP", "issueTypes": [{"name": "Story"}, {"name": "Bug"}, {"name": "Sub-task", "subtask": True}]})

        if u.path == "/rest/api/2/issuetype":
            return self._json(200, [{"name": "Story"}, {"name": "Bug"}, {"name": "Task"}])
        if u.path == "/rest/api/2/status":
            return self._json(200, [{"name": "To Do"}, {"name": "In Progress"}, {"name": "Done"}])
        if u.path == "/rest/api/2/myself":
            return self._json(200, {"name": "jira-user", "displayName": "Jira User"})
        if u.path.startswith("/rest/api/2/issue/SD-"):
            k = u.path.rsplit("/", 1)[1]
            d = sd_issue(k, "Drucker spinnt", "Open", "High", 30, 2)
            d["fields"].update({"description": "Zeile 1\r\nZeile 2 " + "x" * 7000, "assignee": {"displayName": "Ich"},
                                "comment": {"total": 7, "comments": [{"author": {"displayName": "A%d" % i}, "created": jira_time(i), "body": "Kommentar %d" % i} for i in range(7, 0, -1)]}})
            return self._json(200, d)
        if u.path.startswith("/rest/api/2/issue/"):
            key = unquote(u.path.rsplit("/", 1)[1])
            if key not in ISSUES:
                return self._json(404, {"errorMessages": ["Issue does not exist"]})
            return self._json(200, issue(key))
        if u.path == "/rest/api/2/search":
            jql = (q.get("jql") or [""])[0]
            if jql.startswith("watcher"):
                rows = [("SD-9", "Beobachtet", "Open", "Low", 100, 2), SD[0]]      # SD-1 ist auch zugewiesen: darf nicht doppelt erscheinen
                return self._json(200, {"issues": [dict(sd_issue(*r), **{}) for r in rows], "total": 2})
            if "hdkaputt" in jql:
                return self._json(400, {"errorMessages": ["JQL kaputt"]})
            if "project = SD" in jql:
                rows = SD[:2] if "currentUser()" in jql else SD[2:]
                return self._json(200, {"issues": [sd_issue(*r) for r in rows], "total": len(rows)})
            if "HELP" in jql:
                issues = [{"key": "HELP-%d" % i, "fields": {"created": jira_time(h), "summary": "x"}}
                          for i, h in enumerate((5, 30, 80), 1)]
                return self._json(200, {"issues": issues, "total": 3})
            if "currentUser()" in jql:
                keys = [k for k in ISSUES if k not in ("DLP-110",)]
                if "openSprints()" in jql:
                    keys = [k for k in keys if k not in NO_SPRINT]
                return self._json(200, {"issues": [issue(k) for k in keys], "total": len(keys)})
            return self._json(400, {"errorMessages": ["unbekannte JQL im Mock"]})
        return self._json(404, {})

    def do_POST(self):
        if self.headers.get("Authorization", "") not in ("Bearer jtoken", BASIC):
            return self._json(401, {"errorMessages": ["Unauthorized"]})
        n = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(n) or b"{}")
        if urlparse(self.path).path != "/rest/api/2/issue":
            return self._json(404, {})
        f = body.get("fields", {})
        if (f.get("project") or {}).get("key") == "OPS":
            return self._json(403, {"errorMessages": ["You do not have permission to create issues in this project."]})
        if not f.get("summary"):
            return self._json(400, {"errors": {"summary": "You must specify a summary of the issue."}})
        LAST.clear()
        LAST.update(body)
        return self._json(201, {"id": "10500", "key": "DLP-201", "self": "x"})

    def log_message(self, *a):
        pass


if __name__ == "__main__":
    HTTPServer(("127.0.0.1", int(sys.argv[1])), H).serve_forever()
