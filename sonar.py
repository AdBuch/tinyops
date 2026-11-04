"""SonarQube, nur lesend: Quality Gate pro Merge Request und Branch.

Es gibt keinen Schreibzugriff. Anmeldung mit einem Benutzer-Token (als Benutzername, Passwort leer), das funktioniert in allen Versionen.
Merge Requests werden über «pullRequest» (die MR-Nummer, wie sie die GitLab-Anbindung von Sonar vergibt) abgefragt, Branches über «branch».
Beides gibt es erst ab der Developer Edition; in der Community Edition liefert Sonar nur den Hauptbranch, alles andere erscheint als «keine Analyse».
"""
import base64
import json
import urllib.parse
from datetime import datetime

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
    # Multi-Quality-Rule-Modus (SonarQube ab 10.8, Standard in 2026.1): Softwarequalitäten statt Bug/Schwachstelle/Smell
    "new_software_quality_security_rating": "Sicherheit neuer Code", "new_software_quality_reliability_rating": "Zuverlässigkeit neuer Code",
    "new_software_quality_maintainability_rating": "Wartbarkeit neuer Code", "software_quality_security_rating": "Sicherheit",
    "software_quality_reliability_rating": "Zuverlässigkeit", "software_quality_maintainability_rating": "Wartbarkeit",
    "new_software_quality_blocker_issues": "Neue Blocker-Findings", "new_software_quality_high_issues": "Neue Findings mit hoher Auswirkung",
    "new_software_quality_medium_issues": "Neue Findings mit mittlerer Auswirkung", "new_software_quality_low_issues": "Neue Findings mit geringer Auswirkung",
    "new_software_quality_info_issues": "Neue Info-Findings", "new_accepted_issues": "Neue akzeptierte Findings",
    "software_quality_blocker_issues": "Blocker-Findings", "software_quality_high_issues": "Findings mit hoher Auswirkung",
    "new_software_quality_security_issues": "Neue Sicherheits-Findings", "new_software_quality_reliability_issues": "Neue Zuverlässigkeits-Findings",
    "new_software_quality_maintainability_issues": "Neue Wartbarkeits-Findings",
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
                           "facets": "severities,types,impactSeverities,impactSoftwareQualities"})
            resp = self._get("/api/issues/search", params, max_body=4 << 20)
            if resp["status"] == 400:      # ältere Version kennt die Facetten des Multi-Quality-Rule-Modus nicht
                params["facets"] = "severities,types"
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

    def history(self, key, pr=None, branch=None, metrics=("violations",), limit=60):
        """Verlauf aus Sonar (api/measures/search_history), je Analyse ein Punkt: [{"ts", metric: zahl, ...}], alt nach neu.
        «new_*»-Kennzahlen speichert Sonar nicht historisch, deshalb nur die Bestandszahlen (bei MRs sind das die Findings des MR). Leer, wenn es nichts gibt."""
        params = self._scope(key, pr, branch, "component")
        params.update({"metrics": ",".join(metrics), "ps": "1000"})
        resp = self._get("/api/measures/search_history", params)
        st = resp["status"]
        if st in (401, 403):
            raise SonarError("Sonar: Anmeldung abgelehnt (HTTP %d)." % st, auth=True)
        if st in (400, 404):
            return []
        if st != 200:
            raise SonarError("Sonar: Verlauf nicht lesbar (HTTP %d)" % st)
        rows = {}
        for m in (net.parse_json(resp) or {}).get("measures") or []:
            for h in m.get("history") or []:
                try:
                    ts = datetime.fromisoformat(str(h["date"])).timestamp()
                    rows.setdefault(ts, {"ts": ts})[m["metric"]] = float(h["value"])
                except (KeyError, TypeError, ValueError):
                    continue
        return [rows[t] for t in sorted(rows)][-limit:]

    def pull_requests(self, key):
        """Analysierte Pull Requests eines Projekts (Developer Edition und höher). None, wenn nicht verfügbar."""
        resp = self._get("/api/project_pull_requests/list", {"project": key})
        if resp["status"] != 200:
            return None
        return (net.parse_json(resp) or {}).get("pullRequests") or []

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
        values = {}
        for c in ps.get("conditions") or []:
            try:
                values[c["metricKey"]] = float(c["actualValue"])
            except (KeyError, TypeError, ValueError):
                pass
        failed = [describe(c) for c in ps.get("conditions") or [] if c.get("status") in ("ERROR", "WARN")]
        return {"status": status, "failed": failed, "url": self.dashboard_url(key, pr, branch),
                "issues_url": self.issues_url(key, pr, branch), "values": values,
                "detail": "; ".join(failed) if failed else STATUS_LABEL[status]}


SEVERITY_ORDER = ["BLOCKER", "CRITICAL", "HIGH", "MAJOR", "MEDIUM", "MINOR", "LOW", "INFO"]
TYPE_LABEL = {"BUG": "Bug", "VULNERABILITY": "Schwachstelle", "CODE_SMELL": "Code Smell", "SECURITY_HOTSPOT": "Hotspot",
              "SECURITY": "Sicherheit", "RELIABILITY": "Zuverlässigkeit", "MAINTAINABILITY": "Wartbarkeit"}
HIST_COLS = (("violations", "Findings"), ("bugs", "Bugs"), ("vulnerabilities", "Schwachstellen"), ("code_smells", "Smells"), ("coverage", "Abdeckung %"))


def impact(issue):
    """(Schwere, Art) eines Findings: im Multi-Quality-Rule-Modus aus «impacts» (schwerste Auswirkung), sonst aus severity/type."""
    imps = [i for i in issue.get("impacts") or [] if isinstance(i, dict) and i.get("severity")]
    if imps:
        top = min(imps, key=lambda i: SEVERITY_ORDER.index(i["severity"]) if i["severity"] in SEVERITY_ORDER else 99)
        return top["severity"], top.get("softwareQuality") or issue.get("type")
    return issue.get("severity") or "?", issue.get("type") or "?"


def _path(component, key):
    c = str(component or "")
    return c[len(key) + 1:] if c.startswith(key + ":") else c


def _line(txt, n=300):
    txt = " ".join(str(txt or "").split())
    return txt if len(txt) <= n else txt[:n - 1] + "…"


def format_report(title, gate, key, issues, total, facets, hotspots, link, limit, history=None):
    """Markdown für die Zwischenablage. Enthält Dateipfade, Zeilennummern, Regeln und Sonar-Meldungen, aber keinen Quelltext."""
    L = ["# Sonar-Findings: %s" % title, "", "Projekt `%s` · Quality Gate: **%s**" % (key, STATUS_LABEL.get(gate.get("status"), gate.get("status", "?")))]
    if link:
        L.append("Sonar: %s" % link)
    if gate.get("failed"):
        L += ["", "## Nicht erfüllte Bedingungen"] + ["- %s" % f for f in gate["failed"]]
    L += ["", "## Findings (%d offen)" % total]
    sev = facets.get("impactSeverities") or facets.get("severities") or {}
    typ = facets.get("impactSoftwareQualities") or facets.get("types") or {}
    if sev:
        L.append("Schwere: " + ", ".join("%s %s" % (s.lower(), sev[s]) for s in SEVERITY_ORDER if sev.get(s)))
    if typ:
        L.append("Art: " + ", ".join("%s %s" % (TYPE_LABEL.get(t, t), n) for t, n in typ.items() if n))
    if not issues:
        L.append("Keine offenen Findings." if not total else "Keine Findings abrufbar.")
    by_file = {}
    for i in issues:
        by_file.setdefault(_path(i.get("component"), key), []).append(i)
    for path in sorted(by_file, key=lambda p: (min(SEVERITY_ORDER.index(impact(i)[0]) if impact(i)[0] in SEVERITY_ORDER else 99 for i in by_file[p]), p)):
        L += ["", "### `%s`" % path]
        for i in sorted(by_file[path], key=lambda x: x.get("line") or 0):
            sv, ty = impact(i)
            L.append("- Zeile %s [%s, %s] `%s`: %s" % (i.get("line", "?"), sv.lower(), TYPE_LABEL.get(ty, ty), i.get("rule", "?"), _line(i.get("message"))))
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
    if history and history.get("rows"):
        cols = [(k, lab) for k, lab in history["cols"] if any(k in r for r in history["rows"])]
        L += ["", "## Verlauf (%s)" % history["source"], "| Stand | " + " | ".join(lab for _, lab in cols) + " |", "|---|" + "---|" * len(cols)]
        for r in history["rows"]:
            L.append("| %s | " % datetime.fromtimestamp(r["ts"]).strftime("%d.%m. %H:%M") + " | ".join(("%g" % r[k]) if k in r else "" for k, _ in cols) + " |")
        first, last = history["rows"][0], history["rows"][-1]
        k0 = cols[0][0] if cols else None
        if k0 and k0 in first and k0 in last and len(history["rows"]) > 1:
            d = last[k0] - first[k0]
            L.append("%s: %g → %g (%s)" % (cols[0][1], first[k0], last[k0], "weniger" if d < 0 else "mehr" if d > 0 else "unverändert"))
    L += ["", "---", "Erzeugt von tinyops aus der Sonar-API (nur lesend). Enthält Pfade und Meldungen, keinen Quelltext."]
    return "\n".join(L) + "\n"


def trend_of(series, source="sonar", keep=24):
    """series: [(ts, zahl)] alt nach neu → Zusammenfassung für die Anzeige oder None (weniger als zwei Punkte)."""
    pts = [(t, v) for t, v in series if v is not None]
    if len(pts) < 2:
        return None
    first, last = pts[0][1], pts[-1][1]
    return {"source": source, "points": [int(v) if float(v).is_integer() else round(v, 1) for _, v in pts[-keep:]], "first": first, "last": last,
            "delta": last - first, "since": pts[0][0], "n": len(pts)}
