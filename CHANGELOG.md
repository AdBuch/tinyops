# Changelog

Semantic Versioning: **minor** (0.x.0) für neue Funktionen, **patch** (0.x.y) für Korrekturen und Fixes.
Solange die Hauptversion 0 ist, kann sich auch bei einer minor-Version noch etwas Grundsätzliches ändern.
Die Version steht in `server.py` (`VERSION`), im Git-Tag `vX.Y.Z`, im Docker-Tag und oben rechts im Panel.
Die frühere Zählung (1.0 bis 2.6) endet hier; **0.7.0 ist der neue Anfang** und enthält alles davon.

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
