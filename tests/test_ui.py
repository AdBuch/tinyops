"""Oberfläche im echten Browser (0.33): Playwright gegen den Demo-Server.

Deckt ab, was sonst von Hand in der Prüfliste stand: Ansichten laden ohne JavaScript-Fehler, Handy-Breite ohne seitliches
Scrollen, Agenten-Zyklus mit Freigabe, «Kurz vorab», Prompt ansehen/bearbeiten, Testsitzung in Prüfen, Einstellungen.
Ohne Playwright (pip install playwright && python -m playwright install chromium) werden die Tests übersprungen.
"""
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

try:
    from playwright.sync_api import sync_playwright
except ImportError:                     # pragma: no cover - je nach Umgebung
    sync_playwright = None

REPORT = "## Kurz\nRetry mit Backoff bei 429.\n\n## Was und warum\n- `core/retry.py` – RetryPolicy – damit 429 nicht abbricht\n\n## Zuerst ansehen\nDie Schleife.\n"
WORK = ("mkdir -p core && printf 'x = 1\\n' > core/retry.py && echo n > notes.txt && git add -A && "
        "git -c user.name=A -c user.email=a@x commit -qm retry; tinyops-check true; tinyops-ak 1 erfüllt 'Test grün'; "
        "tinyops-manual 'Import mit 429 starten' 'Kein Abbruch'; printf '%s' | tinyops-report" % REPORT.replace("'", "").replace("\n", "\\n"))

_srv = _url = _dir = _pw = _browser = None


def _free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def setUpModule():
    global _srv, _url, _dir, _pw, _browser
    if sync_playwright is None:
        raise unittest.SkipTest("Playwright fehlt (pip install playwright && python -m playwright install chromium)")
    _dir = Path(tempfile.mkdtemp(prefix="tinyops-ui-"))
    ws = _dir / "ws" / "dlp-core"
    ws.mkdir(parents=True)
    for cmd in (["git", "init", "-q", "-b", "main"], ["git", "add", "-A"]):
        subprocess.run(cmd, cwd=ws, check=True)
    (ws / "README").write_text("a\n")
    subprocess.run(["git", "add", "-A"], cwd=ws, check=True)
    subprocess.run(["git", "-c", "user.name=T", "-c", "user.email=t@x", "commit", "-qm", "init"], cwd=ws, check=True)
    port = _free_port()
    cfg = {"data_dir": str(_dir / "data"), "port": port, "time": {"enabled": True}, "connections": [], "ide_command": "true {path}",
           "projects": [{"id": 1, "name": "dlp-core", "data_class": "internal"}, {"id": 2, "name": "dlp-ui", "data_class": "internal"}],
           "agents": [{"id": "ui", "name": "UI-Agent", "kind": "custom", "connection": "local", "workspace_root": str(_dir / "ws"),
                       "cloud": False, "command": WORK}]}
    (_dir / "config.json").write_text(json.dumps(cfg))
    env = dict(os.environ, TINYOPS_NO_WATCHDOG="1", TINYOPS_HOME=str(_dir / "home"))
    _srv = subprocess.Popen([sys.executable, str(ROOT / "server.py"), "--demo", "--config", str(_dir / "config.json")], cwd=ROOT, env=env,
                            stdout=open(_dir / "server.log", "w"), stderr=subprocess.STDOUT)
    _url = "http://127.0.0.1:%d/" % port
    for _ in range(100):
        try:
            urllib.request.urlopen(_url, timeout=1)
            break
        except OSError:
            if _srv.poll() is not None:
                break
            time.sleep(0.2)
    else:
        raise RuntimeError("Demo-Server startet nicht: %s" % (_dir / "server.log").read_text()[-2000:])
    if _srv.poll() is not None:
        raise RuntimeError("Demo-Server beendet: %s" % (_dir / "server.log").read_text()[-2000:])
    _pw = sync_playwright().start()
    try:
        _browser = _pw.chromium.launch()
    except Exception as e:              # Chromium nicht installiert
        _pw.stop()
        _srv.terminate()
        raise unittest.SkipTest("Chromium für Playwright fehlt: %s" % str(e)[:200])


def tearDownModule():
    if _browser:
        _browser.close()
    if _pw:
        _pw.stop()
    if _srv:
        _srv.terminate()
        try:
            _srv.wait(5)
        except subprocess.TimeoutExpired:
            _srv.kill()


class UiCase(unittest.TestCase):
    width, height = 1280, 900

    def setUp(self):
        self.ctx = _browser.new_context(viewport={"width": self.width, "height": self.height})
        self.pg = self.ctx.new_page()
        self.errors = []
        self.pg.on("pageerror", lambda e: self.errors.append(str(e)))
        self.pg.goto(_url)
        self.wait_js("!!document.querySelector('.tab') && typeof AG === 'function' && !!AG()", 15000)
        self.pg.keyboard.press("Escape")

    def tearDown(self):
        self.ctx.close()
        self.assertEqual(self.errors, [], "JavaScript-Fehler im Browser")

    def wait_js(self, expr, timeout=8000):
        """Wie wait_for_function, aber über evaluate: die CSP von tinyops verbietet eval (also wait_for_function mit Text)."""
        end = time.time() + timeout / 1000
        while time.time() < end:
            try:
                if self.pg.evaluate("() => { try { return !!(%s); } catch (e) { return false; } }" % expr):
                    return
            except Exception:
                pass
            self.pg.wait_for_timeout(150)
        self.fail("Wartete vergeblich auf: " + expr)

    VIEWS = {"Fokus": ("focus", "viewFocus"), "Board": ("board", "viewBoard"), "Workspaces": ("ws", "viewWs"), "Listen": ("overview", "viewOverview"),
             "Zeit": ("time", "viewTime"), "Prüfen": ("qa", "viewQa"), "Einstellungen": ("settings", "viewSettings")}

    def tab(self, name):
        """Ansicht wechseln wie ein Mensch: sichtbaren Reiter (oben) oder Knopf der unteren Leiste (Handy) anklicken."""
        v, box = self.VIEWS[name]
        btn = self.pg.locator('.tab[data-view="%s"]:visible, .bn[data-view="%s"]:visible' % (v, v)).first
        if btn.count():
            btn.click()
        else:                               # auf dem Handy nicht in der unteren Leiste: über die Adresse
            self.pg.evaluate("location.hash = '#%s'; setView && setView('%s')" % (v, v))
        self.wait_js("!document.getElementById('%s').hidden" % box)
        self.pg.wait_for_timeout(400)

    def wait_run(self, n=60):
        for _ in range(n):
            st = self.pg.evaluate("post('/api/agents/refresh', {}).then(load).then(() => AG().runs.length ? AG().runs[0].status : '')")
            if st and st not in ("läuft", "zugewiesen"):
                return st
            self.pg.wait_for_timeout(500)
        return st


class Views(UiCase):
    def test_focus_hero_with_pictograms(self):
        pg = self.pg
        pg.wait_for_selector(".hero .htitle", state="visible")
        self.assertTrue(pg.locator(".hero .htitle").first.is_visible())
        self.assertGreater(pg.locator(".hero .hpics svg.pic").count(), 0)          # Repo und Branch als Piktogramm (0.32)
        self.assertGreater(pg.locator(".fm svg.pic").count() + pg.locator(".picn svg.pic").count(), 0)
        pg.wait_for_selector(".hero .hwork h4")                                    # 0.36: Arbeitsfläche statt nur Titel
        self.assertIn("Worum es geht", pg.locator(".hero .hwork").inner_text())

    def test_no_projectron_left(self):
        for name in ("Zeit", "Einstellungen"):                                              # E1 (0.34): nur noch BCS
            self.tab(name)
            txt = self.pg.locator("#" + self.VIEWS[name][1]).inner_text()
            self.assertNotIn("MCP", txt, name)
            self.assertNotIn("Projectron", txt, name)

    def test_all_tabs_render(self):
        for name in self.VIEWS:
            self.tab(name)
            box = self.VIEWS[name][1]
            self.assertTrue(self.pg.locator("#" + box).is_visible(), name)
            self.assertGreater(len(self.pg.locator("#" + box).inner_text().strip()), 20, "%s ist leer" % name)

    def test_settings_sections_have_help(self):
        pg = self.pg
        self.tab("Einstellungen")
        self.wait_js("document.querySelectorAll('#viewSettings section').length > 5")
        sects = pg.evaluate("[...document.querySelectorAll('#viewSettings section[id]')].map(s => [s.id, !!s.querySelector('details.help')])")
        self.assertGreater(len(sects), 10)
        self.assertEqual([sid for sid, has in sects if not has], [], "Abschnitte ohne Hilfe")
        self.assertTrue(pg.locator("#st-save").is_disabled())                 # Demo: Speichern aus, mit Hinweis
        self.assertIn("Speichern ist ausgeschaltet", pg.locator("#viewSettings").inner_text())


class Detail(UiCase):
    def test_keys_open_detail_with_history_and_close(self):
        pg = self.pg
        pg.wait_for_selector("#viewFocus [data-fid]")
        pg.locator("body").click(position={"x": 5, "y": 300})
        pg.keyboard.press("j")
        pg.keyboard.press("j")
        pg.keyboard.press("k")
        self.assertEqual(pg.evaluate("[...document.querySelectorAll('#viewFocus [data-fid]')].findIndex(r => r.classList.contains('sel'))"), 0)   # j/k wählen
        pg.keyboard.press("i")
        pg.wait_for_selector("#ideaDlg[open]")                                               # i: Idee festhalten
        self.assertEqual(pg.evaluate("document.activeElement.id"), "ideaQuick")
        pg.keyboard.press("Escape")
        self.wait_js("!document.getElementById('ideaDlg').open")
        pg.locator("body").click(position={"x": 5, "y": 300})                              # Fokus aus dem Dialog zurück auf die Seite
        self.wait_js("!/INPUT|TEXTAREA|SELECT/.test(document.activeElement.tagName)")
        pg.keyboard.press("n")
        self.wait_js("document.activeElement.id === 'fAdd'")                                 # n: neue Aufgabe
        pg.locator("body").click(position={"x": 5, "y": 300})
        pg.keyboard.press("Enter")
        self.wait_js("!document.getElementById('fx').hidden")                               # Enter öffnet das Detail
        self.assertIn("Verlauf", pg.locator("#fx").inner_text())
        txt = pg.locator("#fx").inner_text()
        for w in ("Planen", "Testen", "Fertig", "MRs und Branches", "Teilschritte"):                 # Stationen, MRs, Teilschritte
            self.assertIn(w, txt)
        pg.keyboard.press("Escape")
        self.wait_js("document.getElementById('fx').hidden")                                # Esc schliesst
        pg.locator("#viewFocus [data-fid]").first.click()
        self.wait_js("!document.getElementById('fx').hidden")
        pg.mouse.click(5, 600)                                                               # ins Leere neben dem Panel
        self.wait_js("document.getElementById('fx').hidden")


class PinAndTime(UiCase):
    def test_pin_starts_time_and_pause(self):
        pg = self.pg
        pg.wait_for_selector("#viewFocus [data-fid]")
        pg.locator("#viewFocus .frow[data-fid]").first.click()
        self.wait_js("!document.getElementById('fx').hidden")
        pg.locator("#fx [data-fpin]:not([data-fpin=''])").first.click()
        pg.wait_for_selector(".htime:has-text('Zeit läuft')")                             # Zeit läuft im Fokus-Kopf
        pg.click("[data-tpause]")
        self.wait_js("!document.querySelector('.htime') || !/Zeit läuft/.test(document.querySelector('.htime').innerText)")


class SettingsNav(UiCase):
    def test_side_menu_stays_visible(self):
        pg = self.pg
        self.tab("Einstellungen")
        pg.wait_for_selector(".setnav")
        pg.mouse.wheel(0, 4000)
        pg.wait_for_timeout(400)
        box = pg.locator(".setnav").bounding_box()
        self.assertTrue(box and 0 <= box["y"] < self.height, box)                       # bleibt beim Scrollen sichtbar


class FocusSession(UiCase):
    def test_start_park_minimize_reopen(self):
        pg = self.pg
        pg.wait_for_selector("[data-fsess]")
        pg.locator("[data-fsess]").first.click()
        pg.wait_for_selector("#fsDlg[open]")
        pg.click('[data-fsmin="25"]')
        pg.click("#fsGo")
        self.wait_js("!document.getElementById('fmode').hidden")                            # Vollbild mit Uhr
        self.assertTrue(pg.locator("#fmClock").is_visible())
        pg.fill("#fmPark", "Gedanke für später")
        pg.keyboard.press("Enter")
        pg.wait_for_selector(".toast:has-text('Geparkt')")
        self.assertEqual(pg.locator("#fmPark").input_value(), "")                          # Feld leer, Cursor bleibt
        self.assertEqual(pg.evaluate("document.activeElement.id"), "fmPark")
        pg.click('[data-fmmin="1"]')                                                         # klein machen
        self.wait_js("document.getElementById('fmode').hidden")
        self.wait_js("!document.getElementById('fbar').hidden")                             # Leiste mit Uhr bleibt
        self.tab("Board")
        self.assertTrue(pg.locator("#fbar").is_visible())                                   # auch in anderen Ansichten
        pg.locator("#fbar").click(position={"x": 60, "y": 20})
        self.wait_js("!document.getElementById('fmode').hidden")                            # Klick öffnet wieder
        pg.click('[data-fmend="abgebrochen"]')
        self.wait_js("document.getElementById('fmode').hidden")


class MrTry(UiCase):
    def test_try_dialog_prompts_git_env(self):
        pg = self.pg
        self.tab("Listen")
        b = pg.locator("[data-mrtry]:visible").first
        b.scroll_into_view_if_needed()
        b.click()
        pg.wait_for_selector("#wsDlg[open] #mtPrompt")
        self.assertEqual(pg.locator("#mtPrompt option").all_inner_texts(), ["review-brief", "smoke-test", "repro-test"])
        self.assertTrue(pg.locator("#mtGit").is_visible())
        self.assertIn("keine eingetragen", pg.locator("#wsDlgBody").inner_text())          # ohne Review-Umgebung: Hinweis statt Knopf
        pg.click("#wsDlg > .dlgx")                                                         # 0.36: × oben rechts in jedem Dialog
        self.wait_js("!document.getElementById('wsDlg').open")
        b.click()
        pg.wait_for_selector("#wsDlg[open] #mtPrompt")
        pg.mouse.click(3, 450)                                                             # Klick daneben schliesst
        self.wait_js("!document.getElementById('wsDlg').open")


class Mobile(UiCase):
    width, height = 390, 844

    def test_no_horizontal_scroll(self):
        for name in (None, "Board", "Workspaces", "Listen", "Zeit", "Prüfen", "Einstellungen"):
            if name:
                self.tab(name)
            w = self.pg.evaluate("document.documentElement.scrollWidth")
            self.assertLessEqual(w, self.width + 1, "seitliches Scrollen in %s" % (name or "Fokus"))


class AgentCycle(UiCase):
    def test_plan_gate_develop_brief_manual(self):
        pg = self.pg
        self.tab("Listen")
        for i in range(5):                          # die Liste wird beim Abgleich neu gezeichnet; dann einfach nochmals
            try:
                sel = pg.locator("select[data-aassign]:visible").first
                sel.scroll_into_view_if_needed(timeout=3000)
                sel.select_option("ui", timeout=3000)
                break
            except Exception:
                if i == 4:
                    raise
                pg.wait_for_timeout(300)
        pg.wait_for_selector("#agPrompt", state="attached")
        pg.click('[data-aph="plan"]')
        pg.wait_for_timeout(800)
        self.assertIn("Planen:", pg.locator('[data-pview="agPrompt"] h3').first.inner_text())
        self.assertIn("Leitplanken", " ".join(pg.locator('[data-pview="agPrompt"] h4').all_inner_texts()))
        pg.click('[data-pv="edit"]')
        self.assertTrue(pg.locator("#agPrompt").is_visible())
        self.assertTrue(pg.locator("#agPrompt").input_value().startswith("# Planen:"))
        pg.click('[data-pv="view"]')
        self.assertTrue(pg.locator('[data-pcopy="agPrompt"]').is_visible())
        pg.click("#agStart")
        self.assertEqual(self.wait_run(), "fertig")
        rid = pg.evaluate("AG().runs[0].id")
        pg.evaluate("openRunDlg(%d)" % rid)
        pg.wait_for_selector(".gatebox")
        self.assertEqual(pg.locator(".cycle .ph").count(), 4)
        pg.click("#agGateOk")
        pg.wait_for_selector(".gatebox.ok")
        pg.click("#agNext")
        pg.wait_for_selector("#agPrompt", state="attached")
        self.assertIn("Freigegebener Plan", pg.locator("#agPrompt").input_value())
        pg.click("#agStart")
        self.assertEqual(self.wait_run(), "fertig")
        rid = pg.evaluate("AG().runs[0].id")
        pg.evaluate("openRunDlg(%d)" % rid)
        pg.wait_for_selector(".brief")
        self.assertIn("Retry mit Backoff", pg.locator(".brief").inner_text())                  # «Kurz vorab» aus dem Bericht
        self.assertIn("RetryPolicy", pg.locator(".bfiles").inner_text())
        self.assertIn("Keine Begründung", pg.locator(".bfiles").inner_text())                   # notes.txt ohne Begründung
        self.assertTrue(pg.locator("#agGateOk").is_disabled())
        n = pg.locator("[data-mck]").count()
        self.assertGreaterEqual(n, 5)
        for i in range(n):
            pg.locator('[data-mck="%d"]' % i).check()
            pg.wait_for_timeout(250)
        self.wait_js("!document.querySelector('#agGateOk').disabled")
        pg.click("#agGateOk")
        pg.wait_for_selector(".gatebox.ok")
        self.assertIn("Review", pg.locator(".gatebox.ok").inner_text())
        pg.wait_for_selector("#agTry b")
        self.assertIn("Ausprobieren", pg.locator("#agTry").inner_text())
        # 0.36: direkt weiterführen, ohne Umweg über den Startdialog
        pg.fill("#agCont", "Bitte noch einen Test für den Timeout.")
        before = pg.evaluate("AG().runs.length")
        pg.click("#agContGo")
        self.wait_js("AG().runs.length > %d" % before, 15000)
        self.assertEqual(self.wait_run(), "fertig")
        self.assertIn("Auftrag des Menschen", pg.evaluate("AG().runs[0].prompt_text"))
        pg.wait_for_selector("#agDlg[open] #agCont")


class QaSession(UiCase):
    def test_next_five_and_session_counter(self):
        pg = self.pg
        self.tab("Prüfen")
        pg.wait_for_selector(".qsess")
        before = pg.locator(".qsess [data-qset]").count()
        self.assertGreater(before, 0)
        self.assertLessEqual(pg.locator(".qsess .qitem, .qsess li").count() or 5, 5)
        pg.locator('.qsess [data-s="ok"]').first.click()
        pg.wait_for_timeout(1200)
        self.assertIn("in dieser Sitzung 1 erledigt", pg.locator(".qsess").inner_text())

    def test_text_click_opens_note(self):
        """0.35: Klick auf den Text eines Prüfpunkts (im Nutzungsbericht 27 tote Klicks) öffnet eine Notiz."""
        pg = self.pg
        self.tab("Prüfen")
        pg.wait_for_selector("[data-qtxt]")
        qid = pg.locator("[data-qtxt]").first.get_attribute("data-qtxt")
        pg.locator('[data-qtxt="%s"] .tx' % qid).first.click()
        self.wait_js("!!document.querySelector('#viewQa textarea[data-qnote=\"%s\"]')" % qid)
        self.assertEqual(pg.evaluate("document.activeElement.dataset.qnote"), qid)

    def test_auto_items_folded_and_not_next(self):
        """0.33 (r33-01/02): Punkte mit Test stehen zugeklappt unten und nie in «Als Nächstes testen»."""
        pg = self.pg
        self.tab("Prüfen")
        pg.wait_for_selector("details.qauto", state="attached")
        self.assertIn("prüft ein automatischer Test", pg.locator("details.qauto summary").first.text_content())
        nxt = pg.evaluate("[...document.querySelectorAll('.qsess [data-qset]')].map(b => b.dataset.qset)")
        autos = pg.evaluate("QA.sections.flatMap(s => s.items).filter(i => i.status === 'auto').map(i => i.id)")
        self.assertTrue(autos)
        self.assertFalse(set(nxt) & set(autos))


class Offline(UiCase):
    def test_banner_and_reconnect(self):
        """0.35: Ist tinyops kurz weg, kommt ein Hinweis oben statt Fehlermeldungen, und er verschwindet beim Wiederverbinden."""
        pg = self.pg
        pg.route("**/api/overview*", lambda r: r.abort())
        # andere Anfragen (Kontingent, Ziel der Fokus-Aufgabe) können dazwischen gelingen und den Hinweis kurz wegnehmen: bis er steht, neu laden
        self.wait_js("document.getElementById('offline') || (load(), false)", 15000)
        self.assertIn("Keine Verbindung", pg.evaluate("document.getElementById('offline') ? document.getElementById('offline').textContent : 'Keine Verbindung'"))
        pg.unroute("**/api/overview*")
        pg.evaluate("load()")
        self.wait_js("!document.getElementById('offline')")


class Tokens(UiCase):
    def test_overview_top_collapsed(self):
        """0.35.1: Zugänge oben in den Einstellungen, zugeklappt; «Eintragen» springt zum Abschnitt."""
        pg = self.pg
        self.tab("Einstellungen")
        pg.wait_for_selector("#tokBox")
        self.assertFalse(pg.evaluate("document.getElementById('tokBox').open"))
        self.assertLess(pg.locator("#tokBox").bounding_box()["y"], pg.locator(".setgrid").bounding_box()["y"])
        self.assertNotIn("Unbekanntes Secret", pg.locator("#tokBox").text_content())      # bcs_token ist speicherbar
        pg.locator("#tokBox > summary").click()
        pg.locator('[data-tokgo="time"]').click()
        self.wait_js("document.querySelector('.setnav [data-goto=\"time\"]').classList.contains('on')")


class AppAndPhone(UiCase):
    def test_settings_section_and_manifest(self):
        """0.36: App-Hülle verlinkt, Abschnitt «App und Handy» mit Koppeln; Agenten zum Ziehen in der Seitenleiste."""
        pg = self.pg
        self.assertEqual(pg.evaluate("document.querySelector('link[rel=manifest]').getAttribute('href')"), "/manifest.webmanifest")
        self.wait_js("document.querySelectorAll('[data-agdrag]').length > 0", 15000)     # erscheint, sobald die Agenten geladen sind
        self.tab("Einstellungen")
        pg.wait_for_selector("#s-app")
        txt = pg.locator("#s-app").inner_text()
        self.assertIn("Handy koppeln", txt)
        self.assertTrue(pg.locator("#app-code").is_disabled())                 # Demo: Koppeln aus
        self.wait_js("!!document.querySelector('#app-devs') && /Gerät/.test(document.querySelector('#app-devs').textContent)")


class FxLayout(UiCase):
    def test_buttons_below_chips_one_draft(self):
        """0.36.3: In «MRs und Branches» stehen die Knöpfe unter Titel und Chips, und «Draft» kommt nur einmal."""
        pg = self.pg
        q = "focusEntries().find(e => e.t === 'card' && (e.c.items || []).some(i => i.draft))"
        self.wait_js(q, 15000)
        fid = pg.evaluate("(%s).id" % q)
        pg.evaluate("openFx(%r)" % fid)
        it = pg.locator("#fx .fxitem:has(.chip.draft)").first
        it.wait_for()
        self.assertEqual(it.locator(".chip.draft").count(), 1)
        nm, bt = it.locator(".nm").bounding_box(), it.locator(".ibtns").bounding_box()
        self.assertGreaterEqual(bt["y"], nm["y"] + nm["height"] - 1)


class SidePanel(UiCase):
    def test_agent_window_is_side_panel(self):
        """0.39: Das Agentenfenster ist ein Seitenpanel; die Seite daneben bleibt bedienbar, Esc schliesst es."""
        pg = self.pg
        self.tab("Listen")
        for i in range(5):
            try:
                sel = pg.locator("select[data-aassign]:visible").first
                sel.scroll_into_view_if_needed(timeout=3000)
                sel.select_option("ui", timeout=3000)
                break
            except Exception:
                if i == 4:
                    raise
                pg.wait_for_timeout(300)
        pg.wait_for_selector("#agDlg[open] #agPrompt", state="attached")
        self.assertTrue(pg.evaluate("$('agDlg').classList.contains('side') && !$('agDlg').matches(':modal')"))
        box = pg.locator("#agDlg").bounding_box()
        self.assertGreater(box["x"], 300)                                    # rechts, nicht in der Mitte über allem
        pg.locator('.tab[data-view="focus"]').click()                        # daneben klicken geht und schliesst nicht
        self.wait_js("!document.getElementById('viewFocus').hidden")
        self.assertTrue(pg.evaluate("$('agDlg').open"))
        pg.keyboard.press("Escape")
        self.wait_js("!$('agDlg').open")

    def test_detail_clicks_copy_and_explain(self):
        """0.39: Im Detail-Panel kopiert ein Klick auf Branch-Code, Chips mit Erklärung zeigen sie (tote Klicks im Nutzungsbericht)."""
        pg = self.pg
        self.ctx.grant_permissions(["clipboard-read", "clipboard-write"])
        q = "focusEntries().find(e => e.t === 'card' && (e.c.items || []).some(i => i.branch))"
        self.wait_js(q, 15000)
        pg.evaluate("openFx((%s).id)" % q)
        code = pg.locator("#fx code[data-copy]").first
        code.wait_for()
        want = code.get_attribute("data-copy")
        code.click()
        self.wait_js("[...document.querySelectorAll('.toast')].some(t => t.textContent === 'Kopiert')")
        self.assertEqual(pg.evaluate("navigator.clipboard.readText()"), want)
        chip = pg.locator("#fx .chip[title]").first
        if chip.count():
            title = chip.get_attribute("title")
            chip.click()
            self.wait_js("[...document.querySelectorAll('.toast')].some(t => t.textContent === %s)" % json.dumps(title))


class Terms(UiCase):
    def test_score_switch_and_areas(self):
        """E3/E4 (0.35): Spielstand abschaltbar, «Bereiche und Wochenziel», kein «Fokus-Modus» mehr."""
        pg = self.pg
        self.tab("Einstellungen")
        self.wait_js("!!document.getElementById('ft-score')")
        txt = pg.locator("#viewSettings").inner_text()
        self.assertIn("Fokus: Bereiche, Wochenziel, Spielstand", txt)      # 0.35.1: Spielstand-Schalter steht hier, nicht unter Weiteres
        self.assertNotIn("Fokusbereiche", txt)
        sec = pg.locator("#s-focusareas")
        self.assertEqual(sec.locator("#ft-score").count(), 1)
        self.assertEqual(pg.locator("#s-more #ft-score").count(), 0)
        self.tab("Fokus")
        self.assertNotIn("Fokus-Modus", pg.locator("#viewFocus").inner_text())
        self.assertEqual(pg.locator("#viewFocus .lvl").count(), 0)


if __name__ == "__main__":
    unittest.main()
