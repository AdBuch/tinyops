"""Einen Branch in einen anderen übernehmen (0.41), z. B. den Branch eines Agenten in den Feature-Branch des Tickets.

Vier Wege: Fast-Forward (nur wenn der Ziel-Branch nicht weiter ist), Merge (Merge-Commit), Rebase (die Commits obendrauf,
gerade Geschichte) und Cherry-Pick (ausgewählte Commits). Alles passiert in deinem lokalen Checkout:

- Vorher `git fetch` beider Branches (nur lesend gegenüber GitLab).
- Gearbeitet wird in einem eigenen, losgelösten Worktree. Dein Arbeitsordner wird dabei nicht umgeschaltet.
- Erst wenn alles gutgeht, rückt der Ziel-Branch vor: nur vorwärts, nie umgeschrieben. Ist er in deinem Checkout ausgecheckt,
  muss der sauber sein und bekommt ein Fast-Forward; sonst wird nur die Referenz versetzt (mit Prüfung des alten Stands).
- Bei Konflikten wird alles zurückgenommen, oder auf Wunsch bleibt der Worktree zum Lösen in IntelliJ stehen.
- Gepusht wird nie. Der Push-Befehl steht im Ergebnis.
"""
import os
import re
import shutil
import subprocess
import time
from pathlib import Path

BRANCH_RE = re.compile(r"^(?!-)(?!.*\.\.)(?!.*//)[A-Za-z0-9._/-]{1,200}(?<![./])$")
HOW = {"ff": "Fast-Forward", "merge": "Merge", "rebase": "Rebase (Commits obendrauf)", "pick": "Cherry-Pick"}


class IntegrateError(Exception):
    pass


def _git(repo, *args, timeout=60, check=False):
    env = dict(os.environ, GIT_TERMINAL_PROMPT="0", GIT_EDITOR="true", LC_ALL="C")
    try:
        r = subprocess.run(["git", "-C", str(repo)] + list(args), capture_output=True, text=True, timeout=timeout,
                           stdin=subprocess.DEVNULL, env=env)
    except FileNotFoundError:
        raise IntegrateError("git ist nicht installiert.")
    except subprocess.TimeoutExpired:
        raise IntegrateError("git %s dauerte zu lange." % args[0])
    if check and r.returncode:
        raise IntegrateError("git %s: %s" % (args[0], (r.stderr or r.stdout).strip().splitlines()[-1:] or ["Fehler"]))
    return r.returncode, r.stdout.strip(), r.stderr.strip()


def _ok_branch(name, what):
    if not BRANCH_RE.match(name or ""):
        raise IntegrateError("%s «%s» ist kein gültiger Branch-Name." % (what, name))


def _rev(repo, ref):
    rc, out, _ = _git(repo, "rev-parse", "--verify", "-q", ref + "^{commit}")
    return out if rc == 0 else ""


def _is_anc(repo, a, b):
    return _git(repo, "merge-base", "--is-ancestor", a, b)[0] == 0


def _checked_out(repo, branch):
    """Pfad des Worktrees, in dem der Branch ausgecheckt ist, sonst leer."""
    rc, out, _ = _git(repo, "worktree", "list", "--porcelain")
    path = ""
    for ln in out.splitlines():
        if ln.startswith("worktree "):
            path = ln[9:]
        elif ln == "branch refs/heads/" + branch:
            return path
    return ""


def _dirty(path):
    return bool(_git(path, "status", "--porcelain", "--untracked-files=no")[1])


def push_cmd(repo, target):
    return "git -C %s push origin %s" % (_q(str(repo)), _q(target))


def _q(s):
    return s if re.match(r"^[A-Za-z0-9._/@:+-]+$", s) else "'" + s.replace("'", "'\\''") + "'"


class Integrator:
    def __init__(self, wt_base=None):
        self.wt_base = wt_base
        self.pending = {}        # Konflikte, die im Worktree gelöst werden: token → Zustand

    def _refs(self, repo, source, target, fetch=True):
        """Holt beide Branches und bestimmt Quelle und Ziel (lokal, sonst origin). Legt den lokalen Ziel-Branch bei Bedarf an
        und spult ihn vor, wenn origin weiter ist und er nicht abweicht."""
        _ok_branch(source, "Quelle")
        _ok_branch(target, "Ziel")
        if source == target:
            raise IntegrateError("Quelle und Ziel sind derselbe Branch.")
        if not Path(repo, ".git").exists():
            raise IntegrateError("%s ist kein Git-Checkout." % repo)
        if fetch:
            for b in (source, target):
                _git(repo, "fetch", "--quiet", "origin", "+refs/heads/%s:refs/remotes/origin/%s" % (b, b), timeout=90)
        src = _rev(repo, "refs/remotes/origin/" + source) or _rev(repo, "refs/heads/" + source)
        if not src:
            raise IntegrateError("Den Branch %s gibt es weder auf GitLab noch in deinem Checkout. Läuft der Agent auf einem anderen Rechner, "
                                 "muss er ihn erst pushen (Einstellungen → Agenten → «pusht seinen Branch»)." % source)
        local, remote = _rev(repo, "refs/heads/" + target), _rev(repo, "refs/remotes/origin/" + target)
        if not local and not remote:
            raise IntegrateError("Den Ziel-Branch %s gibt es nicht." % target)
        behind = bool(local and remote and local != remote and _is_anc(repo, local, remote))
        diverged = bool(local and remote and not _is_anc(repo, local, remote) and not _is_anc(repo, remote, local))
        return {"src": src, "local": local, "remote": remote, "base": remote if (behind or not local) else local, "behind": behind, "diverged": diverged}

    def plan(self, repo, source, target):
        """Was würde passieren? Commits, Fast-Forward möglich, erwartete Konflikte. Ändert nichts ausser dem Fetch."""
        r = self._refs(repo, source, target)
        base, src = r["base"], r["src"]
        rc, out, _ = _git(repo, "log", "--format=%H%x1f%h%x1f%s%x1f%an%x1f%cr", "-n", "60", "%s..%s" % (base, src))
        commits = [dict(zip(("sha", "short", "subject", "author", "when"), ln.split("\x1f"))) for ln in out.splitlines() if ln]
        rc, cherry, _ = _git(repo, "cherry", base, src)
        applied = {ln[2:] for ln in cherry.splitlines() if ln.startswith("- ")}
        for c in commits:
            c["applied"] = c["sha"] in applied
        commits.reverse()                                    # älteste zuerst, wie sie übernommen würden
        rc, mt, _ = _git(repo, "merge-tree", "--write-tree", "--name-only", "--no-messages", base, src)
        conflicts = None if rc not in (0, 1) else ([f for f in mt.splitlines()[1:] if f.strip()] if rc == 1 else [])
        co = _checked_out(repo, target)
        rc, stat, _ = _git(repo, "diff", "--shortstat", "%s...%s" % (base, src))
        return {"repo": str(repo), "source": source, "target": target, "commits": commits, "count": len(commits),
                "can_ff": _is_anc(repo, base, src), "up_to_date": _is_anc(repo, src, base), "conflicts": conflicts, "stat": stat,
                "checked_out": co, "dirty": bool(co) and _dirty(co), "behind_origin": r["behind"], "diverged": r["diverged"],
                "push": push_cmd(repo, target)}

    def _worktree(self, repo, sha):
        base = Path(self.wt_base) if self.wt_base else Path(repo).resolve().parent / ".tinyops-wt"
        base.mkdir(parents=True, exist_ok=True)
        path = base / ("%s-merge-%s-%d" % (Path(repo).name, sha[:8], int(time.time() * 1000) % 10**8))
        _git(repo, "worktree", "add", "--detach", "--quiet", str(path), sha, check=True)
        return path

    def _drop(self, repo, path):
        _git(repo, "worktree", "remove", "--force", str(path))
        if Path(path).exists():
            shutil.rmtree(path, ignore_errors=True)
        _git(repo, "worktree", "prune")

    def run(self, repo, source, target, how, commits=None, keep_on_conflict=False, author=None):
        """Übernimmt source in target. Gibt das Ergebnis zurück; bei Konflikt mit keep_on_conflict den Worktree zum Lösen."""
        if how not in HOW:
            raise IntegrateError("Unbekannte Art: %s" % how)
        r = self._refs(repo, source, target)
        if r["diverged"]:
            raise IntegrateError("Dein lokaler %s und der auf GitLab sind auseinandergelaufen. Bitte erst selbst zusammenführen (pull)." % target)
        co = _checked_out(repo, target)
        if co and _dirty(co):
            raise IntegrateError("%s ist in %s ausgecheckt und hat geänderte Dateien. Erst committen oder beiseitelegen." % (target, co))
        old_local, base, src = r["local"], r["base"], r["src"]
        if _is_anc(repo, src, base):
            return self._finish(repo, target, old_local, base, co, how, 0, "%s ist schon ganz in %s." % (source, target))
        if how == "ff":
            if not _is_anc(repo, base, src):
                raise IntegrateError("Fast-Forward geht nicht: %s hat Commits, die %s nicht kennt. Merge oder Rebase nehmen." % (target, source))
            n = int(_git(repo, "rev-list", "--count", "%s..%s" % (base, src))[1] or 0)
            return self._finish(repo, target, old_local, src, co, how, n, "")
        wt = self._worktree(repo, base)
        ident = ["-c", "user.name=%s" % author[0], "-c", "user.email=%s" % author[1]] if author else []
        if how == "merge":
            rc, out, err = _git(wt, *ident, "merge", "--no-ff", "--no-edit", "-m", "Merge %s in %s" % (source, target), src, timeout=120)
            op = "merge"
        elif how == "rebase":
            _git(wt, "checkout", "--quiet", "--detach", src, check=True)
            rc, out, err = _git(wt, *ident, "rebase", "--quiet", base, timeout=180)
            op = "rebase"
        else:
            want = [c for c in (commits or []) if re.match(r"^[0-9a-f]{7,40}$", str(c))]
            rc0, lst, _ = _git(repo, "rev-list", "--reverse", "%s..%s" % (base, src))
            order = [s for s in lst.splitlines() if any(s.startswith(w) for w in want)]
            if not order:
                self._drop(repo, wt)
                raise IntegrateError("Keine Commits ausgewählt, oder sie sind schon in %s." % target)
            rc, out, err = _git(wt, *ident, "cherry-pick", *order, timeout=180)
            op = "cherry-pick"
        if rc:
            files = [f for f in _git(wt, "diff", "--name-only", "--diff-filter=U")[1].splitlines() if f]
            if keep_on_conflict and files:
                tok = "%x" % int(time.time() * 1000)
                self.pending[tok] = {"repo": str(repo), "wt": str(wt), "target": target, "old": old_local, "base": base, "how": how, "op": op, "source": source}
                return {"ok": False, "conflict": files, "worktree": str(wt), "token": tok, "op": op,
                        "hint": "In IntelliJ lösen, dann «git %s --continue» (bei Merge: «git commit»). Danach in tinyops «Abschliessen»." % op}
            _git(wt, op, "--abort")
            self._drop(repo, wt)
            if files:
                return {"ok": False, "conflict": files, "text": "Konflikt in %d Datei(en). Nichts geändert." % len(files)}
            raise IntegrateError("git %s ging nicht: %s" % (op, (err or out).splitlines()[-1:] or [""]))
        new = _rev(wt, "HEAD")
        n = int(_git(repo, "rev-list", "--count", "%s..%s" % (base, new))[1] or 0)
        self._drop(repo, wt)
        return self._finish(repo, target, old_local, new, co, how, n, "")

    def finish(self, token):
        """Nach dem Lösen der Konflikte im Worktree: Ziel-Branch auf das Ergebnis vorrücken, Worktree weg."""
        p = self.pending.get(token)
        if not p:
            raise IntegrateError("Diese Übernahme kenne ich nicht (mehr). tinyops neu gestartet?")
        wt, repo = p["wt"], p["repo"]
        if Path(wt, ".git").exists() and (Path(_git(wt, "rev-parse", "--git-dir")[1]) / ("MERGE_HEAD" if p["op"] == "merge" else "rebase-merge" if p["op"] == "rebase" else "CHERRY_PICK_HEAD")).exists():
            raise IntegrateError("Im Worktree ist der %s noch nicht abgeschlossen. Erst «git %s --continue» (bei Merge: «git commit»)." % (p["op"], p["op"]))
        if _dirty(wt):
            raise IntegrateError("Im Worktree sind noch Dateien geändert. Erst committen.")
        new = _rev(wt, "HEAD")
        if not new or not _is_anc(repo, p["base"], new):
            raise IntegrateError("Das Ergebnis baut nicht auf %s auf. Nichts geändert." % p["target"])
        co = _checked_out(repo, p["target"])
        if co and _dirty(co):
            raise IntegrateError("%s ist in %s ausgecheckt und hat geänderte Dateien." % (p["target"], co))
        n = int(_git(repo, "rev-list", "--count", "%s..%s" % (p["base"], new))[1] or 0)
        out = self._finish(repo, p["target"], p["old"], new, co, p["how"], n, "")
        self._drop(repo, wt)
        self.pending.pop(token, None)
        return out

    def abort(self, token):
        p = self.pending.pop(token, None)
        if p:
            _git(p["wt"], p["op"], "--abort")
            self._drop(p["repo"], p["wt"])
        return {"ok": True}

    def _finish(self, repo, target, old_local, new, co, how, n, note):
        """Ziel-Branch vorrücken: nur vorwärts. Ausgecheckt: Fast-Forward im Checkout, sonst Referenz mit Prüfung des alten Stands."""
        cur = _rev(repo, "refs/heads/" + target)
        if cur != (old_local or ""):
            raise IntegrateError("%s hat sich währenddessen geändert. Nichts übernommen, bitte nochmals." % target)
        if cur and not _is_anc(repo, cur, new):
            raise IntegrateError("Das Ergebnis würde Commits von %s verwerfen. Nichts geändert." % target)
        if cur != new:
            if co:
                _git(co, "merge", "--ff-only", "--quiet", new, check=True)
            elif cur:
                _git(repo, "update-ref", "-m", "tinyops: %s" % HOW[how], "refs/heads/" + target, new, cur, check=True)
            else:
                _git(repo, "branch", "--quiet", "--track", target, "origin/" + target, check=True)
                _git(repo, "update-ref", "-m", "tinyops: %s" % HOW[how], "refs/heads/" + target, new, check=True)
        remote = _rev(repo, "refs/remotes/origin/" + target)
        ahead = int(_git(repo, "rev-list", "--count", "%s..%s" % (remote, new))[1] or 0) if remote else None
        return {"ok": True, "how": how, "target": target, "head": new[:12], "added": n, "ahead": ahead, "note": note,
                "push": push_cmd(repo, target), "checked_out": co}
