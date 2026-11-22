"""0.39: Oberfläche zerlegt (ui.py setzt sie zusammen), QR-Code beim Koppeln, Agentenfenster als Seitenpanel, Klicks im Detail-Panel."""
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import qr  # noqa: E402
import ui  # noqa: E402


class Parts(unittest.TestCase):
    def test_every_part_listed_and_small(self):
        js = ROOT / "static" / "js"
        self.assertEqual(sorted(p.stem for p in js.glob("*.js")), sorted(ui.PARTS), "jede Datei in static/js steht in ui.PARTS und umgekehrt")
        self.assertEqual(ui.PARTS[0], "core")
        self.assertEqual(ui.PARTS[-1], "boot")
        for f in [ROOT / "static" / "index.html", ROOT / "static" / "app.css"] + [js / ("%s.js" % p) for p in ui.PARTS]:
            n = len(f.read_text(encoding="utf-8").splitlines())
            self.assertLess(n, 1200, "%s hat %d Zeilen (Grenze 1'200)" % (f.name, n))

    def test_page_is_one_script_like_before(self):
        page = ui.page(ROOT)
        self.assertNotIn(ui.CSS_MARK, page)
        self.assertNotIn(ui.JS_MARK, page)
        self.assertEqual(page.count("<script>"), 1)
        self.assertEqual(page.count("<style>"), 1)
        self.assertIn("async function api(", page)
        self.assertIn("function renderFocus(", page)
        boot = (ROOT / "static" / "js" / "boot.js").read_text(encoding="utf-8")
        self.assertIn("load();", boot)                          # Start erst, wenn alles geladen ist
        for p in ui.PARTS[:-1]:
            self.assertNotRegex((ROOT / "static" / "js" / ("%s.js" % p)).read_text(encoding="utf-8"), r"(?m)^load\(\);", p)

    @unittest.skipUnless(shutil.which("node"), "node fehlt")
    def test_script_syntax(self):
        with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False, encoding="utf-8") as f:
            f.write(ui.script(ROOT))
        r = subprocess.run(["node", "--check", f.name], capture_output=True, text=True)
        os.unlink(f.name)
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_missing_mark_is_an_error(self):
        d = Path(tempfile.mkdtemp())
        shutil.copytree(ROOT / "static", d / "static")
        (d / "static" / "index.html").write_text("<html></html>", encoding="utf-8")
        with self.assertRaises(ValueError):
            ui.page(d)


class Qr(unittest.TestCase):
    def test_reed_solomon_known_vector(self):
        """Beispiel aus der Norm-Literatur (Version 1-M, «HELLO WORLD» alphanumerisch): 16 Daten-, 10 Korrektur-Codewörter."""
        data = [32, 91, 11, 120, 209, 114, 220, 77, 67, 64, 236, 17, 236, 17, 236, 17]
        self.assertEqual(qr._rs_remainder(data, qr._rs_divisor(10)), [196, 35, 39, 119, 235, 215, 231, 226, 93, 23])

    def test_sizes_and_limits(self):
        self.assertEqual(len(qr.matrix("x")), 21)                                      # Version 1
        self.assertEqual(len(qr.matrix("https://laptop.tail.ts.net/pair#code=ABCD-EFGH")), 33)   # Version 4
        self.assertEqual(len(qr.matrix("y" * 213)), 57)                                # Version 10, das Maximum
        with self.assertRaises(qr.QrError):
            qr.matrix("y" * 214)

    def test_finder_and_format(self):
        m = qr.matrix("https://laptop.tail.ts.net/pair#code=ABCD-EFGH")
        n = len(m)
        for x0, y0 in ((0, 0), (n - 7, 0), (0, n - 7)):                                # drei Suchmuster 7×7
            self.assertTrue(all(m[y0][x0 + i] and m[y0 + 6][x0 + i] and m[y0 + i][x0] and m[y0 + i][x0 + 6] for i in range(7)))
            self.assertTrue(all(m[y0 + 2 + i][x0 + 2 + j] for i in range(3) for j in range(3)))
        self.assertTrue(m[n - 8][8])                                                   # das immer dunkle Modul
        fmt = [m[i][8] for i in range(6)] + [m[7][8], m[8][8], m[8][7]] + [m[8][14 - i] for i in range(9, 15)]   # erste Kopie, Bit 0 zuerst
        bits = sum(int(b) << i for i, b in enumerate(fmt)) ^ 0x5412
        self.assertEqual(bits >> 13, 0, "Fehlerkorrektur M")

    def test_svg(self):
        s = qr.svg("https://x.example/pair#code=AB")
        self.assertTrue(s.startswith("<svg") and s.endswith("</svg>"))
        self.assertNotIn("<script", s)

    def test_decodes(self):
        try:
            import cv2
            import numpy as np
            det = cv2.QRCodeDetectorAruco() if hasattr(cv2, "QRCodeDetectorAruco") else cv2.QRCodeDetector()
        except ImportError:
            self.skipTest("OpenCV fehlt")
        for t in ("https://laptop.tail.ts.net/pair#code=K7QX-M2PA", "a" * 107, "https://beispiel.example:8443/pair#code=ABCD-EFGH" + "x" * 90):
            m = qr.matrix(t)
            s, q = 8, 4
            img = np.full(((len(m) + 2 * q) * s,) * 2, 255, np.uint8)
            for y, row in enumerate(m):
                for x, v in enumerate(row):
                    if v:
                        img[(y + q) * s:(y + q + 1) * s, (x + q) * s:(x + q + 1) * s] = 0
            self.assertEqual(det.detectAndDecode(img)[0], t)


def _port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class PairQr(unittest.TestCase):
    """Echter Server: «Code erzeugen» liefert den QR-Code mit Adresse und Code; die Kopplungsseite setzt den Code ein."""

    @classmethod
    def setUpClass(cls):
        cls.d = Path(tempfile.mkdtemp())
        cls.port = _port()
        (cls.d / "config.json").write_text(json.dumps({"data_dir": str(cls.d / "data"), "port": cls.port, "app": {"phone_url": "https://laptop.tail.ts.net"}}))
        env = dict(os.environ, TINYOPS_NO_WATCHDOG="1", TINYOPS_HOME=str(cls.d / "home"))
        cls.srv = subprocess.Popen([sys.executable, str(ROOT / "server.py"), "--demo", "--config", str(cls.d / "config.json")], cwd=ROOT, env=env,
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(100):
            try:
                urllib.request.urlopen("http://127.0.0.1:%d/healthz" % cls.port, timeout=1)
                break
            except OSError:
                time.sleep(0.2)

    @classmethod
    def tearDownClass(cls):
        cls.srv.terminate()
        cls.srv.wait(5)

    def call(self, method, path, body=None):
        req = urllib.request.Request("http://127.0.0.1:%d%s" % (self.port, path), method=method,
                                     headers={"X-Requested-With": "tinyops", "Content-Type": "application/json"},
                                     data=json.dumps(body).encode() if body is not None else None)
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.read()

    def test_code_comes_with_qr(self):
        r = json.loads(self.call("POST", "/api/pair/start", {}))
        self.assertEqual(r["link"], "https://laptop.tail.ts.net/pair#code=" + r["code"])
        self.assertTrue(r["qr"].startswith("<svg"))
        self.assertIn("pqr", ui.page(ROOT))
        page = self.call("GET", "/pair").decode()
        self.assertIn("location.hash", page)
        self.assertIn("history.replaceState", page)            # der Code bleibt nicht in der Adresse stehen


if __name__ == "__main__":
    unittest.main()
