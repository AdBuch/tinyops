# Changelog

Semantic Versioning: **minor** (0.x.0) für neue Funktionen, **patch** (0.x.y) für Korrekturen und Fixes.
Solange die Hauptversion 0 ist, kann sich auch bei einer minor-Version noch etwas Grundsätzliches ändern.
Die Version steht in `server.py` (`VERSION`), im Git-Tag `vX.Y.Z`, im Docker-Tag und oben rechts im Panel.
Die frühere Zählung (1.0 bis 2.6) endet hier; **0.7.0 ist der neue Anfang** und enthält alles davon.

## [0.20.0]

### Neu
- **Ideen bewerten:** «Mit dem lokalen Modell bewerten» oder «Selbst bewerten». Die Bewertung wird an der Idee gespeichert: Empfehlung (jetzt/später/verwerfen), Kategorie, Nutzen 1–3, Aufwand S/M/L mit Begründung, Dubletten.
  - «Ähnlich» findet tinyops ohne Modell, über gemeinsame Wörter mit anderen offenen Ideen und laufenden Vorhaben.
  - Das Modell bekommt den Text der Idee, die anderen offenen Ideen und die Titel der laufenden Vorhaben, und nur Modelle im eigenen Netz.
  - Die Antwort wird geprüft (erlaubte Werte, Dubletten nur aus der Liste). Jede Bewertung steht im Verlauf, auch fehlgeschlagene.
  - Sichtbar im Detail-Panel der Idee und als Kurzzeile unter Listen → Ideen.
- **Ticket aus Idee:** «Ticket daraus» nutzt den Ticket-Dialog. Vorlage oder lokales Modell, mit den Abschnitten Story, Akzeptanzkriterien, Risiken, Tests, Abhängigkeiten, offene Fragen.
  - «In Jira anlegen» wie bisher (nur mit `allow_create`, Rückfrage, Doppelt-Schutz) oder «Als tiny-Ticket» mit Kategorie.
  - Die Akzeptanzkriterien werden auf Wunsch Teilschritte; Platzhalter zählen nicht.
  - Die Idee wird erledigt und merkt sich Ticket und Entwurf. Verlauf: «Ticket aus Idee».
- **IntelliJ auf dem MR-Commit:** Bei jedem MR mit eingetragenem lokalem Checkout gibt es «IntelliJ», beim Testen auch im Fokus.
  - Fehlt der Commit, holt tinyops die MR-Ref (`git fetch`, nie push). Dann ein detached Worktree neben dem Checkout (`../.tinyops-wt/<repo>-mr<iid>-<sha8>`) und der IDE-Befehl.
  - Der Befehl ist einstellbar, Standard `idea {path}`. Startet er nicht, kopiert tinyops den Pfad und sagt, wie es weitergeht.
  - «Getestet» bindet die Abnahme an den Commit im Worktree.
  - Ist der MR weiter, zeigt der Chip «veraltet», und der nächste Schritt sagt «neu öffnen».
  - Beim «Fertig» räumt tinyops saubere Worktrees weg. Geänderte bleiben stehen; entfernen nur nach Rückfrage.
  - Neuer Abschnitt Einstellungen → IntelliJ mit Befehl und Pfad je GitLab-Projekt und GitHub-Repo (`repo_path`).
- **Review-App-Link:** Die URL des GitLab-Environments zum MR steht im Panel und beim Testen als «Review-App».
  - Erkannt über den Namen (`…/<branch-slug>`) oder die letzte Bereitstellung.
  - Ein GET je Projekt und Minute, nur lesend.
- Der Selbsttest prüft zusätzlich «Idee bewerten und Ticket-Entwurf». Die Prüfliste hat den Abschnitt 0.20.0 mit 13 Aufgaben.

### Grenzen
- Review-Apps nur für GitLab. GitHub-Deployments sind noch nicht drin.
- Der Fetch der MR-Ref braucht Lesezugriff deines lokalen git auf das Repo (deine üblichen Zugangsdaten). tinyops gibt dafür kein Token weiter.
- `idea` muss im PATH sein (IntelliJ → Tools → Create Command-line Launcher). Den echten Start von IntelliJ unter macOS und Windows habe ich nicht getestet, nur einen Ersatzbefehl.
- Die Ähnlichkeitssuche ist einfach (gemeinsame Wörter). Umformulierte Dubletten findet eher das Modell.

## [0.19.0]

### Neu
- **Fokus-Zeit:** «Als Fokus anheften» startet die Zeit für dieses Vorhaben, ein Wechsel stoppt sie. «Pause» und «Weiter» stehen im Fokus-Kopf.
  - Das Panel meldet sich jede Minute, solange es sichtbar ist und du in den letzten 5 Minuten etwas getan hast.
  - Nach `idle_minutes` (Standard 15) ohne Lebenszeichen endet der Abschnitt beim letzten Lebenszeichen. Die Pause wird als **Lücke** vorgeschlagen («Zählen» oder «Verwerfen») und nie still mitgezählt.
  - Ist der Browser zu, zählt nichts weiter.
  - Agentenlaufzeit zählt nicht. Abschnitte über Mitternacht werden auf die Tage verteilt.
- **Tab «Zeit»:** Entwürfe je Tag und Ticket, auf 15 Minuten gerundet (kaufmännisch, unter 5 Minuten kein Entwurf; beides einstellbar).
  - Text aus Titel und erledigten Teilschritten, Belege aus Stationen, Teilschritten und Abnahmen mit Commit.
  - Bearbeiten (bleibt beim Neuladen, gemessene Zeit steht daneben), zusammenlegen, verwerfen, wiederherstellen, von Hand hinzufügen, «Alle offenen bestätigen».
  - Branches ohne Ticket lassen sich erst nach dem Eintragen eines Tickets bestätigen. Ein Hinweis zeigt offene Entwürfe an früheren Tagen.
- **Übergabe an deinen MCP**, Vertrag `tinyops.time-entry/1` (der Vorschlag aus der Roadmap, siehe README 4w):
  - «Bestätigen» sendet per `POST` an die Wrapper-API, mit `Idempotency-Key` aus dem Inhalt und optional `Authorization: Bearer` (`mcp_token`).
  - Nur `status: booked` gilt als gebucht. `rejected` ergibt «abgelehnt». Fehler, Zeitüberschreitung, kein JSON oder kein Status ergeben «fehlgeschlagen» (bestätigt, nicht gebucht), mit «Erneut senden». Gebuchtes sendet tinyops nie ein zweites Mal.
  - Abholen statt Schieben: `GET /api/time/export`, Rückmeldung über `POST /api/time/result`.
  - Nur Adressen im eigenen Netz, ausser «Externe Adresse erlauben». «Verbindung testen» prüft mit GET und bucht nichts.
  - Jede Bestätigung, Sendung, Rückmeldung, Änderung und Lücke steht im Verlauf.
- **Qualität: Tab «Prüfen».**
  - **Prüfliste** aus `QA-CHECKLIST.md`: Die Grundprüfung deckt mit 44 kurzen Aufgaben alle Funktionen ab, dazu kommt je Release ein Abschnitt nur mit dem, was sich geändert hat (hier 13 Aufgaben).
    - Abhaken mit ok, Fehler mit Notiz oder übersprungen. Der Stand liegt in der Datenbank. Ändert sich der Text einer Aufgabe, ist sie wieder offen.
    - «Ergebnis kopieren» liefert Fehler mit Notizen als Markdown. Fehler lassen sich als Aufgabe ins Board legen.
    - Ein Test stellt sicher, dass jedes Release einen eigenen Abschnitt hat.
  - **Selbsttest** (Knopf oder `python3 server.py --selftest`): Oberfläche, Prompt-Vorlagen, Syntax der Hilfsskripte, Prüfliste, Datenbank (`integrity_check`), Kette des Verlaufs. Dazu ein Durchlauf der Kernfunktionen mit Demo-Daten in einem leeren Ordner: Station, «Schritt erledigt», Verlauf, Zeitentwurf, Review-Punkte. Deine Daten bleiben unberührt.

### Grenzen
- Der Vertrag mit deinem MCP ist mein Vorschlag. Bis dein MCP ihn umsetzt, ist «Senden» nur gegen einen Test-MCP geprüft. Weicht deine Wrapper-API ab, bleibt die Anpassung klein, weil sie in `timesheet.payload()` und `App.time_send()` steckt.
- Gemessen wird nur, was im Panel passiert. Arbeit in IntelliJ ohne Panel-Aktivität zählt nach dem Leerlauf als Lücke, die du annimmst.
- Das Lebenszeichen hängt am offenen Tab. Mehrere Tabs schaden nicht, zählen aber auch nicht doppelt.

## [0.18.0]

### Neu
- **Agenten fragen statt raten:** Jeder Lauf hat drei Hilfsskripte im PATH (reines `sh`, lokal und auf SSH-Zielen):
  - `tinyops-ask "Frage" "Option A" "Option B"` schreibt `<nr>.question.json` und wartet auf die Antwort.
    - Nach `-t` Sekunden (Standard 100) endet es mit Exit 3 und dem Hinweis `tinyops-ask --wait <nr>`. So reisst das Werkzeug-Zeitlimit von Claude Code oder Codex nichts ab, und es entsteht keine neue Frage.
    - `-n` fragt, ohne zu warten.
  - `tinyops-check <Befehl>` führt Tests oder Builds aus und hält Befehl, Exit-Code und Dauer in `<nr>.checks` fest.
  - `tinyops-report` speichert den Ergebnisbericht als `<nr>.summary.md`.
  - Die Prompt-Vorlagen erklären die drei Werkzeuge (`prompts/agent-tools.md` wird an jeden Agenten-Prompt angehängt).
- **«Agent fragt»** steht als nächster Schritt unter «Du bist dran», genau einmal je Frage.
  - Antworten geht im Lauf-Dialog über die Optionen als Knöpfe oder per Freitext (Ctrl+Enter).
  - Die Antwort landet als `<nr>.answer.<id>` beim Agenten. Frage und Antwort stehen im Verlauf.
  - Ohne Antwort greift das Zeitlimit des Agenten: Der Lauf wird «abgelaufen» mit dem Hinweis «Eine Frage war noch offen».
- **Ergebnis ohne Log-Lesen:** Nach dem Ende liest tinyops Bericht und Belege ein (lokal oder per SSH) und zeigt sie im Lauf-Dialog.
  - **Belege** sind die Befehle, die über `tinyops-check` liefen, mit Exit-Code. Der **Bericht** ist ausdrücklich «seine Angaben, nicht geprüft».
  - Der nächste Schritt sagt zum Beispiel «2 Belege, 1 mit Fehler. Bericht liegt vor».
  - «Ergebnis prüfen» erscheint jetzt auch bei MRs (früher nur vor dem MR), bis du den Lauf einmal geöffnet hast.
- **Offene Review-Punkte exportieren:** «Offene Punkte» bei jedem MR/PR im Detail-Panel, bei Reviews anderer und als Aktion von «Kommentare klären».
  - GitLab: offene, auflösbare Threads aus `/merge_requests/:iid/discussions`, nur GET. Systemnotizen, erledigte Threads und reine Kommentare zählen nicht.
  - GitHub: Review-Kommentare als Threads samt Antworten, dazu «Änderungen angefordert» mit Text. Ob ein Thread erledigt ist, liefert die REST-API nicht; tinyops zeigt dort «Status?» und alles zum Abwählen.
  - Jeder Punkt hat sein Ziel: Datei, Zeile oder Bereich, alte oder neue Fassung, Commit des Kommentars, Hinweis «älterer Stand», Link zum Kommentar. Für den MR: Branch, Zielbranch, aktueller Commit, Datenklasse.
  - **Als Prompt kopieren:** Markdown aus `prompts/review-topics.md`. Kommentare stehen als Zitat und gelten ausdrücklich als Daten, nicht als Anweisungen.
  - **JSON** (`tinyops.review-topics/1`) mit allen Zielangaben, zum Weiterverarbeiten.
  - **Agent beauftragen:** Der Agent bekommt die gewählten Punkte als Prompt, mit Rückfrage- und Berichtsweg, und arbeitet im Worktree des MR-Branches.
  - Export-Modus (internal mit Cloud-Pfaden): Punkte zu Dateien ausserhalb der Pfade und allgemeine Punkte gehen nicht an den Cloud-Agenten. Der Dialog nennt, was weggelassen wurde.
  - Kein Code aus dem Diff im Export (GitHubs `diff_hunk` bleibt draussen). Den Code liest der Agent im Repository.
  - Jeder Export steht im Verlauf (Format, Anzahl, Datenklasse).

### Grenzen
- `tinyops-check` ist eine Konvention. Ein Agent kann die Datei `<nr>.checks` auch selbst schreiben. Gegen einen böswilligen Agenten schützt das nicht, gegen «hab getestet» ohne Test schon.
- Ob ein Cloud-Agent die Hilfsskripte aufrufen darf, entscheidet dessen eigene Freigabe für Shell-Befehle (z. B. `--allowedTools` bei Claude Code). Lokal unter Windows laufen die `sh`-Skripte nur mit Git for Windows.
- Die Aufrufe gegen die echten GitLab-19.2- und GitHub-APIs sind aus der Doku gebaut und gegen Mocks getestet, nicht gegen deine Instanzen.

## [0.17.0]

### Neu
- **Verlauf (Audit-Trail):** Tabelle `audit` in `tinyops.db`, nur anhängend. Trigger in SQLite sperren UPDATE und DELETE.
  - Jeder Eintrag trägt den Hash des vorigen (SHA-256-Kette) und eine Instanz-Kennung, damit später mehrere Instanzen oder eine zentrale Datenbank unterscheidbar bleiben.
  - Erfasst werden:
    - Jira-Ticket anlegen, auch abgelehnte Versuche
    - Station setzen und zurücksetzen, «Schritt erledigt» (mit Zielstation), tiny-Ticket (Ziel ist das neue Ticket, der Branch steht in den Details), Aufgabe anlegen oder löschen, Idee einplanen, Kategorien
    - Branch verknüpfen und lösen
    - Abnahme mit den Commits (`ref@sha`), Notiz und Umgebung
    - Fokus anheften
    - Agent zuweisen, starten, stoppen, fertig, abgelaufen, entfernen und übernehmen, jeweils mit Datenklasse, Ort, Modus und dem **Prompt nur als Hash**; gesperrte Zuweisungen und Übernahmen mit Pfaden ausserhalb der Freigabe auch
    - Einstellungen gespeichert: welche Bereiche sich geändert haben und welche Zugangsdaten neu gespeichert wurden, nie Werte
    - Testumgebung deployen und abbauen
  - Abgelehnte Aktionen stehen als Fehler im Verlauf.
  - Verschachtelte Aktionen schreiben genau einen Eintrag. Beispiel: «Schritt erledigt» setzt intern eine Station, im Verlauf steht trotzdem nur «Schritt erledigt».
  - Schreibt der Verlauf nicht (Platte voll), läuft die Aktion trotzdem und der Fehler steht im Log.
- **Verlauf im Detail-Panel** je Vorhaben: Ticket plus alle Branches der Karte, die letzten 30 Einträge.
- **«Log» hat zwei Ansichten:** «Verlauf» (Standard) mit «Kette prüfen» und «Export (JSON)», daneben das technische Log wie bisher.
- **Kommandozeile:**
  - `python3 server.py --verify-audit` prüft die Kette (Exit-Code 1, wenn sie gebrochen ist) und zeigt den letzten Hash.
  - `--export-audit DATEI` schreibt den Verlauf als JSON (`-` für die Standardausgabe).
  - Erkannt werden geänderte Einträge, gelöschte Einträge in der Mitte und fehlende letzte Einträge.
- **Doppelt-Schutz beim Jira-Anlegen:** Gleicher Titel (ohne Gross/klein und Leerzeichen) im selben Projekt innerhalb von 10 Minuten fragt nach und nennt das schon angelegte Ticket. Ein zweites gibt es nur auf ausdrücklichen Wunsch.
- **Aufbewahrung der Agenten-Dateien:** `agent_log_days` (Standard 30, 0 = nie), einstellbar unter Einstellungen → Coding-Agenten.
  - Der Wächter löscht einmal am Tag Logs, Prompts und Patches älterer Läufe lokal und auf jedem SSH-Ziel.
  - Laufende Läufe bleiben unangetastet, die Einträge in der Liste auch. Gelöschtes steht im Verlauf.
- Die Token-Schwärzung (bekannte Formen wie `glpat-…`, `ghp_…`, `Bearer …`) liegt jetzt zentral in `secretstore` und gilt für Agenten-Logs und den Verlauf.

### Grenzen
- Die Kette zeigt Änderungen an, verhindert sie aber nicht. Wer Schreibrechte auf `tinyops.db` hat, kann die ganze Kette neu berechnen. Auffallen tut das nur, wenn der letzte Hash ausserhalb liegt, zum Beispiel in einem regelmässigen Export oder in der Ausgabe von `--verify-audit`.
- Teilschritte (Haken in der Checkliste) stehen nicht im Verlauf, sondern nur im Spielstand.
- Der Verlauf wird nicht automatisch gekürzt; bei normaler Nutzung sind das wenige MB im Jahr.

## [0.16.0]

### Neu
- **Datenklasse je Projekt und GitHub-Repo:** `restricted` (Standard), `internal`, `public`. Sie ersetzt «Cloud-Agent erlaubt»: Wo das gesetzt war, wird `internal`, sonst `restricted`.
  - `restricted`: nur Agenten ohne Cloud. Die Sperre greift schon beim Zuweisen, serverseitig; in der Auswahl sind solche Agenten ausgegraut.
  - `internal`: Cloud-Agenten erlaubt, optional nur für **Cloud-Pfade** (siehe Export).
  - `public`: ohne Einschränkung.
- **Worktree je Lauf** (Standard): Jeder Lauf arbeitet in `<Arbeitsordner>/.tinyops-wt/<Nr>` auf einem eigenen Branch `agent/<key>-<nr>`.
  - Abgezweigt wird vom Branch des Tickets (lokal oder `origin/…`), sonst vom aktuellen Stand.
  - Dein Checkout bleibt unberührt, mehrere Läufe im selben Repo laufen parallel.
  - «Entfernen» sichert offene Änderungen als Commit auf dem Agenten-Branch und entfernt den Worktree; der Branch bleibt.
  - «Gemeinsamer Ordner» (wie bis 0.15) bleibt als Option je Agent.
- **Export für Cloud-Agenten bei `internal` mit Cloud-Pfaden:**
  - Der Agent bekommt einen Ordner nur mit diesen Pfaden und einem eigenen, frischen Git. Weder die übrigen Dateien noch die Git-Objekte des echten Repos sind erreichbar. Getestet: `git cat-file` auf eine fremde Datei schlägt fehl.
  - «Übernehmen» prüft, dass nur Dateien innerhalb der Pfade geändert wurden, und legt sie als Commit auf `agent/<key>-<nr>` im echten Repo an. Pushen und MR erstellen machst du.
  - Nicht übernommene Änderungen schützt «Entfernen» mit einer Rückfrage.
- **Lokale Agenten:** neue Arten **Goose** (`goose run -i <Prompt-Datei>` mit `GOOSE_PROVIDER=ollama`, `GOOSE_MODEL=<Modell>`) und **opencode** (`opencode run --model ollama/<Modell>`), mit Modellfeld. Beide gelten als lokal, solange «sendet Daten an einen Cloud-Anbieter» aus ist. Die Aufrufe sind aus der Doku abgeleitet und nicht gegen die echten CLIs getestet. LangGraph und Ähnliches laufen über «Eigener Befehl».
- **Rechte-Check im Agenten-Test:**
  - Remote warnt der Test bei root, bei sudo ohne Passwort und bei Zugriff auf den Docker-Socket.
  - Lokal weist er darauf hin, dass der Agent mit deinen Rechten läuft.
  - Neuer Schritt «Isolation» prüft, ob git vorhanden ist.
- Der Agenten-Prompt (`prompts/agent-task.md`) beschreibt jetzt den Arbeitsplatz: Worktree mit Agenten-Branch, Export-Ausschnitt oder gemeinsamer Ordner.

### Geändert gegenüber der Roadmap
- Statt eines Sparse-Checkouts gibt es den **Export**: Ein Sparse-Checkout verbirgt nur Dateien. Über die gemeinsamen Git-Objekte (`git show main:pfad`) bleibt alles lesbar, also wäre es keine echte Grenze.

### Grenzen
- Netz und Dateisystem ausserhalb des Arbeitsordners sichert tinyops nicht; das ist Sache des Hosts (eigener Agent-Benutzer, Firewall).
- Pushen auf geschützte Branches verhindert GitLab (Protected Branches), nicht tinyops.
- Lokal unter Windows braucht die Isolation `sh` aus Git for Windows im PATH; der Export ist dort ungetestet.

## [0.15.0]

### Neu
- **Abnahme am Commit:** «Getestet» speichert je MR/PR den Head-Commit, die Zeit und optional Notiz und Umgebung (Felder im Detail-Panel).
  - Kommen danach neue Commits, fällt das Vorhaben zurück auf «Testen» mit «Erneut testen» und zeigt «getestet a1b2c3d4, jetzt e5f6a7b8».
  - Auch «Fertig» mit noch offenem MR braucht eine gültige Abnahme; Punkte gibt es erst danach.
  - Vor 0.15 gesetztes «Getestet» hat keinen Commit-Bezug und wird einmal zur Bestätigung vorgelegt.
  - Das Panel zeigt je MR, auf welchem Stand abgenommen wurde.
- **Unbekannt statt grün:**
  - Sind Freigaben eines MR/PR nicht lesbar, steht «Freigabe prüfen» da, statt dass die Review-Prüfung entfällt; nach eigener Prüfung geht es mit ✓ weiter.
  - Im Fokus-Kopf steht je Quelle (GitLab, GitHub, Jira, Sonar) der Stand oder der Fehler mit dem Alter des letzten guten Stands.
  - Fällt GitLab oder GitHub ganz oder für ein Projekt/Repo aus, bleiben die letzten Einträge stehen, markiert als «veraltet», statt zu verschwinden.
- **Zeitlimit für Agenten:** `max_minutes` je Agent (Standard 60, 0 = aus), einstellbar unter Einstellungen → Coding-Agenten.
  - Danach beendet tinyops den Lauf samt Prozessen (remote die Prozessgruppen der tmux-Sitzung, lokal den Prozessbaum) und setzt «abgelaufen», ein Blocker in Fokus.
  - Ein Wächter prüft alle 30 s, auch wenn das Panel nicht offen ist.
- **Fokus anheften:** «Als Fokus anheften» im Detail-Panel; es gibt höchstens einen.
  - «Jetzt dran» zeigt dann immer dieses Vorhaben, auch wenn es wartet. Blocker anderswo erscheinen als kleiner Hinweis («3 Blocker anderswo»), statt den Fokus zu wechseln.
  - «Fokus lösen» gibt die automatische Auswahl zurück.
- **Selbsttest der Review-Felder:** Der GitLab-Verbindungstest (und damit auch `--preflight`) prüft an einem offenen MR, ob `detailed_merge_status`, `reviewers`, `upvotes` und `/approvals` geliefert werden.

### Korrekturen
- Mehrere Meldungen gleichzeitig liegen übereinander statt aufeinander.

## [0.14.0]

### Neu
- **GitHub als Quelle** (github.com oder GitHub Enterprise, nur lesend): Einstellungen → GitHub mit Token, Verbindungstest (Anmeldung, Anfragelimit,
  Zugriff je Repo, Warnung bei Tokens mit Schreibrechten) und Repo-Suche. Aus den gewählten Repos kommen deine PRs und Branches, aus allen sichtbaren Repos
  die Review-Anfragen und dir zugewiesenen PRs. PRs bringen Checks/Status (als Pipeline), Mergezustand (Konflikt, hinter main), angefragte Reviewer,
  Approves und Daumen hoch mit. Sie fahren denselben Ablauf wie GitLab-MRs, tragen die Quelle «GitHub» und heissen «PR #N».
  Agenten lassen sich auch GitHub-Repos zuweisen (Agent-Ordner und Cloud-Freigabe je Repo). Auch ohne GitLab nutzbar.
- **Review vor dem Merge:** Ein MR ohne Reviewer hat als Schritt «Reviewer zuweisen». Mit Reviewer, aber ohne Approve und ohne 👍 heisst er «Review abwarten»
  (unter «Läuft gerade», mit Namen der Reviewer). Weiter zu Testen und Mergen geht es erst mit Approve oder 👍. Verlangen die Regeln im GitLab-Projekt noch Freigaben,
  reicht der Daumen nicht. Auch von Hand auf «Getestet» gesetzt bleibt «Mergen» blockiert, bis die Freigabe da ist. Im Detail-Panel stehen Reviewer, Approves und Daumen.
  GitLab: Reviewer und Daumen kommen aus der MR-Liste, die Freigaben aus einem zusätzlichen GET je eigenem MR.
- **Schritt erledigt:** Ein ✓ neben dem Knopf jeder Zeile (und gross in «Jetzt dran» und im Panel) schliesst die aktuelle Station ab und setzt die nächste
  von Hand. Zählt im Spielstand wie jeder Fortschritt; «Automatisch» im Panel nimmt es zurück.
- **Ein Branch braucht ein Ticket:** Branches und MRs ohne Jira- oder tiny-Ticket haben als Schritt «Ticket zuordnen» (blockiert, rot). Ein Klick legt ein tiny-Ticket an:
  Titel aus dem Branch, Station «Umsetzung», Kategorie = Projekt (wird bei Bedarf angelegt), der Branch hängt daran. «Schritt erledigt» geht vorher nicht.
  tiny-Keys (LOC-…) im Branchnamen werden auch mit gesetzten Jira-Projektschlüsseln erkannt, und auch ganz ohne Jira.

### Korrekturen
- Ein eigener MR, dessen Key Jira nicht kennt (Tippfehler, kein Zugriff), verschwand aus Board und Fokus. Er erscheint jetzt als eigene Karte mit dem Titel des MR.

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
