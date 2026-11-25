# tinyops Roadmap

**Stand:** 2026-11-25. Ab hier gilt der Plan 0.33–0.53. Der frühere Plan 0.15–0.20 und alle Releases bis 0.32 stehen weiter unten.

## Plan 0.33 – 0.53: aufräumen, entscheiden, dann wenig Neues

**17.11.:** Auf deinen Wunsch kam vor dem Umbau noch 0.36.0 mit deinen Wünschen und dem Bericht vom 17.11. Alles ab «Server zerlegen» rückt um eine Version nach hinten. Die App (PWA) mit Handy-Kopplung ist aus dem letzten Release vorgezogen; dort bleibt der zweite Bereich.

**20.11.:** Deine drei Schwerpunkte für die nächsten Releases, statt Microsoft 365:
1. **Schneller zum Testen von Hand:** vom fertigen Lauf oder MR mit einem Klick zum Ausprobieren, ohne Befehle zu kopieren (0.42).
2. **Agenten-Gefühl:** die vier Rollen Planen, Entwickeln, Review und Test klar sichtbar, und der Kreislauf zurück zum Entwickeln in derselben Sitzung (0.40).
3. **Reviews:** «Review starten» legt die Punkte als Entwurf in GitLab an (E14), und die Einstellungen zeigen jeden Aufruf, den tinyops nach aussen macht (0.42).

Leitlinie dafür: weniger Kopieren, weniger Wechseln, mehr Fokus. Gemessen wird das im Nutzungsbericht an den Klicks auf «Kopieren» und den Wechseln zwischen Fokus und Einstellungen; beide sollen pro Arbeitstag sinken.
Dafür kamen zwei Releases dazu (0.42 und 0.43). Alles ab «Einstellungen und Datenbank» rückt um zwei Versionen nach hinten. M365 wird in «Echte Anbindungen härten» nur noch gemacht, wenn du es dann brauchst.

**23.11.:** Auf deinen Wunsch kam 0.41.0 dazu: den Branch eines Agenten mit einem Klick in den Feature-Branch des Tickets übernehmen (Fast-Forward, Merge, Rebase, Cherry-Pick). Es gehört zum Kreislauf aus 0.40 und spart Kopieren. Alles danach rückt um eine Version nach hinten.

**23.11., später:** Testen von Hand und Reviews in GitLab kamen zusammen in 0.42.0 (dein Wunsch: «implementier 42 mit den agent-reviews, und testing enhancements»). Alles ab «Einstellungen und Datenbank» rückt eine Version nach vorne; der Plan endet mit 0.48.

**25.11.:** Voice Prompting Wednesday: auf deinen Wunsch kommt 0.43.0 mit Diktieren und Sprachbefehlen an Agenten, alles mit einem lokalen Modell. Das bricht die Regel vom 24.11. («erst die Prüfliste») bewusst, auf deinen Wunsch. Alles ab «Einstellungen und Datenbank» rückt um eine Version nach hinten. Am selben Tag kam 0.44.0 dazu (eingebautes Whisper ohne Grafikkarte); der Plan endet jetzt mit 0.50.

**25.11., abends:** Deine Berichte zu 0.44.1 (Prüfliste 22 geprüft, 0 Fehler; Nutzungsbericht mit fünf Wünschen). Dein Vorschlag: zuerst das Refactoring. Darum bleibt 0.45 «Einstellungen und Datenbank». Danach kommen deine Wünsche in drei Releases (0.46 bis 0.48), vor «Tests und Doku». Alles ab «Tests und Doku» rückt um drei Versionen nach hinten; der Plan endet mit 0.53. Das Agentenpanel (0.47) ist der erste Teil des Redesigns vom 24.11.

**24.11.:** Deine Rückmeldung: «es ist momentan ein bisschen viel». Offen sind Outlook und Teams mit echten Konten zu testen, das Härten der Anbindungen (0.45) und ein **Redesign der Oberfläche** (neu, noch ohne Termin). Bis du die Prüfliste 0.40 bis 0.42 durch hast, kommen nur Korrekturen aus deinen Rückmeldungen (wie 0.42.1), keine neuen Themen. Wo das Redesign hingehört, entscheiden wir danach; ein Kandidat ist der Platz von «Tests und Doku» (seit 25.11.: 0.46), weil Tests und Doku ohnehin dem neuen Aussehen folgen müssten.

**Warum:** Der Plan 0.15–0.20 ist geliefert. Danach kamen 12 Releases in 9 Tagen. Das Testen kam nicht mit, es gibt Doppelungen, und die Kerndateien sind gross: `server.py` hat 5'250 Zeilen, `static/index.html` 4'800, `agents.py` 1'730, `settings.py` 1'630. Das widerspricht dem Ziel «einfach reviewen».

**Regeln für diese Releases**
- **Ein Thema je Release, Grösse S.** Refactoring ändert kein Verhalten. Was sich für dich ändert, steht im Changelog unter «Geändert».
- **Takt:** Das nächste Release beginnt erst, wenn du den Prüfabschnitt des vorigen durch hast, oder nach drei Tagen ohne Rückmeldung. Höchstens zwei Releases pro Woche.
- **Jedes Release hat höchstens 6 Prüfpunkte von Hand.** Was ein automatischer Test abdeckt, kommt nicht in die Prüfliste.
- **Jedes Release lässt Platz für Korrekturen aus deinen Tests und dem Nutzungsbericht.** Die gehen vor.
- **Löschen ist erlaubt.** Was entfällt, steht im Changelog unter «Entfernt», mit Grund.

### Überblick

| Version | Thema | Art | Entscheid nötig |
|---|---|---|---|
| **0.33.0** ✓ | Sicherheitsnetz: UI-Tests im Repo, Prüfliste auf das reduzieren, was nur ein Mensch prüfen kann (geliefert 2026-11-15: 10 UI-Tests, 59 statt 198 Punkte von Hand) | Aufräumen | – |
| **0.34.0** ✓ | Doppelungen I: eine Review-Umgebung, ein Buchungsweg; dazu Helpdesk-Fehler r23-04, Review-Umgebung vorbefüllt mit Umsystemen, Checkout aus Workspaces (geliefert 2026-11-16) | Entscheid + Entfernen | E1, E2 ✓ |
| **0.35.0** ✓ | Weniger Begriffe: Fokus und Bereiche, Spielstand abschaltbar; dazu tote Klicks, Verbindungshinweis, Worktrees in Workspaces (geliefert 2026-11-16) | Entscheid + Vereinfachen | E3, E4 ✓ |
| **0.36.0** ✓ | Vor dem Umbau: Lauf weiterführen mit Entscheidungen, Agenten mit Rollen/Push/Kontingent, Fokus-Aufgabe als Arbeitsfläche, Helpdesk → Jira, zurückgeschickte Reviews, BCS ohne Wartezeit, App mit Handy-Kopplung (geliefert 2026-11-17) | Wünsche + Korrekturen | E12, E13 ✓ |
| **0.37.0** ✓ | Server zerlegen I: Routentabelle in `routes.py`, Clients und Demo in eigene Module, `server.py` 5'301 → 3'794 Zeilen (geliefert 2026-11-18) | Refactoring | – |
| **0.38.0** ✓ | Server zerlegen II: App in neun Bereiche (`area_*.py`) mit geprüften Querzugriffen, `config.py`, `server.py` 3'794 → 743 Zeilen (geliefert 2026-11-20) | Refactoring | – |
| **0.39.0** ✓ | Oberfläche zerlegen: `index.html` 5'155 Zeilen → HTML, `app.css` und 16 Skriptteile (grösster 808 Zeilen), zusammengesetzt von `ui.py` ohne Build; dazu QR-Code beim Koppeln, Klickbares im Detail-Panel, Agentenfenster als Seitenpanel (geliefert 2026-11-22) | Refactoring + Korrekturen | E6 ✓ |
| **0.40.0** ✓ | Agenten: Gespräch in derselben Sitzung (Claude Code, Codex, Vibe, Goose, opencode), vier Rollen mit «Zurück ans Entwickeln» und «Erneut prüfen», Git-User je Agent, `agents.py` 1'787 → 925 Zeilen in sechs Module; dazu Update aus dem Panel und Dienst unter Linux (geliefert 2026-11-23) | Refactoring + Wünsche | E5 ✓ |
| **0.41.0/0.41.1** ✓ | Agent-Branch übernehmen: im Detail-Panel «Übernehmen in …» mit Fast-Forward, Rebase, Merge oder Cherry-Pick in den Feature-Branch, lokal im eigenen Worktree, Konflikte in IntelliJ lösen; dazu die Korrektur der Handy-Breite in den Einstellungen (geliefert 2026-11-23) | Wunsch | – |
| **0.42.0/0.42.1** ✓ | Testen von Hand und Reviews in GitLab: Prüfliste je Ticket mit «Jetzt testen», Fehler zurück ans Entwickeln; «▶ Review mit Agent» mit Befunden als deine Entwürfe in GitLab (E14); jeder Aufruf nach aussen in den Einstellungen; dazu Korrekturen aus dem Bericht vom 23.11. (geliefert 2026-11-23). 0.42.1: beim Review den Agenten wählen und Ticket und Ziel des MR mitgeben (Rückmeldung vom 24.11.) | Neu + Korrekturen | E14 ✓ |
| **0.43.0** ✓ | Voice Prompting: Mikrofon an den Prompt-Feldern (Auftrag, «Nachricht an …», Review-Ziel, Ideen, Prüfliste), Sprachbefehle an Agenten (zuweisen, starten, Review anstossen) mit Bestätigung; Erkennung nur über einen Server im eigenen Netz (whisper.cpp, Voxtral Mini über vLLM, speaches) (geliefert 2026-11-25) | Wunsch | E15 ✓ |
| **0.44.0/0.44.1** ✓ | Eingebautes Whisper: tinyops baut whisper.cpp für deinen Prozessor, lädt das Modell (small, base, turbo) mit Prüfsumme und startet den Server selbst, nur auf 127.0.0.1; ohne Grafikkarte (geliefert 2026-11-25). 0.44.1: Review-Befunde auch von Agenten ohne `tinyops-finding` (aus dem Bericht gelesen) und vor dem Anlegen bearbeitbar (Rückmeldung vom 25.11.) | Wunsch + Korrektur | E15 ✓ |
| **0.45.0** ✓ | Einstellungen und Datenbank: Datenbank mit Version und nummerierten Migrationen (`dbschema.py`), Zahlenfelder nach Schema, veraltete Einstellungen fallen weg, `settings.py` 1'630 → 600 Zeilen (geliefert 2026-11-25) | Refactoring | – |
| 0.46.0 | Aufräumen und Zugang: Worktrees aufräumen, lokal und auf den Agenten-Rechnern; Zugriff von aussen (Handy) in den Einstellungen, nur mit Zugangsschlüssel; Review-Start ohne Ordner bietet Klonen an | Wünsche + Korrekturen | – |
| 0.47.0 | Agentenpanel neu: Gespräch, Akzeptanzkriterien, Review-Punkte und Log klar getrennt; die vier Vorlagen direkt erreichbar; im Auftrag wählst du, welche Kriterien und Review-Punkte jetzt drankommen | Wunsch (Redesign, Teil 1) | – |
| 0.48.0 | Commits einzeln: Liste je Commit mit dem, was passiert ist; Review je Commit, auch Zeilen-Review auf eigene Tickets | Wunsch | – |
| 0.49.0 | Tests und Doku neu ordnen: nach Modul statt nach Version, README als Handbuch | Aufräumen | – |
| 0.50.0 | Echte Anbindungen härten: BCS, M365, Helpdesk, Agent auf der devops-Maschine | Korrekturen | – |
| 0.51.0 | Neu: weitere Projekte tracken (ausserhalb von Jira/GitLab), tinyops ohne Code-Plattform nutzbar | Neu, klein | – |
| 0.52.0 | Neu: angefangene Projekte aus Claude, ChatGPT und Mistral tracken | Neu, klein | E8 |
| 0.53.0 | Neu: zweiter Bereich (Privat/Geschäft) mit eigenem Worker; die App gibt es seit 0.36 | Neu | E7 |

### Entscheide (mit meiner Empfehlung)

| Nr. | Frage | Empfehlung | Bis |
|---|---|---|---|
| E1 | Buchen: nur BCS oder auch der Projectron-Export (0.19)? | **Entschieden 2026-11-15: nur BCS** | 0.34 |
| E2 | Alte Testumgebung je MR (Kubernetes, standardmässig ausgeblendet) und neue Review-Umgebung (0.32)? | **Entschieden 2026-11-15:** direkt ausführen über die Review-Umgebung, auch für MRs; Prompts und Shell-Befehle bleiben zum Kopieren, falls kein Agent da ist | 0.34 |
| E3 | Spielstand: Punkte, Serie, Review-Punkte behalten? | **Entschieden 2026-11-16:** behalten, eine Karte im Fokus, abschaltbar | 0.35 |
| E4 | Fokus: Fokusbereiche, Wochenziel, Fokus-Sitzung, Fokus-Modus, Fokus-Leiste? | **Entschieden 2026-11-16:** **Fokus** (mit Sitzung) und **Bereiche** (Wochenziel); «Fokus-Modus» heisst «Vollbild» | 0.35 |
| E5 | Standard-Zyklus der Agenten? | **Entschieden 2026-11-16:** Umsetzen → Review, Planen und Test je Ticket zuschaltbar | 0.40 |
| E6 | Oberfläche mit oder ohne Build-Schritt? | **Entschieden 2026-11-16:** Build (React) nur für die eigene Privat-App; die tinyops-Seite bleibt ohne Build | 0.39 |
| E7 | Privat und Geschäft? | **Entschieden 2026-11-16:** zwei lokale Instanzen; die Privat-App in eigenem Repo mit eigenem Release-Zyklus (E7a) | 0.53 |
| E8 | KI-Projekte: woher kommen die Daten? | Lesezeichen und Daten-Export, dazu neu (18.11.): ein Prompt, mit dem die Chat-App deine offenen Themen als JSON liefert, und die lokalen Sitzungen der Coding-Agenten. Nie Browser-Cookies, kein Auslesen fremder Sitzungen | 0.52 |
| E9–E11 | App: React-PWA, HTTPS mit echtem Namen, Heim- und Arbeitsadresse je Instanz | **Entschieden 2026-11-16** (siehe Entscheide) | 0.53 |
| E12 | Dürfen Agenten pushen? | **Entschieden 2026-11-17:** je Agent einschaltbar; nur der eigene Lauf-Branch. tinyops selbst pusht nie | 0.36 |
| E14 | Darf tinyops in GitLab Review-Kommentare anlegen? | **Entschieden 2026-11-20:** nur als deine Entwürfe (`draft_notes`) mit eigenem Token; abschicken, Approve und Merge nie | 0.42 |
| E13 | Wie koppelt sich ein Gerät? | **Entschieden 2026-11-17:** Einmal-Code je Gerät; die tinyops-Seite per Cookie, die eigene React-App per Token und CORS | 0.36 |
| E15 | Sprache: wo wird erkannt, was dürfen Sprachbefehle? | **Entschieden 2026-11-25:** nur ein Modell im eigenen Netz (whisper.cpp oder Voxtral Mini); Befehle dürfen zuweisen, starten und Review anstossen, immer erst nach deiner Bestätigung | 0.43 |

### Die Releases im Einzelnen

**0.33.0 – Sicherheitsnetz**
- Playwright-Tests ins Repo (`tests/ui/`), in CI ausgeführt:
  - Fokus und Listen
  - Agent zuweisen, alle vier Phasen, Freigabe
  - Prüfen und Einstellungen speichern
  - Handy-Breite ohne seitliches Scrollen, keine JavaScript-Fehler
- Ohne Playwright werden die Tests übersprungen.
- Prüfliste: Punkte, die ein Test abdeckt, bekommen `auto` und fallen aus «Als Nächstes testen». Die Grundprüfung schrumpft auf das, was nur ein Mensch beurteilen kann: echte Systeme, Lesbarkeit, Gefühl.
- Neue Datei `docs/DECISIONS.md` mit den Entscheiden E1–E8.
- **Fertig, wenn:** UI-Tests laufen in CI, und weniger als 60 Punkte bleiben von Hand offen.

**0.34.0 – Doppelungen I**
- E2: Review-Umgebung für Agenten-Läufe und MRs aus einem Modul (`reviewenv.py`). Die alte Testumgebung (Helm, Jobs, alte Agenten-Knöpfe) und die Funktion «testenv» entfallen; `deploy/` bleibt (tinyops selbst in Kubernetes). Prompts (Review-Brief, Smoke-Test, Repro-Test) und die Befehle der Review-Umgebung und zum Auschecken bleiben zum Kopieren am MR, für den Fall, dass kein Agent eingerichtet ist.
- E1: nur BCS. Projectron-Export, MCP-Einstellungen und `/api/time/export` entfallen; bestehende Entwürfe bleiben lesbar.
- `usage.py` (KI-Kontingent) und `ux.py` (Nutzung der Oberfläche) bekommen eindeutige Namen.
- **Fertig, wenn:** Jede Funktion gibt es einmal, und der Changelog listet alles Entfernte.

**0.35.0 – Weniger Begriffe** ✓
- E3 und E4 umgesetzt, Texte in Oberfläche und Hilfe angeglichen.
- Ungenutzte Ansichten ausblenden: verschoben. Der Bericht deckt erst sieben Tage ab; neu bewertet wird mit 0.45 (siehe Auswertung unten).
- Dazu aus dem Nutzungsbericht: tote Klicks in Prüfen, Seitenleiste und Workspaces; Verbindungshinweis statt «Panel nicht erreichbar»; Worktrees in Workspaces.
- **Fertig, wenn:** Jeder Begriff in der Oberfläche hat eine Bedeutung. Die kürzere Hauptnavigation folgt erst mit genug Daten.

**0.36.0 – Vor dem Umbau** ✓
- Aus deinen Wünschen vom 17.11.: Lauf direkt weiterführen, Entscheidungsfelder, an denen der Agent wartet; Rollen je Phase (`/planner`, `/developer`, `/reviewer`, `/tester`), Push des eigenen Branches, Kontingent in der Auswahl, Agent auf Aufgabe ziehen; Fokus-Aufgabe als Arbeitsfläche; Helpdesk → Jira; zurückgeschickte Reviews ausblenden; × in jedem Dialog.
- Aus dem Bericht: BCS-Pause statt 73 s Wartezeit, Fetch liest unbekannte Repos selbst neu ein, das Agentenfenster baut sich nicht mehr alle 4 s neu auf (20 Wutklicks).
- Vorgezogen aus dem letzten Release: tinyops als App (PWA) mit Handy-Kopplung. 0.36.2 ergänzt die Kopplung für die eigene React-App (E9, E11): Token statt Cookie, CORS für ihre Adresse.
- **Fertig, wenn:** Prüfabschnitt 0.36 durch, vor allem `r36-01` und `r36-05` mit echten Systemen.

**0.37.0 – Server zerlegen I** ✓ (Routen-Schnappschuss mit 74 Aufrufen, `routes.py`, `common.py`, `httpclient.py`, `gitlab_client.py`, `jira_client.py`, `ideas.py`, `demo.py`)
- `make_handler` (720 Zeilen) wird eine Routentabelle in `routes.py`.
- `GitLabClient`, `JiraClient`, `Http` und `DemoClient` kommen in eigene Module.
- Vorher ein Test, der alle Routen und Antworten festhält, damit nichts verloren geht.
- **Fertig, wenn:** Alle Tests sind grün, die Routen sind unverändert, und `server.py` ist 1'500 Zeilen kürzer.

**0.38.0 – Server zerlegen II** ✓ (Bereiche als Mixins mit `USES`, geprüft von `tests/test_areas.py`; `agents.py` und `settings.py` bleiben bis 0.40/0.44 über 1'000 Zeilen)
- `App` in Bereiche mit klaren Grenzen:
  - Übersicht und Sync
  - Tickets und Ideen
  - Agenten-Anbindung
  - Zeit und BCS
  - Fokus
  - Prüfen
  - Workspaces
  - Microsoft 365
  - IntelliJ und Review-Umgebung
- Gemeinsames (Audit, Cache, Store) wird hineingereicht, kein Zugriff kreuz und quer.
- **Fertig, wenn:** `server.py` ist unter 1'500 Zeilen, und kein Modul hat mehr als 1'000.

**0.39.0 – Oberfläche zerlegen** ✓ (ohne Build: `ui.py` setzt die Teile zu einer Seite mit einem Skript zusammen, so bleibt das Verhalten gleich. Nicht gemacht: doppelte Stile und Dialog-Muster zusammenführen, das kommt mit 0.40/0.42)
- `index.html` wird zu `app.css` und JS-Modulen, je Ansicht eines, plus gemeinsame Bausteine:
  - Dialog
  - Kopieren
  - Markdown
  - Piktogramme
  - Felder
  - Hilfe
- Doppelte Stile und Dialog-Muster werden zusammengeführt.
- Korrektur-Platz aus den Berichten vom 20.11.:
  - **QR-Code beim Koppeln** (Prüfbericht `r36-05`): Adresse und Code als QR, erzeugt ohne Fremdbibliothek.
  - **Klickbares im Detail-Panel:** Branch- und Code-Angaben kopieren beim Klick, Chips filtern (16 tote Klicks).
  - **Agentenfenster als Seitenpanel** statt Dialog (182 Klicks, 24 Wutklicks im Dialog).
- **Fertig, wenn:** Keine Datei hat mehr als 1'200 Zeilen, die UI-Tests aus 0.33 sind grün, und es gibt sichtbar keinen Unterschied.

**0.40.0 – Agenten: vier Rollen und der Kreislauf** ✓ (dazu auf Wunsch vom 23.11.: Update aus dem Panel, Dienst unter Linux. Offen: Fortsetzen gegen die echten Programme prüfen, `r40-01`)
- **Die vier Rollen klar** (Schwerpunkt 2 vom 20.11.): Planen, Entwickeln, Review, Test. Jede Rolle hat einen Namen, eine Farbe, ihren Agenten und ihren Befehl (`/planner`, `/developer`, `/reviewer`, `/tester`). Die Leiste im Lauf zeigt den Kreislauf und wo das Ticket gerade steht.
- **Der Kreislauf zurück zum Entwickeln:** Review-Punkte, fehlgeschlagene Tests und deine Notizen gehen mit einem Klick «Zurück ans Entwickeln» an den Entwickler, in **seine** Sitzung (siehe unten). Kein Kopieren. Danach geht es mit einem Klick wieder ins Review. Jede Runde ist sichtbar: «Runde 2: 3 Review-Punkte erledigt, 1 offen».
- Standard bleibt E5: Entwickeln → Review; Planen und Test schaltest du je Ticket zu. Alle vier stehen trotzdem immer in der Leiste.
- `agents.py` wird aufgeteilt in Verbindung (SSH, tmux, lokal), Hilfsbefehle, Ergebnisse und Phasen.
- Ein Weg für Review, Vorprüfen und Nachbessern. Der alte Parameter `prereview` entfällt.
- E5 umsetzen.
- **Weiterführen in derselben Sitzung** (dein Wunsch vom 18.11., geklärt am 20.11. zu `r36-01`): Der Agent macht mit dem ganzen Kontext weiter, statt neu anzufangen.
  - tinyops merkt sich je Lauf die Sitzung des Agenten und setzt sie fort, im selben Worktree auf demselben Rechner:
    - Claude Code: Start mit `--session-id <id>`, weiter mit `--resume <id>`.
    - Codex: die `thread_id` aus `codex exec --json`, weiter mit `codex exec resume <id> "…"`.
    - Mistral Vibe: weiter mit `--resume <id>`. Woher die ID kommt, prüfe ich gegen dein Vibe; sonst `--continue` im Worktree.
    - Goose und opencode haben eigene Wege (`--resume`, `--session`); ungetestet, deshalb erst nach einem Versuch bei dir.
  - Jede Fortsetzung bleibt ein eigener Eintrag im Lauf (Log, Bericht, Belege, Entscheidungen), gezeigt als «Fortsetzung 2 von #41».
  - Die Sitzung hat einen Namen (Ticket und Phase) und einen Befehl zum Selbst-Öffnen im Terminal.
  - Geht das Fortsetzen nicht (Sitzung gelöscht, anderer Rechner, Agent ohne Sitzungen), bietet tinyops den bisherigen Weg an: neuer Lauf auf demselben Branch mit Zusammenfassung.
- **Git-User je Agent:** Name und E-Mail für Commits, für den Lauf gesetzt (auch auf entfernten Rechnern).
- **Fertig, wenn:** Ein kleines Ticket braucht zwei Klicks bis zum Review, ein Review-Punkt kommt mit einem Klick beim Entwickler an, und «Weiterführen» setzt bei Claude Code und Codex die Sitzung fort (gegen die echten Programme geprüft).

**0.41.0 – Agent-Branch übernehmen** ✓ (Wunsch vom 23.11.)
- Am Branch eines Agenten im Detail-Panel: «Übernehmen in …» mit dem Feature-Branch des Tickets als Ziel (MR-Branches zuerst).
- Vorschau: Commits, Umfang, erwartete Konflikte (`git merge-tree`), ob Fast-Forward geht.
- Fast-Forward, Rebase (Commits obendrauf), Merge oder Cherry-Pick ausgewählter Commits. Gearbeitet wird in einem eigenen Worktree, der Ziel-Branch rückt nur vor. Konflikt: alles zurück, oder der Worktree bleibt zum Lösen in IntelliJ, danach «Abschliessen».
- tinyops pusht nie; der Push-Befehl steht im Ergebnis.

**0.42.0 – Testen von Hand und Reviews in GitLab** ✓ (Schwerpunkte 1 und 3 vom 20.11.; geliefert wie unten, mit diesen Abweichungen: die Prüfliste beginnt schon bei «Prüfen»; «zuerst ansehen» gehört zum Review, nicht in die Prüfliste; beim Review prüft tinyops noch nicht, ob es einen Punkt schon als Thread gibt)
- **«Jetzt testen»** an jedem fertigen Lauf und jedem MR, im Fokus als nächster Schritt. Ein Klick:
  - holt den Stand in einen eigenen Worktree und öffnet ihn in IntelliJ,
  - startet die Review-Umgebung des Projekts (falls eingerichtet),
  - zeigt die **Prüfliste je Ticket**: die Testschritte des Test-Agenten (`tinyops-manual`), die Akzeptanzkriterien und was der Entwickler als «zuerst ansehen» nennt.
- Abhaken mit ok oder Fehler und Notiz, wie in «Prüfen». Ein Fehler geht mit «Zurück ans Entwickeln» samt Notiz an den Entwickler (Kreislauf aus 0.40).
- Alles ok → «Getestet» mit dem Commit (Abnahme wie seit 0.15), die Review-Umgebung lässt sich gleich stoppen.
- Der Fokus zeigt «2 Tickets warten auf deinen Test» weit oben, damit Testen nicht liegen bleibt.
- **Fertig, wenn:** Vom fertigen Lauf bis zum laufenden System in IntelliJ und Review-Umgebung ist es ein Klick, ohne einen Befehl zu kopieren.

*Reviews in GitLab (E14), ebenfalls in 0.42.0:*
- **«Review starten»** (▶) an jedem MR unter «Andere warten auf dich» und im Detail-Panel. Ein Klick:
  1. wählt den Agenten mit der Rolle `/reviewer` (bei `restricted` nur lokale Agenten),
  2. legt einen Worktree auf dem Head-Commit des MR an,
  3. startet den Review-Lauf mit dem MR-Diff, der Beschreibung, dem Ticket und den offenen Threads.
- Der Agent schreibt seine Punkte in eine Datei: Datei, Zeile, Art (Fehler, Frage, Vorschlag, Kleinigkeit), Text. Er bekommt kein GitLab-Token.
- tinyops prüft jeden Punkt (liegt die Zeile im Diff, gibt es den Punkt schon als Thread?) und legt ihn als **Entwurf** an der richtigen Zeile in GitLab an. Allgemeine Punkte werden ein Entwurf ohne Zeile.
- In tinyops steht dann «7 Entwürfe in GitLab» mit «In GitLab öffnen». Dort siehst du sie als ausstehendes Review, änderst oder löschst, was nicht passt, und schickst das Review selbst ab (mit Freigabe oder Änderungswunsch).
- Ein zweiter Lauf ersetzt nur die Entwürfe, die tinyops angelegt hat. Deine eigenen Entwürfe bleiben unberührt.
- Hat der MR seit dem Review neue Commits, sagt tinyops das und bietet ein neues Review an.
- Ohne `gitlab_review_token` bleibt es wie bisher: Punkte zum Kopieren.
- Ersetzt den geplanten «KI-Vorfilter für fremde Reviews» aus 0.40.
- **«Was tinyops nach aussen tut»** (Wunsch vom 20.11.) in den Einstellungen, je Anbindung (GitLab, Jira, Helpdesk, GitHub, Sonar, BCS, M365, KI-Kontingent, lokales Modell, Agenten über SSH):
  - jeder Aufruf mit Methode und Pfad, lesend oder schreibend, wann er passiert (Abgleich, Knopf, Wächter) und welches Token er braucht,
  - wie oft er heute lief und wann zuletzt, mit dem Ergebnis.
  - Die Liste kommt aus einer Tabelle im Code, durch die jeder Aufruf gehen muss. Ein Test lässt ein Release scheitern, wenn ein Aufruf daran vorbeigeht. So kann die Liste nicht veralten.
- **Fertig, wenn:** Ein MR eines Kollegen bekommt mit einem Klick ein Review als Entwurf in GitLab, du schickst es dort ab, ein Test zeigt, dass tinyops ausser den Entwurfs-Pfaden nichts in GitLab schreibt, und die Einstellungen listen jeden Aufruf nach aussen.

**0.43.0 – Voice Prompting** ✓ (Wunsch vom 25.11.)
- **Diktieren:** In den Prompt-Feldern erscheint oben rechts ein Mikrofon (auch <kbd>Alt</kbd>+<kbd>M</kbd>). Der Text kommt an die Cursorstelle.
- **Sprachbefehle** (Taste <kbd>v</kbd>): «DLP-123 an Qwen zum Entwickeln», «… planen, nur zuweisen», «DLP-123 Review mit Qwen», «Review für MR 47 mit Claude». Feste Regeln verstehen den Satz, das lokale Sprachmodell nur als Rückfall. tinyops zeigt den Vorschlag (Agent, Rolle, starten änderbar, nicht Erlaubtes mit Grund) und führt erst auf «Starten» aus. Was du gesagt hast, geht wörtlich an den Agenten.
- **Lokal:** whisper.cpp-Server oder OpenAI-kompatibel (vLLM mit Voxtral Mini, speaches). Nur Adressen im eigenen Netz, die Aufnahme wird nirgends gespeichert.
- **Fertig, wenn:** Ein Satz ins Mikrofon startet den richtigen Agenten am richtigen Ticket, und kein Ton verlässt das Netz.

**0.44.0 – Eingebautes Whisper** ✓ (Wunsch vom 25.11.: «einfach reinziehen», Intel-Prozessor ohne Grafikkarte)
- «Eingebaut» als Standard: whisper.cpp v1.9.5 holen und mit cmake bauen, Modell laden (SHA1 aus der Modellkarte), Server auf 127.0.0.1 beim ersten Diktieren, Ende nach 20 Minuten ohne Nutzung.
- Voxtral bleibt über den OpenAI-kompatiblen Weg möglich, braucht aber eine Grafikkarte.
- 0.44.1: Ein anderer Agent lieferte das Review nur als Text. tinyops liest Befunde jetzt auch aus Bericht und letzter Antwort (Block, JSON, Tabelle, Aufzählung), und du bearbeitest die Liste vor dem Anlegen in GitLab.

**0.45.0 – Einstellungen und Datenbank** ✓ (Refactoring, auf deinen Vorschlag vom 25.11. vor den neuen Wünschen. Geliefert wie unten, mit einer Abweichung: Die Oberfläche liest aus dem Schema nur Grenzen, Standard und Hilfe der Zahlenfelder und baut die Felder nicht selbst; eine neue Zahl sind drei Zeilen statt einer. Das Upgrade ist ab 0.25 getestet)
- `settings.py` (1'630 Zeilen) teilen: Verbindungstests in ein eigenes Modul, Speichern und Anzeigen nach Schema.
- Ein Schema je Feld (Typ, Grenzen, Hilfe) statt handgeschriebener Prüfungen. Die Oberfläche liest die Hilfe aus derselben Quelle.
- Datenbank mit `schema_version` und nummerierten Migrationen statt tolerantem `alter table`. Die neuen Tabellen für 0.46 bis 0.48 (Commits, Zugang) kommen dann als Migration dazu.
- Veraltete Einstellungen werden beim Laden migriert und entfernt.
- **Fertig, wenn:** Eine neue Einstellung ist eine Zeile im Schema, und ein Upgrade von 0.25 auf 0.45 ist getestet.

**0.46.0 – Aufräumen und Zugang** (Wünsche vom 25.11.)
- **Worktrees aufräumen, lokal und auf den Agenten** («cleanup von work trees muss funktionieren»): Eine Liste aller Worktrees von tinyops, je Ort (dieser Rechner, jeder Agenten-Rechner über SSH), mit Lauf, Alter, Branch und ob er sauber ist. «Aufräumen» entfernt alle sauberen, deren Commits auf einem Branch liegen; geänderte bleiben mit Grund. Auch `git worktree prune` für verwaiste Einträge.
- **Zugriff von aussen** («alles, was nicht 127.0.0.1 ist, vorerst nur mit Accesskey»): Einstellungen → App und Handy: Adresse wählen (Netzwerk-Schnittstelle oder alle), Zugangsschlüssel erzeugen und anzeigen, erlaubte Hostnamen. Ohne Schlüssel lässt sich nichts ausser 127.0.0.1 einschalten. Bisher ging das nur über `config.json` und `--set-secret access_token`. Gekoppelte Geräte (0.36) bleiben wie sie sind.
- **Korrekturen aus dem Bericht:** «Review mit Agent» scheiterte 8× an «Arbeitsverzeichnis gibt es nicht»; der Start bietet dann «Jetzt klonen» an (wie beim Zuweisen seit 0.27). `systemctl --user daemon-reload` schlug einmal fehl; die Meldung sagt, was zu tun ist. Der Rückfall der Sprachbefehle aufs lokale Modell dauerte 75 s; nach 15 s bricht tinyops ab und zeigt die Beispiele.
- **Fertig, wenn:** Nach einem Tag mit Agenten bleibt nach «Aufräumen» kein sauberer Worktree liegen, und das Handy erreicht tinyops nur mit Schlüssel.

**0.47.0 – Agentenpanel neu** (Wünsche vom 25.11.; erster Teil des Redesigns)
- **Klare Trennung** («sehr kompliziert und unübersichtlich»): oben Rolle, Stand und nächster Schritt; darunter Reiter **Gespräch** (Auftrag, deine Nachrichten, Antworten), **Kriterien** (je AK Stand und Beleg), **Review-Punkte** (Befunde mit Datei:Zeile, offen oder erledigt), **Änderungen** (Commits, Dateien) und **Log**.
- **Log lesbar:** Werkzeugaufrufe, Befehle und Fehler als Zeilen mit Symbol, lange Ausgaben zugeklappt, Suche.
- **Vorlagen direkt** («klarer Zugriff auf alle 4 default prompts»): Planen, Entwickeln, Review und Test als Reiter im Auftrag, je mit «Ansehen», «Bearbeiten», «Zurücksetzen». Die Vorlage gilt für alle Tickets, deine Änderung für dieses eine.
- **Auswahl, was jetzt drankommt** («genau auswählen, welche Review-Punkte oder AK jetzt umgesetzt werden»): Beim Planen, Entwickeln und Nachbessern stehen alle Kriterien und offenen Review-Punkte als Haken; nur die angehakten gehen in den Auftrag, die anderen als «nicht in dieser Runde».
- Aus dem Bericht: 10 Wutklicks und 2.8 s Zögern im Agentenfenster; 35 tote Klicks auf den Hintergrund im Fokus.
- **Fertig, wenn:** Du findest in einem fertigen Lauf ohne Suchen, was der Agent gesagt hat, welche Kriterien offen sind und welche Review-Punkte noch fehlen.

**0.48.0 – Commits einzeln** (Wunsch vom 25.11.: «der ganze Workflow muss dynamischer, aber auch durchlässiger werden»)
- **Liste je Commit** im Detail-Panel und im Lauf: Nachricht, Autor (Agent oder Mensch), Dateien mit +/−, und was der Bericht des Agenten dazu sagt.
- **Review je Commit:** «Review mit Agent» für einen oder mehrere Commits statt für den ganzen MR; die Befunde hängen am Commit.
- **Zeilen-Review auf eigene Tickets:** dasselbe Review wie bei Kollegen-MRs (0.42/0.44.1) auch für deine eigenen Branches und die deiner Agenten, mit Befunden zum Zurückschicken ans Entwickeln statt als Entwurf in GitLab.
- **Fertig, wenn:** Ein Commit eines Agenten lässt sich einzeln ansehen, reviewen und mit den Befunden zurückschicken.

**0.49.0 – Tests und Doku**
- 13 Testdateien `test_vNN.py` gehen in Testdateien je Modul auf.
- Das README wird ein Handbuch nach Themen statt der Abschnitte «neu in 0.x».
- Die Hilfe in der Oberfläche verweist auf dieselben Kapitel.
- **Fertig, wenn:** Zu jedem Modul gibt es eine Testdatei, und das README hat höchstens 15 Kapitel.

**0.50.0 – Echte Anbindungen härten**
- Mit dir gemeinsam:
  - BCS gegen die echte Middleware
  - M365 nur, wenn du es dann brauchst (20.11.: kein Schwerpunkt)
  - Helpdesk
  - Agent-Zyklus und Auschecken per SSH auf der devops-Maschine
  - Gruppierung mit euren Link-Typen
- Fehlerbilder, die dabei auftauchen, werden zu Tests mit Fault-Injection.
- **Fertig, wenn:** Jede Anbindung ist einmal echt gelaufen oder hat einen klaren Blocker, den die IT lösen muss.

**0.51.0 – Weitere Projekte tracken**
- Ein «Vorhaben» ohne Jira und GitLab: Name, Ziel, nächster Schritt, Status, Links. Optional mit einem Ordner aus Workspaces oder einem GitHub-Repo.
- Erscheint im Fokus und in den Listen wie ein Ticket.
- **Ohne Code-Plattform nutzbar** (19.11.): tinyops läuft auch nur mit Workspaces, Ideen und Vorhaben, etwa zu Hause ohne GitLab. Die Meldung «GitLab-Adresse fehlt» erscheint nicht mehr, wenn GitHub oder gar keine Plattform eingerichtet ist.
- **Forgejo** als dritte Quelle neben GitLab und GitHub, sobald du eines hast. Gehört nach E7a vielleicht eher in die Privat-App.
- **Fertig, wenn:** Ein privates GitHub-Projekt und ein Projekt ohne Repo stehen mit nächstem Schritt in den Listen.

**0.52.0 – KI-Projekte aus Claude, ChatGPT, Mistral**
- Lesezeichen «In tinyops merken»: Es übernimmt Titel und Link des offenen Chats oder Projekts als Vorhaben aus 0.51, mit Anbieter-Piktogramm.
- Import der offiziellen Daten-Exporte, lokal ausgewertet: Projekt- und Chatnamen und Datum, ohne Inhalte, falls du das willst.
- Ehrlich: Die drei Anbieter haben keine offizielle Schnittstelle, die deine Chatliste herausgibt. Mehr als Lesezeichen und Export geht nicht, ohne Regeln zu umgehen.
- **Fertig, wenn:** Ein Claude-Projekt, ein ChatGPT-Chat und ein Mistral-Chat stehen als Vorhaben mit nächstem Schritt in tinyops.

**0.53.0 – Zweiter Bereich** (nach E7, E7a, E9–E11)
- E7: Privat und Geschäft als zwei Instanzen mit eigenem Datenordner, eigenen Secrets und eigenem Audit. Jede hat eigene Agenten, also einen eigenen Worker.
- Ein Umschalter oben wechselt zwischen den beiden. Der Launcher startet beide.
- **App:** seit 0.36 da (PWA, Handy über Kopplung). Hier kommt nur der Umschalter dazu: Jede Instanz koppelt ihre Geräte selbst.
- **Fertig, wenn:** Ein privates Vorhaben ist in der Geschäfts-Instanz nicht sichtbar, und das Handy kann zwischen beiden wechseln.

### Auswertung 25.11.: Prüf- und Nutzungsbericht 0.44.1

**Was die Berichte zeigen**
- **Prüfliste:** 22 geprüft, 0 Fehler, 47 offen. Offen sind vor allem echte Systeme (BCS, M365, SSH-Agenten), die Sprache (`r43-01` bis `r43-03`) und die neuen Abläufe 0.40 bis 0.42.
- **Ansichten:** Fokus 72 %, Einstellungen 15 %, Prüfen 12 %. Fokus ↔ Einstellungen wieder 15× und 13× hin und her. Die Hilfe zu M365, KI-Entwurf und App ging je 22× auf.
- **Agentenfenster:** 74 Klicks, 2.8 s Zögern, 10 Wutklicks, 6 von 24 Mal ohne Aktion geschlossen. Das deckt sich mit deinem Wunsch, das Panel zu überarbeiten (0.47).
- **Tote Klicks:** 35× auf den leeren Hintergrund im Fokus, 12× auf Text in Prüfen, 9× auf das Banner im Fokus.
- **Fehler:** «Review mit Agent» 8× ohne Arbeitsverzeichnis beim Agenten (0.46); einmal `systemctl --user daemon-reload`; ein Sprachbefehl ohne erkanntes Ticket.
- **Langsam:** Sprachbefehl mit Rückfall aufs lokale Modell 75 s; GitLab-Verbindungstest 5.9 s; Workspaces 11.7 s.
- **Wünsche** (fünf, wörtlich im Bericht): Worktrees aufräumen (0.46), Zugriff von aussen mit Schlüssel (0.46), Commits einzeln reviewen (0.48), Agentenpanel und Log (0.47), Vorlagen und Auswahl der Kriterien (0.47).

**Empfehlungen**

| Wann | Empfehlung | Warum |
|---|---|---|
| 0.45 | Beim Teilen der Einstellungen die Abschnitte M365, KI-Entwurf und App mit kürzerer Hilfe und einem «Was fehlt noch?» oben. | Hilfe je 22× aufgeklappt, 28 Wechsel Fokus ↔ Einstellungen. |
| 0.46 | Klick auf den leeren Fokus-Hintergrund schliesst Detail- und Agentenpanel (wie seit 0.42 neben dem Agentenpanel). | 35 tote Klicks. |
| 0.47 | Das Agentenpanel mit Playwright-Test für «findet in 3 Klicks: Antwort, offene AK, offene Review-Punkte». | 10 Wutklicks, 2.8 s Zögern. |

### Auswertung 16.11.: Prüf- und Nutzungsbericht 0.33, Verlauf

**Was die Berichte zeigen**
- **Prüfliste:** 16 von 67 geprüft, ein Fehler (r23-04, in 0.34 behoben). Offen sind vor allem Punkte mit echten Systemen: BCS (r29), Microsoft 365 (r28), Agenten über SSH (r27). Diese Punkte kann kein automatischer Test ersetzen.
- **Ansichten:**
  - Fokus 55 %, Einstellungen 23 %, Prüfen 9 %. Workspaces, Board, Listen und Zeit liegen je unter 5 %.
  - Einstellungen kosten zu viel Zeit: «Verbindung testen» beim Helpdesk 14×, Agent «Testen» 13×, 3 s Zögern im JQL-Feld, die Hilfe zu Microsoft 365 18× aufgeklappt.
- **Detail-Panel:** Es ist das Arbeitspferd: 68 Klicks auf Einträge, 31× «Schliessen». Dazu kommen 27 tote Klicks auf den leeren Hintergrund im Fokus. Vermutung: Du willst das Panel mit einem Klick daneben schliessen.
- **Bildschirm:** Fast immer 2844 px breit, bei Pixeldichte 0.9. Auf dieser Breite bleibt viel Platz leer.
- **Verlauf:**
  - Ein echter Vibe-Lauf auf der devops-Maschine lief durch.
  - Fehler, die in 0.35 behoben sind: Kategorie lösen und roher Fetch-Fehler.
  - Fehler, die nicht mehr auftreten können: der Test der alten MCP-Verbindung (8 s) und «kube_context fehlt». Beide Funktionen sind seit 0.34 entfernt.
- **Wünsche:**
  - Erledigt in 0.34: Checkout aus Workspaces, vorbefüllte Review-Befehle, Compose-Datei und Umsysteme zum Zusammenklicken.
  - Erledigt in 0.35: Worktrees in Workspaces.
  - Offen: mehrere Repos als **ein** Projekt. Beispiel: Mailhandler mit Frontend, Redis, ActiveMQ und PostgreSQL in IntelliJ und in der Review-Umgebung zusammen.

**Empfehlungen für die nächsten Releases**

| Wann | Empfehlung | Warum |
|---|---|---|
| ~~vor 0.36~~ | Nicht eingehalten: 0.36 kam auf deinen Wunsch direkt danach. Gilt jetzt vor 0.37: Pause bis zum 20.11. oder bis die Prüfabschnitte durch sind. Ursprünglich: Pause bis zum 19.11. oder bis die Prüfabschnitte 0.34 und 0.35 durch sind. Dabei BCS (r29) und Review-Umgebung (r34-04) mit echten Systemen prüfen. | 0.33 bis 0.35 kamen in zwei Tagen, die Regel erlaubt höchstens zwei Releases pro Woche. |
| Korrektur-Platz 0.36 (teils erledigt) | Dialoge schliessen jetzt mit Klick daneben und ×; das Detail-Panel tat das schon seit 0.30. Offen: Klick auf den Titel einer Zeile (`span.tt`) öffnet sie; die toten Klicks auf den leeren Hintergrund bleiben ungeklärt. | 27 + 16 tote Klicks. Das ist klein und gehört vor das Zerlegen, weil Refactoring kein Verhalten ändern darf. |
| 0.37/0.38 | Beim Zerlegen das Testen der Verbindungen in Schritten zeigen (GitLab 5.8 s, GitHub 2.2 s). Das KI-Kontingent zwischenspeichern (`/api/usage` bis 2.3 s). | Langsame Antworten im Bericht. |
| 0.39 | Breites Layout ab 2000 px: Das Detail-Panel steht neben der Liste statt darüber. | 2844 px, 31× Schliessen. |
| 0.41 | Einstellungen nach Schema mit geführter Ersteinrichtung je Anbindung: erst Adresse, dann Test, dann Feinheiten. Für Helpdesk-JQL nur Vorschläge zum Anklicken. | 23 % der Zeit in Einstellungen. |
| 0.42 | Ungenutzte Ansichten mit 30 Tagen Daten neu bewerten. Kandidat: «Listen» in Board und Workspaces aufgehen lassen. «Zeit» bleibt, weil dort gebucht wird. | Sieben Tage reichen nicht. |
| 0.43 | Microsoft 365 Schritt für Schritt einrichten, mit einem fertigen Text für die IT (App-Registrierung, delegierte Rechte, kein Secret). Vorher mit der IT klären, ob es eine App-Registrierung gibt. | Hilfe 18× aufgeklappt, r28 noch ungeprüft. |
| 0.44 | «Weitere Projekte» als **Projektgruppe**: mehrere Repos und Umsysteme unter einem Namen. Die Gruppe öffnet zusammen in IntelliJ und startet zusammen als Review-Umgebung. | Offener Wunsch vom 16.11. |
| 0.46 | Getrennte Instanzen für Privat und Geschäft wie geplant (E7). | Im Bericht tauchte ein privates Projekt neben der Arbeit auf. |

### Auswertung 17.11.: Prüf- und Nutzungsbericht 0.35.1

**Was die Berichte zeigen**
- **Prüfliste:** 17 von 68 geprüft, kein Fehler. Offen bleiben die Punkte mit echten Systemen (BCS, M365, SSH-Agenten).
- **Ansichten:** Fokus 69 %, Einstellungen 15 %. Fokus und Einstellungen wechseln je 14× hin und her, meist wegen Agenten- und KI-Einstellungen. Die Hilfe zu M365 ging 30× auf, die zum KI-Entwurf 28×.
- **Agentenfenster:** 151 Klicks, Median 3.1 s Zögern, 20 Wutklicks. Ursache: Bei laufenden Agenten baute es sich alle 4 s neu auf, und Klicks gingen verloren. In 0.36 behoben.
- **BCS:** 35× «nicht erreichbar», Median 73 s Wartezeit. In 0.36 auf 8 s begrenzt, danach eine Minute Pause mit klarer Meldung.
- **Lokales Modell:** Test 27 s, Bewertung einer Idee 50 bis 87 s. Das Modell ist für diese Aufgaben zu langsam oder zu gross.
- **Wünsche:** alle sechs vom 17.11. in 0.36 umgesetzt (siehe Changelog).

**Empfehlungen für die nächsten Releases**

| Wann | Empfehlung | Warum |
|---|---|---|
| **vor 0.37** | Die Abschnitte 0.36 und 0.35 prüfen, vor allem `r36-01` (Weiterführen mit Entscheidung), `r36-02` (Push und Rollen auf devops) und `r36-05` (Handy über Tailscale). | Viel Neues an einem Tag. Das Zerlegen soll auf geprüftem Verhalten aufsetzen. |
| 0.37/0.38 | Die neuen Teile beim Zerlegen gleich als eigene Module anlegen: `devices.py` ist es schon. Agenten-Fortsetzung und Entscheidungen gehören zu `agents`, der Hero zu einem Fokus-Modul. | Sonst wächst `server.py` wieder. |
| 0.39 | Breites Layout: Arbeitsfläche und Detail nebeneinander. Das Agentenfenster wird ein Seitenpanel statt eines Dialogs. | 2844 px, 151 Klicks im Dialog. |
| 0.40 | Agenten aufräumen: Rollen ersetzen die Auswahl je Phase; «Mit Vorschau» und «Weiterführen» zu einem Weg zusammenlegen, wenn sich «Weiterführen» bewährt. | Zwei Wege für dasselbe. |
| 0.41 | Einstellungen: Agenten und KI-Entwurf als geführte Einrichtung mit Test. Hinweis, wenn das lokale Modell länger als 20 s braucht (kleineres Modell vorschlagen). | 14× Fokus ↔ Einstellungen, Hilfe 28×, Bewertung bis 87 s. |
| 0.43 | M365 Schritt für Schritt mit Text für die IT (wie geplant). | Hilfe jetzt 30× aufgeklappt. |

### Auswertung 20.11.: Prüf- und Nutzungsbericht 0.37

**Was die Berichte zeigen**
- **Prüfliste:** 24 geprüft, 2 Fehler.
  - `r36-01` (Weiterführen) ohne Notiz. Dein Wunsch vom 18.11. «in der gleichen Session weitergehen» lässt vermuten, dass du die bestehende Agenten-Sitzung erwartet hast, nicht einen neuen Lauf. Kommt in 0.40.
  - `r36-05`: Es fehlte der QR-Code. Kommt in 0.39.
- **Ansichten:** Fokus 73 %, Einstellungen 12 %, Prüfen 6 %.
- **Agentenfenster:** weiter das meistgeklickte Ziel (182 Klicks, 24 Wutklicks). Das × wurde 21× benutzt. Als Seitenpanel in 0.39.
- **BCS:** 69 Meldungen «nicht erreichbar». 23 davon schon mit der Pause aus 0.36 («nächster Versuch in …»), die übrigen und der Median von 40 s stammen aus älteren Versionen (zweimal 20 s).
- **Wünsche:** vier neue (Review-Vorfilter, Sitzung fortsetzen, Git-User je Agent, Prüfliste je Ticket). Nachtrag 20.11.: Weiterführen heisst «in derselben Sitzung» (0.40). Der Review-Vorfilter wird ein Review als Entwurf in GitLab mit «Review starten» (0.43, E14). Die Prüfliste je Ticket kommt mit «Jetzt testen» in 0.42.
- Die Versionsnummern in den Auswertungen 16.11. und 17.11. gelten vor den Verschiebungen vom 20. und 23.11. (ab 0.41 drei Versionen später).

### Bewusst nicht im Plan bis 0.53
- Native App (iOS/Android; die Web-App seit 0.36 reicht), zentrale Datenbank, Agenten-Cluster über mehrere Rechner
- Schreiben in GitLab ausser Review-Entwürfen (E14): kein Approve, Merge oder Abschicken eines Reviews. Confluence
- Neue Anbindungen ausser denen in 0.51 bis 0.53

---

## Früherer Plan 0.15 – 0.20 und Releases bis 0.32

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
| **0.30.0** ✓ | Tickets zu Tasks gruppieren (Bug + Begleitticket, Story + Unteraufgaben, von Hand), Bugs bleiben sichtbar; Wunsch an tinyops im Nutzungsbericht; Bericht mit Version, Fehlermeldungen, langsamen Antworten, Hilfe und ungenutzten Ansichten (geliefert 2026-11-13) | – | M |
| **0.31.0** ✓ | Agenten-Zyklus Planen → Umsetzen → Review → Test mit Freigabe und Prüfpunkten von Hand (`tinyops-manual`), Leitplanken in jedem Prompt, Prompts als Markdown (ansehen, bearbeiten, kopieren), Testsitzung in Prüfen (geliefert 2026-11-14) | – | M |
| **0.32.0/0.32.1** ✓ | Einfach reviewen: Begründung im Bericht statt im Code (mit Hinweis bei Kommentar-Rauschen), «Kurz vorab» je Lauf, MR-Beschreibung zum Kopieren, Auschecken in eigenen Worktree und IntelliJ, Review-Umgebung (Docker Compose, Kubernetes, eigene Befehle), Piktogramme für Repo und Branch, Fokus klarer (geliefert 2026-11-15) | – | M |

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
