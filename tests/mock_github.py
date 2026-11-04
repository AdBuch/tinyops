#!/usr/bin/env python3
"""Fake-GitHub-API für Tests: python3 mock_github.py PORT. Token: ghtoken (Bearer). Ich bin «adrian».
Repo adrian/hooks (ID 42): PR #7 von mir (approved von octocat, 1 Daumen, Checks grün), PR #8 von bob. Branches: wip/mine (von mir), wip/other (von bob).
Repo team/core (ID 77) nur über die Suche: PR #3 von carol, Review von mir angefragt, Checks laufen. Repo adrian/secret: 404."""
import json
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, unquote, urlparse

TOKEN = "ghtoken"
METHODS = []
HOST = "http://127.0.0.1"

REPOS = {"adrian/hooks": {"id": 42, "full_name": "adrian/hooks", "default_branch": "main", "private": True},
         "team/core": {"id": 77, "full_name": "team/core", "default_branch": "main", "private": False}}


def pr(n, user, ref, sha, repo_id, draft=False, title=None):
    return {"number": n, "title": title or "PR %d" % n, "user": {"login": user}, "draft": draft, "html_url": "%s/web/pr/%d" % (HOST, n),
            "updated_at": "2026-11-01T10:00:00Z", "head": {"ref": ref, "sha": sha, "repo": {"id": repo_id}}, "requested_reviewers": [{"login": "octocat"}] if n == 7 else []}


PULLS = {"adrian/hooks": [pr(7, "adrian", "feature/DLP-7-hooks", "s7", 42, title="DLP-7 Webhooks"), pr(8, "bob", "bob/x", "s8", 42)],
         "team/core": [pr(3, "carol", "fix/thing", "s3", 77, title="Fix thing")]}


def commit(login, email, name, msg="work"):
    return {"author": {"login": login} if login else None, "commit": {"author": {"email": email, "name": name}, "committer": {"date": "2026-11-02T10:00:00Z"}, "message": msg}}


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _json(self, code, body):
        data = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("X-RateLimit-Remaining", "4990")
        self.send_header("X-RateLimit-Limit", "5000")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self):
        METHODS.append("POST " + self.path)
        self._json(405, {"message": "nope"})

    do_PATCH = do_PUT = do_DELETE = do_POST

    def do_GET(self):
        u = urlparse(self.path)
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        p = unquote(u.path)
        if p == "/_methods":
            return self._json(200, METHODS)
        METHODS.append("GET " + p)
        if self.headers.get("Authorization") != "Bearer " + TOKEN:
            return self._json(401, {"message": "Bad credentials"})
        if self.headers.get("User-Agent") != "tinyops":
            return self._json(403, {"message": "User-Agent fehlt"})
        if p == "/user":
            return self._json(200, {"login": "adrian", "name": "Adrian", "email": "adrian@example.com"})
        if p == "/user/repos":
            return self._json(200, list(REPOS.values()))
        if p == "/search/issues":
            if "review-requested:adrian" in q.get("q", ""):
                return self._json(200, {"items": [{"number": 3, "repository_url": HOST + "/repos/team/core"}]})
            return self._json(200, {"items": []})
        parts = p.strip("/").split("/")
        if parts[0] != "repos" or len(parts) < 3:
            return self._json(404, {"message": "Not Found"})
        full = parts[1] + "/" + parts[2]
        if full not in REPOS:
            return self._json(404, {"message": "Not Found"})
        repo = dict(REPOS[full], html_url="%s/web/%s" % (HOST, full))
        rest = parts[3:]
        if not rest:
            return self._json(200, repo)
        if rest == ["pulls"]:
            return self._json(200, PULLS[full])
        if rest[0] == "pulls" and len(rest) == 2:
            x = next((x for x in PULLS[full] if str(x["number"]) == rest[1]), None)
            return self._json(200, dict(x, mergeable_state="clean")) if x else self._json(404, {})
        if rest[0] == "pulls" and rest[2:] == ["reviews"]:
            return self._json(200, [{"user": {"login": "octocat"}, "state": "COMMENTED"}, {"user": {"login": "octocat"}, "state": "APPROVED"}] if rest[1] == "7" else [])
        if rest[0] == "issues" and rest[2:] == ["reactions"]:
            return self._json(200, [{"content": "+1"}] if rest[1] == "7" else [])
        if rest[0] == "commits" and rest[2:] == ["check-runs"]:
            sha = rest[1]
            runs = {"s7": [{"status": "completed", "conclusion": "success"}], "s3": [{"status": "in_progress", "conclusion": None}]}.get(sha, [])
            return self._json(200, {"total_count": len(runs), "check_runs": runs})
        if rest[0] == "commits" and rest[2:] == ["status"]:
            return self._json(200, {"state": "pending", "total_count": 0})
        if rest == ["branches"]:
            return self._json(200, [{"name": "main", "commit": {"sha": "m"}, "protected": True}, {"name": "feature/DLP-7-hooks", "commit": {"sha": "s7"}},
                                    {"name": "wip/mine", "commit": {"sha": "b1"}}, {"name": "wip/other", "commit": {"sha": "b2"}}])
        if rest[0] == "compare":
            spec = "/".join(rest[1:])
            if spec.endswith("wip/mine"):
                return self._json(200, {"commits": [commit("adrian", "noreply@github", "A", "Retry eingebaut")]})
            return self._json(200, {"commits": [commit("bob", "bob@example.com", "Bob")]})
        return self._json(404, {"message": "Not Found"})


if __name__ == "__main__":
    port = int(sys.argv[1])
    HOST = "http://127.0.0.1:%d" % port
    HTTPServer(("127.0.0.1", port), H).serve_forever()
