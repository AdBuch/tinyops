"""Shell-Skripte für einen Lauf, lokal und auf dem Zielhost gleich: Hilfsbefehle für den Agenten (fragen, belegen, berichten),
Worktree oder Export anlegen und aufräumen, Start in tmux, Stand, Bericht, Antworten.

0.40 aus agents.py gelöst; agents.py gibt alle Namen weiter."""
import json
import re
import shlex
from pathlib import Path

import secretscan
from agent_cmd import _sh_path, clean_text, remote_cmdline
from agent_rules import diff_counts

RUNNER = '''R="$HOME/.tinyops/runs"
ID="$1"
export R ID
{ "${SHELL:-/bin/sh}" -l -c 'PATH="$R/bin:$PATH"; TINYOPS_RUN_DIR="$R"; TINYOPS_RUN_ID="$ID"; PYTHONUNBUFFERED=1; export PATH TINYOPS_RUN_DIR TINYOPS_RUN_ID PYTHONUNBUFFERED; exec sh "$R/$ID.cmd"'; echo $? > "$R/$ID.exit.tmp"; mv "$R/$ID.exit.tmp" "$R/$ID.exit"; } 2>&1 | tee "$R/$ID.log"
'''


# ------------------------------------------------------------------ Hilfsskripte für den Agenten (0.18): fragen, belegen, berichten
# Sie liegen in $R/bin und stehen im PATH des Laufs. Reines POSIX-sh, ohne Python, damit sie auf jedem Zielhost laufen.
_HELPER_HEAD = r'''#!/bin/sh
R="${TINYOPS_RUN_DIR:-$HOME/.tinyops/runs}"; N="${TINYOPS_RUN_ID:-}"
case "$N" in ""|*[!0-9]*) echo "tinyops: TINYOPS_RUN_ID fehlt, das geht nur in einem Lauf aus tinyops." >&2; exit 2;; esac
j() { printf '%s' "$1" | tr '\n\r\t' '   ' | tr -d '\000-\037' | sed 's/\\/\\\\/g; s/"/\\"/g'; }
'''


HELPERS = {
    "tinyops-ask": _HELPER_HEAD + r'''# tinyops-ask [-n] [-d] [-t SEK] "Frage" ["Option" ...]   fragt den Menschen in tinyops und gibt die Antwort aus
# -d: eine Entscheidung (wird im Bericht und im Review als Entscheidung festgehalten)
# tinyops-ask --wait NR [-t SEK]                     wartet weiter auf die Antwort zu Frage NR
# Exit 3: noch keine Antwort nach SEK Sekunden (Standard 100). Dann mit --wait NR weiter warten, nicht neu fragen.
wait=1; to="${TINYOPS_ASK_TIMEOUT:-100}"; K=""; dec=false
while [ $# -gt 0 ]; do case "$1" in -n) wait=0; shift;; -d) dec=true; shift;; -t) to="$2"; shift 2;; --wait) K="$2"; shift 2;; *) break;; esac; done
case "$to" in ""|*[!0-9]*) to=100;; esac
if [ -z "$K" ]; then
  [ -n "$1" ] || { echo 'Aufruf: tinyops-ask [-n] [-t SEK] "Frage" ["Option" ...]' >&2; exit 2; }
  K=$(( $(cat "$R/$N.qn" 2>/dev/null || echo 0) + 1 )); echo "$K" > "$R/$N.qn"
  Q=$(j "$1"); shift; O=""
  for o in "$@"; do O="$O${O:+, }\"$(j "$o")\""; done
  b=true; [ "$wait" = 1 ] || b=false
  printf '{"id": %d, "question": "%s", "options": [%s], "blocking": %s, "decision": %s, "ts": %s}\n' "$K" "$Q" "$O" "$b" "$dec" "$(date +%s)" > "$R/$N.question.tmp" && mv "$R/$N.question.tmp" "$R/$N.question.json"
  [ "$wait" = 1 ] || { echo "$K"; exit 0; }
  echo "[tinyops] Frage $K gestellt. Warte auf die Antwort in tinyops ..." >&2
fi
case "$K" in ""|*[!0-9]*) echo "tinyops-ask: Fragenummer fehlt" >&2; exit 2;; esac
t=0
while [ ! -f "$R/$N.answer.$K" ]; do
  if [ "$to" -gt 0 ] && [ "$t" -ge "$to" ]; then echo "[tinyops] Noch keine Antwort auf Frage $K. Weiter warten mit: tinyops-ask --wait $K" >&2; exit 3; fi
  sleep 2; t=$((t + 2))
done
cat "$R/$N.answer.$K"
''',
    "tinyops-check": _HELPER_HEAD + r'''# tinyops-check BEFEHL [ARG ...]   führt den Befehl aus und hält Befehl, Exit-Code und Dauer als Beleg fest
[ $# -gt 0 ] || { echo "Aufruf: tinyops-check BEFEHL [ARG ...]" >&2; exit 2; }
t0=$(date +%s); "$@"; rc=$?; t1=$(date +%s)
printf '{"cmd": "%s", "exit": %d, "secs": %d, "ts": %d}\n' "$(j "$*")" "$rc" $((t1 - t0)) "$t1" >> "$R/$N.checks"
echo "[tinyops-check] Exit $rc nach $((t1 - t0)) s: $*" >&2
exit $rc
''',
    "tinyops-ak": _HELPER_HEAD + r'''# tinyops-ak NR erfüllt|offen|unklar ["Beleg oder Grund"]   meldet den Stand eines Akzeptanzkriteriums (AK1, AK2 …) an tinyops
# Auch: ok, erfuellt, done | offen, open, fail | unklar, unclear. Die letzte Meldung je Kriterium gilt.
k=$(printf '%s' "$1" | sed 's/^[Aa][Kk]//')
case "$k" in ""|*[!0-9]*) echo 'Aufruf: tinyops-ak NR erfüllt|offen|unklar ["Beleg oder Grund"]' >&2; exit 2;; esac
case "$2" in ok|OK|erf*|done|ja|pass*) s=ok;; offen|open|fail*|nein|nicht*) s=open;; unklar|unclear|block*|"?") s=unclear;;
  *) echo 'tinyops-ak: Stand fehlt. Erlaubt: erfüllt, offen, unklar' >&2; exit 2;; esac
printf '{"n": %d, "state": "%s", "note": "%s", "ts": %s}\n' "$k" "$s" "$(j "$3" | cut -c1-400)" "$(date +%s)" >> "$R/$N.ak"
echo "[tinyops] AK$k: $s" >&2
''',
    "tinyops-manual": _HELPER_HEAD + r'''# tinyops-manual "Schritt" "Erwartet"   beschreibt einen Testschritt, den der Mensch von Hand ausführt (Oberfläche, Ablauf, Daten)
[ -n "$1" ] || { echo 'Aufruf: tinyops-manual "Was tun" "Was soll passieren"' >&2; exit 2; }
printf '{"step": "%s", "expect": "%s", "ts": %s}\n' "$(j "$1" | cut -c1-300)" "$(j "$2" | cut -c1-300)" "$(date +%s)" >> "$R/$N.manual"
echo "[tinyops] manueller Testschritt notiert" >&2
''',
    "tinyops-report": _HELPER_HEAD + r'''# tinyops-report < bericht.md   oder   tinyops-report "Text"   speichert den Ergebnisbericht (Markdown, höchstens 20 KB)
if [ $# -gt 0 ]; then printf '%s\n' "$*"; else cat; fi | head -c 20000 > "$R/$N.summary.md.tmp" && mv "$R/$N.summary.md.tmp" "$R/$N.summary.md"
echo "[tinyops] Bericht gespeichert." >&2
''',
}


def helpers_script():
    """Shell, die die Hilfsskripte nach $R/bin schreibt (Teil des Startskripts auf dem Zielhost)."""
    out = ['mkdir -p "$R/bin"']
    for name, body in HELPERS.items():
        d = _delim(body)
        out.append("cat > \"$R/bin/%s\" <<'%s'\n%s%s\nchmod 755 \"$R/bin/%s\"" % (name, d, body, d, name))
    return "\n".join(out) + "\n"


def write_helpers(run_dir):
    b = Path(run_dir) / "bin"
    b.mkdir(parents=True, exist_ok=True)
    for name, body in HELPERS.items():
        f = b / name
        f.write_text(body, encoding="utf-8", newline="\n")
        try:
            f.chmod(0o755)
        except OSError:
            pass
    return b


def parse_question(text):
    """Frage aus <nr>.question.json. Ungültiges JSON zählt als Frage im Klartext (Nr 0 wird nie beantwortet erwartet)."""
    text = (text or "").strip()
    if not text:
        return None
    try:
        q = json.loads(text)
        if not isinstance(q, dict):
            raise ValueError
    except ValueError:
        return {"id": 1, "question": clean_text(text, 1000), "options": [], "blocking": True, "raw": True}
    try:
        qid = int(q.get("id") or 1)
    except (TypeError, ValueError):
        qid = 1
    opts = [clean_text(str(o), 200).strip() for o in (q.get("options") or []) if str(o).strip()][:8] if isinstance(q.get("options"), list) else []
    return {"id": qid, "question": clean_text(str(q.get("question") or ""), 1000).strip() or "(leere Frage)", "options": opts,
            "blocking": q.get("blocking") is not False, "decision": q.get("decision") is True}


def parse_checks(text):
    out = []
    for line in (text or "").splitlines()[-50:]:
        try:
            c = json.loads(line)
            out.append({"cmd": clean_text(str(c.get("cmd") or ""), 300).strip(), "exit": int(c.get("exit")), "secs": int(c.get("secs") or 0),
                        "ts": int(c.get("ts") or 0)})
        except (ValueError, TypeError, AttributeError):
            continue
    return out


def _delim(*texts):
    n = 0
    while True:
        d = "TINYOPS_EOF_%d" % n
        if not any(d in t for t in texts):
            return d
        n += 1


# ------------------------------------------------------------------ Isolation (Worktree oder Export) als Shell, lokal und remote gleich
def _resolve_base(base):
    b = shlex.quote(base or "")
    return ('BASE=%s; '
            'if [ -n "$BASE" ] && git -C "$REPO" rev-parse -q --verify "$BASE^{commit}" >/dev/null 2>&1; then :; '
            'elif [ -n "$BASE" ] && git -C "$REPO" rev-parse -q --verify "origin/$BASE^{commit}" >/dev/null 2>&1; then BASE="origin/$BASE"; '
            'else BASE=HEAD; fi\n') % b


def prepare_script(mode, repo_sh, root_sh, rid, branch, base, paths=()):
    """Setzt WD (Arbeitsordner des Agenten). Exit 41 Ordner fehlt, 43 kein Git, 44 Worktree, 45 Export. Erwartet R und ID."""
    rid = int(rid)
    s = "REPO=%s\n[ -d \"$REPO\" ] || { echo \"Arbeitsverzeichnis fehlt\" >&2; exit 41; }\n" % repo_sh
    if mode == "shared":
        return s + 'WD="$REPO"\n'
    s += 'command -v git >/dev/null 2>&1 || { echo "git fehlt" >&2; exit 43; }\n'
    s += 'git -C "$REPO" rev-parse --git-dir >/dev/null 2>&1 || { echo "kein Git-Repository" >&2; exit 43; }\n'
    s += "WD=%s/.tinyops-wt/%d\n" % (root_sh, rid)
    s += _resolve_base(base)
    s += 'mkdir -p "$(dirname "$WD")"\nrm -rf "$WD"\n'
    if mode == "worktree":
        s += ('git -C "$REPO" worktree add -q -b %s "$WD" "$BASE" >&2 || { echo "Worktree konnte nicht angelegt werden" >&2; exit 44; }\n'
              'git -C "$WD" rev-parse HEAD > "$R/$ID.base"\n') % shlex.quote(branch)
        return s
    q = " ".join(shlex.quote(p) for p in paths)
    s += ('mkdir -p "$WD"\n'
          'git -C "$REPO" archive --format=tar "$BASE" -- %s | tar -x -C "$WD" || { echo "Export der freigegebenen Pfade fehlgeschlagen (gibt es sie im Branch?)" >&2; exit 45; }\n'
          'git -C "$REPO" rev-parse "$BASE^{commit}" > "$R/$ID.base"\n'
          '( cd "$WD" && git init -q && git add -A && git -c user.name=tinyops -c user.email=tinyops@localhost commit -qm "tinyops: freigegebene Pfade" '
          '&& git rev-parse HEAD > "$R/$ID.init" ) >&2 || { echo "Export-Repository konnte nicht angelegt werden" >&2; exit 45; }\n') % q
    return s


def cleanup_script(mode, repo_sh, wt, rid):
    """Worktree: offene Änderungen als Commit auf dem Agenten-Branch sichern, dann Worktree entfernen (Branch bleibt). Export: Ordner löschen."""
    w = shlex.quote(wt)
    if mode == "worktree":
        return ('REPO=%s; WD=%s; if [ -d "$WD" ]; then cd "$WD" && git add -A && '
                '(git diff --cached --quiet || git -c user.name=tinyops -c user.email=tinyops@localhost commit -qm "tinyops: offener Stand von Lauf %d gesichert" --no-verify); '
                'cd / && git -C "$REPO" worktree remove --force "$WD"; fi; git -C "$REPO" worktree prune; true') % (repo_sh, w, int(rid))
    if mode == "export":
        return 'rm -rf %s; true' % w
    return "true"


def changes_script(wt):
    """Export: offene Änderungen committen und alle geänderten Dateien seit dem Export auflisten."""
    return ('cd %s && git add -A && (git diff --cached --quiet || git -c user.name=tinyops -c user.email=tinyops@localhost commit -qm "tinyops: Stand des Agenten" --no-verify) >/dev/null '
            '&& INIT=$(cat "$R/$ID.init") && git diff --name-only "$INIT" HEAD && git diff --binary "$INIT" HEAD > "$R/$ID.patch"') % shlex.quote(wt)


def apply_script(repo_sh, root_sh, rid, branch, message):
    """Export: Patch auf einem neuen Branch im echten Repo anwenden (eigener, kurzlebiger Worktree), dann den Worktree entfernen."""
    return ('REPO=%s; AW=%s/.tinyops-wt/%d-apply; BASE=$(cat "$R/$ID.base"); rm -rf "$AW"; '
            'git -C "$REPO" worktree add -q -b %s "$AW" "$BASE" >&2 || exit 44; '
            'if git -C "$AW" apply --index "$R/$ID.patch" >&2 && git -C "$AW" -c user.name=tinyops -c user.email=tinyops@localhost commit -qm %s --no-verify >&2; '
            'then git -C "$REPO" worktree remove --force "$AW"; echo applied; else git -C "$REPO" worktree remove --force "$AW"; git -C "$REPO" branch -D %s >/dev/null 2>&1; exit 46; fi'
            ) % (repo_sh, root_sh, int(rid), shlex.quote(branch), shlex.quote(message), shlex.quote(branch))


ISO_ERR = {41: "Das Arbeitsverzeichnis %s gibt es nicht. Repository dort klonen oder den Ordner beim Projekt/Agenten anpassen.",
           43: "%s ist kein Git-Repository (oder git fehlt). Für die Isolation braucht der Agent ein geklontes Repository.",
           44: "Der Worktree unter %s konnte nicht angelegt werden (Branch schon vorhanden? Repository gesperrt?).",
           45: "Der Export der freigegebenen Pfade aus %s ist fehlgeschlagen. Gibt es die Pfade im Ausgangs-Branch?",
           46: "Die Änderungen liessen sich nicht auf den Ausgangsstand von %s anwenden.",
           47: "Der Arbeitsordner des Laufs unter %s ist nicht mehr da. Weiterführen geht dann nur mit einer neuen Sitzung.",
           48: "Der Arbeitsordner unter %s liess sich nicht auf den neuen Stand des Entwicklers bringen (eigene Änderungen?)."}


def resume_prep_script(wd_sh, old_rid, sync=""):
    """0.40: Weiterführen in derselben Sitzung: derselbe Arbeitsordner, Ausgangsstand vom alten Lauf übernehmen.
    sync: Branch, auf den ein Review-Ordner vorgespult wird (der Entwickler hat nachgebessert). Erwartet R und ID."""
    return ("WD=%s\n[ -d \"$WD\" ] || { echo \"Arbeitsordner fehlt\" >&2; exit 47; }\n"
            "for x in base init; do [ -f \"$R/%d.$x\" ] && cp \"$R/%d.$x\" \"$R/$ID.$x\"; done\n"
            "SYNC=%s\nif [ -n \"$SYNC\" ]; then git -C \"$WD\" merge -q --ff-only \"$SYNC\" >&2 || exit 48; fi\n") % (wd_sh, int(old_rid), int(old_rid), shlex.quote(sync or ""))


def remote_start_script(agent, rid, workdir, prompt, prep=None, sess=None):
    cmdline = remote_cmdline(agent, sess)
    d1, d2 = _delim(prompt), _delim(cmdline)
    wd = _sh_path(workdir)
    return """set +e
R="$HOME/.tinyops/runs"
mkdir -p "$R"
chmod 700 "$R" 2>/dev/null || true
rm -f "$R/{rid}.exit" "$R/{rid}.log"
cat > "$R/{rid}.prompt" <<'{d1}'
{prompt}
{d1}
cat > "$R/{rid}.cmd" <<'{d2}'
{cmdline}
{d2}
cat > "$R/runner.sh" <<'TINYOPS_RUNNER_EOF'
{runner}TINYOPS_RUNNER_EOF
command -v tmux >/dev/null 2>&1 || {{ echo "tmux nicht gefunden" >&2; exit 42; }}
rm -f "$R/{rid}.question.json" "$R/{rid}.qn" "$R/{rid}.checks" "$R/{rid}.ak" "$R/{rid}.manual" "$R/{rid}.summary.md" "$R/{rid}.answer."*
{helpers}ID={rid}
{prep}echo "$WD" > "$R/{rid}.wd"
tmux new-session -d -s tinyops-{rid} -c "$WD" "sh '$R/runner.sh' {rid}"
echo "started $WD"
""".format(rid=int(rid), d1=d1, d2=d2, prompt=prompt, cmdline=cmdline, runner=RUNNER, helpers=helpers_script(), prep=prep if prep is not None else 'REPO=%s\n[ -d "$REPO" ] || {{ echo "Arbeitsverzeichnis fehlt" >&2; exit 41; }}\nWD="$REPO"\n'.replace("{{", "{").replace("}}", "}") % wd)


def remote_kill_script(rid):
    """Beendet die Sitzung samt Prozessen: erst TERM an die Prozessgruppe jedes Fensters, dann die Sitzung selbst."""
    return ('S=tinyops-%d; for p in $(tmux list-panes -s -t "$S" -F "#{pane_pid}" 2>/dev/null); do '
            'g=$(ps -o pgid= -p "$p" 2>/dev/null | tr -d " "); [ -n "$g" ] && kill -TERM -- "-$g" 2>/dev/null; pkill -TERM -P "$p" 2>/dev/null; done; '
            'sleep 1; tmux kill-session -t "$S" 2>/dev/null; true') % int(rid)


def remote_status_script(ids):
    return ('R="$HOME/.tinyops/runs"; for i in %s; do '
            'if [ -f "$R/$i.exit" ]; then echo "$i exit $(cat "$R/$i.exit")"; '
            'elif tmux has-session -t tinyops-$i 2>/dev/null; then echo "$i running"; '
            'elif [ -f "$R/$i.exit" ]; then echo "$i exit $(cat "$R/$i.exit")"; '
            'else echo "$i gone"; fi; '
            'if [ -f "$R/$i.question.json" ]; then printf "%%s q " "$i"; head -c 4000 "$R/$i.question.json" | tr "\\n\\r" "  "; echo; fi; done') % " ".join(str(int(i)) for i in ids)


def remote_report_script(rid):
    return ('R="$HOME/.tinyops/runs"; echo "@@SUMMARY"; head -c 20000 "$R/%d.summary.md" 2>/dev/null; echo; echo "@@CHECKS"; '
            'tail -n 50 "$R/%d.checks" 2>/dev/null; echo "@@AK"; tail -n 200 "$R/%d.ak" 2>/dev/null; echo "@@MANUAL"; tail -n 30 "$R/%d.manual" 2>/dev/null; '
            # 0.40: Kennung der Sitzung (Codex, Vibe nennen sie im Log) und das Ende des Logs für die Antwort im Gespräch
            'echo "@@SESSION"; head -c 400000 "$R/%d.log" 2>/dev/null | grep -a -o -m1 -E %s; echo "@@TAIL"; tail -c 48000 "$R/%d.log" 2>/dev/null; true'
            ) % (int(rid), int(rid), int(rid), int(rid), int(rid), shlex.quote(SESSION_GREP), int(rid))


SESSION_GREP = 'session id: *[0-9a-fA-F-]{20,60}|"session_id" *: *"[A-Za-z0-9_.:-]{6,100}"'


def result_script(wt, mode):
    """Was der Lauf am Code geändert hat, gegen den Ausgangsstand: Commits, Dateien, Umfang, offene Änderungen. Nur lesend. Erwartet R und ID."""
    base = "init" if mode == "export" else "base"
    return ('cd %s 2>/dev/null || exit 0; B=$(cat "$R/$ID.%s" 2>/dev/null); [ -n "$B" ] || exit 0; export GIT_OPTIONAL_LOCKS=0; '
            'echo "@@COMMITS"; git log --format="%%h %%s" "$B..HEAD" 2>/dev/null | head -n 30; '
            'echo "@@STAT"; git diff --shortstat "$B" 2>/dev/null; '
            'echo "@@FILES"; git diff --name-status "$B" 2>/dev/null | head -n 80; '
            'echo "@@DIRTY"; git status --porcelain 2>/dev/null | wc -l; '
            'echo "@@DIFF"; git diff -U0 --no-color "$B" 2>/dev/null | head -c 400000; true') % (shlex.quote(wt), base)


def parse_result(out):
    """Ausgabe von result_script lesen."""
    head, _, diff = (out or "").partition("@@DIFF")      # im Diff beginnen Hunk-Köpfe mit @@: er steht deshalb am Ende und wird vorher abgetrennt
    sec, cur = {"DIFF": diff.splitlines()}, None
    for line in head.splitlines():
        if line.startswith("@@"):
            cur = line[2:].strip()
            sec[cur] = []
        elif cur:
            sec[cur].append(line)
    if "COMMITS" not in sec:
        return None
    commits = [{"sha": x.split(" ", 1)[0], "subject": clean_text(x.split(" ", 1)[1] if " " in x else "", 200).strip()} for x in sec["COMMITS"] if x.strip()]
    files = []
    for x in sec.get("FILES") or []:
        p = x.split("\t")
        if len(p) >= 2:
            files.append({"st": p[0][:1], "path": clean_text(p[-1], 300).strip()})
    stat = " ".join(" ".join(sec.get("STAT") or []).split())
    try:
        dirty = int("".join(sec.get("DIRTY") or ["0"]).strip() or 0)
    except ValueError:
        dirty = 0
    secrets = secretscan.scan_diff("\n".join(sec.get("DIFF") or []), "Ergebnis des Laufs")[:20]
    counts = diff_counts(sec.get("DIFF") or [])
    for f in files:
        f.update(counts.get(f["path"]) or {})
    return {"commits": commits, "files": files, "stat": clean_text(stat, 200), "dirty": dirty, "secrets": secrets}


def answer_script(rid, qid, text):
    d = _delim(text)
    return ('R="$HOME/.tinyops/runs"; [ -d "$R" ] || exit 4\n'
            'cat > "$R/{rid}.answer.{q}.tmp" <<\'{d}\'\n{text}\n{d}\n'
            'mv "$R/{rid}.answer.{q}.tmp" "$R/{rid}.answer.{q}"\n'
            'grep -q \'"id": {q},\' "$R/{rid}.question.json" 2>/dev/null && rm -f "$R/{rid}.question.json"\necho ok\n').format(rid=int(rid), q=int(qid), d=d, text=text)
