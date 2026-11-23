"""Reviews in GitLab (0.42, E14): «▶ Review starten» für einen MR, Befunde mit Ort, Entwürfe in GitLab.

Ein Klick startet den Reviewer-Agenten auf genau dem Commit des MR (eigener Worktree, holt den Stand selbst, ändert nichts).
Er hält Befunde mit Datei und Zeile fest (`tinyops-finding`). Auf deinen Klick legt tinyops daraus deine Entwürfe am MR an:
mit Position, wo die Zeile im Diff liegt, sonst als allgemeiner Entwurf mit Datei und Zeile im Text. Abschicken machst du in GitLab.
Ohne `gitlab_review_token` gibt es die Befunde zum Kopieren. Bereich von App; Aufrufe in andere Bereiche stehen in USES."""
import json

import agents
import gitlab_review
import links
import secretstore as store
from common import UserError

SEV_ORDER = {"hoch": 0, "mittel": 1, "klein": 2}


class ReviewArea:
    USES = {"area_agents": ("_find_mr",)}

    def _rv_mr(self, b):
        host = "github" if b.get("host") == "github" else "gitlab"
        if host != "gitlab":
            raise UserError("Review-Entwürfe gibt es nur für GitLab.")
        try:
            pid, iid = int(b.get("project_id")), int(b.get("iid"))
        except (TypeError, ValueError):
            raise UserError("project_id und iid müssen Zahlen sein.")
        it = self._find_mr(host, pid, iid)
        if not it:
            raise UserError("Diesen MR kenne ich nicht (mehr). Einmal «Neu laden».")
        return pid, iid, it

    def _rv_key(self, pid, it):
        return links.ref_of(pid, it.get("branch") or "")

    def _rv_reviewer(self, svc, aid, pid):
        """Der Agent fürs Review: der gewählte, sonst der erste mit der Rolle Review, der das Projekt darf und einen eigenen Worktree hat."""
        cands = [a for a in svc.agent_list() if not aid or a["id"] == aid]
        if not cands:
            raise UserError("Diesen Agenten gibt es nicht." if aid else "Noch kein Agent eingerichtet (Einstellungen → Agenten).")
        cands.sort(key=lambda a: "review" not in (a.get("roles") or {}))      # mit eigener Review-Rolle zuerst
        why = ""
        for a in cands:
            ok, why = svc.allowed(a, pid)
            if ok and svc.mode(a, pid) == "worktree":
                return a
            if ok:
                why = "%s arbeitet nicht in einem eigenen Worktree (Einstellungen → Agenten → Isolation)." % a["name"]
        raise UserError("Kein Agent darf dieses Review machen: %s" % why)

    def review_start(self, b):
        """▶ Review starten: Reviewer-Agent auf dem Head-Commit des MR, ein Klick, ohne Dialog."""
        svc = self.agents
        if self.demo:
            raise UserError("In der Demo startet kein Agent.")
        pid, iid, it = self._rv_mr(b)
        if not it.get("sha"):
            raise UserError("Der MR hat noch keinen Commit.")
        a = self._rv_reviewer(svc, str(b.get("agent") or ""), pid)
        try:
            d = self.client.mr_detail(pid, iid) if self.client is not None else {}
        except UserError:
            d = {}
        target = d.get("target_branch") or it.get("target_branch") or "main"
        desc = (d.get("description") or "").strip()
        extra = {"source": it.get("branch") or "", "target": target, "sha": it["sha"], "mr_ref": "refs/merge-requests/%d/head" % iid,
                 "description": ("## Beschreibung des MR\n\n" + desc[:6000] + "\n") if desc else ""}
        key = self._rv_key(pid, it)
        title = "!%d %s" % (iid, it.get("title") or "")
        info = svc.prompt_info(a["id"], key, pid, it.get("branch") or "", title, key, it.get("url") or "", template="agent-mr-review", extra=extra)
        if not info["allowed"]:
            raise UserError(info["reason"])
        rid = svc.assign(a["id"], key, pid, it.get("branch") or "", title[:300])
        try:
            svc.start(rid, info["prompt"], pid, it.get("branch") or "", phase="review")
        except agents.AgentError as e:
            svc.remove(rid, force=True)
            raise UserError(str(e))
        svc.store.agent_run_update(rid, mr=json.dumps({"host": "gitlab", "project_id": pid, "iid": iid, "sha": it["sha"], "target": target,
                                                       "url": it.get("url") or ""}))
        self.audit("review.start", key, run=rid, agent=a["id"], mr=iid, sha=it["sha"][:12])
        return {"id": rid, "agent": a["name"]}

    def review_state(self, b):
        """Was es zu diesem MR gibt: Review-Läufe mit Befunden, deine Entwürfe von tinyops, ob ein Token da ist."""
        pid, iid, it = self._rv_mr(b)
        key = self._rv_key(pid, it)
        runs = []
        if self.agents:
            for r in sorted(self.agents.store.agent_runs(ticket=key), key=lambda r: -r["id"])[:5]:
                v = self.agents.run_view(r)
                runs.append({"id": v["id"], "status": v["status"], "agent": v["agent_name"], "findings": sorted(v["findings"] or [], key=lambda x: (SEV_ORDER.get(x["severity"], 1), x["path"], x["line"])), "sha": ((v.get("mr") or {}).get("sha") or "")[:8],
                             "summary": (v.get("summary") or "")[:1500], "active": v["active"]})
        return {"key": key, "runs": runs, "drafts": len(self.store.drafts_of(pid, iid)), "token": bool(self._rv_token()), "sha": (it.get("sha") or "")[:8],
                "url": it.get("url") or "", "can_start": bool(self.agents and self.agents.agent_list())}

    def _rv_token(self):
        try:
            val, _ = store.resolve("gitlab_review_token", (self.cfg.get("secrets") or {}).get("gitlab_review_token"))
        except store.SecretError:
            return ""
        return val or ""

    def _rv_run(self, b):
        r = self.agents.store.agent_run(self._rid(b)) if self.agents else None
        if not r or r.get("phase") != "review" or not r.get("mr"):
            raise UserError("Das ist kein Review-Lauf zu einem MR.")
        if r["status"] in ("zugewiesen", "läuft"):
            raise UserError("Das Review läuft noch.")
        v = self.agents.run_view(r)
        f = sorted(v["findings"] or [], key=lambda x: (SEV_ORDER.get(x["severity"], 1), x["path"], x["line"]))
        if b.get("only") is not None:                       # Auswahl in der Oberfläche (Index in der sortierten Liste)
            keep = {int(i) for i in b.get("only") or [] if str(i).isdigit()}
            f = [x for i, x in enumerate(f) if i in keep]
        return v, f

    def review_copy(self, b):
        v, f = self._rv_run(b)
        lines = ["- **%s** `%s%s`: %s" % (x["severity"], x["path"], ":%d" % x["line"] if x["line"] else "", x["text"]) for x in f]
        return {"text": "\n".join(lines) + "\n" if lines else "Keine Befunde.\n", "count": len(f)}

    def review_drafts(self, b):
        """Entwürfe in GitLab anlegen. Ersetzt nur die Entwürfe, die tinyops an diesem MR selbst angelegt hat. Schickt nie ab."""
        v, f = self._rv_run(b)
        if not f:
            raise UserError("Keine Befunde ausgewählt.")
        mr = v["mr"]
        tok = self._rv_token()
        if not tok:
            raise UserError("Für Entwürfe in GitLab fehlt das Review-Token (Einstellungen → GitLab → «Token für Review-Entwürfe», Scope api). Bis dahin: «Kopieren».")
        if self.demo:
            raise UserError("In der Demo schreibt tinyops nicht nach GitLab.")
        gl = gitlab_review.Drafts(self.cfg["gitlab_url"], tok, self.ssl_ctx)
        store.register(tok)
        pid, iid = int(mr["project_id"]), int(mr["iid"])
        ver, old_stand = gitlab_review.pick_version(gl.versions(pid, iid), mr.get("sha") or "")
        if not ver:
            raise UserError("GitLab nennt keine Diff-Version für diesen MR.")
        planned = gitlab_review.plan(f, gl.version(pid, iid, int(ver["id"])))
        mine = {d["draft_id"] for d in self.store.drafts_of(pid, iid)}
        removed = 0
        for d in gl.drafts(pid, iid):                        # nur eigene: in der Datenbank vermerkt UND mit Marke
            if d.get("id") in mine and gitlab_review.MARK in (d.get("note") or ""):
                gl.delete(pid, iid, int(d["id"]))
                removed += 1
        for did in mine:
            self.store.draft_forget(pid, iid, did)
        made, general = 0, 0
        for p in planned:
            note = p["note"] if not old_stand else p["note"].replace(gitlab_review.MARK, "*(geprüft auf %s)*\n\n%s" % ((mr.get("sha") or "")[:8], gitlab_review.MARK))
            d = gl.create(pid, iid, note, p["position"])
            if d.get("id"):
                self.store.draft_add(pid, iid, int(d["id"]), v["id"], mr.get("sha") or "")
                made += 1
                general += 0 if p["position"] else 1
        self.audit("review.drafts", self._rv_key(pid, {"branch": v.get("branch")}), run=v["id"], mr=iid, created=made, positioned=made - general,
                   general=general, replaced=removed)
        return {"created": made, "positioned": made - general, "general": general, "replaced": removed, "old": old_stand, "url": mr.get("url") or ""}
