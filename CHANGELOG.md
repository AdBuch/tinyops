# Changelog

Semantic Versioning: **minor** (0.x.0) für neue Funktionen, **patch** (0.x.y) für Korrekturen und Fixes.
Solange die Hauptversion 0 ist, kann sich auch bei einer minor-Version noch etwas Grundsätzliches ändern.
Die Version steht in `server.py` (`VERSION`), im Git-Tag `vX.Y.Z`, im Docker-Tag und oben rechts im Panel.
Die frühere Zählung (1.0 bis 2.6) endet hier; **0.7.0 ist der neue Anfang** und enthält alles davon.

## [0.13.0]

### Neu
- **Fokus ist die neue Startansicht.** Jedes Vorhaben fährt dieselbe Strecke **Planen → Branch → Code → MR → Prüfen → Testen → Mergen → Fertig**,
  egal ob es aus Jira, GitLab oder dem eigenen Board kommt. Tickets, Branches und MRs mit demselben Key sind ein Vorhaben; ein Branch ohne Ticket fährt trotzdem mit.
  Die Station ergibt sich aus den Daten (Branch da? MR? Draft? Pipeline? Sonar? Konflikt? Freigabe?), jede Zeile zeigt **genau einen nächsten Schritt**,
  wer dran ist (du, CI, andere, Agent) und einen Knopf, der genau das tut (MR erstellen, Pipeline öffnen, Report kopieren, Branch-Befehl kopieren, als getestet markieren ...).
- **Jetzt dran:** Oben steht gross die eine wichtigste Sache: erst Blocker, dann Reviews, auf die jemand wartet, dann was am weitesten ist («fertig machen vor anfangen»).
  «Nicht jetzt» zeigt die nächste. Darunter: Du bist dran / Andere warten auf dich / Läuft gerade / Geplant und Ideen (eingeklappt).
- **Detail-Panel auf der halben Seite** statt eines eingebetteten Browsers: Strecke zum Übersteuern (Klick auf eine Station), alle MRs und Branches mit Pipeline, Sonar,
  Mergestatus und Links, Ticket anlegen/zuordnen, Testumgebung, Agent zuweisen, Teilschritte.
- **Teilschritte:** eine Checkliste je Vorhaben. Der nächste offene Haken wird zum nächsten Schritt; jeder Haken zählt.
- **Spielstand:** Tagesziel (3 Schritte, `flow.daily_goal`), XP, Level, Serie in Tagen, Wochenbalken, letzte Erfolge, kurze Feier bei neuem Fortschritt (aus bei «weniger Bewegung»).
  Gezählt wird nur eine Station, die ein Vorhaben **noch nie** erreicht hatte, und nur mit vollständigen Daten: Zurückfallen und wieder Vorrücken bringt nichts.
- **Tastatur:** j/k auswählen, Enter Details, a nächsten Schritt ausführen, n neue Aufgabe, i Idee, Esc schliessen.
- **Board:** Spalten heissen wie die Stationen und Karten stehen dort, wo der Ablauf sie sieht (solange nicht von Hand verschoben). Karten zeigen nur noch Key, Titel,
  MR/Branch und den nächsten Schritt; Klick öffnet das Detail-Panel. Pfeile, Agent-Auswahl und Löschen sind ins Panel gewandert.
- GitLab-Mergestatus (`detailed_merge_status`: Konflikt, Rebase nötig, Freigabe fehlt, Diskussionen offen) fliesst in den nächsten Schritt ein, ohne zusätzliche Anfrage.
- Die bisherige Übersicht bleibt unter «Listen».

### Korrekturen
- Die Kopfzeile scrollte auf langen Seiten (Einstellungen) nach einer Bildschirmhöhe mit weg. Sie bleibt jetzt stehen; die Einstellungs-Navigation markiert beim Scrollen den Abschnitt.
- Projekte in den Einstellungen als ausgerichtete Tabelle (ID, Name, Sonar, Agent-Ordner, Cloud-Agent); vorher stand das Häkchen weit weg von seiner Beschriftung.
- Sonar unterscheidet jetzt 401 (Token ungültig oder abgelaufen) von 403 (Token gültig, aber ohne «Browse»; oft ein Projekt-Analyse-Token statt User-Token).
- Mobile Leiste unten: vier Einträge passen nebeneinander.

## [0.12.0]

### Neu
- **Coding-Agenten an Tickets:** Einstellungen → Coding-Agenten. Du legst **Verbindungen** an (SSH-Ziel mit Benutzer, Port, Schlüsseldatei; «lokal» gibt es immer)
  und **Agenten** (Claude Code, Codex, Mistral Vibe oder eigener Befehl) mit Verbindung und **Arbeitsordner**. Unter dem Arbeitsordner liegt je Projekt ein Repository
  (Ordnername = Projektname oder das neue Feld «Agent-Ordner» beim Projekt). «Testen» prüft Verbindung, tmux, Ordner und Programm.
- **Zuweisen auf der Karte:** Auf jeder Board-Karte und jeder Story im Jira-Panel steht «Agent zuweisen …». Der Dialog zeigt Ziel, Ordner, Anbieter und den Prompt
  (aus Key, Titel, Projekt, Branch, Link; Vorlage `prompts/agent-task.md`, vor dem Start änderbar). «Zuweisen & starten» oder «Nur zuweisen».
  Auf der Karte steht je Lauf ein Chip mit dem Status **zugewiesen, läuft, fertig, fehlgeschlagen, abgebrochen, verloren**. Klick öffnet das Log (alle 4 s aktualisiert),
  «Stoppen», «Entfernen» und einen kopierbaren `ssh -t … tmux attach`-Befehl zum Mitlesen und Eingreifen.
- **Remote per SSH und tmux:** pro Lauf eine Sitzung `tinyops-<Nr>` auf dem Zielhost; Prompt, Befehl, Log und Exit-Code liegen in `~/.tinyops/runs/`.
  Der Lauf überlebt einen Neustart von tinyops und eine getrennte SSH-Verbindung. **Lokal** startet ein losgelöster Prozess (`agentwrap.py`, auch unter Windows).
- Ein Agent führt je Ordner höchstens einen Lauf gleichzeitig aus.

### Sicherheit
- **Cloud-Agenten (Claude, Codex, Vibe) starten nur für Projekte mit «Cloud-Agent erlaubt»** (Standard: aus), weil Prompt und Code an den Anbieter gehen.
  Ohne Freigabe wird nicht einmal SSH aufgerufen. Eigene Befehle gelten standardmässig auch als Cloud; lokale Modelle lassen sich per `cloud: false` freigeben.
- Der **Befehl** kommt aus eingebauten Vorlagen. Nur beim Typ «custom» steht er in der `config.json` (`command`, mit `{prompt_file}`); die Oberfläche kann ihn nicht setzen oder ändern.
- Der Prompt wird als Datei übertragen (Heredoc mit eindeutigem Ende) und als ein einziges Argument gelesen, nie in eine Shell-Zeile eingebettet; getestet mit feindlichem Prompt.
- Host, Benutzer, Argumente und Ordner werden streng geprüft (kein führender `-`, keine Shell-Zeichen). SSH läuft mit `BatchMode`, strenger Host-Schlüsselprüfung
  (oder bewusst «beim ersten Mal vertrauen») und ohne Passwortabfrage. Ausgaben im Log werden von bekannten Secrets und Token-Formen (GitLab, GitHub, `sk-…`, Bearer, Private Keys) bereinigt.

### Hinweis
- Das Docker-Image enthält keinen SSH-Client; für Remote-Agenten aus dem Container ein Image mit `openssh-client` und die Schlüssel als Volume bereitstellen.

## [0.11.0]

### Neu
- **Sonar-Trend:** An jedem MR und Branch mit Analyse steht neben dem Gate eine kleine Kurve der Findings mit der Änderung seit der ersten Analyse
  (▼ weniger = grün, ▲ mehr = rot). Quelle ist Sonars eigener Verlauf (`api/measures/search_history`, ab zwei Analysen). Liefert Sonar keinen Verlauf,
  nutzt tinyops lokale Schnappschüsse der Gate-Werte (ohne zusätzliche Anfrage, gespeichert nur bei Änderung, 120 Tage). Der Report enthält eine Verlaufstabelle.
- **SonarQube 2026.1 (Multi-Quality-Rule-Modus):** Findings werden nach Auswirkung (`impacts`: Sicherheit, Zuverlässigkeit, Wartbarkeit; hoch/mittel/gering)
  statt nach alter Schwere/Art ausgewertet und im Report so benannt; die neuen Metriknamen der Gate-Bedingungen (`new_software_quality_*`) sind übersetzt.
  Ältere Versionen funktionieren weiter (Rückfall auf Schwere/Art).
- **Verbindungstest Sonar:** neuer Schritt «Pull-Request-Analyse» zeigt je Projekt, wie viele Pull Requests analysiert sind und welcher der letzte ist
  (`api/project_pull_requests/list`), und warnt, wenn die Edition keine MR-Analyse kennt.

### Hinweis
- Alle Sonar-Abfragen nutzen die Web API v1 (`/api/...`). Für Gate, Findings, Hotspots, Verlauf und Pull Requests gibt es nach Sonars Dokumentation
  noch keinen v2-Ersatz, die neue API ersetzt v1 «schrittweise»; die Endpunkt-Liste steht in Sonar unter Hilfe → Web API v2.
- Sonar speichert für `new_*`-Kennzahlen keinen Verlauf. Der Trend zählt deshalb die Findings des MR (`violations`), nicht «neue Findings».

## [0.10.0]

### Neu
- **KI-Kontingent unter der Ideenbox:** eine eingeklappte Box mit einer Zeile pro Fenster (Claude 5 h und Woche, Codex, Mistral Vibe und API).
  Sie klappt nur per Klick auf und nach jedem Reload wieder zu; das Neuladen im Hintergrund lässt eine geöffnete Box offen. Details (Reset, Dollarwerte, Alter) stehen
  in der aufgeklappten Box und, wenn aktiviert, auch in den Einstellungen unter KI-Kontingent. Die Kachel im Raster entfällt.
- **Links an MRs und Branches:** «MR öffnen» bzw. «Branch öffnen», «Sonar» und «Findings» an jedem Eintrag; **«MR erstellen»** an Branches ohne MR
  (öffnet in GitLab das Formular für einen neuen Merge Request mit dem Branch als Quelle), auch an den Branch-Chips in Stories und Board.

### Geändert
- **Abgleich seltener:** GitLab und Jira werden höchstens alle 5 Minuten abgeglichen (vorher 30 s), die Oberfläche fragt alle 5 Minuten nach (vorher 60 s),
  das Kontingent wird 5 Minuten zwischengespeichert. «Neu laden» erzwingt weiterhin einen frischen Abgleich. Steht `cache_seconds` in deiner `config.json`, gilt dieser Wert.

## [0.9.0]

### Neu
- **Sonar-Links und Findings-Report:** Hinter jedem MR und Branch mit Analyse stehen «Sonar» (Dashboard), «Findings» (offene Findings in Sonar) und
  «Report kopieren». Der Report ist Markdown für die Zwischenablage: Gate-Bedingungen, Zähler nach Schwere und Art, Findings je Datei
  (Zeile, Regel, Meldung), Security Hotspots zur Prüfung. Er enthält Pfade und Sonar-Meldungen, keinen Quelltext. Gelesen wird nur auf Knopfdruck
  (GET), höchstens `sonar.report_max` Findings (Standard 200, nach Schwere sortiert).
- **Mistral im KI-Kontingent:** Das Monatsbudget (Vibe und API, Prozent, Dollar, Reset) kommt per Lesezeichen aus dem eingeloggten Browser auf
  `admin.mistral.ai`. Das Lesezeichen liest dort nur die Budgetzahlen und öffnet tinyops mit diesen Zahlen; Cookies und Zugangsdaten sehen nur
  Browser und Mistral. tinyops prüft die Zahlen streng, markiert alte Stände («veraltet» nach 36 h, abgelaufener Monat).

### Bekannte Grenzen
- Das Mistral-Lesezeichen hängt am Seitenaufbau von `admin.mistral.ai` und ist ein Klick pro Aktualisierung. Es wurde nur gegen den Seitentext aus deinem HAR geprüft.
- Der Report wurde nur gegen den Fake-Server geprüft; Felder wie `severity` und `type` der Issues nutzt Sonar auch in neueren Versionen, die neuen «Impacts» liest tinyops nicht.

## [0.8.0]

### Neu
- **KI-Kontingent (nur lesend, standardmässig aus):** Kachel mit dem freien Rest im 5-Stunden- und Wochenfenster von **Claude** und **Codex**.
  Gelesen über die inoffiziellen Schnittstellen, die auch die CLIs nutzen (`api.anthropic.com/api/oauth/usage`, `chatgpt.com/backend-api/wham/usage`),
  mit dem Token aus der Anmeldedatei des jeweiligen CLI. Das Token wird nur gelesen, nie erneuert, gespeichert oder geloggt.
  Jeder Fehler erscheint als «nicht abrufbar» mit Grund, nie als geratene Zahl. Einstellungen mit Test, Preflight-Zeile, Zwischenspeicher.
- Mistral Vibe hat keine Abfrage und bleibt bei den von Hand gepflegten KI-Konten (Einstellungen → Weiteres).

### Bekannte Grenzen
- Beide Schnittstellen sind undokumentiert und können sich ändern; sie wurden nur gegen einen Fake-Server getestet, nicht gegen echte Konten.

## [0.7.0]

### Neu
- **SonarQube-Anbindung (nur lesend):** Quality Gate je Merge Request und je Branch als Chip in Übersicht, Board und Stories.
  Ein rotes Gate zählt bei «Braucht dich». Je GitLab-Projekt ein Sonar-Schlüssel, Token als Secret `sonar_token`
  (`TINYOPS_SONAR_TOKEN`), Verbindungstest und Preflight-Prüfung. Zwischenspeicher und Limit je Abgleich einstellbar.
  Aus per Voreinstellung. Es werden ausschliesslich GET-Anfragen gestellt.
- Versionierung nach SemVer: `server.py --version`, Version in `/healthz`, im Panel, im Docker-Image (Label und Tag), `CHANGELOG.md`.

### Enthalten aus der früheren Zählung
- Sync-Status mit Teilergebnissen, Board mit Workflow und Kategorien, Ideenbox, KI-Konten (aus), Ticketentwurf mit lokalem Modell,
  Jira-Ticket anlegen (nur mit Opt-in), Preflight, Docker/Kubernetes-Deployment, IntelliJ-Run-Configs, Liste manueller Tests.

### Bekannte Grenzen
- Sonar, Jira, GitLab und das Cluster wurden nur gegen Fake-Server und Stubs getestet, nicht gegen echte Instanzen.
- Quality Gates je MR gibt es in SonarQube erst ab Developer Edition.
