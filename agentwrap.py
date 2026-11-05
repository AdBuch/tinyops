#!/usr/bin/env python3
"""Hülle für lokal gestartete Agenten (läuft losgelöst von tinyops, auch unter Windows ohne tmux).

Aufruf: agentwrap.py RUNDIR ID    (liest RUNDIR/ID.spec.json: {"argv": [...]} oder {"shell": "..."}, dazu "cwd" und optional "env")
Schreibt RUNDIR/ID.log (Ausgabe), ID.hb (Lebenszeichen alle 5 s), ID.pid (Prozess des Agenten) und zuletzt ID.exit (Exit-Code).
So kann tinyops den Stand ablesen, auch wenn es zwischendurch neu gestartet wurde.
"""
import json
import os
import subprocess
import sys
import threading
import time


def main():
    rundir, rid = sys.argv[1], sys.argv[2]
    p = lambda ext: os.path.join(rundir, "%s.%s" % (rid, ext))
    spec = json.load(open(p("spec.json"), encoding="utf-8"))
    stop = threading.Event()

    def beat():
        while not stop.is_set():
            try:
                with open(p("hb"), "w") as f:
                    f.write(str(time.time()))
            except OSError:
                pass
            stop.wait(5)
    threading.Thread(target=beat, daemon=True).start()
    rc = 127
    try:
        kw = {"cwd": spec.get("cwd") or None, "stdout": subprocess.PIPE, "stderr": subprocess.STDOUT, "stdin": subprocess.DEVNULL}
        if spec.get("env"):
            kw["env"] = dict(os.environ, **{str(k): str(v) for k, v in spec["env"].items()})
        if os.name == "nt":
            kw["creationflags"] = 0x00000200   # CREATE_NEW_PROCESS_GROUP
        else:
            kw["start_new_session"] = True
        with open(p("log"), "ab", buffering=0) as log:
            try:
                proc = subprocess.Popen(spec["shell"] if "shell" in spec else spec["argv"], shell="shell" in spec, **kw)
            except OSError as e:
                log.write(("[tinyops] Start fehlgeschlagen: %s\n" % e).encode("utf-8", "replace"))
                proc = None
            if proc:
                with open(p("pid"), "w") as f:
                    f.write(str(proc.pid))
                for chunk in iter(lambda: proc.stdout.read1(4096) if hasattr(proc.stdout, "read1") else proc.stdout.read(4096), b""):
                    log.write(chunk)
                rc = proc.wait()
    finally:
        stop.set()
        tmp = p("exit.tmp")
        with open(tmp, "w") as f:
            f.write(str(rc))
        os.replace(tmp, p("exit"))


if __name__ == "__main__":
    main()
