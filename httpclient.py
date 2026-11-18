"""HTTP-Client für GitLab, Jira und Co. (0.37 aus server.py gelöst): JSON, Seiten, keine Weiterleitungen, Fehler als UserError."""
import http.client
import json
import time
import urllib.error
import urllib.parse
import urllib.request

import tlog
from common import HttpStatus, UserError
from net import NoRedirect
from secretstore import scrub

glog = tlog.get("gitlab")
jlog = tlog.get("jira")


class Http:
    def __init__(self, label, base, headers, ctx):
        self.label, self.base, self.headers = label, base, headers
        self.opener = urllib.request.build_opener(NoRedirect, urllib.request.HTTPSHandler(context=ctx))

    def post_json(self, path, body):
        """Schreibender Aufruf. Wird nur für ausdrücklich ausgelöste Aktionen benutzt (Ticket anlegen)."""
        lg = glog if self.label == "GitLab" else jlog
        req = urllib.request.Request(self.base + path, data=json.dumps(body).encode("utf-8"), method="POST",
                                     headers=dict(self.headers, **{"Content-Type": "application/json"}))
        t0 = time.time()
        try:
            with self.opener.open(req, timeout=20) as r:
                data = json.loads(r.read().decode("utf-8") or "{}")
                lg.info("SCHREIBEN POST %s → %s in %d ms", path, r.status, int((time.time() - t0) * 1000))
                return data
        except urllib.error.HTTPError as e:
            detail = ""
            try:
                j = json.loads(e.read(4000).decode("utf-8"))
                errs = list((j.get("errors") or {}).values()) + list(j.get("errorMessages") or [])
                detail = "; ".join(str(x) for x in errs)
            except Exception:
                pass
            lg.warning("SCHREIBEN POST %s → HTTP %s: %s", path, e.code, scrub(detail))
            hint = {401: " (Zugangsdaten falsch oder abgelaufen)", 403: " (keine Berechtigung zum Anlegen in diesem Projekt)"}.get(e.code, "")
            raise HttpStatus("%s: HTTP %s%s%s" % (self.label, e.code, hint, (": " + scrub(detail)) if detail else ""), e.code)
        except (urllib.error.URLError, http.client.HTTPException, OSError) as e:
            raise UserError("%s nicht erreichbar (%s)." % (self.label, scrub(getattr(e, "reason", e))))
        except ValueError:
            raise UserError("%s: Antwort ist kein JSON." % self.label)

    def get(self, path, params=None):
        url = self.base + path
        if params:
            url += "?" + urllib.parse.urlencode(params)
        req = urllib.request.Request(url, headers=self.headers)
        lg = glog if self.label == "GitLab" else jlog
        t0 = time.time()
        shown = path + (("?" + urllib.parse.urlencode(params)) if params else "")
        try:
            with self.opener.open(req, timeout=15) as r:
                data = json.loads(r.read().decode("utf-8"))
                ms = int((time.time() - t0) * 1000)
                (lg.info if ms > 3000 else lg.debug)("GET %s → %s in %d ms%s", shown, r.status, ms,
                                                    " (langsam)" if ms > 3000 else "")
                return data
        except urllib.error.HTTPError as e:
            lg.warning("GET %s → HTTP %s in %d ms", shown, e.code, int((time.time() - t0) * 1000))
            hint = ""
            if e.code == 401:
                hint = " (Zugangsdaten falsch oder abgelaufen)"
            elif e.code in (301, 302, 303, 307, 308):
                hint = " (URL leitet um, prüfe die URL in der config.json, z. B. https statt http)"
            raise HttpStatus("%s %s: HTTP %s%s" % (self.label, path, e.code, hint), e.code)
        except (urllib.error.URLError, http.client.HTTPException, OSError) as e:
            msg = scrub(getattr(e, "reason", e))
            lg.warning("GET %s → nicht erreichbar nach %d ms: %s", shown, int((time.time() - t0) * 1000), msg)
            hint = " Tipp: ca_bundle in der config.json auf die Firmen-CA setzen." if "CERTIFICATE_VERIFY_FAILED" in msg else ""
            raise UserError("%s nicht erreichbar (%s).%s" % (self.label, msg, hint))
        except ValueError:
            lg.warning("GET %s → Antwort ist kein JSON", shown)
            raise UserError("%s %s: Antwort ist kein JSON (falsche URL?)" % (self.label, path))
