"""GitHub (github.com oder GitHub Enterprise), nur lesend: eigene Pull Requests, eigene Branches, Review-Anfragen und zugewiesene PRs.

tinyops stellt nur GET-Anfragen. Ein feingranularer Token mit Lesezugriff reicht: «Metadata», «Contents», «Pull requests»,
«Commit statuses» und «Checks» jeweils «Read-only» (für Review-Anfragen in fremden Repos zusätzlich Zugriff auf diese Repos).
Die Einträge haben dieselbe Form wie die aus GitLab; die Projektnummer ist 10**12 + Repo-ID, damit sie nie mit GitLab-IDs kollidiert.
"""
import json
import re
import threading
import time
import urllib.parse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

import net
import secretstore as store
import tlog

log = tlog.get("github")
PID_BASE = 10 ** 12
REPO_RE = re.compile(r"^[A-Za-z0-9_.-]{1,100}/[A-Za-z0-9_.-]{1,100}$")
API_DEFAULT = "https://api.github.com"


class GitHubError(Exception):
    def __init__(self, msg, status=0):
        super().__init__(msg)
        self.status = status


def pid_of(repo_id):
    return PID_BASE + int(repo_id)


def is_github_pid(pid):
    try:
        return int(pid) >= PID_BASE
    except (TypeError, ValueError):
        return False


def headers(token):
    return {"Authorization": "Bearer " + token, "Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "tinyops"}


def _age_days(iso):
    try:
        ts = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
    except ValueError:
        return 0
    return max(0, int((datetime.now(timezone.utc) - ts).total_seconds() // 86400))


def auth_msg(st, body=None):
    msg = (body or {}).get("message", "") if isinstance(body, dict) else ""
    if st == 401:
        return "GitHub: Anmeldung abgelehnt (HTTP 401). Token ungültig oder abgelaufen."
    if st == 403 and "rate limit" in msg.lower():
        return "GitHub: Anfragelimit erreicht (HTTP 403). In einer Stunde ist es wieder frei; mit Token gilt ein höheres Limit."
    return "GitHub: keine Berechtigung (HTTP %d)%s. Dem Token fehlt Lesezugriff auf dieses Repo (feingranularer Token: Repo freigeben)." % (st, (": " + msg) if msg else "")


class Client:
    def __init__(self, api_url, token, ctx=None, timeout=15):
        self.api = (api_url or API_DEFAULT).rstrip("/")
        self.token, self.ctx, self.timeout = token, ctx, timeout
        self._repo_cache = {}
        self._bcache = {}
        self.lock = threading.Lock()
        store.register(token)

    # -- HTTP
    def get(self, path, params=None, max_body=4 << 20):
        url = self.api + path + (("?" + urllib.parse.urlencode(params)) if params else "")
        t0 = time.time()
        try:
            r = net.probe(url, headers(self.token), self.ctx, timeout=self.timeout, max_body=max_body)
        except net.NetError as e:
            raise GitHubError("GitHub nicht erreichbar (%s)." % e.detail)
        data = net.parse_json(r)
        log.debug("GET %s → %s in %d ms", path, r["status"], int((time.time() - t0) * 1000))
        if r["status"] in (401, 403):
            raise GitHubError(auth_msg(r["status"], data), r["status"])
        if r["status"] != 200:
            raise GitHubError("GitHub %s: HTTP %s" % (path, r["status"]), r["status"])
        if data is None:
            raise GitHubError("GitHub %s: Antwort ist kein JSON (falsche API-Adresse?)" % path)
        return data

    def user(self):
        return self.get("/user")

    def repo(self, full):
        with self.lock:
            if full in self._repo_cache:
                return self._repo_cache[full]
        r = self.get("/repos/%s" % full)
        with self.lock:
            self._repo_cache[full] = r
        return r

    def search_repos(self, q, limit=30):
        """Eigene und freigegebene Repos, gefiltert. «owner/name» findet auch ein einzelnes Repo ausserhalb der Liste."""
        q = (q or "").strip()
        out = []
        if REPO_RE.fullmatch(q):
            try:
                r = self.repo(q)
                out.append(r)
            except GitHubError:
                pass
        for r in self.get("/user/repos", {"per_page": 100, "sort": "pushed", "affiliation": "owner,collaborator,organization_member"}):
            if not q or q.lower() in r.get("full_name", "").lower():
                if r["id"] not in {x["id"] for x in out}:
                    out.append(r)
            if len(out) >= limit:
                break
        return [{"id": r["id"], "full": r["full_name"], "name": r["full_name"], "private": bool(r.get("private")), "default_branch": r.get("default_branch", "main")} for r in out]

    # -- Status eines Commits: Checks (Actions) und klassische Status zusammen
    def pipeline(self, full, sha):
        if not sha:
            return "none", ""
        state = "none"
        try:
            cr = self.get("/repos/%s/commits/%s/check-runs" % (full, sha), {"per_page": 100})
            runs = cr.get("check_runs") or []
            if runs:
                if any(r.get("status") != "completed" for r in runs):
                    state = "running"
                elif any(r.get("conclusion") in ("failure", "timed_out", "cancelled", "action_required", "startup_failure") for r in runs):
                    state = "failed"
                else:
                    state = "success"
        except GitHubError as e:
            log.debug("Checks %s@%s nicht lesbar: %s", full, sha[:8], e)
        if state in ("none", "success"):
            try:
                st = self.get("/repos/%s/commits/%s/status" % (full, sha))
                if st.get("total_count"):
                    s = {"success": "success", "failure": "failed", "error": "failed", "pending": "running"}.get(st.get("state"), "none")
                    if s != "success" or state == "none":
                        state = s
            except GitHubError as e:
                log.debug("Status %s@%s nicht lesbar: %s", full, sha[:8], e)
        return state, ""

    def reviews(self, full, number):
        """(approved_by, changes_requested_by): zählt die letzte Bewertung je Person."""
        last = {}
        for r in self.get("/repos/%s/pulls/%s/reviews" % (full, number), {"per_page": 100}):
            login = (r.get("user") or {}).get("login") or ""
            if r.get("state") in ("APPROVED", "CHANGES_REQUESTED", "DISMISSED"):
                last[login] = r["state"]
        return sorted(k for k, v in last.items() if v == "APPROVED"), sorted(k for k, v in last.items() if v == "CHANGES_REQUESTED")

    def thumbs(self, full, number):
        try:
            return len(self.get("/repos/%s/issues/%s/reactions" % (full, number), {"content": "+1", "per_page": 100}))
        except GitHubError:
            return 0

    # -- Einträge
    def _pr_item(self, full, repo, pr, kind, detail=True):
        number = pr["number"]
        head = pr.get("head") or {}
        item = {"kind": kind, "project_id": pid_of(repo["id"]), "project": full, "title": pr.get("title", ""), "branch": head.get("ref", ""),
                "iid": number, "url": pr.get("html_url", ""), "draft": bool(pr.get("draft")), "pipeline": "none", "pipeline_url": pr.get("html_url", "") + "/checks",
                "updated_at": pr.get("updated_at", ""), "sha": head.get("sha", ""), "author": (pr.get("user") or {}).get("login", ""), "can_deploy": False,
                "merge_status": "", "reviewers": [u.get("login", "") for u in (pr.get("requested_reviewers") or [])], "upvotes": 0, "host": "github",
                "approved": None, "approved_by": [], "approvals_left": None, "age_days": _age_days(pr.get("updated_at", ""))}
        if detail:
            item["pipeline"], _ = self.pipeline(full, item["sha"])
            try:
                full_pr = self.get("/repos/%s/pulls/%s" % (full, number))
                item["merge_status"] = {"dirty": "conflict", "behind": "need_rebase", "clean": "mergeable", "draft": "draft_status"}.get(full_pr.get("mergeable_state"), "")
                item["reviewers"] = [u.get("login", "") for u in (full_pr.get("requested_reviewers") or [])]
            except GitHubError as e:
                log.debug("PR %s#%s: %s", full, number, e)
            try:
                ok, changes = self.reviews(full, number)
                item["approved_by"], item["approved"] = ok, bool(ok) and not changes
                if changes:
                    item["merge_status"] = item["merge_status"] or "discussions_not_resolved"
                item["reviewers"] = sorted(set(item["reviewers"]) | set(ok) | set(changes))
            except GitHubError as e:
                log.debug("Reviews %s#%s: %s", full, number, e)
                item["approval_unknown"] = True
            item["upvotes"] = self.thumbs(full, number)
        return item

    def fetch_repo(self, full, me, ident, classify, bf, ignored):
        """Eigene PRs und eigene Branches eines Repos."""
        repo = self.repo(full)
        default = repo.get("default_branch") or "main"
        html = repo.get("html_url", "")
        out = []
        pulls = self.get("/repos/%s/pulls" % full, {"state": "open", "per_page": 100})
        heads = {(p.get("head") or {}).get("ref") for p in pulls if ((p.get("head") or {}).get("repo") or {}).get("id") == repo["id"]}
        for pr in pulls:
            if (pr.get("user") or {}).get("login") != me or ignored((pr.get("head") or {}).get("ref", "")):
                continue
            out.append(self._pr_item(full, repo, pr, "mr"))
        branches = self.get("/repos/%s/branches" % full, {"per_page": 100})
        checked = 0
        for b in branches:
            bn = b.get("name", "")
            if bn == default or bn in heads or b.get("protected") or ignored(bn):
                continue
            if checked >= int(bf.get("max_branches", 40)):
                break
            checked += 1
            sha = (b.get("commit") or {}).get("sha", "")
            key = (full, bn, sha)
            info = self._bcache.get(key)
            if info is None:
                try:
                    cmp_ = self.get("/repos/%s/compare/%s...%s" % (full, urllib.parse.quote(default, safe=""), urllib.parse.quote(bn, safe="")))
                except GitHubError as e:
                    log.debug("%s: Vergleich %s fehlgeschlagen: %s", full, bn, e)
                    continue
                commits = cmp_.get("commits") or []
                mapped = [{"author_email": ((c.get("commit") or {}).get("author") or {}).get("email", ""),
                           "author_name": ((c.get("commit") or {}).get("author") or {}).get("name", ""),
                           "message": (c.get("commit") or {}).get("message", "")} for c in commits]
                info = classify(mapped, ident)
                if any((c.get("author") or {}).get("login") == me for c in commits):
                    info = dict(info, by_me=True, include=True)
                last = commits[-1] if commits else {}
                info["title"] = ((last.get("commit") or {}).get("message", "") or bn).splitlines()[0][:200]
                info["ts"] = (((last.get("commit") or {}).get("committer") or {}).get("date")) or ""
                info["last_author"] = ((last.get("commit") or {}).get("author") or {}).get("name", "")
                if sha:
                    self._bcache[key] = info
            if not info["include"]:
                continue
            if int(bf.get("max_age_days", 0) or 0) and info.get("ts") and _age_days(info["ts"]) > int(bf["max_age_days"]):
                continue
            q = urllib.parse.quote(bn, safe="")
            out.append({"kind": "branch", "project_id": pid_of(repo["id"]), "project": full, "title": info.get("title") or bn, "branch": bn, "iid": None,
                        "url": "%s/tree/%s" % (html, q), "draft": False, "pipeline": "none", "pipeline_url": "", "updated_at": info.get("ts", ""), "sha": sha,
                        "author": me, "can_deploy": False, "age_days": _age_days(info.get("ts", "")), "state": "kein-mr", "ahead": info["ahead"],
                        "by_me": info["by_me"], "by_agent": info["by_agent"], "last_author": info.get("last_author", ""), "host": "github",
                        "create_mr_url": "%s/compare/%s...%s?expand=1" % (html, urllib.parse.quote(default, safe=""), q)})
        return out

    def search_prs(self, query, kind, limit=30):
        """Review-Anfragen und zugewiesene PRs über alle Repos (Suche), mit Branch und Pipeline aus dem PR selbst."""
        res = self.get("/search/issues", {"q": query, "per_page": limit, "sort": "updated"})
        out = []
        for it in (res.get("items") or [])[:limit]:
            m = re.search(r"/repos/([^/]+/[^/]+)$", it.get("repository_url", ""))
            if not m:
                continue
            full = m.group(1)
            try:
                repo = self.repo(full)
                pr = self.get("/repos/%s/pulls/%s" % (full, it["number"]))
            except GitHubError as e:
                log.debug("%s#%s: %s", full, it.get("number"), e)
                continue
            item = self._pr_item(full, repo, pr, kind, detail=False)
            item["pipeline"], _ = self.pipeline(full, item["sha"])
            out.append(item)
        return out

    def fetch(self, repos, ident, classify, bf, ignored, sink, step):
        """Alles von GitHub in `sink` (mine, review, assigned). Fehler je Repo stoppen die anderen nicht."""
        errors = sink.setdefault("errors", [])
        step("gh-user", "Bei GitHub anmelden", "run")
        try:
            me = self.user()["login"]
        except GitHubError as e:
            step("gh-user", "Bei GitHub anmelden", "err", str(e))
            errors.append(str(e))
            sink["gh_failed_all"] = True
            return
        step("gh-user", "Bei GitHub anmelden", "ok", me)
        ident = dict(ident, names=set(ident["names"]) | {me.lower()})

        def one(full):
            sid = "gh-" + full
            step(sid, "GitHub " + full, "run")
            try:
                items = self.fetch_repo(full, me, ident, classify, bf, ignored)
                sink.setdefault("mine", []).extend(items)
                step(sid, "GitHub " + full, "ok", "%d PR, %d Branches" % (sum(1 for i in items if i["kind"] == "mr"), sum(1 for i in items if i["kind"] == "branch")))
            except GitHubError as e:
                step(sid, "GitHub " + full, "err", str(e))
                errors.append("GitHub %s: %s" % (full, e))
                sink.setdefault("gh_failed_repos", []).append(full)
        for full in repos:
            step("gh-" + full, "GitHub " + full, "wait")
        with ThreadPoolExecutor(max_workers=3) as pool:
            list(pool.map(one, repos))
        for sid, title, q, kind, lst in (("gh-review", "GitHub: Review-Anfragen", "is:pr is:open archived:false review-requested:%s" % me, "review", "review"),
                                         ("gh-assigned", "GitHub: mir zugewiesen", "is:pr is:open archived:false assignee:%s -author:%s" % (me, me), "assigned", "assigned")):
            step(sid, title, "run")
            try:
                items = self.search_prs(q, kind)
                sink.setdefault(lst, []).extend(items)
                step(sid, title, "ok", "%d PR" % len(items))
            except GitHubError as e:
                step(sid, title, "err", str(e))
                errors.append(str(e))
