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
