# Prüfliste

Kurze Aufgaben zum Selbertesten, im Panel unter **Prüfen** zum Abhaken (ok, Fehler mit Notiz, übersprungen).
Die **Grundprüfung** deckt alle Funktionen ab. Danach kommt je Release ein Abschnitt mit nur dem, was sich geändert hat.
Format einer Zeile: `- [ ] \`id\` Aufgabe → erwartet`. Ändert sich der Text, gilt der Punkt wieder als offen.
Endet eine Zeile mit `[auto: test_modul.Klasse]`, prüft das ein automatischer Test bei jedem Release. Solche Punkte zählen nicht als offen und kommen nicht in «Als Nächstes testen».
«Ergebnis kopieren» gibt Fehler und Notizen als Markdown zurück, zum Einfügen in den nächsten Auftrag.

## Grundprüfung: Start und Einstellungen

- [ ] `b-01` `python3 server.py --preflight` mit deiner Config → alle Schritte OK oder klare Hinweise, kein Token in der Ausgabe
- [ ] `b-02` `python3 server.py --selftest` → «Selbsttest bestanden» [auto: test_qa.AppQa]
- [ ] `b-03` Panel öffnen, oben rechts die Version ansehen → stimmt mit dem Release überein [auto: test_version.Version]
- [ ] `b-04` Einstellungen → «Verbindung testen» bei GitLab, Jira, Sonar und (falls genutzt) GitHub → alles grün; GitLab erkennt die MR-Felder (Reviewer, Freigaben), Jira die Projekt-Keys, Sonar die Projektschlüssel, GitHub die Repos
- [ ] `b-08` Eine Einstellung ändern und speichern, dann `config.json` öffnen → geändert, kein Token im Klartext [auto: test_settings.BuildAndSave]
- [ ] `b-09` Seitenmenü der Einstellungen beim Scrollen → bleibt sichtbar [auto: test_ui.SettingsNav]

## Grundprüfung: Fokus und Ablauf

- [ ] `b-10` Fokus öffnen → «Du bist dran» zeigt Blocker zuerst, jedes Vorhaben mit genau einem nächsten Schritt [auto: test_flow.Derive]
- [ ] `b-11` Ein Vorhaben anklicken → Detail-Panel mit Stationen, nächstem Schritt, MRs und Branches [auto: test_ui.Detail]
- [ ] `b-12` «Schritt erledigt» bei einem Jira-Vorhaben → nächste Station, kleine Punkte-Meldung [auto: test_flow.AppFlow]
- [ ] `b-13` «Schritt erledigt» bei einem Branch ohne Ticket → abgelehnt mit «braucht zuerst ein Ticket»
- [ ] `b-14` Branch ohne Ticket → «tiny-Ticket anlegen» → LOC-Ticket, Kategorie gleich Projekt, Branch hängt dran
- [ ] `b-15` Teilschritt anlegen und abhaken → +3 XP einmal, ab- und wieder anhaken zählt nicht doppelt
- [ ] `b-16` Vorhaben «Als Fokus anheften» → steht oben; Blocker anderswo nur als kleiner Hinweis [auto: test_flow.AppFlow]
- [ ] `b-17` Tasten j/k, Enter, n, i, Esc → wählen, öffnen, neue Aufgabe, Idee, schliessen [auto: test_ui.Detail]
- [ ] `b-18` Kopfzeile «GitLab vor X min» bei abgeschaltetem VPN → Quelle rot, alte Einträge «veraltet» statt verschwunden [auto: test_flow.Derive]

## Grundprüfung: MRs, Reviews, Abnahme

- [ ] `b-20` Eigener MR ohne Reviewer → nächster Schritt «Reviewer zuweisen» [auto: test_flow.Derive]
- [ ] `b-21` MR mit Freigabe oder Daumen → Chip mit Namen, «Mergen» erst danach [auto: test_flow.Derive]
- [ ] `b-22` MR bei «Testen»: Notiz und Umgebung eingeben, «Getestet» → Abnahme mit Commit-SHA [auto: test_flow.AppFlow]
- [ ] `b-23` Danach einen Commit pushen und neu laden → «Erneut testen», alte Abnahme veraltet [auto: test_flow.Derive]
- [ ] `b-24` Review-Queue «Andere warten auf dich» → MRs von Kollegen mit Wartezeit [auto: test_review.GitLabApp]
- [ ] `b-25` Pipeline rot → Blocker «Pipeline reparieren» mit Link [auto: test_flow.Derive]
- [ ] `b-26` Sonar-Gate rot → «Report kopieren» liefert Findings mit Pfaden, ohne Quelltext [auto: test_sonar.ReportTests]

## Grundprüfung: Board, Ideen, Jira

- [ ] `b-30` Board: Karte in eine andere Spalte ziehen → Station gesetzt, im Fokus gleich
- [ ] `b-31` Branch-Chip auf eine Karte ziehen → verknüpft; «Lösen» trennt wieder
- [ ] `b-32` Idee festhalten (Taste i), dann im Board mit Kategorie einplanen → Aufgabe in «Geplant» [auto: test_board.BoardApp]
- [ ] `b-33` Ticket-Entwurf für einen MR ohne Ticket (Vorlage, ohne KI) → Titel und Beschreibung aus MR und Commits [auto: test_ticket.AppTicketFlow]
- [ ] `b-34` Ticket in Jira anlegen (nur mit `allow_create`) → Rückfrage, dann Key mit Link [auto: test_ticket.JiraCreate]

## Grundprüfung: Agenten

- [ ] `b-40` Einstellungen → Agent «Test» → Verbindung, tmux, Arbeitsordner, Programm, git, Rechte geprüft
- [ ] `b-41` restricted-Projekt: Cloud-Agent zuweisen → ausgegraut bzw. abgelehnt [auto: test_agents.Gate]
- [ ] `b-42` Lokalen Agenten zuweisen und starten → läuft im Worktree `.tinyops-wt/<nr>`, dein Checkout bleibt sauber [auto: test_agents.Isolation]
- [ ] `b-43` Lauf öffnen → Log live, «Befehl zum Mitlesen kopieren» funktioniert im Terminal
- [ ] `b-44` Lauf stoppen → Status «abgebrochen», Prozess weg [auto: test_agents.Local]
- [ ] `b-45` internal mit Cloud-Pfaden, Cloud-Agent → Export nur dieser Pfade; «Übernehmen» legt Branch `agent/<key>-<nr>` an [auto: test_agents.Isolation]
- [ ] `b-46` Agent fragt (`tinyops-ask`) → «Agent fragt» unter «Du bist dran», Antwort kommt an [auto: test_agents.Questions]
- [ ] `b-47` Nach dem Lauf → Belege (tinyops-check) und Bericht im Lauf-Dialog [auto: test_agents.Questions]

## Grundprüfung: Verlauf und Review-Punkte

- [ ] `b-50` Log → Verlauf → «Kette prüfen» → in Ordnung [auto: test_audit.Chain]
- [ ] `b-51` `python3 server.py --verify-audit` → in Ordnung, Exit 0 [auto: test_qa.AppQa]
- [ ] `b-52` Detail-Panel → Verlauf zeigt die eigenen Entscheidungen zum Vorhaben [auto: test_ui.Detail]
- [ ] `b-53` «Offene Punkte» bei einem MR mit Kommentaren → nur offene Threads, Datei:Zeile stimmt [auto: test_review.GitLabApp]
- [ ] `b-54` «Als Prompt kopieren» → Markdown mit Zielangaben, Kommentare als Zitat [auto: test_review.Unit]
- [ ] `b-55` Gleiches Jira-Ticket zweimal in 10 min anlegen → Rückfrage nennt das erste [auto: test_audit.JiraDuplicate]

## 0.19.0

- [ ] `r19-01` Vorhaben als Fokus anheften → Zeit läuft im Fokus-Kopf, «Pause» hält sie an [auto: test_ui.PinAndTime]
- [ ] `r19-02` 20 min nichts im Panel tun, dann zurück → Lücke vorgeschlagen, zählt erst nach «Zählen» [auto: test_time.Book]
- [ ] `r19-03` Fokus auf ein anderes Vorhaben wechseln → alte Zeit endet, neue beginnt [auto: test_time.Book]
- [ ] `r19-04` Tab «Zeit» → Entwurf je Ticket, auf 15 min gerundet, Text und Belege (Stationen, Abnahmen) [auto: test_time.AppTime]
- [ ] `r19-05` Entwurf ändern (Minuten, Text) → «bearbeitet», bleibt beim Neuladen so [auto: test_time.AppTime]
- [ ] `r19-06` Zwei Entwürfe zusammenlegen → einer mit der Summe, der andere verworfen [auto: test_time.AppTime]
- [ ] `r19-07` Zeile «Von Hand» mit Ticket und Minuten → neuer Entwurf [auto: test_time.AppTime]
- [ ] `r19-13` Tab «Prüfen»: Selbsttest ausführen, einen Punkt als Fehler mit Notiz markieren, «Ergebnis kopieren» → Selbsttest grün, das Markdown enthält den Fehler mit Notiz [auto: test_qa.AppQa]

## 0.20.0

- [ ] `r20-01` Idee festhalten, im Board öffnen, «Mit dem lokalen Modell bewerten» → Empfehlung, Kategorie, Nutzen, Aufwand; bei einer ähnlichen Idee erscheint «Ähnlich»
- [ ] `r20-02` «Selbst bewerten» und speichern → Bewertung «von dir», auch ohne Modell [auto: test_v20.Ideas]
- [ ] `r20-03` «Ticket daraus» → Entwurf mit Story, Akzeptanzkriterien, Risiken, Tests, Abhängigkeiten [auto: test_v20.Ideas]
- [ ] `r20-04` «Entwurf mit KI» im selben Dialog → Text vom Modell, die Idee ist die Quelle
- [ ] `r20-05` «Als tiny-Ticket» mit Kategorie → LOC-Aufgabe in «Geplant», Akzeptanzkriterien als Teilschritte, Idee erledigt [auto: test_v20.Ideas]
- [ ] `r20-06` Mit `allow_create`: «In Jira anlegen» aus einer Idee → Jira-Ticket, Teilschritte am Ticket, Verlauf «Ticket aus Idee» [auto: test_v20.JiraFromIdea]
- [ ] `r20-07` Einstellungen → IntelliJ: Pfad zum lokalen Checkout eintragen, Befehl prüfen → gespeichert
- [ ] `r20-08` MR bei «Testen» → «In IntelliJ öffnen» → IntelliJ startet mit `../.tinyops-wt/<repo>-mr<nr>-<sha>` auf genau dem Commit des MR (`git log -1`)
- [ ] `r20-09` Danach «Getestet» → Abnahme zeigt den SHA des Worktrees [auto: test_v20.Ide]
- [ ] `r20-10` Neuen Commit auf den MR pushen, neu laden → Chip «IntelliJ … (veraltet)», nächster Schritt sagt «neu öffnen» [auto: test_v20.Ide]
- [ ] `r20-11` Im Worktree eine Datei ändern, × am Chip → Rückfrage wegen geänderter Dateien [auto: test_v20.Ide]
- [ ] `r20-12` Vorhaben auf «Fertig» → saubere Worktrees sind weg (`git worktree list`) [auto: test_v20.Ide]
- [ ] `r20-13` MR mit Review-App (Environment `review/<branch-slug>`) → «Review-App» im Panel und beim Testen öffnet die URL [auto: test_v20.ReviewApp]

## 0.21.0

- [ ] `r21-01` Remote auf das Repo umstellen (`git remote set-url origin …`), `git checkout --detach v0.20.0`, dann `python3 start.py` → «Aktualisiert: v0.20.0 → v0.21.0», Selbsttest läuft, tinyops startet
- [ ] `r21-02` Im Panel → Hinweis «Aktualisiert auf v0.21.0» mit neuen Prüfpunkten, «Was ist neu?» zeigt den CHANGELOG, × blendet ihn aus [auto: test_start.PanelNote]
- [ ] `r21-03` Nochmals `python3 start.py --check` → «Auf dem neuesten Stand» [auto: test_start.Starter]
- [ ] `r21-04` Eine Datei im Checkout ändern, `python3 start.py` → «Geänderte Dateien … kein Update», tinyops startet trotzdem [auto: test_start.Starter]
- [ ] `r21-05` VPN/Netz aus, `python3 start.py` → «Nicht erreichbar … Start mit dem, was da ist» [auto: test_start.Starter]
- [ ] `r21-06` Windows (falls genutzt): Doppelklick auf `start.cmd` startet wie unter Linux; beim Launcher die SmartScreen-Warnung mit «Weitere Informationen → Trotzdem ausführen» übergehen

## 0.21.1

- [ ] `r211-03` Launcher für dein System herunterladen und starten (ohne bestehende Installation) → lädt nach `~/.local/share/tinyops/app` bzw. `%LOCALAPPDATA%\tinyops\app`, Browser geht auf
- [ ] `r211-04` Launcher mit `--where` → zeigt Ordner, Repo `AdBuch/tinyops`, Version v0.21.1 und dein Python [auto: test_launcher.Launcher]
- [ ] `r211-06` `python3 tinyops-launcher.pyz --demo` → wie der Launcher, mit Demo-Daten

## 0.35.0

- [ ] `r35-01` Workspaces → Zahl «Worktrees» anklicken → nur Repos mit Worktrees; ein sauberer, alter Worktree eines Agenten → «Entfernen» → weg, `git worktree list` zeigt ihn nicht mehr; ein Worktree mit offenen Dateien hat keinen Knopf
- [ ] `r35-02` Board: ein tiny-Ticket aus seiner einzigen Kategorie nehmen → Frage «zurück in den Ideenpool?» → ja: es steht bei den Ideen, nein: nichts ändert sich
- [ ] `r35-03` Einstellungen → Fokus → «Spielstand im Fokus zeigen» aus, speichern → im Fokus keine Punkte-Karte, beim Abhaken und Sitzungsende keine XP; wieder an → alles wie vorher
- [ ] `r35-04` Workspaces → «Fetch» bei einem Repo ohne Zugriff → eine kurze Meldung mit dem nächsten Schritt statt der rohen git-Ausgabe [auto: test_v35.FetchHint]
- [ ] `r35-05` Prüfen → Klick auf den Text eines Punkts → Notizfeld; Klick auf einen Befehl im Text → kopiert [auto: test_ui.QaSession]
- [ ] `r35-06` tinyops neu starten, während das Panel offen ist → oben «Keine Verbindung … Neuer Versuch in …», danach verschwindet der Hinweis von selbst [auto: test_ui.Offline]
- [ ] `r351-01` Config von vor 0.35 (ohne «score») → Fokus zeigt die Spielstand-Karte oben rechts [auto: test_v35.V351]
- [ ] `r351-02` Einstellungen → BCS-Token eintragen, speichern → oben unter «Zugänge» steht BCS grün [auto: test_v35.V351]
- [ ] `r351-03` Einstellungen öffnen → «Zugänge» zugeklappt ganz oben, aufklappen → «Eintragen» springt zum Abschnitt [auto: test_ui.Tokens]

## 0.34.0

- [ ] `r34-01` Helpdesk: ein Ticket aus der Queue oder «Ich beobachte» öffnen → «Als Fokus anheften, Zeit starten» → Hero zeigt das Ticket, «Zeit läuft»; Tab «Zeit» zeigt einen Abschnitt darauf
- [ ] `r34-02` Einstellungen → IntelliJ und Review-Umgebung: Pfad bei einem Projekt leer lassen, das in Workspaces liegt → Platzhalter «aus Workspaces: …»; «In IntelliJ öffnen» an einem MR nimmt diesen Checkout
- [ ] `r34-03` Review-Umgebung eines Projekts mit Compose-Datei → «Vorschlag: Docker Compose mit …» → Umsysteme anhaken (z. B. PostgreSQL, ein zweites Repo), speichern
- [ ] `r34-04` MR im Fokus → «Ausprobieren» → Prompt kopieren, git-Befehle kopieren; «Starten» → läuft, «Öffnen» geht auf den Port, `docker ps` zeigt die Umsysteme; «Stoppen» räumt auf
- [ ] `r34-05` Tab «Zeit» und Einstellungen → Zeiterfassung → nirgends mehr MCP oder Projectron, Buchen nur über BCS [auto: test_ui.Views]

## 0.33.0

- [ ] `r33-01` Prüfen → ein älterer Abschnitt aufklappen → unten «… Punkte prüft ein automatischer Test», die Zahl im Kopf zählt nur die Punkte von Hand [auto: test_ui.QaSession]
- [ ] `r33-02` «Als Nächstes testen» → kein Punkt mit automatischem Test dabei; insgesamt deutlich weniger offen als vorher [auto: test_ui.QaSession]
## 0.32.0

- [ ] `r32-01` Fokus → unter dem Titel Repo und Branch als Piktogramm; derselbe Branch hat in der Liste darunter dasselbe Bild [auto: test_ui.Views]
- [ ] `r32-02` Umsetzen-Lauf fertig → oben «Kurz vorab»: ein Satz, jede Datei mit +/− und Begründung; eine Datei ohne Begründung ist markiert [auto: test_ui.AgentCycle]
- [ ] `r32-03` «Als MR-Beschreibung kopieren» → in einen GitLab-MR einfügen → Vorschau zeigt Abschnitte und Checkliste sauber
- [ ] `r32-04` Einstellungen → IntelliJ und Review-Umgebung → Pfad zum Checkout eintragen → im Lauf «In IntelliJ öffnen» → IntelliJ öffnet `.tinyops-wt/…-run<nr>`, dein Checkout ist unverändert
- [ ] `r32-05` Agent auf dem SSH-Rechner → «In IntelliJ öffnen» holt den Branch von dort (dein Schlüssel muss funktionieren)
- [ ] `r32-06` Review-Umgebung «Docker Compose» für ein Projekt → im Lauf starten → läuft, «Öffnen» geht auf den Port → «Stoppen» räumt auf

## 0.31.0

- [ ] `r31-01` Prüfen → oben «Als Nächstes testen» mit fünf Punkten aus 0.31.0 → einen auf ok setzen → der nächste rückt nach, «in dieser Sitzung 1 erledigt» [auto: test_ui.QaSession]
- [ ] `r31-02` Agent zuweisen → «Phase: Planen» → «Ansehen» zeigt den Prompt mit Überschriften und «Leitplanken»; «Kopieren» legt ihn in die Zwischenablage; «Bearbeiten» zeigt den Text [auto: test_ui.AgentCycle]
- [ ] `r31-03` Plan-Lauf fertig → Plan gerendert, keine Prüfpunkte → «Freigeben» → «Umsetzen vorbereiten …» → im Prompt steht «Freigegebener Plan» mit dem Plan als Zitat [auto: test_ui.AgentCycle]
- [ ] `r31-04` Umsetzen-Lauf fertig → Prüfpunkte (Diff gelesen, Umfang, Tests, je Kriterium, Testschritte des Agenten) → «Freigeben» ist gesperrt, bis alle abgehakt sind [auto: test_ui.AgentCycle]
- [ ] `r31-05` «Zurückgeben» ohne Notiz → Hinweis; mit Notiz → «Nachbessern lassen …» öffnet den Auftrag mit deiner Notiz [auto: test_v31.Cycle]
- [ ] `r31-06` Nach der Freigabe «Review vorbereiten …» mit einem lokalen Agenten → Prompt «Review», Branch des Laufs; danach «Test vorbereiten …» [auto: test_v31.Cycle]
- [ ] `r31-07` Einstellungen → Coding-Agenten → Leitplanken: 3 Dateien, Team-Regel speichern → neuer Prompt zeigt beides; ein Lauf mit mehr Dateien zeigt den Hinweis im Freigabe-Kasten [auto: test_v31.Cycle]

## 0.30.0

- [ ] `r30-01` Ein Bug in Arbeit, dessen Typ nicht unter «Vorgangstypen, die beim Limit zählen» steht → er erscheint im Panel «Tasks in Arbeit» mit «zählt nicht» und auf dem Board [auto: test_v30.App]
- [ ] `r30-02` Bug und Begleitticket, beide in Arbeit und in Jira verknüpft → ein Task: Bug oben, «+ Begleitticket» darunter; das Begleitticket hat keine eigene Karte; MRs beider Tickets stehen beim Task [auto: test_v30.Build]
- [ ] `r30-03` Story mit Unteraufgabe in Arbeit → die Story ist der Task [auto: test_v30.Build]
- [ ] `r30-04` «Gruppieren …» → ein anderes Ticket als Task wählen → nach dem Auffrischen hängt das Ticket dort; «eigener Task» trennt es; «Automatisch» setzt zurück; im Verlauf «Ticket einem Task zugeordnet» [auto: test_v30.App]
- [ ] `r30-05` Einstellungen → Jira → Link-Typen auf euren Begleitticket-Typ setzen → andere Links gruppieren nicht mehr
- [ ] `r30-06` Ein Task aus zwei Tickets zählt einmal zum Limit [auto: test_v30.App]
- [ ] `r30-07` Taste i, Text, Haken «Wunsch an tinyops» → Meldung «Für tinyops notiert»; nicht in der Ideenbox; Prüfen → UI-Nutzung zeigt «Wünsche an tinyops 1», der kopierte Bericht enthält den Text mit Ansicht und «zuvor: …» [auto: test_v30.Usage]
- [ ] `r30-08` Im Ideenfeld «tinyops: …» + Enter → landet ebenfalls als Wunsch im Bericht [auto: test_v30.Usage]
- [ ] `r30-09` Nutzungsbericht nennt die Versionen; «Auffällig» steht mit «nur Sitzungen mit 0.30.0» [auto: test_v30.Usage]
- [ ] `r30-10` Eine Fehlermeldung provozieren (z. B. BCS prüfen ohne Entwürfe) → der Bericht listet sie unter «Fehlermeldungen» ohne Ticket-Keys und Titel [auto: test_v30.Usage]

## 0.29.0

- [ ] `r29-01` Einstellungen → Zeiterfassung → BCS-Middleware: Adresse `http://127.0.0.1:3210` oder, mit Haken «Middleware im eigenen Netz», die Adresse des Windows-Hosts (und Token, falls gesetzt) speichern → in der Zeit-Ansicht erscheint die Karte «BCS» mit Anwesenheit und den Einträgen des Tages
- [ ] `r29-02` Eine Adresse ausserhalb von 127.0.0.1/localhost wird beim Speichern abgelehnt [auto: test_v29.Unit]
- [ ] `r29-03` Entwurf bestätigen → «BCS-Aufgabe wählen» → Suche findet die Aufgabe, «oft gebucht» zeigt Vorschläge; mit «für alle DLP-… merken» haben auch andere DLP-Entwürfe die Aufgabe
- [ ] `r29-04` «In BCS prüfen» → Dialog zeigt die Buchungen mit «DLP-… …», in BCS ist noch nichts gebucht; dann «In BCS buchen» → «In BCS gebucht», in BCS stehen die Einträge genau einmal
- [ ] `r29-06` Entwurf nach dem Prüfen ändern, dann buchen → tinyops verlangt eine neue Prüfung [auto: test_v29.Flow]
- [ ] `r29-07` Eine Warnung der Middleware (unbekannte Aufgabe, Konflikt) steht im Dialog, «In BCS buchen» fehlt dann
- [ ] `r29-08` Middleware im Probelauf: «In BCS buchen» meldet «Probelauf», die Entwürfe bleiben bestätigt [auto: test_v29.Flow]
- [ ] `r29-09` Middleware während «In BCS buchen» stoppen → Entwürfe «unklar», gesperrt; nach dem Neustart «Mit BCS abgleichen» → gebucht oder zurück auf bestätigt, nichts doppelt [auto: test_v29.Flow]
- [ ] `r29-10` «Lernende» aufklappen → Wochen-, Jahressaldo und Ferien übrig wie in BCS
- [ ] `r29-11` «Texte vorschlagen» mit dem lokalen Modell → Vorschläge je Entwurf, «Vorschlag übernehmen» setzt den Text, sonst bleibt er
- [ ] `r29-12` Protokoll: «BCS: Aufgabe zugeordnet», «BCS: Buchungen geprüft», «BCS: Buchungen bestätigt» [auto: test_v29.Flow]

## 0.28.0

- [ ] `r28-01` Einstellungen → Microsoft 365: Tenant und Client-ID speichern, «Anmelden» (oder «Mit Code anmelden») mit 2FA → «Angemeldet als …», im Log «Microsoft 365: angemeldet»
- [ ] `r28-04` Fokus: Karte «Heute» zeigt die Termine von heute in der richtigen Uhrzeit, abgesagte fehlen; «Beitreten» erscheint kurz vor Beginn
- [ ] `r28-05` Fokus: «Wartet auf dich» zeigt eine Mail direkt an dich, die du noch nicht beantwortet hast; nach dem Antworten verschwindet sie beim nächsten Lesen
- [ ] `r28-06` Ein ungelesener Teams-Chat erscheint unter «Teams, ungelesen»; nach dem Lesen in Teams verschwindet er
- [ ] `r28-07` Vergangener Termin → «als Zeit» → auf ein Ticket übernehmen → steht in der Zeiterfassung; ein zweites Mal wird abgelehnt [auto: test_v28.AppM365]
- [ ] `r28-08` «Fokuszeit im Kalender eintragen dürfen» an, neu anmelden, Sitzung mit Haken starten → Termin «Fokus: …» im Outlook-Kalender
- [ ] `r28-09` Tags darauf ohne neue Anmeldung kommen die Daten weiter; «Abmelden» → «Nicht angemeldet», das gespeicherte Token ist weg
- [ ] `r28-11` MR in der Review-Liste freigeben → nach dem nächsten Auffrischen +20 XP, nur einmal [auto: test_v28.ReviewXp]
- [ ] `r28-12` Claude Code oder Vibe starten → im Lauf-Dialog erscheinen während des Laufs Zeilen wie «▸ Bash: …», nicht erst am Ende
- [ ] `r28-13` Vibe ohne `--auto-approve` → Warnung im Zuweisen-Dialog [auto: test_v28.Streaming]
- [ ] `r28-14` KI-Kontingent: «Mistral-Abo öffnen» öffnet admin.mistral.ai/subscription [auto: test_v28.Ui]
- [ ] `r28-15` Log: keine wiederholten «GET /logo/… → 404» mehr [auto: test_v28.Ui]

## 0.27.0

- [ ] `r27-01` Agent über SSH zuweisen, Projekt liegt im Arbeitsordner → im Dialog «Repository liegt beim Agenten» mit der Remote-Adresse [auto: test_v27.ServerAccess]
- [ ] `r27-02` Projekt wählen, das beim Agenten fehlt → in der Auswahl «fehlt beim Agenten», Banner «Jetzt klonen», «Zuweisen & starten» ist gesperrt [auto: test_v27.ServerAccess]
- [ ] `r27-03` «Jetzt klonen» über SSH → nach kurzer Zeit «Projekt beim Agenten geklont», der Ordner liegt auf dem Zielrechner, im Log stehen «Klonen gestartet» und «Projekt geklont»
- [ ] `r27-04` Klonen ohne Zugriff (Schlüssel des Zielrechners fehlt bei GitLab) → verständliche Meldung mit dem nächsten Schritt, kein halber Ordner bleibt liegen
- [ ] `r27-05` Goose-Agent mit Modell `qwen…`, Anbieter leer, ohne Cloud-Haken → Lauf startet auf dem Zielrechner mit diesem Modell (im Lauf-Dialog unter «Prompt»/Ausgabe sichtbar)
- [ ] `r27-06` Zweiter Goose-Agent mit einem Cloud-Modell und Cloud-Haken → an einem `restricted`-Projekt gesperrt, an `internal` erlaubt [auto: test_v27.Goose]
- [ ] `r27-07` Goose-Agent ohne Cloud-Haken, Modellname enthält «claude» oder «gpt» → Warnung im Dialog, `restricted` bleibt gesperrt [auto: test_v27.Goose]
- [ ] `r27-08` In einem lokalen Repo ein Passwort committen (nicht pushen) → Workspaces zeigt «1 Geheimnis?» mit Datei und Zeile, ohne den Wert; nach dem Entfernen des Commits ist der Hinweis weg [auto: test_v27.WsSecrets]
- [ ] `r27-10` Ohne Fokus-Sitzung ist oben keine Leiste. Sitzung starten → Leiste mit Uhr; Fokus-Modus schliessen → Leiste bleibt [auto: test_v27.FocusAuto]
- [ ] `r27-11` Zeitbox ablaufen lassen → Leiste zeigt «vorbei», «+15 min» und «Abschliessen»; ohne Klick endet die Sitzung nach zehn Minuten mit einer Meldung, die Zeit auf der Aufgabe läuft weiter [auto: test_v27.FocusAuto]
- [ ] `r27-12` «+15 min» → die Uhr läuft wieder rückwärts
- [ ] `r27-13` Während einer Sitzung 20 Minuten im Editor arbeiten, Panel im Hintergrund → die Zeit zählt durch, keine Lücke [auto: test_v27.FocusAuto]
- [ ] `r27-14` Einstellungen: Jeder Abschnitt hat «Hilfe: so richtest du das ein»; bei den Agenten steht die SSH-Anleitung [auto: test_ui.Views]

## 0.26.0

- [ ] `r26-01` Jira-Ticket mit Abschnitt «Akzeptanzkriterien»: Agent zuweisen → der Dialog zeigt «Auftrag aus dem Ticket» mit den Kriterien als Haken, der Prompt enthält «AK1: …» [auto: test_v26.ServerBrief]
- [ ] `r26-02` Haken bei einem Kriterium und bei «Beschreibung mitschicken» entfernen → der Prompt baut sich neu auf, ohne diese Teile [auto: test_v26.ServerBrief]
- [ ] `r26-03` Ticket mit einem Passwort oder Token in der Beschreibung → im Prompt steht «entfernt», der Dialog nennt die Zahl der Schwärzungen [auto: test_v26.Criteria]
- [ ] `r26-04` Ticket ohne Akzeptanzkriterien → Hinweis im Dialog, der Prompt sagt dem Agenten, dass er nachfragen soll [auto: test_v26.ServerBrief]
- [ ] `r26-05` Claude Code ohne `--permission-mode` (oder Codex ohne `--full-auto`) → Warnung im Dialog; nach dem Eintragen unter Einstellungen → Agenten ist sie weg [auto: test_v26.ServerActions]
- [ ] `r26-06` Lauf starten und abwarten → auf der Karte «fertig · n/m AK»; im Lauf je Kriterium erfüllt, offen, unklar oder nicht gemeldet, mit Beleg [auto: test_v26.RunResult]
- [ ] `r26-07` Im beendeten Lauf steht «Änderungen» mit Commits und Dateien; sie stimmen mit `git log` auf dem Branch `agent/…` überein [auto: test_v26.RunResult]
- [ ] `r26-08` «Nachbessern …» mit einer Anmerkung → neuer Auftrag mit den offenen Kriterien, Ausgang ist der Branch des ersten Laufs; der neue Lauf sieht dessen Commits [auto: test_v26.ServerActions]
- [ ] `r26-09` «Als Ticket-Kommentar kopieren» → Text in der Zwischenablage, in Jira eingefügt lesbar; tinyops selbst hat nichts ins Ticket geschrieben
- [ ] `r26-10` Lokale Aufgabe mit zwei offenen Teilschritten → sie stehen als Kriterien im Auftrag [auto: test_v26.ServerBrief]
- [ ] `r26-11` Helpdesk-Ticket und Cloud-Agent → «Beschreibung mitschicken» ist nicht angehakt [auto: test_v26.ServerBrief]

## 0.25.0

- [ ] `r25-01` Einstellungen → Workspaces: deinen Projektordner eintragen (z. B. `~/work`), speichern → «Durchsucht wird» nennt ihn
- [ ] `r25-02` Tab «Workspaces» → deine Repos erscheinen, auch die in Unterordnern; jedes zeigt GitLab, GitHub, anderer Host oder kein Remote [auto: test_v25.Scan]
- [ ] `r25-03` In einem Repo einen Commit machen, nicht pushen, «Neu einlesen» → «1 Commit nicht gepusht», das Repo steht oben [auto: test_v25.Scan]
- [ ] `r25-04` Eine Datei ändern und einen Stash anlegen → «Dateien offen» und «1 Stash» in der Zeile [auto: test_v25.Scan]
- [ ] `r25-05` Repo aufklappen → Branches mit Upstream, voraus/hinter; «push-Befehl» kopieren und im Terminal ausführen → nach «Neu einlesen» ist das Repo sauber
- [ ] `r25-06` Ein Repo, das nicht in tinyops eingerichtet ist → «nicht in tinyops», Filter «Nicht in tinyops» zeigt es, kein «Agent zuweisen» [auto: test_v25.AppWs]
- [ ] `r25-07` Ein Projektordner ohne Git (z. B. mit `package.json`) → steht unter «Projekte ohne Git» [auto: test_v25.Scan]
- [ ] `r25-08` «Abholen» bei einem Repo → Meldung «abgeholt», dein Arbeitsverzeichnis und deine Branches sind unverändert (`git status`) [auto: test_v25.AppWs]
- [ ] `r25-09` Eingerichtetes Projekt: «Agent zuweisen», Satz eingeben, «Weiter zum Auftrag» → Auftragsdialog mit Prompt; nach dem Start erscheint der Worktree des Agenten im Repo
- [ ] `r25-10` Fokus → Seitenleiste «Nicht gepusht» nennt die Repos; die Zahl am Tab zählt nur Repos über dem Meldealter [auto: test_v25.AppWs]
- [ ] `r25-11` Projekt mit `restricted`: im Agenten-Menü sind Cloud-Agenten ausgegraut [auto: test_agents.Gate]

## 0.24.0

- [ ] `r24-01` Fokus: bei einem Helpdesk-Ticket «Ticket ansehen» → Details öffnen sich im Panel mit Beschreibung und Kommentaren, kein neuer Tab
- [ ] `r24-02` Im Panel «Als Fokus anheften, Zeit starten» → die Leiste unter der Kopfzeile zeigt das Ticket und «Zeit läuft, ohne Zeitbox»
- [ ] `r24-03` Gruppe «Ich beobachte» → deine beobachteten Tickets, geänderte fett; eines anklicken → lesbar im Panel, danach nicht mehr fett [auto: test_v24.AppHd]
- [ ] `r24-04` «Alle gesehen» bei «Ich beobachte» → nichts mehr fett; die Queue bleibt unverändert [auto: test_v24.AppHd]
- [ ] `r24-05` Einstellungen → Helpdesk: Vorschlag unter «Queue» anklicken → Abfrage steht im Feld; «Verbindung testen» zeigt die Schritte «Queue» und «Ich beobachte»
- [ ] `r24-06` Fokus-Sitzung starten, «Klein machen» → breite Leiste mit Aufgabe, Restzeit und Fortschritt; sie bleibt in Board, Zeit und Einstellungen sichtbar [auto: test_ui.FocusSession]
- [ ] `r24-07` Klick auf die Leiste → Fokus-Modus öffnet sich wieder [auto: test_ui.FocusSession]
- [ ] `r24-08` Während eines festen Blocks ohne Sitzung → Leiste «Jetzt wäre: …-Block bis …» mit «Block starten»
- [ ] `r24-09` Details offen, neben das Panel ins Leere klicken → Panel schliesst sich [auto: test_ui.Detail]
- [ ] `r24-10` Nach einem Tag Nutzung den Bericht kopieren → tote Klicks nennen den Ort (z. B. «/ rcard.score»)

## 0.23.0

- [ ] `r23-01` Einstellungen → Helpdesk: Adresse, «basic», Benutzername und Passwort eintragen → «Verbindung testen» zeigt Jira 8.5.1, «Angemeldet als …» und die Anzahl deiner Tickets
- [ ] `r23-02` Speichern → im Fokus erscheint eine Gruppe mit deinen Helpdesk-Tickets; ein Ticket über dem SLA steht oben und zeigt «seit … h» rot [auto: test_v23.AppFocus]
- [ ] `r23-03` Queue-JQL eintragen, speichern → «Queue …» zeigt neue Tickets fett; «Alle gesehen» → nichts mehr fett, nach dem nächsten Abgleich nur wirklich neue [auto: test_v23.AppFocus]
- [ ] `r23-05` Einstellungen → Fokusbereiche: bei Berufsbildung einen Block für jetzt eintragen, speichern → über dem Fokus erscheint das Band «Berufsbildung-Block bis …» [auto: test_v23.Plan]
- [ ] `r23-06` Seitenleiste «Fokuszeit diese Woche» → Berufsbildung mit Ziel, Strich «Soll bis jetzt» und «… h hinter Plan» [auto: test_v23.Plan]
- [ ] `r23-07` «Berufsbildung-Block starten» → Tätigkeit «Betreuung Lernende», 25 min → Vollbild mit Uhr, Aufgabe und Tätigkeit; die Tasten j/k/i tun nichts
- [ ] `r23-08` Im Fokus-Modus einen Gedanken eintippen, Enter → «Geparkt in der Ideenbox», das Feld ist leer und behält den Cursor [auto: test_ui.FocusSession]
- [ ] `r23-09` Tätigkeit wechseln, dann «Klein machen» (oder Esc) → die Uhr läuft in der Kopfzeile weiter; Klick darauf öffnet das Vollbild wieder
- [ ] `r23-10` «Erledigt» nach mehr als 20 Minuten → Meldung mit +15 XP; Tab «Zeit» → der Entwurf für Berufsbildung nennt die Tätigkeiten im Text [auto: test_v23.AppFocus]
- [ ] `r23-11` Fokusbereiche: Ziele über 100 % oder einen Block wie «Mo 9-10» speichern → verständliche Fehlermeldung am Feld [auto: test_v23.Config]
- [ ] `r23-12` Log → Verlauf → «Fokus-Sitzung gestartet» und «beendet» mit Bereich, Minuten und Ergebnis [auto: test_v23.AppFocus]

## 0.22.0

- [ ] `r22-01` KI-Kontingent aufklappen und Chips in der Kopfzeile ansehen → jeder Balken hat einen senkrechten Strich (Zeit übrig) und eine Tempo-Zeile, der Tooltip nennt «% der Zeit übrig»
- [ ] `r22-02` Kurz nach einem 5-h-Reset mit wenig Verbrauch → «Vorsprung … verfallen etwa …»; mitten in einer intensiven Sitzung → «Zu schnell … leer in …» [auto: test_v22.Pace]
- [ ] `r22-04` Einige Minuten normal arbeiten, dann Tab «Prüfen» → «UI-Nutzung» zeigt Sitzungen, aktive Minuten und Ereignisse [auto: test_v22.AppUx]
- [ ] `r22-05` «Bericht kopieren» und einfügen → keine Ticket-Titel, kein eingetippter Text, aber Aktionen, Ansichten und Maus-Verteilung [auto: test_v22.Ux]
- [ ] `r22-06` Drei Mal schnell auf etwas nicht Klickbares klicken, Bericht neu kopieren → «tote Klicks» und «Wutklick» erscheinen [auto: test_v22.Ux]
- [ ] `r22-07` Einstellungen → Weiteres → «UI-Nutzung lokal erfassen» aus, speichern → keine neuen Ereignisse mehr; «Daten löschen» leert den Bericht [auto: test_v22.AppUx]

