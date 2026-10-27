#!/usr/bin/env python3
"""tinyops Einrichtung in Schritten. Jeder Schritt erklärt, was er braucht, fragt ab, prüft das Ergebnis sofort
gegen dein System und speichert die config.json. Details landen im Log (python3 server.py --show-log 100).

    python3 setup.py                  # alle Schritte der Reihe nach
    python3 setup.py --list           # Schritte anzeigen
    python3 setup.py --step jira      # nur einen Schritt (oder --from jira ab diesem Schritt)
    python3 setup.py --doctor         # nichts ändern, nur prüfen (Exit-Code 1 bei Problemen)
"""
import argparse
import getpass
import json
import os
import secrets as pysecrets
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.parse
from collections import Counter
from pathlib import Path

BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE))
import secretstore as store  # noqa: E402
import tlog  # noqa: E402

CONFIG = BASE / "config.json"
EXAMPLE = BASE / "config.example.json"
log = tlog.get("setup")
LOOP = ("127.0.0.1", "localhost", "::1")
TTY = sys.stdout.isatty()


def c(code, text):
    return "\033[%sm%s\033[0m" % (code, text) if TTY else text


def ok(msg):
    print(c("32", "  ✓ ") + msg)
    log.info("OK: %s", msg)


def bad(msg):
    print(c("31", "  ✗ ") + msg)
    log.error("PROBLEM: %s", msg)


def warn(msg):
    print(c("33", "  ! ") + msg)
    log.warning("%s", msg)


def info(msg):
    print("    " + msg)


# ------------------------------------------------------------ Eingabe
def ask(label, default="", hint=""):
    if hint:
        info(c("2", hint))
    suffix = " [%s]" % default if default != "" else ""
    try:
        v = input("  %s%s: " % (label, suffix)).strip()
    except EOFError:
        v = ""
    return v or default


def ask_yes(label, default=True):
    try:
        v = input("  %s (%s): " % (label, "J/n" if default else "j/N")).strip().lower()
    except EOFError:
        v = ""
    return default if not v else v in ("j", "ja", "y", "yes")


def ask_list(label, default, hint=""):
    return [x.strip() for x in ask(label, ", ".join(default), hint).split(",") if x.strip()]


def ask_int(label, default, hint=""):
    while True:
        v = ask(label, str(default), hint)
        try:
            return int(v)
        except ValueError:
            warn("Bitte eine ganze Zahl.")


def pick(label, options, default=None):
    """Nummerierte Auswahl. Gibt den Index oder None (Eingabe leer ohne Vorgabe) zurück."""
    for i, o in enumerate(options, 1):
        print("    %2d) %s" % (i, o))
    while True:
        v = ask(label, "" if default is None else str(default + 1))
        if not v:
            return None
        if v.isdigit() and 1 <= int(v) <= len(options):
            return int(v) - 1
        warn("Nummer zwischen 1 und %d eingeben." % len(options))


# ------------------------------------------------------------ Config
def load_cfg():
    for path in (CONFIG, EXAMPLE):
        if path.exists():
            with open(path, encoding="utf-8") as f:
                return json.load(f), path == CONFIG
    return {}, False


def save_cfg(cfg):
    fd, tmp = tempfile.mkstemp(dir=str(BASE), prefix=".config.", suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)
        f.write("\n")
    os.chmod(tmp, 0o600)
    os.replace(tmp, CONFIG)
    log.info("config.json gespeichert (%d Schlüssel)", len(cfg))


class Ctx:
    def __init__(self, cfg):
        self.cfg = cfg
        self._srv = None

    @property
    def server(self):
        if self._srv is None:
            import server
            self._srv = server
        return self._srv

    def merged(self):
        s = self.server
        m = dict(s.DEFAULTS)
        m.update(self.cfg)
        return m

    def ssl(self):
        return self.server.make_ssl(self.cfg)

    def spec(self, name):
        return (self.cfg.get("secrets") or {}).get(name)

    def secret(self, name):
        return store.resolve(name, self.spec(name))

    def gitlab(self):
        tok, _ = self.secret("gitlab_token")
        if not tok or not self.cfg.get("gitlab_url"):
            return None
        store.register(tok)
        return self.server.Http("GitLab", self.cfg["gitlab_url"].rstrip("/") + "/api/v4",
                                {"PRIVATE-TOKEN": tok, "Accept": "application/json"}, self.ssl())

    def jira(self):
        jc = self.cfg.get("jira") or {}
        if not jc.get("url"):
            return None
        name = "jira_token" if jc.get("auth", "bearer") == "bearer" else "jira_password"
        sec, _ = self.secret(name)
        if not sec:
            return None
        store.register(sec)
        hdr = self.server.jira_auth_header(jc, {name: sec})
        return self.server.Http("Jira", jc["url"].rstrip("/") + "/rest/api/2",
                                {"Authorization": hdr, "Accept": "application/json"}, self.ssl())


def explain(e):
    msg = str(e)
    bad(msg)
    log.debug("Fehlerdetail", exc_info=True)
    info("Details im Log: python3 server.py --show-log 40")


def need_secret(ctx, name, label, hint=""):
    """Fragt ein Secret ab und speichert es. True, wenn danach eines vorhanden ist."""
    val, src = ctx.secret(name)
    if val:
        ok("%s ist schon gesetzt (← %s)" % (name, src))
        if not ask_yes("Behalten?", True):
            val = None
        else:
            return True
    if hint:
        info(hint)
    value = getpass.getpass("  %s (Eingabe unsichtbar, Enter = überspringen): " % label)
    if not value:
        warn("%s übersprungen." % name)
        return bool(val)
    try:
        where = store.set_secret(name, value)
    except store.SecretError as e:
        explain(e)
        return False
    got, src = ctx.secret(name)
    if got == value:
        ok("%s gespeichert und zurückgelesen (%s)" % (name, where))
    else:
        warn("%s gespeichert in %s, aber das Zurücklesen lieferte etwas anderes (Quelle: %s). "
             "Vermutlich überschreibt eine Umgebungsvariable oder ein Befehl den Wert." % (name, where, src))
    log.info("Secret %s gespeichert in: %s", name, where)
    return True


# ------------------------------------------------------------ Schritt 1: Voraussetzungen
def keyring_status():
    try:
        import keyring
    except ImportError:
        return False, ("Das Python-Paket 'keyring' ist für %s nicht installiert.\n"
                       "    Debian/Ubuntu: sudo apt install python3-keyring     (nur für das System-Python)\n"
                       "    oder in einer venv: python3 -m venv .venv && .venv/bin/pip install keyring\n"
                       "                        dann mit .venv/bin/python setup.py starten (run.sh nimmt .venv automatisch)"
                       % sys.executable)
    from keyring.backends import fail
    kr = keyring.get_keyring()
    name = "%s.%s" % (type(kr).__module__, type(kr).__name__)
    if isinstance(kr, fail.Keyring):
        return False, ("keyring ist installiert, findet aber keinen Schlüsselbund-Dienst (Secret-Service: GNOME Keyring, "
                       "KDE Wallet, KeePassXC). Ohne Desktop-Sitzung siehe README «Schlüsselbund unter Linux».")
    try:
        keyring.set_password(store.SERVICE, "_selftest", "x")
        good = keyring.get_password(store.SERVICE, "_selftest") == "x"
        keyring.delete_password(store.SERVICE, "_selftest")
    except Exception as e:
        return False, "Backend %s gefunden, Test fehlgeschlagen: %s (gesperrt oder kein D-Bus der Sitzung?)" % (name, e)
    return good, "Backend %s: Schreib-/Lesetest bestanden." % name


def tool_version(argv):
    try:
        r = subprocess.run(argv, capture_output=True, text=True, timeout=8)
        return (r.stdout or r.stderr).strip().splitlines()[0] if (r.stdout or r.stderr).strip() else "?"
    except (OSError, subprocess.SubprocessError):
        return None


def step_preflight(ctx):
    """Prüft, was auf diesem Rechner vorhanden ist. Ändert nichts."""
    info("Hier wird nichts gespeichert. Es wird geprüft, ob dieser Rechner alles mitbringt.")
    v = sys.version_info
    (ok if v >= (3, 9) else bad)("Python %d.%d.%d (%s)%s" % (v[0], v[1], v[2], sys.executable,
                                                              "" if v >= (3, 9) else ", nötig ist 3.9 oder neuer"))
    g = tool_version(["git", "--version"])
    (ok if g else warn)(g or "git nicht gefunden (nur für Updates des Panels nötig)")
    good, text = keyring_status()
    if good:
        ok(text)
    else:
        warn("Kein Schlüsselbund: " + text)
        info("Secrets würden dann in %s liegen (Klartext, nur für deinen Benutzer lesbar)." % store.secrets_file())
        if not ask_yes("Trotzdem fortfahren?", True):
            raise StopSetup("Erst den Schlüsselbund einrichten, dann nochmal starten.")
    for tool, argv, why in (("kubectl", ["kubectl", "version", "--client"], "Testumgebungen"),
                            ("helm", ["helm", "version", "--short"], "Testumgebungen")):
        r = tool_version(argv) if shutil.which(tool) else None
        (ok if r else warn)("%s: %s" % (tool, r) if r else "%s nicht gefunden (nötig für %s, sonst egal)" % (tool, why))
    lf = tlog.log_file(ctx.cfg)
    ok("Log: %s" % lf)
    return True


# ------------------------------------------------------------ Schritt 2: GitLab
def step_gitlab(ctx):
    cfg = ctx.cfg
    info("Das Panel liest GitLab nur. Es braucht die Adresse und einen Token mit dem Scope read_api.")
    while True:
        cfg["gitlab_url"] = ask("GitLab-URL", cfg.get("gitlab_url", ""), "zum Beispiel https://gitlab.firma.example").rstrip("/")
        if not cfg["gitlab_url"].startswith(("http://", "https://")):
            warn("Die Adresse muss mit https:// (oder http://) beginnen.")
            continue
        if cfg["gitlab_url"].startswith("http://"):
            warn("http:// überträgt den Token unverschlüsselt.")
        break
    cfg["ca_bundle"] = ask("Firmen-CA (PEM-Datei, leer = Systemzertifikate)", cfg.get("ca_bundle", ""))
    save_cfg(cfg)
    info("Token anlegen: %s/-/user_settings/personal_access_tokens" % cfg["gitlab_url"])
    info("Name zum Beispiel «tinyops», Scope nur «read_api», Ablaufdatum setzen.")
    while True:
        if not need_secret(ctx, "gitlab_token", "GitLab-Token"):
            warn("Ohne Token geht es hier nicht weiter. Später: python3 setup.py --step gitlab")
            return False
        try:
            gl = ctx.gitlab()
            t0 = time.time()
            me = gl.get("/user")
            ok("Angemeldet als %s (%s), %d ms" % (me.get("username"), me.get("email") or "keine E-Mail sichtbar",
                                                  (time.time() - t0) * 1000))
            ctx.me = me
            break
        except Exception as e:
            explain(e)
            if not ask_yes("Zugangsdaten oder URL korrigieren und nochmal?", True):
                return False
            cfg["gitlab_url"] = ask("GitLab-URL", cfg["gitlab_url"]).rstrip("/")
            cfg["ca_bundle"] = ask("Firmen-CA", cfg.get("ca_bundle", ""))
            save_cfg(cfg)
            if ask_yes("Auch den Token neu eingeben?", False):
                try:
                    store.delete_secret("gitlab_token")
                except store.SecretError:
                    pass
    try:
        tk = gl.get("/personal_access_tokens/self")
        scopes = tk.get("scopes") or []
        if set(scopes) - {"read_api", "read_user", "read_repository"}:
            warn("Der Token hat mehr als nötig: %s. Für das Panel reicht read_api (es schreibt nie)." % ", ".join(scopes))
        else:
            ok("Token-Scopes: %s" % ", ".join(scopes))
        if tk.get("expires_at"):
            info("Läuft ab am %s." % tk["expires_at"])
        else:
            warn("Der Token läuft nie ab. Besser ein Ablaufdatum setzen.")
    except Exception as e:
        log.debug("personal_access_tokens/self nicht lesbar: %s", e)
        info("Scopes konnten nicht gelesen werden (kein Problem, nur ein Hinweis).")
    return True


# ------------------------------------------------------------ Schritt 3: Projekte
def _repo_from(args):
    for a in args:
        if str(a).startswith("image.repository="):
            return a.split("=", 1)[1]
    return ""


def _project_helm(p, old):
    if not ask_yes("Testumgebung (Helm) für dieses Projekt einrichten?", bool(old.get("chart", True))):
        return
    p["chart"] = ask("Helm-Chart (Pfad im Repo)", old.get("chart", "./helm/%s" % p["name"]))
    p["repo_path"] = ask("Lokaler Klon des Projekts", old.get("repo_path", ""),
                         "Dort läuft helm, der Pfad aus «Helm-Chart» gilt relativ dazu")
    if p["repo_path"] and not Path(p["repo_path"]).expanduser().is_dir():
        warn("Ordner %s existiert nicht." % p["repo_path"])
    p["tag_template"] = ask("Image-Tag", old.get("tag_template", "{sha8}"),
                            "{sha8} = erste 8 Stellen des Commit-Hashes; deine CI muss das Image so taggen")
    repo = ask("Image-Repository (Harbor)", _repo_from(old.get("extra_args", [])))
    p["extra_args"] = ["--set", "image.repository=%s" % repo] if repo else []


def step_projects(ctx):
    cfg = ctx.cfg
    gl = ctx.gitlab()
    if not gl:
        warn("GitLab ist noch nicht eingerichtet (Schritt 2).")
        return False
    old = list(cfg.get("projects", []))
    if old:
        info("Schon eingetragen: " + ", ".join("%s (%s)" % (p.get("name"), p["id"]) for p in old))
        if ask_yes("Diese Projekte behalten?", True):
            return True
    info("Projekt suchen: Namen tippen. Oder direkt die Projekt-ID (Projektseite → ⋮ → «Projekt-ID kopieren»).")
    info("Leere Eingabe beendet die Liste.")
    out = []
    while True:
        q = ask("Projekt (Name oder ID)")
        if not q:
            break
        proj = None
        try:
            if q.isdigit():
                proj = gl.get("/projects/%s" % q)
            else:
                found = gl.get("/projects", {"membership": "true", "search": q, "simple": "true", "per_page": 10})
                if not found:
                    warn("Nichts gefunden für «%s» (nur Projekte, in denen du Mitglied bist)." % q)
                    continue
                n = pick("Nummer", [x.get("path_with_namespace", x.get("name")) for x in found])
                if n is None:
                    continue
                proj = gl.get("/projects/%s" % found[n]["id"])
        except Exception as e:
            explain(e)
            continue
        ok("%s (ID %s), Default-Branch: %s" % (proj.get("path_with_namespace"), proj["id"], proj.get("default_branch")))
        if any(p["id"] == proj["id"] for p in out):
            warn("Schon in der Liste.")
            continue
        prev = next((p for p in old if p["id"] == proj["id"]), {})
        p = {"id": proj["id"], "name": ask("Anzeigename", prev.get("name", proj.get("path", str(proj["id"]))))}
        _project_helm(p, prev)
        out.append(p)
    if not out:
        warn("Keine Projekte eingetragen. Das Panel zeigt dann nur die Review-Queue und zugeteilte MRs.")
    cfg["projects"] = out
    return True


# ------------------------------------------------------------ Schritt 4: Identität
def norm_trailer(line):
    """«Co-Authored-By: Claude Sonnet 5.5 <x>» wird zu «Co-Authored-By: Claude»: überlebt Modellwechsel."""
    body = line.split(":", 1)[1].strip().split("<")[0].strip()
    first = body.split()[0] if body.split() else body
    return "Co-Authored-By: " + first


def step_identity(ctx):
    cfg = ctx.cfg
    gl = ctx.gitlab()
    if not gl or not cfg.get("projects"):
        warn("Braucht GitLab und mindestens ein Projekt (Schritte 2 und 3).")
        return False
    info("Das Panel zeigt Branches ohne MR, auf denen du oder dein Agent committet hast.")
    info("Dafür muss es wissen, unter welchen Namen ihr committet. Ich schaue in die letzten Commits und lasse dich wählen.")
    pid = cfg["projects"][0]["id"]
    try:
        commits = gl.get("/projects/%s/repository/commits" % pid, {"all": "true", "per_page": 100})
    except Exception as e:
        explain(e)
        commits = []
    people = Counter()
    trailers = Counter()
    for cm in commits:
        people[(cm.get("author_name", ""), (cm.get("author_email") or "").lower())] += 1
        for line in (cm.get("message") or "").splitlines():
            if line.lower().startswith("co-authored-by:"):
                trailers[line.strip()] += 1
    me_email = (getattr(ctx, "me", None) or {}).get("email", "").lower()
    rows = people.most_common(12)
    bf = dict(cfg.get("branch_filter") or {})
    if rows:
        print()
        labels = []
        for (n, e), k in rows:
            tag = "  ← dein GitLab-Konto" if e and e == me_email else ""
            labels.append("%-28s %-34s %3d Commits%s" % (n[:28], e[:34], k, tag))
        for i, lb in enumerate(labels, 1):
            print("    %2d) %s" % (i, lb))
        dflt = ",".join(str(i + 1) for i, ((n, e), k) in enumerate(rows) if e and e == me_email)
        mine = ask("Welche Nummern bist DU? (Komma)", dflt, "Alle Zeilen, die du selbst bist (mehrere Adressen möglich)")
        agent = ask("Welche Nummer ist dein Agenten-Konto? (Komma, leer = keins)", "",
                    "Nur, wenn der Agent unter eigener Identität committet (zum Beispiel ein Bot-Benutzer)")

        def sel(txt):
            out = []
            for t in txt.split(","):
                t = t.strip()
                if t.isdigit() and 1 <= int(t) <= len(rows):
                    out.append(rows[int(t) - 1][0])
            return out
        me_rows, ag_rows = sel(mine), sel(agent)
        bf["emails"] = sorted({e for n, e in me_rows if e} | set(x for x in bf.get("emails", [])))
        bf["names"] = sorted({n for n, e in me_rows if n})
        bf["agent_emails"] = sorted({e for n, e in ag_rows if e})
        bf["agent_names"] = sorted({n for n, e in ag_rows if n})
    else:
        warn("Keine Commits gelesen. Du gibst die Werte von Hand ein.")
        bf["emails"] = ask_list("Deine Commit-E-Mails", bf.get("emails", []))
        bf["names"] = ask_list("Deine Autorennamen", bf.get("names", []))
        bf["agent_emails"] = ask_list("E-Mails des Agenten-Kontos (leer = keins)", bf.get("agent_emails", []))
        bf["agent_names"] = ask_list("Namen des Agenten-Kontos", bf.get("agent_names", []))
    pats = bf.get("agent_message_patterns", ["Co-Authored-By: Claude"])
    if trailers:
        print()
        info("Diese «Co-Authored-By»-Zeilen kommen in den Commit-Nachrichten vor:")
        tl = trailers.most_common(8)
        for i, (t, k) in enumerate(tl, 1):
            print("    %2d) %-70s %dx" % (i, t[:70], k))
        dflt = ",".join(str(i + 1) for i, (t, k) in enumerate(tl) if "claude" in t.lower() or "bot" in t.lower())
        sel_t = ask("Welche Nummern kennzeichnen deinen Agenten? (Komma, leer = keine)", dflt)
        chosen = [norm_trailer(tl[int(t) - 1][0]) for t in sel_t.split(",") if t.strip().isdigit() and 1 <= int(t) <= len(tl)]
        if chosen:
            info("Gespeichert wird nur der stabile Anfang (ohne Modellversion): " + ", ".join(sorted(set(chosen))))
        pats = sorted(set(chosen) | {p for p in pats if p and not p.lower().startswith("co-authored-by:")})
    bf["agent_message_patterns"] = pats
    if ask_yes("Grenzen (max. Branches, max. Alter) anpassen?", False):
        bf["max_branches"] = ask_int("Höchstens so viele Branches pro Projekt prüfen", bf.get("max_branches", 40))
        bf["max_age_days"] = ask_int("Branches älter als so viele Tage ignorieren (0 = nie)", bf.get("max_age_days", 90))
    cfg["branch_filter"] = bf
    cfg["my_emails"] = sorted(set(cfg.get("my_emails", [])) | set(bf.get("emails", [])))
    save_cfg(cfg)
    ok("Gespeichert: %d eigene E-Mails, %d Agenten-Konten, %d Muster" % (len(bf["emails"]), len(bf["agent_emails"]) + len(bf["agent_names"]),
                                                                         len(pats)))
    preview(ctx)
    return True


def preview(ctx):
    """Trockenlauf: zeigt, was das Panel mit dieser Config anzeigen würde."""
    info("Vorschau mit diesen Einstellungen (echte Abfrage, nur lesend):")
    try:
        s = ctx.server
        cfg = ctx.merged()
        tok, _ = ctx.secret("gitlab_token")
        t0 = time.time()
        data = s.GitLabClient(cfg, tok, ctx.ssl()).fetch()
    except Exception as e:
        explain(e)
        return
    br = [i for i in data["mine"] if i["kind"] == "branch"]
    ok("%d eigene MRs, %d Branches von dir/Agent, %d Review, %d zugeteilt (%.1f s)" % (
        len([i for i in data["mine"] if i["kind"] == "mr"]), len(br), len(data["review"]), len(data["assigned"]),
        time.time() - t0))
    for b in br[:8]:
        who = "Agent" if b.get("by_agent") else "von mir"
        info("%-14s %-42s %2d Commits, %s, %d Tage alt" % (b["project"][:14], b["branch"][:42], b.get("ahead", 0), who, b["age_days"]))
    if len(br) > 8:
        info("... und %d weitere" % (len(br) - 8))
    for e in data.get("errors", []):
        warn(e)
    if not br:
        info("Keine Branches gefunden. Das ist normal, wenn alles einen MR hat. Sonst: Schritt «identity» wiederholen.")


# ------------------------------------------------------------ Schritt 5: Jira
JQL_CHOICES = [
    'assignee = currentUser() AND statusCategory = "In Progress" ORDER BY updated DESC',
    'assignee = currentUser() AND status in ("In Progress", "In Bearbeitung") ORDER BY updated DESC',
]


def step_jira(ctx):
    cfg = ctx.cfg
    jc = dict(cfg.get("jira") or {})
    if not ask_yes("Jira anbinden? (Ticket-Verknüpfung und Story-Limit)", bool(jc.get("url"))):
        cfg["jira"] = {}
        info("Übersprungen. Das Panel läuft auch ohne Jira.")
        return True
    jc["url"] = ask("Jira-URL", jc.get("url", ""), "zum Beispiel https://jira.firma.example (ohne /jira-Pfad, falls es keinen gibt)").rstrip("/")
    jc["auth"] = ask("Anmeldung: bearer (Personal Access Token) oder basic (Benutzer + Passwort)", jc.get("auth", "bearer"))
    while jc["auth"] not in ("bearer", "basic"):
        jc["auth"] = ask("Bitte bearer oder basic", "bearer")
    jc["username"] = ask("Jira-Benutzername", jc.get("username", "")) if jc["auth"] == "basic" else ""
    cfg["jira"] = jc
    save_cfg(cfg)
    name = "jira_token" if jc["auth"] == "bearer" else "jira_password"
    if jc["auth"] == "bearer":
        info("Token anlegen: %s/secure/ViewProfile.jspa → Personal Access Tokens → Create token" % jc["url"])
        info("Ein Jira-Token hat die Rechte deines Kontos; lesend beschränken lässt er sich nicht.")
    if not need_secret(ctx, name, "Jira-Token" if jc["auth"] == "bearer" else "Jira-Passwort"):
        warn("Ohne Zugangsdaten kein Test. Später: python3 setup.py --step jira")
        return False
    while True:
        try:
            jh = ctx.jira()
            me = jh.get("/myself")
            ok("Angemeldet als %s (%s)" % (me.get("name"), me.get("displayName")))
            break
        except (Exception, SystemExit) as e:
            explain(e)
            if not ask_yes("Nochmal versuchen (URL oder Zugangsdaten korrigieren)?", True):
                return False
            jc["url"] = ask("Jira-URL", jc["url"]).rstrip("/")
            save_cfg(cfg)
            try:
                store.delete_secret(name)
            except store.SecretError:
                pass
            need_secret(ctx, name, "Jira-Token" if jc["auth"] == "bearer" else "Jira-Passwort")

    # Projekt-Keys
    keys = []
    try:
        projects = jh.get("/project")
        keys = sorted(p["key"] for p in projects)
        ok("%d Jira-Projekte sichtbar" % len(keys))
    except Exception as e:
        log.debug("Projektliste nicht lesbar: %s", e)
    shown = ", ".join(keys[:40]) + (" ..." if len(keys) > 40 else "")
    jc["project_keys"] = [k.upper() for k in ask_list("Deine Projekt-Keys (Komma getrennt)", jc.get("project_keys", []),
                                                      ("Sichtbar: " + shown) if keys else "zum Beispiel DLP, OPS")]
    unknown = [k for k in jc["project_keys"] if keys and k not in keys]
    if unknown:
        warn("Nicht in der sichtbaren Liste: %s (Tippfehler oder fehlende Rechte?)" % ", ".join(unknown))
    jc["story_limit"] = ask_int("Höchstens so viele Stories gleichzeitig in Arbeit", jc.get("story_limit", 2))

    # Vorgangstypen
    try:
        types = sorted({t["name"] for t in jh.get("/issuetype")})
        info("Vorgangstypen in deinem Jira: " + ", ".join(types))
    except Exception:
        types = []
    jc["wip_issue_types"] = ask_list("Welche Vorgangstypen zählen beim Limit?", jc.get("wip_issue_types", ["Story"]),
                                     "In deutscher Oberfläche zum Beispiel «Story» oder «Aufgabe»")
    try:
        statuses = sorted({s["name"] for s in jh.get("/status")})
        info("Status in deinem Jira: " + ", ".join(statuses[:30]))
    except Exception:
        pass

    # JQL testen
    cur = jc.get("jql_in_progress") or JQL_CHOICES[0]
    while True:
        jql = ask("JQL für «in Arbeit»", cur)
        try:
            res = jh.get("/search", {"jql": jql, "fields": "summary,status,issuetype", "maxResults": 10})
            total = int(res.get("total", 0))
            ok("JQL gültig: %d Treffer" % total)
            for i in res.get("issues", [])[:6]:
                f = i.get("fields") or {}
                info("%-10s %-12s %-12s %s" % (i["key"], (f.get("issuetype") or {}).get("name", "")[:12],
                                                (f.get("status") or {}).get("name", "")[:12], (f.get("summary") or "")[:50]))
            if total == 0:
                warn("0 Treffer. Stimmt das, oder heißt der Status in deinem Jira anders? Alternative: " + JQL_CHOICES[1])
            if ask_yes("Diese JQL verwenden?", True):
                jc["jql_in_progress"] = jql
                break
            cur = jql
        except (Exception, SystemExit) as e:
            explain(e)
            warn("Jira meldet die JQL als fehlerhaft. Vorschlag: " + JQL_CHOICES[1])
            cur = JQL_CHOICES[1]
    jc.pop("helpdesk", None)
    cfg["jira"] = jc
    return True


# ------------------------------------------------------------ Schritt 6: Cluster
def step_cluster(ctx):
    cfg = ctx.cfg
    if not shutil.which("kubectl"):
        warn("kubectl nicht gefunden. Die Testumgebungs-Knöpfe bleiben gesperrt, bis ein kubectl_context eingetragen ist.")
        cfg["kube_context"] = ask("kubectl-Kontext (leer = später)", cfg.get("kube_context", ""))
        return True
    info("Das Panel fasst nur diesen einen Kontext an. Namespaces heißen test-<projekt>-<mr>, nur solche werden abgebaut.")
    try:
        r = subprocess.run(["kubectl", "config", "get-contexts", "-o", "name"], capture_output=True, text=True, timeout=10)
        ctxs = [x for x in r.stdout.split() if x]
    except (OSError, subprocess.SubprocessError):
        ctxs = []
    if ctxs:
        cur = cfg.get("kube_context", "")
        n = pick("Nummer des Test-Kontexts (leer = später)", ctxs, ctxs.index(cur) if cur in ctxs else None)
        cfg["kube_context"] = ctxs[n] if n is not None else cur
    else:
        cfg["kube_context"] = ask("kubectl-Kontext", cfg.get("kube_context", ""))
    kc = cfg["kube_context"]
    if kc:
        if any(w in kc.lower() for w in ("prod", "prd", "live")):
            warn("«%s» sieht nach Produktion aus. Testumgebungen gehören nicht dorthin." % kc)
            if not ask_yes("Trotzdem verwenden?", False):
                cfg["kube_context"] = ""
                return True
        try:
            r = subprocess.run(["kubectl", "--context", kc, "get", "namespaces", "-o", "name", "--request-timeout=8s"],
                               capture_output=True, text=True, timeout=20)
            if r.returncode == 0:
                ok("Cluster %s erreichbar (%d Namespaces sichtbar, nur lesend geprüft)" % (kc, len(r.stdout.split())))
            else:
                warn("Cluster %s nicht erreichbar: %s" % (kc, (r.stderr or "?").strip().splitlines()[-1][:160]))
        except (OSError, subprocess.SubprocessError) as e:
            warn("Test fehlgeschlagen: %s" % e)
    cfg["namespace_prefix"] = ask("Namespace-Präfix", cfg.get("namespace_prefix", "test"))
    return True


# ------------------------------------------------------------ Schritt 7: Zugriff
def step_access(ctx):
    cfg = ctx.cfg
    info("127.0.0.1 = nur dieser Rechner (empfohlen; auf der VM per ssh -L erreichen). Alles andere verlangt einen Zugriffstoken.")
    cfg["bind"] = ask("Adresse, auf der das Panel lauscht", cfg.get("bind", "127.0.0.1"))
    cfg["port"] = ask_int("Port", cfg.get("port", 8765))
    if cfg["bind"] not in LOOP:
        cfg["allowed_hosts"] = ask_list("Erlaubte Hostnamen (wie im Browser eingegeben)", cfg.get("allowed_hosts", []),
                                        "zum Beispiel vm-office, 10.0.0.5")
        val, src = ctx.secret("access_token")
        if val:
            ok("access_token ist schon gesetzt (← %s)" % src)
        elif ask_yes("Zufälligen Zugriffstoken erzeugen und speichern?", True):
            tok = pysecrets.token_urlsafe(32)
            where = store.set_secret("access_token", tok)
            ok("access_token gespeichert (%s)" % where)
            info("Erster Aufruf im Browser: http://<host>:%s/?token=%s" % (cfg["port"], tok))
            info("(Wird nur jetzt angezeigt. Danach merkt sich der Browser ein Cookie.)")
        else:
            need_secret(ctx, "access_token", "Zugriffstoken")
    cfg["log_level"] = ask("Log-Stufe", cfg.get("log_level", "info"), "info = Überblick, debug = jede Anfrage und jede Branch-Entscheidung")
    return True


# ------------------------------------------------------------ Schritt 8: Abschlusstest
def run_doctor(ctx, quiet=False):
    """Prüft alles gegen das echte System. Gibt die Zahl der Probleme zurück."""
    problems = 0
    cfg = ctx.cfg
    if not CONFIG.exists():
        bad("config.json fehlt (python3 setup.py)")
        return 1
    try:
        ctx.server.reject_plain_secrets(cfg)
        ok("config.json lesbar, keine Secrets darin")
    except SystemExit as e:
        bad(str(e).splitlines()[0])
        problems += 1
    for n in store.NAMES:
        val, src = ctx.secret(n)
        need = (n == "gitlab_token") or (n == "jira_token" and (cfg.get("jira") or {}).get("url") and (cfg["jira"].get("auth", "bearer") == "bearer")) \
            or (n == "jira_password" and (cfg.get("jira") or {}).get("url") and (cfg["jira"].get("auth") == "basic")) \
            or (n == "access_token" and cfg.get("bind", "127.0.0.1") not in LOOP)
        if val:
            ok("%s ← %s" % (n, src))
        elif need:
            bad("%s fehlt (python3 setup.py --step %s)" % (n, "gitlab" if n == "gitlab_token" else "access" if n == "access_token" else "jira"))
            problems += 1
        else:
            info("%s: nicht gesetzt, wird nicht gebraucht" % n)
    gl = ctx.gitlab()
    if gl:
        try:
            me = gl.get("/user")
            ok("GitLab: %s" % me["username"])
            ctx.me = me
            for p in cfg.get("projects", []):
                pr = gl.get("/projects/%s" % p["id"])
                ok("Projekt %s → %s" % (p["id"], pr.get("path_with_namespace")))
        except Exception as e:
            bad("GitLab: %s" % e)
            problems += 1
    if (cfg.get("jira") or {}).get("url"):
        try:
            jh = ctx.jira()
            if jh:
                me = jh.get("/myself")
                ok("Jira: %s" % me.get("name"))
                res = jh.get("/search", {"jql": cfg["jira"].get("jql_in_progress") or JQL_CHOICES[0], "maxResults": 0})
                ok("Jira-JQL gültig, %s Treffer «in Arbeit»" % res.get("total"))
        except (Exception, SystemExit) as e:
            bad("Jira: %s" % e)
            problems += 1
    if cfg.get("kube_context"):
        if shutil.which("kubectl"):
            ok("kube_context: %s" % cfg["kube_context"])
        else:
            warn("kubectl fehlt, Testumgebungen gehen nicht")
    else:
        info("kube_context leer: Testumgebungs-Knöpfe sind gesperrt")
    if gl and not quiet:
        preview(ctx)
    return problems


def step_finish(ctx):
    n = run_doctor(ctx)
    print()
    if n:
        warn("%d Problem(e). Die genannten Schritte lassen sich einzeln wiederholen." % n)
    else:
        ok("Alles in Ordnung.")
    info("Start:            ./run.sh            (Adresse: http://%s:%s)" % (ctx.cfg.get("bind", "127.0.0.1"), ctx.cfg.get("port", 8765)))
    info("Mehr Details:     ./run.sh -v         (DEBUG: jede Anfrage, jede Branch-Entscheidung)")
    info("Log ansehen:      python3 server.py --show-log 100     oder im Panel: Knopf «Log»")
    info("Logdatei:         %s" % tlog.log_file(ctx.cfg))
    return True


# ------------------------------------------------------------ Ablauf
class StopSetup(Exception):
    pass


STEPS = [
    ("preflight", "Voraussetzungen prüfen", step_preflight),
    ("gitlab", "GitLab verbinden", step_gitlab),
    ("projects", "Projekte wählen", step_projects),
    ("identity", "Deine Commits und die deines Agenten", step_identity),
    ("jira", "Jira verbinden", step_jira),
    ("cluster", "Cluster und Testumgebung", step_cluster),
    ("access", "Zugriff auf das Panel", step_access),
    ("finish", "Abschlusstest", step_finish),
]


def run_steps(ctx, names):
    total = len(STEPS)
    for idx, (sid, title, fn) in enumerate(STEPS, 1):
        if sid not in names:
            continue
        print("\n" + c("1", "━━ Schritt %d/%d · %s " % (idx, total, title) + "━" * max(2, 50 - len(title))))
        log.info("Schritt %d/%d %s beginnt", idx, total, sid)
        while True:
            try:
                done = fn(ctx)
            except KeyboardInterrupt:
                raise
            except StopSetup as e:
                print("  " + str(e))
                raise
            except Exception as e:   # ein Fehler in einem Schritt soll nicht alles verwerfen
                log.exception("Schritt %s abgebrochen", sid)
                bad("Unerwarteter Fehler: %s (Details im Log)" % e)
                done = False
            save_cfg(ctx.cfg)
            if done:
                log.info("Schritt %s abgeschlossen", sid)
                break
            if sid == "finish" or not ask_yes("Schritt «%s» wiederholen?" % title, True):
                warn("Schritt «%s» ist offen. Später: python3 setup.py --step %s" % (sid, sid))
                break


def main():
    ap = argparse.ArgumentParser(description="tinyops Einrichtung in Schritten")
    ap.add_argument("--list", action="store_true", help="Schritte anzeigen")
    ap.add_argument("--step", choices=[s[0] for s in STEPS], help="nur diesen Schritt ausführen")
    ap.add_argument("--from", dest="from_step", choices=[s[0] for s in STEPS], help="ab diesem Schritt weitermachen")
    ap.add_argument("--doctor", "--check", dest="doctor", action="store_true", help="nur prüfen, nichts ändern")
    args = ap.parse_args()

    if args.list:
        for i, (sid, title, _) in enumerate(STEPS, 1):
            print("%d. %-10s %s" % (i, sid, title))
        return
    cfg, existed = load_cfg()
    tlog.setup(cfg, "debug", console=False)   # Einrichtung schreibt immer ausführlich ins Log
    log.info("Einrichtung gestartet (Python %s, Argumente: %s)", sys.version.split()[0], " ".join(sys.argv[1:]) or "keine")
    ctx = Ctx(cfg)
    try:
        if args.doctor:
            print(c("1", "━━ Prüfung (ändert nichts) ━━"))
            sys.exit(1 if run_doctor(ctx) else 0)
        if args.step:
            names = {args.step}
        elif args.from_step:
            names = {s[0] for s in STEPS[[s[0] for s in STEPS].index(args.from_step):]}
        else:
            names = {s[0] for s in STEPS}
        print(c("1", "tinyops Einrichtung") + "  (Enter übernimmt den Wert in [Klammern], Ctrl+C bricht ab, Fortschritt bleibt gespeichert)")
        print("Log: %s" % tlog.log_file(cfg))
        if existed and CONFIG.exists():
            shutil.copy2(str(CONFIG), str(CONFIG) + ".bak")
            os.chmod(str(CONFIG) + ".bak", 0o600)
            info("Bestehende config.json wird als Vorgabe geladen, Sicherung: config.json.bak")
        elif not existed:
            cfg.pop("secrets", None)
            cfg.update({"projects": [], "my_emails": [], "branch_filter": {}, "jira": {}, "gitlab_url": "", "kube_context": ""})
            ctx.cfg = cfg
        run_steps(ctx, names)
    except KeyboardInterrupt:
        print("\nAbgebrochen. Bisher gespeicherte Schritte bleiben erhalten (python3 setup.py --from <schritt>).")
        sys.exit(1)
    except StopSetup:
        sys.exit(1)


if __name__ == "__main__":
    main()
