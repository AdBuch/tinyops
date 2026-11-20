"""Zeit und BCS: Fokus-Zeit, Entwürfe, Lücken, Buchen über die BCS-Middleware.

Bereich von App (0.38 aus server.py gelöst). Gemeinsames (cfg, store, Audit, Cache) kommt von App;
Aufrufe in andere Bereiche stehen in USES und werden von tests/test_areas.py geprüft."""

import hashlib
import json
import time

import bcs
import flow
import links
import llm
import timesheet
from common import UserError


class TimeArea:
    # Aufrufe in andere Bereiche (tests/test_areas.py prüft, dass genau diese benutzt werden)
    USES = {}

    # -- Fokus-Zeit und Zeitentwürfe (0.19)
    def time_state(self, now=None):
        now = now or time.time()
        if not self.tc["enabled"]:
            return {"enabled": False}
        tb, idle = self.timebook, self.tc["idle_minutes"]
        cur = tb.current()
        d = timesheet.today(now)
        tot = tb.totals(d, now, idle)
        run = None
        if cur:
            idle_now = now - cur["last_seen"] > idle * 60
            run = {"key": cur["key"], "title": cur["title"], "since": cur["start"], "idle": idle_now,
                   "today_secs": (tot.get(cur["key"]) or {}).get("secs", 0), "area": cur.get("area") or "dev", "activity": cur.get("activity") or ""}
        return {"enabled": True, "running": run, "today_secs": sum(x["secs"] for x in tot.values()), "gaps": len(tb.gaps(d)),
                "open_drafts": len([x for x in tb.drafts(state="offen") if x["date"] < d]), "date": d}

    def _time_meta(self):
        meta = {}
        for cid, c in (self._cards or {}).items():
            hint = ", ".join(p["name"] for p in c.get("pools") or []) or next((x.get("project") for x in c.get("items") or [] if x.get("project")), "")
            meta[cid] = {"title": c.get("title") or cid, "project_hint": hint}
        for t in ((self.cache or {}).get("helpdesk_jira") or {}).get("assigned") or []:
            meta.setdefault(t["key"], {"title": t["title"], "project_hint": self.hdc.get("name") or "Helpdesk"})
        return meta

    def time_day(self, d=None, now=None):
        """Abschnitte, Lücken und Entwürfe eines Tages. Führt die automatischen Entwürfe nach."""
        now = now or time.time()
        if not self.tc["enabled"]:
            raise UserError("Die Zeiterfassung ist ausgeschaltet (Einstellungen → Zeiterfassung).")
        d = d or timesheet.today(now)
        try:
            timesheet.day_bounds(d)
        except ValueError:
            raise UserError("Datum im Format JJJJ-MM-TT.")
        tb, idle = self.timebook, self.tc["idle_minutes"]
        a, b = timesheet.day_bounds(d)
        labels = dict(flow.PHASES)
        names = [p for p, _ in flow.PHASES]
        events = []
        for e in self.store.flow_events_between(a, b):
            if e["kind"] == "phase" and 0 <= e["phase"] < len(names):
                events.append({"key": e["key"], "text": "Station %s" % labels[names[e["phase"]]], "ts": e["ts"], "kind": "phase"})
            elif e["kind"] in ("check", "agent") and e["text"]:
                events.append({"key": e["key"], "text": e["text"], "ts": e["ts"], "kind": e["kind"]})
        accs = []
        for key, refs in self.store.acceptances().items():
            for ref, r in refs.items():
                if a <= (r.get("ts") or 0) < b:
                    accs.append({"key": key, "ref": ref, "label": ref, "sha": r.get("sha"), "ts": r["ts"]})
        tot = tb.totals(d, now, idle)
        meta = self._time_meta()
        tb.sync_auto(d, timesheet.compose(d, tot, meta, events, accs, self.tc["round_minutes"], self.tc["min_minutes"]), now)
        drafts = tb.drafts(d)
        tmap = tb.bcs_targets() if self.bcs is not None else {}
        for x in drafts:
            x["ticket_ok"] = not links.is_ref_key(x["ticket"])
            if self.bcs is not None:
                x["bcs_task"] = self._bcs_task(x["ticket"], tmap)
        return {"date": d, "segments": tb.segments(d, now, idle), "gaps": tb.gaps(d), "drafts": drafts,
                "total_secs": sum(x["secs"] for x in tot.values()), "booked_minutes": sum(x["minutes"] for x in drafts if x["state"] == "gebucht"),
                "draft_minutes": sum(x["minutes"] for x in drafts if x["state"] not in ("verworfen",)),
                "round": self.tc["round_minutes"],
                "bcs": {"on": self.bcs is not None, "error": self.bcs_error, "demo": self.demo} if (self.bcs is not None or self.bcs_error) else None,
                "llm": llm.ready(self.lc),
                "earlier_open": sorted({x["date"] for x in tb.drafts(state="offen") if x["date"] < d})[-7:]}

    def _draft(self, did):
        dr = self.timebook.draft(str(did or ""))
        if not dr:
            raise UserError("Diesen Entwurf gibt es nicht.")
        return dr

    def time_action(self, action, b):
        if not self.tc["enabled"]:
            raise UserError("Die Zeiterfassung ist ausgeschaltet.")
        tb, idle = self.timebook, self.tc["idle_minutes"]
        if action == "ping":
            tb.ping(idle=idle)
            return self.time_state()
        if action == "pause":
            tb.stop(idle=idle)
            self.audit("time.pause", (self.store.pin_get() or ""))
            return self.time_state()
        if action == "resume":
            pin = self.store.pin_get()
            if not pin or str(pin).startswith("rv:"):
                raise UserError("Erst ein Vorhaben als Fokus anheften.")
            tb.start(pin, (self._cards.get(pin) or {}).get("title") or "", idle=idle)
            return self.time_state()
        if action == "gap":
            g = tb.gap_set(int(b.get("id")), bool(b.get("count")))
            if not g:
                raise UserError("Diese Lücke ist schon erledigt.")
            self.audit("time.gap", g["key"], counted=bool(b.get("count")), minutes=int((g["end"] - g["start"]) // 60))
            return {"ok": True}
        if action == "texts":                    # Buchungstexte vom lokalen Modell vorschlagen: nur Vorschläge, du übernimmst sie
            return self.time_texts(str(b.get("date") or timesheet.today()))
        if action == "add":
            d = str(b.get("date") or timesheet.today())
            ticket = " ".join(str(b.get("ticket") or "").split()).upper() if not links.is_ref_key(str(b.get("ticket") or "")) else str(b.get("ticket"))
            minutes = self._minutes(b.get("minutes"))
            if not ticket or len(ticket) > 120:
                raise UserError("Ticket fehlt.")
            did = tb.add_manual(d, ticket, minutes, str(b.get("text") or "")[:300], title=(self._cards.get(ticket) or {}).get("title", ""),
                                project_hint=(self._time_meta().get(ticket) or {}).get("project_hint", ""))
            self.audit("time.add", ticket, date=d, minutes=minutes)
            return {"id": did}
        dr = self._draft(b.get("id"))
        if dr["state"] == "unklar":
            raise UserError("Unklar, ob dieser Entwurf in BCS gebucht ist. Erst «Mit BCS abgleichen».")
        if dr["state"] in timesheet.LOCKED and action not in ("send",):
            raise UserError("Schon gebucht (%s). Ändern nur noch in BCS." % (dr["reference"] or "ohne Referenz"))
        if action == "edit":
            if dr["state"] not in ("offen", "abgelehnt", "fehlgeschlagen", "bestätigt"):
                raise UserError("Verworfene Entwürfe erst wiederherstellen.")
            kw = {"edited": 1}
            if "minutes" in b:
                kw["minutes"] = self._minutes(b.get("minutes"))
            if "text" in b:
                kw["text"] = str(b.get("text") or "")[:300]
            if "ticket" in b:
                t = str(b.get("ticket") or "").strip()
                if not t:
                    raise UserError("Ticket fehlt.")
                kw["ticket"] = t[:120]
            if dr["state"] != "offen":
                kw["state"] = "offen"            # nach dem Ändern erneut bestätigen
            tb.update(dr["id"], **kw)
            self.audit("time.edit", dr["ticket"], draft=dr["id"], **{k: v for k, v in kw.items() if k in ("minutes", "ticket")})
            return {"ok": True}
        if action == "discard":
            tb.update(dr["id"], state="verworfen")
            self.audit("time.discard", dr["ticket"], draft=dr["id"], minutes=dr["minutes"])
            return {"ok": True}
        if action == "restore":
            tb.update(dr["id"], state="offen", merged_into="")
            return {"ok": True}
        if action == "merge":
            into = self._draft(b.get("into"))
            if into["id"] == dr["id"] or into["date"] != dr["date"] or into["state"] not in ("offen",) or dr["state"] != "offen":
                raise UserError("Zusammenlegen geht nur mit einem anderen offenen Entwurf desselben Tages.")
            ev = into["evidence"] + [e for e in dr["evidence"] if e not in into["evidence"]]
            tb.update(into["id"], minutes=into["minutes"] + dr["minutes"], text=(into["text"] + "; " + dr["text"])[:300], evidence=ev, edited=1)
            tb.update(dr["id"], state="verworfen", merged_into=into["id"])
            self.audit("time.merge", into["ticket"], draft=into["id"], merged=dr["id"], minutes=into["minutes"] + dr["minutes"])
            return {"ok": True}
        if action == "confirm":
            if dr["state"] != "offen":
                raise UserError("Nur offene Entwürfe lassen sich bestätigen (Status: %s)." % dr["state"])
            if links.is_ref_key(dr["ticket"]):
                raise UserError("Dieser Entwurf hängt an einem Branch ohne Ticket. Erst ein Ticket eintragen.")
            if dr["minutes"] <= 0:
                raise UserError("0 Minuten bucht man nicht. Verwerfen oder Zeit eintragen.")
            tb.update(dr["id"], state="bestätigt", message="")
            self.audit("time.confirm", dr["ticket"], draft=dr["id"], minutes=dr["minutes"], date=dr["date"])
            return {"state": "bestätigt"}
        raise UserError("Unbekannte Aktion.")

    def _minutes(self, v):
        try:
            m = int(v)
        except (TypeError, ValueError):
            raise UserError("Minuten müssen eine ganze Zahl sein.")
        if not 0 <= m <= 24 * 60:
            raise UserError("Minuten zwischen 0 und 1440.")
        return m

    def _bcs_client(self):
        if self.bcs is None:
            raise UserError(self.bcs_error or "BCS ist nicht eingerichtet (Einstellungen → Zeiterfassung → BCS).")
        return self.bcs

    @staticmethod
    def _bcs_task(ticket, tmap):
        """BCS-Aufgabe für ein Ticket: zuerst genau dieses Ticket (oder dieser Bereich), dann das Projekt («DLP-*»)."""
        for pat in (ticket, bcs.prefix_of(ticket)):
            if pat and pat in tmap:
                t = tmap[pat]
                return {"pattern": pat, "task_id": t["task_id"], "name": t["name"], "path": t["path"]}
        return None

    def _bcs_call(self, fn, *a):
        try:
            return fn(*a)
        except bcs.BcsError as e:
            raise UserError(str(e))

    def bcs_day(self, d):
        c = self._bcs_client()
        hit = getattr(self, "_bcs_day_cache", {}).get(d)
        if hit and time.time() - hit[0] < 30:           # 0.36: jedes Neuladen der Zeit-Ansicht fragte BCS neu
            return hit[1]
        day = self._bcs_call(c.day, d)
        out = {"day": bcs.day_summary(day)}
        try:
            out["week"] = c.overview(d, "week")
        except bcs.BcsError as e:
            out["week_error"] = str(e)
        self._bcs_day_cache = {d: (time.time(), out)}
        return out

    def _bcs_included(self, d):
        """Welche Entwürfe eines Tages in die Vorschau gehen: bestätigt, mit Ticket, mit BCS-Aufgabe."""
        tb = self.timebook
        tmap = tb.bcs_targets()
        inc, skip = [], []
        for x in tb.drafts(d):
            if x["state"] not in ("bestätigt", "fehlgeschlagen") or x["minutes"] <= 0:
                continue
            task = self._bcs_task(x["ticket"], tmap)
            if not task:
                skip.append({"id": x["id"], "ticket": x["ticket"], "why": "keine BCS-Aufgabe zugeordnet"})
                continue
            inc.append((x, bcs.change_for(x, task["task_id"])))
        return inc, skip

    @staticmethod
    def _bcs_sig(inc):
        return hashlib.sha256(json.dumps([[x["id"], c] for x, c in inc], sort_keys=True, ensure_ascii=False).encode()).hexdigest()

    def bcs_action(self, action, b, now=None):
        now = now or time.time()
        c = self._bcs_client()
        if action in ("commit", "reconcile"):
            self._bcs_day_cache = {}            # danach soll die Zeit-Ansicht die neuen Buchungen sehen
        d = str(b.get("date") or timesheet.today(now))
        if action == "targets":
            return {"items": self._bcs_call(c.targets, d, b.get("query"))}
        if action == "suggestions":
            return self._bcs_call(c.suggestions, d)
        if action == "map":                        # Ticket oder ganzes Projekt einer BCS-Aufgabe zuordnen (nur lokal gespeichert)
            ticket = str(b.get("ticket") or "").strip()
            pat = bcs.prefix_of(ticket) if b.get("scope") == "project" else ticket
            if not pat or len(pat) > 120:
                raise UserError("Für «ganzes Projekt» braucht es einen Jira-Key wie DLP-123." if b.get("scope") == "project" else "Ticket fehlt.")
            tid = str(b.get("task_id") or "").strip()[:bcs.TASK_ID_MAX]
            path = " › ".join(str(x) for x in b.get("path") or [])[:400] if isinstance(b.get("path"), list) else str(b.get("path") or "")[:400]
            self.timebook.bcs_target_set(pat, tid, str(b.get("name") or "")[:200], path, now)
            self.audit("bcs.map", pat, task=tid, name=str(b.get("name") or "")[:80])
            return {"pattern": pat}
        if action == "preview":
            inc, skip = self._bcs_included(d)
            if not inc:
                raise UserError("Nichts zu prüfen: bestätige Entwürfe und ordne ihnen eine BCS-Aufgabe zu." + (" Ohne Aufgabe: %s." % ", ".join(s_["ticket"] for s_ in skip) if skip else ""))
            r = self._bcs_call(c.preview, d, [ch for _, ch in inc])
            st = r.get("status")
            out = {"status": st, "message": r.get("message", ""), "warnings": r.get("warnings") or [], "entries": r.get("entries") or [], "deletions": r.get("deletions") or [],
                   "dry_run": bool(r.get("dryRun")), "expires": r.get("expiresAt", ""), "draft_id": None, "skipped": skip,
                   "included": [{"id": x["id"], "ticket": x["ticket"], "minutes": ch["durationMinutes"], "description": ch["description"]} for x, ch in inc]}
            if st == "ready" and r.get("draftId"):
                with self._bcs_lock:
                    self._bcs_prev = {k: v for k, v in self._bcs_prev.items() if now - v["ts"] < 900}
                    self._bcs_prev[r["draftId"]] = {"date": d, "ids": [x["id"] for x, _ in inc], "sig": self._bcs_sig(inc), "ts": now}
                out["draft_id"] = r["draftId"]
            self.audit("bcs.preview", d, ok=st == "ready", status=st, drafts=len(inc), minutes=sum(ch["durationMinutes"] for _, ch in inc), warnings=len(out["warnings"]))
            return out
        if action == "commit":
            return self._bcs_commit(c, d, str(b.get("draft_id") or ""), now)
        if action == "reconcile":
            return self._bcs_reconcile(c, d, now)
        if action == "apprentices":
            if not self.bcsc.get("apprentices", True) and not self.demo:
                raise UserError("Lernende sind in den Einstellungen ausgeblendet.")
            lst = self._bcs_call(c.apprentices)
            rows = []
            for m in (lst.get("members") or [])[:20]:
                try:
                    db = c.dashboard(m.get("id", ""))
                    wk = (db.get("currentWeek") or {}).get("days") or []
                    rows.append({"id": m.get("id"), "name": m.get("name"), "status": db.get("status"), "ytd": (db.get("ytd") or {}).get("balanceMinutes"),
                                 "week": sum((x.get("balanceMinutes") or 0) for x in wk) if wk else None, "vacation_left": (db.get("vacation") or {}).get("remainingDays"),
                                 "as_of": db.get("asOf")})
                except bcs.BcsError as e:
                    rows.append({"id": m.get("id"), "name": m.get("name"), "error": str(e)})
            return {"configured": lst.get("configured", False), "members": rows}
        if action == "balance":
            return self._bcs_call(c.time_balance)
        raise UserError("Unbekannte Aktion.")

    def _bcs_commit(self, c, d, did, now):
        """Einmal bestätigen. Nie automatisch wiederholen; bei Abbruch werden die Entwürfe «unklar» und brauchen einen Abgleich."""
        with self._bcs_lock:
            p = self._bcs_prev.get(did)
            if not p or p["date"] != d:
                raise UserError("Diese Vorschau kennt tinyops nicht (mehr). Bitte neu «In BCS prüfen».")
            if now - p["ts"] > 900:
                self._bcs_prev.pop(did, None)
                raise UserError("Die Vorschau ist älter als 15 Minuten. Bitte neu prüfen.")
            inc, _ = self._bcs_included(d)
            if [x["id"] for x, _ in inc] != p["ids"] or self._bcs_sig(inc) != p["sig"]:
                self._bcs_prev.pop(did, None)
                raise UserError("Seit der Vorschau hat sich ein Entwurf geändert. Bitte neu prüfen.")
            self._bcs_prev.pop(did, None)                   # eine Vorschau wird höchstens einmal bestätigt
        tb = self.timebook
        mins = sum(ch["durationMinutes"] for _, ch in inc)
        try:
            r = c.commit(d, did)
        except bcs.BcsError as e:
            if e.uncertain:
                for x, _ in inc:
                    tb.update(x["id"], state="unklar", message="Bestätigen brach ab (%s). Unklar, ob gebucht: erst «Mit BCS abgleichen»." % str(e)[:150],
                              attempts=int(x["attempts"] or 0) + 1, sent=now)
                self.audit("bcs.commit", d, ok=False, status="unklar", drafts=len(inc), minutes=mins, error=str(e)[:200])
                return {"status": "unklar", "message": str(e)}
            raise UserError(str(e))
        st, msg = r.get("status"), str(r.get("message") or "")[:300]
        if st == "committed":
            for x, _ in inc:
                tb.update(x["id"], state="gebucht", reference="BCS %s" % d, message=msg, attempts=int(x["attempts"] or 0) + 1, sent=now)
        elif st == "rejected":
            for x, _ in inc:
                tb.update(x["id"], state="abgelehnt", message=msg or "von BCS abgelehnt", attempts=int(x["attempts"] or 0) + 1, sent=now)
        elif st == "dry_run":
            msg = "Probelauf der Middleware: nichts geschrieben. %s" % msg
        self.audit("bcs.commit", d, ok=st == "committed", status=st, drafts=len(inc), minutes=mins, message=msg[:200])
        return {"status": st, "message": msg, "refresh": bool(r.get("refreshRequired")), "warnings": r.get("warnings") or []}

    def _bcs_reconcile(self, c, d, now):
        """Nach einem unklaren Bestätigen: Tag in BCS lesen. Was dort steht, gilt als gebucht; der Rest darf neu geprüft werden."""
        tb = self.timebook
        day = self._bcs_call(c.day, d)
        tmap = tb.bcs_targets()
        entries = list(day.get("entries") or [])
        booked = back = 0
        for x in tb.drafts(d):
            if x["state"] != "unklar":
                continue
            task = self._bcs_task(x["ticket"], tmap)
            ch = bcs.change_for(x, task["task_id"]) if task else None
            hit = next((e for e in entries if ch and bcs.matches(e, ch)), None)
            if hit:
                entries.remove(hit)                         # ein Eintrag belegt höchstens einen Entwurf
                tb.update(x["id"], state="gebucht", reference="BCS %s" % d, message="Beim Abgleich in BCS gefunden.")
                booked += 1
            else:
                tb.update(x["id"], state="bestätigt", message="Beim Abgleich nicht in BCS gefunden: neu prüfen und bestätigen.")
                back += 1
        self.audit("bcs.reconcile", d, booked=booked, back=back)
        return {"booked": booked, "back": back, "day": bcs.day_summary(day)}

    def time_texts(self, d):
        """Kurze Buchungstexte vom (lokalen) Modell. Nur Vorschläge: übernommen wird erst auf deinen Klick."""
        if not llm.ready(self.lc):
            raise UserError("Kein Sprachmodell eingerichtet (Einstellungen → Lokales Sprachmodell).")
        rows = [x for x in self.timebook.drafts(d) if x["state"] in ("offen", "bestätigt", "fehlgeschlagen", "abgelehnt")][:20]
        if not rows:
            raise UserError("Keine offenen Entwürfe an diesem Tag.")
        try:
            out = llm.booking_texts(self.lc, self.llm_key, [{"id": x["id"], "ticket": x["ticket"], "title": x["title"], "minutes": x["minutes"],
                                                            "text": x["text"], "evidence": x["evidence"][:8]} for x in rows], self.ssl_ctx)
        except llm.LlmError as e:
            raise UserError(str(e))
        self.audit("time.texts", d, drafts=len(rows), suggested=len(out))
        return {"texts": out}
