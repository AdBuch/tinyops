# Changelog

Semantic Versioning: **minor** (0.x.0) für neue Funktionen, **patch** (0.x.y) für Korrekturen und Fixes.
Solange die Hauptversion 0 ist, kann sich auch bei einer minor-Version noch etwas Grundsätzliches ändern.
Die Version steht in `server.py` (`VERSION`), im Git-Tag `vX.Y.Z`, im Docker-Tag und oben rechts im Panel.
Die frühere Zählung (1.0 bis 2.6) endet hier; **0.7.0 ist der neue Anfang** und enthält alles davon.

## [0.44.0]

Eingebautes Whisper, auf deinen Wunsch: Spracherkennung ohne eigenen Server und ohne Grafikkarte, eingerichtet von tinyops.

### Neu
- **Einstellungen → Sprache → «Eingebaut»** (neuer Standard): ein Klick «Einrichten», und tinyops
  1. holt whisper.cpp in einer festen Version (v1.9.5, `git clone`, nur lesend) und baut `whisper-server` mit cmake für genau deinen Prozessor (AVX2/AVX-512 werden genutzt). Das dauert einmal ein bis fünf Minuten; danach bleibt nur das Programm (etwa 4 MB), der Quelltext wird gelöscht.
  2. lädt das Modell von Hugging Face und prüft es gegen die SHA1 aus der Modellkarte. Stimmt sie nicht, wird es nicht benutzt.
  3. startet den Server beim ersten Diktieren selbst, nur auf 127.0.0.1, und beendet ihn nach 20 Minuten ohne Nutzung und wenn tinyops endet.
- **Modelle:** «small» (181 MB, Standard, gut für Deutsch), «base» (57 MB, für schwache Rechner), «turbo» (547 MB, am genauesten, auf dem Prozessor langsamer). Wechseln lädt nur das neue Modell.
- Fortschritt, Ausgabe des Bauens und «Erkennung testen» stehen im Abschnitt. «Entfernen» löscht Programm und Modelle.
- Fehlen cmake oder ein C++-Compiler, sagt tinyops, wie du sie einmal installierst (Ubuntu: `sudo apt install build-essential cmake git`). tinyops selbst nutzt nie sudo.
- Liegt schon ein `whisper-server` im PATH oder trägst du eines ein (Fortgeschritten), baut tinyops nichts.
- «Aufrufe nach aussen» nennt das Holen des Quelltexts und des Modells; beides passiert nur auf «Einrichten».

### Grenzen
- Hier geprüft: echtes Holen und Bauen von whisper.cpp v1.9.5 unter Linux und Erkennung mit dessen kleinem Testmodell. Die Modelle von Hugging Face konnte ich hier nicht laden; ihre Prüfsummen stammen aus der Modellkarte.
- Unter Windows braucht das Bauen Visual Studio Build Tools und CMake, das habe ich nicht geprüft. Einfacher dort: ein fertiges `whisper-server.exe` als Programm eintragen.
- Ein Modell braucht im Speicher etwa so viel wie die Datei, «small» also rund 300 MB, solange der Server läuft.

## [0.43.0]

Voice Prompting Wednesday, auf deinen Wunsch: diktieren statt tippen und Agenten per Sprachbefehl beauftragen. Erkannt wird auf einem Server in deinem Netz (dein Wunsch: «gerne lokal»).

### Neu
- **Spracherkennung, lokal** (Einstellungen → Sprache): tinyops spricht mit zwei Arten von Servern.
  - **whisper.cpp-Server** (`whisper-server`, läuft auch ohne Grafikkarte)
  - **OpenAI-kompatibel** (`/v1/audio/transcriptions`): vLLM mit **Voxtral Mini** von Mistral, speaches, faster-whisper-server.
  - Wie beim KI-Entwurf gehen nur Adressen im eigenen Netz, andere nur mit Haken. «Erkennung testen» schickt eine Sekunde Stille und misst die Zeit.
  - Der Browser nimmt auf und schickt WAV (16 kHz, mono). Die Aufnahme wird nirgends gespeichert; im Log stehen nur Länge und Dauer.
- **Diktieren:** In den Prompt-Feldern erscheint oben rechts ein Mikrofon: Auftrag an den Agenten, «Nachricht an …», Freigabe-Notiz, Antwort auf eine Rückfrage, Review-Ziel, Idee, Prüfliste, Ticket-Beschreibung. Klick oder <kbd>Alt</kbd>+<kbd>M</kbd> startet, nochmal beendet, <kbd>Esc</kbd> verwirft. Der Text kommt an die Cursorstelle.
- **Sprachbefehle an Agenten:** Taste <kbd>v</kbd> oder das Mikrofon oben.
  - Zum Beispiel: «DLP-123 an Qwen zum Entwickeln», «DLP-123 an Claude planen, nur zuweisen», «DLP-123 Review mit Qwen», «Review für MR 47 mit Claude».
  - tinyops zeigt, was es verstanden hat: Ticket oder MR, Agent, Rolle, ob gleich gestartet wird. Alles davon ist änderbar. Was nicht erlaubt ist (Cloud-Agent an restricted, kein Worktree, Review ohne fertigen Entwickeln-Lauf), steht mit Grund da, und «Starten» ist gesperrt.
  - Ausgeführt wird erst auf «Starten», über dieselben Wege wie die Knöpfe. «Im Dialog öffnen» bringt den gewohnten Agenten-Dialog oder den Review-Start, vorausgefüllt.
  - Was du gesagt hast, geht wörtlich als «Dein gesprochener Auftrag» an den Agenten. Im Verlauf steht die Aktion (`voice.run`), nicht der Wortlaut.
  - Verstanden wird mit festen Regeln (Ticket-Key, «MR 47», Agentenname, Stichworte für die Rolle, «nur zuweisen»). Nur wenn die kein Ticket finden, fragt tinyops das lokale KI-Modell, falls eingerichtet; auch dann gelten nur Tickets und MRs, die in tinyops stehen.
- Einstellungen → «Aufrufe nach aussen» listet die Spracherkennung.

### Geändert
- Prüfliste: `r28-04` bis `r28-06` und `r29-03`, `r29-04`, `r29-07` sind zu je einem Punkt zusammengelegt, damit es unter 60 Punkten von Hand bleibt.

### Grenzen
- Gegen whisper.cpp und Voxtral selbst habe ich das nicht laufen lassen, nur gegen einen Nachbau ihrer Schnittstellen. Die Aufnahme im Browser ist mit dem Test-Mikrofon von Chromium geprüft.
- Das Mikrofon geht im Browser nur am Rechner (`localhost`) oder über `https`. Auf dem Handy über `http` gibt es kein Mikrofon.
- Ticket-Keys erkennt whisper.cpp meist als «DLP-123» oder «DLP 123»; beides geht. Zahlen in Worten («hundertdreiundzwanzig») versteht tinyops nicht.
- whisper.cpp nimmt die Sprache aus dem Start (`-l de`); die Einstellung «Sprache» schickt tinyops mit, ob dein Server sie beachtet, hängt von seiner Version ab.

## [0.42.1]

Deine Rückmeldung vom 24.11. zu den Reviews: Der Agent liess sich nicht wählen, und ihm fehlte, worum es im MR geht.

### Geändert
- **«▶ Review mit Agent» öffnet zuerst einen kurzen Start** im Detail-Panel, unter «Review mit Agent»:
  - **Agent:** alle Agenten mit Rolle und Kontingent. Wer nicht darf, steht ausgegraut mit Grund da, zum Beispiel «restricted: nur Agenten ohne Cloud» oder «kein eigener Worktree». Vorgewählt ist der zuletzt gewählte.
  - **Ticket:** erkannt aus Branch, Titel und Beschreibung des MR, änderbar. Darunter Titel, Status und wie viele Akzeptanzkriterien es hat. Der Reviewer bekommt Beschreibung und Kriterien und prüft je Kriterium, ob der MR es erfüllt.
  - **Ziel:** ein Satz von dir, worum es geht oder worauf er achten soll. Er geht wörtlich an den Reviewer.
  - Die Beschreibung des MR geht wie bisher mit, jetzt als Daten markiert und mit geschwärzten Geheimnissen. Hat der MR weder Beschreibung noch Ticket, soll der Agent sagen, was er angenommen hat.
- Der Bericht des Reviewers sagt jetzt auch, ob der MR sein Ziel erreicht und welches Kriterium offen ist.

## [0.42.0]

Deine Schwerpunkte vom 20.11.: schneller zum Testen von Hand und Reviews in GitLab, dazu jeder Aufruf nach aussen sichtbar. Und deine Rückmeldung vom 23.11. (Prüfbericht 0.40 ohne Fehler, Nutzungsbericht). Der Plan hatte das auf 0.42 und 0.43 verteilt; es kommt zusammen.

### Neu
- **Testen von Hand im Detail-Panel** (ab der Station «Prüfen»): eine **Prüfliste je Ticket**, zusammengestellt aus dem, was schon da ist:
  - die Akzeptanzkriterien (mit dem, was der Agent dazu gemeldet hat; ohne Agent direkt aus dem Jira-Ticket),
  - die Testschritte von Entwickler und Test-Agent (`tinyops-manual`),
  - ein fester Schlusspunkt «aus Sicht eines Nutzers erreicht», und eigene Punkte.
  - Je Punkt ✓ oder ✗; bei ✗ ein Satz, was nicht ging. Der Stand bleibt, auch nach einem neuen Lauf.
- **«Jetzt testen»**: ein Klick holt genau den Commit des MR (oder den Branch des Agenten) in einen eigenen Worktree, öffnet IntelliJ darauf und startet die Review-Umgebung, wenn eine eingetragen ist. Was ging und was nicht, steht über der Liste. Nur am Rechner, nicht vom gekoppelten Gerät.
- **«↺ N Fehler zurück an …»**: die Punkte mit ✗ und deine Sätze gehen in die Sitzung des Entwicklers (Kreislauf aus 0.40). Danach sind sie wieder offen, mit «zurück an Lauf N».
- **«Alles ok: Getestet»** nimmt am Commit ab, wie bisher, mit der Prüfliste als Notiz. Mit offenen Punkten heisst der Knopf «Trotzdem abnehmen»; mit Fehlern geht es nicht.
- Im Fokus steht **«Wartet auf deinen Test»** über «Du bist dran». «Manuell testen» in der Liste öffnet jetzt die Prüfliste, statt sofort abzunehmen.
- **Review mit Agent (E14)**: «▶ Review mit Agent» an jedem MR unter «Andere warten auf dich» und im Detail-Panel. Ein Klick startet den Reviewer (Agent mit Review-Rolle, eigener Worktree) auf genau dem Commit des MR. Er holt den Stand selbst, ändert nichts und hält jeden Punkt mit Datei, Zeile und Schwere fest (`tinyops-finding`).
  - Die Befunde stehen im Detail-Panel zum Abwählen. **«N als Entwürfe in GitLab»** legt sie als deine Entwürfe am MR an: an der Zeile, wenn sie im Diff liegt, sonst als allgemeiner Entwurf mit Datei und Zeile im Text. Positioniert wird auf dem Stand, den der Agent geprüft hat, auch wenn der MR inzwischen weiter ist.
  - Abschicken machst du in GitLab. tinyops ruft nie `publish`, Approve, Merge oder Threads auflösen auf; erlaubt sind nur die Pfade in `gitlab_review.ALLOWED`, ein Test hält das fest.
  - Ein zweites Mal ersetzt nur die Entwürfe, die tinyops selbst angelegt hat (in der Datenbank vermerkt und unsichtbar markiert). Deine eigenen bleiben.
  - Dafür gibt es das eigene Token **«Token für Review-Entwürfe»** (Einstellungen → GitLab, Scope `api`). Ohne das: «Kopieren».
- **Einstellungen → «Aufrufe nach aussen»**: jeder Aufruf je Dienst mit Methode, Pfad, wozu, wann und welchem Zugang, schreibende markiert, mit Zähler seit dem Start. Die Liste steht in `apicalls.py`; jede Stelle, die eine Verbindung öffnet, zählt dort mit. Ein Test prüft, dass keine daran vorbeigeht und jeder Pfad im Code in der Liste steht. Ein unbekannter Aufruf erscheint rot.

### Geändert
- **Agenten erben keine Zugangsdaten von tinyops mehr**: Umgebungsvariablen wie `TINYOPS_GITLAB_TOKEN` werden für jeden lokalen Lauf entfernt. Vorher hätte ein Agent ein Token gesehen, das du als Umgebungsvariable gesetzt hattest.
- Die Station «Mergen» heisst «In GitLab mergen» und sagt, dass tinyops dort nur liest (zu deinem Wunsch «wenn auf testen und click auf mergen scheint was nicht zu klappen»: ich vermute, das war gemeint; sonst bitte kurz schreiben, was passiert ist).
- BCS-Middleware aus: Nach jedem weiteren Fehlversuch wartet tinyops doppelt so lange, bis 10 Minuten, statt jede Minute 8 s zu warten (Bericht: 28× im Median 8 s).

### Behoben
- Klick neben das Agenten-Seitenpanel (in den Fokus) schliesst es (Bericht: 40 tote Klicks auf den Hintergrund, 27 schnelle Klicks im Agentenfenster). Ungesendeter Text bleibt geschützt.
- Klick auf einen Agenten-Chip öffnet den Agenten der Aufgabe; Chips im Detail-Panel (Draft, Mergestatus, Agent) erklären sich beim Klick.
- Auf dem Handy lag die Abschnittsliste der Einstellungen über dem Text (die Regel zum Ausblenden stand vor der Grundregel).

### Nicht gemacht
- Beim Review prüft tinyops noch nicht, ob es einen Punkt schon als Thread gibt, und gibt dem Agenten die offenen Threads nicht mit.
- Ein MR aus einem Fork lässt sich reviewen (der Agent holt `refs/merge-requests/N/head`), ist aber nicht gegen ein echtes GitLab geprüft.

## [0.41.1]

Gleicher Inhalt wie 0.41.0. Für v0.41.0 gab es kein Release: Auf GitHub ist kein git-Name eingetragen, und vier Tests zum Übernehmen brauchten einen. Der Tag v0.41.0 bleibt stehen, das Release ist dieses.

### Behoben
- Merge, Rebase und Cherry-Pick: Kennt git deinen Namen für Commits nicht, sagt tinyops jetzt, wie du ihn einmal einträgst, statt der rohen git-Meldung.
- Die Tests zum Übernehmen tragen in ihrem Test-Repo einen eigenen Namen ein und prüfen die Meldung ohne Namen.

## [0.41.0]

Auf deinen Wunsch vom 23.11.: den Branch eines Agenten in den Feature-Branch des Tickets übernehmen, direkt aus dem Detail-Panel.

### Neu
- **«Übernehmen in …»** am Branch eines Agenten (und an jedem Branch ohne MR, wenn die Aufgabe weitere Branches hat). Das Ziel ist vorgewählt: der Branch des MR, sonst der nächste Branch der Aufgabe.
  - **Vorschau:** die Commits, die dazukommen (älteste zuerst, schon übernommene markiert), Umfang, ob Konflikte zu erwarten sind (`git merge-tree`), ob Fast-Forward geht.
  - **Vier Wege:** Fast-Forward (nur wenn der Ziel-Branch nichts Eigenes hat), Rebase (die Commits obendrauf, gerade Geschichte), Merge (mit Merge-Commit), Cherry-Pick (nur die angehakten Commits).
  - **Sicher:** Vorher holt tinyops beide Branches (`git fetch`, nur lesend). Gearbeitet wird in einem eigenen Worktree, dein Arbeitsordner wird nicht umgeschaltet. Der Ziel-Branch rückt nur vor, er wird nie umgeschrieben. Ist er bei dir ausgecheckt, wird er dort nachgezogen. Hat er dort geänderte Dateien oder ist dein lokaler Stand von GitLab abgewichen, passiert nichts, mit Grund.
  - **Konflikt:** Entweder wird alles zurückgenommen, oder der Worktree bleibt stehen und öffnet sich in IntelliJ. Nach dem Lösen «Abschliessen», oder «Abbrechen».
  - **Push:** macht tinyops nie. Das Ergebnis nennt, wie weit dein Branch vor GitLab ist, mit dem Push-Befehl zum Kopieren.
  - Jede Übernahme steht im Verlauf. Gekoppelte Geräte können das nicht.

### Behoben
- Auf Handy-Breite liess sich die Seite Einstellungen um ein paar Pixel seitlich schieben, wenn der Pfad zur Dienst-Datei lang ist (unter «Update und Dienst»). Er bricht jetzt um. Der Test dafür nennt bei einem Fehler, was übersteht.

### Grenzen
- Getestet mit echtem git gegen ein lokales Test-Repo, nicht gegen dein GitLab.
- Liegt der Agent-Branch nur auf dem Agenten-Rechner, muss der Agent ihn erst pushen (Einstellungen → Agenten → «pusht seinen Branch»). tinyops sagt das dann.
- Cherry-Pick eines Commits, der schon drin ist, bricht ab. Solche Commits sind in der Vorschau markiert und nicht angehakt.

## [0.40.0]

Agenten: weiterführen in derselben Sitzung, vier Rollen mit Kreislauf zurück ans Entwickeln. Dazu, auf deinen Wunsch vom 23.11., Update aus dem Panel und tinyops als Dienst unter Linux.

### Neu
- **Gespräch mit dem Agenten in derselben Sitzung** (Wunsch vom 18.11., Klärung zu `r36-01`): Unten im Lauf «Nachricht an …». Der Agent setzt seine Sitzung fort, im selben Ordner auf demselben Branch, mit allem, was er vorher gelesen und getan hat. Nachfragen («Warum so?») gehen genauso wie Aufträge. Über dem Ergebnis steht das «Gespräch»: dein Auftrag, deine Nachrichten, Rückfragen und die Antworten des Agenten, Runde für Runde.
  - Claude Code startet mit `--session-id` und macht mit `--resume` weiter. Codex: `codex exec resume`. Vibe: `--resume` oder `--continue`. Goose: `--name … --resume`. opencode: `--continue`.
  - Geht das nicht (anderer Agent, eigener Befehl, Ordner weg, Lauf vor 0.40), startet wie bisher ein neuer Lauf mit Zusammenfassung. Der Grund steht neben dem Eingabefeld («neue Sitzung»).
- **Vier Rollen und der Kreislauf** (Schwerpunkt 2 vom 20.11.): Oben im Lauf stehen Planen, Entwickeln, Review und Test mit eigener Farbe, ihrem Agenten und dem Stand, dazu die Runde.
  - Aus Review und Test: «↺ Zurück ans Entwickeln» schickt den Befund mit deiner Notiz in die Sitzung des Entwicklers. Ein Klick, kein Kopieren, kein Dialog.
  - Aus Entwickeln: «Zurück ans Entwickeln» mit einem Satz geht direkt an ihn zurück (bisher: Dialog «Nachbessern lassen»).
  - Nach dem Nachbessern: «Erneut prüfen lassen». Derselbe Reviewer prüft in seiner Sitzung, sein Ordner wird auf den neuen Stand des Entwicklers vorgespult. Geht das nicht (anderer Rechner, andere Isolation), öffnet sich der gewohnte Dialog.
- **Git-Benutzer je Agent** (Wunsch vom 18.11.): Einstellungen → Agenten → Git-Name und Git-E-Mail. Die Commits des Agenten tragen sie, auch auf entfernten Rechnern.
- **Update aus dem Panel** (Wunsch vom 23.11.): tinyops sieht alle 6 Stunden nach, ob es ein neueres Release gibt (nur lesend). Oben steht dann «tinyops … ist da», mit «Was ist neu?» und «Jetzt aktualisieren». Das Update läuft wie beim Start über `start.py` (holen, Selbsttest, bei Fehlern zurück). Danach startet tinyops neu und die Seite lädt von selbst. Nicht aktualisiert wird mit geänderten Dateien oder auf einem Branch, mit Grund. Gekoppelte Geräte dürfen das nicht.
- **tinyops als Dienst unter Linux** (Wunsch vom 23.11.): Einstellungen → Update und Dienst → «Als Dienst einrichten und neu starten», oder `python3 server.py --install-service`. Ein Benutzer-Dienst (`systemctl --user`, kein sudo) startet tinyops bei der Anmeldung und nach einem Absturz. Ohne Anmeldung erst nach `loginctl enable-linger $USER`; das steht dabei.

### Geändert
- «Umsetzen» heisst jetzt «Entwickeln», wie die Rolle.
- «Weiterführen» heisst «Nachricht an …» mit «Senden».
- Der Freigabe-Kasten bei Review und Test fragt jetzt: Gibt es etwas zu verbessern? Dann zurück ans Entwickeln, sonst freigeben.

### Entfernt
- Der alte Anfrage-Parameter `prereview` (Vorprüfen aus 0.27). Review geht seit 0.31 über die Phase, mit `parent`. Die Antwort nennt den geprüften Lauf jetzt `review_of`.

### Intern
- **`agents.py` aufgeteilt** (1'787 → 925 Zeilen): `agent_rules.py` (Konfiguration, Rollen, Phasen, Leitplanken), `agent_cmd.py` (Aufruf der Programme, Sitzungen, Git-Benutzer), `agent_scripts.py` (Shell-Skripte eines Laufs), `agent_ssh.py` (Verbindung, Prüfen), `agent_talk.py` (Gespräch). `agents` gibt alle Namen weiter.
- Lauf-Tabelle: neue Spalten für Sitzung, Kette und Gespräch (`session`, `resume_of`, `next_run`, `ask`, `reply`, `fresh`).
- Tests: `test_v40` spielt Gespräch, Zurück ans Entwickeln und Erneut prüfen mit einem Ersatz für Claude Code durch, mit echtem git. `test_updater` prüft Update, Rückfall und Dienst mit einem Mini-Repo und einem Ersatz für `systemctl`.

### Grenzen
- Fortsetzen ist gegen Nachbauten der Programme geprüft, nicht gegen Claude Code, Codex oder Vibe selbst. Ob Vibe seine Sitzungskennung im Streaming nennt, ist nicht dokumentiert. Ohne Kennung nimmt tinyops `--continue`, die letzte Sitzung im Ordner.
- «Jetzt aktualisieren» gibt es ab dieser Version. Der erste echte Durchlauf ist also das Update auf 0.41.
- Den Dienst habe ich mit einem Ersatz für `systemctl` getestet, nicht auf einem echten Ubuntu.
- Doppelte Stile und Dialog-Muster sind weiter nicht zusammengeführt.

## [0.39.0]

Oberfläche zerlegen, dazu drei Korrekturen aus deinen Berichten vom 20.11.

### Neu
- **QR-Code beim Koppeln** (Prüfbericht `r36-05`): Einstellungen → App und Handy → «Code erzeugen» zeigt neben dem Code einen QR-Code. Die Handy-Kamera öffnet damit die Kopplungsseite, der Code steht schon im Feld; du tippst nur noch «Koppeln». Der Code steht hinter `#` in der Adresse: Er geht nicht übers Netz und landet in keinem Log, und die Seite nimmt ihn gleich wieder aus der Adresse. Erzeugt ohne Fremdbibliothek (`qr.py`). Ohne eingetragene Adresse fürs Handy gibt es keinen QR-Code.

### Geändert
- **Agentenfenster als Seitenpanel** (Nutzungsbericht: 182 Klicks, 24 Wutklicks im Dialog): Zuweisen und Lauf öffnen sich rechts. Fokus und Listen bleiben daneben bedienbar, ein Klick daneben schliesst nichts mehr. × oder Esc schliessen. Ab 2'300 px Breite steht es neben dem Detail-Panel statt darüber. Kommt es aus einem anderen Dialog (z. B. Workspaces), öffnet es wie bisher darüber.
- **Klicks im Detail-Panel tun etwas** (30 tote Klicks): Branch-Code und Namen von Repo und Branch kopieren beim Klick, Chips mit Erklärung zeigen sie, der Titel eines MR öffnet ihn.

### Intern
- **Oberfläche zerlegt:** `static/index.html` (5'155 Zeilen) ist jetzt `index.html` (nur HTML), `app.css` und 16 Dateien in `static/js/`, je Ansicht eine, dazu Bausteine (`core.js`: API, Meldungen, Kopieren, Speicher, Felder, Dialoge, Markdown, Piktogramme; `help.js`: Hilfe). Keine Datei hat mehr als 900 Zeilen.
- Ohne Build-Schritt: `ui.py` setzt die Teile beim Start wieder zu einer Seite mit einem Skript zusammen, genau wie bis 0.38. Darum bleibt das Verhalten gleich, und der Offline-Cache der App braucht nichts Neues.
- Ein Test prüft, dass jede Datei in `ui.py` steht, keine 1'200 Zeilen erreicht und das Skript fehlerfrei ist.
- Ein Zeit-Test schlug kurz vor Mitternacht fehl (die Fokus-Sitzung endete am nächsten Tag). Er startet jetzt um 10 Uhr.

### Prüfliste
- `r37-01` und `r38-01` (Arbeitstag nach dem Umbau) gehen in `r39-01` auf, `r36-05` (Koppeln) in `r39-02`.

### Nicht gemacht
- Doppelte Stile und Dialog-Muster sind noch nicht zusammengeführt. Das hätte sichtbare Unterschiede gebracht; es kommt mit den Oberflächen-Änderungen in 0.40 und 0.41, wo die Dialoge ohnehin neu gebaut werden.

## [0.38.0]

Server zerlegen II. Ein reines Refactoring: Für dich ändert sich nichts. `server.py` hat noch 743 Zeilen (vor 0.37: 5'301).

### Geändert
- **App in neun Bereiche geteilt**, je ein Modul `area_*.py`:
  - Übersicht und Sync
  - Tickets, Board und Ideen
  - Agenten-Anbindung
  - Zeit und BCS
  - Fokus
  - Prüfen
  - Workspaces
  - Microsoft 365
  - IntelliJ und Review-Umgebung
- `server.py` behält nur den Kern: Config anwenden, Clients, Speicher, Audit, Start. Standardwerte und Config-Hilfen liegen in `config.py`.
- **Grenzen sichtbar:** Jeder Bereich nennt in `USES`, welche Methoden anderer Bereiche er aufruft. `tests/test_areas.py` prüft, dass es genau diese sind, dass keine Methode doppelt steht und dass die Grössen eingehalten sind (`server.py` unter 1'500, jeder Bereich unter 1'000 Zeilen).
- Ehrlich: Die Bereiche teilen sich weiter `self` (Config, Speicher, Audit, Cache). Sie sind Mixins, keine Dienste mit eigenem Zustand. Die Querzugriffe sind jetzt aber aufgeschrieben und geprüft; die Übersicht (Sync) braucht als einzige fast alle anderen.
- `agents.py` und `settings.py` sind noch grösser als 1'000 Zeilen. Sie kommen mit 0.40 und 0.41 dran.

### Prüfliste
- `r21-06` (Windows-Start) ist in `r211-03` aufgegangen.

## [0.37.1]

### Behoben
- **Linux-Launcher startete tinyops nicht** (auf einem neuen PC mit Python 3.14): «`import ssl` … version `OPENSSL_3.3.0` not found». Der gepackte Launcher gab den Pfad zu seinen mitgepackten Bibliotheken (`LD_LIBRARY_PATH`) an das System-Python weiter, das dann eine ältere OpenSSL lud. Jetzt setzt er den Pfad für alle Kindprozesse (Python, git, Browser) zurück; unter macOS ebenso `DYLD_LIBRARY_PATH`.
- Ausweg mit älteren Launchern: `python3 ~/.local/share/tinyops/app/start.py` oder `python3 tinyops-launcher.pyz`.

## [0.37.0]

Server zerlegen I. Ein reines Refactoring: Für dich ändert sich nichts. `server.py` ist um 1'500 Zeilen kürzer (5'301 → 3'794).

### Geändert
- **Eigene Module statt einer grossen Datei:**
  - `routes.py`: der HTTP-Teil mit Zugang (Host, Token, gekoppelte Geräte) und einer **Routentabelle** statt der langen if-Kette. Eine neue Route ist eine Zeile.
  - `gitlab_client.py`, `jira_client.py`, `httpclient.py`: die Clients.
  - `demo.py`: die Demo-Daten.
  - `ideas.py`: die Ideenbox.
  - `common.py`: was alle brauchen (Fehlerarten, Zeit, Jira-Keys, Secrets).
- Die Namen bleiben über `server` erreichbar, damit Werkzeuge und Tests nicht brechen.
- Verbindungstests in den Einstellungen laufen über eine kleine Tabelle statt sieben gleicher Blöcke.

### Neu (für die Entwicklung)
- **Sicherheitsnetz für das Zerlegen:** `tests/test_routes.py` ruft 74 Routen auf und vergleicht Status, Typ und Form der Antwort mit einem Schnappschuss von vor dem Umbau. Ein zweiter Test passt auf, dass `server.py` nicht wieder wächst.

### Behoben
- Zwei UI-Tests waren wackelig, wenn die Liste beim Abgleich neu gezeichnet wurde.

## [0.36.3]

### Behoben
- **Detail-Panel, «MRs und Branches»:** Die Knöpfe (MR, Pipeline, IntelliJ, Offene Punkte …) lagen über den Chips und verdeckten sie. Sie stehen jetzt in einer eigenen Zeile darunter.
- «Draft» stand bei Draft-MRs doppelt (Draft-Markierung und Merge-Status von GitLab). Jetzt nur einmal.

## [0.36.2]

### Neu
- **Kopplung für die eigene App** (Entscheide E9–E11 vom 16.11.): Die React-PWA aus dem eigenen Repo koppelt sich mit demselben Einmal-Code wie das Handy. Sie bekommt ein Geräte-Token und schickt es als `Authorization: Bearer …`. tinyops beantwortet ihre Anfragen über CORS, aber nur für die Adressen unter Einstellungen → App und Handy → «Adressen der eigenen App». Je Instanz eigene Geräte und Tokens.

### Geändert
- Entscheide zusammengeführt: Die Einträge vom 16.11. (E5–E11) stehen wieder vollständig drin. Meine neuen vom 17.11. heissen **E12** (Agenten pushen ihren Branch) und **E13** (Kopplung je Gerät), statt mit E9/E10 zu kollidieren.

## [0.36.1]

### Behoben
- **Handy: Fokus liess sich seitlich verschieben** (im CI 409 statt 390 px, seit 0.35.1). Die Aufgabe oben und die Liste machen die Spalte nicht mehr breiter als den Bildschirm.
- Der UI-Test für den Verbindungshinweis war wackelig, wenn andere Anfragen dazwischen gelangen.

## [0.36.0]

Noch eine Version vor dem Umbau, auf deinen Wunsch: deine Wünsche und der Nutzungsbericht vom 17.11., dazu tinyops als App mit Handy-Kopplung. Der Plan ab «Server zerlegen» rückt um eine Version nach hinten.

### Neu
- **Lauf weiterführen** (Wunsch): Unten im Lauf schreibst du, wie es weitergehen soll, und «Weiterführen» startet sofort einen neuen Lauf auf demselben Branch. Offene Kriterien und fehlgeschlagene Belege gehen automatisch mit. «Mit Vorschau …» zeigt vorher den ganzen Prompt.
- **Entscheidungen** (Wunsch):
  - Der Agent fragt mit `tinyops-ask -d` und wartet, statt zu raten.
  - Schreibt er «Offene Entscheidungen» in den Bericht, stehen sie im Lauf mit Antwortfeldern; deine Antworten gehen mit dem nächsten Lauf an ihn.
  - Getroffene Entscheidungen stehen im Review und in der MR-Beschreibung.
- **Agenten** (Wunsch):
  - **Rollen** je Phase als Befehl am Anfang des Prompts, z. B. `/planner`, `/developer`, `/reviewer`, `/tester` für eigene Slash-Befehle auf dem Agenten-Rechner. «Weiter mit …» wählt den Agenten mit passender Rolle vor.
  - **Push:** je Agent einschaltbar. Er pusht am Ende genau seinen Lauf-Branch, nie main, master, develop oder release/*. tinyops selbst pusht weiter nie.
  - **Kontingent:** Jeder Agent hängt an einem Abo (Claude, Codex, Mistral). Die Auswahl zeigt, wie viel davon noch frei ist.
  - **Ziehen:** Agenten stehen in der Seitenleiste und lassen sich auf eine Aufgabe im Fokus oder im Board ziehen.
- **Fokus-Aufgabe als Arbeitsfläche** (Wunsch): Die oberste Aufgabe zeigt «Worum es geht» und «Fertig, wenn» aus dem Ticket, rechts Teilschritte zum Abhaken und die Agenten. Bei Helpdesk-Tickets die Beschreibung.
- **Helpdesk → Jira** (Wunsch): «Jira-Ticket daraus anlegen» im Fokus und im Panel. Entwurf mit Link, Problem und Kriterien, Hinweis auf Kundendaten, Anlegen nur mit Bestätigung. Das Helpdesk-Ticket bleibt unverändert; tinyops merkt sich den neuen Key.
- **tinyops als App:** «Als App installieren» unter Einstellungen → App und Handy. Am Rechner ein eigenes Fenster, auf dem Handy über eine eigene Adresse (z. B. Tailscale) und **Kopplung je Gerät** mit Einmal-Code. Von aussen sieht tinyops nur, wer gekoppelt ist; gekoppelte Geräte ändern keine Einstellungen und lassen sich jederzeit entfernen.

### Behoben
- **Agentenfenster:**
  - Es baute sich bei laufenden Agenten alle 4 s neu auf, Klicks gingen verloren (20 Wutklicks im Bericht). Jetzt läuft nur das Log nach.
  - Jeder Dialog hat oben rechts ein ×, das beim Scrollen sichtbar bleibt (Wunsch: «Agenten-Fenster braucht einen Close-Button»). Ein Klick daneben schliesst ihn, ausser etwas Eingetipptes ginge verloren.
- **BCS nicht erreichbar:** Bisher wartete die Zeit-Ansicht bis über eine Minute (35× im Bericht, Median 73 s). Jetzt höchstens 8 s, danach eine Minute Pause mit klarer Meldung und «nächster Versuch in …». Die Tagesansicht wird 30 s zwischengespeichert.
- **Fetch «kennt der letzte Scan nicht»** (7× im Bericht): tinyops liest Workspaces in diesem Fall selbst neu ein.
- **Zurückgeschickte Reviews** (Wunsch): Hast du in GitLab Änderungen angefordert, kommentiert oder freigegeben, oder ist der MR wieder Entwurf, steht er unter «Wartet» statt bei deinen Reviews. Fordert der Autor das Review neu an, ist er wieder da.
- War tinyops kurz weg, holt das Panel nach dem Wiederverbinden gleich den ganzen Stand.

### Geändert
- Nachbessern heisst jetzt «Weiterführen». Dein Text geht als eigener Abschnitt «Auftrag des Menschen» an den Agenten, mit Zeilenumbrüchen.
- Prüfliste: `r20-07`, `r20-08`, `r24-01`, `r24-02` und `r21-01` sind abgelöst, weil neuere Punkte dasselbe prüfen.

## [0.35.1]

Korrekturen nach deinem Test am 16.11.

### Behoben
- **Spielstand fehlte im Fokus:** Eine Config, die vor 0.35 gespeichert wurde, kennt den Schalter «score» nicht. Der Server las das als «aus», die Einstellungen zeigten «an». Jetzt gilt ein fehlender Schalter als Standard, der Spielstand ist wieder da.
- **BCS-Token liess sich nicht speichern** (seit 0.29): Der Secret-Speicher kannte den Namen `bcs_token` nicht und hatte stattdessen noch das alte `mcp_token`.

### Neu
- **Zugänge auf einen Blick:** Ganz oben in den Einstellungen, zugeklappt, eine Zeile mit allen gespeicherten Tokens. Fehler und Fehler beim letzten Abgleich sind rot. Aufgeklappt siehst du je Token den Zustand, woher es kommt (Schlüsselbund, Datei, Umgebung) und «Ändern» oder «Eintragen».
- **BCS-Middleware im eigenen Netz:** Mit dem Haken «Middleware im eigenen Netz» geht auch eine private Adresse, z. B. der Windows-Host deiner VM. Öffentliche Adressen bleiben gesperrt. Die Hilfe zeigt zwei Wege, bei denen 127.0.0.1 bleibt: WSL mit `networkingMode=mirrored` oder ein SSH-Tunnel.

### Geändert
- Der Schalter für den Spielstand steht jetzt unter Einstellungen → **Fokus** (bisher «Weiteres»). Der Abschnitt heisst «Fokus: Bereiche, Wochenziel, Spielstand».

## [0.35.0]

Weniger Begriffe (E3, E4) aus dem Plan, dazu tote Klicks, Fehler und der Worktree-Wunsch aus deinem Nutzungsbericht und dem Verlauf vom 16.11.

### Behoben
- **«Panel nicht erreichbar»** (5× im Nutzungsbericht): Ist tinyops kurz weg, kommt keine Fehlermeldung mehr bei jedem Abgleich. Oben steht ein Hinweis mit Countdown, das Panel verbindet sich selbst wieder (2, 3, 5, 10, 20, dann alle 30 s) und hat «Jetzt verbinden».
- **Board: Aufgabe aus der letzten Kategorie nehmen** endete im Verlauf mit einem Fehler. Jetzt fragt tinyops, ob ein tiny-Ticket zurück in den Ideenpool soll. Nein ändert nichts.
- **Workspaces: «Fetch» fehlgeschlagen** zeigte die rohe git-Ausgabe. Jetzt steht dort kurz, was fehlt: SSH-Schlüssel, Netz oder Rechte.
- **Prüfen: doppelte Häkchen** (im Verlauf zweimal derselbe Eintrag): Ein Doppelklick auf ok oder Fehler sendet nur einmal, die Anzeige wechselt sofort.
- Ein Speichern ohne Änderung landet nicht mehr als leerer Eintrag im Verlauf.

### Neu
- **Worktrees in Workspaces** (dein Wunsch: «AI creates worktrees»): Zahl oben, Filter «Worktrees», alte und saubere Worktrees sind markiert. «Entfernen» geht nur, wenn der Worktree sauber ist und sein Commit noch auf einem Branch oder Remote liegt.
- **Tote Klicks weg** (Nutzungsbericht):
  - Prüfen: Klick auf den Text eines Punkts öffnet eine Notiz, Klick auf einen Befehl kopiert ihn (27 tote Klicks auf Text und «erwartet»).
  - KI-Tempo in der Seitenleiste öffnet die Details zum Kontingent (16 tote Klicks, 3 Wutklicks).
  - Bereiche in der Seitenleiste starten eine Sitzung dafür.
  - Die Zahlen oben in Workspaces filtern die Liste.

### Geändert
- **E3 Spielstand:** eine Karte im Fokus, ohne Level-Balken. Neu abschaltbar unter Einstellungen → Weiteres → «Spielstand»; dann auch keine XP-Meldungen.
- **E4 Begriffe:** «Fokus» (woran du bist, mit Sitzung) und «Bereiche» (Wochenziel). Aus «Fokusbereiche» wird «Bereiche und Wochenziel», aus «Fokus-Modus» der Knopf «Vollbild», die Leiste heisst nicht mehr eigens.
- Ungenutzte Ansichten bleiben vorerst sichtbar: sieben Tage Nutzung reichen dafür nicht (siehe Roadmap, «Auswertung 16.11.»).

## [0.34.0]

Doppelungen I aus dem Plan, dazu Korrekturen und Wünsche aus deinem Prüf- und Nutzungsbericht vom 16.11.

### Behoben
- **Helpdesk-Ticket anheften** (Prüfpunkt r23-04, «öffnen sich nur im neuen Tab»): Tickets aus der Queue und aus «Ich beobachte» liessen sich nicht anheften, im Panel gab es nur «Im Helpdesk öffnen». Jetzt gehen Anheften, Zeit und Fokus-Sitzung für jedes Helpdesk-Ticket, das tinyops kennt. Zuweisen bleibt im Helpdesk.

### Neu
- **«Ausprobieren …» am MR** (im Fokus-Detail, beim Testen neben «In IntelliJ öffnen», in den Listen):
  - Prompts kopieren (Review-Brief, Smoke-Test, Repro-Test)
  - git-Befehle kopieren
  - In IntelliJ öffnen
  - Review-Umgebung starten, stoppen und öffnen, oder ihre Befehle kopieren

  So geht es auch ohne eingerichteten Agenten (Entscheid E2).
- **Review-Umgebung vorbefüllt:** tinyops erkennt Compose-Dateien und Dockerfile in deinem Checkout und schlägt «Docker Compose mit …» vor. Die Befehle sind vorbefüllt und bleiben anpassbar.
- **Umsysteme zusammenklicken:**
  - Wählbar sind PostgreSQL, MariaDB, Redis, ActiveMQ Artemis, RabbitMQ, Mailpit und andere Repos aus Workspaces mit Dockerfile.
  - tinyops schreibt daraus eine Compose-Datei in seinen Datenordner, nie ins Repo, und gibt sie mit `-f` dazu (neuer Platzhalter `{compose_files}`).
  - Umsysteme bekommen keine Ports nach aussen und sind unter ihrem Namen erreichbar.
- **Checkout automatisch aus Workspaces:** Ist bei einem Projekt kein Pfad eingetragen, nimmt «In IntelliJ öffnen» den Checkout aus Workspaces, dessen Remote passt. Worktrees zählen dabei nicht.

### Geändert
- Die Review-Umgebung von Agenten-Läufen und MRs läuft über denselben Weg. Ihr Zustand steht in einer eigenen Tabelle, Läufe aus 0.32/0.33 werden weiter gelesen.
- `usage.py` heisst jetzt `aiquota.py` (Rest-Kontingent der KI-Abos), damit es nicht mit der UI-Nutzung (`ux.py`) verwechselt wird.
- Der Smoke-Test-Prompt prüft die Review-Umgebung statt eines Kubernetes-Namespaces.

### Entfernt
- **Projectron-Export** (E1, gebucht wird nur über BCS): Wrapper-URL, Token, «Senden», «Beim Bestätigen sofort senden», `GET /api/time/export`, `POST /api/time/result` und der Verbindungstest. Der Verbindungstest war mit 8 s die langsamste Antwort im Nutzungsbericht. Bisherige Entwürfe bleiben lesbar, alte Einstellungen werden beim Speichern entfernt.
- **Alte Testumgebung je MR** (E2):
  - Weg sind Helm-Deploy und Abbau, die Test-Jobs, die alten Agenten-Knöpfe pro MR und der Schalter «Testumgebungen» unter Weiteres.
  - Ebenso die Einstellungen `kube_context`, `namespace_prefix`, `deploy_command`, `teardown_command`, `job_timeout` und `agent_command`.
  - Der Fehler «kube_context fehlt» aus dem Nutzungsbericht kann nicht mehr auftreten.
  - `deploy/` bleibt: Damit betreibst du tinyops selbst in Kubernetes, das hat mit der Testumgebung nichts zu tun.

## [0.33.0]

Das erste Release des Plans 0.33–0.45: absichern, bevor aufgeräumt wird. Keine neuen Funktionen.

### Neu
- **UI-Tests im Repo** (`tests/test_ui.py`): Playwright spielt die Oberfläche im echten Browser gegen den Demo-Server durch. Dazu gehören:
  - alle Ansichten
  - Handy-Breite ohne seitliches Scrollen
  - Tasten j/k/Enter/n/i/Esc
  - Detail öffnen und schliessen (auch per Klick daneben)
  - Anheften mit Zeit und Pause
  - Fokus-Sitzung mit Parken, Klein machen und Wieder öffnen
  - Agenten-Zyklus von Planen bis zur Freigabe mit «Kurz vorab»
  - Testsitzung in Prüfen
  - Hilfe in jedem Einstellungsabschnitt

  Jeder JavaScript-Fehler lässt den Test scheitern. Sie laufen auf GitHub bei jedem Push mit. Ohne Playwright werden sie übersprungen.
- **Prüfliste mit `[auto: …]`:** Punkte, die ein automatischer Test prüft, sind so markiert. Sie zählen nicht als offen, kommen nicht in «Als Nächstes testen» und stehen je Abschnitt zugeklappt unter «… prüft ein automatischer Test». Ein Test stellt sicher, dass jede Markierung auf einen echten Test zeigt.
- **`docs/DECISIONS.md`:** getroffene und offene Entscheide (E1–E8) mit Empfehlung und Termin.

### Geändert
- **Prüfliste: 187 statt 198 Punkte, davon nur noch 59 von Hand:**
  - 128 Punkte prüft jetzt ein automatischer Test.
  - Verbindungstests, BCS-Buchen, Microsoft-365-Anmeldung, die Windows-Punkte und das KI-Kontingent sind je zu einem Punkt zusammengefasst.
  - Zwei Punkte zur Oberfläche vor 0.31 («Vorprüfen lassen», «Ergebnis des Agenten prüfen») sind entfernt.
  - Ebenso entfernt sind die Prüfung von GitHub Actions und Release: Ohne grüne Tests entsteht kein Release.
- Einstellungen → Weiteres hat jetzt auch eine Hilfe. Der neue UI-Test hatte sie als fehlend gemeldet.

## [0.32.1]

Gleicher Inhalt wie 0.32.0. Der Tag v0.32.0 zeigt auf einen Stand, dessen Zeit-Tests kurz nach Mitternacht fehlschlugen. Deshalb gab es dafür kein Release.

### Behoben
- Selbsttest und Zeit-Tests prüfen den Zeitentwurf an einem festen Tag (gestern) und hängen nicht mehr von der Uhrzeit ab.
- Prüfen: Bei einem Patch-Release gilt der Abschnitt derselben Minor-Version als aktuell (zuerst in «Als Nächstes testen»).

## [0.32.0]

### Neu
- **Begründen im Bericht, nicht im Code.** Neue Leitplanke in jedem Umsetzen-Prompt: Jede geänderte Datei bekommt im Bericht eine Zeile «Datei – was – warum». Keine Kommentare nur fürs Review, keine auskommentierten Zeilen. Der Bericht hat jetzt feste Abschnitte: Kurz, Was und warum, Zuerst ansehen, Getestet, Bewusst nicht gemacht.
- **Hinweis bei Kommentar-Rauschen.** tinyops zählt neue Kommentarzeilen je Datei im Diff. Ab fünf zeigt der Freigabe-Kasten einen Hinweis.
- **«Kurz vorab» im Lauf.** Oben im Ergebnis, in zwei Minuten lesbar: was jetzt anders ist, jede Datei mit +/− und der Begründung aus dem Bericht (oder «Keine Begründung»), wo anfangen, Kriterien und Belege auf einen Blick. Der ganze Bericht ist aufklappbar.
- **Als MR-Beschreibung kopieren.** Für Reviewer im Team: Worum es geht, Was und warum je Datei, Zuerst ansehen, So testest du (Schritte und Belege), Akzeptanzkriterien als Checkliste. tinyops erstellt keinen MR und pusht nicht.
- **Ausprobieren.** Im Lauf:
  - «In IntelliJ öffnen» holt den Branch des Agenten (lokal oder per SSH vom Agenten-Rechner) in deinen Checkout und legt daneben einen eigenen Worktree an. Dein Arbeitsstand bleibt unberührt.
  - «Befehle kopieren» gibt dir `git fetch`/`git switch` zum Selbermachen, dazu den Push-Befehl für das Team.
  - **Review-Umgebung** je Projekt (Docker Compose, Kubernetes oder eigene Befehle): starten, stoppen und öffnen per Klick, mit Name und Port je Lauf. Nur auf deinen Klick, auf diesem Rechner. Einstellungen → IntelliJ und Review-Umgebung.
- **Piktogramme für Repo und Branch.** Jedes Repo hat ein eigenes Muster, jeder Branch einen kleinen Git-Graphen in eigener Farbe. Die Form der Commits zeigt die Art: Kreis für feature, Raute für fix/bug/hotfix, Quadrat für agent. Gleicher Name heisst überall gleiches Bild: im Fokus, in den Listen und im Lauf.
- **Fokus klarer.** Titel grösser, darunter Repo und Branch als Piktogramm mit Namen.

## [0.31.0]

### Neu
- **Agenten-Zyklus: Planen → Umsetzen → Review → Test.** Jede Phase ist ein eigener Lauf mit eigener Vorlage und endet mit deiner Freigabe. Die Leiste oben im Agenten-Dialog zeigt, wo das Ticket steht.
  - **Planen:** Der Agent liest nur und schreibt einen Plan (Ziel, Schritte mit Dateien, Tests, Umfang, Risiken). Erst wenn du ihn freigibst, kann umgesetzt werden. Der Plan geht als Zitat in den Umsetzen-Auftrag.
  - **Umsetzen** wie bisher, bei kleinen Aufgaben auch ohne Plan.
  - **Review:** Ein zweiter Agent liest das Ergebnis auf demselben Branch und ändert nichts. Ersetzt «Vorprüfen lassen».
  - **Test:** Tests ausführen, fehlende ergänzen, Schritte für deinen Test von Hand beschreiben. Produktionscode bleibt unberührt.
  - **Freigeben** geht erst, wenn alle Prüfpunkte abgehakt sind. **Zurückgeben** braucht einen Satz, was anders werden soll. Er geht direkt in «Nachbessern lassen».
  - Der nächste Schritt im Fokus kennt die Phasen: «Umsetzen prüfen und freigeben (Prüfpunkte 2 von 6)», «Review starten», «Nachbessern lassen».
- **Prüfpunkte von Hand je Lauf.** Fürs Review: Diff ganz gelesen, Umfang passt, Tests passen, jedes Akzeptanzkriterium. Für den Test: die Schritte, die der Agent mit dem neuen `tinyops-manual "Schritt" "Erwartet"` beschreibt, plus «Im laufenden System ausprobiert». Abhaken mit optionaler Notiz.
- **Leitplanken in jedem Prompt.** Klein halten (Standard: höchstens 8 Dateien, etwa 300 Zeilen), nur was die Aufgabe verlangt, einfach vor clever, Test zu jeder Verhaltensänderung, kleine Commits, Bericht für das Review. In Planen und Review zusätzlich: nichts ändern. Werte und eine eigene Team-Regel unter Einstellungen → Coding-Agenten → Leitplanken. Geht ein Ergebnis darüber, zeigt der Lauf einen Hinweis.
- **Prompts lesbar und kopierbar.** Alle Vorlagen sind jetzt Markdown mit klaren Abschnitten. Im Dialog «Ansehen» (gerendert) oder «Bearbeiten» (Text), dazu «Kopieren». Den gesendeten Prompt eines Laufs gibt es ebenso; Bericht, Plan und Befund des Agenten werden gerendert.
- **Testsitzung in Prüfen.** Oben «Als Nächstes testen»: die nächsten fünf offenen Punkte, dieses Release zuerst. Ältere Releases ruhen, bis du den Haken «ältere Releases ruhen lassen» löst.

### Geändert
- «Vorprüfen lassen» heisst jetzt Review und ist Teil des Zyklus. Der Aufruf mit `prereview` geht weiter.
- Läufe aus früheren Versionen gelten als «Umsetzen».

## [0.30.0]

### Neu
- **Tickets zu Tasks gruppieren.** «Stories in Arbeit» heisst jetzt «Tasks in Arbeit». Gehören mehrere Jira-Tickets in Arbeit zusammen, erscheinen sie als ein Task: im Panel, auf dem Board, im Fokus und in der Detailansicht, mit allen MRs und Branches.
  - **Bug mit Begleitticket:** Der Bug ist der Task, das Begleitticket hängt darunter («+ DLP-132 Aufgabe»).
  - **Story mit Unteraufgaben:** Die Story ist der Task.
  - Zusammen gehören Tickets in Arbeit, die in Jira verknüpft sind. Unter Einstellungen → Jira kannst du die Link-Typen einschränken (z. B. «Relates»). Leer heisst: jeder Link zählt.
  - **Von Hand:** «Gruppieren …» am Task oder in der Detailansicht: einem Task zuordnen, eigenständig machen oder zurück auf automatisch. Von Hand gilt immer vor der Erkennung.
  - Ein Task zählt einmal zum Limit.
- **Wunsch an tinyops:** Im Ideen-Dialog (Taste i) der Haken «Wunsch an tinyops», oder im Ideenfeld mit «tinyops:» beginnen. Der Wunsch landet nicht in der Ideenbox, sondern wörtlich im Nutzungsbericht, mit Ansicht, Version und den letzten Klicks davor. Er wird gespeichert, auch wenn die Erfassung aus ist.
- **Mehr im Nutzungsbericht:**
  - **Version je Sitzung.** «Auffällig» zählt nur noch die neueste Version, damit alte Probleme nicht wieder auftauchen.
  - **Fehlermeldungen**, die das Panel gezeigt hat, als Vorlage: Ticket-Keys, Zahlen und Zitate werden ersetzt. Bei Einstellungen nur die Feldnamen.
  - **Langsame Antworten** über 1,5 s je Endpunkt.
  - **Welche Hilfe** aufgeklappt wurde.
  - **Welche Ansichten** im Zeitraum nie geöffnet wurden.

### Geändert
- **Bugs und andere Typen bleiben sichtbar.** Bisher verschwanden Tickets, deren Typ nicht unter «Vorgangstypen, die beim Limit zählen» stand. Jetzt bleiben sie im Panel und auf dem Board, mit dem Hinweis «zählt nicht».

### Korrigiert
- Ein Klick auf eine Board-Karte öffnete die Details und schloss sie im selben Moment wieder. Jetzt bleiben sie offen.

### Grenzen
- Die Gruppierung ist nur gegen nachgebaute Jira-Daten getestet. Welchen Link-Typ ihr für Begleittickets nutzt, zeigt erst euer Jira.
- Gruppiert werden nur Tickets, die in Arbeit sind. Ein Begleitticket in «Offen» bleibt ausserhalb.
- Ein Agent bekommt den Auftrag aus dem Task-Ticket. Die Beschreibung der Begleittickets geht noch nicht mit.

## [0.29.0]

### Neu
- **In BCS buchen über deine Middleware** (Workflow-API `/api/v1`, nur auf diesem Rechner). Der Ablauf folgt der Middleware:
  1. Entwürfe wie bisher **bestätigen**. Das bucht noch nichts.
  2. Je Entwurf einmal **«BCS-Aufgabe wählen»**: Suche in BCS und «oft gebucht». Mit «für alle DLP-… merken» gilt die Zuordnung fürs ganze Projekt; Fokusbereiche wie «Berufsbildung» bekommen ihre eigene.
  3. **«In BCS prüfen»**: Alle bestätigten Buchungen des Tages gehen gemeinsam in die Vorschau. Warnungen, Kandidaten und ein Probelauf der Middleware stehen im Dialog.
  4. **«In BCS buchen»**: genau ein Versuch, nur mit der Vorschau, die tinyops selbst geprüft hat, und nur, wenn sich seither kein Entwurf geändert hat. Nur «committed» gilt als gebucht.
- **Nie doppelt buchen:** Bricht die Verbindung beim Buchen ab, werden die Entwürfe **«unklar»** und gesperrt. tinyops wiederholt nie von selbst. «Mit BCS abgleichen» liest den Tag: Was dort steht, gilt als gebucht, der Rest geht zurück auf «bestätigt».
- **BCS in der Zeit-Ansicht:** Anwesenheit, in BCS gebucht, nicht verteilt, Wochenstand, Warnungen der Middleware und die Einträge des Tages.
- **Lernende** (nur lesen): Wochen- und Jahressaldo sowie Ferien übrig für die Lernenden, die BCS dir zeigt.
- **Texte vorschlagen:** Das eingestellte Sprachmodell (z. B. Qwen lokal) schlägt kurze Buchungstexte vor. Übernommen wird nur, was du anklickst.
- Selbsttest prüft den BCS-Ablauf gegen die Demo-Middleware.

### Sicherheit
- Nur Adressen auf 127.0.0.1 oder localhost, ohne Proxy. Mitgeschickt wird höchstens das `BCS_API_TOKEN` der Middleware, nie BCS-Zugangsdaten.
- Löschungen schlägt tinyops nie vor. Würde eine Vorschau etwas löschen, bucht tinyops nicht.
- Jeder Schritt steht im Protokoll: Zuordnung, Prüfen, Buchen, Abgleich.

### Grenzen
- Gegen deine echte Middleware ist das nicht gelaufen, nur gegen einen Nachbau nach der Spezifikation 0.7.7 und gegen die Demo.
- tinyops bucht Arbeit als Dauer, ohne Von–bis. Braucht BCS Zeiten, meldet das die Vorschau.
- Der Abgleich erkennt eine Buchung an Aufgabe, Dauer und Text. Wurde sie in BCS inzwischen geändert, gilt sie als nicht gefunden.
- Der MCP-Zwilling der Middleware (`/mcp/v1`) wird nicht benutzt; er wäre der Weg für Agenten wie Goose.

## [0.28.0]

### Neu
- **Microsoft 365 (Mail, Kalender, Teams) über Graph.** Anmeldung als du selbst im Browser mit 2FA (OAuth mit PKCE, Rückleitung auf `http://localhost`), ersatzweise mit Gerätecode. Gespeichert wird nur das Refresh-Token; neu anmelden musst du erst, wenn Microsoft es verlangt.
  - **Heute** im Fokus: deine Termine, der nächste mit «In 8 min», «Beitreten» kurz vor Beginn. Abgesagte und abgelehnte Termine fehlen.
  - **Wartet auf dich:** Mails direkt an dich, nicht von dir, nicht von no-reply und noch nicht beantwortet (Exchange merkt sich die letzte Antwort), dazu alles mit Fähnchen und ungelesene Teams-Chats. Ein Klick öffnet Outlook bzw. Teams.
  - **Termin als Zeit:** Vergangene Termine von heute mit «als Zeit» in die Zeiterfassung übernehmen, auf ein Ticket oder einen Fokusbereich. Gebucht wird wie immer erst nach deiner Bestätigung des Entwurfs.
  - **Fokuszeit im Kalender:** Beim Start einer Fokus-Sitzung «Im Kalender als beschäftigt eintragen». Nur wenn in den Einstellungen erlaubt; dann fragt tinyops `Calendars.ReadWrite` statt `Calendars.Read` an.
  - Die Fokus-Leiste sagt «Termin in 8 min: …», wenn während einer Sitzung ein Termin naht.
- **Review gibt XP:** Gibst du einen MR aus deiner Review-Liste frei, gibt es einmal 20 XP.
- **Agenten mitlesen:** Claude Code läuft mit `--output-format stream-json --verbose`, Mistral Vibe mit `--output streaming`. Der Lauf-Dialog zeigt daraus lesbar, was der Agent tut (Werkzeug, Befehl, Datei, Fehler, Ergebnis). Python-Programme laufen ungepuffert.
- **Vibe-Hinweis:** Ohne `--auto-approve` lehnt Vibe Werkzeugaufrufe ab. Der Dialog warnt, wie bei Claude Code und Codex.
- **Mistral-Abo direkt öffnen:** Link auf admin.mistral.ai/subscription im KI-Kontingent und beim Lesezeichen.

### Korrigiert
- Fehlende Logos wurden alle fünf Sekunden neu angefragt (`/logo/jira`, `/logo/gl` → 404 im Log). Jetzt einmal je Seitenaufruf; `gl` zeigt auf das GitLab-Logo.
- Tote Klicks aus dem Nutzungsbericht: Fundstellen des Geheimnis-Scans kopieren auf Klick «Datei:Zeile»; die Hilfe zu festen Wochenblöcken nennt das Format.

### Grenzen
- Microsoft 365 ist nur gegen einen nachgebauten Graph-Server getestet. Ob eure Richtlinien (Conditional Access, Zustimmung durch Admin) die Anmeldung zulassen, zeigt erst der erste echte Versuch.
- «Wartet auf dich» ist eine Faustregel: Antworten aus einem anderen Programm oder vom Handy erkennt Exchange nicht immer.
- Teams: nur ob ein Chat ungelesen ist, keine Erwähnungen in Kanälen (dafür bräuchte es weitere Rechte).
- Das Streaming-Format von Vibe ist nicht dokumentiert. tinyops zeigt bekannte Felder lesbar, Unbekanntes gekürzt als JSON.
- Wer im tmux mitliest, sieht bei Claude Code und Vibe jetzt JSON-Zeilen statt Text.

## [0.27.0]

### Neu
- **Projekte beim Agenten:** Der Zuweisen-Dialog sieht nach, ob das Projekt im Arbeitsordner des Agenten liegt (lokal oder über SSH). Die Projektauswahl zeigt «fehlt beim Agenten».
  - **Jetzt klonen:** Fehlt ein Projekt, klont tinyops es auf deinen Klick beim Agenten, über SSH oder HTTPS (je Agent einstellbar: «Klonen über»). Der Klon läuft im Hintergrund, Start und Ergebnis stehen im Protokoll (`agent.clone.start`, `agent.clone`).
  - Geklont wird mit den Git-Zugangsdaten des Zielrechners. tinyops gibt kein Token weiter und überschreibt keinen vorhandenen Ordner. Fehlermeldungen nennen den nächsten Schritt (Host-Schlüssel, Deploy-Key, Credential Helper).
  - Liegt im Ordner ein anderes Repository als erwartet, steht das im Dialog.
- **Goose mit Anbieter und Modell je Agent:** Neues Feld «Anbieter» (`GOOSE_PROVIDER`). Leer heisst: Goose nimmt seine eigene Konfiguration, tinyops setzt nur `GOOSE_MODEL`. So gehen mehrere Modelle über denselben Proxy: je Modell ein Agent.
  - Ob ein Modell lokal ist, sagst du je Agent mit dem Haken «sendet Daten an einen Cloud-Anbieter». Nur Agenten ohne Haken dürfen an `restricted`-Projekte.
  - Sieht der Modellname eines «lokalen» Agenten nach einem Cloud-Modell aus (claude, gpt, gemini …), warnt der Dialog, und `restricted`-Projekte bleiben gesperrt.
- **Geheimnis-Scan vor dem Push:** Workspaces prüft ungepushte Commits und offene Änderungen auf Passwörter, Tokens und Schlüssel. Funde stehen am Repo («1 Geheimnis?»), in der Karte «Nicht gepusht» und im Ergebnis eines Agenten-Laufs. Gezeigt werden Datei, Zeile, Regel und Länge, nie der Wert.
- **Vorprüfen lassen:** Aus einem beendeten Lauf startest du einen zweiten Agenten (gut: das lokale Modell), der das Ergebnis nur liest, die Akzeptanzkriterien selbst beurteilt und einen Befund schreibt.
- **Hilfe in den Einstellungen:** Jeder Abschnitt hat eine aufklappbare Anleitung, darunter SSH für Agenten Schritt für Schritt mit den häufigen Fehlern.

### Geändert
- **Fokus-Leiste nur bei laufender Sitzung.** Ohne Fokus-Sitzung gibt es keine Leiste mehr («Jetzt wäre …» und «Zeit läuft» sind weg).
- **Eine Fokus-Sitzung endet von selbst:** zehn Minuten nach der Zeitbox (die Zeit auf der Aufgabe läuft weiter), wenn die Zeit auf eine andere Aufgabe wechselt, oder wenn das Panel länger als die Leerlauf-Minuten nicht erreichbar war. Das Panel sagt dann, warum.
- Ist die Zeitbox vorbei, zählt die Uhr nicht mehr ins Minus: Die Leiste zeigt «vorbei», «+15 min» und «Abschliessen».
- Eine laufende Sitzung gilt als Lebenszeichen: Die Zeit zählt auch, wenn du im Editor arbeitest und das Panel nicht anfasst.

### Grenzen
- Klonen ist nur gegen ein lokales Test-Repository geprüft, nicht gegen dein GitLab und nicht über deine SSH-Verbindung.
- Goose ist nicht mit dem echten Programm gestartet. Welche Anbieternamen dein Goose kennt, zeigt `goose configure`.
- Der Geheimnis-Scan erkennt Muster. Ein Fund kann falsch sein, kein Fund ist kein Freibrief. Neue, noch nicht versionierte Dateien sieht er erst nach `git add`.
- Die Cloud-Erkennung am Modellnamen ist ein Netz für Tippfehler, keine Garantie: Massgeblich bleibt dein Haken je Agent.
- Die Vorprüfung ist ein zweiter Agentenlauf, kein Ersatz für dein Review.

## [0.26.0]

### Neu
- **Auftrag aus dem Ticket:** Weist du einem Ticket einen Agenten zu, liest tinyops Beschreibung, Akzeptanzkriterien und die letzten Kommentare und baut daraus den Prompt.
  - Akzeptanzkriterien kommen aus dem Abschnitt «Akzeptanzkriterien», «Abnahmekriterien», «Acceptance Criteria» oder «Definition of Done» (Jira-Markup oder Markdown) und werden nummeriert: AK1, AK2 …
  - Im Dialog wählst du per Haken, was mitgeht: Beschreibung, Kommentare, jedes Kriterium einzeln. Der Prompt bleibt lesbar und änderbar.
  - Lokale Aufgaben: die offenen Teilschritte sind die Kriterien. Helpdesk-Tickets gehen genauso.
- **Meldung je Kriterium:** Der Agent meldet mit dem neuen `tinyops-ak <Nr> erfüllt|offen|unklar "Beleg"` den Stand jedes Kriteriums. Im Lauf steht je Kriterium Stand und Beleg, auf der Karte «2/3 AK».
- **Änderungen des Laufs:** Commits, geänderte Dateien, Umfang und nicht committete Dateien gegenüber dem Ausgangsstand (Worktree und Export).
- **Nachbessern:** Aus einem beendeten Lauf startest du einen neuen mit den offenen Kriterien, den fehlgeschlagenen Belegen und deiner Anmerkung. Er baut auf dem Branch des ersten Laufs auf.
- **Als Ticket-Kommentar kopieren:** Ergebnis als Entwurf in Jira-Markup in die Zwischenablage. tinyops schreibt nichts ins Ticket.
- **Hinweis zu Schreibrechten:** Fehlt bei Claude Code `--permission-mode …` oder bei Codex `--full-auto` in den zusätzlichen Argumenten, steht das vor dem Start im Dialog.
- Der nächste Schritt im Fokus nennt bei einem fertigen Lauf, wie viele Kriterien als erfüllt gemeldet sind.

### Sicherheit
- Tickettext steht im Prompt in einem markierten Datenblock; der Agent bekommt gesagt, dass darin keine Anweisungen stehen. Kriterien liest tinyops nie aus diesem Block.
- Offensichtliche Geheimnisse im Tickettext (Passwörter, Tokens, Schlüssel, Zugangsdaten in URLs) werden vor dem Prompt geschwärzt, die Zahl steht im Dialog.
- Helpdesk-Beschreibungen gehen an einen Cloud-Agenten erst nach deinem Haken. Kommentare gehen nie ungefragt mit.
- Jira wird dafür nur gelesen (ein GET je Ticket, zwei Minuten gemerkt).

### Grenzen
- «Erfüllt» ist die Angabe des Agenten. Belegt ist nur, was über `tinyops-check` lief.
- Die Schwärzung erkennt Muster, nicht jedes Geheimnis. Lies den Prompt vor dem Start bei Cloud-Agenten durch.
- Die Aufrufe von Claude Code, Codex und Mistral Vibe sind nicht gegen die echten Programme getestet; der Hinweis zu den Schreibrechten folgt deren Dokumentation.
- Im Modus «gemeinsamer Ordner» gibt es keine Änderungsübersicht (kein Ausgangsstand).

## [0.25.0]

### Neu
- **Workspaces** (neuer Tab): Was liegt lokal und ist noch nicht gepusht?
  - Ein Workspace ist ein Ordner, dessen Unterordner deine Projekte sind. tinyops durchsucht ihn bis zur eingestellten Tiefe (Standard 3) nach Git-Repos.
  - Je Repo: Commits, die auf keinem Remote liegen, Branches ohne Upstream, offene Dateien (geändert, vorgemerkt, neu), Stashes mit Alter und «hinter Upstream».
  - Repos mit lokaler Arbeit stehen oben, das älteste zuerst. Ab dem eingestellten Alter (Standard 2 Tage) sind sie rot, und der Tab zeigt ihre Zahl.
  - Aufgeklappt: alle Branches mit Upstream, voraus/hinter und Alter, dazu der `git push`-Befehl zum Kopieren.
  - Im Fokus meldet die Karte «Nicht gepusht» in der Seitenleiste, wo etwas liegt.
- **Herkunft je Repo:** GitLab, GitHub, anderer Host oder kein Remote. Repos, die tinyops nicht als Projekt kennt, sind mit «nicht in tinyops» markiert und haben einen eigenen Filter.
- **Projekte ohne Git:** Ordner mit `package.json`, `pom.xml`, `pyproject.toml`, `go.mod` und Ähnlichem, aber ohne Git, stehen als «nicht versioniert, nicht gesichert» in einer eigenen Liste.
- **Worktrees der Agenten:** Je Repo siehst du die Worktrees mit Branch, offenen Dateien und dem zugehörigen Lauf. Ein Klick auf den Lauf öffnet ihn.
- **Agent direkt zuweisen:** In der Repo-Zeile einen Agenten wählen, einen Satz zum Auftrag schreiben, Basis-Branch wählen. tinyops legt die lokale Aufgabe an und öffnet den gewohnten Auftragsdialog.
  - Das geht nur für eingerichtete Projekte, damit Datenklasse und Agenten-Regeln gelten. Cloud-Agenten sind bei `restricted` gesperrt.
- **Abholen:** `git fetch --prune` je Repo auf Knopfdruck, im Verlauf festgehalten.
- **Einstellungen → Workspaces:** Ordner, Suchtiefe, Meldealter, Abstand der Scans. Die Arbeitsordner lokaler Agenten und die Ordner über deinen lokalen Klonen kommen von selbst dazu.

### Sicherheit
- tinyops liest die Repos nur: ohne Index-Lock, ohne Netz. Es pusht, committet und wechselt nie einen Branch. Ein Test prüft das.
- Zugangsdaten in Remote-Adressen (`https://user:token@host/…`) werden weder gezeigt noch geloggt.

### Grenzen
- «Voraus» und «hinter» gelten für den Stand des letzten Abholens.
- Workspaces auf anderen Rechnern (Agenten über SSH) werden noch nicht durchsucht.

## [0.24.0]

### Neu
- **Helpdesk-Tickets im Panel lesen.** «Ticket ansehen» öffnet die Details in tinyops statt in einem neuen Tab: Beschreibung und die letzten fünf Kommentare, nur lesend. «Im Helpdesk öffnen» führt weiterhin zu Jira, dort antwortest du.
- **Ich beobachte (Watcher).** Eine dritte Liste zeigt Tickets, bei denen du Beobachter bist, die aber jemand anderes bearbeitet.
  - Ein Ticket ist fett, wenn es sich seit deinem letzten Blick geändert hat. Öffnen oder «Alle gesehen» nimmt das Fett weg.
  - Die Abfrage steht in Einstellungen → Helpdesk und ist ab Werk an. Leer heisst aus.
  - Auch Queue-Tickets lassen sich jetzt im Panel lesen.
- **Fokus-Leiste.** Unter der Kopfzeile steht in jeder Ansicht ein breiter Balken, der sagt, woran du bist oder sein solltest. Er ersetzt die kleine Uhr und das Block-Band im Fokus.
  - Sitzung klein gemacht: Bereich, Aufgabe, Tätigkeit, Restzeit und Fortschritt. Ein Klick öffnet den Fokus-Modus.
  - Fester Block ohne Sitzung: «Jetzt wäre: Berufsbildung-Block bis 17:00» mit «Block starten», dazu woran du stattdessen bist.
  - Zeit läuft ohne Zeitbox: Aufgabe, Bereich und die Zeit von heute, mit «Fokus-Sitzung».
  - Passt die Sitzung nicht zum laufenden Block, steht das Soll daneben.
- **Vorschläge für die Helpdesk-Abfragen.** Unter jedem der drei JQL-Felder setzen Knöpfe eine fertige Abfrage ein. Die Felder heissen jetzt «Meine Tickets», «Queue» und «Ich beobachte».

### Geändert (aus dem Nutzungsbericht)
- Ein Klick neben das Detail-Panel schliesst es.
- Die Tempo-Zeile im KI-Kontingent erklärt sich beim Klick. Der Spielstand klappt beim Klick den Verlauf auf.
- Der Nutzungsbericht nennt bei toten Klicks den Ort (z. B. «span in focus / rcard.score»).
- Klicks auf die grosse Fokus-Karte zählten im Bericht fälschlich als tote Klicks. Sie öffnen die Details und werden jetzt richtig gezählt.

### Behoben
- Beim allerersten Start konnte der Abgleich mit «duplicate column name» abbrechen, wenn zwei Abläufe die Datenbank gleichzeitig anlegten. Der Stand blieb dann bis zum nächsten Abgleich leer.

## [0.23.0]

### Neu
- **Helpdesk-Jira** (Einstellungen → Helpdesk), eine zweite Jira-Instanz, nur lesend. Gedacht für Jira 8.5: Anmeldung mit Benutzername und Passwort, Bearer-Token ab 8.14.
  - **Dir zugewiesene Tickets** stehen im Fokus in einer eigenen Gruppe. Sortiert wird nach Priorität, SLA und Alter. Über dem SLA steigt ein Ticket nach oben und ist rot markiert, «Waiting for customer» heisst «Antwort prüfen».
  - **Queue:** Eine eigene JQL (z. B. nicht zugewiesene Tickets) meldet Neues fett, bis du «Alle gesehen» drückst.
  - **Zeit:** Ein angeheftetes Helpdesk-Ticket startet die Zeit auf dieses Ticket, im Bereich Helpdesk. Es erscheint in den Zeitentwürfen wie jedes andere Ticket.
  - «Verbindung testen» liest Serverinfo, Anmeldung und beide JQL. Nach einem Fehlversuch pausiert der Test 30 Sekunden, damit das Konto nicht gesperrt wird.
  - `python3 server.py --check` prüft den Helpdesk mit.
- **Fokusbereiche mit Wochenziel** (Einstellungen → Fokusbereiche). Standard: Entwicklung, Helpdesk, Berufsbildung 30 % von 42 Stunden.
  - Je Bereich: Ziel in Prozent, Tätigkeiten, Kategorien im Board, feste Wochenblöcke («Di 13:30-17:00») und ein Buchungsziel.
  - Zeit gehört zu einem Bereich, wenn sie dort gestartet wurde, wenn das Vorhaben in einer seiner Kategorien liegt oder wenn es ein Helpdesk-Ticket ist. Alles andere ist Entwicklung.
  - **Fokuszeit diese Woche** in der Seitenleiste: Ist je Bereich, Ziel, ein Strich für «Soll bis jetzt» und «x h hinter Plan». Das Soll wird anteilig auf die vergangene Arbeitszeit gerechnet (Arbeitstage 08–17 Uhr).
  - Läuft gerade ein fester Block, zeigt der Fokus oben ein Band «Berufsbildung-Block bis 17:00» mit «Block starten».
- **Fokus-Sitzung und Fokus-Modus** («Fokus» im Hero, in den Details oder in der Seitenleiste):
  - Du wählst die Aufgabe (oder einen Bereich), eine Tätigkeit (z. B. «Aufgaben reviewen») und 25, 50 oder 90 Minuten.
  - Der Fokus-Modus zeigt nur noch Uhr, Aufgabe, Tätigkeit und ein Feld «Gedanken parken» (landet in der Ideenbox). Tastenkürzel des Panels sind aus.
  - «Klein machen» lässt die Sitzung als Uhr in der Kopfzeile weiterlaufen.
  - Abschluss mit «Erledigt», «Beenden, Zeit läuft weiter», «Abgelenkt worden» oder «Abbrechen». Ab 20 Minuten gibt es +15 XP.
  - Die Tätigkeiten landen im Text der Zeitentwürfe. Start und Ende stehen im Verlauf.
- **Releases ohne Tag-Push:** Der neue Workflow «Auto-Tag» setzt nach einem Push auf `main` den Tag `vX.Y.Z` aus `VERSION` selbst, wenn es ihn noch nicht gibt und das CHANGELOG den Abschnitt hat, und baut gleich das Release. `git push origin main` reicht.

### Geändert
- Zeitabschnitte merken sich Bereich und Tätigkeit. Ein Wechsel der Tätigkeit beginnt einen neuen Abschnitt beim selben Ticket.

### Grenzen
- Mail, Kalender und Teams kommen nicht in diese Version. Geplant für 0.24 ohne Graph-App: Kalender als ICS-Abo, Termine buchen über Outlook- und Teams-Links.
- Das Helpdesk bleibt nur lesend: Kommentare und Statuswechsel machst du im Helpdesk selbst.

## [0.22.0]

### Neu
- **KI-Kontingent mit Zeitmarke:** Jeder Balken hat jetzt einen senkrechten Strich. Er zeigt, wie viel Zeit im Fenster (5 h, Woche, Monat) noch übrig ist; die Füllung zeigt, wie viel Kontingent frei ist.
  - Liegt die Füllung rechts vom Strich, hast du Vorsprung: Es bleibt etwas übrig, das beim Reset verfällt.
  - Liegt sie links davon, verbrauchst du zu schnell.
  - Derselbe Strich steht klein in den Chips der Kopfzeile.
- **Tempo-Zeile darunter:**
  - «Vorsprung: Bei diesem Tempo verfallen etwa 78 %. Du kannst mehr nutzen.»
  - «Zu schnell: Bei diesem Tempo leer in 2 h, 2 h 30 min vor dem Reset.»
  - «Im Plan.»
  - Gerechnet wird mit dem bisherigen Tempo im Fenster, eine Hochrechnung gibt es erst ab 5 % vergangener Zeit.
  - Fensterlängen: Claude 5 h und Woche, Codex aus `limit_window_seconds`, Mistral der Monat vor dem Reset.
- **UI-Nutzung lokal erfassen** (Einstellungen → Weiteres, Standard an, 30 Tage aufbewahrt):
  - Erfasst werden Klicks mit einer Beschreibung des Elements: Art, id, data-Attribut, Beschriftung von Knöpfen, Ziffern als `#`.
  - Dazu Position, Zögern vom Hovern bis zum Klick, Ansicht und Bereich, tote Klicks und Tasten ausserhalb von Feldern.
  - Dazu Dialoge auf/zu, Ansichtswechsel, Mausweg und eine grobe Verteilung (12 × 8) je Ansicht, Fenstergrösse und JavaScript-Fehler.
  - **Nie** erfasst: Text aus Eingabefeldern (nur die Anzahl Tasten), Titel von Zeilen und Karten. Bekannte Token-Formen werden geschwärzt.
- **Bericht im Tab «Prüfen»** (heute, 7 oder 30 Tage), mit «Bericht kopieren» und «Daten löschen». Ausgewertet werden:
  - Sitzungen und aktive Minuten, Anteil je Ansicht, häufige Wechsel
  - Aktionen mit Median des Zögerns, tote Klicks, Wutklicks (3+ in 1,5 s)
  - Tasten, Eingaben, Dialoge (wie oft ohne Aktion wieder zu), Maus-Verteilung als Textbild, Fehler
  - «Auffällig» fasst die stärksten Signale zusammen
  - Gedacht zum Kopieren in den nächsten Auftrag an mich, für die UI-Optimierung. Sonst verlässt nichts den Rechner.

### Grenzen
- Das Zögern misst vom Hovern bis zum Klick. Wer mit der Tastatur arbeitet, erscheint dort nicht, die Tasten aber schon.
- Gesendet wird alle 15 s und beim Verlassen der Seite. Ein Absturz des Browsers verliert höchstens diese 15 s.
- Das Tempo setzt gleichmässige Nutzung voraus. Ein Arbeitstag mit Pausen verzerrt die Hochrechnung im Wochenfenster.

## [0.21.1]

### Neu
- **Launcher zum Herunterladen:** `tinyops-launcher` für Linux, macOS und Windows (`.exe`), dazu `tinyops-launcher.pyz` für jedes Python.
  - Beim ersten Start klont er https://github.com/AdBuch/tinyops (ohne die Blobs der alten Historie) auf das neueste Release. Der Ordner ist `~/.local/share/tinyops/app`, unter Windows `%LOCALAPPDATA%\tinyops\app`, oder was du mit `--dir` angibst.
  - Danach übernimmt `start.py`: neue Releases holen, Selbsttest, bei Fehlern zurück.
  - Er öffnet den Browser, sobald tinyops antwortet. Optionen wie `--demo` gehen an tinyops durch.
  - `--where` zeigt Ordner, Repo, Version und Python. Fehlen git oder Python 3.10+, sagt er, wie man sie installiert (winget, brew, apt).
  - Einen fremden, nicht leeren Ordner fasst er nicht an.
- **GitHub Actions:**
  - `tests.yml` lässt bei jedem Push auf `main` und bei Pull Requests die Tests und den Selbsttest laufen.
  - `release.yml` baut bei jedem Tag `vX.Y.Z` nach den Tests die Launcher mit PyInstaller auf Linux, macOS und Windows. Dann veröffentlicht es sie mit der Zipapp und dem CHANGELOG-Abschnitt als GitHub-Release.
- `python3 launcher/build.py` baut die Zipapp lokal nach `dist/`.

### Geändert
- Eine interne IP-Adresse in MANUAL-TESTS und im NetworkPolicy-Beispiel durch eine Beispieladresse ersetzt (das Repo ist öffentlich).

### Grenzen
- tinyops selbst läuft mit dem Python des Rechners, auch wenn der Launcher eine .exe ist. Ein Rechner ohne Python braucht es also zuerst.
- Die nativen Programme entstehen erst in der GitHub Action. Hier geprüft sind der Launcher als Skript und als Zipapp, nicht die PyInstaller-Builds.
- Die Programme sind nicht signiert. Windows SmartScreen und macOS Gatekeeper warnen beim ersten Start (macOS: Rechtsklick → Öffnen).

## [0.21.0]

### Neu
- **Starter mit Update:** `python3 start.py` (Windows `start.cmd`). Der Starter holt die Tags von der Remote (`origin` oder `git config tinyops.remote`) und wechselt auf das neueste Release `vX.Y.Z`. Dann prüft er es mit `server.py --selftest` und startet tinyops; Optionen gehen an `server.py` durch.
  - Schlägt der Selbsttest fehl, geht es automatisch zurück auf die vorige Version, mit den fehlgeschlagenen Prüfungen in der Konsole.
  - Kein Update bei geänderten Dateien im Checkout, auf einem Branch (dort wird entwickelt), ohne Release-Tags oder ohne Netz. In jedem Fall startet die vorhandene Version, mit einem Hinweis, warum.
  - Ignorierte Dateien wie `config.json` stören nicht.
  - `--check` zeigt nur, ob es Neues gibt. `--no-update` startet ohne Netz. `--channel main` spult `main` vor (für Entwicklung). `--verify` verlangt signierte Tags.
  - Nur Standardbibliothek, ohne Import aus tinyops, damit ein kaputtes Update den Starter nicht trifft. Nimmt `.venv`, wenn vorhanden.
- **Hinweis im Panel nach einem Update:** einmal «Aktualisiert auf vX.Y.Z (vorher …) · N neue Prüfpunkte», mit «Jetzt prüfen» (Tab «Prüfen») und «Was ist neu?» (CHANGELOG seit der alten Version).
  - Ein fehlgeschlagenes Update steht dort mit dem Grund.
  - Der Hinweis verschwindet nach «×» oder nach 7 Tagen.

### Grenzen
- Der Starter aktualisiert nur beim Start. Ein laufendes tinyops merkt nichts von neuen Releases.
- Die Datenbank wird nur erweitert (neue Spalten und Tabellen). Ein Zurück auf eine ältere Version funktioniert deshalb, neue Daten bleiben dabei ungenutzt.
- Ohne `--verify` vertraut der Starter jedem Tag in der Remote. Wer dort pushen darf, bestimmt, was bei dir läuft.

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
