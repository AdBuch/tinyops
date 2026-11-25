"""Übersicht und Sync: GitLab, Jira, GitHub, Sonar und Helpdesk abgleichen, Übersicht bauen, KI-Kontingent.

Bereich von App (0.38 aus server.py gelöst). Gemeinsames (cfg, store, Audit, Cache) kommt von App;
Aufrufe in andere Bereiche stehen in USES und werden von tests/test_areas.py geprüft."""

import threading
import time
from datetime import datetime, timezone

import aiquota
import flow
import groups
import helpdesk
import links
import settings
import sonar
import tlog
import voice
from common import UserError, extract_keys, ignored_branch, parse_ts
from gitlab_client import branch_cfg, classify_commits, identity
from secretstore import scrub

jlog = tlog.get("jira")
log = tlog.get("app")
rlog = tlog.get("refresh")
slog = tlog.get("sonar")
slog_u = tlog.get("usage")


class SyncArea:
    # Aufrufe in andere Bereiche (tests/test_areas.py prüft, dass genau diese benutzt werden)
    USES = {
        "area_agents": ("agents_view", "prompt_names"),
        "area_focus": ("focus_state",),
        "area_ide": ("_repo_of",),
        "area_m365": ("_m365_fetch", "m365_state"),
        "area_qa": ("update_note",),
        "area_tickets": ("_board", "_group_linked", "_key_rules", "_local_keys", "_local_ticket", "pools_view", "ticket_meta"),
        "area_time": ("time_state",),
        "area_workspaces": ("_ws_summary",),
    }

    @staticmethod
    def _scope_key(key, pr, br):
        return "%s|%s|%s" % (key, pr or "", br or "")

    def _sonar_trend(self, key, pr, br, res):
        """Verlauf der Findings eines MR/Branches: aus Sonars eigener Historie (ab zwei Analysen), sonst aus lokalen Schnappschüssen der Gate-Werte.
        Gleichzeitig wird der aktuelle Stand lokal vermerkt (nur bei Änderung)."""
        scope = self._scope_key(key, pr, br)
        vals = res.get("values") or {}
        if vals:
            try:
                self.store.snap_add(scope, vals)
            except Exception as e:      # der Verlauf ist Beiwerk und darf den Abgleich nie stoppen
                slog.warning("Schnappschuss nicht gespeichert: %s", e)
        try:
            pts = self.sonar.history(key, pr=pr, branch=br, metrics=("violations",))
        except sonar.SonarError as e:
            if e.auth:
                raise
            pts = []
        t = sonar.trend_of([(p["ts"], p.get("violations")) for p in pts], "Sonar-Verlauf")
        if t:
            return t
        rows = self.store.snap_rows(scope)
        for metric in ("new_violations", "violations"):
            t = sonar.trend_of([(ts, v.get(metric)) for ts, v in rows], "lokal beobachtet")
            if t:
                return t
        return None

    def sonar_report(self, project_id, iid=None, branch=None):
        """Findings eines MR oder Branches als Markdown für die Zwischenablage (nur lesend, auf Knopfdruck, nicht im Abgleich)."""
        if not self.sonar:
            raise UserError("Sonar ist nicht eingeschaltet oder es fehlt der Token (Einstellungen → Sonar).")
        p = self.proj_cfg.get(project_id)
        key = (p or {}).get("sonar_key") or ("dlp-core" if self.demo and project_id == 1 else "dlp-ui" if self.demo and project_id == 2 else "")
        if not key:
            raise UserError("Für dieses Projekt ist kein Sonar-Schlüssel eingetragen (Einstellungen → GitLab).")
        pr = int(iid) if iid else None
        br = None if pr else (str(branch or "").strip() or None)
        if not pr and not br:
            raise UserError("MR oder Branch fehlt.")
        limit = int(self.sc["report_max"])
        try:
            gate = self.sonar.gate(key, pr=pr, branch=br)
            issues, total, facets = self.sonar.issues(key, pr=pr, branch=br, limit=limit)
            hot = self.sonar.hotspots(key, pr=pr, branch=br)
            pts = self.sonar.history(key, pr=pr, branch=br, metrics=tuple(k for k, _ in sonar.HIST_COLS), limit=12)
        except sonar.SonarError as e:
            slog.warning("Report: %s", e)
            raise UserError(str(e))
        title = "%s, %s" % ((p or {}).get("name") or key, ("MR !%d" % pr) if pr else "Branch %s" % br)
        slog.info("Report erzeugt: %s (%d von %d Findings)", title, len(issues), total)
        hist = {"source": "Sonar-Verlauf", "cols": sonar.HIST_COLS, "rows": pts} if len(pts) > 1 else None
        if not hist:
            snaps = self.store.snap_rows(self._scope_key(key, pr, br), 12)
            if len(snaps) > 1:
                hist = {"source": "lokal beobachtet", "rows": [dict(v, ts=ts) for ts, v in snaps],
                        "cols": (("new_violations", "Neue Findings"), ("new_coverage", "Abdeckung neuer Code %"), ("new_duplicated_lines_density", "Duplikate neuer Code %"))}
        text = sonar.format_report(title, gate, key, issues, total, facets, hot, gate.get("issues_url") or gate.get("url"), limit, hist)
        return {"text": text, "issues": len(issues), "total": total, "hotspots": len(hot[0]) if hot else 0, "truncated": total > len(issues)}

    def usage_providers(self):
        return [k for k in ("claude", "codex", "mistral") if self.uc.get(k)]

    def usage_view(self, fresh=False):
        """Rest-Kontingent der Abos. Claude und Codex werden abgefragt und zwischengespeichert, jeder einzeln (ein Fehler stoppt den
        anderen nicht). Mistral kommt aus dem zuletzt per Lesezeichen gesendeten Stand und kostet keine Anfrage."""
        prov = self.usage_providers()
        if not prov:
            return {"enabled": False, "items": [], "fetched": 0}
        remote = [k for k in prov if k != "mistral"]
        with self._usage_lock:
            c = self._usage_cache
            if not (c and not fresh and time.time() - c["fetched"] < float(self.uc["cache_seconds"]) and c["kinds"] == remote):
                now = time.time()
                if self.demo:
                    demo = [{"id": "claude", "name": "Claude", "ok": True, "error": "", "fetched": now, "windows": [
                                {"label": "5 h", "used_pct": 62.0, "left_pct": 38.0, "resets_at": now + 5400, "secs_left": 5400},
                                {"label": "Woche", "used_pct": 41.0, "left_pct": 59.0, "resets_at": now + 3 * 86400, "secs_left": 3 * 86400}]},
                            {"id": "codex", "name": "Codex (ChatGPT)", "ok": False, "fetched": now, "windows": [],
                             "error": "Anmeldedatei nicht gefunden (~/.codex/auth.json). Im Container: Datei als Volume einhängen."}]
                    items = [i for i in demo if i["id"] in remote]
                else:
                    items = []
                    for k in remote:
                        r = aiquota.fetch(k, self.uc.get(k + "_file") or None)
                        if not r["ok"]:
                            slog_u.warning("%s: %s", r["name"], r["error"])
                        items.append(r)
                c = self._usage_cache = {"enabled": True, "items": items, "fetched": now, "kinds": list(remote)}
            out = list(c["items"])
        if "mistral" in prov:
            if self.demo:
                now = time.time()
                out.append(aiquota.mistral_item({"pushed": now - 600, "budgets": {
                    "vibe": {"pct": 0.06, "budget": 300.0, "cur": "USD", "reset": now + 26 * 86400},
                    "api": {"pct": 0.159, "budget": 30.0, "cur": "USD", "reset": now + 26 * 86400}}}))
            else:
                out.append(aiquota.mistral_item(aiquota.load_push(self.data_dir())))
        return {"enabled": True, "items": out, "fetched": c["fetched"]}

    def usage_push(self, body):
        """Stand von Mistral aus dem Lesezeichen. Enthält nur Prozent, Budget und Reset, nie Cookies."""
        if not self.uc.get("mistral"):
            raise UserError("Mistral ist in den Einstellungen (KI-Kontingent) nicht eingeschaltet.")
        try:
            clean = aiquota.clean_push(body)
        except aiquota.UsageError as e:
            raise UserError(str(e))
        aiquota.save_push(self.data_dir(), clean)
        slog_u.info("Mistral-Stand empfangen: %s", ", ".join("%s %.2f %%" % (k, v["pct"]) for k, v in clean.items()))
        return {"ok": True, "item": aiquota.mistral_item(aiquota.load_push(self.data_dir()))}

    # -- Jira-Verknüpfung (läuft beim Auffrischen des Caches)
    def _jira_data(self, data, pre=None):
        j = self.jira
        if not j:
            return None
        limit = int(self.jc["story_limit"])
        out = {"enabled": True, "ok": False, "limit": limit, "count": 0, "over": False,
               "stories": [], "url": j.base, "error": ""}
        items = data["mine"] + data["review"] + data["assigned"]
        try:
            inprog = pre() if pre else j.in_progress()       # 0.30: alle Typen bleiben sichtbar; die Typen bestimmen nur, was zum Limit zählt
            allowed = self._key_rules()
            manual = self.store.links()
            for it in items:
                it["keys"] = extract_keys("%s %s" % (it["branch"], it["title"]), allowed)
                m = manual.get(it["ref"])
                it["manual_link"] = m or ""
                if m:
                    it["keys"] = [m]   # eine von Hand gesetzte Verknüpfung gilt vor der Erkennung aus dem Namen
            progress_keys = {i["key"] for i in inprog}
            cand = {k for it in items for k in it["keys"]} | set(self.store.pool_tickets()) | set(self.store.staged_tickets())
            wanted = sorted(k for k in cand if not links.is_local_key(k) and k not in progress_keys)
            known = j.lookup(wanted) if wanted else {}
        except UserError as e:
            jlog.error("Jira-Abfrage fehlgeschlagen: %s", e)
            out["error"] = str(e)
            data["errors"].append("Jira: %s" % e)
            return out
        by_key = {k: dict(v, in_progress=False) for k, v in known.items()}
        by_key.update({i["key"]: dict(i, in_progress=True) for i in inprog})
        by_key.update({t["key"]: self._local_ticket(t) for t in self.store.tasks()})   # Aufgaben ohne Jira-Ticket zählen wie Tickets
        self._by_key = by_key
        heads, head_of = groups.build(inprog, self.store.groups(), self.jc.get("group_link_types") or (), self.jc.get("wip_issue_types") or ())
        self._head_of = head_of
        counted = sum(1 for h in heads if h["counts"])
        over = counted > limit
        for it in items:
            tk = next((by_key[k] for k in it["keys"] if k in by_key), None)
            it["ticket"] = tk
            it["ticket_unknown"] = it["keys"][0] if (it["keys"] and not tk) else ""
            it["no_ticket"] = (not it["keys"]) and it["kind"] in ("mr", "branch")
            it["create_url"] = j.create_url(it["title"]) if it["no_ticket"] else ""
            it["agent_locked"] = bool(over and not (tk and tk["in_progress"]))
        for s in heads:
            linked = self._group_linked(s, items)
            s["items"] = linked
            s["no_mr"] = not any(x["kind"] in ("mr", "assigned") for x in linked)
        sprints = {}
        for t in list(by_key.values()):
            if t.get("sprint") and t["sprint"] not in sprints:
                end = t.get("sprint_end") or ""
                left = None
                if parse_ts(end):
                    left = int((parse_ts(end) - datetime.now(timezone.utc)).total_seconds() // 86400) if parse_ts(end).tzinfo else None
                sprints[t["sprint"]] = {"name": t["sprint"], "end": end, "days_left": left}
        out["sprints"] = list(sprints.values())
        out["only_active"] = bool(self.jc.get("only_active_sprints", True))
        out.update({"ok": True, "count": counted, "over": over, "stories": heads, "tickets": len(inprog)})
        linked_n = sum(1 for it in items if it.get("ticket"))
        jlog.info("%d Tickets in Arbeit, %d Tasks davon %d zählend (Limit %d)%s; %d von %d Einträgen mit Ticket verknüpft, %d ohne Key, %d Key unbekannt",
                  len(inprog), len(heads), counted, limit, " → ÜBER DEM LIMIT" if over else "", linked_n, len(items),
                  sum(1 for it in items if it.get("no_ticket")), sum(1 for it in items if it.get("ticket_unknown")))
        for it in items:
            if it.get("ticket_unknown"):
                jlog.debug("Key %s aus %s/%s nicht in Jira gefunden", it["ticket_unknown"], it["project"], it["branch"])
        self.over_limit, self.inprogress_keys = over, progress_keys
        return out

    # -- Synchronisation: läuft im Hintergrund, Teilergebnisse sind sofort sichtbar
    def _step(self, sid, title, status, detail=""):
        now = time.time()
        with self.sync_lock:
            st = next((x for x in self.sync["steps"] if x["id"] == sid), None)
            if st is None:
                st = {"id": sid, "title": title, "status": "wait", "detail": "", "t0": 0.0, "secs": None}
                self.sync["steps"].append(st)
            if status == "run" and not st["t0"]:
                st["t0"] = now
            if status in ("ok", "err") and st["t0"]:
                st["secs"] = round(now - st["t0"], 1)
            st["status"], st["detail"] = status, str(detail)[:120]

    def start_sync(self):
        """Startet eine Synchronisation im Hintergrund, falls nicht schon eine läuft. Gibt True zurück, wenn eine neu begann."""
        with self.sync_lock:
            if self.sync["running"]:
                return False
            self.sync = {"running": True, "steps": [], "started": time.time(), "finished": 0.0, "n": self.sync["n"] + 1}
            self.partial = {"mine": [], "review": [], "assigned": [], "errors": [], "me": ""}
            self.early_stories = None
            t = threading.Thread(target=self._run_sync, name="sync", daemon=True)
            self._sync_thread = t
        t.start()
        return True

    def _run_sync(self):
        data = None
        try:
            data = self._refresh(self.partial, self._step)
        except Exception as e:   # der Hintergrund-Thread darf nie still sterben
            rlog.exception("Synchronisation abgebrochen: %s", e)
            data = {"me": "", "mine": [], "review": [], "assigned": [], "errors": ["Synchronisation abgebrochen: %s" % e], "jira": None}
        finally:
            with self.cache_lock:
                if data is not None:
                    self.cache, self.cache_t = data, time.time()
            with self.sync_lock:
                self.sync["running"] = False
                self.sync["finished"] = time.time()

    def sync_view(self):
        with self.sync_lock:
            sy = self.sync
            steps = sorted((dict(x) for x in sy["steps"]), key=lambda x: {"ji-link": 1, "sonar": 2}.get(x["id"], 0))   # Verknüpfen und Sonar kommen zuletzt
            return {"running": sy["running"], "n": sy["n"], "started": sy["started"], "finished": sy["finished"],
                    "steps": steps, "done": sum(1 for x in steps if x["status"] in ("ok", "err")), "total": len(steps),
                    "secs": round((sy["finished"] or time.time()) - sy["started"], 1) if sy["started"] else 0}

    def _refresh(self, sink=None, step=None):
        t0 = time.time()
        step = step or (lambda *a, **k: None)
        self.refresh_no = getattr(self, "refresh_no", 0) + 1
        rlog.info("Auffrischen #%d beginnt", self.refresh_no)
        pre_holder = {}
        pre_thread = None
        if self.jira:
            step("ji-stories", "Jira: Stories in Arbeit", "run")

            def early():
                try:
                    r = self.jira.in_progress()
                    pre_holder["v"] = r
                    self.early_stories = r
                    step("ji-stories", "Jira: Stories in Arbeit", "ok", "%d Tickets" % len(r))
                except UserError as e:
                    pre_holder["e"] = e
                    step("ji-stories", "Jira: Stories in Arbeit", "err", str(e))
            pre_thread = threading.Thread(target=early, daemon=True)
            pre_thread.start()
            step("ji-link", "Tickets mit Branches verknüpfen", "wait")
        if self.sonar:
            step("sonar", "Sonar: Quality Gates", "wait")

        def pre():
            pre_thread.join()
            if "e" in pre_holder:
                raise pre_holder["e"]
            return pre_holder["v"]
        try:
            if self.client is None:
                data = sink if sink is not None else {}
                data.update(me=data.get("me", ""), errors=data.get("errors", []))
                for k in ("mine", "review", "assigned"):
                    data.setdefault(k, [])
            else:
                data = self.client.fetch(sink, step)
        except UserError as e:
            rlog.error("GitLab-Abfrage fehlgeschlagen: %s", e)
            step("gl-user", "Bei GitLab anmelden", "err", str(e))
            data = sink if sink is not None else {}
            data.setdefault("me", "")
            for k in ("mine", "review", "assigned"):
                data.setdefault(k, [])
            data.setdefault("errors", []).append(str(e))
            data["gl_failed_all"] = True
        gl_err = bool(data.get("gl_failed_all") or data.get("gl_failed_pids")) or any(not str(x).startswith("GitHub") for x in data.get("errors", []))
        n_err = len(data.get("errors", []))
        if self.github:
            self._github_fetch(data, step)
        gh_err = bool(data.get("gh_failed_all") or data.get("gh_failed_repos")) or len(data.get("errors", [])) > n_err
        self._keep_last_good(data)
        for it in data["mine"] + data["review"] + data["assigned"]:
            it["ref"] = links.ref_of(it["project_id"], it["branch"])
        if not self.jira:
            self._local_keys(data)
        if self.jira:
            step("ji-link", "Tickets mit Branches verknüpfen", "run")
            data["jira"] = self._jira_data(data, pre)
            j = data["jira"]
            step("ji-link", "Tickets mit Branches verknüpfen", "err" if not j["ok"] else "ok", j.get("error", "") if not j["ok"] else "")
            if not j["ok"]:
                self._by_key = {}
        else:
            data["jira"] = None
        data["sonar"] = self._sonar(data, step)
        if self.hdj:
            data["helpdesk_jira"] = self._helpdesk_fetch(step)
        self._review_xp(data)
        self._m365_fetch(step)
        now = time.time()
        src = []
        if self.client is not None:
            src.append(("gitlab", "GitLab", not gl_err))
        if self.github is not None:
            src.append(("github", "GitHub", not gh_err))
        if self.jira:
            src.append(("jira", "Jira", bool((data.get("jira") or {}).get("ok"))))
        if self.sonar:
            src.append(("sonar", "Sonar", bool((data.get("sonar") or {}).get("ok", True))))
        if self.hdj:
            src.append(("helpdesk", self.hdc.get("name") or "Helpdesk", bool((data.get("helpdesk_jira") or {}).get("ok"))))
        data["sources"] = []
        for sid, name, ok in src:
            if ok:
                self._src_ok[sid] = now
            data["sources"].append({"id": sid, "name": name, "ok": ok, "ts": now, "last_ok": self._src_ok.get(sid, 0)})
        rlog.info("Auffrischen #%d fertig in %.1f s: %d eigene Einträge, %d Review, %d zugeteilt, %d Fehler",
                  self.refresh_no, time.time() - t0, len(data["mine"]), len(data["review"]), len(data["assigned"]),
                  len(data["errors"]))
        return data

    # -- Review gibt XP (0.28): eine Freigabe von dir auf einem MR in deiner Review-Liste, einmal je MR
    REVIEW_XP = 20

    def _review_xp(self, data):
        me = (data.get("me") or "").lower()
        if not me:
            return
        for it in data.get("review") or []:
            if me in [x.lower() for x in it.get("approved_by") or []] and it.get("iid"):
                ref = "review:%s!%s" % (it["project_id"], it["iid"])
                if self.store.flow_event_once(ref, it.get("key") or "!%s" % it["iid"], it.get("title") or "", "review", 0, self.REVIEW_XP,
                                              "Review freigegeben: %s !%s" % ((self.proj_cfg.get(it["project_id"]) or {}).get("name") or it["project_id"], it["iid"])):
                    self.audit("flow.review", ref, xp=self.REVIEW_XP)

    def _helpdesk_fetch(self, step):
        """Helpdesk-Jira lesen. Fällt es aus, bleiben die letzten Tickets stehen, als veraltet markiert."""
        name = self.hdc.get("name") or "Helpdesk"
        step("hd", "%s: zugewiesene Tickets und Queue" % name, "run")
        try:
            r = helpdesk.fetch(self.hdj, self.hdc)
            step("hd", "%s: zugewiesene Tickets und Queue" % name, "ok", "%d zugewiesen, %d in der Queue, %d beobachtet" % (r["assigned_total"], r["queue_total"], len(r.get("watched") or [])))
            return r
        except UserError as e:
            jlog.warning("Helpdesk-Jira: %s", e)
            step("hd", "%s: zugewiesene Tickets und Queue" % name, "err", str(e))
            prev = (self.cache or {}).get("helpdesk_jira")
            if prev:
                return dict(prev, ok=False, outdated=True, error=str(e))
            return {"assigned": [], "queue": [], "assigned_total": 0, "queue_total": 0, "ok": False, "error": str(e), "name": name, "sla_hours": self.hdc["sla_hours"]}

    def helpdesk_seen(self, b):
        hd = (self.cache or {}).get("helpdesk_jira") or {}
        if b.get("all") == "watch":
            keys = [t["key"] for t in hd.get("watched") or []]
        elif b.get("all"):
            keys = [t["key"] for t in hd.get("queue") or []]
        else:
            keys = [str(k) for k in (b.get("keys") or []) if helpdesk.KEY_RE.match(str(k))][:200]
        self.store.hd_seen_add(keys)
        return {"seen": len(keys)}

    def helpdesk_ticket(self, key):
        """Ein Helpdesk-Ticket zum Lesen im Panel (Beschreibung, letzte Kommentare). Nur Tickets, die tinyops gerade zeigt."""
        hd = (self.cache or {}).get("helpdesk_jira") or {}
        known = {t["key"] for k in ("assigned", "queue", "watched") for t in hd.get(k) or []}
        if key not in known or self.hdj is None:
            raise UserError("Dieses Helpdesk-Ticket zeigt tinyops gerade nicht.")
        try:
            d = self.hdj.detail(key) if hasattr(self.hdj, "detail") else helpdesk.detail(self.hdj, key)
        except ValueError as e:
            raise UserError(str(e))
        if any(t["key"] == key for t in hd.get("watched") or []):
            self.store.hd_seen_add([key])
        return d

    def _keep_last_good(self, data):
        """Fällt eine Quelle (ganz oder je Projekt/Repo) aus, bleiben ihre letzten Einträge stehen, als «veraltet» markiert (outdated),
        statt aus Board und Fokus zu verschwinden."""
        prev = self.cache
        if not prev:
            return
        gl_all, gl_pids = data.get("gl_failed_all"), set(data.get("gl_failed_pids") or [])
        gh_all, gh_repos = data.get("gh_failed_all"), set(data.get("gh_failed_repos") or [])
        if not (gl_all or gl_pids or gh_all or gh_repos):
            return
        kept = 0
        for lst in ("mine", "review", "assigned"):
            have = {links.ref_of(i["project_id"], i["branch"]) for i in data.get(lst, [])}
            for it in prev.get(lst, []):
                gh = it.get("host") == "github"
                hit = (gh and (gh_all or it.get("project") in gh_repos)) or (not gh and (gl_all or (lst == "mine" and it.get("project_id") in gl_pids)))
                ref = links.ref_of(it["project_id"], it["branch"])
                if hit and ref not in have:
                    x = dict(it, outdated=True, outdated_since=it.get("outdated_since") or self.cache_t or time.time())
                    data.setdefault(lst, []).append(x)
                    have.add(ref)
                    kept += 1
        if kept:
            rlog.warning("%d Einträge aus dem letzten erfolgreichen Abgleich behalten (als veraltet markiert)", kept)

    def _github_fetch(self, data, step):
        bf = branch_cfg(self.cfg)
        ign = list(bf.get("ignore_branches") or [])
        ident = identity(self.cfg, {})
        repos = [r["full"] for r in self.ghc["repos"] if r.get("full")]
        self.github.fetch(repos, ident, classify_commits, bf, lambda b: ignored_branch(b, ign), data, step)

    def _sonar(self, data, step):
        """Quality Gate jedes MR und Branches (nur lesend). Ergebnisse stehen danach in it["sonar"]; ein einzelner Fehler stoppt nichts,
        falsche Zugangsdaten brechen ab, weil alle weiteren Abfragen dasselbe Ergebnis hätten."""
        if not self.sonar:
            return None
        title = "Sonar: Quality Gates"
        step("sonar", title, "run")
        keys = {pid: p.get("sonar_key") for pid, p in self.proj_cfg.items() if p.get("sonar_key")}
        if self.demo:
            keys = {pid: p.get("sonar_key") or p.get("name", str(pid)) for pid, p in self.proj_cfg.items()}
            keys.update({1: "dlp-core", 2: "dlp-ui"})
        cand = [it for lst in ("mine", "assigned", "review") for it in data[lst] if keys.get(it["project_id"]) and (it.get("iid") or it["kind"] == "branch")]
        out = {"enabled": True, "ok": True, "error": "", "checked": 0, "red": 0, "warn": 0, "none": 0, "failed": 0, "skipped": max(0, len(cand) - int(self.sc["max_items"]))}
        cand = cand[:int(self.sc["max_items"])]
        if not cand:
            step("sonar", title, "ok", "keine MRs/Branches mit Sonar-Schlüssel" if not keys else "nichts zu prüfen")
            return out
        now, ttl = time.time(), float(self.sc["cache_seconds"])
        stop = threading.Event()

        def one(it):
            if stop.is_set():
                return
            key = keys[it["project_id"]]
            pr = it["iid"] if it.get("iid") else None
            br = None if pr else it["branch"]
            hit = self._sonar_cache.get((key, pr, br))
            if hit and now - hit[0] < ttl:
                it["sonar"] = hit[1]
                return
            try:
                res = self.sonar.gate(key, pr=pr, branch=br)
                if res["status"] in ("OK", "WARN", "ERROR"):
                    res["trend"] = self._sonar_trend(key, pr, br, res)
            except sonar.SonarError as e:
                if e.auth:
                    out["ok"], out["error"] = False, str(e)
                    stop.set()
                    return
                it["sonar"] = {"status": "UNKNOWN", "failed": [], "url": "", "detail": str(e)}
                out["failed"] += 1
                return
            self._sonar_cache[(key, pr, br)] = (time.time(), res)
            it["sonar"] = res
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=3) as pool:
            list(pool.map(one, cand))
        for it in cand:
            s = (it.get("sonar") or {}).get("status")
            if s:
                out["checked"] += 1
                out["red"] += s == "ERROR"
                out["warn"] += s == "WARN"
                out["none"] += s == "NONE"
        if not out["ok"]:
            step("sonar", title, "err", out["error"])
            slog.error("%s", out["error"])
            data["errors"].append(out["error"])
        else:
            detail = "%d geprüft, %d nicht bestanden%s" % (out["checked"], out["red"], ", %d Fehler" % out["failed"] if out["failed"] else "")
            if out["skipped"]:
                detail += ", %d übersprungen (Limit %d)" % (out["skipped"], int(self.sc["max_items"]))
            step("sonar", title, "err" if out["failed"] and not out["checked"] else "ok", detail)
            slog.info("%s", detail)
        return out

    def _partial_view(self):
        """Zwischenstand während der ersten Synchronisation: schon geladene Listen, Jira-Stories ohne Zuordnung."""
        p = self.partial or {}
        data = {"me": p.get("me", ""), "mine": [dict(i) for i in p.get("mine", [])], "review": [dict(i) for i in p.get("review", [])],
                "assigned": [dict(i) for i in p.get("assigned", [])], "errors": list(p.get("errors", [])), "partial": True}
        for it in data["mine"] + data["review"] + data["assigned"]:
            it["ref"] = links.ref_of(it["project_id"], it["branch"])
            it["keys"] = extract_keys("%s %s" % (it["branch"], it["title"]), self._key_rules()) if self.jira else []
        if self.jira:
            st = self.early_stories
            data["jira"] = {"enabled": True, "ok": st is not None, "loading": st is None, "partial": True, "limit": int(self.jc["story_limit"]),
                            "count": len(st or []), "over": False, "url": self.jira.base, "error": "", "sprints": [],
                            "only_active": bool(self.jc.get("only_active_sprints", True)),
                            "stories": [dict(x, items=[], no_mr=False, in_progress=True) for x in (st or [])]}
        else:
            data["jira"] = None
        data["sonar"] = {"enabled": True, "ok": True, "loading": True} if self.sonar else None
        return data

    def helpdesk(self):
        if not self.jira or not (self.jc.get("helpdesk") or {}).get("jql"):
            return None   # ohne eigene JQL aus (Standard)
        ttl = float((self.jc.get("helpdesk") or {}).get("cache_minutes", 30)) * 60
        with self.hd_lock:
            if time.time() - self.hd_t > ttl:
                try:
                    self.hd_cache = self.jira.helpdesk()
                except UserError as e:
                    self.hd_cache = {"error": str(e)}
                self.hd_t = time.time()
            return self.hd_cache

    # -- Übersicht
    def overview(self, wait=True):
        """wait=True wartet auf eine frische Synchronisation (Tests, Skripte). wait=False liefert sofort, was da ist: den Zwischenspeicher
        oder, solange noch nichts vollständig geladen ist, den Zwischenstand."""
        if not self.configured:
            return {"configured": False, "problems": list(self.problems), "me": "", "mine": [], "review": [], "assigned": [],
                    "errors": [], "jira": None, "wip": 0, "wip_limit": self.cfg["wip_limit"], "stale_days": self.cfg["stale_days"],
                    "demo": self.demo, "version": self.version, "usage_providers": self.usage_providers(), "features": {k: self.has(k) for k in settings.CONFIG_KEYS_FEATURES},
                    "agent_enabled": False, "prompts": [], "fetched": time.time(), "helpdesk": None}
        with self.cache_lock:
            expired = self.cache is None or time.time() - self.cache_t > self.cfg["cache_seconds"]
        if expired:
            self.start_sync()
        if wait:
            t = self._sync_thread
            if t is not None and expired:
                t.join()
        with self.cache_lock:
            cached = self.cache
        data = dict(cached) if cached is not None else self._partial_view()
        data["loading"] = cached is None
        data["board"] = None
        data["sync"] = self.sync_view()
        stale = self.cfg["stale_days"]
        wts = self.store.ide_all()
        for it in data["mine"] + data["review"] + data["assigned"]:
            it["stale"] = it["age_days"] >= stale
            if it.get("iid"):
                it["ide"] = bool(self._repo_of(it.get("host") or "gitlab", it["project_id"])) or self.demo
                w = wts.get(it.get("ref") or links.ref_of(it["project_id"], it.get("branch", "")))
                it["ide_wt"] = {"sha": w["sha"], "path": w["path"], "stale": bool(it.get("sha") and w["sha"] != it["sha"])} if w else None
        data["board"] = self._board(data)
        self._cards = {c["id"]: c for c in data["board"]["cards"]}
        agents_v = self.agents_view()
        by_ticket = {}
        for r in agents_v["runs"]:
            by_ticket.setdefault(r["ticket"], []).append(r)
        try:
            data["flow"] = flow.build(data["board"]["cards"], self.store, by_ticket, complete=not data["loading"] and not data.get("errors"),
                                      goal=int((self.cfg.get("flow") or {}).get("daily_goal", 3)))
            data["flow"]["reviews"] = flow.review_view(data)
            pin = self.store.pin_get()
            data["flow"]["pinned"] = pin if (pin in data["flow"]["items"] or (pin or "").startswith("rv:")) else None
        except Exception as e:   # der Ablauf ist eine Ansicht; er darf die Übersicht nie verhindern
            log.warning("Ablauf: %s", scrub(e))
            data["flow"] = None
        if data.get("flow") is not None:
            hd = data.get("helpdesk_jira")
            pin0 = self.store.pin_get() or ""
            ent, queue = helpdesk.entries(hd, self.store.hd_seen(), pin0[3:] if pin0.startswith("hd:") else None) if hd else ([], [])
            data["flow"]["helpdesk"] = ent
            data["flow"]["hd_queue"] = queue
            data["flow"]["hd_watch"] = helpdesk.watched(hd, self.store.hd_seen_ts()) if hd else []
            data["flow"]["hd_jira"] = self.store.hd_jira_map()          # 0.36: Helpdesk-Ticket → angelegtes Jira-Ticket
            data["flow"]["hd_info"] = {k: hd.get(k) for k in ("name", "url", "ok", "error", "outdated", "assigned_total", "queue_total", "watched_total", "watch_error", "sla_hours")} if hd else None
            pin = self.store.pin_get()
            if pin and pin.startswith("hd:") and any(e["id"] == pin for e in ent):
                data["flow"]["pinned"] = pin
        try:
            data["workspaces"] = self._ws_summary()
        except Exception as e:      # Zugabe: darf die Übersicht nie verhindern
            log.warning("Workspaces: %s", scrub(e))
            data["workspaces"] = None
        try:
            data["m365"] = self.m365_state()
        except Exception as e:      # Zugabe: darf die Übersicht nie verhindern
            log.warning("Microsoft 365: %s", scrub(e))
            data["m365"] = None
        try:
            data["focus"] = self.focus_state()
        except Exception as e:      # Zugabe: darf die Übersicht nie verhindern
            log.warning("Fokusbereiche: %s", scrub(e))
            data["focus"] = None
        try:
            data["time"] = self.time_state()
        except Exception as e:      # die Zeit ist eine Zugabe; sie darf die Übersicht nie verhindern
            log.warning("Zeit: %s", scrub(e))
            data["time"] = {"enabled": False, "error": str(e)}
        data.update({
            "wip": len(data["mine"]), "wip_limit": self.cfg["wip_limit"],
            "stale_days": stale, "demo": self.demo,
            "prompts": self.prompt_names(), "fetched": time.time(),
            "helpdesk": self.helpdesk(), "configured": True, "version": self.version, "usage_providers": self.usage_providers(), "problems": list(self.problems),
            "update": self.update_note(),
            "ux": {"enabled": bool((self.cfg.get("ux") or {}).get("enabled", True))},
            "features": {k: self.has(k) for k in settings.CONFIG_KEYS_FEATURES},
            "ignore_patterns": list(branch_cfg(self.cfg).get("ignore_branches") or []),
            "ticket": self.ticket_meta(),
            "pools": self.pools_view(data),
            "ai": self.store.ai_accounts() if self.has("ai") else [],
            "agents": agents_v,
            "voice": {"enabled": voice.ready(voice.cfg_of(self.cfg)), "max": int(voice.cfg_of(self.cfg).get("max_seconds") or 120)},   # 0.43
        })
        return data
