"""Ergebnis eines Agenten ausprobieren (0.32): Branch auschecken, in IntelliJ öffnen, Review-Umgebung starten.

* Auschecken: tinyops holt den Branch des Laufs (vom lokalen Agenten-Repo oder per SSH vom Agenten-Rechner) in deinen lokalen
  Checkout und legt daneben einen eigenen Worktree an. Dein Arbeitsstand bleibt unberührt. tinyops pusht nie.
* Review-Umgebung: Befehle, die du je Projekt einträgst (Docker Compose, Kubernetes oder eigene), laufen nur auf Klick,
  auf diesem Rechner, im Worktree des Laufs. Platzhalter: {name} {port} {path} {branch} {sha} {ticket} {compose_files}.
* Umsysteme (0.34): Für Docker Compose wählst du Dienste wie PostgreSQL oder Redis und andere Repos aus Workspaces dazu.
  tinyops schreibt daraus eine Compose-Datei (nur lokal, nie ins Repo) und gibt sie mit -f an den Befehl.
"""
import os
import re
import shlex
from pathlib import Path

KINDS = {
    "compose": {"label": "Docker Compose", "up": "docker compose {compose_files} -p {name} up -d --build", "down": "docker compose {compose_files} -p {name} down -v",
                "url": "http://localhost:{port}"},
    "k8s": {"label": "Kubernetes", "up": "kubectl create namespace {name} --dry-run=client -o yaml | kubectl apply -f - && kubectl -n {name} apply -k deploy/review",
            "down": "kubectl delete namespace {name} --wait=false", "url": "https://{name}.review.example"},
    "custom": {"label": "Eigene Befehle", "up": "", "down": "", "url": ""},
}
PORT_BASE = 20000
PLACEHOLDERS = ("name", "port", "path", "branch", "sha", "ticket", "compose_files")
RAW = ("compose_files",)          # schon für die Shell zusammengesetzt, nicht nochmals quoten
COMPOSE_NAMES = ("compose.yaml", "compose.yml", "docker-compose.yaml", "docker-compose.yml")
# Umsysteme zum Zusammenklicken. Nur Standard-Images, Zugangsdaten nur für die Review-Umgebung, Ports nicht nach aussen.
INFRA = {
    "postgres": {"label": "PostgreSQL", "image": "postgres:16", "env": {"POSTGRES_USER": "review", "POSTGRES_PASSWORD": "review", "POSTGRES_DB": "review"}},
    "mariadb": {"label": "MariaDB", "image": "mariadb:11", "env": {"MARIADB_USER": "review", "MARIADB_PASSWORD": "review", "MARIADB_DATABASE": "review",
                                                                  "MARIADB_ROOT_PASSWORD": "review"}},
    "redis": {"label": "Redis", "image": "redis:7", "env": {}},
    "activemq": {"label": "ActiveMQ Artemis", "image": "apache/activemq-artemis:2.37.0", "env": {"ARTEMIS_USER": "review", "ARTEMIS_PASSWORD": "review"}},
    "rabbitmq": {"label": "RabbitMQ", "image": "rabbitmq:3-management", "env": {}},
    "mailpit": {"label": "Mailpit (Mail-Falle)", "image": "axllent/mailpit:v1.20", "env": {}},
}


def slug(s, n=40):
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", str(s or "").lower())).strip("-")[:n].strip("-") or "x"


def env_name(ticket, run_id):
    """DNS-tauglicher Name je Lauf (Compose-Projekt, Namespace): review-<ticket>-<lauf>, höchstens 50 Zeichen."""
    return ("review-%s-%d" % (slug(ticket, 30), int(run_id)))[:50]


def env_port(run_id):
    return PORT_BASE + int(run_id) % 10000


def mr_values(project, iid, branch, path, sha):
    """Werte für einen MR (0.34): eigener Name und Port, damit Lauf und MR sich nicht ins Gehege kommen."""
    return {"name": ("review-%s-mr%d" % (slug(project, 30), int(iid)))[:50], "port": str(PORT_BASE + 10000 + int(iid) % 10000), "path": path,
            "sha": sha or "", "branch": branch or "", "ticket": ""}


def values(run, path, sha):
    return {"name": env_name(run["ticket"], run["id"]), "port": str(env_port(run["id"])), "path": path, "sha": sha or "",
            "branch": run.get("taken") or run.get("out_branch") or run.get("branch") or "", "ticket": run.get("ticket") or ""}


def fill(tmpl, vals, quote=True):
    """Platzhalter ersetzen. In Befehlen werden die Werte für die Shell gequotet."""
    def rep(m):
        v = vals.get(m.group(1), m.group(0))
        if m.group(1) in RAW:
            return v if m.group(1) in vals else ""
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
    if kind == "compose":
        cf = str(item.get("compose_file") or "").strip()
        if cf and (cf.startswith(("/", "~")) or ".." in cf.replace("\\", "/").split("/") or len(cf) > 200):
            return None, "Compose-Datei relativ zum Repo angeben, z. B. docker-compose.yml."
        out["compose_file"] = cf
        try:
            ap = int(item.get("app_port") or 8080)
            if not 1 <= ap <= 65535:
                raise ValueError
        except (TypeError, ValueError):
            return None, "Port der Anwendung: Zahl von 1 bis 65535."
        out["app_port"] = ap
        svc = []
        for x in item.get("services") or []:
            x = str(x).strip()
            if x in INFRA or (x.startswith("repo:") and len(x) < 300 and os.path.isabs(os.path.expanduser(x[5:]))):
                if x not in svc:
                    svc.append(x)
        out["services"] = svc[:12]
    return out, ""


def compose_files_in(path):
    """Compose-Dateien im Wurzelordner eines Repos (für den Vorschlag)."""
    try:
        names = set(os.listdir(path))
    except OSError:
        return []
    out = [n for n in COMPOSE_NAMES if n in names]
    out += sorted(n for n in names if re.fullmatch(r"(docker-)?compose\.[\w.-]+\.ya?ml", n) and n not in out)
    return out[:8]


def has_dockerfile(path):
    return os.path.isfile(os.path.join(path, "Dockerfile"))


def _yq(v):
    return '"%s"' % str(v).replace("\\", "\\\\").replace('"', '\\"')


def compose_yaml(app_path, app_port, services, with_app):
    """Compose-Datei für Umsysteme (und die Anwendung selbst, wenn das Repo keine eigene Compose-Datei hat).
    Ports nach aussen nur für die Anwendung: ${REVIEW_PORT} → app_port. Umsysteme bleiben im Netz der Review-Umgebung."""
    lines = ["# Von tinyops erzeugt für eine Review-Umgebung. Nicht ins Repo legen.", "services:"]
    if with_app:
        lines += ["  app:", "    build: %s" % _yq(app_path), "    ports:", '      - "${REVIEW_PORT}:%d"' % int(app_port)]
        deps = [x for x in services if x in INFRA] + [slug(Path(x[5:]).name, 30) for x in services if x.startswith("repo:")]
        if deps:
            lines += ["    depends_on:"] + ["      - %s" % d for d in deps]
    for x in services:
        if x in INFRA:
            d = INFRA[x]
            lines += ["  %s:" % x, "    image: %s" % _yq(d["image"])]
            if d["env"]:
                lines += ["    environment:"] + ["      %s: %s" % (k, _yq(v)) for k, v in d["env"].items()]
        elif x.startswith("repo:"):
            lines += ["  %s:" % slug(Path(x[5:]).name, 30), "    build: %s" % _yq(os.path.expanduser(x[5:]))]
    return "\n".join(lines) + "\n"


def compose_plan(pe, path, gen_path):
    """Welche Compose-Dateien gehören zum Start? (liste, yaml oder None, fehler). path: Worktree des Laufs/MR."""
    files = []
    cf = pe.get("compose_file") or next(iter(compose_files_in(path)), "")
    if cf and os.path.isfile(os.path.join(path, cf)):
        files.append(os.path.join(path, cf))
    services = pe.get("services") or []
    with_app = not files and has_dockerfile(path)
    if not files and not with_app:
        return [], None, "Im Repo gibt es weder eine Compose-Datei noch ein Dockerfile. Compose-Datei eintragen oder eigene Befehle wählen."
    yaml = compose_yaml(path, pe.get("app_port") or 8080, services, with_app) if (services or with_app) else None
    if yaml:
        files.append(gen_path)
    return files, yaml, ""


def compose_arg(files):
    return " ".join("-f %s" % shlex.quote(f) for f in files)


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
