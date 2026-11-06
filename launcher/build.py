#!/usr/bin/env python3
"""Baut den Launcher als Python-Zipapp: dist/tinyops-launcher.pyz (läuft mit jedem Python 3.10+, unter Windows per Doppelklick).
Die nativen Programme (Linux, macOS, Windows .exe) baut die GitHub Action .github/workflows/release.yml mit PyInstaller."""
import shutil
import sys
import tempfile
import zipapp
from pathlib import Path

HERE = Path(__file__).resolve().parent


def build(out=None):
    out = Path(out or HERE.parent / "dist" / "tinyops-launcher.pyz")
    out.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as t:
        shutil.copy(HERE / "tinyops_launcher.py", Path(t) / "__main__.py")
        zipapp.create_archive(t, out, interpreter="/usr/bin/env python3")
    return out


if __name__ == "__main__":
    print(build(sys.argv[1] if len(sys.argv) > 1 else None))
