"""Fokus: Schritte, Abnahme, Teilschritte, Fokus-Sitzung und Arbeitsfläche.

Bereich von App (0.38 aus server.py gelöst). Gemeinsames (cfg, store, Audit, Cache) kommt von App;
Aufrufe in andere Bereiche stehen in USES und werden von tests/test_areas.py geprüft."""

import time
from datetime import datetime

import flow
import focusplan
import helpdesk
import links
import m365
import tlog
from common import UserError

log = tlog.get("app")


class FocusArea:
    # Aufrufe in andere Bereiche (tests/test_areas.py prüft, dass genau diese benutzt werden)
    USES = {"area_tickets": ("_ref", "board_action", "ticket_brief")}

    # -- Teilschritte (Checkliste je Karte)
    def flow_action(self, action, b):
        tgt = str(b.get("id") or b.get("key") or "")
        if action in ("add", "toggle", "delete"):
            return self._flow_action(action, b)          # Teilschritte: im Verlauf über den Spielstand, nicht im Audit
        if action == "tiny":
            return self._audited("flow.tiny", "", lambda: self._flow_action(action, b), target_of=lambda r: (r or {}).get("key"),
                                 branch="%s:%s" % (b.get("project_id"), b.get("branch")))
        return self._audited("flow." + action, tgt, lambda: self._flow_action(action, b),
                             **{k: b.get(k) for k in ("phase", "note", "env") if b.get(k) not in (None, "")})

    def _flow_action(self, action, b):
        st = self.store
        try:
            if action == "add":
                return {"id": st.check_add(str(b.get("key") or ""), b.get("text"))}
            if action == "toggle":
                r = st.check_toggle(int(b.get("id")), b.get("done"))
                if r["done"]:
                    st.flow_event_once("check:%d" % r["id"], r["key"], "", "check", -1, flow.XP_CHECK, r["text"])
                return {"done": bool(r["done"]), "stats": st.flow_stats(int((self.cfg.get("flow") or {}).get("daily_goal", 3)))}
            if action == "delete":
                st.check_delete(int(b.get("id")))
                return {"ok": True}
            if action == "complete":
                return self._flow_complete(b)
            if action == "tiny":
                return self._flow_tiny(b)
            if action == "accept":
                return self._flow_accept(b)
            if action == "pin":
                cid = b.get("id") or None
                if cid and str(cid).startswith("hd:"):
                    if not helpdesk.find((self.cache or {}).get("helpdesk_jira"), cid[3:]):
                        raise UserError("Dieses Helpdesk-Ticket kennt tinyops gerade nicht (weder zugewiesen noch in Queue oder Beobachtung).")
                elif cid and cid not in self._cards and not str(cid).startswith("rv:"):
                    raise UserError("Dieses Vorhaben gibt es (gerade) nicht.")
                self.store.pin_set(cid)
                if self.tc["enabled"]:
                    if cid and str(cid).startswith("hd:"):
                        key = cid[3:]
                        t = helpdesk.find((self.cache or {}).get("helpdesk_jira"), key) or {}
                        self.timebook.start(key, t.get("title") or key, idle=self.tc["idle_minutes"], area=self.hdc.get("area") or "hd")
                    elif cid and not str(cid).startswith("rv:"):
                        self.timebook.start(cid, (self._cards.get(cid) or {}).get("title") or "", idle=self.tc["idle_minutes"], area=self._area_of(cid))
                    else:
                        self.timebook.stop(idle=self.tc["idle_minutes"])
                return {"pinned": cid}
        except (TypeError, ValueError):
            raise UserError("Teilschritt-Nummer fehlt.")
        except links.LinkError as e:
            raise UserError(str(e))
        raise UserError("Unbekannte Aktion.")

    def _accept(self, cid, note="", env=""):
        """Abnahme an die aktuellen Head-Commits aller offenen MRs/PRs der Karte binden."""
        card = self._cards.get(cid) or {}
        refs = []
        for x in card.get("items") or []:
            if x.get("kind") in ("mr", "assigned") and x.get("iid"):
                ref = x.get("ref") or links.ref_of(x["project_id"], x["branch"])
                w = self.store.ide_get(ref)
                refs.append((ref, w["sha"] if w else x.get("sha") or ""))    # getestet wurde, was im IntelliJ-Worktree lag
        if refs:
            self.store.accept_set(cid, refs, note, env)
            self.audit_note(accepted=["%s@%s" % (r, (sh or "?")[:12]) for r, sh in refs])
            log.info("Abnahme %s: %s", cid, ", ".join("%s@%s" % (r, (sh or "?")[:8]) for r, sh in refs))
        return refs

    def _flow_accept(self, b):
        cid = str(b.get("id") or "")
        if not cid or cid.startswith("idea:") or links.is_ref_key(cid):
            raise UserError("Abnehmen geht nur für Vorhaben mit Ticket.")
        self.board_action("stage", {"key": cid, "stage": "tested", "note": b.get("note"), "env": b.get("env")})   # bindet die Abnahme
        card = self._cards.get(cid) or {}
        return {"stage": "tested", "commits": [{"ref": x.get("ref", ""), "sha": (x.get("sha") or "")[:8]} for x in card.get("items") or [] if x.get("iid")]}

    def _flow_complete(self, b):
        """«Schritt erledigt»: setzt die nächste Station von Hand. Branches und MRs ohne Ticket dürfen das nicht."""
        cid = str(b.get("id") or "")
        if not cid or cid.startswith("idea:"):
            raise UserError("Ideen werden mit «Einplanen» übernommen.")
        if links.is_ref_key(cid):
            raise UserError("Ein Branch braucht zuerst ein Jira- oder tiny-Ticket. Erst «Ticket zuordnen», dann geht es weiter.")
        try:
            phase = int(b.get("phase"))
        except (TypeError, ValueError):
            raise UserError("Station fehlt.")
        stage = flow.next_stage(phase)
        if stage is None:
            raise UserError("Schon fertig.")
        self.board_action("stage", {"key": cid, "stage": stage})
        self.audit_note(stage=stage)
        return {"stage": stage}

    def _flow_tiny(self, b):
        """Ein tiny-Ticket für einen Branch oder MR ohne Ticket: Aufgabe in «Umsetzung», Kategorie = Projekt, Branch verknüpft."""
        pid, branch = self._ref(b)
        title = " ".join(str(b.get("title") or branch).split())[:200]
        pname = (str(b.get("project") or "") or (self.proj_cfg.get(pid) or {}).get("name") or "Projekt %s" % pid)[:60]
        pool = next((p for p in self.store.pools() if p["name"].lower() == pname.lower()), None)
        pool_id = pool["id"] if pool else self._local(self.store.add_pool, pname)
        key = self._local(self.store.task_add, title, "impl", pool_id)
        self._local(self.store.link, pid, branch, key)
        log.info("tiny-Ticket %s für %s:%s angelegt (Kategorie %s)", key, pid, branch, pname)
        self.cache_t = 0.0
        return {"key": key, "pool": pname}

    def focus_brief(self, key, title=""):
        """Worum es geht und wann es fertig ist: aus dem Ticket (Jira, lokal), für die Arbeitsfläche im Fokus."""
        key = str(key or "").strip()[:80]
        if not key:
            return {"goal": "", "criteria": [], "error": "", "source": ""}
        b = self.ticket_brief(key, title)
        desc = b.get("description") or ""
        goal = " ".join(desc.split())
        if len(goal) > 420:                       # die ersten Sätze reichen für «Worum es geht»; der Rest steht im Ticket
            cut = goal[:420]
            goal = cut[:max(cut.rfind(". "), 200) + 1] + " …"
        return {"goal": goal, "criteria": b.get("criteria") or [], "error": b.get("error") or "", "source": b.get("source") or "",
                "comments": len(b.get("comments") or []), "url": b.get("url") or ""}

    # -- Fokusbereiche und Fokus-Sitzung (0.23)
    def _area_of(self, cid):
        if str(cid).startswith("hd:"):
            return self.hdc.get("area") or "hd"
        return focusplan.area_of_card(self.fc, self._cards.get(cid))

    def focus_state(self, now=None):
        now = now or time.time()
        if not self.tc["enabled"]:
            return None
        ws = focusplan.week_start(now).timestamp()
        segs = self.timebook.range_segments(ws, now + 1, now, self.tc["idle_minutes"])
        rep = focusplan.week_report(self.fc, segs, now)
        self._focus_expire(now)
        ses = self.timebook.session()
        if ses:
            ses["grace_secs"] = self.FOCUS_GRACE
            ses["left_secs"] = int(ses["start"] + ses["planned_min"] * 60 - now)
            a = focusplan.area(self.fc, ses["area"])
            ses["area_name"] = a["name"] if a else ses["area"]
        today_a = datetime.fromtimestamp(now).replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
        done = [x for x in self.timebook.sessions(today_a, now + 1) if x["end"]]
        return {"week": rep, "session": ses, "block": focusplan.current_block(self.fc, now), "next_block": focusplan.next_block(self.fc, now),
                "areas": [{"id": a["id"], "name": a["name"], "activities": a.get("activities") or [], "ticket": a.get("ticket") or "",
                           "target_pct": a.get("target_pct", 0)} for a in self.fc["areas"]],
                "today": {"sessions": len(done), "minutes": int(sum((x["end"] - x["start"]) for x in done) // 60)},
                "last_ended": ({"id": done[-1]["id"], "result": done[-1]["result"], "title": done[-1]["title"],
                                "minutes": int((done[-1]["end"] - done[-1]["start"]) // 60)} if done else None)}

    FOCUS_GRACE = 600      # so lange darf eine Zeitbox überzogen sein, bevor die Sitzung von selbst endet

    def _focus_block(self, title, activity, start, minutes):
        if self.demo:
            return {"ok": True, "demo": True}
        try:
            ev = self.m365.block("Fokus: %s" % title, start, start + minutes * 60, "Eingetragen von tinyops (Fokus-Sitzung%s)." % (", " + activity if activity else ""))
            self.audit("m365.event", title, minutes=minutes)
            self.m365_t = 0.0
            return {"ok": True, "url": ev.get("url", "")}
        except m365.GraphError as e:
            self.audit("m365.event", title, ok=False, error=str(e)[:200])
            return {"ok": False, "error": str(e)}

    def _focus_finish(self, ses, result, end, now, note=""):
        """Eine Sitzung abschliessen: Ende, Ergebnis, XP ab 20 Minuten. Gibt die Zusammenfassung zurück."""
        end = max(ses["start"], min(end, now))
        mins = int((end - ses["start"]) // 60)
        self.timebook.session_update(ses["id"], end=end, result=result, note=(ses["note"] + "\n" + str(note or "")[:500]).strip()[-2000:])
        xp = 0
        if mins >= 20 and result in ("erledigt", "weiter", "abgelaufen"):
            xp = 15
            self.store.flow_event_once("focus:%d" % ses["id"], ses["key"], ses["title"], "focus", 0, xp,
                                       "Fokus %d min%s" % (mins, (" · " + ses["activity"]) if ses["activity"] else ""), now)
        self.audit("focus.end", ses["key"], area=ses["area"], minutes=mins, planned=ses["planned_min"], result=result, parked=ses["parked"])
        return {"minutes": mins, "result": result, "xp": xp, "parked": ses["parked"], "title": ses["title"]}

    def _focus_expire(self, now):
        """Eine Sitzung läuft nur, solange du dran bist. Sie endet von selbst, wenn die Zeit auf eine andere Aufgabe wechselt, das Panel länger als
        idle_minutes nicht mehr abgefragt hat (Browser zu, Rechner im Ruhezustand), oder die Zeitbox mehr als zehn Minuten überzogen ist.
        Solange sie läuft, gilt sie als Lebenszeichen: Die Zeit zählt auch, wenn du im Editor arbeitest und das Panel nicht anfasst."""
        ses = self.timebook.session()
        if not ses:
            return None
        cur, idle = self.timebook.current(), self.tc["idle_minutes"]
        if not cur:
            return self._focus_finish(ses, "pausiert", now, now)
        if cur["key"] != ses["key"]:
            return self._focus_finish(ses, "abgelöst", cur["start"], now)
        if now - cur["last_seen"] > idle * 60:
            return self._focus_finish(ses, "pausiert", cur["last_seen"], now)
        over = ses["start"] + ses["planned_min"] * 60
        if now > over + self.FOCUS_GRACE:
            return self._focus_finish(ses, "abgelaufen", over, now)      # die Zeit auf der Aufgabe läuft weiter, nur die Zeitbox ist zu
        self.timebook.ping(now, idle)
        return None

    def focus_action(self, action, b, now=None):
        now = now or time.time()
        if not self.tc["enabled"]:
            raise UserError("Die Zeiterfassung ist ausgeschaltet (Einstellungen → Zeiterfassung).")
        tb, idle = self.timebook, self.tc["idle_minutes"]
        self._focus_expire(now)
        ses = tb.session()
        if action == "start":
            try:
                minutes = int(b.get("minutes") or 50)
            except (TypeError, ValueError):
                minutes = 0
            if not 5 <= minutes <= 240:
                raise UserError("Dauer zwischen 5 und 240 Minuten.")
            activity = " ".join(str(b.get("activity") or "").split())[:80]
            cid = str(b.get("key") or "")
            if cid:
                if cid.startswith("hd:"):
                    key = cid[3:]
                    t = helpdesk.find((self.cache or {}).get("helpdesk_jira"), key)
                    if not t:
                        raise UserError("Dieses Helpdesk-Ticket kennt tinyops gerade nicht.")
                    title, aid = t["title"], self.hdc.get("area") or "hd"
                else:
                    c = self._cards.get(cid)
                    if not c:
                        raise UserError("Dieses Vorhaben gibt es nicht (mehr).")
                    key, title, aid = cid, c.get("title") or cid, b.get("area") or self._area_of(cid)
                self.store.pin_set(cid)
            else:
                a = focusplan.area(self.fc, b.get("area"))
                if not a:
                    raise UserError("Unbekannter Fokusbereich.")
                key, title, aid = focusplan.booking_key(a), a["name"], a["id"]
            tb.start(key, title, now=now, idle=idle, area=aid, activity=activity)
            sid = tb.session_start(key, title, aid, activity, minutes, now)
            self.audit("focus.start", key, area=aid, activity=activity, minutes=minutes, session=sid)
            st = self.focus_state(now)
            if b.get("calendar"):              # auf deinen Haken: im eigenen Kalender als beschäftigt eintragen (0.28)
                st["calendar"] = self._focus_block(title, activity, now, minutes)
            return st
        if not ses:
            raise UserError("Es läuft keine Fokus-Sitzung.")
        if action == "park":
            text = " ".join(str(b.get("text") or "").split())[:500]
            if not text:
                raise UserError("Der Gedanke fehlt.")
            if self.ideas and self.has("ideas"):
                self.ideas.add(text)
            tb.session_update(ses["id"], parked=ses["parked"] + 1, note=(ses["note"] + "\n" + text)[-2000:] if not self.ideas else ses["note"])
            return {"parked": ses["parked"] + 1, "to": "ideen" if self.ideas else "notiz"}
        if action == "activity":
            activity = " ".join(str(b.get("activity") or "").split())[:80]
            tb.start(ses["key"], ses["title"], now=now, idle=idle, area=ses["area"], activity=activity)
            tb.session_update(ses["id"], activity=activity)
            return self.focus_state(now)
        if action == "extend":
            try:
                add = int(b["minutes"]) if b.get("minutes") not in (None, "") else 15
            except (TypeError, ValueError):
                add = 0
            if not 5 <= add <= 60:
                raise UserError("Verlängern um 5 bis 60 Minuten.")
            passed = int((now - ses["start"]) // 60)
            new = max(ses["planned_min"], passed) + add          # ab jetzt gerechnet, wenn die Zeitbox schon vorbei ist
            if new > 480:
                raise UserError("Eine Sitzung dauert höchstens 8 Stunden. Schliess sie ab und starte eine neue.")
            tb.session_update(ses["id"], planned_min=new)
            tb.ping(now, idle)
            return self.focus_state(now)
        if action == "end":
            result = b.get("result") if b.get("result") in ("erledigt", "weiter", "abgelenkt", "abgebrochen") else "abgebrochen"
            ended = self._focus_finish(ses, result, now, now, b.get("note"))
            if result != "weiter":
                tb.stop(now, idle)
            return dict(self.focus_state(now), ended=ended)
        raise UserError("Unbekannte Aktion.")
