"""Agenten-Anbindung: Zuweisen, Phasen, Weiterführen, Review-Punkte, Prompts zum Kopieren.

Bereich von App (0.38 aus server.py gelöst). Gemeinsames (cfg, store, Audit, Cache) kommt von App;
Aufrufe in andere Bereiche stehen in USES und werden von tests/test_areas.py geprüft."""

import threading
import time

import agents
import briefing
import github
import review
import reviewenv
import tlog
import workspaces
from common import HttpStatus, UserError, extract_keys, render
from secretstore import scrub

log = tlog.get("app")


class AgentArea:
    # Aufrufe in andere Bereiche (tests/test_areas.py prüft, dass genau diese benutzt werden)
    USES = {"area_ide": ("run_checkout", "run_env", "run_try"), "area_tickets": ("ticket_brief",), "area_workspaces": ("_ws_hosts", "_ws_projects")}

    # -- Coding-Agenten an Tickets
    def agents_view(self):
        """Agenten und Läufe für die Oberfläche. Der Stand der laufenden Läufe wird im Hintergrund abgefragt (SSH kann dauern)."""
        v = self.agents.view()
        if any(r["active"] for r in v["runs"]) and not self._agent_poll_busy:
            self._agent_poll_busy = True

            def work():
                try:
                    self.agents.poll()
                except Exception as e:   # Abfrage darf die Oberfläche nie stören
                    log.warning("Agenten-Abfrage: %s", scrub(e))
                finally:
                    self._agent_poll_busy = False
            threading.Thread(target=work, daemon=True).start()
        return v

    def agent_action(self, action, b):
        svc = self.agents
        try:
            if action == "prompt":
                if isinstance(b.get("review"), dict):      # Agent soll offene Review-Punkte bearbeiten
                    aid, rv = str(b.get("agent") or ""), dict(b["review"])
                    res, topics = self._review_pick(rv)
                    skipped = []
                    p = svc.project(res["mr"]["project_id"])
                    if p and svc.mode(svc.agent(aid), res["mr"]["project_id"]) == "export":
                        # Export: nur Punkte zu Dateien in den freigegebenen Pfaden; allgemeine Punkte können alles betreffen
                        paths = p.get("cloud_paths") or []
                        keep = [t for t in topics if t["file"] and agents.path_allowed(t["file"], paths)]
                        skipped = [review.where(t) for t in topics if t not in keep]
                        if not keep:
                            raise UserError("Keiner der Punkte liegt in den freigegebenen Pfaden (%s). Einen lokalen Agenten nehmen." % ", ".join(paths))
                        rv["ids"] = [t["id"] for t in keep]
                    extra, mr = self.review_prompt_extra(rv)
                    info = svc.prompt_info(aid, b.get("ticket"), mr["project_id"], mr["branch"],
                                           b.get("title") or "", b.get("key") or "", mr["url"], template="review-topics", extra=extra)
                    info["review_skipped"] = skipped
                    return info
                aid = str(b.get("agent") or "")
                phase = str(b.get("phase") or "")
                if phase and phase not in agents.PHASES:
                    raise UserError("Unbekannte Phase.")
                if phase in ("review", "test") and b.get("parent") not in (None, ""):
                    return self._phase_prompt(svc, aid, phase, b)
                if phase == "review":
                    raise UserError("Review braucht einen beendeten Entwickeln-Lauf mit eigenem Branch.")
                if phase == "test" and b.get("parent") in (None, ""):
                    raise UserError("Test braucht einen beendeten Lauf, dessen Ergebnis getestet wird.")
                if b.get("followup") not in (None, ""):     # Nachbesserung: offene Kriterien des alten Laufs, Ausgang ist sein Branch
                    old = svc.store.agent_run(self._rid({"run": b.get("followup")}))
                    if not old or old["status"] in ("zugewiesen", "läuft"):
                        raise UserError("Nachbessern geht erst, wenn der Lauf beendet ist.")
                    ov = svc.run_view(old)
                    base = ov.get("taken") or (ov.get("out_branch") if ov.get("mode") == "worktree" else "") or ov.get("branch") or ""
                    info = svc.prompt_info(aid, ov["ticket"], ov["project_id"], base, ov.get("title") or "", b.get("key") or ov["ticket"], b.get("url") or "",
                                           template="agent-followup", extra={"brief": briefing.followup(ov, b.get("note"), b.get("answers"))})
                    info.update(branch=base, project_id=ov["project_id"], followup=ov["id"], parent=ov["id"], phase="develop",      # Nachbessern ändert Code: immer Umsetzen
                                repo=self._repo_access(svc, aid, ov["project_id"]))
                    return info
                key = str(b.get("key") or "")
                br = self.ticket_brief(key, b.get("title") or "")
                opts = briefing.options(br, b.get("brief"), bool(svc.agent(aid).get("cloud", True)))
                phase = phase or "develop"
                text, plan = briefing.block(br, opts), None
                if phase == "develop" and b.get("parent") not in (None, ""):      # Umsetzen nach einem freigegebenen Plan
                    plan = svc.store.agent_run(self._rid({"run": b.get("parent")}))
                    if not plan or (plan.get("phase") or "develop") != "plan":
                        raise UserError("Der Plan-Lauf ist nicht mehr da.")
                    if plan.get("gate") != "ok":
                        raise UserError("Den Plan zuerst freigeben.")
                    text += briefing.plan_block(svc.run_view(plan))
                info = svc.prompt_info(aid, b.get("ticket"), self._pid(b.get("project_id")), b.get("branch") or "",
                                       b.get("title") or "", key, b.get("url") or "", template=agents.PHASE_TEMPLATE[phase], extra={"brief": text})
                info.update(phase=phase, parent=plan["id"] if plan else None)
                info["brief"] = briefing.view(br, opts)
                info["repo"] = self._repo_access(svc, aid, self._pid(b.get("project_id")))
                try:                               # für die Projektauswahl: was liegt beim Agenten, was fehlt (derselbe kurz gemerkte Blick)
                    info["access"] = {str(k): v["state"] for k, v in svc.access(aid).items()}
                except agents.AgentError:
                    info["access"] = {}
                return info
            if action == "access":            # liegt das Projekt beim Agenten? (frisch nachsehen)
                return {"repo": self._repo_access(svc, str(b.get("agent") or ""), self._pid(b.get("project_id")), fresh=bool(b.get("fresh")))}
            if action == "clone":             # Projekt beim Agenten klonen: nur auf deinen Klick, im Hintergrund, im Protokoll
                aid, pid = str(b.get("agent") or ""), self._pid(b.get("project_id"))
                if pid is None:
                    raise UserError("Bitte ein Projekt wählen.")
                via = b.get("via") if b.get("via") in ("ssh", "https") else svc.agent(aid).get("clone_via", "ssh")
                svc.clone(aid, pid, self.clone_url(pid, via))
                return {"repo": self._repo_access(svc, aid, pid)}
            if action == "assign":
                rid = svc.assign(str(b.get("agent") or ""), b.get("ticket"), self._pid(b.get("project_id")), b.get("branch"), b.get("title"))
                return {"id": rid}
            if action == "start":
                phase = str(b.get("phase") or "develop")
                if phase not in agents.PHASES:
                    raise UserError("Unbekannte Phase.")
                parent = self._rid({"run": b.get("parent")}) if b.get("parent") not in (None, "") else None
                rid = svc.start(self._rid(b), b.get("prompt"), self._pid(b.get("project_id")), b.get("branch"), phase=phase, parent=parent)
                return {"id": rid}
            if action == "continue":         # 0.36: weiterführen; seit 0.40 in derselben Sitzung des Agenten, wenn er das kann
                return self._agent_continue(svc, b)
            if action == "back":             # 0.40: Befund aus Review/Test (oder deine Notiz) zurück in die Sitzung des Entwicklers
                return self._agent_back(svc, b)
            if action == "again":            # 0.40: derselbe Reviewer prüft den nachgebesserten Stand in seiner Sitzung
                return self._agent_again(svc, b)
            if action == "gate":             # deine Freigabe am Ende einer Phase
                g = str(b.get("gate") or "")
                return svc.gate(self._rid(b), g, b.get("note") or "")
            if action == "manual":           # Prüfpunkt im Lauf abhaken
                try:
                    i = int(b.get("i"))
                except (TypeError, ValueError):
                    raise UserError("Welcher Prüfpunkt?")
                return svc.manual_check(self._rid(b), i, bool(b.get("done")), b.get("note") or "")
            if action == "stop":
                svc.stop(self._rid(b))
                return {"ok": True}
            if action == "remove":
                svc.remove(self._rid(b), force=bool(b.get("force")))
                return {"ok": True}
            if action == "takeover":
                return svc.takeover(self._rid(b))
            if action == "changes":
                return {"files": svc.changes(self._rid(b))}
            if action == "refresh":
                svc.poll(force=True)
                return svc.view()
            if action == "tail":
                return {"text": svc.tail(self._rid(b), int(b.get("lines") or 80))}
            if action == "answer":
                return svc.answer(self._rid(b), b.get("qid"), b.get("text"))
            if action == "report":           # Bericht und Belege neu einlesen
                r = svc.store.agent_run(self._rid(b))
                if not r:
                    raise UserError("Diesen Lauf gibt es nicht (mehr).")
                svc.collect(r)
                return svc.run_view(svc.store.agent_run(r["id"]))
            if action == "ack":
                svc.ack(self._rid(b))
                return {"ok": True}
            if action == "comment":          # Entwurf eines Ticket-Kommentars, nur zum Kopieren: tinyops schreibt ihn nirgends hin
                r = svc.store.agent_run(self._rid(b))
                if not r or r["status"] in ("zugewiesen", "läuft"):
                    raise UserError("Erst wenn der Lauf beendet ist.")
                return {"text": briefing.comment(svc.run_view(r))}
            if action == "try":              # Ausprobieren: Branch, Befehle, Worktree, Review-Umgebung
                return self.run_try(self._rid(b))
            if action == "checkout":         # Branch in deinen Checkout holen (eigener Worktree), optional IntelliJ
                return self.run_checkout(self._rid(b), launch=bool(b.get("ide", True)))
            if action == "env":              # Review-Umgebung starten/stoppen
                if b.get("do") not in ("up", "down"):
                    raise UserError("Starten oder stoppen?")
                return self.run_env(self._rid(b), b["do"])
            if action == "mrdesc":           # MR-Beschreibung für Reviewer im Team, nur zum Kopieren
                r = svc.store.agent_run(self._rid(b))
                if not r or r["status"] in ("zugewiesen", "läuft"):
                    raise UserError("Erst wenn der Lauf beendet ist.")
                return {"text": briefing.mr_description(svc.run_view(r))}
        except agents.AgentError as e:
            raise UserError(str(e))
        raise UserError("Unbekannte Aktion.")

    def _agent_continue(self, svc, b, sync=""):
        """Weiterführen mit deiner Nachricht. Kann der Agent seine Sitzung fortsetzen (0.40), geht es dort weiter: gleicher Ordner,
        gleicher Branch, ganzer Kontext. Sonst wie bis 0.39: neuer Lauf auf dem Branch des alten, mit Zusammenfassung."""
        old = svc.store.agent_run(self._rid(b))
        if not old:
            raise UserError("Diesen Lauf gibt es nicht (mehr).")
        if old["status"] in ("zugewiesen", "läuft"):
            raise UserError("Der Lauf arbeitet noch. Fragt er etwas, antworte dort; sonst warten oder stoppen.")
        text = str(b.get("text") or "").strip()
        answers = {str(k): str(v)[:600] for k, v in (b.get("answers") or {}).items() if str(v or "").strip()} if isinstance(b.get("answers"), dict) else {}
        if not text and not answers:
            raise UserError("Schreib, wie es weitergehen soll, oder beantworte eine offene Entscheidung.")
        aid = str(b.get("agent") or old["agent"])
        same, why = svc.can_continue(old, aid)
        if same:
            ov = svc.run_view(old)
            prompt = svc.resume_prompt(ov, briefing.resume(ov, text, answers))
            rid = svc.assign(aid, old["ticket"], old["project_id"], old["branch"], old.get("title") or "")
            try:
                svc.start(rid, prompt, old["project_id"], old["branch"], phase=old.get("phase") or "develop", parent=old.get("parent") or None,
                          resume=old, ask=text, sync=sync)
            except agents.AgentError:
                svc.remove(rid, force=True)
                raise
            self.audit("agent.continue", old["ticket"], run=old["id"], new_run=rid, agent=aid, answers=len(answers), chars=len(text), session="gleich")
            return {"id": rid, "session": True}
        if sync:
            raise UserError(why)
        info = self.agent_action("prompt", {"agent": aid, "followup": old["id"], "note": text, "answers": answers, "key": old["ticket"]})
        rid = svc.assign(aid, old["ticket"], info["project_id"], info["branch"], old.get("title") or "")
        try:
            svc.start(rid, info["prompt"], info["project_id"], info["branch"], phase="develop", parent=old["id"], ask=text)
        except agents.AgentError:
            svc.remove(rid, force=True)
            raise
        svc.store.agent_run_update(rid, resume_of=str(old["id"]), fresh="1")       # gehört zum Gespräch, aber neue Sitzung
        svc.store.agent_run_update(old["id"], next_run=str(rid))
        self.audit("agent.continue", old["ticket"], run=old["id"], new_run=rid, agent=aid, answers=len(answers), chars=len(text), session="neu")
        return {"id": rid, "session": False, "why": why}

    def _dev_of(self, svc, r):
        """Der jüngste Entwickeln-Lauf zu einem Lauf: über parent zurück bis Entwickeln, dann in dessen Gespräch nach vorne."""
        seen = set()
        while r and (r.get("phase") or "develop") != "develop" and r.get("parent") and r["id"] not in seen:
            seen.add(r["id"])
            r = svc.store.agent_run(self._rid({"run": r["parent"]}))
        if not r or (r.get("phase") or "develop") != "develop":
            raise UserError("Zu diesem Lauf gibt es keinen Entwickeln-Lauf mehr.")
        return svc.chain(r)[-1]

    def _agent_back(self, svc, b):
        """Zurück ans Entwickeln: aus einem Review- oder Test-Lauf geht der Befund (mit deiner Notiz) an den Entwickler,
        aus einem Entwickeln-Lauf deine Notiz. Wenn möglich in seiner Sitzung, ohne Kopieren und ohne Dialog."""
        r = svc.store.agent_run(self._rid(b))
        if not r or r["status"] in ("zugewiesen", "läuft"):
            raise UserError("Zurückgeben geht erst, wenn der Lauf beendet ist.")
        note = str(b.get("note") or "").strip()
        dev = self._dev_of(svc, r)
        if dev["status"] in ("zugewiesen", "läuft"):
            raise UserError("Der Entwickler arbeitet gerade (Lauf %d). Erst wenn er fertig ist." % dev["id"])
        if (r.get("phase") or "develop") == "develop":
            if not note:
                raise UserError("Was soll anders werden? Ein Satz reicht.")
            text = note
        else:
            text = briefing.back_to_dev(svc.run_view(r), note)
        try:
            svc.gate(r["id"], "back", note or "Befund ans Entwickeln")
        except agents.AgentError:
            pass
        out = self._agent_continue(svc, {"run": dev["id"], "text": text})
        self.audit("agent.back", r["ticket"], run=r["id"], dev=dev["id"], new_run=out["id"], phase=r.get("phase") or "develop")
        return dict(out, dev=dev["id"])

    def _agent_again(self, svc, b):
        """Nach dem Nachbessern: der Reviewer der letzten Runde prüft erneut, in seiner Sitzung, auf dem neuen Stand des Entwicklers.
        Geht das nicht (kein Review, andere Isolation, Sitzung weg), sagt die Antwort «fallback» und die Oberfläche öffnet den Dialog."""
        dev = svc.store.agent_run(self._rid(b))
        if not dev or (dev.get("phase") or "develop") != "develop":
            raise UserError("Erneut prüfen geht von einem Entwickeln-Lauf aus.")
        ids = {str(x["id"]) for x in svc.chain(dev)}
        reviews = [x for x in svc.store.agent_runs(ticket=dev["ticket"]) if (x.get("phase") == "review") and str(x.get("parent") or "") in ids]
        reviews = [svc.chain(x)[-1] for x in reviews]
        rv = max(reviews, key=lambda x: x["id"]) if reviews else None
        if not rv or rv.get("mode") != "worktree" or not dev.get("out_branch"):
            return {"fallback": True, "why": "Kein Review in einem eigenen Worktree, das weitergehen könnte."}
        ok, why = svc.can_continue(rv)
        if not ok:
            return {"fallback": True, "why": why}
        text = ("Der Entwickler hat nachgebessert (Lauf %d). Dein Ordner steht jetzt auf seinem neuen Stand. Prüfe erneut: was aus deinem Befund erledigt ist, "
                "was offen bleibt, was neu dazukam. Schreib den Befund mit tinyops-report neu." % dev["id"])
        try:
            out = self._agent_continue(svc, {"run": rv["id"], "text": text}, sync=dev["out_branch"])
        except (UserError, agents.AgentError) as e:     # z. B. Review auf einem anderen Rechner: dann ein neues Review über den Dialog
            return {"fallback": True, "why": str(e)}
        self.audit("agent.again", dev["ticket"], dev=dev["id"], review=rv["id"], new_run=out["id"])
        return out

    def _phase_prompt(self, svc, aid, phase, b):
        """Review oder Test auf dem Ergebnis eines beendeten Laufs: derselbe Branch, Kriterien und Bericht als Grundlage."""
        old = svc.store.agent_run(self._rid({"run": b.get("parent")}))
        if not old or old["status"] in ("zugewiesen", "läuft"):
            raise UserError("%s geht erst, wenn der vorige Lauf beendet ist." % agents.PHASE_LABEL[phase])
        ov = svc.run_view(old)
        if ov["phase"] == "plan":
            raise UserError("Ein Plan hat keinen Code. Zuerst umsetzen lassen.")
        base = ov.get("taken") or (ov.get("out_branch") if ov.get("mode") == "worktree" else "")
        if not base and ov["phase"] in ("review", "test") and ov.get("parent"):      # Review/Test ändern nichts: zurück zum Lauf mit dem Code
            src = svc.store.agent_run(self._rid({"run": ov["parent"]}))
            sv = svc.run_view(src) if src else {}
            base = sv.get("taken") or (sv.get("out_branch") if sv.get("mode") == "worktree" else "") or ov.get("branch") or ""
        if not base:
            raise UserError("Dieser Lauf hat keinen eigenen Branch, den ein zweiter Agent %s könnte." % ("prüfen" if phase == "review" else "testen"))
        brief = briefing.prereview(ov) if phase == "review" else briefing.test_brief(ov)
        info = svc.prompt_info(aid, ov["ticket"], ov["project_id"], base, ov.get("title") or "", b.get("key") or ov["ticket"], b.get("url") or "",
                               template=agents.PHASE_TEMPLATE[phase], extra={"brief": brief})
        info.update(branch=base, project_id=ov["project_id"], parent=ov["id"], phase=phase, repo=self._repo_access(svc, aid, ov["project_id"]))
        if phase == "review":
            info["review_of"] = ov["id"]        # 0.40: hiess «prereview»
        return info

    def clone_url(self, pid, via="ssh"):
        """Adresse, von der der Agent ein Projekt klont: GitLab laut API, GitHub aus dem Repo-Namen. Ohne Zugangsdaten in der Adresse."""
        via = via if via in ("ssh", "https") else "ssh"
        if self.demo:
            raise UserError("In der Demo wird nichts geklont.")
        if pid >= 10 ** 12:
            r = next((x for x in self.ghc.get("repos") or [] if x.get("id") and github.pid_of(x["id"]) == pid), None)
            if not r or not r.get("full"):
                raise UserError("Dieses GitHub-Repo ist nicht eingerichtet.")
            host = (self._ws_hosts()["github"] or ["github.com"])[-1]
            host = "github.com" if host in ("api.github.com", "") else host
            return ("git@%s:%s.git" if via == "ssh" else "https://%s/%s.git") % (host, r["full"])
        u = {}
        if self.client is not None and hasattr(self.client, "clone_urls"):
            try:
                u = self.client.clone_urls(pid)
            except (HttpStatus, UserError) as e:
                raise UserError("GitLab nennt für dieses Projekt keine Adresse: %s" % scrub(e))
        url = workspaces.safe_url(u.get(via) or "")
        if not url:
            raise UserError("Für dieses Projekt ist keine %s-Adresse bekannt." % via.upper())
        return url

    def _repo_access(self, svc, aid, pid, fresh=False):
        """Liegt das Projekt beim Agenten? Für den Zuweisen-Dialog. Fehler beim Nachsehen stehen im Ergebnis, sie blockieren nichts."""
        if pid is None:
            return None
        try:
            st = dict(svc.access(aid, fresh).get(pid) or {"state": "", "remote": "", "path": ""})
        except agents.AgentError as e:
            return {"state": "", "error": str(e), "clone": svc.clone_state(aid, pid)}
        st["clone"] = svc.clone_state(aid, pid)
        st["via"] = svc.agent(aid).get("clone_via", "ssh")
        if st["state"] == "git" and st.get("remote"):
            want = next((p for p in self._ws_projects() if p["pid"] == pid), None)
            host, path = workspaces.parse_remote(st["remote"])
            st["remote"] = "%s/%s" % (host, path) if host else path
            if want and want.get("full") and path and want["full"].lower() != path.lower():
                st["mismatch"] = "Im Ordner liegt %s, erwartet ist %s." % (path, want["full"])
        return st

    # -- Offene Review-Punkte (0.18): lesen, exportieren, als Agenten-Auftrag
    def _find_mr(self, host, pid, iid):
        with self.cache_lock:
            data = self.cache or {}
        for it in (data.get("mine") or []) + (data.get("review") or []) + (data.get("assigned") or []):
            if it.get("iid") == iid and it.get("project_id") == pid and (it.get("host") or "gitlab") == host:
                return it
        return None

    def _data_class(self, pid):
        p = self.agents.project(pid)
        return agents.data_class(p) if p else "restricted"

    def review_topics(self, b):
        host = "github" if b.get("host") == "github" else "gitlab"
        try:
            pid, iid = int(b.get("project_id")), int(b.get("iid"))
        except (TypeError, ValueError):
            raise UserError("project_id und iid müssen Zahlen sein.")
        it = self._find_mr(host, pid, iid)
        if not it:
            raise UserError("Diesen %s kenne ich nicht (mehr). Einmal «Neu laden»." % ("PR" if host == "github" else "MR"))
        key = (host, pid, iid)
        hit = self._rv_cache.get(key)
        if hit and time.time() - hit[0] < 60 and not b.get("fresh"):
            return hit[1]
        mr = {"host": host, "project_id": pid, "iid": iid, "title": it.get("title", ""), "project": it.get("project", ""), "branch": it.get("branch", ""),
              "url": it.get("url", ""), "sha": it.get("sha", ""), "target_branch": "", "kind": it.get("kind", "")}
        note = ""
        try:
            if host == "gitlab" or self.demo:
                if not self.client:
                    raise UserError("GitLab ist nicht verbunden.")
                m, disc = self.client.review_threads(pid, iid)
                mr.update(target_branch=m.get("target_branch") or "", sha=m.get("sha") or mr["sha"], url=m.get("web_url") or mr["url"])
                topics = review.gitlab_topics(disc, mr["sha"])
                for t in topics:
                    t["url"] = "%s#note_%s" % (mr["url"], t["note_id"]) if mr["url"] and t.get("note_id") else ""
            else:
                if not self.github:
                    raise UserError("GitHub ist nicht verbunden.")
                pr, comments, revs = self.github.review_threads(it.get("project", ""), iid)
                mr.update(target_branch=(pr.get("base") or {}).get("ref") or "", sha=(pr.get("head") or {}).get("sha") or mr["sha"])
                topics = review.github_topics(comments, revs, mr["sha"])
                note = "GitHub zeigt über die REST-API nicht, ob ein Thread erledigt ist. Alle Threads sind dabei; wähle ab, was schon erledigt ist."
        except github.GitHubError as e:
            raise UserError(str(e))
        res = {"mr": mr, "topics": topics, "data_class": self._data_class(pid), "configured": self.agents.project(pid) is not None,
               "note": note, "fetched": time.time()}
        self._rv_cache[key] = (time.time(), res)
        log.info("Review-Punkte %s %s!%s: %d offen", host, pid, iid, len(topics))
        return res

    def _review_pick(self, b):
        res = self.review_topics(b)
        ids = b.get("ids")
        topics = [t for t in res["topics"] if ids is None or t["id"] in set(ids)]
        if not topics:
            raise UserError("Keine Punkte ausgewählt.")
        return res, topics

    def _review_template(self):
        try:
            return (self.base / "prompts" / "review-topics.md").read_text(encoding="utf-8")
        except OSError:
            return "Offene Review-Punkte zu {mr_ref}: {title}\n{workspace_line}\n{topics}\n"

    def review_export(self, b):
        """Markdown (als Prompt zum Kopieren) oder JSON (mit allen Zielangaben). Schreibt einen Eintrag in den Verlauf."""
        fmt = "json" if b.get("format") == "json" else "md"
        res, topics = self._review_pick(b)
        mr = res["mr"]
        if fmt == "json":
            text = review.dumps(review.to_json(mr, topics, res["data_class"]))
        else:
            text = review.to_markdown(mr, topics, self._review_template(), {"workspace_line": "", "ask_hint": "", "report_hint": ""})
        self.audit("review.export", "%s%s%s" % (mr["project_id"], "#" if mr["host"] == "github" else "!", mr["iid"]), format=fmt,
                   topics=len(topics), data_class=res["data_class"], branch=mr["branch"])
        name = "review-%s-%s.%s" % (review.context(mr)["mr_ref"].replace(" ", "").replace("!", "").replace("#", ""), time.strftime("%Y%m%d-%H%M"), fmt)
        return {"text": text, "format": fmt, "filename": name.lower(), "count": len(topics), "data_class": res["data_class"]}

    def review_prompt_extra(self, rv):
        """Platzhalter für prompts/review-topics.md, wenn ein Agent die Punkte bearbeitet."""
        res, topics = self._review_pick(rv)
        mr = res["mr"]
        ctx = review.context(mr)
        return dict(ctx, count=len(topics), topics=review.topics_block(mr, topics), ask_hint=" mit `tinyops-ask`", report_hint=", als Bericht mit `tinyops-report`"), mr

    # -- Prompts
    MR_PROMPTS = ("review-brief", "smoke-test", "repro-test")      # zum Kopieren am MR, auch ohne eingerichteten Agenten (E2)

    def prompt_names(self):
        return [n for n in self.MR_PROMPTS if (self.base / "prompts" / (n + ".md")).exists()]

    def _prompt_text(self, name):
        if name not in self.MR_PROMPTS:
            raise UserError("Ungültiger Prompt-Name.")
        path = self.base / "prompts" / (name + ".md")
        if not path.exists():
            raise UserError("Prompt nicht gefunden.")
        return path.read_text(encoding="utf-8")

    def _mr_vars(self, project_id, iid):
        proj = self.proj_cfg.get(project_id)
        if not proj:
            raise UserError("Projekt ist nicht in der config.json eingetragen.")
        mr = self.client.mr(project_id, iid)
        keys = extract_keys("%s %s" % (mr["branch"], mr["title"]), self.jc.get("project_keys"))
        pe = proj.get("review_env")
        rv = reviewenv.mr_values(proj.get("name", str(project_id)), iid, mr["branch"], "", mr["sha"])
        return proj, {
            "project": proj.get("name", str(project_id)), "branch": mr["branch"],
            "mr_iid": iid, "iid": iid, "mr_url": mr["url"], "title": mr["title"],
            "sha": mr["sha"], "sha8": (mr["sha"] or "")[:8], "ticket": keys[0] if keys else "",
            "review_name": rv["name"] if pe else "(keine Review-Umgebung eingetragen)",
            "review_url": reviewenv.fill(pe.get("url"), rv, quote=False) if pe and pe.get("url") else "(keine Adresse eingetragen)",
        }

    def render_prompt(self, name, project_id, iid):
        _, vals = self._mr_vars(project_id, iid)
        return render(self._prompt_text(name), vals)

    def triage_prompt(self):
        ideas = [i for i in self.ideas.list() if i["status"] in ("neu", "geparkt") and not i["expired"]]
        if not ideas:
            raise UserError("Keine offenen Ideen.")
        lines = "\n".join("- (#%d, %d Tage alt) %s" % (i["id"], i["age_days"], i["text"].replace("\n", " ")) for i in ideas)
        return render((self.base / "prompts" / "idea-triage.md").read_text(encoding="utf-8"), {"ideas": lines})
