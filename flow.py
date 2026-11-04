"""Der feste Ablauf jedes Vorhabens und sein nächster Schritt.

Jedes Vorhaben (Jira-Ticket, eigene Aufgabe, Idee, Branch oder MR ohne Ticket) fährt dieselbe Strecke:
Planen → Branch → Code → MR → Prüfen → Testen → Mergen → Fertig.
Die Station ergibt sich aus den Daten (gibt es einen Branch, einen MR, ist die Pipeline grün, ...). Du kannst sie im Board übersteuern;
Blocker (rote Pipeline, rotes Gate, Konflikt) bleiben trotzdem sichtbar. Pro Vorhaben gibt es genau einen nächsten Schritt und wer ihn
machen muss: du, die CI, andere (Review) oder ein Agent.

Fortschritt zählt nur, wenn ein Vorhaben eine Station erreicht, die es noch nie erreicht hatte. Zurückfallen und wieder Vorrücken gibt
deshalb keine Punkte, und Teilergebnisse während eines Abgleichs werden nicht gezählt.
"""
import re
import time

PHASES = (("plan", "Planen"), ("branch", "Branch"), ("code", "Code"), ("mr", "MR"), ("check", "Prüfen"),
          ("test", "Testen"), ("merge", "Mergen"), ("done", "Fertig"))
IDX = {p: i for i, (p, _) in enumerate(PHASES)}
STAGE_TO_PHASE = {"idea": 0, "planned": 0, "impl": 2, "review": 4, "test": 5, "tested": 6, "done": 7}
PHASE_TO_STAGE = {0: "planned", 2: "impl", 4: "review", 5: "test", 6: "tested", 7: "done"}   # Branch und MR sind Tatsachen, keine Wahl
RUNNING = ("running", "pending", "created", "waiting_for_resource", "preparing", "scheduled")
XP_STEP, XP_DONE, XP_CHECK, XP_AGENT = 10, 30, 3, 5


def _slug(s):
    return re.sub(r"[^a-z0-9]+", "-", (s or "").lower()).strip("-")[:40].strip("-")


def branch_cmd(key, title):
    name = "-".join(x for x in ((key or "").strip(), _slug(title)) if x) or "neuer-branch"
    if key:
        name = "feature/" + name
    return "git switch -c %s" % name


def _mr_rank(m):
    """Wie weit ist ein MR? Der am wenigsten fortgeschrittene bestimmt den Schritt (Engpass)."""
    if m.get("draft"):
        return 0
    if (m.get("merge_status") or "") in ("conflict", "need_rebase") or m.get("pipeline") == "failed" or m.get("sonar") == "ERROR":
        return 1
    if m.get("pipeline") in RUNNING:
        return 2
    if (m.get("merge_status") or "") in ("discussions_not_resolved", "not_approved", "approvals_syncing"):
        return 3
    return 4


def _step(kind, sid, label, why, owner="me", **action):
    return {"kind": kind, "id": sid, "label": label, "why": why, "owner": owner, "action": action}


def derive(card, runs=(), checklist=(), seen_max=None, now=None):
    """Station und nächster Schritt einer Karte. Gibt {phase, phase_id, override, next, flags} zurück."""
    now = now or time.time()
    items = [x for x in card.get("items") or [] if x.get("kind") in ("mr", "branch", "assigned")]
    mrs = [x for x in items if x.get("kind") in ("mr", "assigned") and x.get("iid")]
    branches = [x for x in items if x.get("kind") == "branch"]
    open_checks = [c for c in checklist if not c["done"]]
    key, title = card.get("key") or "", card.get("title") or ""
    flags = []
    if not key and not card.get("idea_id"):
        flags.append("ohne Ticket")

    # -- aus den Daten
    if card.get("idea_id"):
        data, nxt = 0, _step("do", "plan", "Einplanen", "Eine Idee. Kategorie wählen und ins Board übernehmen.", action="plan")
    elif mrs:
        m = sorted(mrs, key=_mr_rank)[0]
        ms, label = m.get("merge_status") or "", "!%s" % m.get("iid")
        more = " (und %d weitere MR)" % (len(mrs) - 1) if len(mrs) > 1 else ""
        url = m.get("url", "")
        if m.get("draft"):
            data = 3
            nxt = _step("do", "ready", "Draft fertigstellen", "MR %s ist noch Draft%s. Fertig? Dann «Mark as ready» in GitLab." % (label, more), url=url)
        elif ms in ("conflict", "need_rebase"):
            data = 4
            nxt = _step("blocked", "rebase", "Konflikt lösen", "MR %s lässt sich nicht mergen: %s." % (label, "Konflikt" if ms == "conflict" else "Rebase nötig"), url=url)
        elif m.get("pipeline") == "failed":
            data = 4
            nxt = _step("blocked", "pipeline", "Pipeline reparieren", "Die Pipeline von MR %s ist rot." % label, url=m.get("pipeline_url") or url)
        elif m.get("sonar") == "ERROR":
            data = 4
            nxt = _step("blocked", "sonar", "Sonar-Findings beheben", (m.get("sonar_detail") or "Quality Gate rot") + " (MR %s)." % label,
                        report={"project_id": m.get("project_id"), "iid": m.get("iid"), "branch": m.get("branch")}, url=m.get("sonar_issues_url") or m.get("sonar_url") or url)
        elif m.get("pipeline") in RUNNING:
            data = 4
            nxt = _step("wait", "ci", "Pipeline läuft", "Warten auf die CI von MR %s." % label, owner="ci", url=m.get("pipeline_url") or url)
        elif ms == "discussions_not_resolved":
            data = 4
            nxt = _step("do", "threads", "Kommentare klären", "Im MR %s sind Diskussionen offen." % label, url=url)
        elif ms in ("not_approved", "approvals_syncing"):
            data = 4
            nxt = _step("wait", "review", "Review abwarten", "MR %s braucht noch eine Freigabe." % label, owner="others", url=url)
        else:
            data = 5
            nxt = _step("do", "test", "Manuell testen", "Pipeline und Gate sind in Ordnung (MR %s). Testen, dann als getestet markieren." % label,
                        stage="tested", url=url)
    elif branches:
        b = branches[0]
        data = 2
        n = b.get("ahead") or 0
        nxt = _step("do", "mr_create", "MR erstellen", "%s auf %s, noch kein MR. Ein Draft-MR zeigt früh, ob die Pipeline durchläuft." %
                    ("%d Commit%s" % (n, "" if n == 1 else "s") if n else "Arbeit", b.get("branch")), url=b.get("create_mr_url") or b.get("url", ""))
    elif seen_max is not None and seen_max >= IDX["check"]:
        data = 6
        nxt = _step("do", "close", "Abschliessen", "Kein offener MR mehr. Gemergt? Dann auf «Fertig» setzen.", stage="done")
    elif card.get("stage") in ("impl", "review", "test") or card.get("jira_in_progress"):
        data = 1
        nxt = _step("do", "branch", "Branch anlegen", "In Arbeit, aber noch kein Branch mit %s." % (key or "diesem Namen"), copy=branch_cmd(key, title))
    else:
        data = 0
        nxt = _step("do", "start", "Loslegen", "Geplant. Loslegen heisst: Branch anlegen oder einen Agenten zuweisen.", copy=branch_cmd(key, title), stage="impl")

    # -- Übersteuerung im Board
    manual = STAGE_TO_PHASE.get(card.get("stage")) if card.get("manual_stage") and not card.get("idea_id") else None
    phase = data
    if manual is not None:
        if manual == 7:
            phase, nxt = 7, _step("done", "done", "Erledigt", "Auf «Fertig» gesetzt.", owner="none")
        elif manual > data:
            phase = manual
            if nxt["kind"] == "do":          # Blocker und Warten (CI, Review) bleiben sichtbar, auch wenn von Hand weitergeschoben
                if manual == 6:
                    url = (sorted(mrs, key=_mr_rank)[0]["url"]) if mrs else ""
                    nxt = (_step("do", "merge", "Mergen", "Getestet. In GitLab mergen, danach erscheint «Abschliessen».", url=url) if mrs else
                           _step("do", "close", "Abschliessen", "Getestet. Ist alles gemergt? Dann auf «Fertig» setzen.", stage="done"))
                elif manual == 5:
                    nxt = _step("do", "test", "Manuell testen", "Testen, dann als getestet markieren.", stage="tested",
                                url=(mrs[0]["url"] if mrs else ""))
        elif manual == 0 and data <= 2 and not mrs:
            phase = 0

    # -- Agenten
    latest = runs[0] if runs else None
    if latest and phase < 7:
        if latest["status"] == "läuft":
            nxt = _step("wait", "agent", "Agent arbeitet", "%s seit %s." % (latest.get("agent_name", "Agent"), _dur(now - (latest.get("started") or now))),
                        owner="agent", run=latest["id"])
        elif latest["status"] in ("fehlgeschlagen", "verloren") and nxt["kind"] != "blocked":
            nxt = _step("blocked", "agent_failed", "Agent-Lauf prüfen", "%s: %s." % (latest.get("agent_name", "Agent"), latest["status"]), run=latest["id"])
        elif latest["status"] == "fertig" and phase <= 2:
            nxt = _step("do", "agent_result", "Ergebnis des Agenten prüfen", "%s ist fertig. Log ansehen, dann MR erstellen." % latest.get("agent_name", "Agent"),
                        run=latest["id"])
        elif latest["status"] == "zugewiesen" and phase <= 2 and nxt["kind"] == "do":
            nxt = _step("do", "agent_start", "Agent starten", "%s ist zugewiesen, aber noch nicht gestartet." % latest.get("agent_name", "Agent"), run=latest["id"])

    # -- Teilschritte: der nächste offene Haken ist der kleinste nächste Schritt
    if open_checks and phase in (0, 1, 2, 3) and nxt["kind"] == "do" and nxt["id"] not in ("agent_result", "agent_start", "plan"):
        done_n = len(checklist) - len(open_checks)
        nxt = _step("do", "check", open_checks[0]["text"], "Teilschritt %d von %d. Danach: %s." % (done_n + 1, len(checklist), nxt["label"]),
                    check=open_checks[0]["id"], then=nxt)

    return {"phase": phase, "phase_id": PHASES[phase][0], "override": manual is not None and manual != data, "data_phase": data,
            "next": nxt, "flags": flags, "checks": {"done": len(checklist) - len(open_checks), "total": len(checklist)}}


def _dur(s):
    s = max(0, int(s))
    if s >= 3600:
        return "%d h %d min" % (s // 3600, s % 3600 // 60)
    if s >= 60:
        return "%d min" % (s // 60)
    return "%d s" % s


def priority(card, d):
    """Reihenfolge für «Jetzt dran»: erst Blocker, dann Begonnenes zu Ende bringen (je weiter, desto höher), dann Neues. Warten zählt nicht."""
    k = d["next"]["kind"]
    if k == "done":
        return -10
    if k == "wait":
        return -1
    base = 300 if k == "blocked" else 100
    if card.get("idea_id"):
        base = 10
    elif d["phase"] == 0:
        base = 40 if card.get("jira_in_progress") else 20
    return base + d["phase"] * 10


def review_view(data):
    """MRs anderer, die auf dich warten (Review angefragt oder dir zugeteilt)."""
    out = []
    for it in (data.get("review") or []) + (data.get("assigned") or []):
        rev = it.get("kind") == "review"
        out.append({"id": it.get("ref") or "%s:%s" % (it.get("project_id"), it.get("branch")), "title": it.get("title", ""), "project": it.get("project", ""),
                    "iid": it.get("iid"), "url": it.get("url", ""), "author": it.get("author", ""), "age_days": it.get("age_days", 0),
                    "pipeline": it.get("pipeline", "none"), "keys": it.get("keys") or [],
                    "next": _step("do", "do_review" if rev else "assigned", "Review machen" if rev else "Zugeteilten MR ansehen",
                                  "%s wartet seit %d Tag%s auf dich." % (it.get("author") or "Jemand", it.get("age_days", 0), "" if it.get("age_days", 0) == 1 else "en"),
                                  url=it.get("url", ""))})
    return out


def build(cards, store, runs_by_ticket, complete, goal=3, now=None):
    """Alle Karten mit Station und nächstem Schritt, dazu der Spielstand. Schreibt den Fortschritt nur bei vollständigen Daten."""
    now = now or time.time()
    seen = store.flow_states()
    checks = store.checklists()
    out = []
    for c in cards:
        cid = c["id"]
        d = derive(c, runs_by_ticket.get(cid, []), checks.get(cid, []), (seen.get(cid) or {}).get("max_phase"), now)
        d["prio"] = priority(c, d)
        d["checklist"] = [{"id": x["id"], "text": x["text"], "done": bool(x["done"])} for x in checks.get(cid, [])]
        out.append((c, d))
    if complete:
        store.flow_record([(c["id"], c.get("key") or "", c.get("title") or "", d["phase"]) for c, d in out if not c.get("idea_id")], now)
        for runs in runs_by_ticket.values():
            for r in runs:
                if r["status"] == "fertig":
                    store.flow_event_once("run:%d" % r["id"], r["ticket"], r.get("title") or "", "agent", -1, XP_AGENT,
                                          "%s fertig" % r.get("agent_name", "Agent"), now)
    return {"items": {c["id"]: d for c, d in out}, "stats": store.flow_stats(goal, now), "phases": [{"id": p, "label": l} for p, l in PHASES],
            "phase_stage": {str(k): v for k, v in PHASE_TO_STAGE.items()}}
