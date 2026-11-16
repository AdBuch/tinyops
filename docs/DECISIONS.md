# Entscheide

Offene und getroffene Entscheide für tinyops. Jeder Eintrag sagt, was zur Wahl steht, was ich empfehle und bis wann es feststehen muss.
Getroffene Entscheide bleiben stehen, mit Datum und Begründung. Sie gelten, bis ein neuer Eintrag sie ersetzt.

## Getroffen

| Datum | Entscheid | Folge |
|---|---|---|
| 2026-11-05 | Agenten auf DLP-/Restricted-Repos nur mit lokalen Modellen | Datenklassen je Projekt, Cloud-Agent nur mit Freigabe |
| 2026-11-05 | GitLab bleibt nur lesend | kein Approve, Ready oder Merge aus tinyops |
| 2026-11-05 | Agenten über SSH/tmux, kein CI-Gateway | Worktree je Lauf, Zeitlimit |
| 2026-11-05 | tinyops läuft auf deinem Rechner | Handy später über VPN |
| 2026-11-05 | Confluence hat keine Priorität | nicht im Plan |
| 2026-11-15 | Bis 0.45 vor allem aufräumen; neu nur Projekte tracken, KI-Projekte, zweiter Bereich und App | Plan 0.33–0.45 in der Roadmap |
| 2026-11-15 | **E1:** Gebucht wird nur über BCS | Projectron-Export (0.19), MCP-Einstellungen und `/api/time/export` entfallen in 0.34; bisherige Entwürfe bleiben lesbar |
| 2026-11-15 | **E2:** Direkt ausführen reicht. Prompts und Shell-Befehle zum Kopieren bleiben, für den Fall, dass kein Agent eingerichtet ist | Helm-Deploy je MR, Jobs und alte Agenten-Knöpfe pro MR entfallen in 0.34 (`deploy/` bleibt: damit läuft tinyops selbst in Kubernetes). Die Review-Umgebung (0.32) führt direkt aus, auch für MRs. Review-Brief, Smoke-Test und Repro-Test bleiben als «Prompt kopieren» am MR, dazu die Befehle der Review-Umgebung und zum Auschecken zum Kopieren |
| 2026-11-16 | **E3:** Spielstand bleibt, als eine Karte im Fokus, abschaltbar | Level-Balken entfällt, Schalter «Spielstand» unter Weiteres (0.35). Entschieden mit «implement plans for 35» nach meiner Empfehlung |
| 2026-11-16 | **E4:** Zwei Begriffe: **Fokus** (woran du bist, mit Sitzung) und **Bereiche** (Wochenziel) | «Fokus-Modus» heisst «Vollbild», die Leiste gehört zur Sitzung (0.35). Entschieden wie E3 |
| 2026-11-16 | BCS-Middleware darf auch im eigenen Netz laufen, nur mit Haken und nur private Adressen | Wunsch: Middleware läuft auf dem Windows-Host. Bevorzugt bleibt 127.0.0.1 über WSL mirrored oder SSH-Tunnel (0.35.1) |

## Offen

| Nr. | Frage | Optionen | Empfehlung | Bis |
|---|---|---|---|---|
| E5 | Standard-Zyklus der Agenten? | a) Umsetzen → Review, Planen und Test zuschaltbar · b) immer alle vier Phasen | **a** | 0.39 |
| E6 | Oberfläche mit oder ohne Build-Schritt? | a) ohne: ES-Module direkt aus `static/` · b) mit npm und Bundler | **a**: der Launcher bleibt einfach | 0.38 |
| E7 | Privat und Geschäft? | a) zwei getrennte Instanzen mit Umschalter · b) eine Datenbank mit zwei Bereichen | **a**: Daten, Secrets und Audit bleiben sicher getrennt | 0.45 |
| E8 | Woher kommen KI-Projekte aus Claude, ChatGPT, Mistral? | a) Lesezeichen «In tinyops merken» und Import der offiziellen Daten-Exporte · b) mehr | **a**. Mehr ginge nur über Browser-Cookies oder fremde Sitzungen, und das macht tinyops nicht | 0.44 |
