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

    def _get(self, path, params):
        try:
            return net.probe(self.base + path + "?" + urllib.parse.urlencode(params), headers(self.token), self.ctx, timeout=self.timeout)
        except net.NetError as e:
            raise SonarError("Sonar nicht erreichbar (%s)" % e.detail)

    def dashboard_url(self, key, pr=None, branch=None):
        q = {"id": key}
        if pr:
            q["pullRequest"] = str(pr)
        elif branch:
            q["branch"] = branch
        return "%s/dashboard?%s" % (self.base, urllib.parse.urlencode(q))

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
            return {"status": "NONE", "failed": [], "url": self.dashboard_url(key, pr, branch), "detail": "keine Analyse für %s" % (("MR !%s" % pr) if pr else branch or "Hauptbranch")}
        if st != 200:
            raise SonarError("Sonar: HTTP %d" % st)
        data = net.parse_json(resp)
        ps = (data or {}).get("projectStatus")
        if not isinstance(ps, dict):
            raise SonarError("Sonar: unerwartete Antwort (kein SonarQube unter dieser Adresse?)")
        status = ps.get("status") if ps.get("status") in STATUS_LABEL else "NONE"
        failed = [describe(c) for c in ps.get("conditions") or [] if c.get("status") in ("ERROR", "WARN")]
        return {"status": status, "failed": failed, "url": self.dashboard_url(key, pr, branch),
                "detail": "; ".join(failed) if failed else STATUS_LABEL[status]}
