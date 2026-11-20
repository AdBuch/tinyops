"""Microsoft 365: Anmeldung, Termine, Mail und Teams «wartet auf dich».

Bereich von App (0.38 aus server.py gelöst). Gemeinsames (cfg, store, Audit, Cache) kommt von App;
Aufrufe in andere Bereiche stehen in USES und werden von tests/test_areas.py geprüft."""

import threading
import time

import focusplan
import links
import m365
import secretstore as store
import tlog
from common import UserError
from secretstore import scrub

log = tlog.get("app")


class M365Area:
    # Aufrufe in andere Bereiche (tests/test_areas.py prüft, dass genau diese benutzt werden)
    USES = {"area_focus": ("_area_of",)}

    # -- Microsoft 365 (0.28)
    @staticmethod
    def _m365_store():
        def get():
            try:
                return store.resolve(m365.SECRET)[0] or ""
            except store.SecretError:
                return ""

        def put(v):
            store.register(v)
            store.set_secret(m365.SECRET, v)

        def drop():
            try:
                store.delete_secret(m365.SECRET)
            except store.SecretError:
                pass
        return get, put, drop

    def _m365_fetch(self, step=None, force=False):
        """Mail, Kalender, Teams lesen: höchstens alle refresh_minutes. Fehler bleiben im Ergebnis, alte Daten bleiben stehen."""
        if self.demo or not self.m365.ready() or not self.m365.has_login():
            return
        if not force and self.m365_cache and time.time() - self.m365_t < float(self.mc["refresh_minutes"]) * 60:
            return
        if step:
            step("m365", "Microsoft 365: Mail, Kalender, Teams", "run")
        try:
            r = self.m365.fetch()
            if step:
                step("m365", "Microsoft 365: Mail, Kalender, Teams", "err" if r["errors"] else "ok", "; ".join("%s: %s" % kv for kv in r["errors"].items()))
        except m365.GraphError as e:
            log.warning("Microsoft 365: %s", scrub(e))
            if step:
                step("m365", "Microsoft 365: Mail, Kalender, Teams", "err", str(e))
            r = dict(self.m365_cache or {}, ok=False, error=str(e), outdated=bool(self.m365_cache))
        self.m365_cache, self.m365_t = r, time.time()

    def m365_state(self):
        if self.demo:
            return self._m365_hide_booked(dict(m365.demo(), enabled=True, logged_in=True, calendar_write=True))
        if not self.mc["enabled"]:
            return None
        st = {"enabled": True, "ready": self.m365.ready(), "logged_in": self.m365.has_login(), "calendar_write": bool(self.mc["calendar_write"]),
              "login_error": self.m365.last_error}
        if self.m365_cache:
            st.update(self.m365_cache)
        return self._m365_hide_booked(st)

    def _m365_hide_booked(self, st):
        """Termine, die schon als Zeit übernommen sind, nicht mehr zum Übernehmen anbieten."""
        cal = st.get("calendar")
        if cal and cal.get("past_unbooked"):
            a = min(e["start"] for e in cal["past_unbooked"])
            done = [x["start"] for x in self.timebook.range_segments(a - 1, time.time() + 1) if x.get("source") == "termin"]
            st = dict(st, calendar=dict(cal, past_unbooked=[e for e in cal["past_unbooked"] if not any(abs(d - e["start"]) < 60 for d in done)]))
        return st

    def m365_action(self, action, b, now=None):
        now = now or time.time()
        if action == "login":
            return {"url": self.m365.auth_url()}
        if action == "device":
            return self.m365.device_start()
        if action == "device_state":
            d = self.m365.device_state() or {"state": ""}
            if d.get("state") == "fertig":
                self._m365_fetch(force=True)
            return d
        if action == "logout":
            self.m365.logout()
            self.m365_cache = None
            self.audit("m365.logout", "")
            return {"ok": True}
        if action == "refresh":
            self._m365_fetch(force=True)
            return self.m365_state() or {}
        if action == "book":                     # vergangenen Termin als Zeit übernehmen: nur lokal, in die Zeiterfassung
            if not self.tc["enabled"]:
                raise UserError("Die Zeiterfassung ist ausgeschaltet.")
            cal = ((self.m365_state() or {}).get("calendar") or {})
            ev = next((e for e in cal.get("past_unbooked") or [] if e["id"] == b.get("id")), None)
            if not ev:
                raise UserError("Diesen Termin gibt es (heute) nicht mehr.")
            key = " ".join(str(b.get("key") or "").split())
            key = key if links.is_ref_key(key) else key.upper()
            if not key or len(key) > 120:
                raise UserError("Worauf soll gebucht werden? Ticket oder Bereich angeben.")
            if any(x.get("source") == "termin" and abs(x["start"] - ev["start"]) < 60 for x in self.timebook.range_segments(ev["start"] - 1, ev["end"] + 1, now)):
                raise UserError("Dieser Termin ist schon als Zeit eingetragen.")
            area = b.get("area") if b.get("area") and focusplan.area(self.fc, b.get("area")) else self._area_of(key)
            self.timebook.add_segment(key, ev["subject"], ev["start"], ev["end"], "termin", area or "", "Termin")
            self.audit("time.meeting", key, minutes=int((ev["end"] - ev["start"]) // 60), subject=ev["subject"][:80])
            return {"ok": True, "minutes": int((ev["end"] - ev["start"]) // 60)}
        raise UserError("Unbekannte Aktion.")

    def m365_callback(self, q):
        """Rückleitung von Microsoft nach der Anmeldung. Gibt (ok, Meldung) zurück."""
        if q.get("error"):
            return False, m365._explain((q.get("error") or [""])[0], (q.get("error_description") or [""])[0])
        try:
            me = self.m365.callback((q.get("code") or [""])[0], (q.get("state") or [""])[0])
        except m365.GraphError as e:
            return False, str(e)
        self.audit("m365.login", me.get("mail") and "angemeldet" or "", scopes=" ".join(m365.scopes(self.mc)))
        threading.Thread(target=self._m365_fetch, kwargs={"force": True}, daemon=True).start()
        return True, "Angemeldet als %s." % (me.get("name") or me.get("mail") or "?")
