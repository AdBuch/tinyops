"""Gespräch mit einem Agenten (0.40): Weiterführen in derselben Sitzung, Kette der Läufe, Nachrichten für die Anzeige.
Teil von agents.Service; braucht dessen store, base, agent_list."""
import json
import re

import briefing
from agent_cmd import KINDS, SESSIONS, can_resume
from agent_rules import PHASE_LABEL, STATUS_ACTIVE


class ConversationMixin:
    def can_continue(self, old, aid=None):
        """(ja, Grund): Geht das Weiterführen in der Sitzung des alten Laufs? Sonst startet ein neuer Lauf mit Zusammenfassung."""
        aid = aid or old["agent"]
        a = next((x for x in self.agent_list() if x["id"] == aid), None)
        if not a:
            return False, "Den Agenten gibt es nicht mehr."
        if aid != old["agent"]:
            return False, "Anderer Agent: Er beginnt eine neue Sitzung mit einer Zusammenfassung."
        if not can_resume(a):
            return False, "%s kann keine Sitzung fortsetzen: neuer Lauf mit Zusammenfassung." % KINDS[a["kind"]]["label"]
        if (old.get("mode") or "shared") != "shared" and not old.get("wt"):
            return False, "Der Arbeitsordner dieses Laufs ist nicht mehr da (entfernt, übernommen oder schon weitergeführt)."
        if old.get("next_run"):
            return False, "Dieser Lauf ist schon weitergeführt (Lauf %s)." % old["next_run"]
        if SESSIONS[a["kind"]].get("own") and not old.get("session"):
            return False, "Der Lauf stammt aus einer Version vor 0.40 und hat keine Sitzung: neuer Lauf mit Zusammenfassung."
        if old["status"] in ("verloren",):
            return False, "Der Lauf ist verloren gegangen; seine Sitzung ist unsicher."
        return True, ""

    def resume_prompt(self, old, brief):
        """Kurzer Prompt für die Fortsetzung: Werkzeuge und Auftrag kennt der Agent schon aus seiner Sitzung."""
        try:
            tpl = (self.base / "prompts" / "agent-resume.md").read_text(encoding="utf-8")
        except OSError:
            tpl = "# Weiter in derselben Sitzung\n\n{brief}\n"

        class D(dict):
            def __missing__(self, k):
                return ""
        return re.sub(r"\n{3,}", "\n\n", tpl.format_map(D(brief=brief.strip(), key=old.get("ticket") or "", title=old.get("title") or ""))).strip() + "\n"

    def chain(self, r, limit=30):
        """Alle Läufe eines Gesprächs: zurück über resume_of bis zum ersten, dann vorwärts über next_run."""
        cur, seen = r, {r["id"]}
        while cur.get("resume_of") and len(seen) < limit:
            try:
                prev = self.store.agent_run(int(cur["resume_of"]))
            except ValueError:
                break
            if not prev or prev["id"] in seen:
                break
            cur = prev
            seen.add(cur["id"])
        out, seen = [cur], {cur["id"]}
        while out[-1].get("next_run") and len(out) < limit:
            try:
                nxt = self.store.agent_run(int(out[-1]["next_run"]))
            except ValueError:
                break
            if not nxt or nxt["id"] in seen:
                break
            out.append(nxt)
            seen.add(nxt["id"])
        return out

    def thread(self, r):
        """Gespräch eines Laufs: dein Auftrag, deine Nachrichten, Rückfragen und Antworten, was der Agent jeweils gesagt hat."""
        runs, msgs = self.chain(r), []
        for i, x in enumerate(runs):
            ph = PHASE_LABEL.get(x.get("phase") or "develop", "")
            if i == 0:
                msgs.append({"who": "du", "text": "Auftrag (%s): %s" % (ph, x.get("title") or x["ticket"]), "run": x["id"]})
            else:
                msgs.append({"who": "du", "text": x.get("ask") or "(weiterführen)", "run": x["id"], "fresh": bool(x.get("fresh"))})
            try:
                qa = json.loads(x.get("qa") or "[]")
            except ValueError:
                qa = []
            for q in qa:
                msgs.append({"who": "agent", "text": "Frage: " + str(q.get("q") or ""), "run": x["id"]})
                msgs.append({"who": "du", "text": str(q.get("a") or ""), "run": x["id"]})
            if x["status"] in STATUS_ACTIVE:
                msgs.append({"who": "agent", "text": "… arbeitet", "run": x["id"], "busy": True})
            elif x["status"] != "zugewiesen":
                short = briefing.report_sections(x.get("summary") or "").get("short", "")
                msgs.append({"who": "agent", "text": (short or x.get("reply") or "(%s, keine Antwort)" % x["status"])[:3000], "run": x["id"], "status": x["status"]})
        return {"runs": [x["id"] for x in runs], "messages": msgs, "round": sum(1 for x in runs if (x.get("phase") or "develop") == "develop")}
