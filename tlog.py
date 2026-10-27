"""Logging für tinyops: Datei mit Rotation plus Konsole, Secrets werden aus jeder Zeile geschwärzt.

Logger-Namen: tinyops.http, tinyops.gitlab, tinyops.jira, tinyops.refresh, tinyops.job, tinyops.access,
tinyops.setup. Dateien liegen standardmäßig in ~/.config/tinyops/logs (Rechte 700/600), nie im Projektordner,
damit sie nicht versehentlich eingecheckt oder mitgezippt werden.
"""
import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

import secretstore as store

ROOT = "tinyops"
FILE_NAME = "tinyops.log"
LEVELS = {"debug": logging.DEBUG, "info": logging.INFO, "warning": logging.WARNING, "error": logging.ERROR}


class ScrubFormatter(logging.Formatter):
    """Schwärzt Secrets in der fertigen Zeile, auch in Tracebacks."""

    def format(self, record):
        return store.scrub(super().format(record))


def log_dir(cfg=None):
    custom = (cfg or {}).get("log_dir") or os.environ.get("TINYOPS_LOG_DIR")
    return Path(custom).expanduser() if custom else store.home_dir() / "logs"


def log_file(cfg=None):
    return log_dir(cfg) / FILE_NAME


def get(name):
    return logging.getLogger("%s.%s" % (ROOT, name))


def setup(cfg=None, level=None, console=True):
    """Richtet Datei- und Konsolenlog ein. Das Dateilog schreibt immer mindestens INFO, mit -v alles (DEBUG)."""
    cfg = cfg or {}
    name = str(level or cfg.get("log_level") or "info").lower()
    lvl = LEVELS.get(name, logging.INFO)
    root = logging.getLogger(ROOT)
    root.setLevel(logging.DEBUG)
    root.propagate = False
    for h in list(root.handlers):
        root.removeHandler(h)
        h.close()

    fmt = ScrubFormatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s", "%Y-%m-%d %H:%M:%S")
    problem = None
    try:
        d = log_dir(cfg)
        d.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(d, 0o700)
        except OSError:
            pass
        path = d / FILE_NAME
        if not path.exists():
            fd = os.open(str(path), os.O_WRONLY | os.O_CREAT, 0o600)   # Rechte 600 schon beim Anlegen
            os.close(fd)
        fh = RotatingFileHandler(str(path), maxBytes=int(float(cfg.get("log_max_mb", 2)) * 1024 * 1024),
                                 backupCount=int(cfg.get("log_backups", 5)), encoding="utf-8")
        fh.setLevel(lvl)
        fh.setFormatter(fmt)
        root.addHandler(fh)
    except OSError as e:
        problem = "Logdatei nicht beschreibbar (%s), es bleibt bei der Konsole." % e
    if console:
        ch = logging.StreamHandler(sys.stderr)
        ch.setLevel(lvl)
        ch.setFormatter(ScrubFormatter("%(asctime)s %(levelname)-7s %(message)s", "%H:%M:%S"))
        root.addHandler(ch)
    if problem:
        get("setup").warning(problem)
    return log_file(cfg) if not problem else None


def tail(cfg=None, lines=200, min_level="debug"):
    """Letzte Zeilen der aktuellen Logdatei (bereits geschwärzt). Mehrzeilige Tracebacks bleiben beim Eintrag."""
    path = log_file(cfg)
    if not path.exists():
        return []
    try:
        with open(path, "rb") as f:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            f.seek(max(0, size - 512 * 1024))
            raw = f.read().decode("utf-8", errors="replace")
    except OSError:
        return []
    out = store.scrub(raw).splitlines()
    want = LEVELS.get(min_level, logging.DEBUG)
    if want > logging.DEBUG:
        keep, cur = [], True
        for ln in out:
            parts = ln.split(" ", 3)
            lvl = parts[2].strip().lower() if len(parts) > 2 else ""
            if lvl in LEVELS:
                cur = LEVELS[lvl] >= want
            if cur:
                keep.append(ln)
        out = keep
    return out[-max(1, min(int(lines), 2000)):]
