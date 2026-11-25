"""Offenlegen (0.42, Entscheid vom 20.11.): jeder Aufruf, den tinyops nach aussen macht, steht hier.

CALLS ist die Liste dessen, was tinyops aufrufen darf und wozu. Jede Stelle im Code, die eine Verbindung nach aussen öffnet,
meldet den Aufruf mit `record()`; tests/test_v42.py prüft, dass es keine Stelle daran vorbei gibt und dass jeder Pfad im Code
in CALLS vorkommt. Die Einstellungsseite zeigt die Liste mit Zählern seit dem Start (nur im Speicher, nie mit Inhalten).
Ein Aufruf, der nicht in CALLS steht, erscheint dort rot als «nicht in der Liste» und im Log als Warnung."""
import re
import threading
import time
import urllib.parse

import tlog

log = tlog.get("tinyops")

N = r"[^/]+"           # eine Kennung im Pfad (Zahl, Key, Name)
# (Dienst, Methode, Pfad wie angezeigt, Muster für das Ende des Pfads, wozu, schreibt?, wann, Zugang)
_RAW = (
    # GitLab: nur lesend, Token mit Scope read_api
    ("GitLab", "GET", "/user", r"/user", "wer du bist (Name, Mail-Adressen für «deine» Branches)", False, "beim Auffrischen", "gitlab_token"),
    ("GitLab", "GET", "/merge_requests", r"/merge_requests", "deine MRs und MRs, bei denen du Reviewer bist", False, "beim Auffrischen", "gitlab_token"),
    ("GitLab", "GET", "/projects/:id", r"/projects/%s" % N, "Projekt: Hauptbranch, Klon-Adressen", False, "beim Auffrischen, beim Klonen", "gitlab_token"),
    ("GitLab", "GET", "/projects/:id/merge_requests", r"/projects/%s/merge_requests" % N, "offene MRs je Projekt", False, "beim Auffrischen", "gitlab_token"),
    ("GitLab", "GET", "/projects/:id/merge_requests/:iid", r"/projects/%s/merge_requests/\d+" % N, "ein MR (Commit, Status)", False, "beim Auffrischen, auf Klick", "gitlab_token"),
    ("GitLab", "GET", "/projects/:id/merge_requests/:iid/{approvals,reviewers,commits,discussions}",
     r"/projects/%s/merge_requests/\d+/(approvals|reviewers|commits|discussions)" % N, "Freigaben, Reviewer, Commits, offene Punkte", False, "beim Auffrischen, auf Klick", "gitlab_token"),
    ("GitLab", "GET", "/projects/:id/pipelines", r"/projects/%s/pipelines" % N, "letzte Pipeline je Branch", False, "beim Auffrischen", "gitlab_token"),
    ("GitLab", "GET", "/projects/:id/environments", r"/projects/%s/environments" % N, "Review-App eines Branches", False, "beim Auffrischen", "gitlab_token"),
    ("GitLab", "GET", "/projects/:id/repository/{branches,compare,commits}", r"/projects/%s/repository/(branches|compare|commits)" % N,
     "deine Branches und ihre Commits", False, "beim Auffrischen", "gitlab_token"),
    ("GitLab", "GET", "/projects", r"/projects", "Projekte zur Auswahl", False, "Einstellungen: Verbindung testen", "gitlab_token"),
    ("GitLab", "GET", "/version, /personal_access_tokens/self", r"/(version|personal_access_tokens/self)", "Version und Rechte des Tokens", False, "Einstellungen: Verbindung testen", "gitlab_token"),
    # GitLab Review-Entwürfe (E14): eigenes Token, nur diese Pfade (siehe gitlab_review.ALLOWED)
    ("GitLab (Review)", "GET", "/projects/:id/merge_requests/:iid{,/versions,/versions/:v}", r"/projects/\d+/merge_requests/\d+(/versions(/\d+)?)?",
     "MR und Diff-Versionen, um Befunde an die richtige Zeile zu setzen", False, "auf Klick «Entwürfe in GitLab anlegen»", "gitlab_review_token"),
    ("GitLab (Review)", "GET", "/projects/:id/merge_requests/:iid/draft_notes", r"/projects/\d+/merge_requests/\d+/draft_notes",
     "deine Entwürfe (nur deine sind sichtbar)", False, "auf Klick", "gitlab_review_token"),
    ("GitLab (Review)", "POST", "/projects/:id/merge_requests/:iid/draft_notes", r"/projects/\d+/merge_requests/\d+/draft_notes",
     "Entwurf anlegen (nur du siehst ihn, bis du in GitLab abschickst)", True, "auf Klick", "gitlab_review_token"),
    ("GitLab (Review)", "DELETE", "/projects/:id/merge_requests/:iid/draft_notes/:id", r"/projects/\d+/merge_requests/\d+/draft_notes/\d+",
     "eigenen Entwurf von tinyops ersetzen", True, "auf Klick", "gitlab_review_token"),
    # Jira
    ("Jira", "GET", "/search", r"/search", "deine Tickets in Arbeit, Stories, Begleittickets", False, "beim Auffrischen", "jira_token"),
    ("Jira", "GET", "/issue/:key", r"/issue/%s" % N, "ein Ticket: Beschreibung, Kriterien, Kommentare", False, "auf Klick (Auftrag, Prüfliste)", "jira_token"),
    ("Jira", "GET", "/field", r"/field", "Feld-ID des Sprints", False, "einmal nach dem Start", "jira_token"),
    ("Jira", "POST", "/issue", r"/issue", "Ticket anlegen", True, "nur auf Klick und mit Bestätigung", "jira_token"),
    ("Jira", "GET", "/myself, /serverInfo, /project, /issuetype, /status", r"/(myself|serverInfo|project(/%s)?|issuetype|status)" % N,
     "Anmeldung, Version, Projekte, Typen", False, "Einstellungen: Verbindung testen", "jira_token"),
    # Helpdesk (zweites Jira, nur lesend)
    ("Helpdesk", "GET", "/search", r"/search", "Tickets dir, der Queue, beobachtet", False, "beim Auffrischen", "helpdesk_token"),
    ("Helpdesk", "GET", "/issue/:key", r"/issue/%s" % N, "ein Helpdesk-Ticket mit Kommentaren", False, "auf Klick", "helpdesk_token"),
    ("Helpdesk", "GET", "/field, /myself, /serverInfo", r"/(field|myself|serverInfo)", "Felder, Anmeldung", False, "Einstellungen, einmal nach dem Start", "helpdesk_token"),
    # GitHub: nur lesend
    ("GitHub", "GET", "/user, /user/repos, /search/issues", r"/(user|user/repos|search/issues)", "wer du bist, deine Repos, deine PRs", False, "beim Auffrischen", "github_token"),
    ("GitHub", "GET", "/repos/:owner/:repo/…", r"/repos/%s/%s(/.*)?" % (N, N), "Repo, Branches, PRs, Checks, Reviews", False, "beim Auffrischen", "github_token"),
    # Sonar: nur lesend
    ("Sonar", "GET", "/api/{issues,hotspots}/search", r"/api/(issues|hotspots)/search", "Findings je Branch und MR", False, "beim Auffrischen, «Report»", "sonar_token"),
    ("Sonar", "GET", "/api/{qualitygates,measures,project_pull_requests}/…", r"/api/(qualitygates/project_status|measures/search_history|project_pull_requests/list)",
     "Quality Gate, Verlauf, MRs", False, "beim Auffrischen", "sonar_token"),
    ("Sonar", "GET", "/api/{authentication,system,components}/…", r"/api/(authentication/validate|system/status|components/show)", "Anmeldung, Version, Projekt", False,
     "Einstellungen: Verbindung testen", "sonar_token"),
    # BCS-Middleware (eigener Rechner oder LAN)
    ("BCS", "GET", "/api/v1/{days,overviews,booking-targets,suggestions,reports}/…", r"/api/v1/(days/%s|overviews|booking-targets|suggestions|reports/[a-z-]+)" % N,
     "Buchungen, Aufgaben, Saldo", False, "Zeit-Ansicht, auf Klick", "bcs_token"),
    ("BCS", "POST", "/api/v1/drafts/preview", r"/api/v1/drafts/preview", "Buchungen prüfen (bucht nichts)", False, "auf Klick «In BCS prüfen»", "bcs_token"),
    ("BCS", "POST", "/api/v1/drafts/commit", r"/api/v1/drafts/commit", "Buchungen eintragen", True, "nur auf Klick «In BCS buchen», nie wiederholt", "bcs_token"),
    # Lokales Modell (nur im eigenen Netz, ausser allow_remote)
    ("LLM", "GET", "/api/tags, /v1/models, /models", r"/(api/tags|v1/models|models)", "verfügbare Modelle", False, "Einstellungen, Kopfzeile", "llm_key"),
    ("LLM", "POST", "/api/chat, /v1/chat/completions", r"/(api/chat|v1/chat/completions|chat/completions)", "Text erzeugen (Entwurf, Bewertung, Zeittexte)", False,
     "auf Klick", "llm_key"),
    # Spracherkennung (0.43): nur im eigenen Netz, ausser allow_remote; nur auf deinen Klick am Mikrofon
    ("Spracherkennung", "POST", "/v1/audio/transcriptions, /inference", r"/(v1/audio/transcriptions|inference)", "gesprochenen Text erkennen (Aufnahme geht nur dorthin, wird nicht gespeichert)",
     False, "auf Klick am Mikrofon, Einstellungen: Testen", "voice_key (optional)"),
    # Microsoft 365 (delegiert, ohne Client-Secret)
    ("Microsoft 365", "POST", "login: /:tenant/oauth2/v2.0/{token,devicecode}", r"/%s/oauth2/v2\.0/(token|devicecode)" % N, "anmelden, Zugang erneuern", False,
     "Anmelden, stündlich", "m365_refresh"),
    ("Microsoft 365", "GET", "/me, /me/calendarView, /me/mailFolders/inbox/messages, /me/messages, /me/chats", r"/me(/calendarView|/mailFolders/inbox/messages|/messages|/chats)?",
     "Termine heute, Mails an dich, ungelesene Chats", False, "beim Auffrischen", "m365_refresh"),
    ("Microsoft 365", "POST", "/me/events", r"/me/events", "Fokuszeit im Kalender eintragen", True, "nur wenn erlaubt, beim Start einer Fokus-Sitzung", "m365_refresh"),
    # KI-Kontingent (Anbieter der Agenten)
    ("KI-Kontingent", "GET", "Claude /api/oauth/usage, Codex /backend-api/wham/usage", r"/(api/oauth/usage|backend-api/wham/usage)", "Kontingent der KI-Abos", False,
     "Kopfzeile, höchstens alle paar Minuten", "Token der CLI auf diesem Rechner"),
    # Update
    ("Update", "GIT", "git ls-remote --tags", r"ls-remote", "neue Release-Tags", False, "höchstens alle 6 Stunden", "keiner (öffentliches Repo)"),
)
CALLS = tuple({"svc": s, "method": m, "path": p, "rx": re.compile("(^|/)" + rx.lstrip("/") + "$"), "what": w, "write": wr, "when": wh, "token": t}
              for s, m, p, rx, w, wr, wh, t in _RAW)
SERVICES = tuple(dict.fromkeys(c["svc"] for c in CALLS))

_lock = threading.Lock()
_seen = {}              # Index in CALLS oder ("?", Dienst, Methode, Pfad) → [Anzahl, zuletzt]


def find(svc, method, path):
    path = urllib.parse.urlparse(path).path if "://" in path else path.split("?", 1)[0]
    for i, c in enumerate(CALLS):
        if c["svc"] == svc and c["method"] == method and c["rx"].search(path):
            return i
    return None


def _norm(path):
    path = urllib.parse.urlparse(path).path if "://" in path else path.split("?", 1)[0]
    return re.sub(r"/(\d+|[A-Z][A-Z0-9_]+-\d+|[0-9a-f]{12,40})(?=/|$)", "/:id", path)[:200]


def record(svc, method, path):
    """Ein Aufruf nach aussen. Zählt nur (kein Inhalt, keine Parameter)."""
    i = find(svc, method, path)
    key = i if i is not None else ("?", svc, method, _norm(path))
    if i is None:
        log.warning("Aufruf nicht in der Liste (apicalls.CALLS): %s %s %s", svc, method, key[3])
    with _lock:
        e = _seen.setdefault(key, [0, 0.0])
        e[0] += 1
        e[1] = time.time()


def view():
    """Für die Einstellungsseite: alle erlaubten Aufrufe mit Zähler seit dem Start, dazu unbekannte."""
    with _lock:
        seen = {k: list(v) for k, v in _seen.items()}
    rows = [{"svc": c["svc"], "method": c["method"], "path": c["path"], "what": c["what"], "write": c["write"], "when": c["when"], "token": c["token"],
             "count": seen.get(i, [0, 0])[0], "last": seen.get(i, [0, 0])[1] or None} for i, c in enumerate(CALLS)]
    rows += [{"svc": k[1], "method": k[2], "path": k[3], "what": "nicht in der Liste", "write": k[2] not in ("GET", "GIT"), "when": "", "token": "",
              "count": v[0], "last": v[1], "unknown": True} for k, v in seen.items() if isinstance(k, tuple)]
    return {"rows": rows, "since": _START}


def reset():
    with _lock:
        _seen.clear()


_START = time.time()
