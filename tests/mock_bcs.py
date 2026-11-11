"""Ersatz für die BCS-Middleware (Workflow-API /api/v1), nur was tinyops braucht."""
import json
import threading
import urllib.parse
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

TASKS = [{"id": "T-1", "name": "Entwicklung DLP", "path": ["Produkte", "DLP"], "favorite": True},
         {"id": "T-2", "name": "Berufsbildung", "path": ["Intern", "Berufsbildung"], "favorite": False}]


class State:
    def __init__(self):
        self.calls, self.entries, self.drafts = [], {}, {}
        self.token = ""
        self.mode = "ok"              # ok | dry_run | rejected | drop (Verbindung bricht beim commit ab, gebucht wird trotzdem) | drop_nothing


def make(st):
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _j(self, code, obj):
            b = json.dumps(obj).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(b)))
            self.end_headers()
            self.wfile.write(b)

        def _auth(self):
            if st.token and self.headers.get("Authorization") != "Bearer " + st.token:
                self._j(401, {"error": "Token fehlt oder ist ungültig"})
                return False
            return True

        def do_GET(self):
            u = urllib.parse.urlparse(self.path)
            q = dict(urllib.parse.parse_qsl(u.query))
            st.calls.append(("GET", u.path, q))
            if not self._auth():
                return
            if u.path.startswith("/api/v1/days/"):
                d = u.path.rsplit("/", 1)[1]
                ents = st.entries.setdefault(d, [])
                return self._j(200, {"date": d, "closedDate": None, "entries": ents, "absences": [], "issues": [{"message": "Pause fehlt"}],
                                     "totals": {"workMinutes": sum(e["durationMinutes"] for e in ents), "attendanceMinutes": 480, "pauseMinutes": 0, "unallocatedMinutes": 0}})
            if u.path == "/api/v1/overviews":
                return self._j(200, {"scope": q.get("scope"), "actualMinutes": 600, "targetMinutes": 2520, "days": []})
            if u.path == "/api/v1/booking-targets":
                return self._j(200, {"items": [t for t in TASKS if q["query"].lower() in t["name"].lower()]})
            if u.path == "/api/v1/suggestions":
                return self._j(200, {"daysRead": 5, "suggestions": [{"task": TASKS[0], "days": 3, "duration": 120}]})
            if u.path == "/api/v1/reports/apprentices":
                return self._j(200, {"configured": True, "members": [{"id": "a1", "name": "Lea"}]})
            if u.path == "/api/v1/reports/dashboard":
                return self._j(200, {"status": "available", "member": {"id": q.get("memberId"), "name": "Lea"}, "ytd": {"balanceMinutes": -30},
                                     "vacation": {"remainingDays": 9}, "currentWeek": {"days": [{"balanceMinutes": -10}, {"balanceMinutes": 25}]}})
            return self._j(404, {"error": "unbekannt"})

        def do_POST(self):
            u = urllib.parse.urlparse(self.path)
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
            st.calls.append(("POST", u.path, body))
            if not self._auth():
                return
            if u.path == "/api/v1/drafts/preview":
                bad = [i for i, c in enumerate(body["changes"]) if c.get("taskId") not in [t["id"] for t in TASKS]]
                if bad:
                    return self._j(200, {"status": "blocked", "draftId": None, "warnings": [{"index": bad[0], "message": "Aufgabe unbekannt", "candidates": TASKS}], "entries": []})
                did = str(uuid.uuid4())
                st.drafts[did] = body
                return self._j(200, {"status": "ready", "draftId": did, "entries": [], "deletions": [], "warnings": [], "expiresAt": "2099-01-01T00:00:00Z", "dryRun": st.mode == "dry_run"})
            if u.path == "/api/v1/drafts/commit":
                assert body.get("confirm") is True
                dr = st.drafts.pop(body["draftId"], None)
                if not dr:
                    return self._j(200, {"status": "invalid_draft", "message": "unbekannt"})
                if st.mode == "dry_run":
                    return self._j(200, {"status": "dry_run", "message": "nichts geschrieben"})
                if st.mode == "rejected":
                    return self._j(200, {"status": "rejected", "message": "Tag ist abgeschlossen"})
                if st.mode != "drop_nothing":
                    for i, c in enumerate(dr["changes"]):
                        st.entries.setdefault(dr["date"], []).append({"id": "e%d" % i, "kind": "work", "durationMinutes": c["durationMinutes"], "description": c["description"],
                                                                      "task": next(t for t in TASKS if t["id"] == c["taskId"])})
                if st.mode in ("drop", "drop_nothing"):
                    self.close_connection = True
                    self.connection.shutdown(2)        # Antwort geht verloren: unklar, ob gebucht
                    return
                return self._j(200, {"status": "committed", "message": "%d gespeichert" % len(dr["changes"]), "entries": st.entries[dr["date"]]})
            return self._j(404, {"error": "unbekannt"})
    return H


def start():
    st = State()
    srv = ThreadingHTTPServer(("127.0.0.1", 0), make(st))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, st, "http://127.0.0.1:%d" % srv.server_address[1]
