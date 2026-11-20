"""Tickets, Board und Ideen: Verknüpfen, Kategorien, Board, Ticket-Entwurf und Anlegen, Ideen bewerten.

Bereich von App (0.38 aus server.py gelöst). Gemeinsames (cfg, store, Audit, Cache) kommt von App;
Aufrufe in andere Bereiche stehen in USES und werden von tests/test_areas.py geprüft."""

import re
import time

import briefing
import groups
import helpdesk
import links
import llm
import settings
import tlog
from common import HttpStatus, UserError, extract_keys
from ideas import similar
from secretstore import scrub

jlog = tlog.get("jira")
log = tlog.get("app")


class TicketArea:
    # Aufrufe in andere Bereiche (tests/test_areas.py prüft, dass genau diese benutzt werden)
    USES = {"area_focus": ("_accept",), "area_ide": ("_ide_cleanup",)}

    def _key_rules(self):
        allowed = list(self.jc.get("project_keys") or [])
        return allowed + [links.LOCAL_PREFIX] if allowed else allowed   # tiny-Tickets (LOC-…) zählen im Branchnamen immer

    def _local_keys(self, data):
        """Ohne Jira: Keys aus Branchnamen und Hand-Verknüpfungen trotzdem setzen, damit tiny-Tickets ihre Branches finden."""
        manual = self.store.links()
        by_key = {t["key"]: self._local_ticket(t) for t in self.store.tasks()}
        self._by_key = by_key
        for it in data["mine"] + data["review"] + data["assigned"]:
            keys = [k for k in extract_keys("%s %s" % (it["branch"], it["title"])) if links.is_local_key(k)]
            m = manual.get(it["ref"])
            it["manual_link"] = m or ""
            it["keys"] = [m] if m else keys
            it["ticket"] = next((by_key[k] for k in it["keys"] if k in by_key), None)
            it["ticket_unknown"] = ""
            it["no_ticket"] = (not it["keys"]) and it["kind"] in ("mr", "branch")
            it["create_url"] = ""

    def _group_linked(self, head, items):
        """MRs und Branches eines Tasks: die des Kopf-Tickets und aller Begleittickets, ohne Doppelte."""
        seen, out = set(), []
        for k in [head["key"]] + [c["key"] for c in head.get("companions") or []]:
            for x in self._linked(k, items):
                if x.get("ref") not in seen:
                    seen.add(x.get("ref"))
                    out.append(x)
        return out

    def group_action(self, b):
        """Ticket einem Task zuordnen (head), eigenständig machen (head «») oder zur Erkennung zurück (reset)."""
        key = str(b.get("key") or "").strip().upper()
        if not groups.KEY_RE.match(key):
            raise UserError("Ticket-Key wie DLP-123 erwartet.")
        if b.get("reset"):
            self.store.group_set(key, None)
            self.audit("board.group", key, head="(automatisch)")
        else:
            head = str(b.get("head") or "").strip().upper()
            if head and (not groups.KEY_RE.match(head) or head == key):
                raise UserError("Wähle ein anderes Ticket als Task.")
            if head and self.store.groups().get(head):
                raise UserError("%s ist selbst einem Task zugeordnet. Wähle dessen Task." % head)
            self.store.group_set(key, head)
            self.audit("board.group", key, head=head or "(eigenständig)")
        self.cache_t = 0.0                  # beim nächsten Abruf neu gruppieren
        return {"ok": True}

    @staticmethod
    def _local_ticket(t):
        return {"key": t["key"], "summary": t["title"], "status": "", "type": "Aufgabe", "url": "", "sprint": "", "sprint_end": "",
                "in_sprint": None, "in_progress": False, "local": True}

    @staticmethod
    def _linked(key, items):
        """Alle MRs und Branches eines Tickets: ein Ticket kann beliebig viele haben."""
        return [{"project": it["project"], "branch": it["branch"], "iid": it["iid"], "url": it["url"], "kind": it["kind"],
                 "pipeline": it["pipeline"], "project_id": it["project_id"], "manual": bool(it.get("manual_link")),
                 "draft": bool(it.get("draft")), "ref": it.get("ref", ""), "author": it.get("author", ""),
                 "sonar": (it.get("sonar") or {}).get("status", ""), "sonar_detail": (it.get("sonar") or {}).get("detail", ""),
                 "sonar_url": (it.get("sonar") or {}).get("url", ""), "sonar_issues_url": (it.get("sonar") or {}).get("issues_url", ""),
                 "sonar_trend": (it.get("sonar") or {}).get("trend"),
                 "create_mr_url": it.get("create_mr_url", ""), "merge_status": it.get("merge_status", ""), "pipeline_url": it.get("pipeline_url", ""),
                 "ahead": it.get("ahead", 0), "age_days": it.get("age_days", 0), "title": it.get("title", ""), "by_agent": bool(it.get("by_agent")),
                 "reviewers": it.get("reviewers"), "upvotes": it.get("upvotes", 0), "approved": it.get("approved"), "approved_by": it.get("approved_by") or [],
                 "approvals_left": it.get("approvals_left"), "host": it.get("host", "gitlab"), "sha": it.get("sha", ""),
                 "approval_unknown": bool(it.get("approval_unknown")), "outdated": bool(it.get("outdated")),
                 "review_app": it.get("review_app", ""), "review_env": it.get("review_env", ""), "target_branch": it.get("target_branch", ""),
                 "ide": bool(it.get("ide")), "ide_wt": it.get("ide_wt")}
                for it in items if key in it.get("keys", [])]

    def _board(self, data):
        """Board und Jira-Panel aus einer Quelle: jede Aufgabe (Jira-Ticket, lokale Aufgabe, Idee, MR/Branch ohne Ticket) ist eine Karte;
        alles mit demselben Ticket-Key wird zusammengeführt. Läuft bei jeder Anfrage auf dem Zwischenspeicher, damit Verschieben sofort wirkt."""
        stages = self.store.stages()
        items = data["mine"] + data["review"] + data["assigned"]
        j = data.get("jira")
        known = dict(self._by_key)
        for t in self.store.tasks():
            known[t["key"]] = self._local_ticket(t)
        pools, pool_list = {}, []
        for p in self.store.pools():
            for i in p["items"]:
                pools.setdefault(i["value"], []).append({"id": p["id"], "name": p["name"]})
        jira_prog = {st["key"] for st in (j or {}).get("stories", [])}
        head_of = dict(getattr(self, "_head_of", {}) or {})
        comps_of = {}
        for st in (j or {}).get("stories", []):
            comps_of[st["key"]] = st.get("companions") or []
        mine_keys = {k for it in data["mine"] for k in it.get("keys", [])}
        # auch Keys, die Jira (noch) nicht kennt: sonst verschwände ein eigener MR mit Tippfehler im Key aus Board und Fokus
        keys = set(jira_prog) | set(known) | {k for k in stages if not links.is_ref_key(k)} | set(self.store.pool_tickets()) | mine_keys

        def derive(tk, linked):
            if tk and tk.get("in_progress"):
                return "review" if any(x["kind"] == "mr" and not x["draft"] for x in linked) else "impl"
            return "planned"
        cards = []
        for k in sorted(keys):
            tk = known.get(k)
            if k in head_of and head_of[k] in keys:
                continue   # Begleitticket: erscheint auf der Karte seines Tasks (0.30)
            if k not in stages and k not in pools and k not in jira_prog and k not in mine_keys and not (tk and tk.get("local")):
                continue   # Tickets nur, wenn sie in Arbeit, im Pool, auf dem Board oder mit eigenem MR/Branch verbunden sind
            linked = self._group_linked({"key": k, "companions": comps_of.get(k) or []}, items)
            st = stages.get(k)
            card = {"id": k, "key": k, "title": (tk or {}).get("summary", "") or next((x.get("title", "") for x in linked if x.get("title")), ""), "status": (tk or {}).get("status", ""), "url": (tk or {}).get("url", ""),
                    "local": bool(tk and tk.get("local")), "known": tk is not None, "type": (tk or {}).get("type", ""), "items": linked,
                    "stage": st["stage"] if st else derive(tk, linked), "manual_stage": bool(st), "updated": st["updated"] if st else 0,
                    "pools": pools.get(k, []), "jira_in_progress": k in jira_prog, "sprint": (tk or {}).get("sprint", ""),
                    "companions": [{"key": c["key"], "summary": c.get("summary", ""), "type": c.get("type", ""), "status": c.get("status", ""), "url": c.get("url", ""),
                                    "why": c.get("why", "")} for c in comps_of.get(k) or []]}
            cards.append(card)
        for it in data["mine"]:   # MRs/Branches ohne Ticket: eigene Karten, damit nichts fehlt
            if it["kind"] in ("mr", "branch") and not it.get("keys") and it.get("ref"):
                st = stages.get(it["ref"])
                linked = self._linked_ref(it)
                cards.append({"id": it["ref"], "key": "", "title": it["title"], "status": "", "url": it["url"], "local": False, "known": True, "type": "",
                              "items": [linked], "stage": st["stage"] if st else ("review" if it["kind"] == "mr" and not it.get("draft") else "impl"),
                              "manual_stage": bool(st), "updated": st["updated"] if st else 0, "pools": pools.get(it["ref"], []),
                              "jira_in_progress": False, "sprint": "", "orphan": True})
        if self.ideas is not None and self.has("ideas"):
            for i in self.ideas.list():
                if i["status"] in ("neu", "geparkt") and not i["expired"]:
                    cards.append({"id": "idea:%d" % i["id"], "key": "", "title": i["text"], "status": "", "url": "", "local": True, "known": True, "type": "Idee",
                                  "items": [], "stage": "idea", "manual_stage": True, "updated": 0, "pools": [], "jira_in_progress": False, "sprint": "",
                                  "idea_id": i["id"]})
        done = sorted((c for c in cards if c["stage"] == "done"), key=lambda c: -c["updated"])
        hide = {c["id"] for c in done[12:]}
        shown = [c for c in cards if c["id"] not in hide]
        for p in self.store.pools():
            pool_list.append({"id": p["id"], "name": p["name"], "count": sum(1 for c in cards if any(x["id"] == p["id"] for x in c["pools"]))})
        board = {"cards": shown, "done_hidden": len(hide), "stages": list(links.STAGES), "pools": pool_list}
        if j and j.get("ok") is not None and "stories" in j:
            j = dict(j)
            stories = [dict(st) for st in j["stories"]]
            have = {st["key"] for st in stories}
            for c in cards:
                if c["stage"] in links.PROGRESS and c["key"] and c["key"] not in have:
                    base = dict(known.get(c["key"]) or {"key": c["key"], "summary": "", "status": "", "type": "", "url": ""})
                    base.update(in_progress=True, via_board=True, items=c["items"], no_mr=not any(x["kind"] in ("mr", "assigned") for x in c["items"]))
                    stories.append(base)
            by_id = {c["id"]: c for c in cards}
            for st in stories:
                st["stage"] = (by_id.get(st["key"]) or {}).get("stage", "impl")
            if not j.get("partial"):
                for st in stories:
                    st.setdefault("counts", True)
                    st.setdefault("companions", [])
                j["stories"], j["count"] = stories, sum(1 for st in stories if st["counts"])
                j["over"] = j["count"] > int(j.get("limit", 2))
                prog_keys = {st["key"] for st in stories} | {c["key"] for st in stories for c in st["companions"]}
                for it in items:
                    tk = it.get("ticket")
                    it["agent_locked"] = bool(j["over"] and not (tk and tk["key"] in prog_keys))
                self.over_limit, self.inprogress_keys = j["over"], prog_keys
            data["jira"] = j
        return board

    @staticmethod
    def _linked_ref(it):
        return {"project": it["project"], "branch": it["branch"], "iid": it["iid"], "url": it["url"], "kind": it["kind"], "pipeline": it["pipeline"],
                "project_id": it["project_id"], "manual": False, "draft": bool(it.get("draft")), "ref": it.get("ref", ""), "author": it.get("author", ""),
                "sonar": (it.get("sonar") or {}).get("status", ""), "sonar_detail": (it.get("sonar") or {}).get("detail", ""), "sonar_url": (it.get("sonar") or {}).get("url", ""), "sonar_issues_url": (it.get("sonar") or {}).get("issues_url", ""),
                 "sonar_trend": (it.get("sonar") or {}).get("trend"),
                 "create_mr_url": it.get("create_mr_url", ""), "merge_status": it.get("merge_status", ""), "pipeline_url": it.get("pipeline_url", ""),
                 "ahead": it.get("ahead", 0), "age_days": it.get("age_days", 0), "title": it.get("title", ""), "by_agent": bool(it.get("by_agent")),
                 "reviewers": it.get("reviewers"), "upvotes": it.get("upvotes", 0), "approved": it.get("approved"), "approved_by": it.get("approved_by") or [],
                 "approvals_left": it.get("approvals_left"), "host": it.get("host", "gitlab"), "sha": it.get("sha", ""),
                 "approval_unknown": bool(it.get("approval_unknown")), "outdated": bool(it.get("outdated")),
                 "review_app": it.get("review_app", ""), "review_env": it.get("review_env", ""), "target_branch": it.get("target_branch", ""),
                 "ide": bool(it.get("ide")), "ide_wt": it.get("ide_wt")}

    def board_action(self, action, body):
        tgt = str(body.get("key") or body.get("ref") or ("idea:%s" % body["id"] if action == "plan_idea" and body.get("id") else "") or "")
        det = {k: body.get(k) for k in ("stage", "pool_id", "title") if body.get(k) not in (None, "")}
        return self._audited("board." + action, tgt, lambda: self._board_action(action, body),
                             target_of=lambda r: (r or {}).get("key") if isinstance(r, dict) else None, **det)

    def _board_action(self, action, body):
        st = self.store
        if action == "stage":
            key = body.get("key") or body.get("ref")
            if str(key or "").startswith("idea:"):
                raise UserError("Ideen werden mit «Planen» übernommen.")
            if key and not links.is_ref_key(key):
                key = self._local(links.norm_ticket, key)
                self._check_ticket_exists(key)
                if not links.is_local_key(key):
                    self._learn(key)
            key = self._local(st.stage_set, key, body.get("stage"))
            if body.get("stage") in ("tested", "done"):
                self._accept(key, body.get("note"), body.get("env"))
            if body.get("stage") == "done":
                self._ide_cleanup(key)
            return {"key": key}
        if action == "add":
            title = str(body.get("title") or "").strip()
            stage = body.get("stage") or "planned"
            if re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{1,19}-\d{1,9}", title):   # ein Jira-Key: Ticket aufs Board holen
                key = self._local(links.norm_ticket, title)
                self._check_ticket_exists(key)
                self._learn(key)
                return {"key": self._local(st.stage_set, key, stage)}
            self.cache_t = 0.0
            return {"key": self._local(st.task_add, title, stage, self._pool_id(body.get("pool_id")))}
        if action == "remove":
            key = str(body.get("key") or "")
            if links.is_local_key(key):
                self._local(st.task_delete, key)
            else:
                st.stage_clear(key)
            self.cache_t = 0.0
            return {}
        if action == "plan_idea":
            if not (self.ideas and self.has("ideas")):
                raise UserError("Die Ideenbox ist ausgeschaltet.")
            iid = int(body.get("id"))
            idea = next((i for i in self.ideas.list() if i["id"] == iid), None)
            if not idea:
                raise UserError("Idee nicht gefunden.")
            if not self._pool_id(body.get("pool_id")):
                raise UserError("Eine Idee braucht eine Kategorie (Pool), bevor sie geplant wird.")
            key = self._local(st.task_add, idea["text"].split("\n")[0][:200], body.get("stage") or "planned", self._pool_id(body.get("pool_id")))
            self.ideas.set_status(iid, "erledigt")
            self.cache_t = 0.0
            return {"key": key}
        if action in ("assign", "unassign"):
            key = body.get("key") or body.get("ref")
            pid = self._pool_id(body.get("pool_id"))
            if not pid:
                raise UserError("Kategorie fehlt.")
            kind = "ref" if links.is_ref_key(key) else "ticket"
            if kind == "ticket":
                key = self._local(links.norm_ticket, key)
                self._check_ticket_exists(key)
                if not links.is_local_key(key):
                    self._learn(key)
            if action == "assign":
                self._local(st.add_item, pid, kind, key)
            else:
                stage = (st.stages().get(key) or {}).get("stage", "")
                if kind == "ticket" and links.is_local_key(key) and stage not in ("", "idea") and len(st.pools_of(key)) <= 1:
                    if not body.get("to_pool"):
                        e = UserError("%s braucht eine Kategorie. Zurück in den Ideenpool legen?" % key)
                        e.data = {"to_pool": True}
                        raise e
                    self._local(st.stage_set, key, "idea")       # 0.35: zurück in den Ideenpool statt Sackgasse (aus dem Verlauf)
                st.remove_item(pid, kind, key)
            self.cache_t = 0.0
            return {}
        raise UserError("Unbekannte Aktion.")

    @staticmethod
    def _pool_id(v):
        try:
            return int(v) if v not in (None, "", 0, "0") else None
        except (TypeError, ValueError):
            raise UserError("Ungültige Kategorie.")

    def _learn(self, key):
        """Ein frisch aufs Board geholtes Jira-Ticket sofort bekannt machen, ohne auf den nächsten Abgleich zu warten."""
        if self.jira and key not in self._by_key:
            try:
                self._by_key.update({k: dict(v, in_progress=False) for k, v in self.jira.lookup([key]).items()})
            except UserError:
                pass
        self.cache_t = 0.0

    def _check_ticket_exists(self, key):
        if links.is_local_key(key):
            if key not in {t["key"] for t in self.store.tasks()}:
                raise UserError("Die Aufgabe %s gibt es nicht." % key)
            return
        if self.jira:
            try:
                if key not in self.jira.lookup([key]):
                    raise UserError("Das Ticket %s gibt es in Jira nicht (oder du darfst es nicht sehen)." % key)
            except HttpStatus as e:
                raise UserError("Jira konnte %s nicht prüfen: %s" % (key, e))

    def _ref(self, body):
        try:
            return int(body.get("project_id")), str(body.get("branch") or "")
        except (TypeError, ValueError):
            raise UserError("project_id muss eine Zahl sein.")

    def link_ticket(self, body):
        return self._audited("link.set", "%s:%s" % (body.get("project_id"), body.get("branch")), lambda: self._link_ticket(body), ticket=body.get("ticket"))

    def unlink_ticket(self, body):
        return self._audited("link.delete", "%s:%s" % (body.get("project_id"), body.get("branch")), lambda: self._unlink_ticket(body))

    def _link_ticket(self, body):
        pid, branch = self._ref(body)
        key = self._local(links.norm_ticket, body.get("ticket"))
        self._check_ticket_exists(key)
        self._local(self.store.link, pid, branch, key)
        log.info("Verknüpfung gesetzt: %s:%s → %s", pid, branch, key)
        self.cache_t = 0.0
        return {"ticket": key}

    def _unlink_ticket(self, body):
        pid, branch = self._ref(body)
        removed = self._local(self.store.unlink, pid, branch)
        log.info("Verknüpfung gelöst: %s:%s", pid, branch)
        self.cache_t = 0.0
        return {"removed": removed}

    def pool_action(self, action, body):
        det = {k: body.get(k) for k in ("id", "name") if body.get(k) not in (None, "")}
        return self._audited("pool." + action, "pool:%s" % (body.get("id") or body.get("name") or ""), lambda: self._pool_action(action, body),
                             target_of=lambda r: "pool:%s" % r["id"] if isinstance(r, dict) and r.get("id") else None, **det)

    def _pool_action(self, action, body):
        st = self.store
        if action == "create":
            return {"id": self._local(st.add_pool, body.get("name"))}
        if action == "rename":
            self._local(st.rename_pool, body.get("id"), body.get("name"))
            return {}
        if action == "delete":
            self._local(st.delete_pool, body.get("id"))
            return {}
        if action in ("add", "remove"):
            kind = body.get("kind")
            value = body.get("value")
            if kind == "ref":
                pid, branch = self._ref(body)
                value = links.ref_of(pid, branch)
            if action == "add":
                if kind == "ticket":
                    value = self._local(links.norm_ticket, value)
                    self._check_ticket_exists(value)
                value = self._local(st.add_item, body.get("id"), kind, value)
                if kind == "ticket":
                    self.cache_t = 0.0   # Jira-Daten des Tickets beim nächsten Abruf holen
                return {"value": value}
            return {"removed": self._local(st.remove_item, body.get("id"), kind, value)}
        raise UserError("Unbekannte Aktion.")

    def ai_action(self, action, body):
        st = self.store
        if action == "save":
            return {"id": self._local(st.ai_save, body.get("id"), body.get("name"), body.get("kind"), body.get("window_hours"),
                                      body.get("budget"), body.get("unit"))}
        if action == "delete":
            self._local(st.ai_delete, body.get("id"))
            return {}
        if action == "set":
            self._local(st.ai_set, body.get("id"), body.get("used"), body.get("resets_in_min"), body.get("delta"))
            return {}
        raise UserError("Unbekannte Aktion.")

    def pools_view(self, data):
        items = {it["ref"]: it for it in data["mine"] + data["review"] + data["assigned"] if it.get("ref")}
        out = []
        for p in self.store.pools():
            tickets, refs = [], []
            for i in p["items"]:
                if i["kind"] == "ticket":
                    t = self._by_key.get(i["value"])
                    tickets.append(dict(t, known=True) if t else {"key": i["value"], "summary": "", "status": "", "url": (self.jira.base + "/browse/" + i["value"]) if self.jira else "", "known": False})
                else:
                    it = items.get(i["value"])
                    if it:
                        refs.append({"ref": i["value"], "missing": False, "project_id": it["project_id"], "branch": it["branch"], "title": it["title"], "kind": it["kind"],
                                     "iid": it["iid"], "url": it["url"], "project": it["project"], "pipeline": it["pipeline"], "draft": it["draft"]})
                    else:
                        pid, _, br = i["value"].partition(":")
                        refs.append({"ref": i["value"], "missing": True, "project_id": int(pid), "branch": br, "title": br, "kind": "branch", "iid": None,
                                     "url": "", "project": self.proj_cfg.get(int(pid), {}).get("name", "Projekt %s" % pid), "pipeline": "none", "draft": False})
            out.append({"id": p["id"], "name": p["name"], "tickets": tickets, "refs": refs})
        return out

    # -- Tickets anlegen (Schreibzugriff: nur auf ausdrückliche Aktion, nur mit jira.allow_create)
    def ticket_meta(self):
        return {"can_create": bool(self.jira and self.jc.get("allow_create")), "jira": bool(self.jira),
                "llm": llm.ready(self.lc), "llm_label": llm.PROVIDERS[self.lc["provider"]].label if self.lc.get("provider") in llm.PROVIDERS else "",
                "projects": list(self.jc.get("project_keys") or []), "default_type": self.jc.get("create_type") or "Story"}

    def _types(self, project_key):
        if project_key not in self._types_cache:
            try:
                self._types_cache[project_key] = self.jira.issue_types(project_key) if self.jira else []
            except UserError as e:
                jlog.warning("Vorgangstypen für %s nicht lesbar: %s", project_key, e)
                return [self.jc.get("create_type") or "Story"]
        return self._types_cache[project_key] or [self.jc.get("create_type") or "Story"]

    def ticket_draft(self, body):
        if body.get("idea_id") not in (None, ""):
            return self._idea_draft(body)
        if body.get("hd_key"):
            return self._hd_draft(body)
        if not self.client:
            raise UserError("GitLab ist nicht verbunden.")
        try:
            pid = int(body.get("project_id"))
            iid = int(body["iid"]) if body.get("iid") not in (None, "") else None
        except (TypeError, ValueError):
            raise UserError("project_id und iid müssen Zahlen sein.")
        branch = str(body.get("branch") or "")[:250]
        meta = self.ticket_meta()
        project = str(body.get("project") or (meta["projects"][0] if meta["projects"] else "")).upper()
        ctx = self.client.ticket_context(pid, iid, branch)
        ctx["issue_types"] = self._types(project) if project else [meta["default_type"]]
        out = {"meta": meta, "project": project, "issue_types": ctx["issue_types"], "source": "vorlage", "warning": "",
               "draft": llm.template_draft(ctx)}
        if body.get("use_llm"):
            if not llm.ready(self.lc):
                raise UserError("Die KI ist nicht eingerichtet (Einstellungen → KI-Entwurf).")
            t0 = time.time()
            try:
                out["draft"] = llm.draft_ticket(self.lc, self.llm_key, ctx, str(body.get("hint") or ""))
                out["source"] = "ki"
                try:
                    if self.has("ai"):
                        self.store.ai_bump("local")   # Zähler der eigenen Anfragen an das lokale Modell
                except Exception as e:
                    log.debug("Zähler nicht aktualisiert: %s", e)
                log.info("KI-Entwurf von %s (%s) in %.1f s, %d Commit-Titel gesendet", self.lc["provider"], self.lc.get("model") or "-",
                         time.time() - t0, len(ctx["commits"]))
            except llm.LlmError as e:
                log.warning("KI-Entwurf fehlgeschlagen: %s", e)
                out["warning"] = "Die KI hat nicht geliefert (%s). Hier die Vorlage." % e
        if not out["draft"]["issue_type"] or out["draft"]["issue_type"] not in ctx["issue_types"]:
            dt = meta["default_type"]
            out["draft"]["issue_type"] = dt if dt in ctx["issue_types"] else ctx["issue_types"][0]
        return out

    def _hd_draft(self, body):
        """0.36: Jira-Ticket aus einem Helpdesk-Ticket (Wunsch). Das Helpdesk-Ticket bleibt unberührt; tinyops merkt sich nur die Verknüpfung."""
        key = str(body.get("hd_key") or "")
        hd = (self.cache or {}).get("helpdesk_jira") or {}
        t = helpdesk.find(hd, key)
        if t is None or self.hdj is None:
            raise UserError("Dieses Helpdesk-Ticket zeigt tinyops gerade nicht. Einmal neu laden.")
        try:
            d = self.hdj.detail(key) if hasattr(self.hdj, "detail") else helpdesk.detail(self.hdj, key)
        except (UserError, HttpStatus, ValueError) as e:
            raise UserError("Helpdesk-Ticket nicht lesbar: %s" % scrub(e))
        meta = self.ticket_meta()
        project = str(body.get("project") or (meta["projects"][0] if meta["projects"] else "")).upper()
        types = self._types(project) if project else [meta["default_type"]]
        b = briefing.make("helpdesk", key, d.get("title") or t.get("title") or "", description=d.get("description") or "")
        desc = ["Aus Helpdesk-Ticket [%s|%s]%s." % (key, d.get("url") or t.get("url") or "", " (%s)" % d.get("status") if d.get("status") else ""), "",
                "h3. Problem", "", b["description"][:3000] or "(keine Beschreibung im Helpdesk-Ticket)", "",
                "h3. Akzeptanzkriterien", ""] + (["* %s" % c for c in b["criteria"]] or ["* Das gemeldete Problem tritt nicht mehr auf", "* Helpdesk-Ticket %s kann beantwortet werden" % key])
        if b["masked"]:
            desc += ["", "_(%d Stellen, die nach Zugangsdaten aussahen, hat tinyops geschwärzt.)_" % b["masked"]]
        itype = next((x for x in ("Bug", "Fehler") if x in types), meta["default_type"] if meta["default_type"] in types else types[0])
        return {"meta": meta, "project": project, "issue_types": types, "source": "helpdesk", "hd_key": key, "linked": self.store.hd_jira_map().get(key, ""),
                "warning": "Der Text kommt aus dem Helpdesk. Vor dem Anlegen prüfen, ob Kundendaten darin stehen, die nicht ins Entwicklungs-Jira gehören.",
                "draft": {"summary": ("%s (%s)" % (d.get("title") or t.get("title") or key, key))[:255], "description": "\n".join(desc), "issue_type": itype}}

    def ticket_create(self, body):
        if not self.jira:
            raise UserError("Jira ist nicht verbunden.")
        if not self.jc.get("allow_create"):
            raise UserError("Das Anlegen von Tickets ist ausgeschaltet (Einstellungen → Jira → «Tickets aus dem Panel anlegen»).")
        keys = self.jc.get("project_keys") or []
        project = str(body.get("project") or "").strip().upper()
        if not project or (keys and project not in keys) or not settings.KEY_RE.match(project):
            raise UserError("Projekt-Key «%s» ist nicht erlaubt (erlaubt: %s)." % (project, ", ".join(keys) or "gültiger Key"))
        summary = " ".join(str(body.get("summary") or "").split())
        description = str(body.get("description") or "").strip()
        if not summary or len(summary) > 255:
            raise UserError("Der Titel fehlt oder ist länger als 255 Zeichen.")
        if len(description) > 30000:
            raise UserError("Die Beschreibung ist zu lang.")
        itype = str(body.get("issue_type") or "").strip()
        types = self._types(project)
        if itype not in types:
            raise UserError("Vorgangstyp «%s» gibt es in %s nicht (vorhanden: %s)." % (itype, project, ", ".join(types)))
        if not body.get("force"):
            for r in self.audit_log.rows(action="jira.create", since=time.time() - 600, limit=50):
                d = r["detail"]
                if r["ok"] and d.get("project") == project and (d.get("summary") or "").lower() == summary.lower():
                    err = UserError("Dasselbe Ticket hast du vor %d min schon angelegt: %s." % (max(1, int((time.time() - r["ts"]) // 60)), r["target"]))
                    err.data = {"duplicate": r["target"], "url": "%s/browse/%s" % (self.jc["url"].rstrip("/"), r["target"]) if self.jc.get("url") else ""}
                    raise err
        try:
            res = self.jira.create_issue(project, itype, summary, description)
        except UserError as e:
            self.audit("jira.create", project, ok=False, project=project, summary=summary, issue_type=itype, error=str(e)[:300])
            raise
        self.audit("jira.create", res["key"], project=project, summary=summary, issue_type=itype, description_chars=len(description), forced=bool(body.get("force")))
        jlog.info("Ticket %s angelegt (%s, %d Zeichen Beschreibung)", res["key"], itype, len(description))
        self.cache_t = 0.0   # beim nächsten Abruf neu lesen
        if body.get("idea_id") not in (None, ""):
            res["checks"] = self._idea_done(body, res["key"], summary, description)
        hk = str(body.get("hd_key") or "")
        if hk and helpdesk.KEY_RE.match(hk):
            self.store.hd_jira_set(hk, res["key"])
            self.audit("helpdesk.to_jira", hk, jira=res["key"])
        return res

    # -- Ideen (0.20): bewerten, als Ticket ausformulieren
    def _idea(self, iid):
        if not (self.ideas and self.has("ideas")):
            raise UserError("Die Ideenbox ist ausgeschaltet.")
        try:
            idea = self.ideas.get(int(iid))
        except (TypeError, ValueError):
            idea = None
        if not idea:
            raise UserError("Diese Idee gibt es nicht (mehr).")
        return idea

    def idea_assess(self, iid, b):
        """Bewertung an der Idee speichern: vom lokalen Modell oder von dir. Ähnliche Ideen und Vorhaben findet tinyops selbst (ohne Modell)."""
        idea = self._idea(iid)
        others = [i for i in self.ideas.list() if i["id"] != idea["id"] and i["status"] in ("neu", "geparkt") and not i["expired"]]
        tasks = [(cid, c.get("title") or "") for cid, c in (self._cards or {}).items() if not c.get("idea_id")]
        sim = similar(idea["text"], [("#%d" % o["id"], o["text"]) for o in others] + tasks)
        if b.get("manual"):
            a = {"category": b.get("category") if b.get("category") in llm.CATEGORIES else "",
                 "benefit": int(b.get("benefit")) if str(b.get("benefit")) in ("1", "2", "3") else 0,
                 "effort": b.get("effort") if b.get("effort") in llm.EFFORTS else "",
                 "effort_why": str(b.get("effort_why") or "")[:300], "duplicates": [],
                 "recommendation": b.get("recommendation") if b.get("recommendation") in llm.RECOMMEND else "", "why": str(b.get("why") or "")[:500]}
            if not a["recommendation"]:
                raise UserError("Empfehlung fehlt (jetzt, später oder verwerfen).")
            a["source"] = "du"
        else:
            if not llm.ready(self.lc):
                raise UserError("Die KI ist nicht eingerichtet (Einstellungen → KI-Entwurf). Du kannst die Idee auch selbst bewerten.")
            try:
                a = llm.assess_idea(self.lc, self.llm_key, idea, others, [t for _, t in tasks], self.ssl_ctx)
            except llm.LlmError as e:
                self.audit("idea.assess", "idea:%d" % idea["id"], ok=False, error=str(e)[:300])
                raise UserError("Bewertung fehlgeschlagen: %s" % e)
            a["source"] = "modell"
            a["model"] = self.lc.get("model") or self.lc.get("provider")
        a["similar"] = sim
        a["ts"] = time.time()
        self.ideas.set_field(idea["id"], assessment=a)
        self.audit("idea.assess", "idea:%d" % idea["id"], source=a["source"], recommendation=a["recommendation"], benefit=a["benefit"],
                   effort=a["effort"], category=a["category"], similar=[x["id"] for x in sim][:5])
        return a

    def _idea_draft(self, body):
        idea = self._idea(body.get("idea_id"))
        meta = self.ticket_meta()
        project = str(body.get("project") or (meta["projects"][0] if meta["projects"] else "")).upper()
        types = self._types(project) if project and self.jira else [meta["default_type"]]
        ctx = {"idea_id": idea["id"], "idea_text": idea["text"], "assessment": idea.get("assessment"), "issue_types": types}
        out = {"meta": meta, "project": project, "issue_types": types, "source": "vorlage", "warning": "", "draft": llm.template_from_idea(ctx),
               "idea": {"id": idea["id"], "text": idea["text"]}}
        if body.get("use_llm"):
            if not llm.ready(self.lc):
                raise UserError("Die KI ist nicht eingerichtet (Einstellungen → KI-Entwurf).")
            try:
                out["draft"] = llm.draft_from_idea(self.lc, self.llm_key, ctx, str(body.get("hint") or ""), self.ssl_ctx)
                out["source"] = "ki"
            except llm.LlmError as e:
                out["warning"] = "Die KI hat nicht geliefert (%s). Hier die Vorlage." % e
        if not out["draft"]["issue_type"] or out["draft"]["issue_type"] not in types:
            dt = meta["default_type"]
            out["draft"]["issue_type"] = dt if dt in types else types[0]
        out["acceptance"] = llm.acceptance_items(out["draft"]["description"])
        return out

    def _idea_done(self, body, key, summary, description):
        """Idee erledigt, Ticket an der Idee vermerken, auf Wunsch Akzeptanzkriterien als Teilschritte."""
        iid = int(body.get("idea_id"))
        self.ideas.set_field(iid, status="erledigt", ticket=key, draft={"summary": summary, "description": description[:30000]})
        n = 0
        if body.get("checklist", True):
            for t in llm.acceptance_items(description):
                try:
                    self.store.check_add(key, t)
                    n += 1
                except links.LinkError:
                    break
        self.audit("idea.ticket", "idea:%d" % iid, ticket=key, checks=n, kind="tiny" if links.is_local_key(key) else "jira")
        return n

    def idea_tiny(self, iid, b):
        """tiny-Ticket aus der Idee: lokale Aufgabe mit dem Titel des Entwurfs; Akzeptanzkriterien werden Teilschritte."""
        idea = self._idea(iid)
        summary = " ".join(str(b.get("summary") or idea["text"].splitlines()[0]).split())[:200]
        pool = self._pool_id(b.get("pool_id"))
        key = self.board_action("add", {"title": summary, "stage": "planned" if pool else "idea", "pool_id": pool})["key"]
        n = self._idea_done(dict(b, idea_id=idea["id"]), key, summary, str(b.get("description") or ""))
        self.cache_t = 0.0
        return {"key": key, "checks": n}

    JIRA_KEY = re.compile(r"^[A-Z][A-Z0-9_]{0,30}-\d{1,9}$")

    def ticket_brief(self, key, title=""):
        """Rohdaten für den Auftrag: lokale Aufgabe (Teilschritte), Helpdesk-Ticket oder Jira-Ticket. Zwei Minuten gemerkt, Fehler stehen im Ergebnis."""
        key = str(key or "").strip()
        hit = self._briefs.get(key)
        if hit and time.time() - hit[0] < 120:
            return hit[1]
        hd = (self.cache or {}).get("helpdesk_jira") or {}
        try:
            if key.startswith(links.LOCAL_PREFIX + "-"):
                steps = [c["text"] for c in (self.store.checklists().get(key) or []) if not c.get("done")]
                b = briefing.make("lokal", key, title, items=steps)
            elif self.hdj is not None and any(t["key"] == key for k in ("assigned", "queue", "watched") for t in hd.get(k) or []):
                d = self.hdj.detail(key) if hasattr(self.hdj, "detail") else helpdesk.detail(self.hdj, key)
                b = briefing.make("helpdesk", key, d.get("title") or title, d.get("type") or "", d.get("status") or "", d.get("description") or "",
                                  d.get("comments") or [], url=d.get("url") or "")
            elif self.jira is not None and self.JIRA_KEY.match(key):
                d = self.jira.brief(key)
                b = briefing.make("jira", key, d["title"] or title, d["kind"], d["status"], d["description"], d["comments"], url=d["url"])
            else:
                b = briefing.empty("", key, "" if not key else "Zu dieser Karte gibt es kein Ticket mit Beschreibung.")
        except (UserError, HttpStatus, KeyError, ValueError) as e:
            b = briefing.empty("jira", key, "Ticket nicht lesbar: %s" % scrub(e))
        if len(self._briefs) > 200:
            self._briefs.clear()
        self._briefs[key] = (time.time(), b)
        return b
