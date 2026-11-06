"""Offene Review-Punkte eines MR/PR (0.18): lesen (nur GET), als Markdown-Prompt oder JSON ausgeben.

GitLab: Threads, die sich auflösen lassen und noch offen sind (`/merge_requests/:iid/discussions`).
GitHub: Review-Kommentare (`/pulls/:n/comments`) als Threads, dazu «Änderungen angefordert» mit Text. Ob ein GitHub-Thread
erledigt ist, steht nur in der GraphQL-API (POST); tinyops bleibt bei GET, also heisst es dort «Status unbekannt».

Nicht im Export: Code aus dem Diff (diff_hunk). Ziel ist Datei, Zeile und Commit; den Code liest der Agent im Repository.
Kommentartexte sind Inhalt von Reviewern. Im Prompt stehen sie als Zitat und gelten ausdrücklich als Daten.
"""
import json
import re
import time

import secretstore as store

SCHEMA = "tinyops.review-topics/1"
MAX_BODY = 4000


def _txt(s, n=MAX_BODY):
    s = store.scrub_all(str(s or "")).replace("\r\n", "\n").strip()
    return s if len(s) <= n else s[:n] + " …"


def _line_range(pos):
    lr = (pos or {}).get("line_range") or {}
    a, b = (lr.get("start") or {}), (lr.get("end") or {})
    sa, sb = a.get("new_line") or a.get("old_line"), b.get("new_line") or b.get("old_line")
    return "%s-%s" % (sa, sb) if sa and sb and sa != sb else ""


def gitlab_topics(discussions, head_sha):
    """Offene, auflösbare Threads. Systemnotizen und einzelne Kommentare ohne Auflösen zählen nicht."""
    out = []
    for d in discussions or []:
        notes = [n for n in d.get("notes") or [] if not n.get("system")]
        if not notes:
            continue
        resolvable = [n for n in notes if n.get("resolvable")]
        if not resolvable or all(n.get("resolved") for n in resolvable):
            continue
        first = notes[0]
        pos = first.get("position") or {}
        f = pos.get("new_path") or pos.get("old_path") or ""
        line = pos.get("new_line") or pos.get("old_line")
        sha = pos.get("head_sha") or ""
        out.append({
            "id": "gl:%s" % d.get("id", first.get("id")), "kind": "line" if f else "general", "file": f,
            "old_file": pos.get("old_path") if pos.get("old_path") and pos.get("old_path") != f else "",
            "line": line, "side": "neu" if pos.get("new_line") else ("alt" if pos.get("old_line") else ""), "range": _line_range(pos),
            "sha": sha, "outdated": bool(sha and head_sha and sha != head_sha), "resolved": False,
            "author": (first.get("author") or {}).get("username", ""), "created": first.get("created_at", ""),
            "body": _txt(first.get("body")), "url": "",
            "note_id": first.get("id"),
            "replies": [{"author": (n.get("author") or {}).get("username", ""), "body": _txt(n.get("body"), 1500), "created": n.get("created_at", "")}
                        for n in notes[1:]][:20],
        })
    return out


def github_topics(comments, reviews, head_sha):
    """Review-Kommentare als Threads (Antworten über in_reply_to_id) plus «Änderungen angefordert» mit Text."""
    roots, replies = [], {}
    for c in comments or []:
        if c.get("in_reply_to_id"):
            replies.setdefault(c["in_reply_to_id"], []).append(c)
        else:
            roots.append(c)
    out = []
    for c in roots:
        sha = c.get("commit_id") or c.get("original_commit_id") or ""
        line = c.get("line") or c.get("original_line")
        start = c.get("start_line") or c.get("original_start_line")
        out.append({
            "id": "gh:%s" % c.get("id"), "kind": "line" if c.get("path") else "general", "file": c.get("path") or "", "old_file": "",
            "line": line, "side": "alt" if c.get("side") == "LEFT" else "neu", "range": "%s-%s" % (start, line) if start and line and start != line else "",
            "sha": sha, "outdated": c.get("position") is None or bool(sha and head_sha and sha != head_sha), "resolved": None,
            "author": (c.get("user") or {}).get("login", ""), "created": c.get("created_at", ""), "body": _txt(c.get("body")),
            "url": c.get("html_url", ""), "note_id": c.get("id"),
            "replies": [{"author": (r.get("user") or {}).get("login", ""), "body": _txt(r.get("body"), 1500), "created": r.get("created_at", "")}
                        for r in sorted(replies.get(c.get("id"), []), key=lambda x: x.get("created_at", ""))][:20],
        })
    latest = {}
    for r in reviews or []:
        u = (r.get("user") or {}).get("login", "")
        if r.get("state") in ("APPROVED", "CHANGES_REQUESTED", "DISMISSED"):
            latest[u] = r
    for u, r in latest.items():
        if r.get("state") == "CHANGES_REQUESTED" and (r.get("body") or "").strip():
            out.append({"id": "ghr:%s" % r.get("id"), "kind": "review", "file": "", "old_file": "", "line": None, "side": "", "range": "",
                        "sha": r.get("commit_id") or "", "outdated": bool(r.get("commit_id") and head_sha and r.get("commit_id") != head_sha),
                        "resolved": None, "author": u, "created": r.get("submitted_at", ""), "body": _txt(r.get("body")),
                        "url": r.get("html_url", ""), "note_id": r.get("id"), "replies": []})
    return out


def where(t):
    if not t["file"]:
        return "allgemein" if t["kind"] != "review" else "Review «Änderungen angefordert»"
    s = t["file"]
    if t.get("line"):
        s += ":%s" % (t["range"] or t["line"])
        if t.get("side") == "alt":
            s += " (alte Fassung)"
    if t.get("old_file"):
        s += " (vorher %s)" % t["old_file"]
    return s


def _quote(text):
    return "\n".join("> " + ln if ln.strip() else ">" for ln in (text or "").splitlines()) or ">"


def topics_block(mr, topics):
    """Die Punkte als Markdown, jeder Kommentar als Zitat."""
    out = []
    for i, t in enumerate(topics, 1):
        state = {False: "offen", None: "Status unbekannt"}.get(t.get("resolved"), "offen")
        head = "### Punkt %d: %s" % (i, where(t))
        meta = ["von @%s" % t["author"] if t["author"] else "", (t.get("created") or "")[:10], state]
        if t.get("sha"):
            meta.append("Kommentar auf %s%s" % (t["sha"][:10], " (älterer Stand, Zeile kann sich verschoben haben)" if t.get("outdated") else ""))
        if t.get("url"):
            meta.append(t["url"])
        out.append(head + "\n" + ", ".join(m for m in meta if m) + "\n" + _quote(t["body"]))
        for r in t.get("replies") or []:
            out.append("Antwort von @%s:\n%s" % (r["author"], _quote(r["body"])))
    return "\n\n".join(out)


def context(mr):
    return {"mr_ref": ("PR #%s" if mr.get("host") == "github" else "MR !%s") % mr.get("iid"), "title": mr.get("title", ""),
            "project": mr.get("project", ""), "branch": mr.get("branch", ""), "target_branch": mr.get("target_branch") or "?",
            "sha": (mr.get("sha") or "")[:12] or "?", "url": mr.get("url", "")}


def to_markdown(mr, topics, template, extra=None):
    """Prompt aus prompts/review-topics.md. extra: z. B. workspace_line und tools für einen Agenten."""
    class D(dict):
        def __missing__(self, k):
            return ""
    vals = D(context(mr), count=len(topics), topics=topics_block(mr, topics))
    vals.update(extra or {})
    return re.sub(r"\n{3,}", "\n\n", template.format_map(vals)).strip() + "\n"


def to_json(mr, topics, data_class=""):
    m = {k: mr.get(k) for k in ("host", "project", "project_id", "iid", "title", "url", "branch", "target_branch", "sha")}
    m["data_class"] = data_class
    return {"schema": SCHEMA, "exported": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "mr": m,
            "topics": [{k: t.get(k) for k in ("id", "kind", "file", "old_file", "line", "range", "side", "sha", "outdated", "resolved",
                                               "author", "created", "body", "url", "replies")} | {"where": where(t)} for t in topics]}


def dumps(obj):
    return json.dumps(obj, ensure_ascii=False, indent=1)
