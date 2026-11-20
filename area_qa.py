"""Prüfen und Nutzung: Prüfliste, Testsitzung, Nutzungsbericht, Hinweis nach einem Update.

Bereich von App (0.38 aus server.py gelöst). Gemeinsames (cfg, store, Audit, Cache) kommt von App;
Aufrufe in andere Bereiche stehen in USES und werden von tests/test_areas.py geprüft."""

import json
import re
import time

import qa
import secretstore as store
import ux
from common import UserError
from config import DEFAULTS


class QaArea:
    # Aufrufe in andere Bereiche (tests/test_areas.py prüft, dass genau diese benutzt werden)
    USES = {"area_tickets": ("board_action",)}

    # -- UI-Nutzung (0.22): lokal erfassen, auswerten, als Bericht kopieren
    def _ux_cfg(self):
        c = dict(DEFAULTS["ux"])
        c.update(self.cfg.get("ux") or {})
        return c

    def ux_events(self, b):
        c = self._ux_cfg()
        if not c["enabled"]:
            return {"ok": False, "off": True}
        return {"ok": True, "n": self.uxlog.add_batch(b.get("sess"), b.get("events"), int(c["days"] or 30))}

    def ux_report(self, days=7):
        days = max(1, min(int(days or 7), 365))
        evs = self.uxlog.events(time.time() - days * 86400)
        a = ux.analyse(evs)
        sub, newest = ux.latest_only(evs, a)
        cur = ux.analyse(sub) if sub is not None else None
        return {"text": ux.report_md(a, days, self.version, cur, newest), "sessions": a["sessions"], "events": a["events"], "active_min": a["active_min"],
                "hints": ux.hints(cur or a), "enabled": self._ux_cfg()["enabled"], "stored": self.uxlog.count(), "days": days, "wishes": len(a["wishes"])}

    def ux_wish(self, b):
        """Wunsch an tinyops (0.30): landet im Nutzungsbericht, auch wenn die Erfassung aus ist – du hast ihn ja ausdrücklich geschrieben."""
        try:
            self.uxlog.add_wish(b.get("sess"), b.get("text"), b.get("view") or "", b.get("trail") or [], self.version)
        except ValueError as e:
            raise UserError(str(e))
        self.audit("ux.wish", "", chars=len(str(b.get("text") or "")))
        return {"ok": True}

    def ux_clear(self):
        n = self.uxlog.clear()
        self.audit("ux.clear", "", events=n)
        return {"deleted": n}

    # -- Hinweis vom Starter (0.21): «Aktualisiert auf …» einmal im Panel zeigen
    def update_note(self):
        f = store.home_dir() / "last-update.json"
        try:
            n = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        if n.get("seen") or time.time() - float(n.get("ts") or 0) > 7 * 86400:
            return None
        return {k: n.get(k) for k in ("from", "to", "ok", "qa_new", "message")}

    def update_seen(self):
        f = store.home_dir() / "last-update.json"
        try:
            n = json.loads(f.read_text(encoding="utf-8"))
            n["seen"] = True
            f.write_text(json.dumps(n, ensure_ascii=False), encoding="utf-8")
        except (OSError, ValueError):
            pass
        return {"ok": True}

    def update_news(self):
        n = self.update_note() or {}
        try:
            text = (self.base / "CHANGELOG.md").read_text(encoding="utf-8")
        except OSError:
            return {"text": ""}
        m = re.match(r"v?(\d+\.\d+\.\d+)$", str(n.get("from") or ""))
        old = tuple(int(x) for x in m.group(1).split(".")) if m else None
        out, take = [], False
        for ln in text.splitlines():
            h = re.match(r"^## \[(\d+\.\d+\.\d+)\]", ln)
            if h:
                take = old is None and not out or (old is not None and tuple(int(x) for x in h.group(1).split(".")) > old)
            if take:
                out.append(ln)
        return {"text": "\n".join(out).strip()}

    # -- Qualität (0.19): Prüfliste und Selbsttest
    def _checklist(self):
        try:
            return qa.parse_checklist((self.base / "QA-CHECKLIST.md").read_text(encoding="utf-8"))
        except OSError:
            return []
        except ValueError as e:
            raise UserError(str(e))

    def qa_view(self):
        secs = qa.view(self._checklist(), self.qabook.states())
        exact = any(s_["version"] == self.version for s_ in secs)
        mm = self.version.rsplit(".", 1)[0]
        for s_ in secs:                     # Patch-Release ohne eigenen Abschnitt: der Abschnitt derselben Minor-Version gilt als aktuell
            s_["current"] = s_["version"] == self.version or (not exact and bool(s_["version"]) and s_["version"].rsplit(".", 1)[0] == mm)
        return {"version": self.version, "sections": secs, "file": str(self.base / "QA-CHECKLIST.md")}

    def qa_action(self, action, b):
        if action == "report":
            return {"text": qa.report_md(self.qa_view()["sections"], self.version)}
        if action == "selftest":
            res = self.selftest()
            self.audit("qa.selftest", self.version, ok=res["ok"], failed=[x["title"] for x in res["steps"] if x["status"] == "fail"],
                       warn=[x["title"] for x in res["steps"] if x["status"] == "warn"])
            return res
        iid = str(b.get("id") or "")
        it = next((i for s_ in self._checklist() for i in s_["items"] if i["id"] == iid), None)
        if not it:
            raise UserError("Diesen Prüfpunkt gibt es nicht (mehr).")
        if action == "set":
            st = b.get("status") or "offen"
            if st not in qa.STATES + ("offen",):
                raise UserError("Status: ok, fehler, übersprungen oder offen.")
            note = str(b.get("note") or "").strip()
            self.qabook.set(iid, st, note, self.version, it["hash"])
            if st != "offen":
                self.audit("qa.check", iid, ok=st != "fehler", status=st, note=note[:200])
            return {"ok": True}
        if action == "task":
            title = "QA %s: %s" % (iid, it["text"])
            res = self.board_action("add", {"title": title[:200], "stage": "idea"})
            return {"key": res["key"]}
        raise UserError("Unbekannte Aktion.")
