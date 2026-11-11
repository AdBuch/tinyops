# tinyops Roadmap 0.15 – 0.20

**Stand:** 2026-11-05 · **Grundlage:** `docs/reviews/cockpit-gap-analysis.md` (Gaps T-1 … T-6, SEC-1 … SEC-6) und die geklärten Fragen unten.
**Regel wie bisher:** jede Version minor, getestet gegen Mock-Server, Handtests in `MANUAL-TESTS.md`, Bundle mit Tag.
Grössen: S = ein Tag, M = zwei bis drei Tage, L = eine Woche (Arbeit an tinyops, nicht Kalenderzeit).

## Geklärte Entscheidungen (2026-11-05)

| Frage | Entscheid | Folge für den Plan |
|---|---|---|
| Agenten auf DLP-/Restricted-Repos? | **Ja, nur mit lokalen Modellen** | Isolation und Datenklassen werden P0 und kommen früh (0.16). Bis dahin laufen lokale Agenten auf DLP-Repos ohne Isolation: nur auf einer eigenen VM oder gar nicht |
| GitLab schreiben? | **Nein, bleibt nur lesend** | kein Approve, Ready oder Merge; F-19 und G3 bleiben N/A. Gates zeigen nur an, wann du in GitLab handeln kannst |
| Agenten-Weg | **SSH/tmux härten** | Worktree je Lauf, Zeitlimit, Datenklasse, optional eigener Agent-Benutzer; kein CI-Gateway |
| Lokale Agenten | **Goose + Ollama, opencode, eigener Befehl, evtl. LangGraph** | Vorlagen für Goose und opencode; LangGraph und Ähnliches über «eigener Befehl» |
| Projectron | **eigener MCP-Server (TypeScript, mit Frontend)** | tinyops liefert Zeitentwürfe und schreibt nach Bestätigung an die Wrapper-API des MCP (0.19); Vertrag mit dem MCP noch abzustimmen |
| Betrieb | **eigener Rechner** (Entscheid 2026-11-05, ersetzt «Cluster»); möglicherweise später zentrale Datenbank und/oder mehrere Instanzen als Agenten-Cluster | nichts Cluster-Spezifisches vor 0.20; Abschnitt «Nach 0.20» |
| Confluence | **keine Priorität** | nicht im Plan |

## Überblick

| Version | Thema | Gaps | Grösse |
|---|---|---|---|
| **0.15.0** ✓ | Ehrlich und an den Commit gebunden (geliefert 2026-11-05) | T-1, T-4, T-6, Zeitlimit aus T-2 | M |
| **0.16.0** ✓ | Agenten isoliert, Datenklassen (geliefert 2026-11-05; Export statt Sparse-Checkout, siehe unten) | T-2, SEC-1, SEC-2, F-10, F-14 | L |
| **0.17.0** ✓ | Audit und Verlauf (geliefert 2026-11-06) | T-3, SEC-6, F-15 | M |
| **0.18.0** ✓ | Rückfragen und Ergebnisse von Agenten, offene Review-Punkte exportieren (geliefert 2026-11-06) | T-5, F-09 | M |
| **0.19.0** ✓ | Fokus-Zeit und Zeitentwürfe für Projectron, Prüfliste und Selbsttest (geliefert 2026-11-06) | F-20 | M |
| **0.20.0** ✓ | Vom Einfall zum Test: Ideen bewerten, Ticket aus Idee, IntelliJ auf dem MR-Commit (geliefert 2026-11-06) | F-06, F-07, F-17, G9 | M–L |
| **0.21.0** ✓ | Starter mit Update aus dem Repo (ausser Plan, geliefert 2026-11-06) | – | S |
| **0.21.1** ✓ | Launcher zum Herunterladen, GitHub Actions für Tests und Releases (geliefert 2026-11-06) | – | S |
| **0.22.0** ✓ | KI-Tempo mit Zeitmarke, UI-Nutzung lokal erfassen für die UI-Optimierung (geliefert 2026-11-06) | – | S–M |
| **0.23.0** ✓ | Helpdesk-Jira (nur lesend), Fokusbereiche mit Wochenziel (Berufsbildung 30 %), Fokus-Sitzung und Fokus-Modus, Auto-Tag (geliefert 2026-11-07) | – | M |
| **0.24.0** ✓ | Helpdesk im Panel lesen, «Ich beobachte» (Watcher), Fokus-Leiste, Korrekturen aus dem Nutzungsbericht (geliefert 2026-11-10) | – | S–M |
| **0.25.0** ✓ | Workspaces lokal: Unterordner nach Git-Repos durchsuchen (GitLab, GitHub, andere, ohne Git), ungepushte Commits, Uncommittetes, Stashes, Worktrees der Agenten, Agent direkt zuweisen (geliefert 2026-11-10) | – | M |
| **0.26.0** ✓ | Agenten aus tinyops: Auftrag aus Ticket und Akzeptanzkriterien, Meldung je Kriterium (`tinyops-ak`), Änderungen des Laufs, Nachbessern, Kommentar-Entwurf, Hinweis zu Schreibrechten von Claude Code und Codex (geliefert 2026-11-11) | – | M–L |
| **0.27.0** ✓ | Projekte beim Agenten prüfen und klonen, Goose mit Anbieter und Modell je Agent (Qwen über Proxy), Geheimnis-Scan vor dem Push, Vorprüfung durch zweiten Agenten, Fokus-Leiste nur bei laufender Sitzung, Hilfe in allen Einstellungen (geliefert 2026-11-11) | – | M |
| **0.28.0** ✓ | Microsoft 365 über Graph (delegiert, Anmeldung im Browser mit 2FA oder Code): Termine heute, Mail und Teams «wartet auf dich», Termine als Zeit übernehmen, Fokuszeit im Kalender eintragen; Review-XP; Agenten-Streaming für Claude Code und Vibe (geliefert 2026-11-11) | – | L |
| **0.29.0** ✓ | BCS buchen über die lokale Middleware (Workflow-API): Aufgaben zuordnen, Tag gemeinsam prüfen, einmal bestätigen, Abgleich nach Abbruch; BCS-Tageskarte, Lernende (lesen), Buchungstexte vom lokalen Modell (geliefert 2026-11-11) | – | L |

Reihenfolge: 0.15 ist klein und nimmt die falschen Grünmeldungen weg. 0.16 vor 0.17, weil du Agenten auf DLP-Repos willst.
0.17 vor 0.19, weil Zeitbuchungen der erste neue Write nach draussen sind und auditiert sein müssen. 0.18 braucht das Zeitlimit aus 0.15.

---

## 0.15.0 — Ehrlich und an den Commit gebunden

**Ziel:** Kein Grün ohne Beleg und keine Abnahme, die neue Commits überlebt.

1. **Abnahme am Commit (T-1).** «Getestet» speichert je MR/PR den Head-SHA, Zeit, optional Notiz und Umgebung (Tabelle `acceptance`).
   - Neue Commits setzen die Station zurück auf «Testen», mit dem Hinweis «2 neue Commits seit deinem Test am 05.11.».
   - «Fertig» bringt erst nach gültiger Abnahme Punkte.
2. **Unbekannt statt grün (T-4).**
   - Sind Freigaben oder Reviewer nicht lesbar, steht «Freigabe unbekannt» (Warten) da, statt dass die Prüfung entfällt.
   - Im Fokus-Kopf steht je Quelle «Stand vor X min». Einträge einer Quelle mit Fehler sind als «veraltet» markiert.
3. **Zeitlimit für Agenten.** `max_minutes` je Agent (Standard 60). Danach wird die Sitzung beendet (tmux, lokal der Prozessbaum), Status «abgelaufen», Blocker in Fokus.
4. **Fokus anheften (T-6).** «Als Fokus setzen» im Panel; höchstens einer. Blocker anderswo erscheinen als kleiner Hinweis statt den Fokus zu wechseln.
5. **Selbsttest der GitLab-Felder.** Preflight und Verbindungstest prüfen, ob `detailed_merge_status`, `reviewers` und `/approvals` geliefert werden. Damit ist die offene Frage zu GitLab 19.2 beantwortet.

**Abnahme:**
- SHA-Wechsel im Mock macht «Getestet» ungültig.
- 403 auf `/approvals` ergibt «Freigabe unbekannt».
- Ein `sleep 600`-Agent mit 1 Minute Limit endet als «abgelaufen».

**Tests:** `test_flow` (SHA gleich/ungleich, mehrere MRs), Mock-GitLab mit 403, tmux-Timeout-Test, lokaler Prozessbaum-Kill.

## 0.16.0 — Agenten isoliert, Datenklassen

**Ziel:** Lokale Agenten dürfen sicher auf DLP-Repos arbeiten, Cloud-Agenten nachweisbar nicht.

1. **Datenklasse je Projekt/Repo:** `restricted` (Standard für neue Projekte), `internal`, `public`. Ersetzt «Cloud-Agent erlaubt» (Migration: erlaubt → `internal`, sonst `restricted`).
   - `restricted`: nur Agenten mit `cloud: false`. Die Sperre greift bei Zuweisen und Start, serverseitig; der Knopf ist in der Oberfläche gesperrt.
2. **Worktree je Lauf.** `git worktree add <root>/.tinyops-wt/<nr> -b agent/<key>-<nr>` vom Ticket-Branch oder Hauptbranch.
   - Der Hauptcheckout bleibt unberührt; mehrere Läufe im selben Repo blockieren sich nicht mehr.
   - Aufräumen bei «Entfernen»; ungespeicherte Änderungen bleiben als Branch erhalten.
3. **Freigegebene Pfade für Cloud-Agenten** (nur `internal`): ~~optionaler Sparse-Checkout im Worktree~~. **Umgesetzt als Export** (eigenes Git nur mit diesen Pfaden), weil ein Sparse-Checkout über die Git-Objekte alles lesbar lässt. Der Agent sieht dann technisch nur diese Pfade, zum Beispiel `src/main/java/ch/…/util/` plus die zugehörigen Tests.
   - Das ist die Antwort auf «Unit-Tests für ganze Klassen an Codex/Claude», sofern dein DLP-Verantwortlicher das für diese Pfade freigibt (siehe unten).
4. **Vorlagen für lokale Agenten:** Goose (`goose run`), opencode, «eigener Befehl» mit Beispiel für LangGraph. Ollama-Modell je Agent einstellbar.
   - Kennzeichnung «Aufruf nicht gegen die echte CLI getestet», bis du ihn bestätigst.
5. **Eigener Agent-Benutzer** je SSH-Verbindung: Anleitung und Verbindungstest. Der Test prüft, dass der Benutzer nicht auf geschützte Branches pushen kann (`git push --dry-run`) und kein sudo hat.

**Abnahme:**
- Ein Restricted-Projekt lässt sich keinem Cloud-Agenten zuweisen: API 400 und gesperrter Knopf.
- Zwei Läufe im selben Repo laufen parallel in getrennten Worktrees.
- Bei Sparse-Checkout fehlen nicht freigegebene Dateien im Worktree.

**Tests:** echtes git + tmux + ssh-Ersatz, Migrationstest der Config, Policy-Test «restricted nie an cloud».

**Grenze:** Netz-Egress und Dateisystem ausserhalb des Worktrees sichert tinyops nicht. Das bleibt Sache des Hosts (eigener Benutzer, Firewall); die Doku nennt das klar.

## 0.17.0 — Audit und Verlauf ✓

**Ziel:** Jede Aktion nach aussen und jede Entscheidung ist nachvollziehbar.

1. **Tabelle `audit`**, nur anhängend: Zeit, Aktion, Ziel, Details, Ergebnis, Hash des vorherigen Eintrags. Die Hash-Kette macht nachträgliches Ändern erkennbar.
   - Erfasst werden: Jira-Ticket anlegen, Station übersteuern, Schritt erledigt, tiny-Ticket, Abnahme (mit SHA), Agent zuweisen/starten/stoppen/ablaufen (mit Prompt-Hash, Datenklasse, Ziel), Einstellungen gespeichert (ohne Secrets).
2. **Verlauf im Detail-Panel** je Vorhaben, dazu eine Gesamtliste unter «Log».
3. **Export als JSON** und **Prüfen der Kette** (`python3 server.py --verify-audit`).
4. **Idempotenz beim Jira-Anlegen:** gleicher Titel im selben Projekt innerhalb von 10 Minuten → Rückfrage statt Duplikat.
5. **Aufbewahrung** für Agenten-Logs: 30 Tage, einstellbar.

**Abnahme:**
- Jede genannte Aktion erzeugt genau einen Eintrag.
- Eine geänderte Zeile meldet `--verify-audit`.
- Keine Secrets im Audit (Schwärzungstest).

**Umgesetzt (2026-11-06):** wie geplant, dazu `--export-audit`, Instanz-Kennung je Eintrag, Erkennung fehlender letzter Einträge, Audit von Deploy/Teardown, Kategorien und Agent-Ende. Teilschritte bleiben ausserhalb des Audits (nur Spielstand).

## 0.18.0 — Rückfragen und Ergebnisse von Agenten ✓

**Ziel:** Agenten fragen statt raten, und das Ergebnis ist ohne Log-Lesen klar.

1. **Frage-Konvention:** Der Agent schreibt `$R/<nr>.question.json` (Frage, Optionen, blockierend) und wartet auf `$R/<nr>.answer`.
   - Die Vorlage in `prompts/agent-task.md` erklärt das. Für Goose und opencode gibt es ein kleines Hilfsskript `tinyops-ask`.
2. **Status «wartet auf Antwort»:** erscheint einmal unter «Du bist dran», Antwort im Panel. Ohne Antwort nach dem Zeitlimit → «abgelaufen», keine Schleife.
3. **Ergebnisbericht:** `$R/<nr>.summary.md` (was geändert, was getestet, was offen) wird im Panel gezeigt. Exit-Codes von Tests, die der Agent über `tinyops-check <befehl>` laufen lässt, gelten als Beleg; Behauptungen ohne Exit-Code nicht (F-11).

**Abnahme:** Ein Skript-Agent fragt, bekommt die Antwort und läuft weiter. Eine Frage erscheint genau einmal. Der Bericht erscheint im Panel.

**Umgesetzt (2026-11-06):**
- wie geplant, Hilfsskripte `tinyops-ask`, `tinyops-check` und `tinyops-report` in reinem `sh` für alle Agenten
- `tinyops-ask` mit Zeitlimit und `--wait`, damit Werkzeug-Timeouts der CLIs nicht neue Fragen erzeugen
- «Ergebnis prüfen» auch nach dem MR, bis der Lauf geöffnet wurde

**Dazu, auf Wunsch:** Offene Review-Punkte eines MR/PR mit Zielangaben (Datei, Zeile, Commit, Branch, Zielbranch) als Prompt (Markdown) oder JSON exportieren oder direkt einem Agenten geben.
- GitLab-Threads per GET; GitHub-Kommentare per REST (Erledigt-Status dort unbekannt).
- Im Export-Modus nur Punkte innerhalb der Cloud-Pfade. Jeder Export steht im Verlauf.

## 0.19.0 — Fokus-Zeit und Zeitentwürfe für Projectron ✓

**Ziel:** Zeit fällt beim Arbeiten an; gebucht wird nur nach Bestätigung, über deinen MCP.

1. **Fokus-Zeit:** Den Fokus anheften (0.15) startet einen Timer für dieses Vorhaben; ein Wechsel stoppt ihn.
   - Pausen über 15 Minuten ohne Panel-Aktivität werden als Lücke vorgeschlagen, nicht stillschweigend gezählt.
   - Agentenlaufzeit zählt **nicht** als Arbeitszeit.
2. **Zeitentwürfe je Tag:** Ticket, Dauer (auf 15 min gerundet, einstellbar), Text aus Titel und erledigten Schritten, Belege (Stationen, Commits, Abnahmen). Bearbeiten, zusammenlegen, verwerfen, bestätigen.
3. **Übergabe an deinen MCP**, in beide Richtungen:
   - `GET /api/time/drafts?state=confirmed`: dein MCP holt die bestätigten Entwürfe ab.
   - Nach Bestätigung schickt tinyops sie an die **Wrapper-API** deines MCP: Adresse und Token in den Einstellungen, Idempotency-Key je Entwurf, Ergebnis im Audit.
   - Schlägt das fehl, bleibt der Entwurf «bestätigt, nicht gebucht». Eine falsche Erfolgsmeldung gibt es nicht (AC-16).
4. **Vorschlag für den Vertrag** (abzustimmen, bevor 0.19 beginnt):
   ```json
   {"id": "td-2026-11-05-DLP-5351", "date": "2026-11-05", "ticket": "DLP-5351", "project_hint": "dlp-mailhandler",
    "minutes": 135, "text": "Resilient Cache: Tests ergänzt, MR !254 Review", "evidence": ["MR !254 @ a1b2c3d4", "Station Prüfen 10:42"],
    "idempotency_key": "td-2026-11-05-DLP-5351"}
   ```
   Antwort des MCP: `{"id": "...", "status": "booked" | "rejected", "reference": "...", "message": "..."}`.

**Abnahme:**
- Keine Buchung ohne Bestätigung.
- Doppeltes Senden bucht einmal.
- Ist der MCP nicht erreichbar, bleibt der Entwurf erhalten und ist sichtbar.

**Tests:** Mock-MCP (HTTP) mit Erfolg, Fehler und Doppelsendung; Timer-Tests mit simulierter Zeit.

**Umgesetzt (2026-11-06):**
- Vertrag wie vorgeschlagen, als `tinyops.time-entry/1`. Der Idempotency-Key entsteht aus dem Inhalt, damit ein geänderter Entwurf nach einem Fehlschlag nicht am alten Schlüssel hängt.
- Dazu Abholen (`GET /api/time/export`) mit Rückmeldung (`POST /api/time/result`).
- Lücken statt stiller Pausen; ein Browser ohne Lebenszeichen zählt nicht weiter.
- **Noch offen:** Abgleich mit der echten Wrapper-API deines MCP.

**Dazu, auf Wunsch:**
- **Qualität:** Prüfliste `QA-CHECKLIST.md` (Grundprüfung aller Funktionen plus je Release nur das Geänderte) zum Abhaken im Tab «Prüfen».
- **Selbsttest** `--selftest`.
- **Regel ab jetzt:** Jedes Release ergänzt die Prüfliste um einen eigenen Abschnitt (ein Test erzwingt das).

## 0.20.0 — Vom Einfall zum Test ✓

**Ziel:** Die Enden der Strecke schliessen, vorne Ideen, hinten der manuelle Test.

1. **Ideen bewerten (F-06)** mit dem lokalen LLM: Kategorie, Nutzen, Aufwand, Dubletten, Empfehlung. Das Ergebnis wird an der Idee gespeichert; die Bewertung bleibt ein Vorschlag.
2. **Ticket aus Idee (F-07):** Entwurf mit Story, Akzeptanzkriterien, Risiken, Tests und Abhängigkeiten.
   - Anlegen in Jira wie heute nur mit `allow_create`, Bestätigung und Audit; alternativ als tiny-Ticket.
3. **IntelliJ auf dem MR-Commit (F-17):** In der Station «Testen» legt «In IntelliJ öffnen» einen Worktree auf dem genauen Head-SHA an und startet `idea <pfad>`.
   - Geht nur, weil tinyops lokal läuft; nur für konfigurierte Repos; die Abnahme aus 0.15 nimmt diesen SHA.
   - Aufräumen beim Abschliessen.
4. **Review-App-Link (G9):** Die URL des GitLab-Environments zum MR erscheint im Panel, nur lesend; tinyops deployt dafür nichts.

**Abnahme:**
- Eine Idee wird bewertet und als Ticket angelegt; beides steht im Audit.
- «In IntelliJ öffnen» checkt genau den angezeigten SHA aus.

**Umgesetzt (2026-11-06):**
- wie geplant; «Ähnlich» ohne Modell als Ergänzung zur Dubletten-Erkennung des Modells
- Akzeptanzkriterien werden Teilschritte
- der Worktree liegt neben dem Checkout statt darin, damit `git status` sauber bleibt
- Review-App über GitLab-Environments, für GitHub noch nicht

## Nicht im Plan (bewusst)

- Approve, Ready oder Merge in GitLab (Entscheid: nur lesend)
- GitLab-CI als Agenten-Gateway
- Confluence; die API gibt es, siehe Hinweise
- eigener Projectron-Client (das macht dein MCP)
- Umbau auf andere Technik
- Team-Betrieb

## Nach 0.20: eigener Rechner, zentrale Datenbank, Agenten-Cluster

**Entscheid 2026-11-05:** tinyops bleibt auf deinem Rechner. Denkbar sind später eine zentrale Datenbank und mehrere Instanzen, die als Agenten-Cluster arbeiten.
Was das bedeutet, und was bis 0.20 schon darauf vorbereitet:
- **Zentrale Datenbank:** Heute liegt alles in einer SQLite-Datei (`tinyops.db`), Zugriffe laufen über `links.Store`. Eine zweite Implementierung des Stores (PostgreSQL) wäre der Weg; die Tabellen sind schlicht (keine Joins über Systeme).
  Vorbereitung bis 0.20: neue Tabellen nur über den Store, keine SQLite-Besonderheiten in neuem Code; Audit (0.17) mit Instanz-ID je Eintrag.
- **Mehrere Instanzen als Agenten-Cluster:** Heute startet eine Instanz Agenten per SSH. Mehrere Instanzen bräuchten eine gemeinsame Warteschlange (in der zentralen DB) und ein «Claim» je Lauf, damit kein Lauf doppelt startet (Lease aus F-24).
  Vorbereitung bis 0.20: Lauf-IDs und Run-Dateien schon eindeutig je Instanz (`<instanz>-<nr>`), Zustände nur in der DB, nicht im Speicher.
- **Handy über VPN:** Mit Server auf deinem Rechner geht das über den bestehenden Zugriffstoken und eine Freigabe der Adresse im VPN; der Rechner muss dann laufen.

### Frühere Überlegung: Betrieb im Cluster oder anderem Netz, Handy über VPN

Wichtig zur Architektur: **tinyops spricht mit allen Systemen vom Server aus, nicht aus dem Browser.** Der Browser redet nur mit tinyops; einzige Ausnahme ist das Mistral-Lesezeichen.
Wer tinyops verschiebt, verschiebt also auch alle Zugriffe:
- Jira, GitLab, GitHub, Sonar und Ollama müssen von dort erreichbar sein.
- Die Agenten-Hosts müssen per SSH erreichbar sein.
- Die Secrets liegen dann dort (Kubernetes-Secret statt Schlüsselbund).
- Lokale Agenten und «In IntelliJ öffnen» gehen dann nur noch über SSH zu deinem Rechner.

Zwei Wege, Entscheid später:
1. **Server bleibt auf deinem Rechner**, das Handy kommt über das VPN an dessen Port. Das braucht nur das Zugriffstoken, das es schon gibt. Dafür muss der Rechner laufen.
2. **Server im Cluster** mit OIDC-Proxy davor, Netzfreigaben zu allen Systemen, eigene Agent-VM; Image und Manifeste gibt es schon (`deploy/k8s.py`).

Vorbereitung ohne Mehraufwand bis 0.20: Mobile-Ansicht von Fokus pflegen, keine neuen Funktionen, die nur mit lokalem Dateisystem gehen (ausser IntelliJ, bewusst lokal).

## Hinweise zu deinen Rückfragen

- **Confluence-API:** Ja. Confluence Server/Data Center hat eine REST-API (`/rest/api/content`, Suche per CQL über `/rest/api/content/search`).
  Einfacher wären die Remote Links eines Jira-Tickets (`/rest/api/2/issue/{key}/remotelink`), die Confluence-Seiten meist schon verlinken. Das wären etwa S an Aufwand, wenn es später Priorität bekommt.
- **Unit-Tests für ganze Klassen an Codex/Claude:** Eine Klasse ist Quellcode. Nach deiner eigenen Regel («Kundendaten und Teile des Quellcodes nicht in die Cloud») geht das für DLP-Repos nicht.
  Ob einzelne, unkritische Module eines Repos freigegeben werden dürfen, ist eine Entscheidung deines Sicherheits- oder DLP-Verantwortlichen, keine technische. tinyops setzt sie dann durch: Datenklasse `internal` plus freigegebene Pfade per Sparse-Checkout (0.16). Der Cloud-Agent sieht technisch nur diese Dateien.
- **MCP-Integration:** Eine direkte Einbindung des MCP-Protokolls in tinyops ist nicht nötig. Die Wrapper-API deines MCP-Servers (HTTP) reicht, und dein MCP kann umgekehrt die Entwürfe bei tinyops abholen.
  Offen ist nur der Vertrag (Format, Auth, Fehlercodes). Der Vorschlag steht bei 0.19.
