# Entscheide

Offene und getroffene Entscheide für tinyops. Jeder Eintrag sagt, was zur Wahl steht, was ich empfehle und bis wann es feststehen muss.
Getroffene Entscheide bleiben stehen, mit Datum und Begründung. Sie gelten, bis ein neuer Eintrag sie ersetzt.
Seit dem 17.11. ist der Plan um eine Version verschoben (0.36 kam vor dem Umbau dazu), seit dem 20.11. ab 0.41 um zwei weitere (Testen von Hand, Reviews in GitLab), seit dem 23.11. ab 0.41 um noch eine (Agent-Branch übernehmen). Die Versionsnummern unten sind schon angepasst.

## Getroffen

| Datum | Entscheid | Folge |
|---|---|---|
| 2026-11-05 | Agenten auf DLP-/Restricted-Repos nur mit lokalen Modellen | Datenklassen je Projekt, Cloud-Agent nur mit Freigabe |
| 2026-11-05 | GitLab bleibt nur lesend | kein Approve, Ready oder Merge aus tinyops |
| 2026-11-05 | Agenten über SSH/tmux, kein CI-Gateway | Worktree je Lauf, Zeitlimit |
| 2026-11-05 | tinyops läuft auf deinem Rechner | Handy später über VPN |
| 2026-11-05 | Confluence hat keine Priorität | nicht im Plan |
| 2026-11-15 | Bis 0.45 vor allem aufräumen; neu nur Projekte tracken, KI-Projekte, zweiter Bereich und App | Plan 0.33–0.45 in der Roadmap (seit 17.11.: 0.33–0.46, seit 20.11.: 0.33–0.48, seit 23.11.: 0.33–0.49) |
| 2026-11-15 | **E1:** Gebucht wird nur über BCS | Projectron-Export (0.19), MCP-Einstellungen und `/api/time/export` entfallen in 0.34; bisherige Entwürfe bleiben lesbar |
| 2026-11-15 | **E2:** Direkt ausführen reicht. Prompts und Shell-Befehle zum Kopieren bleiben, für den Fall, dass kein Agent eingerichtet ist | Helm-Deploy je MR, Jobs und alte Agenten-Knöpfe pro MR entfallen in 0.34 (`deploy/` bleibt: damit läuft tinyops selbst in Kubernetes). Die Review-Umgebung (0.32) führt direkt aus, auch für MRs. Review-Brief, Smoke-Test und Repro-Test bleiben als «Prompt kopieren» am MR, dazu die Befehle der Review-Umgebung und zum Auschecken zum Kopieren |
| 2026-11-16 | **E3:** Spielstand bleibt, als eine Karte im Fokus, abschaltbar | Level-Balken entfällt, Schalter «Spielstand» (seit 0.35.1 unter Einstellungen → Fokus). Entschieden mit «implement plans for 35» nach meiner Empfehlung |
| 2026-11-16 | **E4:** Zwei Begriffe: **Fokus** (woran du bist, mit Sitzung) und **Bereiche** (Wochenziel) | «Fokus-Modus» heisst «Vollbild», die Leiste gehört zur Sitzung (0.35). Entschieden wie E3 |
| 2026-11-16 | BCS-Middleware darf auch im eigenen Netz laufen, nur mit Haken und nur private Adressen | Wunsch: Middleware läuft auf dem Windows-Host. Bevorzugt bleibt 127.0.0.1 über WSL mirrored oder SSH-Tunnel (0.35.1) |
| 2026-11-16 | **E5:** Standard-Zyklus der Agenten ist **Umsetzen → Review**. Planen und Test sind je Ticket zuschaltbar | Umsetzung in 0.40. Die Zuschaltung ist ein Schalter im Auftragsdialog, kein Eintrag in den Einstellungen |
| 2026-11-16 | **E7:** Privat und Geschäft als **zwei lokale Instanzen** | Je eigener Datenordner, Secrets, Audit und Worker. Die Privat-Instanz ist nur über VPN erreichbar oder gar nicht; die Geschäfts-Instanz nur im Arbeits-LAN. Keine Sicht zwischen den Instanzen. Die App wählt die Instanz, die gerade erreichbar ist (0.49). Die Privat-Instanz muss nicht aus derselben Codebasis kommen (siehe nächste Zeile) |
| 2026-11-16 | **E7a:** Die Privat-App hat einen **eigenen Release-Zyklus** in einem **eigenen Repo** | Eigene Roadmap, Changelog, Versionen und Auto-Tag. Die Release-Regeln von tinyops (ein Thema je Release, Takt) gelten dafür nicht. Gemeinsame Teile kommen später als kleines Paket |
| 2026-11-16 | **E6:** Oberfläche **mit Build-Schritt** (React, Bundler) für die Privat-App. Die Wahl der Technik liegt bei der Entwicklung | Gilt für die React-PWA ab 0.49. Die bestehende tinyops-Oberfläche bleibt ohne Build, bis 0.39 sie zerlegt. Die Roadmap-Zeile zu 0.39 bleibt daher gültig |
| 2026-11-16 | **E9:** Frontend als **Web-App (PWA) mit React**, keine native App | Zunächst nur Android. Installierbar und mit Offline-Cache. Gilt für beide Instanzen. **Keine Pflicht für Push-Benachrichtigungen**; Erinnerungen laufen in der App |
| 2026-11-16 | **E10:** HTTPS im LAN über einen echten Namen und ein Let's-Encrypt-Zertifikat (DNS-Challenge) | Funktioniert im LAN und über VPN gleich. Nötig, weil Chrome auf Android die PWA über `http://` nicht installieren lässt |
| 2026-11-16 | **E11:** Die App hinterlegt Heim- und Arbeitsadresse je Instanz; die erreichbare gewinnt | Tokens getrennt je Instanz, damit nie Privates an die Geschäfts-Instanz geht. Ein Knopf «Instanz wechseln» als Hand-Umschalter bleibt als Rückfall |
| 2026-11-16 | Team-Betrieb ist **keine Planung**, nur Idee (mögliche bezahlte Version) | Bleibt unter «Nicht im Plan» |
| 2026-11-17 | **E12:** Agenten dürfen ihren eigenen Lauf-Branch pushen, wenn du es je Agent einschaltest | Wunsch «Remote agents müssen pushen». Nie main, master, develop, release/*, kein Force-Push. tinyops selbst pusht weiter nie (0.36) |
| 2026-11-17 | **E13:** Kopplung je Gerät mit Einmal-Code; von aussen nur gekoppelte Geräte | Code 5 min, einmal, 5 Fehlversuche; nur der Hash des Geräte-Tokens liegt in der Datenbank. Gekoppelte Geräte ändern keine Einstellungen. Zwei Wege mit demselben Code: die tinyops-Seite selbst als App (Cookie, seit 0.36) und die eigene React-App nach E9 (Token als `Authorization: Bearer`, CORS nur für eingetragene App-Adressen, seit 0.36.2). Je Instanz eigene Geräte und Tokens, passend zu E11 |
| 2026-11-17 | Bis die React-App (E9, E7a) steht, ist die tinyops-Seite selbst die App (PWA, ohne Build) | Kein Widerspruch zu E6: die Seite bleibt ohne Build; sie bekam nur Manifest, Service Worker und Icons |
| 2026-11-17 | Plan verschiebt sich um eine Version: 0.36 vor dem Umbau, «Server zerlegen» ab 0.37 | Auf deinen Wunsch («nochmals eine Version vor dem grossen Refactoring») |
| 2026-11-17 | Rollen je Phase als Befehl am Anfang des Prompts (z. B. `/planner`) | Passt zu eigenen Slash-Befehlen auf dem Agenten-Rechner; ohne Rollen gilt der Agent für alle Phasen (0.36) |
| 2026-11-20 | **E14:** Reviews fremder MRs darf tinyops als **Entwurf in GitLab** anlegen («Review starten»). Abschicken machst du selbst in GitLab | Wunsch vom 20.11. Ersetzt für diesen einen Fall «GitLab bleibt nur lesend». Erlaubt sind nur deine eigenen Entwurfs-Kommentare (`draft_notes`: anlegen, ändern, löschen, und nur die, die tinyops selbst angelegt hat). Nie abschicken (`publish`, `bulk_publish`), nie Approve, Merge, Ready oder Threads auflösen. Entwürfe sieht bis zum Abschicken nur du. Dafür ein **zweites Token** `gitlab_review_token` mit Scope `api`, das nur dieser eine Weg benutzt; das Lese-Token bleibt `read_api`. Ehrlich: Ein `api`-Token könnte in GitLab alles. Die Grenze setzt tinyops im Code (feste Liste erlaubter Pfade, Test), nicht GitLab. Der Agent bekommt das Token nie: Er schreibt seine Befunde in eine Datei, tinyops legt daraus die Entwürfe an. Am 20.11. bestätigt: `api`-Zugang bekommst du. Umsetzung in 0.43 |
| 2026-11-20 | **Weiterführen in derselben Agenten-Sitzung**, mit dem ganzen Kontext | Klärung zu `r36-01`. «Weiterführen» setzt die Sitzung des Agenten fort (Claude Code `--resume`, Codex `exec resume`, Vibe `--resume`), im selben Worktree auf demselben Rechner. Geht das nicht (Sitzung weg, anderer Agent), bietet tinyops den bisherigen Weg an: neuer Lauf mit Zusammenfassung. Umsetzung in 0.40 |
| 2026-11-20 | Plan verschiebt sich ab 0.41 um zwei Versionen | «Testen von Hand» (heute 0.42) und «Reviews in GitLab» (heute 0.43) bekommen je ein Release, damit 0.40 beim Thema Agenten bleibt |
| 2026-11-20 | **Schwerpunkte:** schneller zum Testen von Hand, Agenten-Gefühl (vier Rollen, Kreislauf zurück zum Entwickeln), Reviews. Leitlinie: weniger Kopieren, weniger Wechseln, mehr Fokus | Microsoft 365 ist kein Schwerpunkt mehr und wird beim Härten nur gemacht, wenn du es dann brauchst. Gemessen an Kopier-Klicks und Wechseln im Nutzungsbericht |
| 2026-11-20 | **Offenlegen:** Jeder Aufruf, den tinyops nach aussen macht, steht in den Einstellungen (Methode, Pfad, lesend/schreibend, wann, Token, wie oft) | Eine Tabelle im Code, durch die jeder Aufruf muss; ein Test verhindert Aufrufe daran vorbei (0.43) |
| 2026-11-23 | **Update aus dem Panel und Dienst** (Wunsch vom 23.11.) | tinyops fragt höchstens alle 6 Stunden nur lesend nach neuen Release-Tags. Aktualisiert wird nur auf deinen Klick und nur am Rechner (nicht vom gekoppelten Gerät), über denselben Weg wie beim Start (Selbsttest, Rückfall). Dienst nur als Benutzer-Dienst (`systemctl --user`), nie mit sudo (0.40) |
| 2026-11-23 | «Umsetzen» heisst «Entwickeln», wie die Rolle (E5 bleibt: Standard Entwickeln → Review) | Rollen und Kreislauf in 0.40 |
| 2026-11-23 | **Branch übernehmen** (Wunsch vom 23.11.): tinyops darf in deinem lokalen Checkout einen Branch in einen anderen übernehmen (Fast-Forward, Rebase, Merge, Cherry-Pick) | Nur auf deinen Klick, nur am Rechner. In einem eigenen Worktree, dein Arbeitsordner wird nicht umgeschaltet. Der Ziel-Branch rückt nur vor, nie umgeschrieben; ist er ausgecheckt und hat Änderungen, passiert nichts. Gepusht wird weiter nie (0.41) |

## Offen

| Nr. | Frage | Optionen | Empfehlung | Bis |
|---|---|---|---|---|
| E8 | Woher kommen KI-Projekte aus Claude, ChatGPT, Mistral? | a) Lesezeichen «In tinyops merken» und Import der offiziellen Daten-Exporte · c) **Prompt zum Kopieren** (neu 18.11.): tinyops gibt dir je App einen Prompt, die App listet deine offenen Themen als JSON, du fügst das in tinyops ein · d) **Sitzungen der Coding-Agenten** (neu 18.11.): Claude Code, Codex und Vibe legen ihre Sitzungen als Dateien auf deinem Rechner ab; tinyops liest Ordner, Titel und Datum · b) mehr | **a + c + d**. c nutzt, was die Chat-Apps selbst über deine Chats wissen (bei Claude die Suche in früheren Chats); das ist hilfreich, aber nicht vollständig. d ist vollständig für die Agenten, weil es deine eigenen Dateien sind. Die Agenten selbst sehen deine Web-Chats nicht. Mehr ginge nur über Browser-Cookies oder fremde Sitzungen, und das macht tinyops nicht | 0.48 |

## Ideen, nicht geplant

- Home Assistant als Anbindung (Waschmaschine, Vorräte, Garten): noch keine Entscheidung, Einordnung nach 0.49.
- Mehrere Haushaltsmitglieder mit Rechten: an den Team-Betrieb gekoppelt, nicht geplant.
- Team-Betrieb als bezahlte Version: Idee, nicht geplant.
