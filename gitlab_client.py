"""GitLab lesen (0.37 aus server.py gelöst): MRs, Branches, Pipelines, Freigaben. Nur lesend."""
import re
import time
import urllib.parse

import tlog
from common import UserError, _age_key, age_days, ignored_branch
from httpclient import Http

glog = tlog.get("gitlab")

BRANCH_DEFAULTS = {
    "emails": [],                 # weitere E-Mail-Adressen, unter denen DU committest
    "names": [],                  # weitere Autorennamen von dir
    "agent_emails": [],           # eigene Identität deines Agenten, falls er unter anderem Konto committet
    "agent_names": [],
    "agent_message_patterns": ["Co-Authored-By: Claude", "Claude-Session"],   # nur zum Beschriften
    "max_branches": 40,           # so viele Branches pro Projekt werden verglichen (neueste zuerst)
    "max_age_days": 90,           # ältere Branches werden ignoriert, 0 = kein Limit
    "ignore_branches": ["release/*"],   # Muster (* = beliebig): gilt für Branches ohne MR und für eigene MRs
}


def branch_cfg(cfg):
    b = dict(BRANCH_DEFAULTS)
    b.update(cfg.get("branch_filter") or {})
    return b


def ref_slug(branch):
    """Wie CI_COMMIT_REF_SLUG: klein, alles ausser a-z0-9 wird «-», höchstens 63 Zeichen, ohne «-» am Rand."""
    s_ = re.sub(r"[^a-z0-9]", "-", (branch or "").lower())[:63]
    return s_.strip("-")


def derive_state(item):
    if item["kind"] == "branch":
        return "kein-mr"
    if item["draft"]:
        return "draft"
    if item["pipeline"] == "failed":
        return "rot"
    if item["pipeline"] in ("running", "pending", "created", "waiting_for_resource"):
        return "laeuft"
    if item["pipeline"] == "success":
        return "bereit"
    return "offen"


def identity(cfg, me):
    """Wer bin ich, wer ist mein Agent: aus den Einstellungen (Meine Commits) und dem angemeldeten Konto."""
    bf = branch_cfg(cfg)

    def low(xs):
        return {str(x).strip().lower() for x in xs if str(x).strip()}

    emails = low(list(cfg.get("my_emails") or []) + list(bf["emails"]) +
                 [me.get("email") or "", me.get("public_email") or "", me.get("commit_email") or ""])
    names = low(list(bf["names"]) + [me.get("name") or ""])
    return {"emails": emails, "names": names,
            "agent_emails": low(bf["agent_emails"]), "agent_names": low(bf["agent_names"]),
            "patterns": [p.lower() for p in bf["agent_message_patterns"] if p]}


def classify_commits(commits, ident):
    """Wem gehört ein Branch? Betrachtet alle Commits, die der Branch dem Default-Branch voraus hat.

    include  = mindestens ein Commit von dir oder von der Agent-Identität (diese Branches werden gezeigt)
    by_agent = Agent-Identität, oder deine Commits mit Agent-Zeile in der Nachricht (z. B. Co-Authored-By: Claude).
    Eine Agent-Zeile allein bei einem Kollegen reicht NICHT, sonst würden fremde Branches auftauchen."""
    by_me = agent_id = trailer = False
    for c in commits:
        email = (c.get("author_email") or "").strip().lower()
        name = (c.get("author_name") or "").strip().lower()
        msg = ("%s\n%s" % (c.get("message") or "", c.get("title") or "")).lower()
        if email in ident["emails"] or name in ident["names"]:
            by_me = True
        if email in ident["agent_emails"] or name in ident["agent_names"]:
            agent_id = True
        if any(p in msg for p in ident["patterns"]):
            trailer = True
    return {"ahead": len(commits), "by_me": by_me, "by_agent": agent_id or (by_me and trailer),
            "include": by_me or agent_id}


class GitLabClient:
    def clone_urls(self, pid):
        """Adressen zum Klonen eines Projekts, wie GitLab sie nennt. Nur GET."""
        if pid not in self._urls:
            d = self.http.get("/projects/%s" % int(pid), {"simple": "true"}) or {}
            self._urls[pid] = {"ssh": d.get("ssh_url_to_repo") or "", "https": d.get("http_url_to_repo") or "", "full": d.get("path_with_namespace") or ""}
        return self._urls[pid]

    def __init__(self, cfg, token, ctx):
        self.cfg = cfg
        self.http = Http("GitLab", cfg["gitlab_url"].rstrip("/") + "/api/v4",
                         {"PRIVATE-TOKEN": token, "Accept": "application/json"}, ctx)
        self.proj_cfg = {p["id"]: p for p in cfg["projects"]}
        self._urls = {}
        self._bcache = {}   # (Projekt, Branch, Commit) -> Ergebnis; ein neuer Commit ergibt einen neuen Eintrag

    def _pipeline(self, project_id, ref):
        try:
            res = self.http.get("/projects/%s/pipelines" % project_id, {"ref": ref, "per_page": 1})
        except UserError:
            return "none", ""
        if res:
            return res[0].get("status", "none"), res[0].get("web_url", "")
        return "none", ""

    def _mr_item(self, mr, kind, project_name):
        pid = mr["project_id"]
        pipeline, purl = "none", ""
        if pid in self.proj_cfg:
            pipeline, purl = self._pipeline(pid, mr["source_branch"])
        app_url, app_env = self._review_app(pid, mr["source_branch"]) if pid in self.proj_cfg else ("", "")
        item = {
            "kind": kind, "project_id": pid,
            "project": project_name, "title": mr["title"],
            "branch": mr["source_branch"], "iid": mr["iid"], "url": mr["web_url"],
            "draft": bool(mr.get("draft") or mr.get("work_in_progress")),
            "pipeline": pipeline, "pipeline_url": purl,
            "updated_at": mr.get("updated_at", ""), "sha": mr.get("sha", ""),
            "author": (mr.get("author") or {}).get("username", ""),
            "can_deploy": pid in self.proj_cfg,
            "merge_status": mr.get("detailed_merge_status") or "",   # GitLab ab 15.6: mergeable, not_approved, conflict, ...
            "reviewers": [r.get("username", "") for r in (mr.get("reviewers") or [])] if "reviewers" in mr else None,
            "upvotes": int(mr.get("upvotes") or 0), "host": "gitlab",
            "approved": None, "approved_by": [], "approvals_left": None,
            "target_branch": mr.get("target_branch", ""), "review_app": app_url, "review_env": app_env,
        }
        if kind == "mr":
            self._approvals(item)
        item["age_days"] = age_days(item["updated_at"])
        item["state"] = derive_state(item) if kind == "mr" else "review"
        return item

    def _review_app(self, pid, branch):
        """URL der Review-App zum Branch aus den GitLab-Environments (ein GET je Projekt und Minute, nur lesend).
        Erkannt wird ein Environment, dessen letzte Bereitstellung diesen Branch hat oder dessen Name auf den Branch-Slug endet
        (übliche Benennung review/$CI_COMMIT_REF_SLUG)."""
        cache = self.__dict__.setdefault("_env_cache", {})
        hit = cache.get(pid)
        if not hit or time.time() - hit[0] > 60:
            try:
                envs = self.http.get("/projects/%s/environments" % pid, {"states": "available", "per_page": 100}) or []
            except UserError as e:
                glog.debug("Environments von %s nicht lesbar: %s", pid, e)
                envs = []
            hit = cache[pid] = (time.time(), envs)
        slug = ref_slug(branch)
        for e in hit[1]:
            if not e.get("external_url"):
                continue
            last = (e.get("last_deployment") or {})
            if last.get("ref") == branch or (e.get("name") or "").rsplit("/", 1)[-1] == slug:
                return e["external_url"], e.get("name", "")
        return "", ""

    def _my_review(self, mr, username):
        """0.36: Mein Stand als Reviewer (unreviewed, reviewed, requested_changes, approved, unapproved). Ein GET je MR und Änderung.
        Fehlt die Funktion (ältere GitLab-Versionen), bleibt es leer und der MR erscheint wie bisher."""
        cache = self.__dict__.setdefault("_rv_cache", {})
        key = (mr["project_id"], mr["iid"], mr.get("updated_at", ""))
        if key not in cache:
            try:
                rows = self.http.get("/projects/%s/merge_requests/%s/reviewers" % (mr["project_id"], mr["iid"])) or []
                cache[key] = next((str(x.get("state") or "") for x in rows if ((x.get("user") or {}).get("username") or "") == username), "")
            except UserError as e:
                glog.debug("Reviewer-Stand von !%s nicht lesbar: %s", mr["iid"], e)
                cache[key] = ""
            if len(cache) > 500:
                cache.pop(next(iter(cache)))
        return cache[key]

    def _approvals(self, item):
        """Freigaben eines eigenen MR (ein GET je MR). Fehlt das Recht oder die Funktion, bleibt es «unbekannt»."""
        try:
            a = self.http.get("/projects/%s/merge_requests/%s/approvals" % (item["project_id"], item["iid"]))
        except UserError as e:
            glog.debug("Freigaben von !%s nicht lesbar: %s", item["iid"], e)
            item["approval_unknown"] = True
            return
        item["approved_by"] = [((x.get("user") or {}).get("username") or "") for x in (a.get("approved_by") or [])]
        left = a.get("approvals_left")
        item["approvals_left"] = int(left) if isinstance(left, int) else None
        item["approved"] = bool(item["approved_by"])     # «approved» von GitLab ist auch ohne Regeln wahr; zählt nur, wer wirklich freigegeben hat

    def _identity(self, me):
        return identity(self.cfg, me)

    def _classify(self, pid, default, b, ident):
        sha = (b.get("commit") or {}).get("id", "")
        key = (pid, b["name"], sha)
        if sha and key in self._bcache:
            return self._bcache[key]
        try:
            res = self.http.get("/projects/%s/repository/compare" % pid,
                                {"from": default, "to": b["name"], "straight": "false"})
        except UserError:
            return None
        info = classify_commits(res.get("commits") or [], ident)
        if sha:
            self._bcache[key] = info
        return info

    def review_threads(self, project_id, iid):
        """MR (Zielbranch, aktueller Commit) und seine Diskussionen, höchstens 500. Nur GET."""
        mr = self.http.get("/projects/%s/merge_requests/%s" % (project_id, iid))
        out = []
        for page in range(1, 6):
            res = self.http.get("/projects/%s/merge_requests/%s/discussions" % (project_id, iid), {"per_page": 100, "page": page}) or []
            out.extend(res)
            if len(res) < 100:
                break
        return mr, out

    def ticket_context(self, project_id, iid, branch):
        """Das, was ein Ticket-Entwurf braucht: Titel, MR-Beschreibung, Commit-Titel. Keine Diffs, keine Dateiinhalte."""
        ctx = {"project_id": project_id, "iid": iid, "branch": branch, "project": self._pname(project_id),
               "title": branch, "mr_description": "", "commits": [], "url": ""}
        if iid:
            mr = self.http.get("/projects/%s/merge_requests/%s" % (project_id, iid))
            ctx.update(title=mr.get("title", ""), mr_description=mr.get("description") or "", url=mr.get("web_url", ""))
            commits = self.http.get("/projects/%s/merge_requests/%s/commits" % (project_id, iid), {"per_page": 20})
        else:
            proj = self.http.get("/projects/%s" % project_id)
            default = proj.get("default_branch") or "main"
            ctx["url"] = proj.get("web_url", "") + "/-/tree/" + urllib.parse.quote(branch)
            res = self.http.get("/projects/%s/repository/compare" % project_id, {"from": default, "to": branch, "straight": "false"})
            commits = res.get("commits") or []
            ctx["title"] = (commits[-1].get("title") if commits else "") or branch
        ctx["commits"] = [(c.get("title") or "").strip() for c in commits if c.get("title")][:20]
        return ctx

    def _pname(self, project_id):
        return self.proj_cfg.get(project_id, {}).get("name", "Projekt %s" % project_id)

    def fetch(self, sink=None, step=None):
        """Holt alles von GitLab. Ergebnisse landen schon während des Abrufs in `sink` (Liste für Liste), und `step(id, Titel, Status, Detail)`
        meldet den Fortschritt, damit die Oberfläche nicht auf das Ende warten muss."""
        step = step or (lambda *a, **k: None)
        sink = sink if sink is not None else {}
        errors = sink.setdefault("errors", [])
        step("gl-user", "Bei GitLab anmelden", "run")
        me = self.http.get("/user")
        username = me["username"]
        sink["me"] = username
        step("gl-user", "Bei GitLab anmelden", "ok", username)
        ident = self._identity(me)
        glog.debug("Angemeldet als %s, %d E-Mails und %d Namen für die Branch-Erkennung", username,
                   len(ident["emails"]), len(ident["names"]))
        bf = branch_cfg(self.cfg)
        ignore = list(bf.get("ignore_branches") or [])
        mine = sink.setdefault("mine", [])
        review = sink.setdefault("review", [])
        assigned = sink.setdefault("assigned", [])

        def one(p):
            pid, name = p["id"], p.get("name", str(p["id"]))
            try:
                proj = self.http.get("/projects/%s" % pid)
                default = proj.get("default_branch", "main")
                mrs = self.http.get("/projects/%s/merge_requests" % pid,
                                    {"state": "opened", "author_username": username, "per_page": 50})
                with_mr = set()
                ignored_mrs = 0
                for mr in mrs:
                    with_mr.add(mr["source_branch"])
                    if ignored_branch(mr["source_branch"], ignore):
                        glog.debug("%s: MR !%s übersprungen (Branch %s passt auf ignore_branches)", name, mr["iid"], mr["source_branch"])
                        ignored_mrs += 1
                        continue
                    mine.append(self._mr_item(mr, "mr", name))
                branches = self.http.get("/projects/%s/repository/branches" % pid, {"per_page": 100})
                branches.sort(key=lambda b: _age_key((b.get("commit") or {}).get("committed_date")))
                checked = 0
                shown_b = skipped = 0
                for b in branches:
                    bn = b["name"]
                    reason = ("Default-Branch" if bn == default else "geschützt" if b.get("protected")
                              else "schon gemergt" if b.get("merged") else "hat einen MR" if bn in with_mr
                              else "passt auf ignore_branches" if ignored_branch(bn, ignore) else "")
                    if reason:
                        glog.debug("%s: Branch %s übersprungen (%s)", name, bn, reason)
                        continue
                    commit = b.get("commit") or {}
                    ts = commit.get("committed_date", "")
                    if int(bf["max_age_days"]) and age_days(ts) > int(bf["max_age_days"]):
                        glog.debug("%s: Branch %s übersprungen (%d Tage alt, Limit %s)", name, bn, age_days(ts), bf["max_age_days"])
                        skipped += 1
                        continue
                    if checked >= int(bf["max_branches"]):
                        glog.info("%s: max_branches=%s erreicht, weitere Branches werden nicht geprüft", name, bf["max_branches"])
                        break
                    checked += 1
                    info = self._classify(pid, default, b, ident)
                    if info is None:   # Vergleich fehlgeschlagen: dann zählt nur der letzte Commit
                        glog.warning("%s: Vergleich für Branch %s fehlgeschlagen, es zählt nur der letzte Commit", name, bn)
                        if (commit.get("author_email") or "").lower() not in ident["emails"]:
                            continue
                        info = {"ahead": 0, "by_me": True, "by_agent": False, "include": True}
                    if not info["include"]:
                        glog.debug("%s: Branch %s ausgeblendet (%d Commits, keiner von dir oder dem Agenten)", name, bn, info["ahead"])
                        continue
                    shown_b += 1
                    glog.debug("%s: Branch %s angezeigt (%d Commits, von mir=%s, Agent=%s)", name, bn, info["ahead"],
                               info["by_me"], info["by_agent"])
                    mine.append({
                        "kind": "branch", "project_id": pid, "project": name,
                        "title": commit.get("title", b["name"]), "branch": b["name"], "iid": None,
                        "url": proj.get("web_url", "") + "/-/tree/" + urllib.parse.quote(b["name"]),
                        "draft": False, "pipeline": "none", "pipeline_url": "",
                        "updated_at": ts, "sha": commit.get("id", ""), "author": username,
                        "can_deploy": False, "age_days": age_days(ts), "state": "kein-mr",
                        "ahead": info["ahead"], "by_me": info["by_me"], "by_agent": info["by_agent"],
                        "last_author": commit.get("author_name", ""),
                        "create_mr_url": proj.get("web_url", "") + "/-/merge_requests/new?merge_request%5Bsource_branch%5D=" + urllib.parse.quote(b["name"], safe=""),
                    })
                glog.info("%s: %d eigene MRs (%d ignoriert), %d Branches geprüft, %d angezeigt, %d zu alt", name, len(mrs),
                          ignored_mrs, checked, shown_b, skipped)
                return "ok", "%d MR, %d Branches" % (len(mrs) - ignored_mrs, shown_b)
            except UserError as e:
                glog.error("%s: %s", name, e)
                errors.append("%s: %s" % (name, e))
                sink.setdefault("gl_failed_pids", []).append(pid)
                return "err", str(e)

        def run_one(p):
            name = p.get("name", str(p["id"]))
            sid = "gl-%s" % p["id"]
            step(sid, "Projekt " + name, "run")
            status, detail = one(p)
            step(sid, "Projekt " + name, status, detail)

        projects = list(self.cfg["projects"])
        for p in projects:
            step("gl-%s" % p["id"], "Projekt " + p.get("name", str(p["id"])), "wait")
        step("gl-review", "Review-Queue", "wait")
        step("gl-assigned", "Mir zugeteilte MRs", "wait")
        if projects:
            from concurrent.futures import ThreadPoolExecutor
            with ThreadPoolExecutor(max_workers=min(3, len(projects))) as pool:
                list(pool.map(run_one, projects))
        order = {p["id"]: i for i, p in enumerate(projects)}
        mine.sort(key=lambda it: order.get(it["project_id"], 99))   # stabil: innerhalb eines Projekts bleibt die Reihenfolge
        step("gl-review", "Review-Queue", "run")
        try:
            rmrs = self.http.get("/merge_requests", {"state": "opened", "scope": "all",
                                                     "reviewer_username": username, "per_page": 50})
            for mr in rmrs:
                it = self._mr_item(mr, "review", self._pname(mr["project_id"]))
                it["my_review"] = self._my_review(mr, username)
                review.append(it)
            step("gl-review", "Review-Queue", "ok", "%d MR" % len(review))
        except UserError as e:
            errors.append("Review-Queue: %s" % e)
            step("gl-review", "Review-Queue", "err", str(e))
        step("gl-assigned", "Mir zugeteilte MRs", "run")
        try:
            seen = {(m["project_id"], m["iid"]) for m in review}
            seen |= {(m["project_id"], m["iid"]) for m in mine if m["kind"] == "mr"}
            amrs = self.http.get("/merge_requests", {"state": "opened", "scope": "all",
                                                     "assignee_username": username, "per_page": 50})
            for mr in amrs:
                if (mr["project_id"], mr["iid"]) in seen:
                    continue
                assigned.append(self._mr_item(mr, "assigned", self._pname(mr["project_id"])))
            step("gl-assigned", "Mir zugeteilte MRs", "ok", "%d MR" % len(assigned))
        except UserError as e:
            errors.append("Zugeteilte MRs: %s" % e)
            step("gl-assigned", "Mir zugeteilte MRs", "err", str(e))
        return sink

    def mr(self, project_id, iid):
        mr = self.http.get("/projects/%s/merge_requests/%s" % (project_id, iid))
        return {"title": mr["title"], "branch": mr["source_branch"], "sha": mr["sha"],
                "url": mr["web_url"]}
