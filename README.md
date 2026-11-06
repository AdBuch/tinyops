# tinyops: Arbeitspanel

Version 0.11.0 (Semantic Versioning, siehe [CHANGELOG.md](CHANGELOG.md): neue Funktion = minor, Korrektur = patch).

Ein kleines lokales Panel. Nur Python (getestet mit 3.13, sollte ab 3.9 laufen), keine Pflicht-Abhängigkeiten.

**Kann:** deine Branches und MRs mit Pipeline-Status zeigen, sie mit Jira-Tickets verknüpfen, die Stories in Arbeit
gegen ein Limit zählen, die Review-Queue und dir zugeteilte MRs zeigen, offene Branches mit deinen oder Agent-Commits zeigen, eine Ideenbox
führen, pro MR eine Testumgebung im Cluster starten und fertige Prompts füllen.

**Kann bewusst nicht:** approven, mergen, pushen. In Jira schreibt es nur mit ausdrücklichem Opt-in (`jira.allow_create`) und Bestätigung, SonarQube und GitLab liest es nur.

## 1. Ansehen (ohne GitLab und Jira)

    ./run.sh --demo        # dann http://localhost:8765 öffnen

## 2. Mit deinem GitLab und Jira

**Start:** `./run.sh` und im Browser `http://localhost:8765` öffnen. Ohne `config.json` öffnet sich die Seite
**«Einstellungen»** von selbst. Dort verbindest du GitLab und Jira, und jede Verbindung lässt sich direkt testen:

| Abschnitt | Was du eingibst | Was der Test Schritt für Schritt prüft |
| --- | --- | --- |
| GitLab | Adresse, optional Firmen-CA, Token (Feld unsichtbar) | Adresse gültig → Name auflösbar → Port erreichbar → Zertifikat (Aussteller, Restlaufzeit) → ist es GitLab → Anmeldung → Token-Scopes und Ablaufdatum → Version → jedes gewählte Projekt |
| Projekte | Suche nach Name oder Projekt-ID | Projekt existiert und ist lesbar |
| Meine Commits | Auswahl aus den echten Autoren der letzten Commits («ich», «Agent») | – |
| Jira | Adresse, Anmeldeart (Token oder Benutzer+Passwort), Projekt-Keys, Vorgangstypen, JQL | wie GitLab, dazu: Anmeldung, sichtbare Projekt-Keys, Vorgangstypen, **JQL-Testlauf mit den ersten Treffern** |

Jeder Test zeigt pro Schritt ✓, ! oder ✗ und bei Problemen, **woran es liegt und was du tun kannst**:

| Meldung | Typische Ursache und Hinweis |
| --- | --- |
| Name lässt sich nicht auflösen | Tippfehler oder VPN fehlt |
| Verbindung abgelehnt / Zeitüberschreitung | falscher Port, Firewall |
| Zertifikat nicht vertrauenswürdig | Firmen-CA: PEM-Datei bei «CA-Datei» eintragen (die Prüfung lässt sich absichtlich nicht abschalten) |
| Zertifikat gilt für anderen Namen | Adresse muss dem Namen im Zertifikat entsprechen |
| HTTP 404 auf die API | Kontextpfad fehlt (`https://host/gitlab`, `https://host/jira`) |
| Weiterleitung | Zieladresse wird genannt; oft http→https |
| HTTP 401 | Token ungültig/abgelaufen; bei Jira Hinweis auf Anmeldeart bearer ↔ basic |
| HTTP 403 | fehlender Scope `read_api`, gesperrtes Konto, Firewall |
| Jira verlangt CAPTCHA | einmal im Browser anmelden und das CAPTCHA lösen |
| JQL fehlerhaft / 0 Treffer | Jiras Fehlermeldung plus die Status deiner Instanz zur Hilfe |

Die Tests laufen mit den Werten **in den Feldern**, auch ungespeicherten. «Speichern» schreibt die `config.json` (Rechte 600,
nie mit Secrets) und legt Tokens im Schlüsselbund (sonst in der 600er-Datei) ab; danach gilt alles **sofort ohne Neustart**
und prüft sich nochmal selbst. Gespeicherte Secrets werden nie zurück an den Browser geschickt; das Feld zeigt nur
«gespeichert (← Quelle)». Bei «basic» pausiert tinyops nach einem falschen Passwort 30 Sekunden, damit Jira dein Konto
nicht sperrt.

**Vorerst ausgeblendet** (Ideenbox, Testumgebungen mit Prompts und Agenten-Knöpfen, Helpdesk) bleibt alles, was nicht GitLab
oder Jira ist. Einschalten: Einstellungen → «Weitere Funktionen». Ausgeschaltete Funktionen sind auch serverseitig gesperrt.

Tokens besorgen und Hintergründe stehen darunter; von Hand geht es auch:
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

## 2b. Logs

Das Panel schreibt ein Logbuch nach `~/.config/tinyops/logs/tinyops.log` (Rechte 600, 2 MB pro Datei, 5 Dateien
Rotation, ausserhalb des Projektordners). Secrets werden in jeder Zeile geschwärzt, auch in Tracebacks.

| Wie | Was |
| --- | --- |
| `./run.sh` | Stufe `info`: Start, Auffrischen mit Dauer und Zahlen pro Projekt, Jira-Verknüpfung, Jobs, Warnungen, abgelehnte Zugriffe |
| `./run.sh -v` | Stufe `debug`: zusätzlich jeder API-Aufruf mit Dauer und **die Begründung für jede Branch-Entscheidung** («Branch X ausgeblendet: keiner der 3 Commits von dir») sowie die Ausgabe jedes Jobs |
| `python3 server.py --show-log 100` | letzte 100 Zeilen |
| Knopf «Log» im Panel | letzte 400 Zeilen, filterbar nach Stufe |
| `log_level`, `log_dir`, `log_max_mb`, `log_backups` | in der `config.json` |

Jeder Verbindungstest der Einstellungsseite steht mit Ergebnis im Log. Zugriffs-Log: GET-Abfragen im Takt nur bei `debug`,
Aktionen (POST) und alle Fehler (ab HTTP 400) immer. Die Adresse mit `?token=` taucht nie auf, nur der Pfad.

## 2c. Mit Git installieren und aktualisieren

    git clone <adresse-deines-gitlab-repos> tinyops && cd tinyops
    # beim ersten Start im Browser unter «Einstellungen» einrichten
    ./run.sh
    # später: Neues holen, Einstellungen bleiben
    git pull && ./run.sh

`config.json`, `config.json.bak`, `data/` (Ideenbox) und Logs sind in `.gitignore` und werden **nie** eingecheckt oder
überschrieben. Secrets liegen sowieso ausserhalb des Ordners. Neues Repo bei dir anlegen: `git remote add origin <url>`
und `git push -u origin main`.

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
   - venv: `python3 -m venv .venv && .venv/bin/pip install keyring`. `run.sh` nimmt `.venv` automatisch.
     (Ein venv ist die sauberere Wahl, wenn `pip` sonst `externally-managed-environment` meldet.)
2. **Prüfen:** Unter «Einstellungen → Wo liegt was» steht, ob der Schlüsselbund gefunden wurde, sonst «Datei … (Klartext)».
   Nach dem ersten Speichern zeigt «Gespeichert (← Schlüsselbund)», dass es geklappt hat.
3. **Speichern:** über die Einstellungsseite (oder `python3 server.py --set-secret gitlab_token`). Einträge liegen unter Dienst `tinyops`, Namen wie `gitlab_token`.
   Ansehen und löschen kannst du sie in «Passwörter und Schlüssel» (Seahorse) oder mit `secret-tool search service tinyops`.
4. **Gesperrter Schlüsselbund:** Beim Start entsperrt der Desktop ihn meist automatisch beim Login. Sonst erscheint beim ersten Zugriff ein Dialog.

**Ohne Desktop-Sitzung (SSH, headless VM)** gibt es keinen Secret-Service, `keyring` meldet `fail.Keyring`. Optionen:
- Secrets stattdessen aus einem Passwortmanager holen: `"secrets": {"gitlab_token": {"cmd": ["pass", "show", "tinyops/gitlab"]}}`
  (oder `op read`, `gpg -d`, `secret-tool lookup ...`). Das ist für VMs meist die beste Lösung.
- Oder die 600er-Datei akzeptieren (die Einstellungsseite weist darauf hin).
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

## 4b. Filter (neu in 1.5)

- **Nur aktive Sprints** (`jira.only_active_sprints`, Standard an): Die JQL für «in Arbeit» wird um `sprint in openSprints()` ergänzt.
  Verknüpfte Tickets, die in keinem aktiven Sprint liegen, bleiben sichtbar, tragen aber den Hinweis «außerhalb Sprint».
  Braucht Jira Software (Sprint-Feld). Der Jira-Test in den Einstellungen warnt, wenn das nicht klappt; dann Option ausschalten.
- **Branches ignorieren** (`branch_filter.ignore_branches`, Standard `["release/*"]`): Muster mit `*`, Groß/Klein zählt.
  Gilt für Branches ohne MR und für deine eigenen MRs. Review-Anfragen und dir zugeteilte MRs bleiben immer sichtbar.
  Im Debug-Log (`-v`) steht, welcher Branch warum ignoriert wurde.
- **Filterleiste** auf der Übersicht: Suche (Taste `/`), Projekt, nur Agent, ohne Ticket, liegt schon lange. Die Auswahl merkt sich der Browser.

## 4c. Layout (neu in 1.6)

- **Großer Bildschirm (z. B. 2560 × 1440):** vier Kacheln nebeneinander (Stories in Arbeit, Braucht dich, Meine MRs, Offene Branches), rechts die Ideenbox. Jede Kachel scrollt für sich.
- **Kachel anklicken:** sie nimmt die halbe Breite ein. Zwei Kacheln gleichzeitig (z. B. Jira-Stories links, Branches rechts); die übrigen schrumpfen zu einer Leiste. Nochmal klicken schließt. Der Browser merkt sich die Wahl.
- **Handy:** eine Spalte und unten ein Menü wie in einer App: Übersicht, Ideen, Einstellungen.
- Die Ideenbox ist jetzt standardmäßig an (`features.ideas`), Testumgebungen bleiben aus.

## 4d. Wo die Config liegt (neu in 1.7)

Config, Ideenbox und Log liegen jetzt **beim Nutzer**, nicht mehr im Projektordner: `~/.config/tinyops/` (`config.json`, `data/`, `logs/`, dazu die Secrets).
Ein neues Auspacken des Bundles, ein frischer Klon oder `git pull` verliert also nichts. Eine alte `config.json` (und `data/tinyops.db`) aus dem
Projektordner wird beim ersten Start automatisch dorthin kopiert; bestehende Dateien werden nie überschrieben. Anderer Ort: `TINYOPS_HOME=/pfad` oder `--config /pfad/config.json`.
Die Ansicht «Kacheln» oder «Liste» (wie in 1.5) schaltest du über den Umschalter neben den Filtern; der Browser merkt sie sich.

## 4e. Jira oder GitLab? Ideen-Drop (neu in 1.8)

- **Farben:** Jira ist violett (Raute), GitLab orange (Punkt). Kachel «Stories in Arbeit» trägt das Jira-Zeichen, die anderen das GitLab-Zeichen.
  In den Zeilen steht «MR !52» oder «Branch» in Orange (GitLab) und das Ticket als «Jira DLP-140 · In Review» in Violett.
- **Ideen-Drop:** Taste `i` oder Knopf «+ Idee» oben öffnet ein kleines Fenster, Enter speichert. Die Ideenbox rechts (am Handy: Tab «Ideen») zeigt alles.

## 4f. Tickets direkt anlegen und KI-Entwurf (neu in 1.9)

**Ticket anlegen, ohne das Panel zu verlassen.** Bei Einträgen ohne Ticket öffnet «Ticket anlegen» einen Dialog: Jira-Projekt, Vorgangstyp, Titel und Beschreibung
sind schon aus Branch, MR-Titel, MR-Beschreibung und Commit-Titeln vorbereitet (Jira-Wiki-Format mit Ausgangslage, Ziel, Akzeptanzkriterien).
- **Schreibzugriff ist standardmäßig aus.** Einschalten: Einstellungen → Jira → «Tickets aus dem Panel anlegen» (`jira.allow_create`). Danach legt das Panel
  ein Ticket nur an, wenn du «In Jira anlegen» drückst und die Rückfrage bestätigst. Das Konto braucht die Jira-Berechtigung «Vorgänge erstellen».
  Es ist der einzige schreibende Aufruf; er steht im Log als «SCHREIBEN POST /issue». Approve, Merge und Push bleiben ausgeschlossen.
- Ist es aus, bleibt der Dialog nützlich: «Text kopieren» oder «In Jira öffnen».
- Erlaubt sind nur die Projekt-Keys aus den Einstellungen und Vorgangstypen, die das Jira-Projekt wirklich hat.

**KI-Entwurf mit lokalem Modell** (Einstellungen → KI-Entwurf). Zwei Dialekte: **Ollama** (`ollama serve`, Adresse `http://127.0.0.1:11434`) und **OpenAI-kompatibel**
(llama.cpp `llama-server`, LM Studio, vLLM; Adresse z. B. `http://127.0.0.1:8080`). Der Verbindungstest prüft Adresse, Server, Modell und einen Testentwurf.
- **DLP:** Es werden nur Adressen im eigenen Netz angenommen (localhost, private Adressen, Namen im Büro-Netz). Eine externe Adresse braucht ein ausdrückliches Häkchen.
  Gesendet werden Titel, Branch, MR-Beschreibung und Commit-Titel, nie Diffs oder Code. Antwortet das Modell nicht brauchbar, bleibt die Vorlage.
- **Langsame oder grosse Modelle:** Die Antwort wird gestreamt; der Timeout (Standard 120 s, einstellbar) gilt nur für Pausen ohne Lebenszeichen, nicht für die ganze Antwort.
  Das erste Zeichen kommt bei grossen Modellen erst nach dem Laden. Der Testentwurf ist auf 400 Token begrenzt und zeigt die Dauer.
- **Log:** Jede Anfrage, Dauer, «erstes Zeichen nach …», Fehler und alle Testschritte stehen im Log (Knopf «Log» oben, Logger `tinyops.llm`). Mit `-v` zusätzlich Prompt und Antwort.
- **Weitere APIs:** In `llm.py` eine Klasse mit `models()` und `chat()` schreiben und mit `register()` eintragen; sie erscheint dann in der Auswahl.
  Ein optionaler Zugangsschlüssel liegt wie alle Secrets im Schlüsselbund (`llm_key`).

## 4g. Verknüpfen per Drag and drop und Pools (neu in 2.0; Pools heissen ab 2.5 «Kategorien» und leben im Board, siehe 4k)

- **Ticket und Branch passen nicht zusammen** (zum Beispiel Sammel-Tickets für Bugs): Ziehe die Zeile eines Branches oder MRs auf eine Story in der Kachel
  «Stories in Arbeit». Oder drücke bei der Zeile «Zuordnen» bzw. «Ticket ändern» und gib einen Key ein; das geht auch am Handy.
  Die Zuordnung überstimmt die Erkennung aus dem Branch-Namen, ist mit «manuell» gekennzeichnet und lässt sich mit dem × wieder lösen; dann gilt wieder der Name.
- **Pools** sind benannte Arbeitsbereiche ausserhalb von Sprint und Story-Limit, zum Beispiel «Agenten-VM» oder ein Produkt. Du legst sie in der Kachel «Pools» an
  und ziehst Zeilen (Branch/MR), Stories oder Ticket-Chips hinein. Ein Ticket, das nicht in den Listen steht, fügst du über den Key hinzu (Jira liefert Titel und Status).
- **Nur lokal:** Alles liegt in `~/.config/tinyops/data/tinyops.db`. In Jira und GitLab wird nichts geändert.

## 4h. Sync-Status und Teilergebnisse (neu in 2.2)

Das Panel wartet nicht mehr, bis alles geladen ist. Der Server synchronisiert im Hintergrund, die Seite fragt alle 0,9 s nach, solange das läuft.

* Eine Leiste über den Kacheln zeigt, was gerade abgeglichen wird: GitLab-Anmeldung, jedes Projekt, Review-Queue, zugeteilte MRs, Jira-Stories und das Verknüpfen. Pro Schritt siehst du Ergebnis und Dauer. Danach bleibt eine einzeilige Zusammenfassung («Synchronisiert um 17:06:21 in 6 s»), die sich aufklappen lässt.
* Schon geladene Projekte erscheinen sofort. Leere Kacheln zeigen «lädt …», bis der Abruf durch ist. Jira-Stories kommen früh (parallel zu GitLab), ihre Zuordnung zu Branches folgt am Ende.
* Beim Auffrischen bleiben die alten Daten stehen, bis die neuen komplett sind. «Neu laden» startet den Abgleich und blockiert nicht.
* GitLab-Projekte werden mit bis zu 3 Anfragen parallel geladen (nur lesend). Ein Fehler in einem Projekt stoppt die anderen nicht.
* Für Skripte: `POST /api/refresh` startet den Abgleich, `GET /api/overview` liefert sofort und enthält `sync` und `loading`.
* Zum Ansehen mit künstlicher Verzögerung: `TINYOPS_DEMO_DELAY=1.2 ./run.sh --demo`.

## 4i. KI-Konten: Rest im Zeitfenster (neu in 2.3, ab 2.4 standardmässig aus)

Einschalten unter Einstellungen → Weitere Funktionen → «KI-Konten» (`features.ai` in der config.json). Ausgeschaltet bleibt die Kachel weg und `/api/ai/*` antwortet mit 404; gespeicherte Konten bleiben erhalten.

Kachel «KI-Konten». Claude.ai, ChatGPT und Mistral Vibe (Abos) bieten **keine offizielle Abfrage** für das Restlimit. Das Panel liest deshalb nichts von dort (und braucht dafür keine Zugangsdaten), sondern rechnet mit dem, was du einträgst:

* Pro Konto: Name, Art, Fenster in Stunden (Standard 5; für ein Wochenlimit 168 als zweites Konto), Budget (Standard 100 %) und Einheit.
* **Stand setzen:** «Verbraucht» und «Reset in» (Minuten) so eintragen, wie es die Anzeige des Anbieters zeigt. Danach läuft das Fenster im Panel weiter: Restwert, Balken (grün, gelb unter 20 %, rot bei leer) und Zeit bis zum Reset. Ist das Fenster abgelaufen, steht das Konto auf «Fenster frei» (0 verbraucht). Mit −10 / +10 passt du schnell an.
* **Lokales Modell:** Art «Lokal» zählt die Anfragen des Panels (KI-Entwurf) automatisch, ohne Limit.
* Gespeichert wird nur lokal in `tinyops.db`, nichts geht an einen Anbieter. API: `POST /api/ai/save|set|delete`, `ai` im `/api/overview`.
* Grenze: Der Stand ist nur so aktuell wie dein letzter Eintrag. Verbrauch ausserhalb des Panels (Web, Handy) siehst du erst, wenn du ihn nachträgst.

## 4j. Board: Workflow und eine Karte pro Aufgabe (neu in 2.4)

Zweite Seite «Board» mit den Spalten **Ideenpool → Geplant → Umsetzung → Review → Test → Getestet → Fertig**.

* **Eine Karte pro Aufgabe.** Alles mit demselben Ticket-Key wird zu einer Karte zusammengeführt. Ein Ticket kann beliebig viele MRs und Branches haben, sie erscheinen als Chips auf der Karte. MRs und Branches ohne Ticket (nur deine) haben eine eigene Karte «ohne Ticket» und lassen sich ausblenden.
* **Quellen:** Jira-Tickets in Arbeit, Pool-Tickets, Tickets, die du aufs Board holst (Jira-Key ins Feld oben eintragen), **lokale Aufgaben** (Text eintragen, sie heissen `LOC-1`, `LOC-2` …) und offene Ideen aus der Ideenbox (Spalte Ideenpool, Knopf «Planen» macht daraus eine Aufgabe in Geplant).
* **Verschieben:** Karte in eine andere Spalte ziehen oder ◀ ▶ benutzen. Die Stufe gilt nur im Panel, in Jira wird nichts geändert. Ohne eigene Stufe gilt: in Jira in Arbeit → Umsetzung, mit offenem MR (kein Draft) → Review, sonst Geplant. ✕ löscht lokale Aufgaben oder setzt die eigene Stufe zurück.
* **Verbinden:** einen MR-/Branch-Chip auf eine andere Karte ziehen, dann gehört er zu deren Ticket (wie das Verknüpfen aus 4g, auch mit `LOC-…`-Aufgaben).
* **Jira-Panel:** Umsetzung, Review und Test zählen als «in Arbeit». Solche Aufgaben erscheinen zusätzlich zu den Jira-Stories im Panel «Stories in Arbeit», zählen für das Limit und tragen dort ihre Stufe. Jira-Stories in Arbeit bleiben immer sichtbar, auch wenn du sie im Board woandershin schiebst (sonst würde das Limit etwas verstecken).
* «Fertig» zeigt die 12 neuesten Karten. API: `POST /api/board/stage|add|remove|plan_idea`, `board` im `/api/overview`.

## 4k. Kategorien statt Pools-Kachel, Ideen mit Kategorie (neu in 2.5)

* Die Kachel «Pools» ist weg. Pools sind jetzt **Kategorien im Board**: Projekte oder Aufgabengruppen ohne Jira (z. B. «Agenten-VM», «Produkt X»). Die Leiste über den Spalten filtert nach Kategorie («Alle» zeigt alles), legt neue an, benennt um und löscht (Aufgaben, Tickets und Branches bleiben bestehen). Bestehende Pools und ihre Zuordnungen bleiben erhalten.
* Karte auf eine Kategorie ziehen ordnet sie zu (Jira-Tickets, lokale Aufgaben, Branches). Eine Karte kann in mehreren Kategorien stehen; das × am Kategorie-Chip nimmt sie wieder heraus.
* **Regel:** Ideen und lokale Aufgaben ohne Kategorie bleiben im Ideenpool. Ab «Geplant» (und beim Übernehmen einer Idee mit «Planen») braucht eine Aufgabe ohne Jira eine Kategorie. Jira-Tickets brauchen keine. Die letzte Kategorie einer geplanten Aufgabe lässt sich nicht entfernen, solange sie nicht zurück im Ideenpool ist.
* Ideen ohne Kategorie sieht man nur unter «Alle», nicht innerhalb einer Kategorie.
* API: `POST /api/board/assign|unassign` (`key` oder `ref`, `pool_id`), `add` und `plan_idea` nehmen `pool_id`.
* Layout: höchstens 4 Kacheln nebeneinander; in schmalen Kacheln rutschen die Knöpfe unter den Titel, statt ihn zu überdecken.

## 4l. SonarQube: Quality Gate je MR und Branch (neu in 0.7.0)

Aus per Voreinstellung. Einschalten unter Einstellungen → Sonar (Adresse, Token) und je GitLab-Projekt den **Sonar-Projektschlüssel** eintragen.
Der Token kommt wie alle Secrets in den Schlüsselbund oder in `TINYOPS_SONAR_TOKEN`, nie in die `config.json`.

* tinyops fragt ausschliesslich per GET `api/qualitygates/project_status` (MR: `pullRequest=<iid>`, Branch: `branch=<name>`).
  Der Chip zeigt «Gate grün», «Gate rot» (mit den verletzten Bedingungen im Tooltip und Link zu Sonar), «Warnung» oder «keine Analyse».
* Ein rotes Gate setzt den MR unter «Braucht dich». Im Board und in den Stories erscheint ein Punkt am MR-Chip.
* Je Abgleich höchstens `sonar.max_items` Abfragen (Standard 40), Ergebnisse `sonar.cache_seconds` (Standard 300) im Speicher.
  Ein falscher Token bricht die Sonar-Abfragen mit einer klaren Meldung ab, ein einzelner Fehler nur diesen Eintrag.
* **Edition:** Gates je Merge Request liefert SonarQube erst ab Developer Edition. In der Community Edition steht für MRs «keine Analyse».
* Der Test in den Einstellungen und `--preflight` prüfen Erreichbarkeit, Token und, ob die eingetragenen Schlüssel existieren.

## 4m. KI-Kontingent: Claude und Codex (neu in 0.8.0)

Aus per Voreinstellung. Einstellungen → KI-Kontingent: «Claude lesen» und/oder «Codex lesen» ankreuzen, speichern, «Jetzt abfragen».

* Claude: `GET https://api.anthropic.com/api/oauth/usage`, Token aus `~/.claude/.credentials.json`. Codex: `GET https://chatgpt.com/backend-api/wham/usage`,
  Token aus `~/.codex/auth.json` (ChatGPT-Anmeldung, ein reiner API-Schlüssel reicht nicht). Pfade lassen sich ändern.
* **Inoffiziell:** Beide Schnittstellen sind nicht dokumentiert und können sich ohne Ankündigung ändern oder gesperrt werden. Dann steht in der Kachel «nicht abrufbar» mit Grund.
* Das Token wird nur gelesen (nie erneuert, kopiert oder geloggt) und nur an den genannten Host geschickt. Ist es abgelaufen: einmal `claude` bzw. `codex` im Terminal starten.
* Im Container müssen die Dateien eingehängt sein (z. B. als Secret-Volume, schreibgeschützt). Das Manifest tut das bewusst nicht von selbst.
* Mistral Vibe bietet keine Abfrage; dafür bleiben die von Hand gepflegten KI-Konten (Einstellungen → Weiteres).

## 4n. Sonar-Links und Findings-Report (neu in 0.9.0)

* Hinter jedem MR und Branch mit Sonar-Analyse (Zeilen, Board, Stories): **Sonar** (Dashboard), **Findings** (offene Findings in Sonar, nur bei Gate grün/Warnung/rot) und **Report kopieren**.
* **Report kopieren** liest auf Knopfdruck per GET Quality Gate, offene Findings (`api/issues/search`) und Security Hotspots (`api/hotspots/search`)
  und legt Markdown in die Zwischenablage: nicht erfüllte Bedingungen, Zähler nach Schwere und Art, Findings je Datei mit Zeile, Regel und Meldung.
  Höchstens `sonar.report_max` Findings (Standard 200, nach Schwere sortiert), der Rest steht in Sonar.
* **DLP:** Der Report enthält Dateipfade, Zeilennummern, Regelnamen und Sonar-Meldungen (die manchmal Bezeichner aus dem Code nennen), aber keinen Quelltext.
  Er geht nirgends hin, ausser in deine Zwischenablage. Was du damit machst (z. B. in einen Cloud-Chat einfügen), entscheidest du; bei Kundenprojekten vorher lesen.
* Hotspots brauchen die Berechtigung «Administer Security Hotspots» bzw. «Browse»; sonst steht im Report «Nicht lesbar».

> Ab 0.10.0 steht der Stand der Abos als eingeklappte Box «KI-Kontingent» unter der Ideenbox (Klick öffnet, ein Reload schliesst sie wieder).
> «MR erstellen» an Branches ohne MR öffnet in GitLab das Formular für einen neuen Merge Request. Abgleich höchstens alle `cache_seconds` (Standard 300).

> Ab 0.11.0: **Trend** der Findings neben dem Gate (Sonar-Verlauf, sonst lokal beobachtet), Auswertung nach Auswirkung (SonarQube 2026.1), Schritt «Pull-Request-Analyse» im Verbindungstest.

## 4o. Mistral im KI-Kontingent per Lesezeichen (neu in 0.9.0)

Mistral hat keine Schnittstelle fürs Restkontingent, die Budgets stehen nur auf `admin.mistral.ai/subscription` und nur mit der Browser-Sitzung. Die bekommt tinyops nicht zu sehen.

1. Einstellungen → KI-Kontingent → «Mistral anzeigen» ankreuzen und speichern.
2. Den Link «tinyops: Mistral lesen» in die Lesezeichenleiste ziehen.
3. Eingeloggt auf `admin.mistral.ai` das Lesezeichen anklicken. Es holt dort die Seite selbst, liest `vibe_budget` und `api_budget` (Prozent, Budget, Währung, Reset)
   und öffnet tinyops in einem neuen Tab nur mit diesen Zahlen (`#mistral=...`). tinyops prüft sie, speichert sie in `usage_push.json` im Datenordner (nur Zahlen) und zeigt sie in der Kachel.

`usage_percentage` ist ein Prozentwert (0,159 bei 30 $ = 0,05 $ verbraucht). Nach 36 Stunden zeigt die Kachel «veraltet»; nach dem Monatswechsel «abgelaufener Monat».
Voraussetzung: tinyops muss in diesem Browser unter der gewohnten Adresse erreichbar (und angemeldet) sein. Ändert Mistral die Seite, meldet das Lesezeichen «Keine Budgetdaten gefunden».

## 4p. Coding-Agenten an Tickets (neu in 0.12.0)

Agenten sind CLI-Programme (Claude Code, Codex, Mistral Vibe oder dein eigener Befehl), die auf diesem Rechner oder per SSH auf einem anderen laufen. Du weist sie auf der Karte einem Ticket zu; der Status steht danach direkt auf der Karte.

1. Einstellungen → **Coding-Agenten** → «Verbindung hinzufügen» (Name, Rechner, Benutzer, Port, optional Schlüsseldatei). Auf dem Zielhost müssen `tmux` und der Agent installiert und angemeldet sein, und der SSH-Schlüssel muss ohne Passwortabfrage funktionieren (ssh-agent). Der Host-Schlüssel muss bekannt sein: einmal im Terminal `ssh <rechner>` ausführen.
2. «Agent hinzufügen»: Name, Art, Verbindung (oder lokal), **Arbeitsordner** (auf dem Zielhost absolut, z. B. `/home/adrian/work`), optional zusätzliche Argumente (`--model opus`). «Testen» zeigt, woran es hängt.
3. Unter GitLab → Projekte: optional **Agent-Ordner** (Standard: Projektname; das Repository muss unter dem Arbeitsordner liegen) und **Cloud-Agent erlaubt**.
4. Auf der Karte «Agent zuweisen …», Prompt prüfen, «Zuweisen & starten». Der Chip zeigt den Stand; ein Klick öffnet das Log, «Stoppen» beendet die Sitzung.

Stände: *zugewiesen* (noch nicht gestartet), *läuft*, *fertig* (Exit 0), *fehlgeschlagen* (Exit ≠ 0 oder Start gescheitert), *abgebrochen* (von dir), *verloren* (Sitzung ohne Exit-Datei weg, z. B. Neustart des Zielhosts). Ist der Zielhost kurz nicht erreichbar, bleibt der Lauf auf *läuft* mit Hinweis «Status unbekannt».

**DLP:** Claude, Codex und Vibe senden Prompt und Code an den Anbieter. Sie starten deshalb nur, wenn beim Projekt «Cloud-Agent erlaubt» angekreuzt ist (Standard: aus). Ein eigener Befehl mit lokalem Modell: in der `config.json` beim Agenten `"cloud": false` und `"command": "mein-agent {prompt_file}"` setzen. Den Befehl kann die Oberfläche nicht ändern.
Der Prompt enthält nur Key, Titel, Projekt, Branch und Link plus die Regeln aus `prompts/agent-task.md` (kein Merge, kein Push auf geschützte Branches, kein Force-Push). **Das ist eine Bitte an den Agenten, keine technische Sperre:** Was der Agent mit seinen eigenen Zugangsdaten auf dem Zielhost darf, bestimmen dort die Rechte. Gib ihm dort nur, was er braucht (zum Beispiel keinen Token mit Merge-Recht auf geschützte Branches).

## 4q. Fokus: ein Ablauf, ein nächster Schritt (neu in 0.13.0)

Die Startansicht beantwortet eine Frage: **Was mache ich jetzt?** Jedes Vorhaben (Jira-Ticket, eigene Aufgabe, Branch oder MR, auch ohne Ticket) liegt auf derselben Strecke:

| Station | erkannt an | nächster Schritt (Beispiele) |
|---|---|---|
| Planen | Ticket ohne Branch, nicht in Arbeit | Loslegen (Branch-Befehl kopieren) |
| Branch | in Arbeit, aber kein Branch mit dem Key | Branch anlegen |
| Code | Branch ohne MR | MR erstellen, oder der nächste Teilschritt |
| MR | Draft-MR | Draft fertigstellen |
| Prüfen | MR offen | Pipeline reparieren, Sonar-Findings beheben, Konflikt lösen, Kommentare klären; warten auf CI oder Review |
| Testen | Pipeline grün, Gate ok, nichts offen | Manuell testen → «Getestet» |
| Mergen | von dir als getestet markiert | MR öffnen und mergen |
| Fertig | von dir abgeschlossen, oder MR weg nach «Prüfen» → «Abschliessen» | – |

Übersteuern: im Detail-Panel auf eine Station klicken oder die Karte im Board verschieben; «Automatisch» nimmt das zurück. Blocker und Warten bleiben trotzdem sichtbar.
Branch und MR sind Tatsachen aus GitLab und lassen sich nicht von Hand setzen. tinyops merged nie selbst und ändert in Jira nichts.

Der Spielstand zählt nur echten Fortschritt (eine noch nie erreichte Station, ein abgehakter Teilschritt, ein fertiger Agentenlauf). Das Tagesziel stellst du in der `config.json` ein: `"flow": {"daily_goal": 3}`.

## 4r. GitHub, Review-Pflicht und Ticketpflicht (neu in 0.14.0)

**GitHub verbinden:** Auf GitHub unter Settings → Developer settings → Fine-grained tokens einen Token anlegen. Repository access: die gewünschten Repos,
Permissions nur **Read-only**: Metadata, Contents, Pull requests, Commit statuses, Checks. In tinyops unter Einstellungen → GitHub Token eintragen, «Verbindung testen»,
Repos suchen und hinzufügen, «GitHub einschalten», speichern. GitHub Enterprise: API-Adresse `https://host/api/v3`. Umgebungsvariable: `TINYOPS_GITHUB_TOKEN`.
Ein Abgleich braucht je eigenem PR etwa fünf Anfragen (PR, Checks, Status, Reviews, Reaktionen) und je Branch eine; das Limit liegt bei 5000 pro Stunde.

**Review vor dem Merge:** ohne Reviewer → «Reviewer zuweisen»; mit Reviewer, ohne Approve oder 👍 → «Review abwarten»; erst danach Testen und Mergen.
Verlangen die Approval-Regeln in GitLab noch Freigaben, zählt ein Daumen nicht.

**Ticketpflicht:** Jeder Branch und MR braucht ein Jira- oder tiny-Ticket. Ohne Ticket ist der Schritt «Ticket zuordnen»; ein Klick legt ein tiny-Ticket an
(Kategorie = Projekt). Wer das Ticket schon im Branchnamen hat (`feature/DLP-123-…` oder `feature/LOC-4-…`), merkt davon nichts.

**Schritt erledigt** (✓): schliesst die aktuelle Station ab, wenn tinyops sie nicht selbst erkennen kann (zum Beispiel nach dem manuellen Test).

## 4s. Abnahme am Commit, Zeitlimit, angehefteter Fokus (neu in 0.15.0)

- **Abnahme:** «Getestet» gilt für genau den Commit, auf dem du getestet hast. Ein neuer Commit im MR macht sie ungültig, das Vorhaben steht wieder auf «Erneut testen».
  Notiz und Umgebung trägst du im Detail-Panel ein; sie stehen neben der Abnahme.
- **Unbekannt:** Was tinyops nicht lesen kann (Freigaben, ein ausgefallenes Projekt), zeigt es als unbekannt oder veraltet, nie als in Ordnung.
- **Zeitlimit:** Jeder Agent hat ein Zeitlimit (Standard 60 min). Danach wird der Lauf beendet und steht auf «abgelaufen».
- **Fokus anheften:** Im Panel «Als Fokus anheften». Der Fokus bleibt, bis du ihn löst; Blocker anderswo siehst du als Hinweis.

## 4t. Datenklassen, Worktree und Export (neu in 0.16.0)

| Datenklasse | Lokale Agenten (Goose/opencode mit Ollama, eigener Befehl ohne Cloud) | Cloud-Agenten (Claude, Codex, Vibe) |
|---|---|---|
| restricted (Standard) | ja, im eigenen Worktree | **nein** (Zuweisen gesperrt) |
| internal ohne Cloud-Pfade | ja, Worktree | ja, Worktree mit dem ganzen Repo |
| internal mit Cloud-Pfaden | ja, Worktree | ja, aber nur im **Export** dieser Pfade; Ergebnis per «Übernehmen» |
| public | ja | ja, Worktree |

**Worktree:** `<Arbeitsordner>/.tinyops-wt/<Nr>`, Branch `agent/<key>-<nr>`. Das Repository muss unter dem Arbeitsordner geklont sein. Aufräumen mit «Entfernen».
**Export:** Ein Ordner mit nur den freigegebenen Dateien und eigenem Git. «Übernehmen» legt einen Commit auf `agent/<key>-<nr>` im echten Repo an, wenn nur Dateien in den Pfaden geändert wurden.
Pushen und MR erstellen bleiben bei dir. Ob ein Pfad in die Cloud darf, entscheidet dein DLP- oder Sicherheitsverantwortlicher; tinyops setzt nur durch, was eingetragen ist.
**Eigener Agent-Benutzer (empfohlen für restricted):** auf dem Zielhost einen Benutzer ohne sudo und ohne Docker-Gruppe anlegen, die Repos dort klonen, in GitLab nur Developer-Rechte und Protected Branches. Der Agenten-Test zeigt Warnungen, wenn das nicht so ist.

## 4u. Verlauf, Doppelt-Schutz und Aufbewahrung (neu in 0.17.0)

**Verlauf:** Was du in tinyops entscheidest, steht im Verlauf: Tickets anlegen, Stationen, «Schritt erledigt», Abnahmen mit Commit, Agenten, Einstellungen und Deploys. Pro Vorhaben siehst du ihn im Detail-Panel, alles zusammen unter **Log → Verlauf**.
- Die Einträge sind nur anhängend und per SHA-256 verkettet. «Kette prüfen» oder `python3 server.py --verify-audit` meldet, wenn ein Eintrag nachträglich geändert oder gelöscht wurde.
- Prompts stehen nur als Hash drin (`sha256:…`), Secrets nie.
- Wer den Verlauf als Beleg braucht, legt den Export (`--export-audit verlauf.json` oder der Knopf) regelmässig dort ab, wo tinyops nicht hinschreibt.

**Doppelt-Schutz:** Legst du in Jira dasselbe Ticket (Titel, Projekt) innerhalb von 10 Minuten nochmals an, fragt tinyops nach und verlinkt das vorhandene.

**Aufbewahrung:** `agent_log_days` (Standard 30) löscht alte Logs, Prompts und Patches der Agentenläufe auf allen Rechnern. `0` heisst «nie löschen».

## 4v. Rückfragen, Bericht und offene Review-Punkte (neu in 0.18.0)

**Rückfragen:** Im Lauf eines Agenten stehen `tinyops-ask`, `tinyops-check` und `tinyops-report` im PATH. Fragt der Agent, steht «Agent fragt» unter «Du bist dran». Du antwortest im Lauf-Dialog, und der Agent arbeitet weiter.

    tinyops-ask "Retry exponentiell oder fix?" "exponentiell" "fix"   # wartet, Antwort auf stdout; Exit 3 = weiter warten mit --wait 1
    tinyops-check mvn -q test                                        # Beleg: Befehl + Exit-Code
    tinyops-report < bericht.md                                      # Bericht für das Panel

Für eigene Befehle (LangGraph usw.) gilt dieselbe Konvention: `$TINYOPS_RUN_DIR/$TINYOPS_RUN_ID.question.json` schreiben, auf `….answer.<id>` warten.

**Offene Review-Punkte:** «Offene Punkte» bei einem MR/PR zeigt die offenen Threads mit Datei, Zeile und Commit. Auswählen, dann:
- **Als Prompt kopieren**, etwa für einen Chat oder ein IDE-Werkzeug
- **JSON** mit allen Zielangaben
- **Agent beauftragen**, der die Punkte im Worktree des MR-Branches bearbeitet

Bei restricted-Projekten erinnert der Dialog daran, dass Kommentare Code oder Kundendaten enthalten können.

## 4w. Fokus-Zeit, Zeitentwürfe, Prüfen (neu in 0.19.0)

**Fokus-Zeit:** Solange ein Vorhaben als Fokus angeheftet ist, läuft die Zeit (Pause im Fokus-Kopf). Das Panel meldet sich jede Minute, solange du es benutzt. Nach 15 Minuten ohne Aktivität endet der Abschnitt beim letzten Lebenszeichen; die Pause erscheint als **Lücke** und zählt nur, wenn du sie annimmst. Agentenlaufzeit zählt nie.

**Zeitentwürfe (Tab «Zeit»):** je Tag und Ticket, auf 15 Minuten gerundet, mit Text und Belegen (Stationen, Teilschritte, Abnahmen). Bearbeiten, zusammenlegen, verwerfen, von Hand ergänzen. Gebucht wird erst nach **Bestätigen**.

**Übergabe an deinen MCP (Projectron):**
- **Schieben:** Ist unter Einstellungen → Zeiterfassung eine Wrapper-URL eingetragen, sendet «Bestätigen» ein `POST`. Der Body hat das Schema `tinyops.time-entry/1`, dazu kommen `Idempotency-Key` und optional `Authorization: Bearer <mcp_token>`.
  - Gebucht ist der Entwurf nur bei `{"status": "booked", "reference": "..."}`.
  - `rejected` gibt «abgelehnt». Alles andere gibt «fehlgeschlagen» mit «Erneut senden».
- **Abholen:** `GET /api/time/export?state=bestätigt`, Rückmeldung mit `POST /api/time/result` `{"id", "status": "booked"|"rejected", "reference", "message"}` (Header `X-Requested-With: tinyops`).

    {"schema": "tinyops.time-entry/1", "id": "td-2026-11-05-DLP-5351", "date": "2026-11-05", "ticket": "DLP-5351",
     "project_hint": "dlp-mailhandler", "minutes": 135, "text": "Resilient Cache: Tests ergänzt",
     "evidence": ["Station Prüfen 10:42", "Abnahme 1:feature/DLP-5351 @ a1b2c3d4"], "idempotency_key": "td-2026-11-05-DLP-5351-3f9a…"}

Gleicher Inhalt ergibt denselben Schlüssel, so bucht doppeltes Senden einmal. Wird der Entwurf nach einem Fehlschlag geändert, gibt es einen neuen Schlüssel.

**Prüfen (Tab «Prüfen»):** Prüfliste aus `QA-CHECKLIST.md` zum Abhaken (ok, Fehler mit Notiz, übersprungen), «Ergebnis kopieren», Fehler als Aufgabe ins Board. **Selbsttest** (Knopf oder `python3 server.py --selftest`): Vorlagen, Hilfsskripte, Datenbank, Kette des Verlaufs und ein Durchlauf der Kernfunktionen mit Demo-Daten in einem leeren Ordner.

## 12. Kubernetes und IntelliJ (neu in 2.6)

Ausführliche Testliste: `MANUAL-TESTS.md`.

**In IntelliJ starten:** Der Ordner `.run/` bringt fertige Run-Konfigurationen mit (Python-Plugin und Interpreter nötig):
*tinyops - Demo*, *Echt (dev-Config)*, *Preflight*, *Tests*. Config, Datenbank und Logs liegen dabei in `.dev/` im Projekt
(`TINYOPS_HOME`), getrennt von deiner echten Config.

**Preflight:** `python3 server.py --preflight` prüft Config, beschreibbare Ordner, Secrets, GitLab, Jira, Sprachmodell und macht einen
echten Probe-Durchlauf (nur lesend). Exit-Code 1 bei Problemen, jeder Fehler mit Hinweis. Im Cluster: `python deploy/k8s.py preflight`.

**Nach Kubernetes:** Einmal `deploy/deploy.example.json` → `deploy/deploy.local.json` (Registry, Namespace, Kontext) und
`deploy/k8s/config.seed.json` anpassen. Dann:

    python deploy/k8s.py secret      # GitLab-/Jira-Token verdeckt abfragen, Zugriffstoken erzeugen
    python deploy/k8s.py release     # Tests, Image bauen (docker oder podman), pushen, ausrollen
    python deploy/k8s.py forward --open

Weitere Befehle: `logs`, `status`, `token`, `preflight`, `deploy`, `build`, `push`, `reseed --yes` (Config auf die Vorlage zurück),
`undeploy` (Daten bleiben), `purge --yes` (alles weg). `--dry-run` zeigt nur die Befehle.

Aufbau: ein Pod, ein Volume `/data` (Config, SQLite, Logs), Secret für die Zugangsdaten (als Umgebungsvariablen
`TINYOPS_ACCESS_TOKEN`, `TINYOPS_GITLAB_TOKEN`, `TINYOPS_JIRA_TOKEN`, `TINYOPS_LLM_KEY`), nur ein ClusterIP-Service ohne Ingress. Der Pod läuft
unprivilegiert (uid 10001, Root-Dateisystem schreibgeschützt, keine Capabilities). `/healthz` ist für die Probes ohne Token
erreichbar und verrät nur die Version. `TINYOPS_BIND`, `TINYOPS_PORT`, `TINYOPS_ALLOWED_HOSTS` überschreiben die Werte der config.json.
Ohne Zugriffstoken startet das Panel bei `bind 0.0.0.0` nicht.

Grenzen: Ein Pod, keine Hochverfügbarkeit (SQLite auf einem Volume). Optional liegen `networkpolicy.optional.yaml` (Egress nur zu GitLab,
Jira, Modell) und `ingress.optional.yaml` bei; beide sind nicht aktiv und müssen vorher angepasst werden. Das Secret liegt im Cluster
im etcd, schützt es dort wie jedes andere. Docker-Image, Manifeste und die IntelliJ-Konfigurationen sind nicht gegen einen echten
Cluster oder eine echte IDE getestet; getestet ist die Befehlsfolge mit Ersatzprogrammen, der Preflight und `/healthz`.

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
    settings.py          Einstellungsseite: Verbindungstests, Speichern
    net.py               Netzwerk: TLS, Fehlerarten, keine Weiterleitungen
    tlog.py              Logging (Rotation, Schwärzung)
    secretstore.py       Secret-Speicher
    audit.py             Verlauf: nur anhängend, Hash-Kette, Prüfen und Export
    review.py            Offene Review-Punkte: lesen, Prompt und JSON
    timesheet.py         Fokus-Zeit, Lücken, Zeitentwürfe, Vertrag mit dem MCP
    qa.py                Prüfliste und Selbsttest
    QA-CHECKLIST.md      Prüfliste zum Abhaken, je Release ergänzt
    agents.py            Coding-Agenten: lokal und per SSH/tmux, Worktree, Export
    flow.py              Ablauf, nächster Schritt, Spielstand
    static/index.html    Oberfläche
    prompts/*.md         Prompt-Vorlagen
    tests/               Unit-Tests und Fake-GitLab/Jira: python3 -m unittest discover -s tests -v

## 11. Ehrliche Grenzen

- Getestet: über 140 Tests (darunter die Verbindungstests gegen Fake-GitLab/Jira inkl. TLS, Weiterleitung, 401/403/404/503, CAPTCHA, und der ganze Weg über den Server), Demo-Modus, GitLab und Jira gegen Fake-Server (Bearer, Basic, falscher Token),
  Zugriffsschutz, Secret-Rechte, Schwärzung, Oberfläche im Headless-Browser.
  **Nicht getestet:** dein echtes Jira 9.4 und GitLab 19.2, `helm`/`kubectl` gegen dein Cluster, der Schlüsselbund,
  Windows, Python unter 3.13.
- Jira-Details, die in deiner Instanz abweichen können: JQL für «In Arbeit», Ticket-Erstellen-URL, Suchlimit
  (100 Treffer, bei Überschreitung zeigt die Helpdesk-Pille ein «+»).
- Pipeline-Status gibt es nicht für Branches ohne MR. Mehr als 100 Branches pro Projekt werden nicht gelesen. Der Branch-Filter ist gegen den Fake-GitLab getestet, nicht gegen dein 19.2.
- Stop-Regel für dich: Wenn du das Panel nach vier Wochen nicht täglich öffnest, lösche es.

### Logos
Aus Markenrechtsgründen liegen keine Logos im Projekt. Eigene Dateien (offizielle Logos aus eurem Brand-Bereich) legst du hin als
`~/.config/tinyops/logos/jira.svg` und `gitlab.svg` (oder `.png`, höchstens 256 KB); sie erscheinen dann in den Kachelköpfen. Fehlt eine Datei, bleibt es beim Text.
