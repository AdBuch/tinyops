#!/usr/bin/env python3
"""tinyops Einrichtung: fragt alles ab, schreibt config.json (ohne Secrets) und speichert die Secrets sicher.

    python3 setup.py            # komplette Einrichtung (bestehende config.json liefert die Vorgaben)
    python3 setup.py --check    # nur Schlüsselbund und gespeicherte Secrets prüfen
    python3 setup.py --secrets  # nur Secrets neu eingeben
"""
import argparse
import getpass
import json
import os
import sys
import tempfile
from pathlib import Path

BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE))
import secretstore as store  # noqa: E402

CONFIG = BASE / "config.json"
EXAMPLE = BASE / "config.example.json"


# ------------------------------------------------------------ Eingabe
def ask(label, default="", hint=""):
    suffix = " [%s]" % default if default else ""
    if hint:
        print("  " + hint)
    try:
        v = input("%s%s: " % (label, suffix)).strip()
    except EOFError:
        v = ""
    return v or default


def ask_yes(label, default=True):
    d = "J/n" if default else "j/N"
    try:
        v = input("%s (%s): " % (label, d)).strip().lower()
    except EOFError:
        v = ""
    return default if not v else v in ("j", "ja", "y", "yes")


def ask_list(label, default, hint=""):
    v = ask(label, ", ".join(default), hint)
    return [x.strip() for x in v.split(",") if x.strip()]


def head(text):
    print("\n== %s ==" % text)


# ------------------------------------------------------------ Schlüsselbund
def keyring_status():
    """Gibt (ok, Text) zurück. Macht einen echten Schreib-/Lesetest mit einem Wegwerf-Eintrag."""
    try:
        import keyring
    except ImportError:
        return False, ("Das Python-Paket 'keyring' ist für %s nicht installiert.\n"
                       "    Debian/Ubuntu: sudo apt install python3-keyring     (nur für das System-Python)\n"
                       "    oder in einer venv: python3 -m venv .venv && .venv/bin/pip install keyring\n"
                       "                        dann alles mit .venv/bin/python setup.py starten (run.sh nimmt .venv automatisch)"
                       % sys.executable)
    kr = keyring.get_keyring()
    name = "%s.%s" % (type(kr).__module__, type(kr).__name__)
    from keyring.backends import fail
    if isinstance(kr, fail.Keyring):
        return False, ("keyring ist installiert, findet aber keinen Schlüsselbund-Dienst.\n"
                       "    Läuft ein Secret-Service? (GNOME Keyring, KDE Wallet mit Secret-Service, KeePassXC)\n"
                       "    Ohne Desktop-Sitzung (SSH, VM): siehe README, Abschnitt «Schlüsselbund unter Linux».")
    try:
        keyring.set_password(store.SERVICE, "_selftest", "x")
        ok = keyring.get_password(store.SERVICE, "_selftest") == "x"
        keyring.delete_password(store.SERVICE, "_selftest")
    except Exception as e:
        return False, ("Backend %s gefunden, aber der Test schlug fehl: %s\n"
                       "    Meist ist der Schlüsselbund gesperrt oder es gibt keinen D-Bus der Sitzung." % (name, e))
    return ok, "Backend %s funktioniert (Schreib-/Lesetest bestanden)." % name


def show_secret_state():
    head("Gespeicherte Secrets")
    for n in store.NAMES:
        val, src = store.resolve(n)
        print("  %-14s %s" % (n, ("← " + src) if val else "nicht gesetzt"))


# ------------------------------------------------------------ Config
def load_base():
    path = CONFIG if CONFIG.exists() else EXAMPLE
    with open(path, encoding="utf-8") as f:
        cfg = json.load(f)
    return cfg, CONFIG.exists()


def write_config(cfg):
    fd, tmp = tempfile.mkstemp(dir=str(BASE), prefix=".config.", suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)
        f.write("\n")
    os.chmod(tmp, 0o600)
    os.replace(tmp, CONFIG)


def ask_projects(existing):
    print("\nProjekte (GitLab-Projekt-ID: Projektseite → ⋮ → «Projekt-ID kopieren»). Leere ID beendet die Eingabe.")
    out, old = [], list(existing)
    while True:
        o = old.pop(0) if old else {}
        pid = ask("  Projekt-ID", str(o.get("id", "")) if o else "")
        if not pid:
            break
        if not pid.isdigit():
            print("  Die ID besteht nur aus Ziffern, nochmals.")
            if o:
                old.insert(0, o)
            continue
        p = {"id": int(pid), "name": ask("  Anzeigename", o.get("name", "projekt-%s" % pid))}
        if ask_yes("  Testumgebung (Helm) für dieses Projekt einrichten?", bool(o.get("chart", True))):
            p["chart"] = ask("    Helm-Chart (Pfad)", o.get("chart", "./helm/%s" % p["name"]))
            p["repo_path"] = ask("    Lokaler Klon (Pfad)", o.get("repo_path", ""))
            p["tag_template"] = ask("    Image-Tag", o.get("tag_template", "{sha8}"),
                                    "{sha8} = erste 8 Stellen des Commit-Hashes (deine CI muss so taggen)")
            repo = ask("    Image-Repository (Harbor)", _repo_from(o.get("extra_args", [])))
            p["extra_args"] = ["--set", "image.repository=%s" % repo] if repo else []
        out.append(p)
    return out


def _repo_from(args):
    for a in args:
        if str(a).startswith("image.repository="):
            return a.split("=", 1)[1]
    return ""


def ask_config(cfg):
    head("GitLab")
    cfg["gitlab_url"] = ask("GitLab-URL", cfg.get("gitlab_url", ""), "zum Beispiel https://gitlab.firma.example").rstrip("/")
    if cfg["gitlab_url"].startswith("http://"):
        print("  Achtung: http:// überträgt den Token unverschlüsselt.")
    cfg["ca_bundle"] = ask("Firmen-CA (PEM-Datei, leer = Systemzertifikate)", cfg.get("ca_bundle", ""))
    cfg["my_emails"] = ask_list("Deine Commit-E-Mails (Komma getrennt)", cfg.get("my_emails", []),
                                "Alle Adressen, unter denen du committest (git config user.email)")

    head("Branches von dir und deinem Agenten")
    bf = dict(cfg.get("branch_filter") or {})
    bf["names"] = ask_list("Deine Autorennamen", bf.get("names", []), "git config user.name, falls abweichend vom GitLab-Namen")
    bf["agent_emails"] = ask_list("E-Mails des Agenten-Kontos (leer, wenn er unter deinem Namen committet)", bf.get("agent_emails", []))
    bf["agent_names"] = ask_list("Namen des Agenten-Kontos", bf.get("agent_names", []))
    bf["agent_message_patterns"] = ask_list("Muster in Commit-Nachrichten, die Agent-Commits markieren",
                                            bf.get("agent_message_patterns", ["Co-Authored-By: Claude"]))
    bf["emails"] = bf.get("emails", [])
    bf["max_branches"] = int(ask("Höchstens so viele Branches pro Projekt prüfen", str(bf.get("max_branches", 40))) or 40)
    bf["max_age_days"] = int(ask("Branches älter als so viele Tage ignorieren (0 = nie)", str(bf.get("max_age_days", 90))) or 0)
    cfg["branch_filter"] = bf

    head("Projekte")
    cfg["projects"] = ask_projects(cfg.get("projects", []))

    head("Jira")
    jc = dict(cfg.get("jira") or {})
    if ask_yes("Jira anbinden?", bool(jc.get("url"))):
        jc["url"] = ask("Jira-URL", jc.get("url", ""), "zum Beispiel https://jira.firma.example").rstrip("/")
        jc["auth"] = ask("Anmeldung: bearer (Personal Access Token) oder basic (Benutzer + Passwort)",
                         jc.get("auth", "bearer"))
        while jc["auth"] not in ("bearer", "basic"):
            jc["auth"] = ask("Bitte bearer oder basic", "bearer")
        jc["username"] = ask("Jira-Benutzername", jc.get("username", "")) if jc["auth"] == "basic" else ""
        jc["project_keys"] = ask_list("Projekt-Keys (Komma getrennt)", jc.get("project_keys", []), "zum Beispiel DLP, OPS")
        jc["story_limit"] = int(ask("Höchstens so viele Stories gleichzeitig in Arbeit", str(jc.get("story_limit", 2))) or 2)
        types = ask_list("Vorgangstypen, die zählen", jc.get("wip_issue_types", ["Story"]), "in deutschem Jira evtl. «Story» oder «Aufgabe»")
        jc["wip_issue_types"] = types
        jc["jql_in_progress"] = ask("JQL für «in Arbeit»", jc.get("jql_in_progress",
                                    'assignee = currentUser() AND statusCategory = "In Progress" ORDER BY updated DESC'),
                                    "Im Jira-Suchfeld testen! Bei deutscher Oberfläche ggf. anpassen")
        jc.pop("helpdesk", None)   # Helpdesk bleibt aus
    else:
        jc = {}
    cfg["jira"] = jc

    head("Cluster und Zugriff")
    cfg["kube_context"] = ask("kubectl-Kontext der Testumgebung", cfg.get("kube_context", ""),
                              "kubectl config get-contexts. Ohne Eintrag startet das Panel keine Testumgebungen")
    cfg["bind"] = ask("Adresse, auf der das Panel lauscht", cfg.get("bind", "127.0.0.1"),
                      "127.0.0.1 = nur dieser Rechner (empfohlen). Alles andere erzwingt einen Zugriffstoken")
    cfg["port"] = int(ask("Port", str(cfg.get("port", 8765))) or 8765)
    if cfg["bind"] not in ("127.0.0.1", "localhost", "::1"):
        cfg["allowed_hosts"] = ask_list("Erlaubte Hostnamen (Host-Header)", cfg.get("allowed_hosts", []), "zum Beispiel vm-office, 10.0.0.5")
    return cfg


# ------------------------------------------------------------ Secrets
def collect_secrets(cfg):
    head("Zugangsdaten")
    ok, text = keyring_status()
    print(("  OK: " if ok else "  Kein Schlüsselbund: ") + text)
    if not ok:
        print("  Die Secrets landen sonst in %s (Klartext, nur für deinen Benutzer lesbar)." % store.secrets_file())
        if not ask_yes("  Trotzdem fortfahren?", True):
            print("  Abgebrochen. Secrets lassen sich später mit: python3 setup.py --secrets")
            return
    jc = cfg.get("jira") or {}
    wanted = [("gitlab_token", "GitLab-Token (Scope read_api)")]
    if jc.get("url"):
        wanted.append(("jira_token", "Jira Personal Access Token") if jc.get("auth") == "bearer"
                      else ("jira_password", "Jira-Passwort für %s" % jc.get("username")))
    if cfg.get("bind") not in ("127.0.0.1", "localhost", "::1"):
        wanted.append(("access_token", "Zugriffstoken fürs Panel (frei wählbar, lang und zufällig)"))
    for name, label in wanted:
        val, src = store.resolve(name)
        if val and not ask_yes("  %s ist schon gesetzt (← %s). Überschreiben?" % (name, src), False):
            continue
        if name == "access_token" and ask_yes("  Zufälligen Zugriffstoken erzeugen?", True):
            import secrets
            value = secrets.token_urlsafe(32)
            print("  Erzeugt. Für den ersten Aufruf: http://<host>:%s/?token=%s" % (cfg.get("port", 8765), value))
            print("  (Wird nur jetzt angezeigt und nicht im Log gespeichert.)")
        else:
            value = getpass.getpass("  %s (Eingabe unsichtbar, Enter = überspringen): " % label)
        if not value:
            print("  %s übersprungen." % name)
            continue
        try:
            print("  %s gespeichert in: %s" % (name, store.set_secret(name, value)))
        except store.SecretError as e:
            print("  Fehler: %s" % e)


# ------------------------------------------------------------ Verbindungstest
def test_connections(cfg):
    head("Verbindungstest (nur lesend)")
    import server
    ctx = server.make_ssl(cfg)
    tok, _ = store.resolve("gitlab_token")
    if tok and cfg.get("gitlab_url"):
        store.register(tok)
        try:
            me = server.Http("GitLab", cfg["gitlab_url"], {"PRIVATE-TOKEN": tok, "Accept": "application/json"}, ctx).get("/api/v4/user")
            print("  GitLab OK: angemeldet als %s (%s)" % (me.get("username"), me.get("email", "keine E-Mail sichtbar")))
            if me.get("email") and me["email"].lower() not in [e.lower() for e in cfg.get("my_emails", [])]:
                print("  Hinweis: %s steht nicht in my_emails; das Panel nimmt sie automatisch dazu." % me["email"])
        except Exception as e:
            print("  GitLab FEHLER: %s" % e)
    jc = cfg.get("jira") or {}
    if jc.get("url"):
        name = "jira_token" if jc.get("auth") == "bearer" else "jira_password"
        sec, _ = store.resolve(name)
        if sec:
            store.register(sec)
            try:
                hdr = server.jira_auth_header(jc, {name: sec})
                me = server.Http("Jira", jc["url"], {"Authorization": hdr, "Accept": "application/json"}, ctx).get("/rest/api/2/myself")
                print("  Jira OK: angemeldet als %s" % (me.get("name") or me.get("displayName")))
            except (Exception, SystemExit) as e:
                print("  Jira FEHLER: %s" % e)


# ------------------------------------------------------------ Hauptprogramm
def main():
    ap = argparse.ArgumentParser(description="tinyops Einrichtung")
    ap.add_argument("--check", action="store_true", help="nur Schlüsselbund und Secrets prüfen")
    ap.add_argument("--secrets", action="store_true", help="nur Secrets neu eingeben")
    args = ap.parse_args()

    print("tinyops Einrichtung (Python %s). Enter übernimmt den Wert in [Klammern]. Ctrl+C bricht ab." % sys.version.split()[0])
    try:
        if args.check:
            ok, text = keyring_status()
            print(("OK: " if ok else "PROBLEM: ") + text)
            show_secret_state()
            return
        cfg, existed = load_base()
        if args.secrets:
            if not existed:
                raise SystemExit("Keine config.json gefunden. Erst python3 setup.py ohne Optionen.")
        else:
            if existed:
                print("Bestehende config.json wird als Vorgabe geladen. Eine Sicherung kommt nach config.json.bak.")
                CONFIG.replace(CONFIG.with_suffix(".json.bak"))
            cfg = ask_config(cfg)
            cfg.pop("secrets", None)
            write_config(cfg)
            print("\nconfig.json geschrieben (Rechte 600, keine Secrets darin).")
        collect_secrets(cfg)
        if ask_yes("\nVerbindungen jetzt testen?", True):
            test_connections(cfg)
        show_secret_state()
        print("\nFertig. Start: ./run.sh")
    except KeyboardInterrupt:
        print("\nAbgebrochen.")
        sys.exit(1)


if __name__ == "__main__":
    main()
