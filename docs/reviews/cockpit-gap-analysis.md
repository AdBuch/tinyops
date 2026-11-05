# Engineering Cockpit: Implementation Gap Review

**Geprüft:** tinyops 0.14.0 (Tag `v0.14.0`, Commit `eabbefa`), 232 automatisierte Tests grün
**Gegen:** (A) `AI_Engineering_Cockpit_Focus_Board_Reference_and_Gap_Analysis.md` v1.0 (F-01…F-26, Invarianten, AC-01…AC-18) und
(B) «Gap-Analyse: Work Cockpit — vom Prototyp zum produktiven Tool» (G1…G20)
**Stand:** 2026-11-05 · **Methode:** read-only Durchsicht von Code und Tests; Belege als `Datei:Zeile` und Testname (Zeilen beziehen sich auf `v0.14.0`).
Statusbegriffe wie in (A) 16.1. **DONE nur mit Test.** Nicht gegen echtes Jira 9.4, GitLab 19.2, GitHub oder einen Cluster geprüft: alle Integrationsaussagen beziehen sich auf Mock-Server.

> Hinweis zu (B): Die Ist-Spalte dort beschreibt einen React-Prototyp mit Mock-Daten. tinyops ist ein anderes, bereits angebundenes Produkt;
> viele G-Punkte sind hier geschlossen oder bewusst anders gelöst (Abschnitt 4).

---

## 1. Executive Summary

**Reifegrad (evidenzbasiert):** Die **Sicht-Schicht** ist produktiv nutzbar: Jira-, GitLab- und GitHub-Lesezugriff, ein abgeleiteter Ablauf mit genau einem nächsten Schritt je Vorhaben, Fokus-Ansicht, Review-Queue, Sonar-Gates, Ideen-Inbox, Agentenstatus.
Die **Ausführungs-Schicht** (Agenten) funktioniert, ist aber nicht abgesichert genug für DLP-nahe Repos. Die **Nachweis-Schicht** (SHA-gebundene Evidenz, Audit) fehlt weitgehend.
Phase A der Referenz ist im Kern erreicht, Phase B teilweise, Phase C funktional, aber nicht gehärtet, Phase D teilweise. E und F sind kaum begonnen.

**Top-5-Gaps**
1. **Manuelle Abnahme ist nicht an den Commit gebunden** (F-18, AC-11, NFR-06). «Getestet» bleibt stehen, auch wenn danach neue Commits kommen. Dann ist «Mergen» mit veralteter Abnahme möglich.
2. **Agenten arbeiten ungeschützt** (F-10, F-24, NFR-05, AC-18).
   - Sie laufen im gemeinsamen Checkout mit allen Rechten des Benutzers.
   - Es gibt keinen Worktree je Lauf, kein Zeit- oder Kostenlimit und keine technische Befehlssperre.
   - Die Regeln stehen nur im Prompt.
3. **Kein Audit-Trail** (F-15, NFR-09). Externe Writes, Übersteuerungen, Agentenstarts und Prompts stehen nur im rotierenden Log.
4. **«Unbekannt» wird als «in Ordnung» behandelt** (Ergonomieregel «keine falsche Vollständigkeit», NFR-10). Sind Freigaben nicht lesbar, entfällt die Review-Prüfung stillschweigend. Veraltete Daten sind je Eintrag nicht markiert.
5. **Kein Rückkanal für Agenten-Fragen** (F-09, AC-06). Ein Agent kann nicht «wartet auf Antwort» melden, und Needs Me kennt keine Klärungsfragen.

**Sicherheitsblocker** (nur, wenn Agenten auf Restricted-Repos laufen sollen): SEC-1 und SEC-2 aus Abschnitt 5. Ohne Agenten bleibt kein Blocker: Das Panel liest sonst nur; geschrieben wird einzig in Jira, mit Opt-in und Bestätigung.

**Quick Wins (je Stunden):**
- Laufzeitlimit je Agent mit Kill
- Chip «Freigabe nicht lesbar» statt stillem Durchwinken
- Fokus von Hand anheften (F-01)
- Link auf die GitLab-Review-App-URL (G9)
- Datum «Stand vor X min» je Integration im Fokus-Kopf

---

## 2. Feature Coverage (Referenz A)

| ID | Status | Evidenz | Gap | Severity | Ticket |
|---|---|---|---|---|---|
| F-01 Ein Fokus-Task | PARTIAL | `flow.py:206` `priority`, `static/index.html:2403` `focusGroups`/`heroHtml`; Test `test_flow.Derive.test_priority` | «Jetzt dran» wird berechnet, nicht gewählt. Kein «max. 1 aktiver Fokus»; «Nicht jetzt» gilt nur pro Tab | P1 | T-6 |
| F-02 Today-Übersicht | PARTIAL | Fokus-Gruppen Du bist dran / Andere warten / Läuft gerade, Agenten-Leiste; `test_flow.AppFlow.test_overview_has_flow_for_every_card` | keine eigene «Heute»-Liste (Tagesplan); fehlgeschlagene Agenten nur als Blocker in der Zeile | P1 | – |
| F-03 Attention | PARTIAL | Blocker zuerst, Warten getrennt (`flow.py:206`) | keine Bündelung, keine Unterbrechungsregel, kein Fokusmodus, keine Benachrichtigungen | P2 | – |
| F-04 WorkItem-Detail | PARTIAL | Detail-Panel `static/index.html:2516` `renderFx`: Station, Next Step, MRs/PRs, Pipeline, Sonar, Mergestatus, Reviewer, Agenten, Teilschritte | kein Plan, keine Testevidenz, keine Historie | P1 | T-1, T-3 |
| F-05 Idea Inbox | DONE | `server.py:436` `Ideas` (Limit, Verfall), Taste «i», erzeugt keinen Branch; `test_board…test_orphans_ideas_and_validation`, `test_flow…test_orphan_flag_and_ideas` | – | – | – |
| F-06 AI-Ideenbewertung | PARTIAL | Triage-Prompt zum Kopieren (`prompts/idea-triage.md`, `server.py` `triage_prompt`) | Ergebnis wird nicht zurückgespeichert, keine Felder Impact/Effort an der Idee | P2 | – |
| F-07 Jira-Ticketvorschläge | PARTIAL | Entwurf aus MR/Branch per lokalem LLM oder Vorlage (`llm.py:206`, `llm.py:267`), Anlegen nur mit `allow_create` + Bestätigung (`server.py:170`, `server.py:2028`); `test_ticket.test_create_is_off_by_default`, `…test_create_validates_and_works` | nicht aus Ideen; Abschnitte Risiken, Abhängigkeiten, Tests fehlen | P1 | – |
| F-08 Workflow-Zustandsmaschine | PARTIAL (anders gelöst) | `flow.py:77` `derive`: 8 Stationen aus den Daten, Übersteuern, Blocker und Warten als eigene Art (entspricht der Empfehlung «orthogonale Flags»); 21 Tests in `test_flow` | kein gespeicherter Übergangsverlauf; TRIAGE und PLAN_APPROVAL fehlen. Ableiten statt Speichern hält Jira und GitLab als Quelle der Wahrheit, gute Alternative | P2 | T-3 |
| F-09 Agentenstatus/Fragen | PARTIAL | Status, Log, Stop, Mitlesen (`agents.py:514` `poll`, `:563` `stop`, `:613` `tail`); `test_agents.Remote.*` | keine Klärungsfragen, kein WAITING_FOR_INPUT | P1 | T-5 |
| F-10 Isolierter Worker | BROKEN (Risiko) | Arbeitsordner = gemeinsamer Checkout (`agents.py` `workdir`); einzige Sperre: ein Lauf je Ordner (`test_agents…test_stop_and_one_run_per_workdir`) | kein Worktree je Lauf, kein eigener Benutzer, keine Befehls- oder Netzsperre | **P0** | T-2 |
| F-11 CI-/Testevidenz | PARTIAL | Pipeline/Checks/Sonar bestimmen den Schritt (`flow.py:77`), GitHub-Checks `github.py` `pipeline`; `test_github.ClientTests.test_fetch_items` | nicht an SHA gebunden, keine Testberichte, kein Artefakt-Digest | P1 | T-1 |
| F-12 Review-Queue | PARTIAL | `flow.py:221` `review_view` (GitLab + GitHub), Prompt `prompts/review-brief.md` | Risikozusammenfassung nur als kopierbarer Prompt (und nur bei eingeschalteter Testumgebung) | P1 | – |
| F-13 Draft MR | PARTIAL (bewusst) | «MR erstellen» öffnet das GitLab-/GitHub-Formular (`create_mr_url`); Sync von MR und Pipeline: `test_sync` | kein API-Write (bewusst: GitLab nur lesend) | P2 | Entscheid 1 |
| F-14 Datenklassen/Policy | PARTIAL (stark) | Cloud-Agent nur mit Freigabe je Projekt/Repo (`agents.py:362`, `test_agents.Gate.test_cloud_agent_needs_project_opt_in`); LLM nur lokal (`test_ticket.test_remote_is_refused_unless_allowed`); an das LLM gehen nur Titel (`test_ticket.test_template_and_prompt_send_no_more_than_titles`) | Klasse je Projekt, nicht je Ticket; kein RESTRICTED/SECRET-Modell; Cloud-Flag bei «custom» selbst erklärt | P1 | – |
| F-15 Audit | MISSING | nur Log-Zeilen (`server.py:384` «SCHREIBEN POST», Agentenstart in `agents.py`), Log rotiert | keine unveränderliche Historie für Writes, Übersteuerungen, Prompts, Entscheidungen | **P0** | T-3 |
| F-16 K8s Review Env | PARTIAL | Testumgebung je MR mit Image-Tag aus dem SHA, Namespace-Präfix, Cluster-Sperre (`server.py:2230–2295`, `test_deploy`), standardmässig aus | kein TTL-Aufräumen, keine Quota/NetworkPolicy, keine Readiness-Prüfung | P2 | – |
| F-17 IntelliJ Companion | MISSING | `.run/` sind nur Startkonfigurationen für tinyops selbst | Worktree auf MR-Commit + `idea` öffnen fehlt | P2 | – |
| F-18 Manuelle Testevidenz | BROKEN | «Getestet» = Board-Stufe `tested` (`links.py:185` `stage_set`), Teilschritte | ohne SHA, Umgebung, Notiz; bleibt bei neuen Commits gültig (AC-11) | **P0** | T-1 |
| F-19 MR Ready/Approval | N/A (Entscheid) | GitLab ist absichtlich nur lesend; Review-Gate vor «Mergen» nur in der Anzeige (`flow.py:39` `_approval`, `test_flow…test_review_and_approval`) | widerspricht (A) F-19 und (B) G3/G4; siehe Abschnitt 7 | – | Entscheid 1 |
| F-20 Projectron | MISSING | – | API-Lage ungeklärt | P2 | Frage 2 |
| F-21 Confluence | MISSING | – | – | P2 | – |
| F-22 Sprintplanung | PARTIAL | Sprintname, Resttage, Story-Limit (Jira-Panel, WIP-Karte) | keine Vorschläge | P2 | – |
| F-23 Multi-Worker | PARTIAL | mehrere Agenten und Verbindungen, Auswahl von Hand, Cloud-Sperre | kein Routing nach Fähigkeit oder Datenklasse | P2 | – |
| F-24 Recovery/Leases | PARTIAL | tmux überlebt Neustart, Exit-Datei, «verloren» (`agents.py:215`, `test_agents…test_lost_session`, `…test_status_unreachable_keeps_running_with_note`), lokaler Heartbeat (`agentwrap.py`) | **kein Timeout**, kein Retry-Budget, kein Lease | **P0** (Timeout) | T-2 |
| F-25 Analytics | PARTIAL | Spielstand (Schritte je Tag, Serie: `test_flow.Score.*`), Alter von Branches/MRs | Durchlaufzeit, Review-Latenz, Fehlerrate | P3 | – |
| F-26 Team | N/A | Ein-Personen-Werkzeug | – | – | – |

### Invarianten (A, Kapitel 5)

| Invariante | Stand |
|---|---|
| max. ein aktiver Fokus | nein: berechnet, nicht erzwungen (WIP-Limit nur für Jira-Stories) |
| Ideen erzeugen keine Tickets/Branches | **ja** |
| Ein Branch braucht ein Ticket | **ja**, strenger als die Referenz (`flow.py:149`, `test_flow…test_branch_needs_ticket`) |
| Evidenz an Commit-SHA gebunden / neuer SHA macht stale | **nein** (Gap 1) |
| Agent kann nicht selbst approven | ja, mittelbar: tinyops approvt nie. Agenten-Tokens auf dem Zielhost sind ausserhalb von tinyops |
| Writes idempotent und auditiert | teilweise: Jira-Anlegen mit Bestätigung und gesperrtem Knopf, aber ohne Idempotency-Key und ohne Audit |
| Cloud nur mit Freigabe | **ja** (`test_agents.Gate.*`) |

---

## 3. Architecture Findings

- **Stack weicht bewusst ab.** Die Referenz empfiehlt Spring Boot, Angular, PostgreSQL, SSE und OIDC. tinyops nutzt Python-Standardbibliothek, SQLite und eine einzige HTML-Datei, dazu Polling statt SSE.
  - Für ein Ein-Personen-Cockpit auf dem eigenen Rechner ist das gleichwertig: keine Abhängigkeiten, Start in einer Sekunde, kaum Ops-Last. Das ist auch das Ziel von (B).
  - **Empfehlung: nicht umschreiben.** Ein Umbau kostet Wochen und bringt für einen Nutzer nichts. Erst bei Team-Betrieb (F-26) neu bewerten.
- **Domäne.** Es gibt kein eigenes WorkItem. Vorhaben entstehen bei jedem Abgleich aus Jira, GitLab, GitHub und lokalen Aufgaben, zusammengeführt über den Key (`server.py` `_board`).
  - Gespeichert wird nur, was keiner Quelle gehört: Stufen-Übersteuerung, Kategorien, tiny-Tickets, Teilschritte, Fortschritt, Agentenläufe (`links.py`).
  - Das erfüllt «Source of Truth bleibt extern» besser als ein WorkItem-Modell mit Sync.
  - Preis: Ohne gespeicherte Übergänge gibt es keine Historie. Das löst T-3 ohne Modellwechsel.
- **APIs** sind intern, ohne Versionierung und OpenAPI. Für ein Panel mit genau einem Client ist das akzeptabel; Contract-Tests ersetzt die Testsuite gegen die App.
- **Worker** sind kein Pull-Modell mit Leases. tinyops startet per SSH eine tmux-Sitzung und liest Exit- und Log-Dateien.
  - Das ist einfacher und übersteht Neustarts, hat aber kein Timeout und keine Isolation.
  - (B) empfiehlt GitLab-CI-Jobs mit Runner-Tag als Agenten-Gateway. Das brächte Audit, Rechte und Laufzeitlimit gratis vom CI. Es ist die stärkste Alternative zu T-2, siehe Entscheid 2.
- **Integrationen:** Abgleich per Polling (5 min, `cache_seconds`), keine Webhooks. Das trifft auch AC-15 (doppelte Webhooks): Ohne Webhooks kann es keine doppelte Ausführung geben. Fehler je Quelle erscheinen als Banner und in der Sync-Leiste.
- **Review Envs:** Die Testumgebung (Helm je MR) existiert, ist standardmässig aus und nie gegen einen echten Cluster gelaufen.

## 4. Abgleich mit (B) G1–G20

| G | Thema | Stand in tinyops | Bemerkung |
|---|---|---|---|
| G1 | Jira lesen | DONE (Mock) | `test_ticket`, `test_sync` |
| G2 | GitLab lesen | DONE (Mock) | ohne Diff-Summary (bewusst: kein Code ins LLM) |
| G3 | Approve ausführen | N/A (Entscheid) | GitLab bleibt lesend |
| G4 | Gating serverseitig | PARTIAL | Gates werden serverseitig abgeleitet (`flow.py`), schützen aber nur die Anzeige, weil es keinen Write gibt |
| G5 | Agenten | PARTIAL | SSH/tmux und lokal, statt CI-Jobs; ohne Limits |
| G6 | AuthN/AuthZ | PARTIAL | Loopback als Standard, Zugriffstoken Pflicht ausserhalb von Loopback, Host-Allowlist, CSRF-Header (`server.py:2381–2410`); kein SSO |
| G7 | KI-Klärungs-Inbox | MISSING | T-5 |
| G8 | Open in IntelliJ | MISSING | |
| G9 | Review-Umgebungs-Link | PARTIAL | eigene Testumgebung, aber kein Link auf die GitLab-Environment-URL (Quick Win) |
| G10 | Projectron | MISSING | API-Frage zuerst |
| G11 | Ideen-Persistenz | DONE (anders) | lokal in SQLite statt Jira-Label; Triage als Prompt |
| G12 | Sprint-Tickets erzeugen | PARTIAL | aus MR/Branch, nicht aus Notizen |
| G13 | Prompt Store | DONE | `prompts/*.md` versioniert im Repo |
| G14 | Confluence | MISSING | |
| G15 | Branch-/WIP-Statistik | PARTIAL | Alter, «liegt schon lange», WIP-Limit |
| G16 | Scheduled Report | MISSING | kann als geplanter Lauf ausserhalb des Panels entstehen |
| G17 | Security-Hardening | PARTIAL | siehe Abschnitt 5 |
| G18 | Ops-Deployment | PARTIAL | Dockerfile und `deploy/k8s.py` mit Manifesten ohne Ingress (Zugriff per Port-Forward; Prüfung des Build- und Deploy-Aufrufs in `test_k8s_cli`, kein eigener Ingress-Test); Image nie gebaut |
| G19 | Tests | PARTIAL | 232 Unit- und Integrationstests gegen Mock-Server, Policy-Tests (nur GET bei GitHub und Sonar, Jira-Write standardmässig aus, Deploy nur mit Secret); E2E nur per Headless-Screenshot, nicht automatisiert |
| G20 | Kostenkontrolle | PARTIAL | KI-Kontingent sichtbar (Claude, Codex, Mistral); kein Budget oder Zeitlimit je Lauf |

---

## 5. Security Findings

| ID | Finding | Ausnutzbarkeit | Impact | Evidenz | Mitigation |
|---|---|---|---|---|---|
| SEC-1 | Agenten laufen mit allen Rechten des Benutzers im gemeinsamen Checkout. Sperren stehen nur im Prompt | mittel: Ticket-Titel und Branchnamen landen im Prompt und sind untrusted (Prompt Injection) | hoch: Push mit den Git-Zugangsdaten des Benutzers, Zugriff auf andere Repos und Dateien | `prompts/agent-task.md`, README 4p sagt es selbst | T-2: Worktree je Lauf, eigener Unix-Benutzer ohne Push-Rechte auf geschützte Branches, Netz-Allowlist; oder Läufe als GitLab-CI-Jobs |
| SEC-2 | Kein Laufzeit- oder Kostenlimit | hoch (hängender Agent) | mittel: Kosten, blockierter Ordner | `agents.py`: kein Timeout ausser bei SSH-Aufrufen | `max_minutes` je Agent, Watchdog im Poll, `tmux kill-session` |
| SEC-3 | Manuelle Abnahme ohne SHA | mittel | mittel: Merge mit veralteter Abnahme | `flow.py` ohne SHA-Bezug | T-1 |
| SEC-4 | Freigabe nicht lesbar gilt als «kein Gate» | gering | mittel: «Mergen» ohne Review sichtbar | `flow.py:39–46` (`_approval` gibt None zurück → keine Prüfung) | Status «Freigabe unbekannt» als Warten anzeigen |
| SEC-5 | Schwärzen im Agenten-Log nach Muster | gering | mittel | `agents.py:266` `TOKEN_RE` | Agenten keine Secrets geben; Log-Aufbewahrung begrenzen |
| SEC-6 | Kein Audit | – | mittel: nicht nachvollziehbar, wer was wann ausgelöst hat | Log rotiert (`log_backups`) | T-3 |
| ok | Secrets nie in der config.json | – | – | `server.py:188` `PLAIN_SECRET_KEYS`, Schwärzen (`test_tinyops…test_scrub`) | – |
| ok | Prompt als Datei, nie als Shell-Code | – | – | `test_agents.Remote.test_full_run_with_hostile_prompt` | – |
| ok | GitHub und Sonar nur GET, Jira-Write nur mit Opt-in | – | – | `test_github.ClientTests.test_read_only`, `test_sonar…test_report_via_app_is_read_only…`, `test_ticket.test_create_is_off_by_default` | – |
| ok | Web-Zugriff | – | – | Loopback, Token ausserhalb, Host-Allowlist, CSRF-Header (`server.py:2381–2410`) | im Cluster zusätzlich einen OIDC-Proxy davor |

## 6. UX / Productivity Findings

- **Erfüllt:** eine primäre Aktion je Zeile, Details erst im Panel, Tastatur (j/k/Enter/a/n/i/Esc), Herkunft sichtbar (Jira, GitLab, GitHub, tiny), Blocker zuerst, Wartendes getrennt, Ideen ohne Branch.
- **Lücke «keine falsche Vollständigkeit»:** Je Zeile ist nicht sichtbar, wie alt die Daten sind. Bei einem Ausfall zeigt Fokus den letzten Stand ohne Hinweis am Eintrag; der Fehler steht nur im Banner.
- **Lücke F-01:** Der Fokus wechselt, sobald sich Prioritäten ändern (neue rote Pipeline). Das ist gut für Blocker, aber unruhig für die Konzentration. Ein angehefteter Fokus mit Hinweis «Blocker anderswo» wäre ruhiger.
- **Gamification** misst Stationen, nicht verifizierte Arbeit (North Star von A). Mit T-1 sollte «Fertig» erst nach SHA-gebundener Abnahme und Merge zählen.

---

## 7. Proposed Backlog (Top 5 als Tickets)

| Rang | Story | Scope | Akzeptanzkriterien | Tests | Abh. | Aufwand |
|---|---|---|---|---|---|---|
| T-1 | **Als** Entwickler **will ich**, dass «Getestet» an den Commit gebunden ist, **damit** ich nie eine veraltete Abnahme merge | Beim Setzen von `tested` den Head-SHA je MR/PR speichern (Tabelle `acceptance`: key, ref, sha, ts, note, env). Abgleich vergleicht mit dem aktuellen SHA | 1) neue Commits → Station zurück auf «Testen», Hinweis «neue Commits seit Test am …»; 2) Notiz und Umgebung optional; 3) Spielstand zählt «Fertig» nur nach gültiger Abnahme | Unit in `test_flow` (SHA gleich/ungleich, mehrere MRs), App-Test mit Mock-GitLab und SHA-Wechsel | – | S–M |
| T-2 | **Als** Verantwortlicher für DLP-Code **will ich** Agenten isoliert und begrenzt laufen lassen | a) `git worktree add` je Lauf auf eigenem Branch unter `<root>/.tinyops-wt/<nr>`, Aufräumen bei «Entfernen»; b) `max_minutes` je Agent (Standard 60) mit Kill und Status «abgelaufen»; c) optional eigener Unix-Benutzer je Verbindung | 1) zwei Läufe im selben Repo blockieren sich nicht mehr; 2) ein Lauf nach Ablauf ist beendet (Prozessbaum); 3) der Hauptcheckout bleibt unverändert | echtes tmux + ssh-Ersatz (wie `test_agents`): Worktree entsteht und verschwindet, Timeout greift bei `sleep 600`, lokaler Kill entfernt den Prozessbaum | – | M |
| T-3 | **Als** Nutzer **will ich** eine Historie aller Writes und Entscheidungen | Append-only-Tabelle `audit` (ts, actor, action, target, detail-hash, ok): Jira-Anlegen, Übersteuerung, Schritt erledigt, tiny-Ticket, Agent zuweisen/starten/stoppen inkl. Prompt-Hash, Abnahme (T-1); Ansicht im Panel «Verlauf» je Vorhaben; Export als JSON | 1) jede genannte Aktion erzeugt genau einen Eintrag; 2) Einträge lassen sich über die API nicht ändern oder löschen; 3) keine Secrets im Eintrag | Unit je Aktion, Test «Update/Delete nicht möglich», Schwärzungstest | – | S–M |
| T-4 | **Als** Nutzer **will ich** «unbekannt» sehen statt «in Ordnung» | Freigaben/Reviewer nicht lesbar → Warten «Freigabe unbekannt»; je Quelle «Stand vor X min» im Fokus-Kopf; Einträge aus einer fehlerhaften Quelle als «veraltet» markiert | 1) Approvals-Endpunkt 403 → kein «Manuell testen»; 2) GitLab-Ausfall → Fokus zeigt letzten Stand mit Alter, keine Erfolgsmeldung | Mock-GitLab mit 403 auf `/approvals`, Fault-Injection (Server aus) | – | S |
| T-5 | **Als** Nutzer **will ich** Klärungsfragen von Agenten in «Needs Me» beantworten | Konvention: Agent schreibt `$R/<nr>.question` (JSON: Frage, Optionen, blockierend) und wartet. Status «wartet auf Antwort», Eintrag unter «Du bist dran», Antwort wird als Datei zurückgeschrieben und per `tmux send-keys` signalisiert | 1) Frage erscheint genau einmal; 2) Antwort setzt den Lauf fort; 3) unbeantwortet nach Limit → «abgelaufen», keine Endlosschleife | tmux-Test mit Skript-Agent, der fragt und auf die Antwortdatei wartet | T-2 (Timeout) | M |
| T-6 | Quick Win: Fokus anheften | «Als Fokus setzen» im Panel, gespeichert; Blocker anderer Vorhaben als kleiner Hinweis statt Wechsel | genau ein angehefteter Fokus; Lösen jederzeit | Unit und UI-Screenshot | – | S |

**Bewusst nicht bauen** (in Übereinstimmung mit B, Abschnitt 3 «G16»):
- eigener Issue-Tracker, Confluence-Editor, Production-Deploy
- automatische Projectron-Buchung
- Umbau auf Spring/Angular/Postgres
- Kafka, Redis oder Vektordatenbank
- Approve oder Merge durch tinyops, solange T-1 und T-3 fehlen

---

## 8. Entscheidungen, die anstehen

1. **Bleibt GitLab nur lesend?** (A) F-19 und (B) G3/G4 wollen Approve oder «Ready» aus dem Panel; die bisherige Vorgabe lautet: nichts approven, mergen oder pushen.
   - Mein Vorschlag: lesend lassen. Höchstens «Draft → Ready» erlauben, mit eigenem Token, nur nach T-1 (Abnahme am aktuellen SHA) und T-3 (Audit), serverseitig geprüft.
   - Der Test aus (B) muss dabei gelten: Ein direkter Aufruf mit curl ohne erfüllte Gates ergibt 403.
2. **Agenten-Gateway:** SSH/tmux härten (T-2) oder Läufe als GitLab-CI-Jobs auf einem Agent-Runner, wie in (B) empfohlen? CI-Jobs bringen Audit, Laufzeitlimit und Rechte von GitLab mit, kosten aber den direkten tmux-Zugang.

## 9. Unknowns / Questions (max. 5)

1. Sollen Agenten **auf DLP-/Restricted-Repos** überhaupt laufen, und wenn ja, auf welchem Host und unter welchem Benutzer? Davon hängt ab, ob T-2 P0 ist.
2. Hat **Projectron** eine freigegebene API (REST, Export, keine)? Ohne Antwort bleibt F-20 offen; der Fallback wären Buchungsvorlagen zum Kopieren.
3. Läuft tinyops weiter **lokal** oder bald im **Cluster**? Im Cluster braucht es einen OIDC-Proxy (G6) und das gebaute Image (G18).
4. Liefert dein GitLab 19.2 `detailed_merge_status`, `reviewers` und `/approvals` für deine Projekte? Getestet ist das nur gegen Mock-Daten.
5. Brauchst du **Confluence** im Panel wirklich (Links je Ticket), oder reicht der Jira-Link?

---

## 10. Kurzfazit

- **Produktiv nutzbar:** Fokus, Board, Review-Queue, Jira/GitLab/GitHub/Sonar lesen, Ideen, Ticket-Entwurf und Anlegen mit Opt-in, Agentenstatus.
- **Blockiert einen sicheren MVP:** fehlende Commit-Bindung der Abnahme (T-1) und Agenten ohne Isolation und Zeitlimit (T-2), sofern Agenten auf DLP-Code laufen; fehlendes Audit (T-3).
- **Bewusst nicht bauen:** Approve oder Merge aus dem Panel vor T-1 und T-3, Stack-Umbau, eigene Systeme für Tickets, Doku oder Zeit.
- **Nächste drei kleinen Schritte:** T-4 (unbekannt statt grün, S), Laufzeitlimit aus T-2b (S), T-1 (S–M).
