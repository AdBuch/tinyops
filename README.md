# tinyops 1.2: Arbeitspanel

Ein kleines lokales Panel. Nur Python (getestet mit 3.13, sollte ab 3.9 laufen), keine Pflicht-Abhängigkeiten.

**Kann:** deine Branches und MRs mit Pipeline-Status zeigen, sie mit Jira-Tickets verknüpfen, die Stories in Arbeit
gegen ein Limit zählen, die Review-Queue und dir zugeteilte MRs zeigen, offene Branches mit deinen oder Agent-Commits zeigen, eine Ideenbox
führen, pro MR eine Testumgebung im Cluster starten und fertige Prompts füllen.

**Kann bewusst nicht:** approven, mergen, pushen, in Jira schreiben. Das Panel liest nur.

## 1. Ansehen (ohne GitLab und Jira)

    ./run.sh --demo        # dann http://localhost:8765 öffnen

## 2. Mit deinem GitLab und Jira

**Am einfachsten:** `python3 setup.py` fragt alles ab (URLs, Projekte, Jira, Branch-Filter, Cluster), schreibt die
`config.json` (Rechte 600, ohne Secrets), speichert die Tokens im Schlüsselbund und testet die Verbindungen (nur lesend).
Erneut ausführbar: Die bestehende Config liefert die Vorgaben, die alte kommt nach `config.json.bak`.
`python3 setup.py --check` prüft nur den Schlüsselbund, `--secrets` gibt nur die Tokens neu ein.

Von Hand:

1. `cp config.example.json config.json` und anpassen (URLs, Projekt-IDs, `jira.project_keys`, `kube_context`).
2. Zugangsdaten sicher speichern (Abschnitt 3). **Nie in die config.json schreiben**, das Panel verweigert dann den Start.
3. Starten: `./run.sh`

Tokens besorgen:
- **GitLab:** Profil → Access Tokens, Scope **`read_api`** reicht.
- **Jira 9.4:** Profil → Personal Access Tokens → Token erstellen (Auth `bearer`). Ein Jira-Token hat immer die Rechte
  deines Kontos, man kann es nicht auf «nur lesen» beschränken. Frag, ob ihr ein Lesekonto nehmen könnt.
- Benutzername und Passwort (`"auth": "basic"`, Benutzername in `jira.username`) gehen auch, sind aber schlechter:
  Mehrfach falsche Passwörter können in Jira eine CAPTCHA-Sperre auslösen.

## 3. Zugangsdaten sicher speichern

Die config.json enthält nur Adressen und Benutzernamen. Secrets (`gitlab_token`, `jira_token`, `jira_password`,
`access_token`) kommen aus dem Secret-Speicher. Quellen in dieser Reihenfolge:

| Quelle | Wann sinnvoll | Einrichten |
| --- | --- | --- |
| Befehl aus der Config | Du hast einen Passwortmanager (`pass`, `secret-tool`, `gpg`, `op`) | `"secrets": {"jira_token": {"cmd": ["pass", "show", "tinyops/jira"]}}` |
| Umgebungsvariable | CI, systemd, kurze Tests | `TINYOPS_JIRA_TOKEN=...` (Name: `TINYOPS_` + Secret-Name in Großbuchstaben) |
| Schlüsselbund des Betriebssystems | Laptop, empfohlen | `pip install keyring`, dann `--set-secret` (nutzt ihn automatisch) |
| Datei `~/.config/tinyops/secrets.json` | Auf der VM ohne Schlüsselbund | `--set-secret` legt sie mit Rechten 600 an |

Befehle:

    python3 server.py --set-secret jira_token       # fragt ohne Echo ab
    pass show tinyops/jira | python3 server.py --set-secret jira_token   # aus einer Pipe
    python3 server.py --list-secrets                # zeigt, WOHER ein Secret kommt, nie den Wert
    python3 server.py --delete-secret jira_token

Was das Panel dafür tut:
- Die Datei liegt außerhalb des Projektordners (kein versehentlicher Git-Commit, kein Zip-Versand) und ist nur für
  deinen Benutzer lesbar. Sind die Rechte offener, **verweigert** das Panel das Lesen.
- Secrets gehen nie an den Browser und werden aus Fehlern, Job-Logs und Serverlog geschwärzt.
- Der Zugriffstoken steht nicht im Cookie (nur ein Hash) und nicht im Log. Die Adresse mit `?token=` wird sofort
  durch eine Weiterleitung ersetzt.
- Weiterleitungen werden nicht befolgt: Dein Token kann so nicht an einen anderen Host geschickt werden.
- Gestartete Jobs (Deploy, Agent) erben keine Secret-Umgebungsvariablen (`TINYOPS_*`, `GITLAB_TOKEN`).
- Läuft GitLab oder Jira über `http://`, gibt es eine Warnung, weil der Token dann unverschlüsselt über das Netz geht.

Ehrlich dazu: **Die Datei ist Klartext.** Rechte 600 schützen vor anderen Benutzern, nicht vor Root und nicht vor
Schadsoftware unter deinem Konto. Schlüsselbund oder Passwortmanager-Befehl sind besser. Getestet habe ich Datei,
Befehl und Umgebungsvariable, den Schlüsselbund nicht (ist hier nicht installiert). Unter Windows lassen sich
Dateirechte nicht prüfen, nimm dort den Schlüsselbund oder einen Befehl.

### Schlüsselbund unter Linux (Schritt für Schritt)

Das Panel nutzt das Python-Paket `keyring`, das über D-Bus mit dem **Secret-Service** deines Desktops spricht
(GNOME Keyring/«Passwörter und Schlüssel», KDE Wallet mit aktivierter Secret-Service-Schnittstelle, KeePassXC).

1. **Paket besorgen** (dasselbe Python, das auch `server.py` startet):
   - Debian/Ubuntu: `sudo apt install python3-keyring` (gilt nur für `/usr/bin/python3`), oder
   - venv: `python3 -m venv .venv && .venv/bin/pip install keyring`. `run.sh` nimmt `.venv` automatisch, `setup.py` startest du dann mit `.venv/bin/python setup.py`.
     (Ein venv ist die sauberere Wahl, wenn `pip` sonst `externally-managed-environment` meldet.)
2. **Prüfen:** `python3 setup.py --check` macht einen echten Schreib-/Lesetest mit einem Wegwerf-Eintrag und nennt das Backend.
   Gewünscht: `keyring.backends.SecretService.Keyring`. Zeigt es `fail.Keyring`, läuft kein Secret-Service.
3. **Speichern:** `python3 setup.py` (oder nur `--secrets`). Einträge liegen unter Dienst `tinyops`, Namen wie `gitlab_token`.
   Ansehen und löschen kannst du sie in «Passwörter und Schlüssel» (Seahorse) oder mit `secret-tool search service tinyops`.
4. **Gesperrter Schlüsselbund:** Beim Start entsperrt der Desktop ihn meist automatisch beim Login. Sonst erscheint beim ersten Zugriff ein Dialog.

**Ohne Desktop-Sitzung (SSH, headless VM)** gibt es keinen Secret-Service, `keyring` meldet `fail.Keyring`. Optionen:
- Secrets stattdessen aus einem Passwortmanager holen: `"secrets": {"gitlab_token": {"cmd": ["pass", "show", "tinyops/gitlab"]}}`
  (oder `op read`, `gpg -d`, `secret-tool lookup ...`). Das ist für VMs meist die beste Lösung.
- Oder die 600er-Datei akzeptieren (`setup.py` fragt vorher nach).
- Wer unbedingt einen Schlüsselbund auf der VM will: `gnome-keyring` plus `dbus-run-session -- sh -c 'echo -n "$PW" | gnome-keyring-daemon --unlock; ./run.sh'`.
  Das ist fummelig und ich habe es nicht getestet.

Häufige Fehler: `keyring` im System-Python installiert, aber `.venv` aktiv (oder umgekehrt) → `--check` mit demselben Python
starten, das `run.sh` benutzt. Unter `sudo` oder einem anderen Benutzer sieht man den Schlüsselbund des Desktop-Benutzers nicht.

Eigene Firmen-CA: `"ca_bundle": "/pfad/zur/firmen-ca.pem"`. Das Prüfen der Zertifikate lässt sich nicht abschalten.

## 4. Jira: Verknüpfung, Story-Limit, Ticket anlegen

- **Verknüpfung:** Das Panel liest den Ticket-Key aus Branchname und MR-Titel (`feature/DLP-123-retry`).
  Trage `jira.project_keys` ein (zum Beispiel `["DLP"]`). Dann zählen Keys auch kleingeschrieben (`dlp-123`) und
  nur für deine Projekte. Ohne Eintrag zählen nur GROSS geschriebene Keys.
- **Story-Limit:** `jira.story_limit` (Standard 2) gegen die Treffer von `jira.jql_in_progress`. Mit
  `wip_issue_types: ["Story"]` zählen nur Stories (Bugs nicht). Über dem Limit: rotes Banner, rote Kopfzeilen-Pille,
  und «Agent starten» geht nur noch für Tickets, die schon in Arbeit sind (auch serverseitig geprüft).
  **Das Panel kann dich nicht hindern, einen Branch anzulegen.** Eine harte Sperre müsste in Jira sitzen.
- **Ohne Ticket:** MRs und Branches ohne Key bekommen «Ticket anlegen» (öffnet die Jira-Maske, das Panel schreibt
  nicht selbst) und «In Ideenbox parken». Für einen vorausgefüllten Titel setze `create_pid` (Projekt-ID) und
  `create_issuetype` (Vorgangstyp-ID), sonst öffnet sich die leere Maske.
- **Wichtig, ungeprüft gegen dein Jira:** Der Standard `statusCategory = "In Progress"` kann in einer deutschen Instanz
  anders heißen. Teste die JQL im Jira-Suchfeld und passe `jql_in_progress` an, falls nötig.

## 5. Offene Branches von dir und deinem Agenten (`branch_filter`)

Neben den MRs zeigt das Panel Branches ohne MR, die mindestens einen Commit von dir oder deinem Agenten tragen.
Pro Branch werden alle Commits verglichen, die er dem Default-Branch voraus hat (nicht nur der letzte). Geschützte,
gemergte und Default-Branches fehlen. Konfigurierbar in `branch_filter`:

| Schlüssel | Bedeutung |
| --- | --- |
| `emails`, `names` | Deine Identitäten (zusätzlich zu `my_emails` und deinem GitLab-Konto). Ohne Beachtung der Groß-/Kleinschreibung |
| `agent_emails`, `agent_names` | Läuft dein Agent unter eigenem Konto, trage es hier ein. Solche Branches zählen immer und tragen das Badge «Agent» |
| `agent_message_patterns` | Textstellen in der Commit-Nachricht (Standard `Co-Authored-By: Claude`, `Claude-Session`). Sie **beschriften** nur: Ein Branch mit solchem Text, aber ohne Commit von dir oder dem Agenten-Konto, taucht nicht auf (sonst erschienen fremde Branches) |
| `max_branches`, `max_age_days` | Höchstens so viele Branches pro Projekt (neueste zuerst, Standard 40) und nicht älter als 90 Tage (0 = kein Limit) |

Kosten: ein API-Aufruf pro Branch, pro Commit-Stand nur einmal (Zwischenspeicher im Speicher). Der erste Start mit
vielen Branches ist langsamer. Schlägt ein Vergleich fehl, zählt ersatzweise nur der letzte Commit.
Branches, die ein Agent unter **deinem** Git-Namen committet, erkennst du nur am Muster in der Nachricht. Prüfe in einem
echten Agent-Commit, was dort steht, und passe `agent_message_patterns` an.

## 6. Mir zugeteilte MRs und Helpdesk

- **Mir zugeteilt:** MRs mit dir als Assignee, die nicht von dir sind und nicht in «Wartet auf mich» stehen.
- **Helpdesk (standardmäßig aus):** Erscheint nur, wenn `jira.helpdesk.jql` gesetzt ist, und nur für dieselbe Jira-Instanz. Eine Zahl in der Kopfzeile aus `jira.helpdesk.jql`: offene Anfragen, älteste in Stunden, wie viele
  älter als `sla_hours` sind. Das ist das Alter, **kein echter SLA** aus Jira Service Management. Kein Popup, keine
  Liste, die Zahl wird höchstens alle `cache_minutes` (30) aktualisiert. Ein Klick öffnet die Liste in Jira.
  Läuft euer Helpdesk nicht in Jira, bleibt das Feld leer.

## 7. Zugriff

| Wo es läuft | Wie du draufkommst |
| --- | --- |
| Auf deinem Laptop (empfohlen) | `http://localhost:8765` |
| Auf der Office-VM | Vom Laptop: `ssh -L 8765:localhost:8765 user@vm`, dann `http://localhost:8765`. Nichts im Netz offen |
| Im Büronetz direkt | `bind` auf die VM-IP, `allowed_hosts` auf den Hostnamen, `--set-secret access_token`. Ohne Token startet das Panel nicht. Einmal `http://vm:8765/?token=...` öffnen |

## 8. Testumgebung pro MR

Der Button führt `deploy_command` aus der Config aus (Standard: `helm upgrade --install`). Das Image-Tag ist
standardmäßig `{sha8}`: Deine CI muss das Image des MR also mit den ersten 8 Stellen des Commit-Hashes taggen
und in Harbor ablegen. Passt das nicht, ändere `tag_template` pro Projekt (`{sha8}`, `{iid}`, `{branch_slug}`).

Schutzregeln im Code: `kube_context` muss gesetzt sein; Namespaces heißen `test-<projekt>-<mr>` und nur solche
werden abgebaut; Befehle kommen nur aus der Config, ohne Shell und ohne Eingaben aus dem Browser; Zeitlimit pro Job.

## 9. Prompts, Agenten, Ideenbox

`prompts/*.md` sind Vorlagen. Platzhalter: `{project} {branch} {mr_iid} {mr_url} {title} {sha8} {namespace}
{context} {ticket}`. «Prompt kopieren» legt den gefüllten Text in die Zwischenablage, den fügst du in Claude Code,
Mistral Vibe oder Goose ein (für DLP-Projekte der richtige Weg: Du entscheidest pro Aufruf, wer den Text sieht).
Optional startet `agent_command` den Prompt direkt, Flags prüfst du in der Hilfe des Tools.

Die Ideenbox fasst höchstens 25 Ideen, unbehandelte verfallen nach 30 Tagen. Sie startet nie etwas.

## 10. Dateien

    server.py            Server, GitLab- und Jira-Client, Jobs, Ideen (SQLite in data/)
    setup.py             Einrichtung: fragt alles ab, schreibt config.json, speichert Secrets
    secretstore.py       Secret-Speicher
    static/index.html    Oberfläche
    prompts/*.md         Prompt-Vorlagen
    tests/               Unit-Tests und Fake-GitLab/Jira: python3 -m unittest discover -s tests -v

## 11. Ehrliche Grenzen

- Getestet: 26 Unit-Tests, Demo-Modus, GitLab und Jira gegen Fake-Server (Bearer, Basic, falscher Token),
  Zugriffsschutz, Secret-Rechte, Schwärzung, Oberfläche im Headless-Browser.
  **Nicht getestet:** dein echtes Jira 9.4 und GitLab 19.2, `helm`/`kubectl` gegen dein Cluster, der Schlüsselbund,
  Windows, Python unter 3.13.
- Jira-Details, die in deiner Instanz abweichen können: JQL für «In Arbeit», Ticket-Erstellen-URL, Suchlimit
  (100 Treffer, bei Überschreitung zeigt die Helpdesk-Pille ein «+»).
- Pipeline-Status gibt es nicht für Branches ohne MR. Mehr als 100 Branches pro Projekt werden nicht gelesen. Der Branch-Filter ist gegen den Fake-GitLab getestet, nicht gegen dein 19.2.
- Stop-Regel für dich: Wenn du das Panel nach vier Wochen nicht täglich öffnest, lösche es.
