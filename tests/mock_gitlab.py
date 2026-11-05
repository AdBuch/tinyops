#!/usr/bin/env python3
"""Minimaler Fake-GitLab für Tests: python3 mock_gitlab.py 9100  (Token: secret)"""
import json
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse

NOW = "2026-10-22T10:00:00.000Z"
OLD = "2026-10-01T10:00:00.000+02:00"


def mr(iid, title, branch, sha, draft, updated, author):
    return {"iid": iid, "project_id": 1, "title": title, "source_branch": branch, "sha": sha,
            "web_url": "https://g/x/-/merge_requests/%d" % iid, "draft": draft,
            "updated_at": updated, "author": {"username": author}}


MR_A = mr(7, "Feature A", "feature/DLP-101-a", "abcdef1234567890", False, NOW, "me")
MR_B = mr(8, "Draft B", "feature-b", "1234567890abcdef", True, OLD, "me")
MR_R = mr(9, "DLP-110 Kollege C", "feature-c", "fedcba0987654321", False, NOW, "kollege")
MR_REL = mr(12, "Release-Merge", "release/1.5", "99887766aabbccdd", False, NOW, "me")
MR_Z = mr(11, "Zugeteilt D", "feature/DLP-102-d", "0011223344556677", False, NOW, "kollege")
MR_A.update(detailed_merge_status="mergeable", reviewers=[{"username": "kollege"}], upvotes=1)   # wie GitLab ab 15.6

ROUTES = {
    "/api/v4/user": {"username": "me", "email": "me@x.ch"},
    "/api/v4/version": {"version": "19.2.5-ee", "revision": "abc"},
    "/api/v4/personal_access_tokens/self": {"scopes": ["read_api"], "expires_at": "2027-01-01"},
    "/api/v4/projects": [{"id": 1, "name": "dlp-core", "path": "dlp-core", "path_with_namespace": "dlp/dlp-core"}],
    "/api/v4/projects/1/repository/commits": [
        {"author_name": "Me Myself", "author_email": "me@x.ch", "message": "a"},
        {"author_name": "Me Myself", "author_email": "me@x.ch", "message": "b\n\nCo-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"},
        {"author_name": "Me Myself", "author_email": "me@x.ch", "message": "c\n\nCo-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"},
        {"author_name": "Bot", "author_email": "bot@x.ch", "message": "d"},
        {"author_name": "Kollege", "author_email": "k@x.ch", "message": "e"},
    ],
    "/api/v4/projects/1": {"id": 1, "name": "dlp-core", "path": "dlp-core", "path_with_namespace": "dlp/dlp-core", "default_branch": "main", "web_url": "https://g/x"},
    "/api/v4/projects/1/merge_requests": [MR_A, MR_B, MR_REL],
    "/api/v4/projects/1/merge_requests/7": MR_A,
    "/api/v4/projects/1/merge_requests/8": MR_B,
    "/api/v4/projects/1/merge_requests/9": MR_R,
    "/api/v4/projects/1/merge_requests/7/approvals": {"approved_by": [{"user": {"username": "kollege"}}], "approvals_left": 0, "approved": True},
    "/api/v4/projects/1/pipelines": [{"status": "success", "web_url": "https://g/x/-/pipelines/1"}],
    "/api/v4/projects/1/repository/branches": [
        {"name": "main", "merged": False, "protected": True, "commit": {"author_email": "me@x.ch"}},
        {"name": "feature/DLP-101-a", "merged": False, "protected": False, "commit": {"author_email": "me@x.ch"}},
        {"name": "idea-old", "merged": False, "protected": False,
         "commit": {"author_email": "me@x.ch", "committed_date": OLD, "title": "alte Idee", "id": "aaaa"}},
        {"name": "other-person", "merged": False, "protected": False,
         "commit": {"author_email": "x@y.ch", "committed_date": NOW, "title": "fremd", "id": "bbbb"}},
        {"name": "agent/DLP-130-retry", "merged": False, "protected": False,
         "commit": {"author_email": "bot@x.ch", "committed_date": NOW, "title": "agent", "id": "cccc"}},
        {"name": "kollege-claude", "merged": False, "protected": False,
         "commit": {"author_email": "k@x.ch", "committed_date": NOW, "title": "kollege", "id": "dddd"}},
        {"name": "mixed", "merged": False, "protected": False,
         "commit": {"author_email": "k@x.ch", "committed_date": NOW, "title": "gemischt", "id": "eeee"}},
        {"name": "release/2.0", "merged": False, "protected": False,
         "commit": {"author_email": "me@x.ch", "committed_date": NOW, "title": "release-arbeit", "id": "ffff"}},
        {"name": "done", "merged": True, "protected": False, "commit": {"author_email": "me@x.ch"}},
    ],
}


def C(email, msg="x", name=""):
    return {"author_email": email, "author_name": name, "message": msg, "title": msg}


COMPARE = {
    "idea-old": [C("me@x.ch"), C("me@x.ch")],
    "release/2.0": [C("me@x.ch")],
    "other-person": [C("x@y.ch")],
    "agent/DLP-130-retry": [C("bot@x.ch", "Co-Authored-By: Claude")],
    "kollege-claude": [C("k@x.ch", "Co-Authored-By: Claude")],
    "mixed": [C("k@x.ch"), C("me@x.ch", "fix\n\nCo-Authored-By: Claude")],
}


class H(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.headers.get("PRIVATE-TOKEN") != "secret":
            data = b'{"message":"401 Unauthorized"}'
            self.send_response(401)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return
        u = urlparse(self.path)
        if u.path == "/api/v4/merge_requests":
            q = parse_qs(u.query)
            if "reviewer_username" in q:
                body = [MR_R]
            elif "assignee_username" in q:
                body = [MR_Z, MR_A, MR_R]   # MR_A ist von mir, MR_R schon in der Review-Queue
            else:
                body = []
        elif u.path == "/api/v4/projects/1/repository/compare":
            body = {"commits": COMPARE.get(parse_qs(u.query).get("to", [""])[0], [])}
        else:
            body = ROUTES.get(u.path)
        if body is None:
            self.send_response(404)
            self.end_headers()
            return
        data = json.dumps(body).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *a):
        pass


if __name__ == "__main__":
    HTTPServer(("127.0.0.1", int(sys.argv[1])), H).serve_forever()
