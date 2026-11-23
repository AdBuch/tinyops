"""Testen von Hand (0.42): Prüfliste je Ticket und «Jetzt testen».

Die Prüfliste sammelt, was zu testen ist, aus dem, was schon da ist: die Akzeptanzkriterien (wie der Agent sie gemeldet hat, sonst aus dem Ticket),
die Testschritte von Entwickler und Test-Agent (`tinyops-manual`), dazu eigene Punkte.
Je Punkt ok oder Fehler mit Notiz. Fehler gehen mit einem Klick zurück ans Entwickeln (in die Sitzung des Entwicklers, 0.40),
alles ok wird zur Abnahme am Commit (wie «Getestet» seit 0.15).

«Jetzt testen» bringt den Stand mit einem Klick auf den Tisch: Worktree genau auf dem MR-Commit (oder dem Branch des Agenten),
IntelliJ darauf, und die Review-Umgebung, wenn eine eingerichtet ist. Nur auf deinen Klick, nur auf diesem Rechner.

Bereich von App; Aufrufe in andere Bereiche stehen in USES und werden von tests/test_areas.py geprüft."""
import hashlib

from common import UserError

STATES = ("", "ok", "fail")
GENERIC = "Im laufenden System ausprobiert"          # fester Schlusspunkt in run_view; hier ein eigener


def _id(source, text):
    return hashlib.sha1(("%s\0%s" % (source, " ".join(text.split()).lower())).encode("utf-8")).hexdigest()[:12]


class TestArea:
    USES = {"area_ide": ("ide_open", "mr_env", "run_checkout", "run_env"), "area_agents": ("_agent_back",), "area_focus": ("_flow_accept",),
            "area_tickets": ("ticket_brief",)}

    def _test_runs(self, key):
        """Läufe des Tickets, neueste zuerst, als Ansicht (mit Kriterien, Bericht, Testschritten)."""
        svc = self.agents
        if not svc or not key:
            return []
        return [svc.run_view(r) for r in sorted(svc.store.agent_runs(ticket=key), key=lambda r: -r["id"])]

    def _test_sources(self, key):
        """Vorgeschlagene Punkte aus Kriterien, Test-Agent und Entwickler-Bericht."""
        runs, out = self._test_runs(key), []
        dev = next((r for r in runs if (r.get("phase") or "develop") == "develop" and r["status"] not in ("zugewiesen",)), None)
        test = next((r for r in runs if r.get("phase") == "test" and r["status"] == "fertig"), None)
        if not (dev and dev.get("criteria")):            # ohne Agent: Akzeptanzkriterien direkt aus dem Ticket
            for c in (self.ticket_brief(key) or {}).get("criteria") or []:
                out.append(("Kriterium", str(c)[:300], "aus dem Ticket"))
        if dev:
            for c in dev.get("criteria") or []:
                hint = {"ok": "Agent: erfüllt", "open": "Agent: offen", "unclear": "Agent: unklar"}.get(c.get("state"), "")
                out.append(("Kriterium", c["text"], hint))
        for who, r in (("Entwickler", dev), ("Test-Agent", test)):
            for m in (r or {}).get("manual") or []:
                if m.get("kind") == "test" and m.get("step") != GENERIC:
                    out.append((who, m["step"] + (" → " + m["expect"] if m.get("expect") else ""), "Testschritt"))
        out = out[:39] + [("tinyops", "Aus Sicht eines Nutzers ist das Ticket-Ziel erreicht", "zum Schluss")]
        seen, uniq = set(), []
        for src, text, hint in out:
            k = " ".join(text.split()).lower()
            if k not in seen:
                seen.add(k)
                uniq.append((src, text, hint))
        return uniq, dev, test

    def test_list(self, key):
        key = str(key or "").strip()
        if not key:
            raise UserError("Ticket fehlt.")
        sources, dev, test = self._test_sources(key)
        have = {r["id"]: r for r in self.store.tcheck_list(key)}
        items = []
        for src, text, hint in sources:
            iid = _id(src, text)
            r = have.pop(iid, None) or {}
            items.append({"id": iid, "text": text, "source": src, "hint": hint, "state": r.get("state", ""), "note": r.get("note", ""), "sha": r.get("sha", "")})
        for r in have.values():                  # eigene Punkte und solche, deren Quelle sich geändert hat (z. B. neuer Bericht)
            items.append({"id": r["id"], "text": r["text"], "source": r["source"], "hint": "" if r["source"] == "du" else "nicht mehr in der Quelle",
                          "state": r["state"], "note": r["note"], "sha": r["sha"], "own": r["source"] == "du"})
        card = (getattr(self, "_cards", None) or {}).get(key) or {}
        mrs = [x for x in card.get("items") or [] if x.get("iid")]
        n = {s: sum(1 for i in items if i["state"] == s) for s in STATES}
        return {"key": key, "items": items, "ok": n["ok"], "fail": n["fail"], "open": n[""],
                "dev_run": dev["id"] if dev else None, "dev_agent": dev.get("agent_name") if dev else "", "test_run": test["id"] if test else None,
                "target": ({"mr": {"host": mrs[0].get("host") or "gitlab", "project_id": mrs[0]["project_id"], "iid": mrs[0]["iid"], "sha": (mrs[0].get("sha") or "")[:8]}}
                           if mrs else {"run": dev["id"]} if dev and dev.get("out_branch") else {})}

    def test_action(self, action, b):
        key = str(b.get("key") or "").strip()
        if not key:
            raise UserError("Ticket fehlt.")
        if action == "list":
            return self.test_list(key)
        if action == "check":
            iid, st = str(b.get("id") or ""), str(b.get("state") or "")
            if st not in STATES:
                raise UserError("ok, Fehler oder offen?")
            row = next((i for i in self.test_list(key)["items"] if i["id"] == iid), None)
            if not row:
                raise UserError("Diesen Punkt gibt es nicht (mehr).")
            note = None if b.get("note") is None else " ".join(str(b["note"]).split())[:1000]
            if st == "fail" and not (note or row["note"]):
                raise UserError("Was ging nicht? Ein Satz reicht, er geht so an den Entwickler.")
            self.store.tcheck_set(key, iid, row["text"], row["source"], state=st, note=note, sha=(self.test_list(key)["target"].get("mr") or {}).get("sha", ""))
            return self.test_list(key)
        if action == "add":
            text = " ".join(str(b.get("text") or "").split())[:300]
            if len(text) < 3:
                raise UserError("Was willst du prüfen?")
            self.store.tcheck_set(key, _id("du", text), text, "du")
            return self.test_list(key)
        if action == "remove":
            self.store.tcheck_delete(key, str(b.get("id") or ""))
            return self.test_list(key)
        if action == "start":
            return self._test_start(key)
        if action == "back":
            return self._test_back(key, b)
        if action == "done":
            return self._test_done(key, b)
        raise UserError("Unbekannte Aktion.")

    def _test_start(self, key):
        """Jetzt testen: Stand in einen eigenen Worktree und IntelliJ, Review-Umgebung starten, wenn eingerichtet."""
        t = self.test_list(key)["target"]
        steps = []
        if t.get("mr"):
            m = t["mr"]
            try:
                r = self.ide_open({"host": m["host"], "project_id": m["project_id"], "iid": m["iid"]})
                steps.append({"step": "Worktree und IntelliJ", "ok": True, "msg": " ".join(x for x in (r.get("path"), r.get("hint")) if x), "path": r.get("path", "")})
            except UserError as e:
                steps.append({"step": "Worktree und IntelliJ", "ok": False, "msg": str(e)})
            pe = (self.proj_cfg.get(m["project_id"]) or {}).get("review_env")
            if pe:
                try:
                    r = self.mr_env({"host": m["host"], "project_id": m["project_id"], "iid": m["iid"], "do": "up"})
                    steps.append({"step": "Review-Umgebung", "ok": True, "msg": _env_msg(r), "url": (r or {}).get("url") or ""})
                except UserError as e:
                    steps.append({"step": "Review-Umgebung", "ok": False, "msg": str(e)})
        elif t.get("run"):
            rid = t["run"]
            try:
                r = self.run_checkout(rid)
                steps.append({"step": "Worktree und IntelliJ", "ok": True, "msg": " ".join(x for x in (r.get("path"), r.get("hint")) if x), "path": r.get("path", "")})
            except UserError as e:
                steps.append({"step": "Worktree und IntelliJ", "ok": False, "msg": str(e)})
            run = self.store.agent_run(rid) or {}
            if run.get("project_id") is not None and (self.proj_cfg.get(run["project_id"]) or {}).get("review_env"):
                try:
                    r = self.run_env(rid, "up")
                    steps.append({"step": "Review-Umgebung", "ok": True, "msg": _env_msg(r), "url": (r or {}).get("url") or ""})
                except UserError as e:
                    steps.append({"step": "Review-Umgebung", "ok": False, "msg": str(e)})
        else:
            raise UserError("Noch nichts zum Testen: kein MR und kein beendeter Lauf mit eigenem Branch.")
        self.audit("test.start", key, steps=len(steps), ok=sum(1 for s in steps if s["ok"]))
        return {"steps": steps}

    def _test_back(self, key, b):
        """Fehler zurück ans Entwickeln: die Punkte mit Fehler und ihre Notizen gehen in die Sitzung des Entwicklers."""
        lst = self.test_list(key)
        bad = [i for i in lst["items"] if i["state"] == "fail"]
        if not bad:
            raise UserError("Kein Punkt ist als Fehler markiert.")
        if not lst["dev_run"]:
            raise UserError("An diesem Ticket arbeitet kein Agent. «Fehler kopieren» und selbst weitergeben.")
        text = "Beim Testen von Hand ging das nicht:\n" + "\n".join("- %s: %s" % (i["text"], i["note"]) for i in bad)
        extra = " ".join(str(b.get("note") or "").split())[:1000]
        if extra:
            text += "\n\nDazu: " + extra
        out = self._agent_back(self.agents, {"run": lst["dev_run"], "note": text})
        for i in bad:                                # die Punkte sind beim Entwickler; nach seinem Lauf wieder prüfen
            self.store.tcheck_set(key, i["id"], i["text"], i["source"], state="", note="zurück an Lauf %s: %s" % (out.get("id"), i["note"]))
        self.audit("test.back", key, fails=len(bad), new_run=out.get("id"))
        return dict(out, sent=len(bad))

    def _test_done(self, key, b):
        """Alles ok: Abnahme am Commit (wie «Getestet»), mit der Prüfliste als Notiz."""
        lst = self.test_list(key)
        if lst["fail"]:
            raise UserError("%d Punkt(e) mit Fehler. Erst zurück ans Entwickeln oder neu prüfen." % lst["fail"])
        if lst["open"] and not b.get("force"):
            raise UserError("%d Punkt(e) noch offen. Abhaken, oder trotzdem abnehmen." % lst["open"])
        note = "Prüfliste: %d ok%s" % (lst["ok"], ", %d offen" % lst["open"] if lst["open"] else "")
        out = self._flow_accept({"id": key, "note": note, "env": b.get("env") or ""})
        self.audit("test.done", key, ok=lst["ok"], open=lst["open"])
        return out


def _env_msg(st):
    """Zustand der Review-Umgebung (von _renv_start) in einem Satz."""
    st = st or {}
    return "%s: %s" % (st.get("state") or "startet", (st.get("cmd") or "")[:200])


def checklist_text(lst):
    """Prüfliste als Markdown, zum Kopieren (z. B. in den MR)."""
    mark = {"ok": "[x]", "fail": "[ ] ✗", "": "[ ]"}
    return "\n".join("- %s %s%s" % (mark[i["state"]], i["text"], (" — " + i["note"]) if i.get("note") else "") for i in lst["items"]) + "\n"


