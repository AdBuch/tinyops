"""Oberfläche zusammensetzen (0.39). Ohne Build-Schritt: static/index.html hat zwei Platzhalter, dort setzt der Server
static/app.css und die Dateien aus static/js in fester Reihenfolge ein. Das Ergebnis ist eine Seite mit einem Skript,
genau wie bis 0.38. So bleibt das Verhalten gleich (Funktionen sind im ganzen Skript bekannt), und die Quelle ist trotzdem
nach Ansichten getrennt.

Reihenfolge: Bausteine zuerst, «boot» als letztes. Eine neue Datei in static/js muss hier stehen (tests/test_v39.py)."""
from pathlib import Path

PARTS = ("core", "help", "lists", "board", "agents", "time", "qa", "shell", "settings", "update", "pair",
         "focus", "detail", "session", "workspaces", "ux", "boot")
CSS_MARK, JS_MARK = "<!-- tinyops:css -->", "<!-- tinyops:js -->"


def script(base):
    """Das ganze Skript, wie es im Browser läuft."""
    js = Path(base) / "static" / "js"
    return "".join((js / ("%s.js" % p)).read_text(encoding="utf-8") for p in PARTS)


def page(base):
    """Die fertige Seite als Text."""
    st = Path(base) / "static"
    html = (st / "index.html").read_text(encoding="utf-8")
    if CSS_MARK not in html or JS_MARK not in html:
        raise ValueError("static/index.html: Platzhalter für CSS oder Skript fehlt")
    css = (st / "app.css").read_text(encoding="utf-8")
    return html.replace(CSS_MARK, "<style>\n" + css + "</style>", 1).replace(JS_MARK, "<script>\n" + script(base) + "</script>", 1)


def source(base):
    """Alles, was zur Oberfläche gehört, für Tests, die nach Texten suchen."""
    return page(base)
