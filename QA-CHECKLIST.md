# Prüfliste

Kurze Aufgaben zum Selbertesten, im Panel unter **Prüfen** zum Abhaken (ok, Fehler mit Notiz, übersprungen).
Die **Grundprüfung** deckt alle Funktionen ab. Danach kommt je Release ein Abschnitt mit nur dem, was sich geändert hat.
Format einer Zeile: `- [ ] \`id\` Aufgabe → erwartet`. Ändert sich der Text, gilt der Punkt wieder als offen.
«Ergebnis kopieren» gibt Fehler und Notizen als Markdown zurück, zum Einfügen in den nächsten Auftrag.

## Grundprüfung: Start und Einstellungen

- [ ] `b-01` `python3 server.py --preflight` mit deiner Config → alle Schritte OK oder klare Hinweise, kein Token in der Ausgabe
- [ ] `b-02` `python3 server.py --selftest` → «Selbsttest bestanden»
- [ ] `b-03` Panel öffnen, oben rechts die Version ansehen → stimmt mit dem Release überein
- [ ] `b-04` Einstellungen → GitLab «Verbindung testen» → alle Schritte grün, die MR-Felder (Reviewer, Freigaben) werden erkannt
- [ ] `b-05` Einstellungen → Jira «Verbindung testen» → grün, Projekt-Keys gefunden
- [ ] `b-06` Einstellungen → Sonar «Verbindung testen» → grün, Projektschlüssel gefunden
- [ ] `b-07` Einstellungen → GitHub «Verbindung testen» (falls genutzt) → grün, Repos wählbar
- [ ] `b-08` Eine Einstellung ändern und speichern, dann `config.json` öffnen → geändert, kein Token im Klartext
- [ ] `b-09` Seitenmenü der Einstellungen beim Scrollen → bleibt sichtbar

## Grundprüfung: Fokus und Ablauf

- [ ] `b-10` Fokus öffnen → «Du bist dran» zeigt Blocker zuerst, jedes Vorhaben mit genau einem nächsten Schritt
- [ ] `b-11` Ein Vorhaben anklicken → Detail-Panel mit Stationen, nächstem Schritt, MRs und Branches
- [ ] `b-12` «Schritt erledigt» bei einem Jira-Vorhaben → nächste Station, kleine Punkte-Meldung
- [ ] `b-13` «Schritt erledigt» bei einem Branch ohne Ticket → abgelehnt mit «braucht zuerst ein Ticket»
- [ ] `b-14` Branch ohne Ticket → «tiny-Ticket anlegen» → LOC-Ticket, Kategorie gleich Projekt, Branch hängt dran
- [ ] `b-15` Teilschritt anlegen und abhaken → +3 XP einmal, ab- und wieder anhaken zählt nicht doppelt
- [ ] `b-16` Vorhaben «Als Fokus anheften» → steht oben; Blocker anderswo nur als kleiner Hinweis
- [ ] `b-17` Tasten j/k, Enter, a, n, i, Esc → wählen, öffnen, nächsten Schritt, neue Aufgabe, Idee, schliessen
- [ ] `b-18` Kopfzeile «GitLab vor X min» bei abgeschaltetem VPN → Quelle rot, alte Einträge «veraltet» statt verschwunden

## Grundprüfung: MRs, Reviews, Abnahme

- [ ] `b-20` Eigener MR ohne Reviewer → nächster Schritt «Reviewer zuweisen»
- [ ] `b-21` MR mit Freigabe oder Daumen → Chip mit Namen, «Mergen» erst danach
- [ ] `b-22` MR bei «Testen»: Notiz und Umgebung eingeben, «Getestet» → Abnahme mit Commit-SHA
- [ ] `b-23` Danach einen Commit pushen und neu laden → «Erneut testen», alte Abnahme veraltet
- [ ] `b-24` Review-Queue «Andere warten auf dich» → MRs von Kollegen mit Wartezeit
- [ ] `b-25` Pipeline rot → Blocker «Pipeline reparieren» mit Link
- [ ] `b-26` Sonar-Gate rot → «Report kopieren» liefert Findings mit Pfaden, ohne Quelltext

## Grundprüfung: Board, Ideen, Jira

- [ ] `b-30` Board: Karte in eine andere Spalte ziehen → Station gesetzt, im Fokus gleich
- [ ] `b-31` Branch-Chip auf eine Karte ziehen → verknüpft; «Lösen» trennt wieder
- [ ] `b-32` Idee festhalten (Taste i), dann im Board mit Kategorie einplanen → Aufgabe in «Geplant»
- [ ] `b-33` Ticket-Entwurf für einen MR ohne Ticket (Vorlage, ohne KI) → Titel und Beschreibung aus MR und Commits
- [ ] `b-34` Ticket in Jira anlegen (nur mit `allow_create`) → Rückfrage, dann Key mit Link

## Grundprüfung: Agenten

- [ ] `b-40` Einstellungen → Agent «Test» → Verbindung, tmux, Arbeitsordner, Programm, git, Rechte geprüft
- [ ] `b-41` restricted-Projekt: Cloud-Agent zuweisen → ausgegraut bzw. abgelehnt
- [ ] `b-42` Lokalen Agenten zuweisen und starten → läuft im Worktree `.tinyops-wt/<nr>`, dein Checkout bleibt sauber
- [ ] `b-43` Lauf öffnen → Log live, «Befehl zum Mitlesen kopieren» funktioniert im Terminal
- [ ] `b-44` Lauf stoppen → Status «abgebrochen», Prozess weg
- [ ] `b-45` internal mit Cloud-Pfaden, Cloud-Agent → Export nur dieser Pfade; «Übernehmen» legt Branch `agent/<key>-<nr>` an
- [ ] `b-46` Agent fragt (`tinyops-ask`) → «Agent fragt» unter «Du bist dran», Antwort kommt an
- [ ] `b-47` Nach dem Lauf → Belege (tinyops-check) und Bericht im Lauf-Dialog

## Grundprüfung: Verlauf und Review-Punkte

- [ ] `b-50` Log → Verlauf → «Kette prüfen» → in Ordnung
- [ ] `b-51` `python3 server.py --verify-audit` → in Ordnung, Exit 0
- [ ] `b-52` Detail-Panel → Verlauf zeigt die eigenen Entscheidungen zum Vorhaben
- [ ] `b-53` «Offene Punkte» bei einem MR mit Kommentaren → nur offene Threads, Datei:Zeile stimmt
- [ ] `b-54` «Als Prompt kopieren» → Markdown mit Zielangaben, Kommentare als Zitat
- [ ] `b-55` Gleiches Jira-Ticket zweimal in 10 min anlegen → Rückfrage nennt das erste

## 0.19.0

- [ ] `r19-01` Vorhaben als Fokus anheften → Zeit läuft im Fokus-Kopf, «Pause» hält sie an
- [ ] `r19-02` 20 min nichts im Panel tun, dann zurück → Lücke vorgeschlagen, zählt erst nach «Zählen»
- [ ] `r19-03` Fokus auf ein anderes Vorhaben wechseln → alte Zeit endet, neue beginnt
- [ ] `r19-04` Tab «Zeit» → Entwurf je Ticket, auf 15 min gerundet, Text und Belege (Stationen, Abnahmen)
- [ ] `r19-05` Entwurf ändern (Minuten, Text) → «bearbeitet», bleibt beim Neuladen so
- [ ] `r19-06` Zwei Entwürfe zusammenlegen → einer mit der Summe, der andere verworfen
- [ ] `r19-07` Zeile «Von Hand» mit Ticket und Minuten → neuer Entwurf
- [ ] `r19-08` Einstellungen → Zeiterfassung: Wrapper-URL deines MCP, «Verbindung testen» → erreichbar, nichts gebucht
- [ ] `r19-09` Entwurf bestätigen → an deinen MCP gesendet, Status «gebucht» mit Referenz
- [ ] `r19-10` MCP stoppen, dann bestätigen → «fehlgeschlagen» (bestätigt, nicht gebucht), «Erneut senden» klappt nach dem Start
- [ ] `r19-11` Denselben Entwurf zweimal senden lassen (MCP-Log ansehen) → gleicher Idempotency-Key, eine Buchung
- [ ] `r19-12` Dein MCP holt `GET /api/time/export` ab und meldet `POST /api/time/result` → Entwurf «gebucht»
- [ ] `r19-13` Tab «Prüfen»: Selbsttest ausführen, einen Punkt als Fehler mit Notiz markieren, «Ergebnis kopieren» → Selbsttest grün, das Markdown enthält den Fehler mit Notiz

## 0.20.0

- [ ] `r20-01` Idee festhalten, im Board öffnen, «Mit dem lokalen Modell bewerten» → Empfehlung, Kategorie, Nutzen, Aufwand; bei einer ähnlichen Idee erscheint «Ähnlich»
- [ ] `r20-02` «Selbst bewerten» und speichern → Bewertung «von dir», auch ohne Modell
- [ ] `r20-03` «Ticket daraus» → Entwurf mit Story, Akzeptanzkriterien, Risiken, Tests, Abhängigkeiten
- [ ] `r20-04` «Entwurf mit KI» im selben Dialog → Text vom Modell, die Idee ist die Quelle
- [ ] `r20-05` «Als tiny-Ticket» mit Kategorie → LOC-Aufgabe in «Geplant», Akzeptanzkriterien als Teilschritte, Idee erledigt
- [ ] `r20-06` Mit `allow_create`: «In Jira anlegen» aus einer Idee → Jira-Ticket, Teilschritte am Ticket, Verlauf «Ticket aus Idee»
- [ ] `r20-07` Einstellungen → IntelliJ: Pfad zum lokalen Checkout eintragen, Befehl prüfen → gespeichert
- [ ] `r20-08` MR bei «Testen» → «In IntelliJ öffnen» → IntelliJ startet mit `../.tinyops-wt/<repo>-mr<nr>-<sha>` auf genau dem Commit des MR (`git log -1`)
- [ ] `r20-09` Danach «Getestet» → Abnahme zeigt den SHA des Worktrees
- [ ] `r20-10` Neuen Commit auf den MR pushen, neu laden → Chip «IntelliJ … (veraltet)», nächster Schritt sagt «neu öffnen»
- [ ] `r20-11` Im Worktree eine Datei ändern, × am Chip → Rückfrage wegen geänderter Dateien
- [ ] `r20-12` Vorhaben auf «Fertig» → saubere Worktrees sind weg (`git worktree list`)
- [ ] `r20-13` MR mit Review-App (Environment `review/<branch-slug>`) → «Review-App» im Panel und beim Testen öffnet die URL

## 0.21.0

- [ ] `r21-01` Remote auf das Repo umstellen (`git remote set-url origin …`), `git checkout --detach v0.20.0`, dann `python3 start.py` → «Aktualisiert: v0.20.0 → v0.21.0», Selbsttest läuft, tinyops startet
- [ ] `r21-02` Im Panel → Hinweis «Aktualisiert auf v0.21.0» mit neuen Prüfpunkten, «Was ist neu?» zeigt den CHANGELOG, × blendet ihn aus
- [ ] `r21-03` Nochmals `python3 start.py --check` → «Auf dem neuesten Stand»
- [ ] `r21-04` Eine Datei im Checkout ändern, `python3 start.py` → «Geänderte Dateien … kein Update», tinyops startet trotzdem
- [ ] `r21-05` VPN/Netz aus, `python3 start.py` → «Nicht erreichbar … Start mit dem, was da ist»
- [ ] `r21-06` Windows (falls genutzt): Doppelklick auf `start.cmd` → wie unter Linux

## 0.21.1

- [ ] `r211-01` GitHub → Actions → «Tests» nach dem Push → grün
- [ ] `r211-02` GitHub → Releases → v0.21.1 → vier Launcher und der CHANGELOG-Abschnitt sind da
- [ ] `r211-03` Launcher für dein System herunterladen und starten (ohne bestehende Installation) → lädt nach `~/.local/share/tinyops/app` bzw. `%LOCALAPPDATA%\tinyops\app`, Browser geht auf
- [ ] `r211-04` Launcher mit `--where` → zeigt Ordner, Repo `AdBuch/tinyops`, Version v0.21.1 und dein Python
- [ ] `r211-05` Windows: SmartScreen-Warnung → «Weitere Informationen → Trotzdem ausführen» startet ihn
- [ ] `r211-06` `python3 tinyops-launcher.pyz --demo` → wie der Launcher, mit Demo-Daten

## 0.25.0

- [ ] `r25-01` Einstellungen → Workspaces: deinen Projektordner eintragen (z. B. `~/work`), speichern → «Durchsucht wird» nennt ihn
- [ ] `r25-02` Tab «Workspaces» → deine Repos erscheinen, auch die in Unterordnern; jedes zeigt GitLab, GitHub, anderer Host oder kein Remote
- [ ] `r25-03` In einem Repo einen Commit machen, nicht pushen, «Neu einlesen» → «1 Commit nicht gepusht», das Repo steht oben
- [ ] `r25-04` Eine Datei ändern und einen Stash anlegen → «Dateien offen» und «1 Stash» in der Zeile
- [ ] `r25-05` Repo aufklappen → Branches mit Upstream, voraus/hinter; «push-Befehl» kopieren und im Terminal ausführen → nach «Neu einlesen» ist das Repo sauber
- [ ] `r25-06` Ein Repo, das nicht in tinyops eingerichtet ist → «nicht in tinyops», Filter «Nicht in tinyops» zeigt es, kein «Agent zuweisen»
- [ ] `r25-07` Ein Projektordner ohne Git (z. B. mit `package.json`) → steht unter «Projekte ohne Git»
- [ ] `r25-08` «Abholen» bei einem Repo → Meldung «abgeholt», dein Arbeitsverzeichnis und deine Branches sind unverändert (`git status`)
- [ ] `r25-09` Eingerichtetes Projekt: «Agent zuweisen», Satz eingeben, «Weiter zum Auftrag» → Auftragsdialog mit Prompt; nach dem Start erscheint der Worktree des Agenten im Repo
- [ ] `r25-10` Fokus → Seitenleiste «Nicht gepusht» nennt die Repos; die Zahl am Tab zählt nur Repos über dem Meldealter
- [ ] `r25-11` Projekt mit `restricted`: im Agenten-Menü sind Cloud-Agenten ausgegraut

## 0.24.0

- [ ] `r24-01` Fokus: bei einem Helpdesk-Ticket «Ticket ansehen» → Details öffnen sich im Panel mit Beschreibung und Kommentaren, kein neuer Tab
- [ ] `r24-02` Im Panel «Als Fokus anheften, Zeit starten» → Fokus-Leiste unter der Kopfzeile zeigt das Ticket und «Zeit läuft, ohne Zeitbox»
- [ ] `r24-03` Gruppe «Ich beobachte» → deine beobachteten Tickets, geänderte fett; eines anklicken → lesbar im Panel, danach nicht mehr fett
- [ ] `r24-04` «Alle gesehen» bei «Ich beobachte» → nichts mehr fett; die Queue bleibt unverändert
- [ ] `r24-05` Einstellungen → Helpdesk: Vorschlag unter «Queue» anklicken → Abfrage steht im Feld; «Verbindung testen» zeigt die Schritte «Queue» und «Ich beobachte»
- [ ] `r24-06` Fokus-Sitzung starten, «Klein machen» → breite Leiste mit Aufgabe, Restzeit und Fortschritt; sie bleibt in Board, Zeit und Einstellungen sichtbar
- [ ] `r24-07` Klick auf die Leiste → Fokus-Modus öffnet sich wieder
- [ ] `r24-08` Während eines festen Blocks ohne Sitzung → Leiste «Jetzt wäre: …-Block bis …» mit «Block starten»
- [ ] `r24-09` Details offen, neben das Panel ins Leere klicken → Panel schliesst sich
- [ ] `r24-10` Nach einem Tag Nutzung den Bericht kopieren → tote Klicks nennen den Ort (z. B. «/ rcard.score»)

## 0.23.0

- [ ] `r23-01` Einstellungen → Helpdesk: Adresse, «basic», Benutzername und Passwort eintragen → «Verbindung testen» zeigt Jira 8.5.1, «Angemeldet als …» und die Anzahl deiner Tickets
- [ ] `r23-02` Speichern → im Fokus erscheint eine Gruppe mit deinen Helpdesk-Tickets; ein Ticket über dem SLA steht oben und zeigt «seit … h» rot
- [ ] `r23-03` Queue-JQL eintragen, speichern → «Queue …» zeigt neue Tickets fett; «Alle gesehen» → nichts mehr fett, nach dem nächsten Abgleich nur wirklich neue
- [ ] `r23-04` Ein Helpdesk-Ticket öffnen → «Als Fokus anheften» → Hero zeigt das Ticket, «Zeit läuft»; Tab «Zeit» zeigt einen Abschnitt auf das Helpdesk-Ticket
- [ ] `r23-05` Einstellungen → Fokusbereiche: bei Berufsbildung einen Block für jetzt eintragen, speichern → über dem Fokus erscheint das Band «Berufsbildung-Block bis …»
- [ ] `r23-06` Seitenleiste «Fokuszeit diese Woche» → Berufsbildung mit Ziel, Strich «Soll bis jetzt» und «… h hinter Plan»
- [ ] `r23-07` «Berufsbildung-Block starten» → Tätigkeit «Betreuung Lernende», 25 min → Vollbild mit Uhr, Aufgabe und Tätigkeit; die Tasten j/k/i tun nichts
- [ ] `r23-08` Im Fokus-Modus einen Gedanken eintippen, Enter → «Geparkt in der Ideenbox», das Feld ist leer und behält den Cursor
- [ ] `r23-09` Tätigkeit wechseln, dann «Klein machen» (oder Esc) → die Uhr läuft in der Kopfzeile weiter; Klick darauf öffnet den Fokus-Modus wieder
- [ ] `r23-10` «Erledigt» nach mehr als 20 Minuten → Meldung mit +15 XP; Tab «Zeit» → der Entwurf für Berufsbildung nennt die Tätigkeiten im Text
- [ ] `r23-11` Fokusbereiche: Ziele über 100 % oder einen Block wie «Mo 9-10» speichern → verständliche Fehlermeldung am Feld
- [ ] `r23-12` Log → Verlauf → «Fokus-Sitzung gestartet» und «beendet» mit Bereich, Minuten und Ergebnis

## 0.22.0

- [ ] `r22-01` KI-Kontingent aufklappen → jeder Balken hat einen senkrechten Strich (Zeit übrig), darunter eine Tempo-Zeile
- [ ] `r22-02` Kurz nach einem 5-h-Reset mit wenig Verbrauch → «Vorsprung … verfallen etwa …»; mitten in einer intensiven Sitzung → «Zu schnell … leer in …»
- [ ] `r22-03` Chips in der Kopfzeile → kleiner Balken mit Strich, Tooltip nennt «% der Zeit übrig»
- [ ] `r22-04` Einige Minuten normal arbeiten, dann Tab «Prüfen» → «UI-Nutzung» zeigt Sitzungen, aktive Minuten und Ereignisse
- [ ] `r22-05` «Bericht kopieren» und einfügen → keine Ticket-Titel, kein eingetippter Text, aber Aktionen, Ansichten und Maus-Verteilung
- [ ] `r22-06` Drei Mal schnell auf etwas nicht Klickbares klicken, Bericht neu kopieren → «tote Klicks» und «Wutklick» erscheinen
- [ ] `r22-07` Einstellungen → Weiteres → «UI-Nutzung lokal erfassen» aus, speichern → keine neuen Ereignisse mehr; «Daten löschen» leert den Bericht

