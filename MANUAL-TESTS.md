# Manuelle Tests gegen dein echtes Jira, GitLab und Modell

Bisher lief alles gegen Mock-Server. Diese Liste zeigt, was nur du prüfen kannst. Reihenfolge von oben nach unten, jeder
Block baut auf dem vorigen auf. Bei einem Fehler: Log-Ausschnitt (er ist von Secrets bereinigt) und die Zeile dieser Liste
zurückmelden, mehr brauche ich nicht.

## 0. Lokal starten (IntelliJ)

1. Projektordner `tinyops` öffnen. Unter *Run* erscheinen die Konfigurationen aus `.run/` automatisch
   (falls nicht: *Settings → Build, Execution, Deployment → Run/Debug* und Ordner `.run` prüfen).
   Braucht das Python-Plugin und einen Python-3.10+-Interpreter (*Project Structure → SDK*).
2. **tinyops - Demo** starten, `http://localhost:8765` öffnen: Kacheln, Board und Sync-Leiste sollten mit Demo-Daten laufen.
3. **tinyops - Echt (dev-Config)** starten. Config, Datenbank und Logs liegen in `.dev/` im Projekt (nicht in deinem echten
   `~/.config/tinyops`, nicht im Git). Beim ersten Start führt die Seite «Einstellungen» durch GitLab, Projekte, Jira.
4. **tinyops - Preflight** laufen lassen. Ziel: `Alles bereit.` Jeder Fehler nennt den Grund und einen Hinweis.

Wenn der Preflight grün ist, ist die Verbindung belegt. Alles Weitere sind Fachtests.

## 1. Jira (Version 9.4.14)

| # | Prüfen | Erwartet |
|---|--------|----------|
| 1.1 | Preflight, Block «Jira» | Anmeldung, Projekte, Vorgangstypen, JQL ok. Sprint-Feld wird gefunden (sonst Hinweis) |
| 1.2 | Kachel «Stories in Arbeit» | Nur Tickets aus **aktiven** Sprints (JQL `sprint in openSprints()`); Sprintname und «noch n Tage» stimmen mit Jira überein |
| 1.3 | Ein Ticket aus einem **geschlossenen/künftigen** Sprint, das «In Arbeit» ist | Erscheint nicht (mit Schalter «alle Sprints» in den Einstellungen schon) |
| 1.4 | Limit | Mehr als 2 Stories in Arbeit: Zähler rot, Hinweis «Limit überschritten» |
| 1.5 | Branch/MR mit Ticket-Key im Namen | Chip `Jira DLP-123 · Status` auf der Zeile, Story zeigt den MR |
| 1.6 | Branch **ohne** Key | Chip «ohne Ticket», Knopf «Ticket anlegen» |

**Besonders prüfen:** das Format des Sprint-Felds (Jira liefert es je nach Version als Text oder Objekt). Falls 1.2 den
Sprintnamen leer zeigt, schick mir aus dem Log (`.dev/logs`, Stufe debug) die Zeile mit «Sprint».

## 2. GitLab (19.2.5-ee)

| # | Prüfen | Erwartet |
|---|--------|----------|
| 2.1 | Preflight, Block «GitLab» | Token-Rechte `read_api`, Projekte gefunden |
| 2.2 | «Meine MRs» | Genau deine offenen MRs, mit Pipelinestatus und Draft-Markierung |
| 2.3 | «Braucht dich» | Review-Queue und dir zugeteilte MRs; fehlgeschlagene Pipeline eigener MRs |
| 2.4 | «Offene Branches» | Branches mit Commits von dir oder deinem Agenten, **ohne** `release/*` |
| 2.5 | Agent-Branch (Co-Authored-By: Claude) | Chip «Agent» |
| 2.6 | Projekt mit sehr vielen Branches | Lädt in vernünftiger Zeit; Sync-Leiste zeigt, welches Projekt läuft |

## 3. Sync und Fehlerfälle

1. «Neu laden»: Leiste zeigt Schritte mit Dauer, alte Daten bleiben stehen bis alles neu ist.
2. Falschen GitLab-Token setzen (Einstellungen), speichern: Banner mit klarer Meldung, kein Absturz; Token zurücksetzen.
3. VPN trennen und «Neu laden»: Fehlermeldung nennt den Grund (DNS/Timeout), das Panel bleibt bedienbar.

## 4. Board, Kategorien, Ideen

1. Aufgabe ohne Jira anlegen (Spalte Ideenpool): braucht keine Kategorie. In «Geplant» schieben: verlangt eine Kategorie.
2. Kategorie «Agenten-VM» anlegen, Aufgabe zuordnen, nach «Umsetzung» schieben: erscheint im Jira-Panel (zählt fürs Limit).
3. Eine Jira-Story mit **zwei** MRs/Branches: eine Karte, beide Chips. Chip auf eine andere Karte ziehen verknüpft neu.
4. Idee in der Ideenbox erfassen, im Board «Planen» ohne Kategorie: Hinweis; mit Kategorie: Aufgabe in «Geplant».
5. Panel neu starten: Board, Kategorien, Ideen, Verknüpfungen sind noch da.

## 5. Ticket anlegen und KI-Entwurf (nur mit Absicht einschalten)

Schreibt in Jira. **Nur in einem Testprojekt.**

1. Einstellungen → Jira: «Tickets anlegen erlauben» an, Vorgangstyp prüfen. «Ticket anlegen» bei einem Branch ohne Key.
2. Ohne KI: Vorlage aus Branch, MR-Beschreibung und Commit-Titeln, bearbeiten, anlegen. Das Ticket erscheint in Jira und der
   Branch ist danach verknüpft.
3. KI (Modell 10.0.0.12): Einstellungen → KI-Entwurf → «Verbindung testen». Danach «Entwurf mit KI». Bei Timeout
   den Wert «Timeout» erhöhen; das Log (`llm`) zeigt Anfrage, erste Antwort und Dauer.
4. Prüfen, dass nur Titel, Branch, MR-Beschreibung und Commit-Titel gesendet werden (Log, Stufe debug), kein Code, keine Diffs.

## 6. Sicherheit (Stichproben)

- `grep SCHREIBEN .dev/logs/*.log`: leer, solange du kein Ticket angelegt hast. Nach dem Anlegen genau eine Zeile.
- Kein Secret im Log: `grep -i -E "glpat|token=|bearer " .dev/logs/*.log` bleibt leer.
- `.dev/config.json` enthält keine Tokens; `ls -l .dev/` zeigt Rechte 600 für Config (und `secrets.json`, falls ohne Schlüsselbund).
- Mit Zugriffstoken (Kubernetes): Seite ohne `?token=` gibt 401, mit fremdem Host-Header 403.

## 7. Kubernetes

Einmalig: `deploy/deploy.example.json` nach `deploy/deploy.local.json` kopieren und Registry, Namespace, Kontext eintragen.
`deploy/k8s/config.seed.json` anpassen (GitLab- und Jira-Adresse, Projekt-Keys). Dann in dieser Reihenfolge die Run-Konfigurationen
**k8s - 1 Secret anlegen**, **k8s - 2 Release**, **k8s - 3 Panel öffnen** (oder auf der Befehlszeile `python deploy/k8s.py secret|release|forward --open`).

| # | Prüfen | Erwartet |
|---|--------|----------|
| 7.1 | Secret anlegen | Fragt GitLab-Token (und optional Jira-Token) verdeckt ab, erzeugt den Zugriffstoken |
| 7.2 | Release | Tests grün, Image gebaut und hochgeladen, `rollout status` meldet fertig |
| 7.3 | Panel öffnen | Browser zeigt das Panel (nach dem Tausch von `?token=` gegen ein Cookie) |
| 7.4 | **k8s - Preflight im Pod** | Dieselben Prüfungen wie lokal, aber aus dem Cluster: zeigt, ob der Pod GitLab/Jira/Modell erreicht |
| 7.5 | Pod löschen (`kubectl delete pod -l app=tinyops`) | Neuer Pod startet, Ideen, Board und Einstellungen sind noch da (Volume) |
| 7.6 | Zweites Release nach einer Codeänderung | Neuer Tag, Pod wird ersetzt (kurze Pause, da `Recreate`), Daten bleiben |
| 7.7 | Secret ändern (Run-Konfiguration 1) und `kubectl rollout restart deployment/tinyops` | Neuer Wert gilt, alte Werte bleiben, wenn du sie nicht neu eingibst |

Typische Fehler: `ImagePullBackOff` (Cluster hat keinen Zugang zur Registry: `imagePullSecrets` am Deployment ergänzen),
`Pending` (keine StorageClass fürs Volume: `storageClassName` in `deploy/k8s/pvc.yaml`), Preflight im Pod meldet
Timeout/DNS (Egress-Regeln oder interne Namen; `deploy/k8s/networkpolicy.optional.yaml` nur nach Anpassung einspielen).

## 8. Sonar, KI-Kontingent, Mistral-Lesezeichen (ab 0.7.0)

| # | Prüfen | Erwartet |
|---|--------|----------|
| 8.1 | Einstellungen → Sonar: Adresse, Token, je Projekt Sonar-Schlüssel, «Verbindung testen» | Schritte grün; falsche Schlüssel werden mit Namen gemeldet |
| 8.2 | Übersicht nach dem Speichern | Chips «Gate grün/rot/Warnung» an MRs und Branches; rotes Gate steht unter «Braucht dich» |
| 8.3 | «Sonar» und «Findings» anklicken | Dashboard bzw. offene Findings des MR/Branches in Sonar (nicht das Hauptprojekt) |
| 8.4 | «Report kopieren» an einem MR mit Findings, dann in einen Texteditor einfügen | Markdown mit Bedingungen, Zählern, Findings je Datei; keine Codezeilen; Zahlen passen zu Sonar |
| 8.5 | Report an einem Branch ohne Analyse | Kein Knopf (nur bei Gate vorhanden); bei Community Edition «keine Analyse» für MRs ist normal |
| 8.6 | Einstellungen → KI-Kontingent: Claude lesen, speichern, «Jetzt abfragen» | Prozent frei im 5-h- und Wochenfenster, Reset; bei Fehler ein klarer Grund (Datei, abgelaufen, HTTP-Code) |
| 8.7 | Dasselbe mit Codex | Ebenso; nur mit ChatGPT-Anmeldung (`codex login`), nicht mit reinem API-Schlüssel |
| 8.8 | Mistral anzeigen ankreuzen, speichern, Lesezeichen in die Leiste ziehen, auf `admin.mistral.ai` anklicken | Neuer Tab mit tinyops, Meldung «Mistral-Stand übernommen», Kachel zeigt Vibe und API Monat mit Dollar-Werten wie auf der Mistral-Seite |
| 8.9 | Lesezeichen auf einer anderen Seite anklicken | Hinweis, erst admin.mistral.ai zu öffnen; nichts wird gesendet |
| 8.10 | Übersicht neu laden (F5) | Box «KI-Kontingent» unter der Ideenbox ist zu und zeigt nur die Zeile mit Prozentwerten; Klick öffnet sie |
| 8.11 | An einem Branch ohne MR «MR erstellen» | GitLab öffnet das Formular für einen neuen MR mit dem Branch als Quelle |
| 8.12 | Panel 10 Minuten offen lassen (Log auf DEBUG) | GitLab/Jira werden höchstens alle 5 Minuten abgefragt, nicht jede Minute |
| 8.13 | Sonar «Verbindung testen» mit Projektschlüssel | Schritt «Pull-Request-Analyse» nennt die Zahl analysierter PRs und den letzten (`!N`); bei Community Edition eine Warnung |
| 8.14 | MR mit mindestens zwei Analysen in Sonar | Kurve und ▼/▲ neben dem Gate; Tooltip nennt Anfang, Ende, Datum und Quelle «Sonar-Verlauf» (stimmt mit Sonar überein?) |
| 8.15 | Report an einem solchen MR | Abschnitt «Verlauf» mit Tabelle; Schwere heisst hoch/mittel/gering (Auswirkung), nicht blocker/major |

## 9. Coding-Agenten (ab 0.12.0)

| # | Prüfen | Erwartet |
|---|--------|----------|
| 9.1 | Verbindung zum Entwicklungsrechner anlegen, Agent mit Arbeitsordner, «Testen» | Vier grüne Schritte; ohne bekannten Host-Schlüssel die Meldung mit dem Hinweis `ssh <rechner>` |
| 9.2 | Test mit falschem Benutzer oder Schlüssel | «Anmeldung abgelehnt», keine Passwortabfrage im Terminal von tinyops |
| 9.3 | Projekt ohne «Cloud-Agent erlaubt»: Claude-Agent zuweisen | Rote Meldung im Dialog, «Zuweisen & starten» gesperrt; auf dem Zielhost startet nichts |
| 9.4 | Freigabe ankreuzen, Karte zuweisen und starten | Chip «läuft»; auf dem Zielhost `tmux ls` zeigt `tinyops-<Nr>`; das Repository liegt unter Arbeitsordner/Projektname |
| 9.5 | Log im Dialog, dann den kopierten `ssh -t … tmux attach`-Befehl im Terminal | Gleiche Ausgabe; Mitlesen und Eingreifen geht; Trennen (Strg-b d) lässt den Lauf weiterlaufen |
| 9.6 | tinyops neu starten, während der Agent läuft | Chip bleibt «läuft», danach «fertig» mit dem richtigen Exit-Code |
| 9.7 | «Stoppen» | Chip «abgebrochen», Sitzung weg |
| 9.8 | Der echte Claude-Aufruf: Nimmt `claude -p "<Prompt>"` den Prompt wie erwartet, arbeitet er im Repository, legt er den Branch an? | Genau das, sonst «Zusätzliche Argumente» oder `custom` mit eigenem Befehl nutzen (Rückmeldung bitte mit Fehlermeldung des Agenten) |
| 9.9 | Dasselbe mit Codex (`codex exec`) und Vibe (`vibe -p`) | Die Aufrufe sind aus der Dokumentation abgeleitet, nicht getestet: Abweichungen melden |
| 9.10 | Lokaler Agent (Windows und Linux) | Läuft losgelöst weiter, wenn tinyops beendet wird; «Stoppen» beendet den Prozessbaum |

## 10. Fokus und Ablauf (ab 0.13.0)

| # | Prüfen | Erwartet |
|---|--------|----------|
| 10.1 | Panel öffnen | Startet in «Fokus»; oben «Jetzt dran» mit einer Aufgabe, gross der nächste Schritt und ein Knopf |
| 10.2 | Je ein Vorhaben mit: nur Ticket, Branch ohne MR, Draft-MR, MR mit roter Pipeline, MR grün | Stationen Branch, Code, MR, Prüfen (rot), Testen; passende Knöpfe |
| 10.3 | MR mit offenen Diskussionen, ohne Freigabe, mit Konflikt (GitLab 19.2) | «Kommentare klären», «Review abwarten» (unter «Läuft gerade»), «Konflikt lösen» |
| 10.4 | «Getestet» an einem grünen MR, dann in GitLab mergen, Panel neu laden | Station Mergen, danach «Abschliessen»; Klick setzt Fertig, die Feier erscheint einmal |
| 10.5 | Teilschritte anlegen und abhaken | Erster offener Haken ist der nächste Schritt; Ring zählt mit; ab- und wieder anhaken zählt nicht doppelt |
| 10.6 | Board | Karten stehen in derselben Spalte wie die Station in Fokus; Klick öffnet das Panel |
| 10.7 | Einstellungen lang scrollen | Kopfzeile und linke Navigation bleiben stehen; die Navigation markiert den Abschnitt |
| 10.8 | Sonar mit Projekt-Analyse-Token | Meldung «keine Berechtigung (HTTP 403) … User-Token» statt «Anmeldung abgelehnt» |
| 10.9 | Tastatur: j, k, Enter, a, n, Esc | Auswahl springt, Panel öffnet und schliesst, «a» führt den Schritt der Zeile aus |

## 11. GitHub, Reviews, Ticketpflicht (ab 0.14.0)

| # | Prüfen | Erwartet |
|---|--------|----------|
| 11.1 | Feingranularer Token (nur Lesen), Einstellungen → GitHub, «Verbindung testen» | Anmeldung, Anfragelimit, Repos grün; ein klassischer Token mit `repo` gibt eine Warnung |
| 11.2 | Repo suchen und hinzufügen, einschalten, speichern | Eigene PRs und Branches erscheinen mit Quelle «GitHub», «PR #N», Checks als Pipeline-Punkt |
| 11.3 | PR, in dem du als Reviewer angefragt bist | Unter «Andere warten auf dich» mit «Review öffnen» |
| 11.4 | Eigener GitLab-MR ohne Reviewer | «Reviewer zuweisen»; nach dem Zuweisen «Review abwarten» mit dem Namen |
| 11.5 | Reviewer gibt 👍 oder Approve | Weiter zu «Manuell testen»; Panel zeigt Daumen bzw. Freigabe mit Namen |
| 11.6 | Projekt mit Approval-Regel (z. B. 1 Freigabe nötig), nur 👍 | Bleibt bei «Review abwarten», Panel zeigt «noch 1 Freigabe» |
| 11.7 | Branch ohne Key im Namen | «Ticket zuordnen» (rot); «tiny-Ticket anlegen» erzeugt LOC-N in der Kategorie des Projekts, der Branch hängt daran |
| 11.8 | ✓ «Schritt erledigt» an einem Ticket in «Testen» | Station «Mergen», XP-Meldung; im Panel «Automatisch» setzt es zurück |
| 11.9 | Log auf DEBUG während eines Abgleichs | Nur GET-Anfragen an GitHub und an `…/approvals` in GitLab |

## 12. Abnahme, Unbekannt, Zeitlimit, Fokus (ab 0.15.0)

| # | Prüfen | Erwartet |
|---|--------|----------|
| 12.1 | MR grün und freigegeben, im Panel Notiz eintragen, «Getestet» | Station Mergen; Panel zeigt «MR !N auf <sha>», Zeit, Notiz |
| 12.2 | Danach einen Commit auf den Branch pushen, «Neu laden» | «Erneut testen», «getestet <alt>, jetzt <neu>», Flag «Abnahme veraltet» |
| 12.3 | Vorhaben, das vor 0.15 auf «Getestet» stand | einmal «Erneut testen» mit «ohne Bezug auf einen Commit» |
| 12.4 | Einstellungen → GitLab → Verbindung testen | Schritt «Review-Felder» grün; sonst Warnung mit fehlenden Feldern |
| 12.5 | Projekt, dessen Freigaben dein Token nicht lesen darf | «Freigabe prüfen» statt «Manuell testen» |
| 12.6 | VPN trennen, «Neu laden» | Fokus-Kopf: «GitLab: Fehler, Stand vor X min»; Einträge bleiben, markiert «veraltet» |
| 12.7 | Agent mit Zeitlimit 1 min und einer langen Aufgabe starten, Panel schliessen | Nach gut einer Minute (Wächter alle 30 s) «abgelaufen», auf dem Zielhost keine Prozesse und keine tmux-Sitzung mehr |
| 12.8 | «Als Fokus anheften», dann eine rote Pipeline an einem anderen MR | «Jetzt dran» bleibt beim Fokus; Hinweis «1 Blocker anderswo» öffnet den Blocker |

## 13. Datenklassen, Worktree, Export (ab 0.16.0)

| # | Prüfen | Erwartet |
|---|--------|----------|
| 13.1 | Projekt auf restricted, Claude-Agent zuweisen | In der Auswahl ausgegraut; per API 400 «restricted: nur lokale Agenten» |
| 13.2 | Goose mit Ollama-Modell auf dem Agent-Host, Agenten-Test | Schritte grün, «Rechte» ohne Warnung beim eigenen Agent-Benutzer |
| 13.3 | Goose-Lauf auf einem restricted-Projekt | läuft in `.tinyops-wt/<Nr>` auf `agent/<key>-<nr>`, dein Checkout unverändert (`git status` leer) |
| 13.4 | Der echte Goose-Aufruf (`goose run -i`, `GOOSE_PROVIDER/GOOSE_MODEL`) | Goose liest den Prompt und arbeitet; sonst Fehlermeldung zurückmelden |
| 13.5 | opencode (`opencode run --model ollama/<modell>`) | wie 13.4 |
| 13.6 | Zwei Läufe im selben Repo gleichzeitig | beide laufen, getrennte Worktrees |
| 13.7 | «Entfernen» nach einem Lauf mit offenen Änderungen | Commit «offener Stand gesichert» auf dem Agenten-Branch, Worktree weg |
| 13.8 | internal mit Cloud-Pfad `src/…/util`, Claude-Lauf «Unit-Tests schreiben» | Export enthält nur diese Pfade; `git log` dort hat einen Commit; «Übernehmen» legt `agent/<key>-<nr>` an |
| 13.9 | Agent ändert eine Datei ausserhalb der Pfade | «Übernehmen» lehnt ab und nennt die Datei; nichts im Repo |

## 14. Verlauf und Audit (ab 0.17.0)

| # | Prüfen | Erwartet |
|---|--------|----------|
| 14.1 | Bei einem Vorhaben «Schritt erledigt», dann das Detail-Panel öffnen | Unter «Verlauf» genau ein Eintrag «Schritt erledigt» mit Zielstation |
| 14.2 | Abnahme mit Notiz und Umgebung | Eintrag «Abgenommen» mit `ref@sha`, Notiz und Umgebung |
| 14.3 | Agent zuweisen und starten | Zwei Einträge; beim Start Datenklasse, Ort, Modus und `Prompt: sha256:…`, nicht der Prompt-Text |
| 14.4 | Claude-Agent auf ein restricted-Projekt zuweisen | Fehler-Eintrag (✕) «Agent zugewiesen» mit «restricted» |
| 14.5 | Einstellungen mit neuem Token speichern | Eintrag mit geänderten Bereichen und Token-Namen, kein Wert |
| 14.6 | Ticket in Jira anlegen, dann sofort denselben Titel nochmals | Rückfrage nennt das erste Ticket; «Abbrechen» legt nichts an |
| 14.7 | Log → Verlauf → «Kette prüfen» | «Kette in Ordnung», Anzahl und letzter Hash |
| 14.8 | Server stoppen, in `tinyops.db` mit `sqlite3` die Trigger löschen und einen Eintrag ändern, dann `python3 server.py --verify-audit` | «GEBROCHEN bei Eintrag …», Exit-Code 1 |
| 14.9 | «Export (JSON)» | Datei `tinyops-audit-<Datum>.json` mit allen Einträgen und dem Prüfergebnis |
| 14.10 | `agent_log_days` auf 1, einen Tag warten (oder Datei-Zeit zurücksetzen und Server neu starten) | Alte Dateien in `~/.tinyops/runs` (SSH-Ziel) und lokal weg, Eintrag «Alte Agenten-Logs gelöscht» |

## 15. Rückfragen, Bericht, Review-Punkte (ab 0.18.0)

| # | Prüfen | Erwartet |
|---|--------|----------|
| 15.1 | Eigener Befehl: `ans=$(tinyops-ask "Weiter?" ja nein); echo $ans` | «Agent fragt» unter «Du bist dran»; nach «ja» steht `ja` im Log, der Lauf endet «fertig» |
| 15.2 | Claude Code oder Codex mit dem Standard-Prompt auf einer unklaren Aufgabe | Der Agent ruft `tinyops-ask` auf (oder nicht: zurückmelden). Bei Exit 3 ruft er `--wait` auf, statt neu zu fragen |
| 15.3 | Goose mit Ollama: Aufgabe mit Tests | Im Ergebnis stehen Belege von `tinyops-check` und ein Bericht |
| 15.4 | Frage offen lassen bis zum Zeitlimit | Status «abgelaufen», Hinweis «Eine Frage war noch offen» |
| 15.5 | Eigener MR mit offenen Threads, «Offene Punkte» | Nur offene, auflösbare Threads; Datei:Zeile stimmen mit GitLab überein; erledigte fehlen |
| 15.6 | Thread auf einem älteren Commit (nach neuem Push) | Chip «älterer Stand» |
| 15.7 | «Als Prompt kopieren» und in einen Chat einfügen | Markdown mit Zielangaben, Kommentare als Zitat |
| 15.8 | «JSON» | Datei `review-mr<nr>-<datum>.json`, Schema `tinyops.review-topics/1` |
| 15.9 | internal-Projekt mit Cloud-Pfaden, Claude beauftragen | Punkte ausserhalb der Pfade fehlen im Prompt, der Dialog nennt sie |
| 15.10 | GitHub-PR mit Review-Kommentaren | Threads mit Antworten, «Status?», kein Code aus dem Diff im JSON |
| 15.11 | Log → Verlauf | Einträge «Review-Punkte exportiert», «Agent fragt», «Agent geantwortet» |

## Rückmeldung

Pro Zeile reicht: **ok**, **Abweichung** (was du gesehen hast) oder **nicht getestet**. Bei Abweichungen zusätzlich die
Log-Zeilen. Kein Token, keine Kundendaten mitschicken (die Logs enthalten Ticket- und Branchnamen, prüf sie vorher).
