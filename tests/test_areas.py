"""0.38: App ist in Bereiche zerlegt (area_*.py). Dieser Test hält die Grenzen fest:
* Jeder Bereich ruft nur die Methoden anderer Bereiche auf, die er in USES nennt. Neue Querzugriffe fallen so auf.
* server.py bleibt unter 1'500 Zeilen, kein Bereich über 1'000.
* Keine Methode steht doppelt (in zwei Bereichen oder im Kern und in einem Bereich).
"""
import ast
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _cls(path):
    t = ast.parse(path.read_text(encoding="utf-8"))
    return [n for n in t.body if isinstance(n, ast.ClassDef)]


class Areas(unittest.TestCase):
    def setUp(self):
        self.areas = {}
        for p in sorted(ROOT.glob("area_*.py")):
            c = _cls(p)[0]
            own = {n.name for n in c.body if isinstance(n, ast.FunctionDef)} | {n.targets[0].id for n in c.body if isinstance(n, ast.Assign)}
            used = {n.attr for n in ast.walk(c) if isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name) and n.value.id == "self"}
            uses = next(ast.literal_eval(n.value) for n in c.body if isinstance(n, ast.Assign) and n.targets[0].id == "USES")
            self.areas[p.stem] = (own - {"USES"}, used, uses)

    def test_cross_calls_are_declared(self):
        owner = {m: a for a, (own, _, _) in self.areas.items() for m in own}
        for a, (own, used, uses) in self.areas.items():
            got = {}
            for u in sorted(used):
                if u in owner and owner[u] != a:
                    got.setdefault(owner[u], []).append(u)
            self.assertEqual({k: tuple(sorted(v)) for k, v in got.items()}, {k: tuple(sorted(v)) for k, v in uses.items()},
                             "%s: Aufrufe in andere Bereiche passen nicht zu USES" % a)

    def test_no_method_twice(self):
        seen = {}
        app = next(c for c in _cls(ROOT / "server.py") if c.name == "App")
        core = {n.name for n in app.body if isinstance(n, ast.FunctionDef)}
        for a, (own, _, _) in self.areas.items():
            for m in own:
                self.assertNotIn(m, seen, "%s steht in %s und %s" % (m, seen.get(m), a))
                self.assertNotIn(m, core, "%s steht im Kern und in %s" % (m, a))
                seen[m] = a

    def test_sizes(self):
        n = len((ROOT / "server.py").read_text(encoding="utf-8").splitlines())
        self.assertLess(n, 1500, "server.py: %d Zeilen" % n)
        for p in ROOT.glob("area_*.py"):
            self.assertLess(len(p.read_text(encoding="utf-8").splitlines()), 1000, p.name)


if __name__ == "__main__":
    unittest.main()
