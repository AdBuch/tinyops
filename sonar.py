"""SonarQube, nur lesend: Quality Gate pro Merge Request und Branch.

Es gibt keinen Schreibzugriff. Anmeldung mit einem Benutzer-Token (als Benutzername, Passwort leer), das funktioniert in allen Versionen.
Merge Requests werden über «pullRequest» (die MR-Nummer, wie sie die GitLab-Anbindung von Sonar vergibt) abgefragt, Branches über «branch».
Beides gibt es erst ab der Developer Edition; in der Community Edition liefert Sonar nur den Hauptbranch, alles andere erscheint als «keine Analyse».
"""
import base64
import json
import urllib.parse

import net
import secretstore as store

STATUS_LABEL = {"OK": "bestanden", "WARN": "Warnung", "ERROR": "nicht bestanden", "NONE": "keine Analyse"}

METRIC_LABEL = {
    "new_coverage": "Abdeckung neuer Code", "coverage": "Abdeckung",
    "new_duplicated_lines_density": "Duplikate neuer Code", "duplicated_lines_density": "Duplikate",
    "new_violations": "Neue Verstösse", "new_bugs": "Neue Bugs", "new_vulnerabilities": "Neue Schwachstellen",
    "new_code_smells": "Neue Code Smells", "new_security_hotspots_reviewed": "Security Hotspots geprüft",
    "new_security_rating": "Sicherheit neuer Code", "new_reliability_rating": "Zuverlässigkeit neuer Code",
    "new_maintainability_rating": "Wartbarkeit neuer Code", "security_rating": "Sicherheit", "reliability_rating": "Zuverlässigkeit",
    "sqale_rating": "Wartbarkeit", "bugs": "Bugs", "vulnerabilities": "Schwachstellen", "code_smells": "Code Smells",
    "new_security_hotspots_reviewed_status": "Security Hotspots geprüft",
}
RATING = {"1.0": "A", "2.0": "B", "3.0": "C", "4.0": "D", "5.0": "E", "1": "A", "2": "B", "3": "C", "4": "D", "5": "E"}
COMPARATOR = {"LT": "mindestens", "GT": "höchstens", "EQ": "genau", "NE": "nicht"}


class SonarError(Exception):
    """Meldung ist für den Anwender gedacht. `auth` heisst: Zugangsdaten falsch, alle weiteren Abfragen sind sinnlos."""
    def __init__(self, msg, auth=False):
        super().__init__(msg)
        self.auth = auth


def headers(token):
    raw = base64.b64encode(("%s:" % token).encode("utf-8")).decode("ascii")
    return {"Authorization": "Basic " + raw, "Accept": "application/json"}


def _num(v):
    try:
        f = float(v)
        return ("%.1f" % f).rstrip("0").rstrip(".")
    except (TypeError, ValueError):
        return str(v)


def describe(cond):
    """Eine fehlgeschlagene Bedingung als Satz: «Abdeckung neuer Code 61.2 % (mindestens 80 %)»."""
    key = cond.get("metricKey", "")
    label = METRIC_LABEL.get(key, key.replace("_", " "))
    actual, limit = cond.get("actualValue"), cond.get("errorThreshold")
    if key.endswith("_rating"):
        return "%s %s (%s %s)" % (label, RATING.get(str(actual), actual), COMPARATOR.get(cond.get("comparator"), ""), RATING.get(str(limit), limit))
    unit = " %" if ("coverage" in key or "density" in key or key.endswith("reviewed")) else ""
    return "%s %s%s (%s %s%s)" % (label, _num(actual), unit, COMPARATOR.get(cond.get("comparator"), ""), _num(limit), unit)


class Client:
    def __init__(self, base, token, ctx=None, timeout=15):
        self.base, self.token, self.ctx, self.timeout = base.rstrip("/"), token, ctx, timeout
        store.register(token)

    def _get(self, path, params, max_body=262144):
        try:
            return net.probe(self.base + path + "?" + urllib.parse.urlencode(params), headers(self.token), self.ctx, timeout=self.timeout, max_body=max_body)
        except net.NetError as e:
            raise SonarError("Sonar nicht erreichbar (%s)" % e.detail)

    def dashboard_url(self, key, pr=None, branch=None):
        q = {"id": key}
        if pr:
            q["pullRequest"] = str(pr)
        elif branch:
            q["branch"] = branch
        return "%s/dashboard?%s" % (self.base, urllib.parse.urlencode(q))

    def _scope(self, key, pr=None, branch=None, id_name="id"):
        q = {id_name: key}
        if pr:
            q["pullRequest"] = str(pr)
        elif branch:
            q["branch"] = branch
        return q

    def issues_url(self, key, pr=None, branch=None):
        q = self._scope(key, pr, branch)
        q["resolved"] = "false"
        return "%s/project/issues?%s" % (self.base, urllib.parse.urlencode(q))

    def hotspots_url(self, key, pr=None, branch=None):
        return "%s/security_hotspots?%s" % (self.base, urllib.parse.urlencode(self._scope(key, pr, branch)))

    def issues(self, key, pr=None, branch=None, limit=200):
        """Offene Findings (nur lesen). Gibt (liste, gesamt, facetten) zurück; höchstens `limit` Einträge, in Sonar-Reihenfolge nach Schwere."""
        out, total, facets, page = [], 0, {}, 1
        while len(out) < limit:
            params = self._scope(key, pr, branch, "componentKeys")
            params.update({"resolved": "false", "ps": str(min(100, limit - len(out))), "p": str(page), "s": "SEVERITY", "asc": "false",
                           "facets": "severities,types"})
            resp = self._get("/api/issues/search", params, max_body=4 << 20)
            st = resp["status"]
            if st in (401, 403):
                raise SonarError("Sonar: Anmeldung abgelehnt (HTTP %d)." % st, auth=True)
            if st == 404:
                return [], 0, {}
            if st != 200:
                raise SonarError("Sonar: Findings nicht lesbar (HTTP %d)" % st)
            d = net.parse_json(resp) or {}
            batch = d.get("issues") or []
            total = int((d.get("paging") or {}).get("total", len(batch)))
            if page == 1:
                for f in d.get("facets") or []:
                    facets[f.get("property")] = {v.get("val"): v.get("count") for v in f.get("values") or []}
            out.extend(batch)
            if not batch or len(out) >= total:
                break
            page += 1
        return out[:limit], total, facets

    def hotspots(self, key, pr=None, branch=None, limit=100):
        """Security Hotspots zur Prüfung. Gibt (liste, gesamt) zurück oder None, wenn nicht lesbar (Berechtigung, Edition)."""
        params = self._scope(key, pr, branch, "projectKey")
        params.update({"status": "TO_REVIEW", "ps": str(limit)})
        resp = self._get("/api/hotspots/search", params, max_body=2 << 20)
        if resp["status"] != 200:
            return None
        d = net.parse_json(resp) or {}
        return d.get("hotspots") or [], int((d.get("paging") or {}).get("total", len(d.get("hotspots") or [])))

    def gate(self, key, pr=None, branch=None):
        """Quality Gate eines MR (pr) oder Branches. Gibt {status, failed[], url} zurück. Ohne Analyse: status NONE."""
        params = {"projectKey": key}
        if pr:
            params["pullRequest"] = str(pr)
        elif branch:
            params["branch"] = branch
        resp = self._get("/api/qualitygates/project_status", params)
        st = resp["status"]
        if st in (401, 403):
            raise SonarError("Sonar: Anmeldung abgelehnt (HTTP %d). Token prüfen, er braucht «Browse» auf dem Projekt." % st, auth=True)
        if st == 404:
            return {"status": "NONE", "failed": [], "url": self.dashboard_url(key, pr, branch), "issues_url": "", "detail": "keine Analyse für %s" % (("MR !%s" % pr) if pr else branch or "Hauptbranch")}
        if st != 200:
            raise SonarError("Sonar: HTTP %d" % st)
        data = net.parse_json(resp)
        ps = (data or {}).get("projectStatus")
        if not isinstance(ps, dict):
            raise SonarError("Sonar: unerwartete Antwort (kein SonarQube unter dieser Adresse?)")
        status = ps.get("status") if ps.get("status") in STATUS_LABEL else "NONE"
        failed = [describe(c) for c in ps.get("conditions") or [] if c.get("status") in ("ERROR", "WARN")]
        return {"status": status, "failed": failed, "url": self.dashboard_url(key, pr, branch),
                "issues_url": self.issues_url(key, pr, branch),
                "detail": "; ".join(failed) if failed else STATUS_LABEL[status]}


SEVERITY_ORDER = ["BLOCKER", "CRITICAL", "MAJOR", "MINOR", "INFO"]
TYPE_LABEL = {"BUG": "Bug", "VULNERABILITY": "Schwachstelle", "CODE_SMELL": "Code Smell", "SECURITY_HOTSPOT": "Hotspot"}


def _path(component, key):
    c = str(component or "")
    return c[len(key) + 1:] if c.startswith(key + ":") else c


def _line(txt, n=300):
    txt = " ".join(str(txt or "").split())
    return txt if len(txt) <= n else txt[:n - 1] + "…"


def format_report(title, gate, key, issues, total, facets, hotspots, link, limit):
    """Markdown für die Zwischenablage. Enthält Dateipfade, Zeilennummern, Regeln und Sonar-Meldungen, aber keinen Quelltext."""
    L = ["# Sonar-Findings: %s" % title, "", "Projekt `%s` · Quality Gate: **%s**" % (key, STATUS_LABEL.get(gate.get("status"), gate.get("status", "?")))]
    if link:
        L.append("Sonar: %s" % link)
    if gate.get("failed"):
        L += ["", "## Nicht erfüllte Bedingungen"] + ["- %s" % f for f in gate["failed"]]
    L += ["", "## Findings (%d offen)" % total]
    sev, typ = facets.get("severities") or {}, facets.get("types") or {}
    if sev:
        L.append("Schwere: " + ", ".join("%s %s" % (s.lower(), sev[s]) for s in SEVERITY_ORDER if sev.get(s)))
    if typ:
        L.append("Art: " + ", ".join("%s %s" % (TYPE_LABEL.get(t, t), n) for t, n in typ.items() if n))
    if not issues:
        L.append("Keine offenen Findings." if not total else "Keine Findings abrufbar.")
    by_file = {}
    for i in issues:
        by_file.setdefault(_path(i.get("component"), key), []).append(i)
    for path in sorted(by_file, key=lambda p: (min(SEVERITY_ORDER.index(i.get("severity")) if i.get("severity") in SEVERITY_ORDER else 9 for i in by_file[p]), p)):
        L += ["", "### `%s`" % path]
        for i in sorted(by_file[path], key=lambda x: x.get("line") or 0):
            L.append("- Zeile %s [%s, %s] `%s`: %s" % (i.get("line", "?"), (i.get("severity") or "?").lower(), TYPE_LABEL.get(i.get("type"), i.get("type") or "?"),
                                                    i.get("rule", "?"), _line(i.get("message"))))
    if total > len(issues):
        L += ["", "_Es werden %d von %d Findings gezeigt (nach Schwere sortiert). Den Rest gibt es in Sonar._" % (len(issues), total)]
    L += ["", "## Security Hotspots zur Prüfung"]
    if hotspots is None:
        L.append("Nicht lesbar (Berechtigung oder Edition).")
    elif not hotspots[0]:
        L.append("Keine.")
    else:
        for h in hotspots[0]:
            L.append("- `%s` Zeile %s [%s, %s]: %s" % (_path(h.get("component"), key), h.get("line", "?"), (h.get("vulnerabilityProbability") or "?").lower(),
                                                    h.get("securityCategory", "?"), _line(h.get("message"))))
        if hotspots[1] > len(hotspots[0]):
            L.append("_%d weitere in Sonar._" % (hotspots[1] - len(hotspots[0])))
    L += ["", "---", "Erzeugt von tinyops aus der Sonar-API (nur lesend). Enthält Pfade und Meldungen, keinen Quelltext."]
    return "\n".join(L) + "\n"
