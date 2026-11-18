# Entscheide

Offene und getroffene Entscheide für tinyops. Jeder Eintrag sagt, was zur Wahl steht, was ich empfehle und bis wann es feststehen muss.
Getroffene Entscheide bleiben stehen, mit Datum und Begründung. Sie gelten, bis ein neuer Eintrag sie ersetzt.
Seit dem 17.11. ist der Plan um eine Version verschoben (0.36 kam vor dem Umbau dazu). Die Versionsnummern unten sind schon angepasst.

## Getroffen

| Datum | Entscheid | Folge |
|---|---|---|
| 2026-11-05 | Agenten auf DLP-/Restricted-Repos nur mit lokalen Modellen | Datenklassen je Projekt, Cloud-Agent nur mit Freigabe |
| 2026-11-05 | GitLab bleibt nur lesend | kein Approve, Ready oder Merge aus tinyops |
| 2026-11-05 | Agenten über SSH/tmux, kein CI-Gateway | Worktree je Lauf, Zeitlimit |
| 2026-11-05 | tinyops läuft auf deinem Rechner | Handy später über VPN |
| 2026-11-05 | Confluence hat keine Priorität | nicht im Plan |
| 2026-11-15 | Bis 0.45 vor allem aufräumen; neu nur Projekte tracken, KI-Projekte, zweiter Bereich und App | Plan 0.33–0.45 in der Roadmap (seit 17.11.: 0.33–0.46) |
| 2026-11-15 | **E1:** Gebucht wird nur über BCS | Projectron-Export (0.19), MCP-Einstellungen und `/api/time/export` entfallen in 0.34; bisherige Entwürfe bleiben lesbar |
| 2026-11-15 | **E2:** Direkt ausführen reicht. Prompts und Shell-Befehle zum Kopieren bleiben, für den Fall, dass kein Agent eingerichtet ist | Helm-Deploy je MR, Jobs und alte Agenten-Knöpfe pro MR entfallen in 0.34 (`deploy/` bleibt: damit läuft tinyops selbst in Kubernetes). Die Review-Umgebung (0.32) führt direkt aus, auch für MRs. Review-Brief, Smoke-Test und Repro-Test bleiben als «Prompt kopieren» am MR, dazu die Befehle der Review-Umgebung und zum Auschecken zum Kopieren |
| 2026-11-16 | **E3:** Spielstand bleibt, als eine Karte im Fokus, abschaltbar | Level-Balken entfällt, Schalter «Spielstand» (seit 0.35.1 unter Einstellungen → Fokus). Entschieden mit «implement plans for 35» nach meiner Empfehlung |
| 2026-11-16 | **E4:** Zwei Begriffe: **Fokus** (woran du bist, mit Sitzung) und **Bereiche** (Wochenziel) | «Fokus-Modus» heisst «Vollbild», die Leiste gehört zur Sitzung (0.35). Entschieden wie E3 |
| 2026-11-16 | BCS-Middleware darf auch im eigenen Netz laufen, nur mit Haken und nur private Adressen | Wunsch: Middleware läuft auf dem Windows-Host. Bevorzugt bleibt 127.0.0.1 über WSL mirrored oder SSH-Tunnel (0.35.1) |
| 2026-11-16 | **E5:** Standard-Zyklus der Agenten ist **Umsetzen → Review**. Planen und Test sind je Ticket zuschaltbar | Umsetzung in 0.40. Die Zuschaltung ist ein Schalter im Auftragsdialog, kein Eintrag in den Einstellungen |
| 2026-11-16 | **E7:** Privat und Geschäft als **zwei lokale Instanzen** | Je eigener Datenordner, Secrets, Audit und Worker. Die Privat-Instanz ist nur über VPN erreichbar oder gar nicht; die Geschäfts-Instanz nur im Arbeits-LAN. Keine Sicht zwischen den Instanzen. Die App wählt die Instanz, die gerade erreichbar ist (0.46). Die Privat-Instanz muss nicht aus derselben Codebasis kommen (siehe nächste Zeile) |
| 2026-11-16 | **E7a:** Die Privat-App hat einen **eigenen Release-Zyklus** in einem **eigenen Repo** | Eigene Roadmap, Changelog, Versionen und Auto-Tag. Die Release-Regeln von tinyops (ein Thema je Release, Takt) gelten dafür nicht. Gemeinsame Teile kommen später als kleines Paket |
| 2026-11-16 | **E6:** Oberfläche **mit Build-Schritt** (React, Bundler) für die Privat-App. Die Wahl der Technik liegt bei der Entwicklung | Gilt für die React-PWA ab 0.46. Die bestehende tinyops-Oberfläche bleibt ohne Build, bis 0.39 sie zerlegt. Die Roadmap-Zeile zu 0.39 bleibt daher gültig |
| 2026-11-16 | **E9:** Frontend als **Web-App (PWA) mit React**, keine native App | Zunächst nur Android. Installierbar und mit Offline-Cache. Gilt für beide Instanzen. **Keine Pflicht für Push-Benachrichtigungen**; Erinnerungen laufen in der App |
| 2026-11-16 | **E10:** HTTPS im LAN über einen echten Namen und ein Let's-Encrypt-Zertifikat (DNS-Challenge) | Funktioniert im LAN und über VPN gleich. Nötig, weil Chrome auf Android die PWA über `http://` nicht installieren lässt |
| 2026-11-16 | **E11:** Die App hinterlegt Heim- und Arbeitsadresse je Instanz; die erreichbare gewinnt | Tokens getrennt je Instanz, damit nie Privates an die Geschäfts-Instanz geht. Ein Knopf «Instanz wechseln» als Hand-Umschalter bleibt als Rückfall |
| 2026-11-16 | Team-Betrieb ist **keine Planung**, nur Idee (mögliche bezahlte Version) | Bleibt unter «Nicht im Plan» |
| 2026-11-17 | **E12:** Agenten dürfen ihren eigenen Lauf-Branch pushen, wenn du es je Agent einschaltest | Wunsch «Remote agents müssen pushen». Nie main, master, develop, release/*, kein Force-Push. tinyops selbst pusht weiter nie (0.36) |
| 2026-11-17 | **E13:** Kopplung je Gerät mit Einmal-Code; von aussen nur gekoppelte Geräte | Code 5 min, einmal, 5 Fehlversuche; nur der Hash des Geräte-Tokens liegt in der Datenbank. Gekoppelte Geräte ändern keine Einstellungen. Zwei Wege mit demselben Code: die tinyops-Seite selbst als App (Cookie, seit 0.36) und die eigene React-App nach E9 (Token als `Authorization: Bearer`, CORS nur für eingetragene App-Adressen, seit 0.36.2). Je Instanz eigene Geräte und Tokens, passend zu E11 |
| 2026-11-17 | Bis die React-App (E9, E7a) steht, ist die tinyops-Seite selbst die App (PWA, ohne Build) | Kein Widerspruch zu E6: die Seite bleibt ohne Build; sie bekam nur Manifest, Service Worker und Icons |
| 2026-11-17 | Plan verschiebt sich um eine Version: 0.36 vor dem Umbau, «Server zerlegen» ab 0.37 | Auf deinen Wunsch («nochmals eine Version vor dem grossen Refactoring») |
| 2026-11-17 | Rollen je Phase als Befehl am Anfang des Prompts (z. B. `/planner`) | Passt zu eigenen Slash-Befehlen auf dem Agenten-Rechner; ohne Rollen gilt der Agent für alle Phasen (0.36) |

## Offen

| Nr. | Frage | Optionen | Empfehlung | Bis |
|---|---|---|---|---|
| E8 | Woher kommen KI-Projekte aus Claude, ChatGPT, Mistral? | a) Lesezeichen «In tinyops merken» und Import der offiziellen Daten-Exporte · c) **Prompt zum Kopieren** (neu 18.11.): tinyops gibt dir je App einen Prompt, die App listet deine offenen Themen als JSON, du fügst das in tinyops ein · d) **Sitzungen der Coding-Agenten** (neu 18.11.): Claude Code, Codex und Vibe legen ihre Sitzungen als Dateien auf deinem Rechner ab; tinyops liest Ordner, Titel und Datum · b) mehr | **a + c + d**. c nutzt, was die Chat-Apps selbst über deine Chats wissen (bei Claude die Suche in früheren Chats); das ist hilfreich, aber nicht vollständig. d ist vollständig für die Agenten, weil es deine eigenen Dateien sind. Die Agenten selbst sehen deine Web-Chats nicht. Mehr ginge nur über Browser-Cookies oder fremde Sitzungen, und das macht tinyops nicht | 0.45 |

## Ideen, nicht geplant

- Home Assistant als Anbindung (Waschmaschine, Vorräte, Garten): noch keine Entscheidung, Einordnung nach 0.46.
- Mehrere Haushaltsmitglieder mit Rechten: an den Team-Betrieb gekoppelt, nicht geplant.
- Team-Betrieb als bezahlte Version: Idee, nicht geplant.
