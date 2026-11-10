"""Workspaces (0.25): Was liegt lokal und ist noch nicht gepusht?

Ein Workspace ist ein Ordner, dessen Unterordner Projekte sind (z. B. ~/work/dlp-core, ~/work/kunden/sync-tool).
tinyops durchsucht diese Ordner nach Git-Repos und nach Software-Projekten ohne Git und zeigt je Repo:

* Branches mit Commits, die dem Upstream voraus sind, und Branches ohne Upstream
* uncommittete Dateien, Stashes
* Worktrees, auch die der Agenten (.tinyops-wt, Branch agent/…)
* wohin das Repo gehört: GitLab, GitHub oder ein anderer Host, und ob tinyops das Projekt kennt

Gelesen wird nur lokal und ohne Index-Lock (GIT_OPTIONAL_LOCKS=0). «Abholen» ist ein `git fetch --prune` auf Knopfdruck.
tinyops pusht nie und ändert nichts an Arbeitsverzeichnis, Index oder Branches.
"""
import os
import re
import subprocess
import time
import urllib.parse
from pathlib import Path

DEFAULTS = {
    "enabled": True,
    "roots": [],              # zusätzliche Ordner; die Arbeitsordner lokaler Agenten und die Ordner über repo_path kommen von selbst dazu
    "depth": 3,               # so tief unter einem Workspace wird gesucht
    "stale_days": 2,          # ab diesem Alter meldet der Fokus ungepushte Arbeit
    "scan_minutes": 5,
    "max_repos": 200,
}
SKIP = {"node_modules", ".venv", "venv", "__pycache__", "target", "build", "dist", ".gradle", ".idea", ".vscode", ".cache", ".tox", "vendor",
        ".tinyops-wt", ".git", "site-packages", ".m2", ".npm", "bin", "obj"}
MARKERS = (("package.json", "Node"), ("pom.xml", "Maven"), ("build.gradle", "Gradle"), ("build.gradle.kts", "Gradle"), ("pyproject.toml", "Python"),
           ("setup.py", "Python"), ("requirements.txt", "Python"), ("Cargo.toml", "Rust"), ("go.mod", "Go"), ("composer.json", "PHP"),
           ("Gemfile", "Ruby"), ("CMakeLists.txt", "CMake"), ("Makefile", "Make"), ("Dockerfile", "Docker"))
SLN_RE = re.compile(r"\.(sln|csproj)$", re.I)
TRACK_RE = re.compile(r"ahead (\d+)|behind (\d+)")
CRED_RE = re.compile(r"//[^/@\s]+@")
GIT_TIMEOUT = 8


def cfg(c):
    out = dict(DEFAULTS)
    out.update(c.get("workspaces") or {})
    out["roots"] = [str(r) for r in out.get("roots") or [] if str(r).strip()]
    return out


def roots_of(c):
    """Workspaces aus der Config: eingetragene Ordner, Arbeitsordner lokaler Agenten, Ordner über den lokalen Klonen (repo_path)."""
    out = []

    def add(p, why):
        try:
            p = str(Path(str(p)).expanduser())
        except (OSError, RuntimeError, ValueError):
            return
        if p and p not in (x["path"] for x in out):
            out.append({"path": p, "why": why})
    for r in cfg(c)["roots"]:
        add(r, "eingetragen")
    for a in c.get("agents") or []:
        if a.get("connection") in (None, "", "local") and a.get("workspace_root"):
            add(a["workspace_root"], "Arbeitsordner von %s" % (a.get("name") or a.get("id")))
    rp = [p.get("repo_path") for p in c.get("projects") or []] + [r.get("repo_path") for r in (c.get("github") or {}).get("repos") or []]
    for p in rp:
        if p:
            add(Path(str(p)).expanduser().parent, "über einem lokalen Klon")
    return out


def _git(repo, *args, timeout=GIT_TIMEOUT):
    env = dict(os.environ, GIT_OPTIONAL_LOCKS="0", GIT_TERMINAL_PROMPT="0", LC_ALL="C")
    try:
        r = subprocess.run(["git", "-C", str(repo)] + list(args), capture_output=True, text=True, timeout=timeout, env=env, errors="replace")
        return r.returncode, r.stdout, r.stderr.strip()
    except (subprocess.TimeoutExpired, OSError) as e:
        return 124, "", str(e)


def find(root, depth=3, limit=200):
    """Git-Repos und Projekte ohne Git unter root. In ein Repo wird nicht weiter hineingeschaut."""
    repos, plain = [], []
    root = Path(root)
    if not root.is_dir():
        return repos, plain

    def walk(d, level):
        if len(repos) + len(plain) >= limit:
            return
        try:
            names = sorted(e.name for e in os.scandir(d))
        except OSError:
            return
        if ".git" in names:
            repos.append(d)
            return
        kind = next((k for m, k in MARKERS if m in names), None) or (".NET" if any(SLN_RE.search(n) for n in names) else None)
        before = len(repos) + len(plain)
        if level >= depth:
            if kind and level > 0:
                plain.append((d, kind))
            return
        for n in names:
            if n in SKIP or n.startswith("."):
                continue
            p = d / n
            try:
                if p.is_dir() and not p.is_symlink():
                    walk(p, level + 1)
            except OSError:
                continue
        if kind and level > 0 and len(repos) + len(plain) == before:      # Projektordner ohne Git und ohne Repos darunter
            plain.append((d, kind))
    walk(root, 0)
    return repos, plain


def parse_remote(url):
    """(host, pfad) aus einer Remote-Adresse, ohne Zugangsdaten. Unterstützt https, ssh://, git@host:pfad."""
    url = (url or "").strip()
    m = re.match(r"^(?:[\w.-]+@)?([\w.-]+):(?!//)(.+)$", url)
    if m and "://" not in url:
        host, path = m.group(1), m.group(2)
    else:
        u = urllib.parse.urlparse(url)
        host, path = (u.hostname or ""), u.path
    path = re.sub(r"\.git/?$", "", path.strip("/"))
    return host.lower(), path


def safe_url(url):
    return CRED_RE.sub("//", url or "")


def classify(host, hosts):
    """gitlab, github oder other. hosts: {"gitlab": [..], "github": [..]} aus der Config."""
    if not host:
        return "none"
    if host in hosts.get("gitlab", ()) or "gitlab" in host:
        return "gitlab"
    if host in hosts.get("github", ()) or host == "github.com" or "github" in host:
        return "github"
    return "other"


def match_project(path, remotes, projects):
    """Welches eingerichtete Projekt ist das? projects: [{"pid", "name", "host", "full", "repo_path", "agent_dir"}]."""
    rp = os.path.normcase(os.path.realpath(str(path)))
    for p in projects:
        if p.get("repo_path") and os.path.normcase(os.path.realpath(os.path.expanduser(p["repo_path"]))) == rp:
            return p
    for r in remotes:
        for p in projects:
            if p["host"] != r["kind"]:
                continue
            if p.get("full") and p["full"].lower() == r["path"].lower():
                return p
            if not p.get("full") and r["path"].rsplit("/", 1)[-1].lower() in {(p.get("name") or "").lower(), (p.get("agent_dir") or "").strip("/").rsplit("/", 1)[-1].lower()} - {""}:
                return p
    return None


def _count(repo, *args):
    rc, out, _ = _git(repo, "rev-list", "--count", *args)
    try:
        return int(out.strip()) if rc == 0 else None
    except ValueError:
        return None


def status_of(path):
    """Uncommittetes in einem Arbeitsverzeichnis: geändert, vorgemerkt, neu."""
    rc, out, _ = _git(path, "status", "--porcelain=v1", "-unormal")
    if rc != 0:
        return None
    staged = changed = new = 0
    for line in out.splitlines():
        if len(line) < 2:
            continue
        if line.startswith("??"):
            new += 1
            continue
        if line[0] not in " ?":
            staged += 1
        if line[1] not in " ?":
            changed += 1
    return {"staged": staged, "changed": changed, "new": new, "total": staged + changed + new}


def inspect(path, hosts=None, projects=(), now=None):
    """Ein Repo lesen. Nur lokale Git-Befehle, kein Netz."""
    now = now or time.time()
    hosts = hosts or {}
    path = Path(path)
    info = {"path": str(path), "name": path.name, "ok": True, "branches": [], "worktrees": [], "remotes": [], "stashes": 0, "stash_age_days": None}
    rc, out, err = _git(path, "rev-parse", "--abbrev-ref", "HEAD")
    if rc != 0:
        rc2, out2, _ = _git(path, "symbolic-ref", "--short", "HEAD")      # frisches Repo ohne Commit
        if rc2 != 0:
            return dict(info, ok=False, error=(err or "kein lesbares Git-Repo")[:200])
        info["head"], info["empty"] = out2.strip(), True
    else:
        info["head"] = out.strip()
    seen = {}
    rc, out, _ = _git(path, "remote", "-v")
    for line in out.splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[0] not in seen:
            host, rpath = parse_remote(parts[1])
            seen[parts[0]] = {"name": parts[0], "url": safe_url(parts[1]), "host": host, "path": rpath, "kind": classify(host, hosts) if host else "other"}
    info["remotes"] = list(seen.values())
    main = seen.get("origin") or (info["remotes"][0] if info["remotes"] else None)
    info["host"] = main["kind"] if main else "none"
    info["remote"] = ("%s/%s" % (main["host"], main["path"])) if main else ""
    p = match_project(path, info["remotes"], projects)
    info["project"] = {"pid": p["pid"], "name": p["name"], "host": p["host"]} if p else None
    fmt = "%(refname:short)%00%(upstream:short)%00%(upstream:track)%00%(committerdate:unix)%00%(objectname:short)%00%(subject)"
    rc, out, _ = _git(path, "for-each-ref", "--format=" + fmt, "refs/heads")
    for line in out.splitlines():
        f = line.split("\0")
        if len(f) < 6:
            continue
        name, up, track, ts, sha, subject = f[:6]
        ahead = behind = 0
        gone = "gone" in track
        for a, b in TRACK_RE.findall(track):
            ahead, behind = (int(a) if a else ahead), (int(b) if b else behind)
        if not up or gone:      # ohne Upstream: Commits, die auf keinem Remote-Branch liegen
            n = _count(path, name, "--not", "--remotes") if info["remotes"] else _count(path, name)
            ahead = n if n is not None else 0
        try:
            age = max(0.0, (now - int(ts)) / 86400.0)
        except ValueError:
            age = None
        info["branches"].append({"name": name, "upstream": "" if gone else up, "gone": gone, "ahead": ahead, "behind": behind, "sha": sha,
                                 "subject": subject[:120], "age_days": round(age, 1) if age is not None else None,
                                 "agent": name.startswith("agent/"), "current": name == info["head"]})
    # Commits, die auf keinem Remote liegen, einmal gezählt (mehrere Branches können dieselben Commits tragen)
    info["unique_unpushed"] = _count(path, "--branches", "--not", "--remotes") if info["branches"] else 0
    st = status_of(path)
    info["dirty"] = st or {"staged": 0, "changed": 0, "new": 0, "total": 0}
    rc, out, _ = _git(path, "stash", "list", "--format=%ct")
    ts = [int(x) for x in out.split() if x.isdigit()]
    if ts:
        info["stashes"], info["stash_age_days"] = len(ts), round((now - min(ts)) / 86400.0, 1)
    rc, out, _ = _git(path, "worktree", "list", "--porcelain")
    cur = None
    for line in out.splitlines() + [""]:
        if line.startswith("worktree "):
            cur = {"path": line[9:], "branch": "", "sha": "", "detached": False}
        elif cur is not None and line.startswith("HEAD "):
            cur["sha"] = line[5:13]
        elif cur is not None and line.startswith("branch "):
            cur["branch"] = line[7:].replace("refs/heads/", "", 1)
        elif cur is not None and line == "detached":
            cur["detached"] = True
        elif cur is not None and not line:
            if os.path.realpath(cur["path"]) != os.path.realpath(str(path)):
                cur["agent"] = ".tinyops-wt" in cur["path"].replace("\\", "/") or cur["branch"].startswith("agent/")
                cur["missing"] = not os.path.isdir(cur["path"])
                d = status_of(cur["path"]) if not cur["missing"] and len(info["worktrees"]) < 12 else None
                cur["dirty"] = d["total"] if d else 0
                info["worktrees"].append(cur)
            cur = None
    fh = path / ".git" / "FETCH_HEAD"
    try:
        info["fetched_days"] = round((now - fh.stat().st_mtime) / 86400.0, 1)
    except OSError:
        info["fetched_days"] = None
    info.update(summary(info))
    return info


def summary(r):
    """Kennzahlen eines Repos: Was würde verloren gehen, wenn die Platte stirbt?"""
    unpushed = [b for b in r["branches"] if b["ahead"] > 0]
    commits = r.get("unique_unpushed")
    if commits is None:
        commits = sum(b["ahead"] for b in unpushed)
    ages = [b["age_days"] for b in unpushed if b["age_days"] is not None]
    wt_dirty = sum(1 for w in r["worktrees"] if w.get("dirty"))
    todo = bool(commits or r["dirty"]["total"] or r["stashes"] or wt_dirty)
    return {"unpushed_branches": len(unpushed), "unpushed_commits": commits, "no_upstream": sum(1 for b in unpushed if not b["upstream"]),
            "agent_branches": sum(1 for b in unpushed if b["agent"]), "oldest_days": max(ages) if ages else None, "wt_dirty": wt_dirty, "todo": todo}


def scan(roots, hosts=None, projects=(), depth=3, limit=200, now=None, budget=25.0):
    """Alle Workspaces durchsuchen. Gibt Repos (mit Arbeit zuerst), Projekte ohne Git und je Workspace den Stand zurück."""
    now = now or time.time()
    t0 = time.time()
    out = {"ts": now, "roots": [], "repos": [], "plain": [], "partial": False}
    seen = set()
    for r in roots:
        root = Path(r["path"])
        entry = {"path": r["path"], "why": r.get("why", ""), "ok": root.is_dir(), "repos": 0, "plain": 0}
        out["roots"].append(entry)
        if not entry["ok"]:
            continue
        repos, plain = find(root, depth, limit)
        for p in repos:
            key = os.path.realpath(str(p))
            if key in seen:
                continue
            seen.add(key)
            if time.time() - t0 > budget or len(out["repos"]) >= limit:
                out["partial"] = True
                break
            info = inspect(p, hosts, projects, now)
            info["root"] = r["path"]
            try:
                info["rel"] = str(p.relative_to(root)) if p != root else p.name
            except ValueError:
                info["rel"] = p.name
            out["repos"].append(info)
            entry["repos"] += 1
        for p, kind in plain:
            if os.path.realpath(str(p)) in seen:
                continue
            seen.add(os.path.realpath(str(p)))
            try:
                rel = str(p.relative_to(root))
            except ValueError:
                rel = p.name
            out["plain"].append({"path": str(p), "name": p.name, "rel": rel, "kind": kind, "root": r["path"]})
            entry["plain"] += 1
    out["repos"].sort(key=lambda x: (not x.get("todo"), -(x.get("oldest_days") or 0), x["name"].lower()))
    out["secs"] = round(time.time() - t0, 2)
    return out


def totals(res, stale_days=2):
    """Zusammenfassung für Fokus und Seitenleiste."""
    repos = [r for r in (res or {}).get("repos") or [] if r.get("ok")]
    todo = [r for r in repos if r.get("todo")]
    stale = [r for r in todo if (r.get("oldest_days") or 0) >= stale_days or (r.get("stash_age_days") or 0) >= stale_days]
    return {"repos": len(repos), "todo": len(todo), "commits": sum(r["unpushed_commits"] for r in todo), "dirty": sum(1 for r in repos if r["dirty"]["total"]),
            "stashes": sum(r["stashes"] for r in repos), "agent_branches": sum(r["agent_branches"] for r in repos),
            "plain": len((res or {}).get("plain") or []), "unknown": sum(1 for r in repos if not r.get("project")),
            "stale": [{"name": r["name"], "days": r.get("oldest_days") or r.get("stash_age_days"), "commits": r["unpushed_commits"]} for r in stale[:5]],
            "oldest_days": max([r.get("oldest_days") or 0 for r in todo] or [0]), "ts": (res or {}).get("ts"), "partial": bool((res or {}).get("partial"))}


def fetch(path):
    """git fetch --prune für ein Repo (auf Knopfdruck). Ändert nur Remote-Tracking-Refs."""
    rc, out, err = _git(path, "fetch", "--prune", "--quiet", timeout=90)
    return rc == 0, CRED_RE.sub("//", err)[:300]
