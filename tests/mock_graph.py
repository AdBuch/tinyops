"""Kleiner Ersatz für login.microsoftonline.com und graph.microsoft.com (nur, was tinyops braucht)."""
import json
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ME = {"id": "u-me", "displayName": "Adrian Test", "mail": "adrian@firma.example", "userPrincipalName": "adrian@firma.example"}


def iso(ts):
    return time.strftime("%Y-%m-%dT%H:%M:%S.0000000", time.gmtime(ts))


class State:
    def __init__(self):
        self.calls, self.events_created, self.refresh_tokens = [], [], []
        self.device_polls = 0
        self.refresh_ok = True


def make(state, now):
    def mail(i, frm, to, subj, ago_h, read=False, verb=None, flag=False, conv=None):
        m = {"id": "m%d" % i, "subject": subj, "from": {"emailAddress": {"address": frm, "name": frm.split("@")[0].title()}},
             "toRecipients": [{"emailAddress": {"address": a}} for a in to], "receivedDateTime": iso(now - ago_h * 3600) + "Z", "isRead": read,
             "flag": {"flagStatus": "flagged" if flag else "notFlagged"}, "webLink": "https://outlook.example/%d" % i, "importance": "normal",
             "bodyPreview": "Text %d" % i, "conversationId": conv or "c%d" % i}
        if verb is not None:
            m["singleValueExtendedProperties"] = [{"id": "Integer 0x1081", "value": str(verb)}]
        return m
    inbox = [mail(1, "mara@firma.example", ["adrian@firma.example"], "Frage zu DLP-120", 3),
             mail(2, "lea@firma.example", ["adrian@firma.example"], "Schon beantwortet", 5, read=True, verb=102),
             mail(3, "team@firma.example", ["dlp-team@firma.example"], "Nur in Kopie über Verteiler", 2),
             mail(4, "no-reply@jira.example", ["adrian@firma.example"], "[JIRA] DLP-1 updated", 1),
             mail(5, "adrian@firma.example", ["mara@firma.example"], "Von mir", 1, read=True),
             mail(6, "nico@firma.example", ["adrian@firma.example"], "Re: Frage zu DLP-120", 1, conv="c1")]
    flagged = [mail(7, "einkauf@firma.example", ["adrian@firma.example"], "Offerte", 90, read=True, flag=True)]
    d0 = now - (now % 86400)

    def ev(i, start, mins, subj, **k):
        e = {"id": "e%d" % i, "subject": subj, "start": {"dateTime": iso(start), "timeZone": "UTC"}, "end": {"dateTime": iso(start + mins * 60), "timeZone": "UTC"},
             "isAllDay": False, "isCancelled": False, "showAs": "busy", "location": {"displayName": "Raum 1"}, "isOnlineMeeting": True,
             "onlineMeeting": {"joinUrl": "https://teams.example/j%d" % i}, "webLink": "https://outlook.example/e%d" % i, "responseStatus": {"response": "accepted"},
             "organizer": {"emailAddress": {"address": "mara@firma.example", "name": "Mara"}}, "categories": []}
        e.update(k)
        return e
    events = [ev(1, now - 7200, 60, "Refinement DLP-120"), ev(2, now + 600, 30, "Daily"), ev(3, now - 3600, 30, "Abgesagt", isCancelled=True),
              ev(4, now - 5400, 30, "Abgelehnt", responseStatus={"response": "declined"}), ev(5, now + 3600, 50, "Fokus: alt", categories=["tinyops"])]
    chats = [{"id": "c1", "topic": None, "chatType": "oneOnOne", "webUrl": "https://teams.example/c1", "viewpoint": {"lastMessageReadDateTime": iso(now - 7200) + "Z"},
              "lastMessagePreview": {"createdDateTime": iso(now - 600) + "Z", "from": {"user": {"id": "u-nico", "displayName": "Nico"}}, "body": {"content": "<p>Pipeline&nbsp;grün</p>"}}},
             {"id": "c2", "topic": "DLP Dev", "chatType": "group", "webUrl": "https://teams.example/c2", "viewpoint": {"lastMessageReadDateTime": iso(now) + "Z"},
              "lastMessagePreview": {"createdDateTime": iso(now - 600) + "Z", "from": {"user": {"id": "u-nico", "displayName": "Nico"}}, "body": {"content": "gelesen"}}},
             {"id": "c3", "topic": "Ich", "chatType": "group", "webUrl": "", "viewpoint": {},
              "lastMessagePreview": {"createdDateTime": iso(now - 60) + "Z", "from": {"user": {"id": "u-me", "displayName": "Adrian"}}, "body": {"content": "von mir"}}}]

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _json(self, code, obj):
            b = json.dumps(obj).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(b)))
            self.end_headers()
            self.wfile.write(b)

        def do_POST(self):
            n = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(n).decode()
            u = urllib.parse.urlparse(self.path)
            state.calls.append(("POST", u.path, raw))
            if u.path.endswith("/oauth2/v2.0/token"):
                f = dict(urllib.parse.parse_qsl(raw))
                if f.get("grant_type") == "authorization_code":
                    if f.get("code") != "good-code" or not f.get("code_verifier"):
                        return self._json(400, {"error": "invalid_grant", "error_description": "AADSTS70000: bad code\r\nTrace ID: x"})
                elif f.get("grant_type") == "refresh_token":
                    if not state.refresh_ok:
                        return self._json(400, {"error": "invalid_grant", "error_description": "AADSTS700082: expired"})
                    state.refresh_tokens.append(f.get("refresh_token"))
                elif f.get("grant_type", "").endswith("device_code"):
                    state.device_polls += 1
                    if state.device_polls < 2:
                        return self._json(400, {"error": "authorization_pending"})
                return self._json(200, {"access_token": "at-%d" % len(state.calls), "refresh_token": "rt-%d" % len(state.calls), "expires_in": 3600})
            if u.path.endswith("/oauth2/v2.0/devicecode"):
                return self._json(200, {"device_code": "dc", "user_code": "ABCD-EFGH", "verification_uri": "https://microsoft.com/devicelogin", "expires_in": 60, "interval": 0})
            if u.path == "/v1.0/me/events":
                if not self.headers.get("Authorization", "").startswith("Bearer at-"):
                    return self._json(401, {"error": {"message": "no"}})
                state.events_created.append(json.loads(raw))
                return self._json(201, {"id": "new", "webLink": "https://outlook.example/new"})
            return self._json(404, {})

        def do_GET(self):
            u = urllib.parse.urlparse(self.path)
            q = urllib.parse.parse_qs(u.query)
            state.calls.append(("GET", u.path, u.query))
            if not self.headers.get("Authorization", "").startswith("Bearer at-"):
                return self._json(401, {"error": {"code": "InvalidAuthenticationToken", "message": "Access token is empty."}})
            if u.path == "/v1.0/me":
                return self._json(200, ME)
            if u.path == "/v1.0/me/mailFolders/inbox/messages":
                assert "receivedDateTime ge" in q["$filter"][0] and "0x1081" in q["$expand"][0]
                return self._json(200, {"value": inbox})
            if u.path == "/v1.0/me/messages":
                return self._json(200, {"value": flagged})
            if u.path == "/v1.0/me/calendarView":
                assert q.get("startDateTime") and self.headers.get("Prefer") == 'outlook.timezone="UTC"'
                return self._json(200, {"value": events})
            if u.path == "/v1.0/me/chats":
                return self._json(403, {"error": {"code": "Forbidden", "message": "Missing scope Chat.Read"}}) if getattr(state, "chats_forbidden", False) else self._json(200, {"value": chats})
            return self._json(404, {"error": {"message": "unbekannt"}})
    return H


def start(now=None):
    st = State()
    srv = ThreadingHTTPServer(("127.0.0.1", 0), make(st, now or time.time()))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, st, "http://127.0.0.1:%d" % srv.server_address[1]
