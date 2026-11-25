// Hilfe in den Einstellungen: Texte je Abschnitt, aufgeklappt bleibt aufgeklappt.
// Hilfe zu den Einstellungen (0.27): je Abschnitt eine kurze Anleitung zum Aufklappen. Texte sind fest, ohne Daten aus der Konfiguration.
const HELP = {
  gitlab: `<ol><li>In GitLab oben rechts auf dein Bild, dann «Einstellungen» und «Zugriffstoken».</li><li>Neues Token mit dem Recht <code>read_api</code> anlegen. Mehr braucht tinyops nicht.</li>
    <li>Adresse (z. B. <code>https://gitlab.firma.ch</code>) und Token hier eintragen, «Verbindung testen».</li><li>Unter «Projekte» die Projekte wählen, die du sehen willst.</li></ol>
    <p>tinyops liest nur. Es gibt keine Funktion, die in GitLab freigibt, mergt oder pusht. <b>Datenklasse</b> je Projekt: <code>restricted</code> = nur lokale Agenten, <code>internal</code> und <code>public</code> = auch Cloud-Agenten.</p>`,
  identity: `<p>tinyops zeigt Branches ohne MR nur, wenn ein Commit von dir darauf liegt. Trag hier die Namen und Mail-Adressen ein, mit denen du committest (<code>git config user.email</code>), und die deiner Agenten.</p>`,
  filters: `<p>Muster für Branches, die nie erscheinen sollen (z. B. <code>renovate/*</code>), und das Alter, ab dem ein Branch als liegengeblieben gilt.</p>`,
  jira: `<ol><li>Adresse eintragen (z. B. <code>https://jira.firma.ch</code>).</li><li>Zugangsdaten passend zur Anmeldeart eintragen (persönliches Zugriffstoken aus dem Jira-Profil, sonst Benutzername und Passwort).</li><li>«Verbindung testen».</li></ol>
    <p>Die JQL bestimmt, was «in Arbeit» ist. Geschrieben wird nur, wenn «Tickets anlegen» an ist, und dann erst nach deiner Bestätigung im Dialog.</p>
    <p><b>Agenten und Tickets:</b> Steht im Ticket ein Abschnitt «Akzeptanzkriterien» mit Aufzählung, übernimmt tinyops die Punkte in den Auftrag an den Agenten.</p>`,
  github: `<ol><li>Auf github.com unter Settings → Developer settings ein «Fine-grained token» anlegen, nur lesend: Contents, Pull requests, Metadata.</li><li>Token eintragen, Repos wählen.</li></ol>
    <p>Für GitHub Enterprise die API-Adresse anpassen (<code>https://github.firma.ch/api/v3</code>).</p>`,
  sonar: `<p>Adresse und ein Benutzer-Token eintragen. Den Sonar-Schlüssel je Projekt trägst du bei den Projekten ein. tinyops fragt nur das Quality Gate ab.</p>`,
  update: `<p><b>Update:</b> tinyops sieht höchstens alle 6 Stunden nach, ob es ein neueres Release gibt (nur lesend, <code>git ls-remote</code>). Ist eines da, steht oben ein Hinweis mit «Jetzt aktualisieren».</p>
    <p>Aktualisieren geht wie beim Start über <code>start.py</code>: neue Version holen, Selbsttest, bei Fehlern zurück auf die alte. Danach startet tinyops neu und die Seite lädt von selbst. Deine Einstellungen, Zugangsdaten und Daten liegen ausserhalb des Programmordners und bleiben, wie sie sind.</p>
    <p>Nicht aktualisiert wird, wenn im Programmordner Dateien geändert sind oder er auf einem Branch steht (Entwicklung). Der Grund steht dann hier.</p>
    <p><b>Als Dienst (Linux):</b> tinyops startet dann bei der Anmeldung und nach einem Absturz von selbst, ohne Terminal. Es ist ein Benutzer-Dienst (<code>systemctl --user</code>), kein sudo nötig. Log: <code>journalctl --user -u tinyops -f</code>. Ohne Anmeldung (nach einem Neustart) läuft er erst nach einmal <code>loginctl enable-linger $USER</code>. Im Terminal geht dasselbe mit <code>python3 server.py --install-service</code>.</p>`,
  voice: `<p><b>Am einfachsten: «Eingebaut».</b> tinyops holt whisper.cpp, baut es für deinen Prozessor und lädt das Modell, alles auf einen Klick «Einrichten» (ein bis fünf Minuten, einmal). Eine Grafikkarte braucht es nicht.
    Zum Bauen braucht der Rechner git, cmake und einen C++-Compiler; unter Ubuntu einmal <code>sudo apt install build-essential cmake git</code>. tinyops selbst nutzt nie sudo.</p>
    <p><b>Modelle:</b> «small» (181 MB) ist der Standard und versteht Deutsch gut; «base» (57 MB) für schwache Rechner; «turbo» (547 MB) ist am genauesten, auf dem Prozessor aber spürbar langsamer. Gespeicherte Modelle werden vor dem ersten Einsatz gegen die Prüfsumme geprüft.</p>
    <p>Der Server läuft nur auf 127.0.0.1, startet beim ersten Diktieren und hört nach 20 Minuten ohne Nutzung wieder auf. Ein Modell im Speicher braucht etwa so viel RAM wie die Datei gross ist, plus etwas.</p>
    <p><b>Oder einen eigenen Server</b>, eines von beiden:</p>
    <p><b>whisper.cpp</b> (läuft auch ohne Grafikkarte): Modell laden, z. B. <code>ggml-small.bin</code> oder <code>ggml-large-v3-turbo-q5_0.bin</code>, dann
    <code>whisper-server -m models/ggml-small.bin --host 127.0.0.1 --port 8178 -l de</code>. Art «whisper.cpp-Server», Adresse <code>http://127.0.0.1:8178</code>.</p>
    <p><b>Voxtral Mini</b> (Mistral, braucht eine Grafikkarte mit etwa 10 GB): <code>vllm serve mistralai/Voxtral-Mini-3B-2507 --tokenizer_mode mistral --config_format mistral --load_format mistral</code>.
    Art «OpenAI-kompatibel», Adresse <code>http://127.0.0.1:8000</code>, Modell <code>mistralai/Voxtral-Mini-3B-2507</code>. Ebenso speaches oder faster-whisper-server.</p>
    <p><b>Diktieren:</b> In Prompt-Feldern (Auftrag, «Nachricht an …», Review-Ziel, Ideen, Prüfliste) erscheint oben rechts ein Mikrofon. Klick oder <kbd>Alt</kbd>+<kbd>M</kbd> startet, nochmal beendet; der Text kommt an die Cursorstelle.</p>
    <p><b>Sprachbefehl:</b> Taste <kbd>v</kbd> oder «Sagen» oben. Zum Beispiel «DLP-123 an Qwen zum Entwickeln», «DLP-123 an Claude planen, nur zuweisen», «Review für MR 47 mit Qwen». tinyops zeigt, was es verstanden hat; ausgeführt wird erst auf «Starten». Findet es kein Ticket, fragt es das lokale KI-Modell (falls eingerichtet).</p>
    <p>Das Mikrofon geht im Browser nur am Rechner (<code>localhost</code>) oder über <code>https</code>. Die Aufnahme geht als WAV an deinen Server und wird nirgends gespeichert.</p>`,
  calls: `<p>Diese Liste steht im Code (<code>apicalls.py</code>). Jede Stelle, die eine Verbindung nach aussen öffnet, zählt hier mit; ein Test prüft, dass es keine Stelle daran vorbei gibt und jeder Pfad im Code in der Liste steht.</p>
    <p><b>Zugang</b> nennt das Token oder Passwort, das der Aufruf benutzt. Agenten bekommen keines davon: tinyops entfernt sie aus der Umgebung jedes Laufs.</p>
    <p><b>Schreibend</b> sind nur: Jira-Ticket anlegen (mit Bestätigung), BCS buchen (auf Klick, nie wiederholt), Fokuszeit im Kalender (wenn erlaubt) und deine Review-Entwürfe in GitLab (eigenes Token, nie abschicken).</p>
    <p>Gezählt wird nur im Speicher und nur die Anzahl, nie Inhalte oder Parameter. Nach einem Neustart beginnt es bei null.</p>`,
  app: `<p><b>Als App am Rechner:</b> «Als App installieren» legt tinyops als eigenes Fenster ab. Es ist dieselbe Seite, nur ohne Browser-Leisten.</p>
    <p><b>Aufs Handy, Schritt für Schritt:</b></p>
    <ol><li>Den Rechner fürs Handy erreichbar machen, ohne tinyops ins Netz zu stellen. Am einfachsten mit <a href="https://tailscale.com/kb/1312/serve" target="_blank" rel="noopener">Tailscale Serve</a>: <code>tailscale serve --bg 8765</code>. Das gibt eine https-Adresse nur in deinem Tailnet; tinyops bleibt auf 127.0.0.1.</li>
    <li>Diese Adresse oben eintragen und speichern.</li>
    <li>«Code erzeugen». Auf dem Handy <code>&lt;Adresse&gt;/pair</code> öffnen und den Code eintippen.</li>
    <li>Auf dem Handy im Browser-Menü «Zum Startbildschirm» bzw. «App installieren».</li></ol>
    <p><b>Sicherheit:</b> Jede Anfrage, die nicht direkt von diesem Rechner kommt, braucht ein gekoppeltes Gerät. Gespeichert wird nur ein Hash des Geräte-Tokens. Daten werden auf dem Handy nicht zwischengespeichert, nur die leere Seite für den Start. Firmen-VPN oder Tailscale: kläre vorher, ob Dienstdaten auf ein privates Handy dürfen.</p>`,
  more: `<p>Hier schaltest du Funktionen ein, die nicht jeder braucht. Ausgeschaltet verschwinden sie aus der Oberfläche, ihre Daten bleiben erhalten.</p>
    <p><b>Ideenbox:</b> Einfälle festhalten (Taste <code>i</code>), bewerten lassen und als Ticket ausformulieren. <b>Testumgebungen:</b> die ältere Testumgebung je MR über Helm. Ab 0.34 geht sie in der Review-Umgebung auf (Einstellungen → IntelliJ und Review-Umgebung). <b>KI-Konten:</b> von Hand gepflegte Übersicht.</p>
    <p><b>UI-Nutzung erfassen:</b> Zählt Klicks, Mausweg, gewechselte Ansichten, Tasten ausserhalb von Feldern, Fehlermeldungen und langsame Antworten. Nie Eingaben, Titel oder Inhalte. Alles bleibt auf diesem Rechner. Den Bericht kopierst du unter «Prüfen» und gibst ihn weiter, wenn du willst.</p>`,
  agents: `<p><b>Der Zyklus: Planen → Entwickeln → Review → Test</b></p>
    <p>Jede Phase ist ein eigener Lauf und endet mit deiner Freigabe. <b>Planen</b>: Der Agent liest nur und schreibt einen Plan. <b>Umsetzen</b>: Code auf eigenem Branch, nach dem freigegebenen Plan. <b>Review</b>: Ein zweiter Agent (gern ein lokales Modell) liest das Ergebnis und ändert nichts. <b>Test</b>: Tests laufen lassen, fehlende ergänzen und Schritte für deinen Test von Hand beschreiben.</p>
    <p>Freigeben geht erst, wenn du die Prüfpunkte abgehakt hast: fürs Review den Diff gelesen, den Umfang geprüft und jedes Kriterium; für den Test die Schritte, die der Agent mit <code>tinyops-manual</code> beschrieben hat. «Zurückgeben» braucht einen Satz, was anders werden soll. Er geht in den Nachbessern-Auftrag. Kleine Aufgaben kannst du direkt umsetzen lassen, ohne Plan.</p>
    <p><b>Einfach reviewen</b></p>
    <p>Agenten begründen jede Datei im Bericht («Datei – was – warum»), nicht als Kommentar im Code. Im Lauf steht oben «Kurz vorab», dazu «In IntelliJ öffnen» (eigener Worktree neben deinem Checkout), «Befehle kopieren» und, falls eingerichtet, die Review-Umgebung. «Als MR-Beschreibung kopieren» ist für Reviewer im Team.</p>
    <p><b>Agent auf einem anderen Rechner (SSH), Schritt für Schritt</b></p>
    <ol><li>Auf <em>diesem</em> Rechner einen Schlüssel ohne Passphrase anlegen (tinyops kann keine Passphrase abfragen):<pre>ssh-keygen -t ed25519 -C tinyops -f ~/.ssh/tinyops_agent -N ""</pre></li>
    <li>Den öffentlichen Teil auf den Zielrechner bringen:<pre>ssh-copy-id -i ~/.ssh/tinyops_agent.pub benutzer@zielrechner</pre></li>
    <li>Einmal von Hand verbinden und den Fingerabdruck bestätigen. Wichtig: <code>-i</code> bekommt die Datei <em>ohne</em> <code>.pub</code>:<pre>ssh -i ~/.ssh/tinyops_agent benutzer@zielrechner</pre></li>
    <li>Auf dem Zielrechner: <code>sudo apt install tmux git</code>. Das Programm des Agenten muss in einer Login-Shell gefunden werden:<pre>bash -lc "which claude goose codex"</pre>Kommt nichts, den Ordner in <code>~/.profile</code> in den PATH eintragen.</li>
    <li>Hier unter «SSH-Verbindungen»: Rechner, Benutzer, Port 22, Schlüsseldatei <code>~/.ssh/tinyops_agent</code>.</li>
    <li>Beim Agenten die Verbindung wählen und als Arbeitsordner den Ordner angeben, in dem die Repos liegen (absolut, z. B. <code>/home/benutzer/workspace/projects</code>). «Testen».</li></ol>
    <p><b>Häufige Fehler:</b> «Permission denied» = der öffentliche Schlüssel fehlt in <code>~/.ssh/authorized_keys</code> des Zielrechners, oder die Rechte sind zu offen (<code>chmod 700 ~/.ssh; chmod 600 ~/.ssh/authorized_keys</code>). «UNPROTECTED PRIVATE KEY FILE» = <code>chmod 600 ~/.ssh/tinyops_agent</code>, und nicht die <code>.pub</code>-Datei angeben.</p>
    <p><b>Projekte beim Agenten:</b> Ein Projekt liegt unter Arbeitsordner/Projektname (oder dem «Agenten-Ordner» des Projekts). Fehlt es, bietet der Zuweisen-Dialog «Jetzt klonen» an. Geklont wird mit den Git-Zugangsdaten des Zielrechners: Für SSH muss dessen Schlüssel bei GitLab oder GitHub hinterlegt sein (prüfen mit <code>ssh -T git@gitlab.firma.ch</code> auf dem Zielrechner).</p>
    <p><b>Schreibrechte der Cloud-CLIs:</b> Claude Code braucht in «Zusätzliche Argumente» <code>--permission-mode acceptEdits</code>, Codex <code>--full-auto</code>, Mistral Vibe <code>--auto-approve</code>. Sonst ändern sie im Lauf keine Dateien und lehnen Werkzeugaufrufe ab.</p>
    <p><b>Mitlesen:</b> Claude Code und Vibe laufen mit Streaming-Ausgabe (<code>--output-format stream-json</code> bzw. <code>--output streaming</code>). tinyops zeigt daraus im Lauf, was der Agent gerade tut. Wer im tmux mitliest, sieht die rohen JSON-Zeilen. Setzt du das Ausgabeformat selbst in den zusätzlichen Argumenten, lässt tinyops seines weg.</p>
    <p><b>Goose mit Qwen oder anderen Modellen:</b> Art «Goose», Modell = der Name, unter dem dein Proxy oder Ollama das Modell führt. Anbieter leer lassen, wenn Goose auf dem Zielrechner schon eingerichtet ist (<code>goose configure</code>); tinyops setzt dann nur <code>GOOSE_MODEL</code>.
      Laufen alle Modelle über denselben Proxy, leg je Modell einen Agenten an und setz den Haken «sendet Daten an einen Cloud-Anbieter» bei jedem, das nicht im eigenen Netz rechnet. Nur Agenten ohne den Haken dürfen an <code>restricted</code>-Projekte.</p>
    <p><b>Eigener Befehl:</b> steht nur in der config.json (<code>"command"</code>, mit <code>{prompt_file}</code>), damit niemand über die Oberfläche Befehle einschleusen kann.</p>`,
  ide: `<p>Der Befehl, der IntelliJ mit einem Ordner startet, z. B. <code>idea {path}</code> oder <code>/opt/idea/bin/idea.sh {path}</code>. Darunter trägst du je Projekt ein, wo dein lokaler Klon liegt.</p>`,
  time: `<p><b>BCS buchen (über deine Middleware):</b> «In BCS buchen» einschalten, Adresse (Standard <code>http://127.0.0.1:3210</code>) und, falls gesetzt, das <code>BCS_API_TOKEN</code> eintragen. Dann in der Zeit-Ansicht:</p>
    <ol><li>Entwürfe prüfen und «Bestätigen» (das bucht noch nichts).</li><li>Je Entwurf einmal «BCS-Aufgabe wählen». Mit «für alle DLP-… merken» gilt die Zuordnung fürs ganze Projekt.</li>
    <li>«In BCS prüfen»: Die Middleware prüft alle bestätigten Buchungen des Tages gemeinsam und zeigt Warnungen.</li><li>«In BCS buchen»: genau ein Versuch. Nur «committed» gilt als gebucht.</li></ol>
    <p>Bricht die Verbindung beim Buchen ab, werden die Entwürfe «unklar». tinyops wiederholt nie von selbst; «Mit BCS abgleichen» liest den Tag und markiert, was dort schon steht.</p>
    <p>Die Zeit läuft auf dem angehefteten Vorhaben, solange du das Panel benutzt. Nach <b>Leerlauf-Minuten</b> ohne Aktivität endet der Abschnitt, und tinyops fragt später, wohin die Lücke gehört.</p>
    <p>Eine <b>Fokus-Sitzung</b> zählt als Aktivität, auch wenn du im Editor arbeitest. Sie endet von selbst zehn Minuten nach der Zeitbox, wenn du nicht verlängerst. Gebucht wird nichts automatisch: Du bestätigst die Entwürfe.</p><p><b>Middleware auf einem anderen Rechner</b> (z. B. tinyops in WSL oder einer VM, die Middleware auf dem Windows-Host). Drei Wege, der erste ist der einfachste:</p>
<ul><li><b>WSL:</b> in <code>%UserProfile%\.wslconfig</code> unter <code>[wsl2]</code> die Zeile <code>networkingMode=mirrored</code> eintragen, <code>wsl --shutdown</code>. Dann gilt <code>http://127.0.0.1:3210</code> auch in WSL, ohne Haken.</li>
<li><b>SSH-Tunnel:</b> <code>ssh -N -L 3210:127.0.0.1:3210 du@windows-host</code>. tinyops spricht mit 127.0.0.1, die Middleware sieht eine lokale Anfrage.</li>
<li><b>Direkt im Netz:</b> Haken «Middleware im eigenen Netz», Adresse wie <code>http://10.x.x.x:3210</code>. Die Middleware muss Anfragen aus dem Netz annehmen; sonst meldet sie «nicht lokal» (403).</li></ul>`,
  focusareas: `<p>Je Bereich ein Wochenziel in Prozent (z. B. Berufsbildung 30) und optional feste Blöcke (Tag, von, bis). Ein Bereich ohne Ticket bucht auf seinen Namen. Die Tätigkeiten erscheinen als Schnellwahl in der Fokus-Sitzung.</p>`,
  workspaces: `<p>Trag die Ordner ein, in denen deine Projekte liegen (z. B. <code>~/work</code>). tinyops sucht darunter bis zur eingestellten Tiefe nach Git-Repos und zeigt, was nur auf deinem Rechner liegt.</p>
    <p>Der <b>Geheimnis-Scan</b> prüft ungepushte Commits und offene Änderungen auf Passwörter und Tokens. tinyops pusht nie selbst; «Abholen» macht nur <code>git fetch</code>.</p>`,
  helpdesk: `<ol><li>Adresse des Helpdesk-Jira eintragen und die Anmeldeart wählen: Jira 8.5 kennt nur Benutzername und Passwort (basic), ab 8.14 geht ein persönliches Zugriffstoken (bearer).</li>
    <li>Die drei JQL prüfen: «mir zugewiesen», «Queue», «ich beobachte». Die Knöpfe darunter setzen gängige Vorlagen.</li><li>«Verbindung testen» zeigt je JQL die Trefferzahl.</li></ol><p>Dieses Jira wird nur gelesen.</p>`,
  usage: `<p>Claude und Codex: tinyops nimmt das Token aus der Anmeldedatei der jeweiligen CLI auf diesem Rechner und fragt damit das freie Kontingent ab. Die Schnittstelle ist inoffiziell und kann sich ändern. Mistral: Der Stand kommt über ein Lesezeichen aus deinem Browser.</p>`,
  llm: `<p>Für Ticket-Entwürfe und Bewertungen im Panel (nicht für Agenten). Ollama: Adresse <code>http://127.0.0.1:11434</code>, Modell wie in <code>ollama list</code>. OpenAI-kompatibel (llama.cpp, LiteLLM, vLLM): Basisadresse mit oder ohne <code>/v1</code> und der Modellname.</p>
    <p>Adressen ausserhalb des eigenen Netzes sind gesperrt, solange «entfernte Adresse erlauben» aus ist.</p>`,
  m365: `<p><b>Einmalig in Entra ID (Azure AD) – das macht meist die IT:</b></p>
    <ol><li>«App-Registrierungen» → «Neue Registrierung». Name z. B. «tinyops», Kontotyp «Nur Konten in diesem Organisationsverzeichnis».</li>
    <li>Plattform hinzufügen: <b>«Mobile- und Desktopanwendungen»</b>, Umleitungs-URI <code>http://localhost</code> (der Port spielt dort keine Rolle).</li>
    <li>Unter «Authentifizierung» <b>«Öffentliche Clientflows zulassen»</b> auf Ja (für «Mit Code anmelden»). Kein Geheimnis und kein Zertifikat anlegen.</li>
    <li>«API-Berechtigungen» → Microsoft Graph → <b>delegiert</b>: <code>User.Read</code>, <code>Mail.Read</code>, <code>Calendars.Read</code> (oder <code>Calendars.ReadWrite</code> fürs Eintragen der Fokuszeit), <code>Chat.Read</code>, <code>offline_access</code>. Je nach Richtlinie erteilt ein Admin die Zustimmung.</li>
    <li>Aus «Übersicht» die <b>Anwendungs-ID (Client)</b> und die <b>Verzeichnis-ID (Tenant)</b> hier eintragen, speichern, «Anmelden».</li></ol>
    <p>Die Anmeldung läuft im Browser mit deiner 2FA. tinyops speichert nur das Refresh-Token (Schlüsselbund oder secrets.json) und fragt erst wieder nach, wenn Microsoft es verlangt (Ablauf, Conditional Access, Passwortwechsel).</p>
    <p><b>Was tinyops liest:</b> Mails der letzten Tage im Posteingang (Absender, Betreff, Vorschau), deine Termine heute und morgen, die letzte Nachricht deiner Chats. Nichts davon verlässt deinen Rechner. <b>Was es schreibt:</b> nur den Termin «Fokus: …», wenn du «Fokuszeit eintragen dürfen» einschaltest und beim Start der Sitzung anhakst.</p>
    <p><b>«Wartet auf dich»</b> heisst: direkt an dich, nicht von dir, nicht von einer Absenderadresse wie no-reply, und noch nicht beantwortet. Dazu alles mit Fähnchen.</p>`,
  where: `<p>Die config.json enthält keine Geheimnisse: Tokens liegen im Schlüsselbund des Systems oder in der Datei daneben mit Rechten nur für dich. Das Protokoll zeigt jede schreibende Aktion.</p>`,
};
function secretHelp(name, label) {
  const st = S.secrets[name];
  if (st.error) return `<span style="color:var(--bad)">${esc(st.error)}</span>`;
  return st.set ? `Gespeichert (← ${esc(st.source)}). Feld leer lassen, um ihn zu behalten.` : `Noch kein ${label} gespeichert.`;
}
document.addEventListener('toggle', ev => { const d = ev.target; if (d.dataset && d.dataset.help) { LS.set('help.' + d.dataset.help, d.open); if (d.open && typeof uxPush === 'function' && uxOn()) uxPush({ k: 'help', t: d.dataset.help }); } }, true);
