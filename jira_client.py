"""Jira lesen und, nur mit Freigabe, Tickets anlegen (0.37 aus server.py gelöst)."""
import base64
import urllib.parse

import briefing
import groups
import secretstore as store
import sprint
import tlog
from common import HttpStatus, UserError, hours_since
from httpclient import Http

jlog = tlog.get("jira")


class JiraClient:
    def __init__(self, jc, auth_header, ctx):
        self.jc = jc
        self.base = jc["url"].rstrip("/")
        self.http = Http("Jira", self.base + "/rest/api/2",
                         {"Authorization": auth_header, "Accept": "application/json"}, ctx)
        self._sf = None   # Feld-ID des Sprint-Feldes; "" = es gibt keines

    def sprint_field(self):
        if self._sf is None:
            self._sf = ""
            try:
                for f in self.http.get("/field"):
                    if f.get("name") == "Sprint" and "gh-sprint" in str((f.get("schema") or {}).get("custom", "")):
                        self._sf = f["id"]
                        break
                jlog.info("Sprint-Feld: %s", self._sf or "nicht gefunden (kein Jira Software?)")
            except UserError as e:
                jlog.warning("Sprint-Feld nicht lesbar: %s", e)
        return self._sf

    def _fields(self):
        sf = self.sprint_field()
        return ["summary", "status", "issuetype", "issuelinks", "parent"] + ([sf] if sf else [])

    def _issue(self, i):
        f = i.get("fields") or {}
        out = {
            "key": i["key"], "summary": f.get("summary", ""),
            "status": (f.get("status") or {}).get("name", ""),
            "type": (f.get("issuetype") or {}).get("name", ""),
            "url": self.base + "/browse/" + i["key"],
            "sprint": "", "sprint_end": "", "in_sprint": None,
            "links": groups.links_of(f), "parent": (f.get("parent") or {}).get("key", ""),
        }
        if self._sf:
            act = sprint.active_sprint(f.get(self._sf))
            out["in_sprint"] = bool(act)
            if act:
                out["sprint"], out["sprint_end"] = act["name"], act["end"]
        return out

    def _search(self, jql, fields, limit=100):
        res = self.http.get("/search", {"jql": jql, "fields": ",".join(fields), "maxResults": limit})
        return res.get("issues", []), int(res.get("total", 0))

    def brief(self, key):
        """Ein Ticket für den Auftrag an einen Agenten: Beschreibung und die letzten Kommentare. Nur GET."""
        d = self.http.get("/issue/" + urllib.parse.quote(key), {"fields": "summary,status,issuetype,description,comment"})
        f = d.get("fields") or {}
        rows = (f.get("comment") or {}).get("comments") or []
        return {"title": f.get("summary") or "", "kind": (f.get("issuetype") or {}).get("name", ""), "status": (f.get("status") or {}).get("name", ""),
                "description": f.get("description") or "", "url": self.base + "/browse/" + key,
                "comments": [{"author": (c.get("author") or {}).get("displayName", ""), "body": c.get("body") or ""} for c in rows[-briefing.MAX_COMMENTS:]][::-1]}

    def jql_in_progress(self):
        return sprint.effective_jql(self.jc["jql_in_progress"], self.jc.get("only_active_sprints", True))

    def in_progress(self):
        fields = self._fields()
        jql = self.jql_in_progress()
        jlog.debug("JQL in Arbeit: %s", jql)
        issues, _ = self._search(jql, fields)
        out = [self._issue(i) for i in issues]
        if self.jc.get("only_active_sprints", True):
            for o in out:
                o["in_sprint"] = True   # die JQL hat es schon geprüft
        return out

    def lookup(self, keys):
        """Einzelabfragen: ein unbekannter Key bricht sonst die ganze JQL-Suche ab."""
        out = {}
        for key in keys[:60]:
            try:
                out[key] = self._issue(self.http.get("/issue/" + urllib.parse.quote(key),
                                                     {"fields": ",".join(self._fields())}))
            except HttpStatus as e:
                if e.code in (400, 403, 404):
                    continue
                raise
        return out

    def helpdesk(self):
        h = self.jc.get("helpdesk") or {}
        if not h.get("jql"):
            return None
        issues, total = self._search(h["jql"], ["created", "summary"])
        ages = [hours_since((i.get("fields") or {}).get("created")) for i in issues]
        sla = float(h.get("sla_hours", 24))
        return {
            "open": total,
            "oldest_hours": int(max(ages)) if ages else 0,
            "over_hours": sum(1 for a in ages if a >= sla),
            "sla_hours": sla,
            "truncated": total > len(issues),
            "url": self.base + "/issues/?jql=" + urllib.parse.quote(h["jql"]),
        }

    def issue_types(self, project_key):
        """Erlaubte Vorgangstypen des Projekts (ohne Unteraufgaben)."""
        res = self.http.get("/project/" + urllib.parse.quote(project_key))
        return [t["name"] for t in res.get("issueTypes", []) if not t.get("subtask")]

    def create_issue(self, project_key, issue_type, summary, description):
        res = self.http.post_json("/issue", {"fields": {
            "project": {"key": project_key}, "issuetype": {"name": issue_type},
            "summary": summary, "description": description}})
        return {"key": res["key"], "url": "%s/browse/%s" % (self.base, res["key"])}

    def create_url(self, summary):
        pid, it = self.jc.get("create_pid"), self.jc.get("create_issuetype")
        if pid and it:
            return "%s/secure/CreateIssueDetails!init.jspa?pid=%s&issuetype=%s&summary=%s" % (
                self.base, urllib.parse.quote(str(pid)), urllib.parse.quote(str(it)),
                urllib.parse.quote(summary[:200]))
        return self.base + "/secure/CreateIssue!default.jspa"


def jira_auth_header(jc, secrets):
    auth = jc.get("auth", "bearer")
    if auth == "bearer":
        return "Bearer " + secrets["jira_token"]
    if auth == "basic":
        if not jc.get("username"):
            raise SystemExit("jira.username fehlt in der config.json (nötig bei auth = basic).")
        raw = base64.b64encode(("%s:%s" % (jc["username"], secrets["jira_password"])).encode("utf-8")).decode("ascii")
        store.register(raw)
        return "Basic " + raw
    raise SystemExit("jira.auth muss 'bearer' oder 'basic' sein.")
