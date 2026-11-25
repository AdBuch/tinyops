"""Sprache (0.43): diktieren in Prompt-Felder und Sprachbefehle an Agenten.

Diktieren: der Browser nimmt auf, `voice_transcribe` gibt nur Text zurück (voice.py, lokaler Server).
Sprachbefehle wie «DLP-123 an Qwen zum Entwickeln, starten» oder «Review für MR 47 mit Claude»:
1. `voice_command` versteht den Satz, zuerst mit festen Regeln, nur wenn die nichts finden mit dem lokalen Sprachmodell.
   Das Ergebnis ist ein Vorschlag, geprüft gegen die bekannten Tickets, MRs und Agenten. Ausgeführt wird dabei nichts.
2. Du bestätigst. Erst `voice_run` führt aus, über dieselben Wege wie die Knöpfe (Agent zuweisen, starten, Review), mit allen ihren Prüfungen.
Was du gesagt hast, geht wörtlich als «Dein gesprochener Auftrag» an den Agenten. Im Verlauf steht die Aktion, nicht der Wortlaut.

Bereich von App; Aufrufe in andere Bereiche stehen in USES und werden von tests/test_areas.py geprüft."""
import json
import re

import agents
import llm
import voice
from common import UserError

PHASE_WORDS = (("review", r"review\w*|prüf\w*|durchseh\w*|gegenles\w*|code ?review"), ("test", r"test\w*"),
               ("plan", r"plan\w*"), ("develop", r"entwickl\w*|umsetz\w*|implementier\w*|bau\w*|fix\w*|programmier\w*|mach\w*"))
NO_START = re.compile(r"\bnur zuweis\w*|\bnicht starten|\bohne (zu )?start\w*|\bspäter starten", re.I)
MR_RE = re.compile(r"(?:\bmerge[- ]?request|\bmr|!)\s*(?:nummer\s*)?#?(\d{1,6})\b", re.I)
KEY_RE = re.compile(r"\b([A-Za-z]{2,10})(?:\s*[-‐–]\s*|\s+)?(\d{1,7})\b")

COMMAND_SYSTEM = (
    "Du übersetzt einen gesprochenen Satz in einen Auftrag an einen Coding-Agenten. Antworte nur mit JSON: "
    "{\"ticket\": \"<Key oder leer>\", \"mr\": <MR-Nummer oder null>, \"agent\": \"<id oder leer>\", "
    "\"phase\": \"plan|develop|review|test\", \"start\": true|false}. "
    "Nimm nur Tickets, MRs und Agenten aus den Listen. Fehlt etwas oder ist es unklar, lass das Feld leer. Erfinde nichts."
)


def _norm(s):
    return re.sub(r"[^a-z0-9äöü]+", " ", s.lower()).strip()


class VoiceArea:
    USES = {"area_agents": ("agent_action",), "area_review": ("review_start",)}

    # ------------------------------------------------------------ Diktieren
    def voice_transcribe(self, wav, lang=""):
        vc = voice.cfg_of(self.cfg)
        try:
            text, secs, took = voice.transcribe(vc, wav, lang if lang in voice.LANGS else None, self._voice_key(), self.ssl_ctx)
        except voice.VoiceError as e:
            raise UserError(str(e))
        return {"text": text, "seconds": round(secs, 1), "took": round(took, 1)}

    def _voice_key(self):
        try:
            import secretstore
            val, _ = secretstore.resolve("voice_key", (self.cfg.get("secrets") or {}).get("voice_key"))
        except Exception:      # kein Schlüssel ist der Normalfall bei einem lokalen Server
            return ""
        return val or ""

    # ------------------------------------------------------------ Sprachbefehl verstehen
    def _voice_known(self):
        """Was ein Befehl nennen darf: Karten mit Ticket-Key, MRs, die auf dich warten, und die Agenten."""
        cards = {}
        for c in (getattr(self, "_cards", None) or {}).values():
            if c.get("idea_id"):
                continue
            for k in {c.get("key"), c.get("id")} - {None, ""}:
                cards[str(k).upper()] = c
        with self.cache_lock:
            data = self.cache or {}
        mrs = [it for it in (data.get("review") or []) + (data.get("assigned") or []) + (data.get("mine") or [])
               if it.get("iid") and (it.get("host") or "gitlab") == "gitlab"]
        ags = self.agents.agent_list() if self.agents else []
        return cards, mrs, ags

    def _voice_rules(self, text, cards, mrs, ags):
        """Feste Regeln: Ticket-Key oder MR-Nummer, Agent beim Namen, Phase und «starten» an Stichworten."""
        low = " " + _norm(text) + " "
        out = {"ticket": "", "mr": None, "agent": "", "phase": "", "start": not NO_START.search(text)}
        m = MR_RE.search(text)
        if m:
            out["mr"] = int(m.group(1))
        for pre, num in KEY_RE.findall(text):
            k = "%s-%s" % (pre.upper(), num)
            if k in cards:
                out["ticket"] = k
                break
        best = ""
        for a in ags:
            for name in {a["name"], a["id"]}:
                n = _norm(name)
                if n and re.search(r"(^| )%s( |$)" % re.escape(n), low.strip()) and len(n) > len(best):
                    best, out["agent"] = n, a["id"]
        for ph, rx in PHASE_WORDS:
            if re.search(r"\b(%s)\b" % rx, low):
                out["phase"] = ph
                break
        return out

    def _voice_model(self, text, cards, mrs, ags):
        """Rückfall, wenn die Regeln weder Ticket noch MR finden: das lokale Sprachmodell, mit festen Listen."""
        if not llm.ready(self.lc):
            return None
        lists = ["Tickets:"] + ["- %s: %s" % (k, (c.get("title") or "")[:80]) for k, c in list(cards.items())[:60] if "-" in k]
        lists += ["MRs:"] + ["- %d: %s" % (it["iid"], (it.get("title") or "")[:80]) for it in mrs[:40]]
        lists += ["Agenten:"] + ["- %s: %s (Rollen: %s)" % (a["id"], a["name"], ", ".join(agents.agent_roles(a))) for a in ags]
        try:
            raw = llm.ask(self.lc, self.llm_key, COMMAND_SYSTEM, "\n".join(lists) + "\n\nSatz: " + text[:600], self.ssl_ctx, what="Sprachbefehl")
            m = re.search(r"\{.*\}", raw, re.S)
            d = json.loads(m.group(0)) if m else {}
        except (llm.LlmError, ValueError, AttributeError):
            return None
        if not isinstance(d, dict):
            return None
        mr = d.get("mr")
        return {"ticket": str(d.get("ticket") or "").upper(), "mr": int(mr) if isinstance(mr, (int, float)) or str(mr).isdigit() else None,
                "agent": str(d.get("agent") or ""), "phase": d.get("phase") if d.get("phase") in agents.PHASES else "",
                "start": d.get("start") is not False}

    def voice_command(self, b):
        """Gesprochener Satz → Vorschlag zum Bestätigen. Führt nichts aus."""
        text = " ".join(str(b.get("text") or "").split())[:1000]
        if len(text) < 3:
            raise UserError("Nichts verstanden. Zum Beispiel: «DLP-123 an Qwen zum Entwickeln».")
        if not self.agents or not self.agents.agent_list():
            raise UserError("Noch kein Agent eingerichtet (Einstellungen → Coding-Agenten).")
        cards, mrs, ags = self._voice_known()
        if isinstance(b.get("plan"), dict):          # im Vorschlag geändert (Agent, Phase, starten): nur neu prüfen, nicht neu verstehen
            q = b["plan"]
            mr = q.get("mr")
            return self._voice_plan({"ticket": str(q.get("ticket") or ""), "mr": mr.get("iid") if isinstance(mr, dict) else None, "agent": q.get("agent"),
                                     "phase": q.get("phase") if q.get("phase") in agents.PHASES else "", "start": q.get("start", True) is not False,
                                     "text": text, "via": q.get("via") or ""}, cards, mrs, ags)
        p, via = self._voice_rules(text, cards, mrs, ags), "Regeln"
        if not p["ticket"] and p["mr"] is None:
            q = self._voice_model(text, cards, mrs, ags)
            if q:
                p, via = dict(q, start=q["start"] and p["start"]), "lokales Modell"
                if p["ticket"] not in cards:
                    p["ticket"] = ""
        return self._voice_plan(dict(p, text=text, via=via), cards, mrs, ags)

    def _voice_plan(self, p, cards, mrs, ags):
        """Vorschlag prüfen und beschreiben. Auch voice_run geht hier durch: nie einem Vorschlag aus dem Browser vertrauen."""
        svc = self.agents
        by_id = {a["id"]: a for a in ags}
        phase = p.get("phase") or ""
        mr = None
        if p.get("mr") is not None and (phase in ("review", "") or not p.get("ticket")):
            hits = [it for it in mrs if it["iid"] == int(p["mr"])]
            if not hits:
                raise UserError("MR %s kenne ich nicht: nur MRs, die in tinyops stehen (deine und die, die auf dich warten)." % p["mr"])
            if len({it["project_id"] for it in hits}) > 1:
                raise UserError("MR %s gibt es in mehreren Projekten (%s). Bitte im Detail-Panel starten." % (p["mr"], ", ".join(sorted({it.get("project") or str(it["project_id"]) for it in hits}))))
            mr, phase = hits[0], "review"
        card = cards.get(str(p.get("ticket") or "").upper()) if not mr else None
        if not mr and not card:
            raise UserError("Welches Ticket oder welcher MR? Ich habe keinen erkannt, der in tinyops steht. Zum Beispiel: «DLP-123 an Qwen zum Entwickeln» oder «Review für MR 47».")
        phase = phase or "develop"
        aid = p.get("agent") or ""
        if aid and aid not in by_id:
            aid = ""
        if not aid:                       # kein Name genannt: der erste mit passender Rolle, sonst der erste
            aid = (next((a for a in ags if phase in agents.agent_roles(a)), None) or ags[0])["id"]
        a = by_id[aid]
        out = {"kind": "mr_review" if mr else "agent", "agent": aid, "agent_name": a["name"], "phase": phase, "phase_label": agents.PHASE_LABEL[phase],
               "start": bool(p.get("start", True)) or bool(mr), "text": p.get("text") or "", "via": p.get("via") or "", "warn": ""}
        if mr:
            out.update(mr={"project_id": mr["project_id"], "iid": mr["iid"], "title": mr.get("title") or "", "project": mr.get("project") or ""},
                       ticket=(mr.get("keys") or [""])[0], title="!%d %s" % (mr["iid"], mr.get("title") or ""))
            ok, why = svc.allowed(a, mr["project_id"])
            if ok and svc.mode(a, mr["project_id"]) != "worktree":
                ok, why = False, "arbeitet nicht in einem eigenen Worktree"
        else:
            items = card.get("items") or []
            pid = items[0]["project_id"] if items else None
            out.update(ticket=card["id"], key=card.get("key") or "", title=card.get("title") or "", project_id=pid,
                       branch=(items[0].get("branch") if items else "") or "")
            ok, why = (svc.allowed(a, pid) if pid is not None else (True, ""))
            if phase in ("review", "test"):
                dev = self._voice_dev_run(card["id"])
                if not dev:
                    ok, why = False, "%s braucht einen beendeten Entwickeln-Lauf an %s." % (agents.PHASE_LABEL[phase], card.get("key") or card["id"])
                out["parent"] = dev
        if phase not in agents.agent_roles(a):
            out["warn"] = "%s hat die Rolle «%s» nicht." % (a["name"], agents.PHASE_LABEL[phase])
        out["ok"], out["why"] = ok, ("" if ok else why)
        return out

    def _voice_dev_run(self, ticket):
        runs = [r for r in self.agents.store.agent_runs(ticket=ticket) if (r.get("phase") or "develop") == "develop"
                and r["status"] not in ("zugewiesen", "läuft")]
        return max((r["id"] for r in runs), default=None)

    # ------------------------------------------------------------ Ausführen (nach deiner Bestätigung)
    def voice_run(self, b):
        if self.demo:
            raise UserError("In der Demo startet kein Agent.")
        cards, mrs, ags = self._voice_known()
        p = {k: b.get(k) for k in ("agent", "phase", "text", "via")}
        p["start"] = b.get("start", True) is not False
        p["ticket"], p["mr"] = str(b.get("ticket") or ""), ((b.get("mr") or {}).get("iid") if isinstance(b.get("mr"), dict) else None)
        plan = self._voice_plan(p, cards, mrs, ags)
        if not plan["ok"]:
            raise UserError("%s: %s" % (plan["agent_name"], plan["why"]))
        said = plan["text"][:1000]
        if plan["kind"] == "mr_review":
            out = self.review_start({"host": "gitlab", "project_id": plan["mr"]["project_id"], "iid": plan["mr"]["iid"], "agent": plan["agent"],
                                     "ticket": plan.get("ticket") or "", "goal": said})
            self.audit("voice.run", "!%d" % plan["mr"]["iid"], kind="mr_review", agent=plan["agent"], run=out["id"])
            return dict(out, started=True, plan=plan)
        body = {"agent": plan["agent"], "ticket": plan["ticket"], "key": plan.get("key") or "", "project_id": plan["project_id"],
                "branch": plan["branch"], "title": plan["title"], "url": "", "phase": plan["phase"]}
        if plan.get("parent"):
            body["parent"] = plan["parent"]
        info = self.agent_action("prompt", body)
        if not info.get("allowed", True):
            raise UserError(info.get("reason") or "Dieser Agent darf das nicht.")
        rp = info.get("repo") or {}
        if plan["project_id"] is not None and rp.get("state") in ("missing", "dir"):
            raise UserError("Das Projekt liegt beim Agenten %s noch nicht. Im Agenten-Dialog «Jetzt klonen»." % plan["agent_name"])
        pid = info.get("project_id", plan["project_id"])
        branch = info.get("branch") or plan["branch"]
        prompt = info["prompt"].rstrip() + "\n\n## Dein gesprochener Auftrag (wörtlich)\n\n" + said + "\n"
        rid = self.agent_action("assign", {"agent": plan["agent"], "ticket": plan["ticket"], "project_id": pid, "branch": branch, "title": plan["title"]})["id"]
        if plan["start"]:
            self.agent_action("start", {"run": rid, "prompt": prompt, "project_id": pid, "branch": branch, "phase": plan["phase"], "parent": info.get("parent")})
        self.audit("voice.run", plan["ticket"], kind="agent", agent=plan["agent"], phase=plan["phase"], start=plan["start"], run=rid, via=plan["via"])
        return {"id": rid, "agent": plan["agent_name"], "started": plan["start"], "plan": plan}
