"""Review-Entwürfe in GitLab (0.42, E14): Befunde eines Review-Laufs als deine Entwurfs-Kommentare am MR.

Was dieser Weg darf, steht in ALLOWED und nirgends sonst: MR, Diff-Versionen und deine Entwürfe lesen, Entwürfe anlegen und löschen.
Nie abschicken (publish, bulk_publish), nie Approve, Merge, Ready oder Threads auflösen. Jede Anfrage läuft durch `_req`, das gegen ALLOWED prüft.
Ehrlich: Das Token (`gitlab_review_token`, Scope api) könnte in GitLab mehr. Die Grenze setzt dieser Code, und tests/test_v42.py hält sie fest.
Der Agent sieht das Token nie: er schreibt Befunde mit `tinyops-finding` in eine Datei, tinyops legt daraus die Entwürfe an.
tinyops ändert oder löscht nur Entwürfe, die es selbst angelegt hat (in der Datenbank vermerkt und mit MARK im Text)."""
import http.client
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request

import apicalls
import tlog
from common import HttpStatus, UserError
from net import NoRedirect
from secretstore import scrub

log = tlog.get("gitlab")

_MR = r"/projects/\d+/merge_requests/\d+"
ALLOWED = (
    ("GET", re.compile(r"^%s$" % _MR)),                               # MR: Titel, Zielbranch, Head-Commit, Adresse
    ("GET", re.compile(r"^%s/versions$" % _MR)),                      # Diff-Versionen (base/start/head) für die Position
    ("GET", re.compile(r"^%s/versions/\d+$" % _MR)),                  # Diff einer Version: liegt die Zeile im Diff?
    ("GET", re.compile(r"^%s/draft_notes$" % _MR)),                   # deine Entwürfe (GitLab zeigt nur die eigenen)
    ("POST", re.compile(r"^%s/draft_notes$" % _MR)),                  # Entwurf anlegen
    ("DELETE", re.compile(r"^%s/draft_notes/\d+$" % _MR)),            # eigenen Entwurf löschen (vor dem Ersetzen)
)
MARK = "<!-- tinyops -->"          # unsichtbar in GitLab; nur Entwürfe mit dieser Marke fasst tinyops an
SEV_LABEL = {"hoch": "**Wichtig:** ", "mittel": "", "klein": "*Kleinigkeit:* "}


def allowed(method, path):
    return any(m == method and rx.match(path) for m, rx in ALLOWED)


class Drafts:
    def __init__(self, gitlab_url, token, ctx):
        self.base = gitlab_url.rstrip("/") + "/api/v4"
        self.headers = {"PRIVATE-TOKEN": token, "Accept": "application/json"}
        self.opener = urllib.request.build_opener(NoRedirect, urllib.request.HTTPSHandler(context=ctx))

    def _req(self, method, path, body=None, params=None):
        if not allowed(method, path):            # die eine Stelle, an der die Grenze gilt
            raise UserError("tinyops darf in GitLab nur Entwürfe anlegen und löschen; %s %s ist nicht erlaubt." % (method, path))
        url = self.base + path + (("?" + urllib.parse.urlencode(params)) if params else "")
        data = json.dumps(body).encode("utf-8") if body is not None else None
        hdr = dict(self.headers, **({"Content-Type": "application/json"} if data else {}))
        req = urllib.request.Request(url, data=data, method=method, headers=hdr)
        apicalls.record("GitLab (Review)", method, path)
        t0 = time.time()
        try:
            with self.opener.open(req, timeout=20) as r:
                raw = r.read().decode("utf-8")
                (log.info if method != "GET" else log.debug)("%sREVIEW %s %s → %s in %d ms", "SCHREIBEN " if method != "GET" else "", method, path, r.status,
                                                             int((time.time() - t0) * 1000))
                return json.loads(raw) if raw.strip() else None
        except urllib.error.HTTPError as e:
            log.warning("REVIEW %s %s → HTTP %s", method, path, e.code)
            hint = {401: " (Review-Token falsch oder abgelaufen)", 403: " (das Review-Token darf das nicht; Scope api?)",
                    404: " (MR oder Entwurf nicht gefunden, oder das Token sieht das Projekt nicht)"}.get(e.code, "")
            raise HttpStatus("GitLab: HTTP %s%s" % (e.code, hint), e.code)
        except (urllib.error.URLError, http.client.HTTPException, OSError) as e:
            raise UserError("GitLab nicht erreichbar (%s)." % scrub(getattr(e, "reason", e)))
        except ValueError:
            raise UserError("GitLab: Antwort ist kein JSON.")

    def mr(self, pid, iid):
        return self._req("GET", "/projects/%d/merge_requests/%d" % (pid, iid)) or {}

    def versions(self, pid, iid):
        return self._req("GET", "/projects/%d/merge_requests/%d/versions" % (pid, iid)) or []

    def version(self, pid, iid, vid):
        return self._req("GET", "/projects/%d/merge_requests/%d/versions/%d" % (pid, iid, vid)) or {}

    def drafts(self, pid, iid):
        return self._req("GET", "/projects/%d/merge_requests/%d/draft_notes" % (pid, iid)) or []

    def create(self, pid, iid, note, position=None):
        body = {"note": note}
        if position:
            body["position"] = position
        return self._req("POST", "/projects/%d/merge_requests/%d/draft_notes" % (pid, iid), body) or {}

    def delete(self, pid, iid, did):
        return self._req("DELETE", "/projects/%d/merge_requests/%d/draft_notes/%d" % (pid, iid, did))


# ------------------------------------------------------------ Diff: welche Zeilen liegen im Diff?
def diff_lines(diff):
    """Aus einem Unified Diff: {neue Zeile: alte Zeile oder None (hinzugefügt)}. Nur Zeilen, die GitLab im Diff zeigt."""
    out, old, new = {}, 0, 0
    for ln in (diff or "").splitlines():
        m = re.match(r"^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@", ln)
        if m:
            old, new = int(m.group(1)), int(m.group(2))
            continue
        if not new:
            continue
        if ln.startswith("+"):
            out[new] = None
            new += 1
        elif ln.startswith("-"):
            old += 1
        elif ln.startswith("\\"):
            continue
        else:
            out[new] = old
            old += 1
            new += 1
    return out


def plan(findings, version, url=""):
    """Je Befund: Entwurf mit Position (Zeile im Diff) oder allgemein (Datei nicht im Diff, keine Zeile, Zeile ausserhalb)."""
    files = {}
    for d in version.get("diffs") or []:
        files[d.get("new_path") or d.get("old_path")] = (d, diff_lines(d.get("diff")))
    out = []
    for f in findings:
        text = SEV_LABEL.get(f.get("severity"), "") + f["text"]
        hit = files.get(f["path"])
        if hit and f["line"] and f["line"] in hit[1] and not hit[0].get("deleted_file"):
            d, lines = hit
            pos = {"position_type": "text", "base_sha": version["base_commit_sha"], "start_sha": version["start_commit_sha"],
                   "head_sha": version["head_commit_sha"], "new_path": d.get("new_path"), "old_path": d.get("old_path"), "new_line": f["line"]}
            if lines[f["line"]] is not None:
                pos["old_line"] = lines[f["line"]]
            out.append({"finding": f, "note": text + "\n\n" + MARK, "position": pos})
        else:
            why = "nicht im Diff" if not hit else ("ohne Zeile" if not f["line"] else "Zeile nicht im Diff")
            where = "`%s%s`" % (f["path"], ":%d" % f["line"] if f["line"] else "")
            out.append({"finding": f, "note": "%s: %s\n\n%s" % (where, text, MARK), "position": None, "why": why})
    return out


def pick_version(versions, sha):
    """Die Diff-Version, auf der das Review lief (Head-Commit), sonst die neueste. Zweiter Wert: lief es auf einem älteren Stand?"""
    if not versions:
        return None, False
    hit = next((v for v in versions if sha and str(v.get("head_commit_sha") or "").startswith(sha)), None)
    return (hit, hit is not versions[0]) if hit else (versions[0], bool(sha))
