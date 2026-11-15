"""Ergebnis eines Agenten ausprobieren (0.32): Branch auschecken, in IntelliJ öffnen, Review-Umgebung starten.

* Auschecken: tinyops holt den Branch des Laufs (vom lokalen Agenten-Repo oder per SSH vom Agenten-Rechner) in deinen lokalen
  Checkout und legt daneben einen eigenen Worktree an. Dein Arbeitsstand bleibt unberührt. tinyops pusht nie.
* Review-Umgebung: Befehle, die du je Projekt einträgst (Docker Compose, Kubernetes oder eigene), laufen nur auf Klick,
  auf diesem Rechner, im Worktree des Laufs. Platzhalter: {name} {port} {path} {branch} {sha} {ticket}.
"""
import re
import shlex

KINDS = {
    "compose": {"label": "Docker Compose", "up": "docker compose -p {name} up -d --build", "down": "docker compose -p {name} down -v",
                "url": "http://localhost:{port}"},
    "k8s": {"label": "Kubernetes", "up": "kubectl create namespace {name} --dry-run=client -o yaml | kubectl apply -f - && kubectl -n {name} apply -k deploy/review",
            "down": "kubectl delete namespace {name} --wait=false", "url": "https://{name}.review.example"},
    "custom": {"label": "Eigene Befehle", "up": "", "down": "", "url": ""},
}
PORT_BASE = 20000
PLACEHOLDERS = ("name", "port", "path", "branch", "sha", "ticket")


def slug(s, n=40):
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", str(s or "").lower())).strip("-")[:n].strip("-") or "x"


def env_name(ticket, run_id):
    """DNS-tauglicher Name je Lauf (Compose-Projekt, Namespace): review-<ticket>-<lauf>, höchstens 50 Zeichen."""
    return ("review-%s-%d" % (slug(ticket, 30), int(run_id)))[:50]


def env_port(run_id):
    return PORT_BASE + int(run_id) % 10000


def values(run, path, sha):
    return {"name": env_name(run["ticket"], run["id"]), "port": str(env_port(run["id"])), "path": path, "sha": sha or "",
            "branch": run.get("taken") or run.get("out_branch") or run.get("branch") or "", "ticket": run.get("ticket") or ""}


def fill(tmpl, vals, quote=True):
    """Platzhalter ersetzen. In Befehlen werden die Werte für die Shell gequotet."""
    def rep(m):
        v = vals.get(m.group(1), m.group(0))
        return shlex.quote(v) if quote and m.group(1) in vals and not re.fullmatch(r"[A-Za-z0-9._/:@+-]+", v or "-") else v
    return re.sub(r"\{(%s)\}" % "|".join(PLACEHOLDERS), rep, tmpl or "")


def clean(item):
    """Review-Umgebung eines Projekts prüfen. Gibt (eintrag oder None, fehler) zurück."""
    if not isinstance(item, dict) or not item.get("kind"):
        return None, ""
    kind = str(item.get("kind"))
    if kind not in KINDS:
        return None, "Unbekannte Art «%s»." % kind[:20]
    out = {"kind": kind}
    for k, n in (("up", 1000), ("down", 1000), ("url", 300)):
        v = " ".join(str(item.get(k) or "").split()) if k == "url" else str(item.get(k) or "").strip()
        if "\n" in v or "\r" in v:
            return None, "Befehle bitte in einer Zeile (mehrere mit && verbinden)."
        if len(v) > n:
            return None, "Höchstens %d Zeichen." % n
        out[k] = v
    if not out["up"]:
        return None, "Ohne Start-Befehl gibt es keine Review-Umgebung."
    if out["url"] and not re.match(r"^https?://", out["url"]):
        return None, "Die Adresse beginnt mit http:// oder https://."
    return out, ""


def source_url(agent, conn, repo):
    """Woher der Branch kommt: lokaler Pfad oder ssh://… zum Agenten-Rechner (Pfade mit ~ bleiben relativ zum Home)."""
    if conn is None:
        return repo
    host = ("%s@%s" % (conn["user"], conn["host"])) if conn.get("user") else conn["host"]
    path = repo if repo.startswith("/") else "/" + repo if repo.startswith("~") else "/~/" + repo
    return "ssh://%s:%s%s" % (host, conn.get("port") or 22, path)


def checkout_commands(src, branch, local=False):
    """Zum Kopieren: so holst du den Branch in deinen eigenen Checkout."""
    if not branch:
        return ""
    lines = ["git fetch %s %s:%s" % (shlex.quote(src), shlex.quote(branch), shlex.quote(branch)), "git switch %s" % shlex.quote(branch)]
    if local:
        lines.insert(0, "# Der Branch liegt im Repo %s. Dort ist er im Worktree des Agenten ausgecheckt." % src)
    return "\n".join(lines) + "\n"
