"""0.35.2: App koppeln. QR-Code, Einmal-Code gegen Geräte-Token, App-Schnittstelle mit eigenem Schutz."""
import http.client
import json
import sys
import tempfile
import threading
import unittest
import urllib.parse
from http.server import ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import devices  # noqa: E402
import qr  # noqa: E402
import server  # noqa: E402

try:
    import cv2
    import numpy
except ImportError:      # ohne OpenCV wird nur der Aufbau geprüft, nicht das Zurücklesen
    cv2 = None


def decode(matrix):
    for scale in (8, 6, 10):
        n, border = len(matrix), 4
        img = numpy.full(((n + 2 * border) * scale,) * 2, 255, numpy.uint8)
        for y, row in enumerate(matrix):
            for x, dark in enumerate(row):
                if dark:
                    img[(y + border) * scale:(y + border + 1) * scale, (x + border) * scale:(x + border + 1) * scale] = 0
        text = cv2.QRCodeDetector().detectAndDecode(img)[0]
        if text:
            return text
    return ""


class Qr(unittest.TestCase):
    def test_size_grows_with_text(self):
        self.assertEqual(len(qr.matrix("a")), 21)                   # Version 1
        self.assertEqual(len(qr.matrix("a" * 15)), 25)              # 14 Bytes passen in Version 1, 15 nicht
        self.assertEqual(len(qr.matrix("a" * 213)), 57)             # Version 10
        with self.assertRaises(ValueError):
            qr.matrix("a" * 214)

    def test_finder_and_timing(self):
        m = qr.matrix("tinyops")
        self.assertTrue(all(m[0][x] for x in range(7)))             # oberer Rand des Suchmusters
        self.assertFalse(any(m[7][x] for x in range(8)))            # Trennlinie
        self.assertEqual([m[6][x] for x in range(8, 13)], [True, False, True, False, True])
        self.assertTrue(m[len(m) - 8][8])                           # das immer dunkle Modul

    def test_svg(self):
        s = qr.svg("tinyops")
        self.assertTrue(s.startswith("<svg") and s.endswith("</svg>"))
        self.assertIn('viewBox="0 0 29 29"', s)                     # 21 Module plus Ruhezone
        self.assertNotIn("<script", s)

    @unittest.skipUnless(cv2, "OpenCV fehlt")
    def test_reads_back(self):
        link = devices.pair_link("http://localhost:8000", "https://tinyops.heim.example:8765", "ABCD-2345")
        texts = ["a", "Grüezi", link, "x" * 60, "y" * 120, "z" * 180, "https://example.org/?q=" + "0123456789" * 19]
        for t in texts:
            self.assertEqual(decode(qr.matrix(t)), t, "Länge %d" % len(t))


class Pairing(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.d = devices.Devices(Path(self.tmp.name) / "t.db")

    def tearDown(self):
        self.tmp.cleanup()

    def test_code_once(self):
        p = self.d.pair_start(now=1000)
        self.assertRegex(p["code"], r"^[A-Z2-9]{4}-[A-Z2-9]{4}$")
        token, dev = self.d.pair_finish(p["code"].lower().replace("-", " "), "  Pixel   8 ", now=1010)       # Schreibweise egal
        self.assertEqual(dev["name"], "Pixel 8")
        self.assertEqual(self.d.check(token)["id"], dev["id"])
        with self.assertRaises(devices.PairError):                  # verbraucht
            self.d.pair_finish(p["code"], "zweites", now=1011)
        self.assertEqual(len(self.d.list()), 1)

    def test_expired_and_without_code(self):
        with self.assertRaises(devices.PairError):
            self.d.pair_finish("ABCD-EFGH", "x")
        p = self.d.pair_start(now=1000)
        self.assertTrue(self.d.pending(now=1000 + devices.CODE_TTL - 1))
        self.assertFalse(self.d.pending(now=1000 + devices.CODE_TTL))
        with self.assertRaises(devices.PairError):
            self.d.pair_finish(p["code"], "x", now=1000 + devices.CODE_TTL)

    def test_wrong_tries_burn_the_code(self):
        p = self.d.pair_start(now=1000)
        for i in range(devices.CODE_TRIES):
            with self.assertRaises(devices.PairError):
                self.d.pair_finish("AAAA-AAAA", "x", now=1001)
        with self.assertRaises(devices.PairError):                  # auch der richtige Code geht jetzt nicht mehr
            self.d.pair_finish(p["code"], "x", now=1002)
        self.assertEqual(self.d.list(), [])

    def test_new_code_replaces_old(self):
        old = self.d.pair_start(now=1000)
        new = self.d.pair_start(now=1001)
        with self.assertRaises(devices.PairError):
            self.d.pair_finish(old["code"], "x", now=1002)
        self.d.pair_finish(new["code"], "x", now=1003)

    def test_token_only_as_hash_and_revoke(self):
        p = self.d.pair_start()
        token, dev = self.d.pair_finish(p["code"], "Handy")
        raw = (Path(self.tmp.name) / "t.db").read_bytes()
        self.assertNotIn(token.encode(), raw)
        self.assertNotIn("token_hash", json.dumps(self.d.list()))
        self.assertIsNone(self.d.check(token + "x"))
        self.assertIsNone(self.d.check(""))
        self.assertEqual(self.d.revoke(dev["id"]), "Handy")
        self.assertIsNone(self.d.check(token))
        self.assertIsNone(self.d.revoke(dev["id"]))
        self.assertEqual(self.d.list(), [])

    def test_link_and_origin(self):
        link = devices.pair_link("http://localhost:8000/", "http://127.0.0.1:8765", "ABCD-2345")
        self.assertEqual(link, "http://localhost:8000/#pair=ABCD-2345@http%3A%2F%2F127.0.0.1%3A8765")
        self.assertEqual(devices.clean_origin("HTTPS://Home.Example:8443/pfad?x=1"), "https://home.example:8443")
        for bad in ("", "javascript:alert(1)", "ftp://x", "http://user:pw@host", "//host", None):
            self.assertEqual(devices.clean_origin(bad), "")


class Http(unittest.TestCase):
    """Der echte Handler im Demo-Modus, mit Zugriffstoken fürs Panel: Die App kommt trotzdem nur mit ihrem eigenen Token durch."""
    APP = "http://localhost:8000"

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        cfg = server.load_config(None)
        cfg["data_dir"] = self.tmp.name
        self.app = server.App(cfg, True, {"access_token": "panel-geheim"}, Path("/nonexistent/c.json"))
        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), server.make_handler(self.app))
        self.port = self.srv.server_address[1]
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()

    def tearDown(self):
        self.srv.shutdown()
        self.srv.server_close()
        self.tmp.cleanup()

    def call(self, method, path, body=None, headers=None, host=None):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=30)
        h = dict(headers or {})
        if host:
            h["Host"] = host
        data = json.dumps(body).encode() if body is not None else None
        if data:
            h["Content-Type"] = "application/json"
        c.request(method, path, data, h)
        r = c.getresponse()
        raw = r.read()
        c.close()
        return r.status, (json.loads(raw) if raw else {}), dict(r.getheaders())

    def panel(self, method, path, body=None):
        import hashlib
        session = hashlib.sha256(b"tinyops-session:panel-geheim").hexdigest()
        return self.call(method, path, body, {"Cookie": "tinyops=" + session, "X-Requested-With": "tinyops"})

    def pair(self, name="Pixel"):
        st, p, _ = self.panel("POST", "/api/devices/pair", {"base": "http://127.0.0.1:%d" % self.port})
        self.assertEqual(st, 200, p)
        st, res, _ = self.call("POST", "/api/pair", {"code": p["code"], "name": name}, {"Origin": self.APP})
        self.assertEqual(st, 200, res)
        return p, res

    def test_pair_and_read_focus(self):
        p, res = self.pair()
        self.assertIn("<svg", p["qr"])
        self.assertFalse(p["insecure"])                             # 127.0.0.1 gilt als lokal
        code, _, inst = urllib.parse.urlsplit(p["link"]).fragment[len("pair="):].partition("@")
        self.assertEqual((code, urllib.parse.unquote(inst)), (p["code"], "http://127.0.0.1:%d" % self.port))
        self.assertEqual(res["instance"]["version"], server.VERSION)
        auth = {"Authorization": "Bearer " + res["token"], "Origin": self.APP}

        st, hello, hdr = self.call("GET", "/api/app/hello", headers=auth)
        self.assertEqual((st, hello["device"]["name"]), (200, "Pixel"))
        self.assertEqual(hdr["Access-Control-Allow-Origin"], self.APP)

        self.app.overview()                                         # Demo-Daten fertig laden
        st, focus, _ = self.call("GET", "/api/app/focus", headers=auth)
        self.assertEqual(st, 200)
        keys = [i["key"] for i in focus["items"]]
        self.assertIn("DLP-102", keys)
        it = next(i for i in focus["items"] if i["key"] == "DLP-102")
        self.assertEqual((it["title"] != "", it["phase"], it["kind"], it["next"]), (True, "Testen", "do", "Manuell testen"))
        kinds = [i["kind"] for i in focus["items"]]
        self.assertEqual(kinds, sorted(kinds, key=lambda k: {"blocked": 0, "do": 1, "wait": 2}.get(k, 3)))      # du bist dran vor warten
        self.assertTrue(focus["helpdesk"])
        dump = json.dumps(focus)
        for secret in ("panel-geheim", res["token"], "git switch", self.tmp.name):
            self.assertNotIn(secret, dump)

        st, state, _ = self.panel("GET", "/api/devices")
        self.assertEqual(([d["name"] for d in state["devices"]], state["pending"]), (["Pixel"], False))
        self.assertGreater(state["devices"][0]["last_seen"], 0)

    def test_app_needs_its_own_token(self):
        _, res = self.pair()
        for headers in ({}, {"Authorization": "Bearer falsch"}, {"Authorization": "Bearer panel-geheim"}, {"Authorization": res["token"]}):
            self.assertEqual(self.call("GET", "/api/app/focus", headers=headers)[0], 401, headers)
        # und umgekehrt: Das Geräte-Token öffnet das Panel nicht
        st, _, _ = self.call("GET", "/api/overview", headers={"Authorization": "Bearer " + res["token"]})
        self.assertEqual(st, 401)
        st, _, _ = self.call("GET", "/api/devices", headers={"Authorization": "Bearer " + res["token"]})
        self.assertEqual(st, 401)
        self.assertEqual(self.call("POST", "/api/app/focus", {}, {"Authorization": "Bearer " + res["token"]})[0], 404)   # nur lesen

    def test_revoke(self):
        _, res = self.pair()
        auth = {"Authorization": "Bearer " + res["token"]}
        self.assertEqual(self.call("GET", "/api/app/hello", headers=auth)[0], 200)
        st, state, _ = self.panel("POST", "/api/devices/revoke", {"id": res["device"]["id"]})
        self.assertEqual((st, state["devices"]), (200, []))
        st, body, _ = self.call("GET", "/api/app/hello", headers=auth)
        self.assertEqual(st, 401)
        self.assertIn("nicht (mehr) gekoppelt", body["error"])
        self.assertEqual(self.panel("POST", "/api/devices/revoke", {"id": res["device"]["id"]})[0], 400)

    def test_origin_host_and_preflight(self):
        st, _, hdr = self.call("OPTIONS", "/api/app/focus", headers={"Origin": self.APP, "Access-Control-Request-Headers": "authorization"})
        self.assertEqual(st, 204)
        self.assertIn("Authorization", hdr["Access-Control-Allow-Headers"])
        st, body, hdr = self.call("OPTIONS", "/api/pair", headers={"Origin": "https://boese.example"})
        self.assertEqual(st, 403)
        self.assertNotIn("Access-Control-Allow-Origin", hdr)
        self.assertEqual(self.call("POST", "/api/pair", {"code": "x"}, {"Origin": "https://boese.example"})[0], 403)
        self.assertEqual(self.call("POST", "/api/pair", {"code": "x"}, host="boese.example")[0], 403)                 # DNS-Rebinding
        self.assertEqual(self.call("OPTIONS", "/api/overview")[0], 405)

    def test_pairing_needs_the_panel(self):
        st, _, _ = self.call("POST", "/api/devices/pair", {"base": "http://127.0.0.1"}, {"X-Requested-With": "tinyops"})
        self.assertEqual(st, 401)                                   # ohne Panel-Cookie kein QR-Code
        st, body, _ = self.panel("POST", "/api/devices/pair", {"base": "http://fremd.example:8765"})
        self.assertEqual(st, 400)                                   # fremde Adresse kommt nicht in den QR-Code
        st, body, _ = self.call("POST", "/api/pair", {"code": "AAAA-AAAA", "name": "x"})
        self.assertEqual(st, 400)
        self.assertIn("Kein gültiger Code", body["error"])

    def test_audit_has_pairing_without_secrets(self):
        p, res = self.pair("Tablet")
        self.call("POST", "/api/pair", {"code": "AAAA-AAAA"})
        self.panel("POST", "/api/devices/revoke", {"id": res["device"]["id"]})
        st, log, _ = self.panel("GET", "/api/audit")
        self.assertEqual(st, 200)
        dump = json.dumps(log, ensure_ascii=False)
        for action in ("app.pair_start", "app.pair", "app.revoke"):
            self.assertIn(action, dump)
        self.assertIn("Tablet", dump)
        self.assertNotIn(res["token"], dump)
        self.assertNotIn(p["code"], dump)

    def test_cancel(self):
        st, p, _ = self.panel("POST", "/api/devices/pair", {"base": "http://localhost:%d" % self.port})
        self.assertEqual(self.panel("GET", "/api/devices")[1]["pending"], True)
        self.assertEqual(self.panel("POST", "/api/devices/cancel", {})[1]["pending"], False)
        self.assertEqual(self.call("POST", "/api/pair", {"code": p["code"]})[0], 400)


if __name__ == "__main__":
    unittest.main()
