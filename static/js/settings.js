// Einstellungen: alle Abschnitte, Verbindungstests, Speichern.
function stepsHtml(res) {
  const ic = { ok: '✓', fail: '✗', warn: '!', skip: '–' };
  return '<div class="steps">' + res.steps.map(s => `
    <div class="step ${esc(s.status)}"><span class="ic">${ic[s.status] || '?'}</span><div>
      <div class="st">${esc(s.title)}</div>
      ${s.detail ? `<div class="sd">${esc(s.detail)}</div>` : ''}
      ${s.hint ? `<div class="hint">💡 ${esc(s.hint)}</div>` : ''}</div></div>`).join('')
    + `<div class="verdict ${res.ok ? 'ok' : 'bad'}">${res.ok ? 'Verbindung in Ordnung.' : 'Nicht in Ordnung: Der erste rote Schritt zeigt, wo es hängt.'}</div></div>`;
}
async function loadSettings() {
  const box = $('viewSettings');
  try { S = await api('GET', '/api/settings'); } catch (e) { box.innerHTML = `<div class="banner bad">${esc(e.message)}</div>`; return; }
  P = S.projects.map(p => ({ ...p }));
  const g = S.gitlab, j = S.jira, b = S.branch_filter;
  const glTokenUrl = g.url ? esc(g.url.replace(/\/+$/, '')) + '/-/user_settings/personal_access_tokens' : '';
  const sect = (id, title, lead, body) => `<section class="sset" id="s-${id}"><header><h2>${title}</h2><p class="lead">${lead}</p></header>${HELP[id] ? `<details class="help" data-help="${id}" ${LS.get('help.' + id, false) ? 'open' : ''}><summary>Hilfe: so richtest du das ein</summary><div class="helpbody">${HELP[id]}</div></details>` : ''}${body}</section>`;
  box.innerHTML = `
  ${S.demo ? '<div class="banner warn">Demo-Modus: Tests funktionieren, Speichern ist ausgeschaltet.</div>' : ''}
  ${!S.configured && !S.demo ? `<div class="banner warn"><strong>Erst verbinden.</strong> Trage unten GitLab (und, wenn du magst, Jira) ein, drücke jeweils «Verbindung testen» und dann «Speichern».</div>` : ''}
  ${tokBox(S)}
  <div class="setgrid">
   <nav class="setnav" aria-label="Abschnitte">
     <button data-goto="gitlab" class="on">GitLab</button><button data-goto="identity">Meine Commits</button>
     <button data-goto="filters">Filter</button><button data-goto="jira">Jira</button>
     <button data-goto="github">GitHub</button><button data-goto="sonar">Sonar</button><button data-goto="agents">Agenten</button><button data-goto="ide">IntelliJ</button><button data-goto="usage">KI-Kontingent</button><button data-goto="llm">KI-Entwurf</button><button data-goto="time">Zeit</button><button data-goto="focusareas">Fokus</button><button data-goto="workspaces">Workspaces</button><button data-goto="helpdesk">Helpdesk</button><button data-goto="m365">Microsoft 365</button><button data-goto="app">App und Handy</button><button data-goto="more">Weiteres</button><button data-goto="where">Ablage</button>
   </nav>
   <div>
  ${sect('gitlab', 'GitLab', 'Zeigt deine MRs, die Review-Queue und offene Branches. Der Token braucht nur Leserechte.', `
    <div class="grid2">
      ${field('gl-url', 'Adresse', g.url, { ph: 'https://gitlab.firma.example', err: 'gitlab.url', help: 'Nur die Basisadresse, ohne /api/v4 und ohne Projektpfad.' })}
      ${field('gl-ca', 'CA-Datei (optional)', g.ca_bundle, { ph: '/pfad/zur/firmen-ca.pem', help: 'Nur bei einer Firmen-CA nötig. Gilt auch für Jira. Die Zertifikatsprüfung bleibt immer an.' })}
    </div>
    ${field('gl-token', 'Zugriffstoken', '', { type: 'password', ph: S.secrets.gitlab_token.set ? '•••••••• gespeichert' : 'glpat-…', err: 'gitlab_token',
      help: secretHelp('gitlab_token', 'Token') + (glTokenUrl ? ` Neu anlegen: <a href="${glTokenUrl}" target="_blank" rel="noopener">Persönliche Zugriffstoken</a>, Scope nur <code>read_api</code>, Ablaufdatum setzen.` : '') })}
    <div class="row">
      <button class="primary" id="gl-test">Verbindung testen</button>
      ${S.secrets.gitlab_token.set ? '<button id="gl-del">Gespeicherten Token löschen</button>' : ''}
      <span class="quiet small">Testet mit den Werten in den Feldern, auch ungespeicherten.</span>
    </div>
    <div id="gl-result"></div>
    <h3>Projekte</h3>
    <div class="quiet small" style="margin-bottom:8px">Diese Projekte beobachtet das Panel (MRs und Branches). Review-Queue und dir zugeteilte MRs kommen projektübergreifend.</div>
    <div id="pj-list"></div>
    <div class="row"><input type="text" id="pj-q" style="max-width:340px" placeholder="Name oder Projekt-ID suchen" autocomplete="off"><button id="pj-search">Suchen</button></div>
    <div id="pj-res" style="margin-top:8px"></div>
    <div class="ferr" data-err="projects"></div>`)}

  ${sect('identity', 'Meine Commits', 'Branches ohne MR erscheinen, wenn mindestens ein Commit von dir oder deinem Agenten darauf liegt.', `
    <div class="row" style="margin-bottom:10px"><button id="id-suggest">Aus den letzten Commits vorschlagen</button>
      <span class="quiet small">Braucht eine funktionierende GitLab-Verbindung und ein Projekt.</span></div>
    <div id="id-result"></div>
    <div class="grid2">
      ${field('bf-emails', 'Meine E-Mail-Adressen', b.emails.join(', '), { err: 'branch_filter.emails', help: 'Komma getrennt. Alle Adressen, unter denen du committest.' })}
      ${field('bf-names', 'Meine Autorennamen', b.names.join(', '), { err: 'branch_filter.names' })}
      ${field('bf-aemails', 'E-Mail-Adressen des Agenten', b.agent_emails.join(', '), { err: 'branch_filter.agent_emails', help: 'Nur, wenn der Agent unter einem eigenen Konto committet.' })}
      ${field('bf-anames', 'Namen des Agenten', b.agent_names.join(', '), { err: 'branch_filter.agent_names' })}
    </div>
    ${field('bf-pat', 'Muster in Commit-Nachrichten, die den Agenten kennzeichnen', b.agent_message_patterns.join(', '), { err: 'branch_filter.agent_message_patterns',
      help: 'Zum Beispiel <code>Co-Authored-By: Claude</code>. Markiert nur («Agent»); ein Branch erscheint nur wegen Commits von dir oder dem Agenten-Konto.' })}`)}

  ${sect('filters', 'Filter', 'Was auf der Übersicht erscheinen soll und was nicht.', `
    ${field('bf-ignore', 'Branches ignorieren', (b.ignore_branches || []).join(', '), { err: 'branch_filter.ignore_branches', ph: 'release/*, hotfix/*',
      help: 'Muster mit <code>*</code> als Platzhalter, Groß/Klein zählt. <code>release/*</code> blendet alle Branches aus, die mit «release/» beginnen: Branches ohne MR und deine eigenen MRs. Review-Anfragen und dir zugeteilte MRs bleiben sichtbar.' })}
    <div class="grid2">
      ${field('bf-max', 'Höchstens so viele Branches pro Projekt prüfen', b.max_branches, { type: 'number', err: 'branch_filter.max_branches' })}
      ${field('bf-age', 'Branches älter als so viele Tage ignorieren (0 = nie)', b.max_age_days, { type: 'number', err: 'branch_filter.max_age_days' })}
    </div>`)}

  ${sect('jira', 'Jira', 'Optional. Verknüpft MRs und Branches mit Tickets und zählt die Stories in Arbeit. Adresse leer lassen = Jira aus.', `
    <div class="grid2">
      ${field('ji-url', 'Adresse', j.url, { ph: 'https://jira.firma.example', err: 'jira.url', help: 'Basisadresse (mit Kontextpfad, falls Jira unter /jira läuft).' })}
      <div class="field"><label for="ji-auth">Anmeldeart</label>
        <select class="full" id="ji-auth"><option value="bearer" ${j.auth === 'bearer' ? 'selected' : ''}>bearer: Personal Access Token (empfohlen)</option>
          <option value="basic" ${j.auth === 'basic' ? 'selected' : ''}>basic: Benutzername + Passwort</option></select>
        <div class="ferr" data-err="jira.auth"></div></div>
    </div>
    <div id="ji-userbox">${field('ji-user', 'Benutzername', j.username, { err: 'jira.username', help: 'Meist der Jira-Benutzername, nicht die E-Mail-Adresse.' })}</div>
    <div id="ji-secbox"></div>
    <div class="grid2">
      ${field('ji-keys', 'Projekt-Keys', j.project_keys.join(', '), { err: 'jira.project_keys', ph: 'DLP, OPS', help: 'Damit erkennt das Panel Ticket-Nummern in Branch-Namen.' })}
      ${field('ji-limit', 'Höchstens so viele Stories gleichzeitig in Arbeit', j.story_limit, { type: 'number', err: 'jira.story_limit' })}
    </div>
    ${field('ji-types', 'Vorgangstypen, die beim Limit zählen', j.wip_issue_types.join(', '), { err: 'jira.wip_issue_types', help: 'Deutsche Instanzen: oft «Aufgabe», «Fehler». Leer = alle Typen zählen. Andere Typen bleiben sichtbar, zählen aber nicht.' })}
    ${field('ji-grp', 'Link-Typen, die Tickets zu einem Task gruppieren', (j.group_link_types || []).join(', '), { err: 'jira.group_link_types', ph: 'leer = jeder Link zwischen Tickets in Arbeit', help: 'Z. B. «Relates», «Begleitticket». Bug mit Begleitticket: der Bug ist der Task. Unteraufgaben gehören immer zu ihrer Story.' })}
    <label class="check"><input type="checkbox" id="ji-sprint" ${j.only_active_sprints !== false ? 'checked' : ''}>
      <span><strong>Nur Tickets aus aktiven Sprints</strong><br><span class="quiet small">Ergänzt die JQL um <code>sprint in openSprints()</code> und markiert verknüpfte Tickets ausserhalb eines Sprints. Braucht Jira Software. Der Test unten sagt, ob es funktioniert.</span></span></label>
    <label class="check"><input type="checkbox" id="ji-create" ${j.allow_create ? 'checked' : ''}>
      <span><strong>Tickets aus dem Panel anlegen</strong><br><span class="quiet small">Das ist der einzige Schreibzugriff auf Jira. Er läuft nur, wenn du im Dialog «In Jira anlegen» drückst und bestätigst. Das Konto braucht dort die Berechtigung «Vorgänge erstellen». Aus = das Panel bleibt rein lesend.</span></span></label>
    ${field('ji-ctype', 'Vorgangstyp, der im Dialog vorgewählt ist', j.create_type || 'Story', { err: 'jira.create_type' })}
    ${field('ji-jql', 'JQL für «in Arbeit»', j.jql_in_progress, { area: true, rows: 2, err: 'jira.jql_in_progress',
      help: 'Zuerst im Jira-Suchfeld (Erweitert) probieren. Der Test unten zeigt die ersten Treffer.' })}
    <div class="row"><button class="primary" id="ji-test">Verbindung testen</button>
      ${(S.secrets.jira_token.set || S.secrets.jira_password.set) ? '<button id="ji-del">Gespeicherte Zugangsdaten löschen</button>' : ''}</div>
    <div id="ji-result"></div>`)}

  ${sect('github', 'GitHub', 'Zusätzlich zu GitLab: eigene Pull Requests, eigene Branches, Review-Anfragen und dir zugewiesene PRs von github.com oder GitHub Enterprise. Nur lesend: tinyops stellt ausschliesslich GET-Anfragen.', `
    <label class="check"><input type="checkbox" id="gh-on" ${S.github.enabled ? 'checked' : ''}><span><strong>GitHub einschalten</strong></span></label>
    <div class="grid2">
      ${field('gh-api', 'API-Adresse', S.github.api_url, { err: 'github.api_url', ph: 'https://api.github.com', help: 'github.com: https://api.github.com · Enterprise: https://host/api/v3' })}
      ${field('gh-secret', 'Token', '', { type: 'password', err: 'github_token', ph: S.secrets.github_token.set ? '•••••••• gespeichert' : 'github_pat_…', help: secretHelp('github_token', 'Token') + ' Feingranularer Token, nur Lesen: Metadata, Contents, Pull requests, Commit statuses, Checks.' })}
    </div>
    <div class="row"><button class="primary" id="gh-test">Verbindung testen</button>${S.secrets.github_token.set ? '<button id="gh-del">Gespeicherten Token löschen</button>' : ''}</div>
    <div id="gh-result"></div>
    <h3>Repos</h3>
    <div class="quiet small" style="margin-bottom:8px">Aus diesen Repos kommen deine PRs und Branches. Review-Anfragen und zugewiesene PRs kommen aus allen Repos, die der Token sehen darf.</div>
    <div id="gh-list"></div>
    <div class="row"><input type="text" id="gh-q" style="max-width:340px" placeholder="Name oder owner/name suchen" autocomplete="off"><button id="gh-search">Suchen</button></div>
    <div id="gh-res" style="margin-top:8px"></div>
    <div class="ferr" data-err="github.repos"></div>`)}

  ${sect('sonar', 'SonarQube', 'Zeigt das Quality Gate je MR und Branch. Nur lesend: tinyops stellt ausschliesslich GET-Anfragen. Den Sonar-Schlüssel trägst du je Projekt unter GitLab ein.', `
    <label class="check"><input type="checkbox" id="sq-on" ${S.sonar.enabled ? 'checked' : ''}><span><strong>Sonar einschalten</strong></span></label>
    <div class="grid2">
      ${field('sq-url', 'Adresse', S.sonar.url, { err: 'sonar.url', ph: 'https://sonar.example.intern', help: 'Läuft Sonar unter einem Kontextpfad, gehört er dazu (https://host/sonar).' })}
      ${field('sq-secret', 'Token', '', { type: 'password', err: 'sonar_token', ph: S.secrets.sonar_token.set ? '•••••••• gespeichert' : '', help: secretHelp('sonar_token', 'Token') + ' Ein User-Token reicht; es braucht «Browse» auf den Projekten.' })}
    </div>
    <div class="grid2">
      ${field('sq-cache', 'Zwischenspeicher in Sekunden', S.sonar.cache_seconds, { type: 'number', err: 'sonar.cache_seconds', help: 'So lange gilt ein Ergebnis, bevor erneut gefragt wird.' })}
      ${field('sq-max', 'Höchstens so viele Prüfungen je Abgleich', S.sonar.max_items, { type: 'number', err: 'sonar.max_items' })}
      ${field('sq-rep', 'Höchstens so viele Findings im Report', S.sonar.report_max, { type: 'number', err: 'sonar.report_max', help: 'Für «Report kopieren»: nach Schwere sortiert, der Rest steht in Sonar. Der Report enthält Dateipfade, Zeilen, Regeln und Sonar-Meldungen, aber keinen Quelltext.' })}
    </div>
    <div class="hint">Quality Gates je Merge Request gibt es nur in SonarQube ab Developer Edition. In der Community Edition zeigt tinyops sie für Branches nur, wenn dort mehrere Branches analysiert werden; sonst steht «keine Analyse».</div>
    <div class="row"><button class="primary" id="sq-test">Verbindung testen</button>
      ${S.secrets.sonar_token.set ? '<button id="sq-del">Gespeicherten Token löschen</button>' : ''}</div>
    <div id="sq-result"></div>`)}

  ${sect('agents', 'Coding-Agenten', 'Lokale und über SSH/tmux erreichbare Agenten (Claude Code, Codex, Mistral Vibe, eigener Befehl), die du auf der Karte einem Ticket zuweist und startest. Je Agent legst du den Arbeitsordner fest; darunter liegt je Projekt ein Repository.', `
    <div class="hint">Cloud-Agenten (Claude, Codex, Vibe) senden Prompt und Code an den Anbieter. Für Projekte der Datenklasse «restricted» starten nur lokale Agenten; bei «internal» sehen Cloud-Agenten nur die freigegebenen Pfade. Jede Zuweisung, jeder Start und jede Übernahme steht im Verlauf (Log → Verlauf). tinyops fragt nie nach Passwörtern: SSH läuft mit Schlüsseln, ohne Rückfrage, mit strenger Host-Schlüsselprüfung.</div>
    <h3>Verbindungen</h3>
    <div id="cn-list"></div><div class="row"><button id="cn-add">Verbindung hinzufügen</button><span class="quiet small">«Lokal» (dieser Rechner) gibt es immer.</span></div>
    <h3>Agenten</h3>
    <div id="ag-list"></div><div class="row"><button id="ag-add">Agent hinzufügen</button></div>
    ${field('ag-days', 'Logs, Prompts und Patches der Läufe aufbewahren (Tage, 0 = nie löschen)', S.agent_log_days ?? 30, { type: 'number', err: 'agent_log_days' })}
    <h3>Leitplanken</h3>
    <div class="hint">Stehen in jedem Prompt, damit Änderungen klein bleiben und sich leicht reviewen lassen. Geht ein Ergebnis darüber, zeigt der Lauf einen Hinweis. Entscheiden tust du.</div>
    <div class="grid3">${field('ag-gf', 'Höchstens Dateien je Lauf', (S.agent_guards || {}).max_files ?? 8, { type: 'number', err: 'agent_guards.max_files' })}
      ${field('ag-gl', 'Etwa so viele geänderte Zeilen', (S.agent_guards || {}).max_lines ?? 300, { type: 'number', err: 'agent_guards.max_lines' })}</div>
    ${field('ag-gx', 'Im Team vereinbart (optional)', (S.agent_guards || {}).extra || '', { ph: 'z. B. Kein Lombok. Logs auf Englisch. Neue Endpunkte immer mit OpenAPI-Eintrag.', err: 'agent_guards.extra', help: 'Ein, zwei Sätze, die in jeden Prompt kommen. Höchstens 600 Zeichen.' })}
    <div class="ferr" data-err="connections"></div><div class="ferr" data-err="agents"></div>`)}

  ${sect('ide', 'IntelliJ und Review-Umgebung', 'Für «In IntelliJ öffnen» beim Testen: tinyops legt neben deinem Checkout einen Worktree genau auf dem Commit des MR oder auf dem Branch eines Agenten an (<code>../.tinyops-wt/</code>) und startet die IDE damit. Geholt wird mit <code>git fetch</code>, gepusht wird nie. Beim Abschliessen räumt tinyops saubere Worktrees wieder weg.', `
    ${field('ide-cmd', 'Befehl zum Öffnen', S.ide_command, { ph: 'idea {path}', err: 'ide_command', help: '<code>{path}</code> wird durch den Worktree ersetzt. macOS ohne Launcher: <code>open -na "IntelliJ IDEA.app" --args {path}</code>. Windows: Pfad zu <code>idea64.exe</code>.' })}
    <div id="ide-list"></div>
    <h3>Review-Umgebung je Projekt</h3>
    <div class="hint">Startet das Ergebnis eines Agenten zum Ausprobieren: nur auf deinen Klick, auf diesem Rechner, im Worktree des Laufs. Platzhalter: <code>{name}</code> (review-ticket-lauf), <code>{port}</code>, <code>{path}</code>, <code>{branch}</code>, <code>{sha}</code>, <code>{ticket}</code>. Dieselben Werte stehen als <code>REVIEW_NAME</code>, <code>REVIEW_PORT</code> und <code>COMPOSE_PROJECT_NAME</code> in der Umgebung.</div>
    <div id="renv-list"></div>
    <div class="ferr" data-err="projects"></div><div class="ferr" data-err="github.repos"></div>`)}

  ${sect('time', 'Zeiterfassung', 'Zeit läuft, solange ein Vorhaben als Fokus angeheftet ist und du das Panel benutzt. Daraus entstehen Entwürfe je Ticket. Gebucht wird erst nach «Bestätigen», in BCS über deine Middleware.', `
    <label class="check"><input type="checkbox" id="tm-on" ${S.time.enabled ? 'checked' : ''}><span><strong>Fokus-Zeit erfassen</strong></span></label>
    <div class="grid3">
      ${field('tm-round', 'Runden auf Minuten', S.time.round_minutes, { type: 'number', err: 'time.round_minutes' })}
      ${field('tm-min', 'Kein Entwurf unter Minuten', S.time.min_minutes, { type: 'number', err: 'time.min_minutes' })}
      ${field('tm-idle', 'Leerlauf ab Minuten', S.time.idle_minutes, { type: 'number', err: 'time.idle_minutes', help: 'So lange ohne Aktivität im Panel: Die Zeit endet beim letzten Lebenszeichen, die Pause wird als Lücke vorgeschlagen.' })}
    </div>
    <h3 style="margin:18px 0 6px">BCS-Middleware</h3>
    <label class="check"><input type="checkbox" id="bc-on" ${(S.time.bcs || {}).enabled ? 'checked' : ''}><span><strong>In BCS buchen</strong> <span class="quiet small">über deine Middleware (Workflow-API), auf diesem Rechner oder im eigenen Netz.</span></span></label>
    <div class="grid2">
      ${field('bc-url', 'Adresse der Middleware', (S.time.bcs || {}).url || 'http://127.0.0.1:3210', { ph: 'http://127.0.0.1:3210', err: 'time.bcs.url', help: 'Dieser Rechner (127.0.0.1) oder, mit dem Haken unten, eine private Adresse im eigenen Netz.' })}
      ${field('bc-secret', 'BCS_API_TOKEN (nur falls gesetzt)', '', { type: 'password', err: 'bcs_token', ph: S.secrets.bcs_token && S.secrets.bcs_token.set ? '•••••••• gespeichert' : '', help: 'Das Token der Middleware, nicht dein BCS-Passwort.' })}
    </div>
    <label class="check"><input type="checkbox" id="bc-lan" ${(S.time.bcs || {}).allow_lan ? 'checked' : ''}><span>Middleware im eigenen Netz <span class="quiet small">(z. B. auf dem Windows-Host deiner VM; nur private Adressen. Das Token geht unverschlüsselt durchs Netz, wenn die Adresse mit http:// beginnt.)</span></span></label>
    <label class="check"><input type="checkbox" id="bc-appr" ${(S.time.bcs || {}).apprentices !== false ? 'checked' : ''}><span>Lernende in der Zeit-Ansicht zeigen <span class="quiet small">(nur lesen, was BCS dir zeigt)</span></span></label>`)}

  ${sect('focusareas', 'Fokus: Bereiche, Wochenziel, Spielstand', 'Wie viel deiner Woche wohin gehen soll. Ein Bereich mit Ziel (z. B. Berufsbildung 30 %) zeigt im Fokus, ob du im Plan bist, und lässt sich als Block mit Zeitbox starten. Zeit zählt zu einem Bereich, wenn du sie dort startest, wenn das Vorhaben in einer seiner Kategorien liegt oder (Helpdesk) wenn es ein Helpdesk-Ticket ist. Alles andere ist Entwicklung.', `
    <label class="check"><input type="checkbox" id="ft-score" ${S.features.score !== false ? 'checked' : ''}><span><strong>Spielstand im Fokus zeigen</strong> <span class="quiet small">(Karte oben rechts: Schritte heute, Tagesziel, Serie und XP für erledigte Schritte)</span></span></label>
    <div class="grid3">
      ${field('fo-hours', 'Arbeitsstunden pro Woche', S.focus.week_hours, { type: 'number', err: 'focus.week_hours' })}
      ${field('fo-start', 'Arbeitstag ab', S.focus.day_start, { ph: '08:00', err: 'focus.day_start' })}
      ${field('fo-end', 'Arbeitstag bis', S.focus.day_end, { ph: '17:00', err: 'focus.day_end', help: 'Für «Soll bis jetzt»: Das Wochenziel wird anteilig auf die vergangene Arbeitszeit gerechnet.' })}
    </div>
    <div id="fa-list"></div>
    <div class="row"><button id="fa-add">Bereich hinzufügen</button><span class="quiet small" id="fa-sum"></span></div>
    <div class="ferr" data-err="focus.areas"></div>`)}

  ${sect('workspaces', 'Workspaces', 'Ordner, deren Unterordner deine Projekte sind. tinyops sucht darin Git-Repos (GitLab, GitHub, andere) und Projekte ohne Git und zeigt, was noch nicht gepusht ist. Gelesen wird nur lokal; gepusht wird nie.', `
    <label class="check"><input type="checkbox" id="ws-on" ${S.workspaces.enabled ? 'checked' : ''}><span><strong>Workspaces durchsuchen</strong></span></label>
    ${field('ws-roots', 'Ordner (einer pro Zeile)', (S.workspaces.roots || []).join('\n'), { area: true, rows: 3, ph: '~/work', err: 'workspaces.roots', help: 'Die Arbeitsordner lokaler Agenten und die Ordner über deinen lokalen Klonen kommen von selbst dazu.' })}
    <div class="small quiet" style="margin:-4px 0 12px">Durchsucht wird: ${(S.workspaces.found || []).map(r => `<code>${esc(r.path)}</code> (${esc(r.why)})`).join(', ') || 'noch nichts'}</div>
    <div class="grid3">
      ${field('ws-depth', 'Suchtiefe', S.workspaces.depth, { type: 'number', err: 'workspaces.depth', help: 'Ebenen unter dem Ordner, z. B. 3 für work/kunde/projekt.' })}
      ${field('ws-stale', 'Melden ab (Tage)', S.workspaces.stale_days, { type: 'number', err: 'workspaces.stale_days', help: 'Ab diesem Alter erscheint Ungepushtes rot und als Zahl am Tab.' })}
      ${field('ws-scan', 'Neu einlesen alle (Minuten)', S.workspaces.scan_minutes, { type: 'number', err: 'workspaces.scan_minutes' })}
    </div>`)}

  ${sect('m365', 'Microsoft 365', 'Mail, Kalender und Teams-Chats aus deinem Konto: was auf deine Antwort wartet, die Termine von heute im Fokus, vergangene Termine als Zeit übernehmen. Gelesen wird als du selbst; geschrieben wird nur ein Fokus-Termin in deinen Kalender, wenn du es einschaltest und beim Start anhakst.', `
    <label class="check"><input type="checkbox" id="m3-on" ${S.m365.enabled ? 'checked' : ''}><span><strong>Microsoft 365 einbinden</strong></span></label>
    <div class="grid2">
      ${field('m3-tenant', 'Tenant (Verzeichnis-ID)', S.m365.tenant, { ph: '00000000-0000-0000-0000-000000000000 oder firma.onmicrosoft.com', err: 'm365.tenant' })}
      ${field('m3-client', 'Client-ID (Anwendungs-ID)', S.m365.client_id, { ph: '00000000-0000-0000-0000-000000000000', err: 'm365.client_id', help: 'Aus der App-Registrierung in Entra ID. Kein Geheimnis nötig.' })}
    </div>
    <div class="row" style="flex-wrap:wrap;gap:6px 18px;margin:6px 0 10px">
      <label class="check"><input type="checkbox" id="m3-mail" ${S.m365.mail ? 'checked' : ''}><span>Mail</span></label>
      <label class="check"><input type="checkbox" id="m3-cal" ${S.m365.calendar ? 'checked' : ''}><span>Kalender</span></label>
      <label class="check"><input type="checkbox" id="m3-teams" ${S.m365.teams ? 'checked' : ''}><span>Teams-Chats</span></label>
      <label class="check"><input type="checkbox" id="m3-write" ${S.m365.calendar_write ? 'checked' : ''}><span>Fokuszeit im Kalender eintragen dürfen</span></label>
    </div>
    <div class="grid3">
      ${field('m3-days', 'Mails der letzten (Tage)', S.m365.reply_days, { type: 'number', err: 'm365.reply_days', help: 'So weit zurück sucht «Wartet auf dich».' })}
      ${field('m3-every', 'Neu lesen alle (Minuten)', S.m365.refresh_minutes, { type: 'number', err: 'm365.refresh_minutes' })}
    </div>
    <div class="small quiet">Rechte, die tinyops bei der Anmeldung anfragt: <code>${esc(S.m365.scopes.join(' '))}</code>. Rückleitung: <code>${esc(S.m365.redirect)}</code></div>
    <div id="m3-status" style="margin-top:10px"></div>`)}

  ${sect('helpdesk', 'Helpdesk-Jira', 'Eine zweite Jira-Instanz, nur lesend: dir zugewiesene Tickets erscheinen im Fokus, eine Queue meldet Neues, und angeheftet läuft die Zeit auf das Helpdesk-Ticket. Kommentieren und Status ändern bleibt im Helpdesk.', `
    <label class="check"><input type="checkbox" id="hd-on" ${S.helpdesk.enabled ? 'checked' : ''}><span><strong>Helpdesk einbinden</strong></span></label>
    <div class="grid2">
      ${field('hd-url', 'Adresse', S.helpdesk.url, { ph: 'https://helpdesk.firma.example', err: 'helpdesk.url' })}
      ${field('hd-name', 'Anzeigename', S.helpdesk.name, { ph: 'Helpdesk', err: 'helpdesk.name' })}
      <div class="field"><label for="hd-auth">Anmeldeart</label>
        <select class="full" id="hd-auth"><option value="basic" ${S.helpdesk.auth !== 'bearer' ? 'selected' : ''}>basic: Benutzername + Passwort (Jira 8.5)</option>
          <option value="bearer" ${S.helpdesk.auth === 'bearer' ? 'selected' : ''}>bearer: Personal Access Token (ab Jira 8.14)</option></select>
        <div class="ferr" data-err="helpdesk.auth"></div></div>
      ${field('hd-user', 'Benutzername', S.helpdesk.username, { err: 'helpdesk.username' })}
    </div>
    <div id="hd-secbox"></div>
    <h3 style="margin:14px 0 2px">Was tinyops aus dem Helpdesk zeigt</h3>
    <div class="quiet small" style="margin-bottom:10px">Drei Listen, jede mit einer Jira-Abfrage (JQL). Die Vorschläge setzen eine fertige Abfrage ein; du musst kein JQL schreiben. Leer heisst: Liste aus.</div>
    ${field('hd-jql', '1. Meine Tickets (im Fokus unter «Du bist dran»)', S.helpdesk.assigned_jql, { area: true, rows: 2, err: 'helpdesk.assigned_jql' })}
    <div class="jqlp" data-jqlfor="hd-jql"><button data-jql="assignee = currentUser() AND resolution = Unresolved ORDER BY priority DESC, updated ASC">Mir zugewiesen, offen</button><button data-jql="assignee = currentUser() AND resolution = Unresolved AND status != &quot;Waiting for customer&quot; ORDER BY priority DESC, updated ASC">ohne «wartet auf Kunde»</button></div>
    ${field('hd-qjql', '2. Queue (meldet neue Tickets)', S.helpdesk.queue_jql, { area: true, rows: 2, err: 'helpdesk.queue_jql', help: 'Neue Treffer sind fett, bis du «Alle gesehen» drückst. Für «Unzugewiesen im Projekt» das Projektkürzel anpassen.' })}
    <div class="jqlp" data-jqlfor="hd-qjql"><button data-jql="project = SD AND assignee is EMPTY AND resolution = Unresolved ORDER BY created DESC">Unzugewiesen im Projekt SD</button><button data-jql="assignee is EMPTY AND resolution = Unresolved AND created >= -7d ORDER BY created DESC">Unzugewiesen, letzte 7 Tage</button><button data-jql="">Aus</button></div>
    ${field('hd-wjql', '3. Ich beobachte (Watcher)', S.helpdesk.watch_jql, { area: true, rows: 2, err: 'helpdesk.watch_jql', help: 'Tickets, bei denen du Beobachter bist, die aber jemand anderes bearbeitet. Fett, wenn sich seit deinem letzten Blick etwas geändert hat.' })}
    <div class="jqlp" data-jqlfor="hd-wjql"><button data-jql="watcher = currentUser() AND (assignee is EMPTY OR assignee != currentUser()) AND resolution = Unresolved ORDER BY updated DESC">Beobachtet, nicht meine</button><button data-jql="watcher = currentUser() AND resolution = Unresolved AND updated >= -14d ORDER BY updated DESC">Beobachtet, geändert in 14 Tagen</button><button data-jql="">Aus</button></div>
    <div class="grid2">
      ${field('hd-sla', 'SLA in Stunden', S.helpdesk.sla_hours, { type: 'number', err: 'helpdesk.sla_hours', help: 'Ab diesem Alter steigt ein Ticket nach oben und ist rot markiert.' })}
      <div class="field"><label for="hd-area">Zeit zählt zum Bereich</label><select class="full" id="hd-area">${S.focus.areas.map(a => `<option value="${esc(a.id)}" ${a.id === S.helpdesk.area ? 'selected' : ''}>${esc(a.name)}</option>`).join('')}</select></div>
    </div>
    <div class="row"><button class="primary" id="hd-test">Verbindung testen</button>${S.secrets.helpdesk_password.set || S.secrets.helpdesk_token.set ? '<button id="hd-del">Gespeicherte Zugangsdaten löschen</button>' : ''}<span class="quiet small">Liest nur: Serverinfo, Anmeldung, beide JQL.</span></div>
    <div id="hd-result"></div>`)}

  ${sect('usage', 'KI-Kontingent', 'Zeigt, wie viel im 5-Stunden- und Wochenfenster deines Claude- und Codex-Abos noch frei ist (gelesen über die Schnittstelle, die auch die CLIs nutzen: inoffiziell, kann sich ändern) und das Monatsbudget von Mistral (per Lesezeichen aus deinem Browser).', `
    <label class="check"><input type="checkbox" id="us-claude" ${S.usage.claude ? 'checked' : ''}><span><strong>Claude lesen</strong> <span class="quiet small">(Token aus der Anmeldedatei von Claude Code)</span></span></label>
    ${field('us-claude-file', 'Pfad der Claude-Anmeldedatei', S.usage.claude_file, { ph: '~/.claude/.credentials.json', err: 'usage.claude_file' })}
    <label class="check"><input type="checkbox" id="us-mistral" ${S.usage.mistral ? 'checked' : ''}><span><strong>Mistral anzeigen</strong> <span class="quiet small">(Stand kommt per Lesezeichen aus deinem Browser)</span></span></label>
    <div class="hint" id="us-bm"></div>
    <label class="check"><input type="checkbox" id="us-codex" ${S.usage.codex ? 'checked' : ''}><span><strong>Codex lesen</strong> <span class="quiet small">(Token aus der Anmeldedatei des Codex-CLI, ChatGPT-Anmeldung nötig)</span></span></label>
    ${field('us-codex-file', 'Pfad der Codex-Anmeldedatei', S.usage.codex_file, { ph: '~/.codex/auth.json', err: 'usage.codex_file' })}
    ${field('us-cache', 'Zwischenspeicher in Sekunden', S.usage.cache_seconds, { type: 'number', err: 'usage.cache_seconds' })}
    <div class="hint">Das Token wird nur gelesen, nie erneuert, gespeichert oder geloggt, und nur an api.anthropic.com bzw. chatgpt.com geschickt. Läuft tinyops im Container, muss die Datei dort eingehängt sein; ist das Token abgelaufen, einmal <code>claude</code> bzw. <code>codex</code> starten. Erst speichern, dann testen.</div>
    <div id="us-live"></div>
    <div class="row"><button class="primary" id="us-test">Jetzt abfragen</button></div>
    <div id="us-result"></div>`)}

  ${sect('llm', 'KI-Entwurf (lokal)', 'Ein Sprachmodell auf deinem Rechner oder im Büro-Netz schreibt den ersten Entwurf eines Tickets. Ohne Modell nimmt der Dialog eine Vorlage.', `
    <label class="check"><input type="checkbox" id="lm-on" ${S.llm.enabled ? 'checked' : ''}><span><strong>KI-Entwurf einschalten</strong></span></label>
    <div class="grid2">
      <div class="field"><label for="lm-prov">Dialekt des Servers</label>
        <select class="full" id="lm-prov">${S.llm.providers.map(p => `<option value="${esc(p.id)}" ${p.id === S.llm.provider ? 'selected' : ''}>${esc(p.label)}</option>`).join('')}</select>
        <div class="help">Ollama: <code>ollama serve</code>. llama.cpp: <code>llama-server -m modell.gguf</code> (OpenAI-kompatibel). Weitere Anbieter lassen sich in <code>llm.py</code> ergänzen.</div>
        <div class="ferr" data-err="llm.provider"></div></div>
      ${field('lm-url', 'Adresse', S.llm.url, { err: 'llm.url', ph: 'http://127.0.0.1:11434', help: 'Nur Adressen im eigenen Netz werden angenommen (localhost, private Adressen, Namen im Büro-Netz).' })}
    </div>
    <div class="grid2">
      ${field('lm-model', 'Modell', S.llm.model, { ph: 'llama3.2:3b', err: 'llm.model', help: 'Bei Ollama der Name aus «ollama list». Bei llama.cpp meist leer lassen; bei einem Router (mehrere Modelle) den genauen Namen eintragen.' })}
      ${field('lm-timeout', 'Timeout in Sekunden', S.llm.timeout || 120, { type: 'number', err: 'llm.timeout', help: 'So lange wartet das Panel auf ein Lebenszeichen. Grosse Modelle brauchen beim ersten Aufruf oft mehrere Minuten, weil sie erst geladen werden.' })}
    </div>
    <label class="check"><input type="checkbox" id="lm-remote" ${S.llm.allow_remote ? 'checked' : ''}>
      <span>Adresse ausserhalb des eigenen Netzes erlauben <span class="quiet small">(nicht empfohlen: Titel, Branch-Namen und Commit-Titel verlassen dann das Netz, bei Kundenprojekten ein DLP-Verstoss)</span></span></label>
    <div id="lm-keybox"></div>
    <div class="row"><button class="primary" id="lm-test">Verbindung testen</button></div>
    <div id="lm-result"></div>`)}

  ${sect('app', 'App und Handy', 'tinyops als eigenes Fenster auf dem Rechner und als App auf dem Handy. Das Panel bleibt dabei nur für gekoppelte Geräte offen.', `
    <div class="row" style="align-items:center;gap:12px;margin-bottom:14px"><button id="app-install" ${PWA.prompt ? '' : 'disabled'}>${ic('plus')} Als App installieren</button>
      <span class="quiet small" id="app-inst-msg">${PWA.installed ? 'Läuft schon als App.' : PWA.prompt ? 'Öffnet tinyops in einem eigenen Fenster, mit Symbol im Dock oder Startmenü.' : 'Chrome oder Edge: Menü → «App installieren». Safari: Teilen → «Zum Home-Bildschirm».'}</span></div>
    ${field('app-phone', 'Adresse fürs Handy', S.app.phone_url, { ph: 'https://mein-rechner.tailnet.ts.net', err: 'app.phone_url', help: 'Unter dieser Adresse erreicht das Handy tinyops, z. B. über Tailscale (<code>tailscale serve --bg ' + esc(S.server.port) + '</code>) oder dein VPN. Mit https lässt sich tinyops auf dem Handy als App installieren. tinyops nimmt den Namen in die erlaubten Hosts auf.' })}
    ${field('app-origins', 'Adressen der eigenen App (optional)', (S.app.origins || []).join(', '), { ph: 'https://app.mein-name.ch', err: 'app.origins', help: 'Nur für eine eigene App (z. B. die React-PWA), die tinyops von einer anderen Adresse aus aufruft. Sie koppelt sich mit demselben Code und meldet sich mit dem Geräte-Token an. Leer lassen, wenn du die tinyops-Seite selbst als App nutzt.' })}
    <h3 style="margin:16px 0 6px">Handy koppeln</h3>
    <div class="small quiet">Nur gekoppelte Geräte sehen tinyops von aussen. Ein Gerät darf keine Einstellungen ändern und keine weiteren koppeln; entfernen geht jederzeit hier.</div>
    <div class="row" style="margin-top:8px"><button id="app-code" ${S.demo ? 'disabled title="Im Demo-Modus aus"' : ''}>Code erzeugen</button></div>
    <div id="app-codebox"></div>
    <div id="app-devs" style="margin-top:12px"></div>`)}

  ${sect('more', 'Weiteres', 'Vorerst ausgeblendet, damit die Oberfläche beim Wesentlichen bleibt.', `
    <label class="check"><input type="checkbox" id="ft-ideas" ${S.features.ideas ? 'checked' : ''}><span>Ideenbox</span></label>
    <label class="check"><input type="checkbox" id="ft-ai" ${S.features.ai ? 'checked' : ''}><span>KI-Konten <span class="quiet small">(nur von Hand gepflegt, da die Anbieter keine Abfrage bieten; vorerst aus)</span></span></label>
    <label class="check"><input type="checkbox" id="ux-on" ${S.ux.enabled ? 'checked' : ''}><span>UI-Nutzung lokal erfassen <span class="quiet small">(Klicks, Mausweg, Tasten ausserhalb von Feldern, nie Eingaben oder Titel; Bericht unter «Prüfen», zum Kopieren für die Verbesserung der Oberfläche)</span></span></label>
    ${field('ux-days', 'UI-Nutzung aufbewahren (Tage)', S.ux.days, { type: 'number', err: 'ux.days' })}`)}

  ${sect('where', 'Ablage', 'Wo Zugangsdaten, Konfiguration und Log liegen.', `
    <div class="small">Zugangsdaten: ${esc(S.storage.text)}</div>
    ${S.storage.keyring ? '' : '<div class="hint">Kein Schlüsselbund gefunden. Besser: <code>pip install keyring</code> in der Python-Umgebung von tinyops (siehe README). Bis dahin liegen Tokens in einer Datei, die nur dein Benutzer lesen kann.</div>'}
    <div class="small quiet" style="margin-top:8px">Config: ${esc(S.server.config)} (enthält nie Zugangsdaten)</div>
    <div class="small quiet">Log: ${esc(S.server.log)} · Adresse: ${esc(S.server.bind)}:${esc(S.server.port)} (nur per Neustart änderbar)</div>`)}
   </div>
  </div>
  <div class="savebar"><button class="primary" id="st-save" ${S.demo ? 'disabled' : ''}>Speichern</button>
    <span class="quiet small" id="st-msg">Änderungen gelten sofort nach dem Speichern, ohne Neustart.</span></div>`;
  CN = (S.connections || []).map(c => ({ ...c })); AGC = (S.agents || []).map(a => ({ ...a })); renderAgentCfg();
  GH = ((S.github || {}).repos || []).map(r => ({ ...r })); renderGhRepos();
  $('gh-test').onclick = testGithub; $('gh-search').onclick = searchGithub; $('gh-q').onkeydown = ev => { if (ev.key === 'Enter') searchGithub(); };
  if ($('gh-del')) $('gh-del').onclick = () => delSecrets(['github_token'], 'GitHub-Token');
  renderJiraSecret(); renderProjects(); renderBookmarklet(); renderUsageBox(); loadUsage(false); renderM3Status();
  renderLlmKey(); wireApp();
  FA = S.focus.areas.map(a => ({ ...a, pools: (a.pools || []).join(', '), activities: (a.activities || []).join(', ') })); renderFocusAreas();
  $('fa-add').onclick = () => { FA.push({ id: '', name: '', target_pct: 0, ticket: '', pools: '', activities: '', blocks_text: '' }); renderFocusAreas(); };
  renderHdSecret(); $('hd-auth').onchange = renderHdSecret;
  $('hd-test').onclick = () => busy($('hd-test'), 'Teste …', async () => {
    try { $('hd-result').innerHTML = stepsHtml(await api('POST', '/api/settings/test/helpdesk', hdForm())); }
    catch (e) { $('hd-result').innerHTML = `<div class="banner bad">${esc(e.message)}</div>`; }
  });
  if ($('hd-del')) $('hd-del').onclick = () => delSecrets(['helpdesk_password', 'helpdesk_token'], 'Helpdesk-Zugangsdaten');
  $('lm-test').onclick = testLlm; $('lm-prov').onchange = () => {
    const p = S.llm.providers.find(x => x.id === $('lm-prov').value), cur = val('lm-url');
    if (p && (!cur || S.llm.providers.some(x => x.url === cur))) $('lm-url').value = p.url;
    renderLlmKey();
  };
  $('us-test').onclick = testUsage;
  $('sq-test').onclick = testSonar; if ($('sq-del')) $('sq-del').onclick = () => delSecrets(['sonar_token'], 'Sonar-Token');
  $('gl-test').onclick = testGitlab; $('ji-test').onclick = testJira; $('st-save').onclick = saveSettings;
  $('pj-search').onclick = searchProjects; $('pj-q').onkeydown = ev => { if (ev.key === 'Enter') searchProjects(); };
  $('id-suggest').onclick = suggestIdentity; $('ji-auth').onchange = renderJiraSecret;
  if ($('gl-del')) $('gl-del').onclick = () => delSecrets(['gitlab_token'], 'GitLab-Token');
  if ($('ji-del')) $('ji-del').onclick = () => delSecrets(['jira_token', 'jira_password'], 'Jira-Zugangsdaten');
  if (window.IntersectionObserver) {   // Navigation zeigt beim Scrollen, wo man ist
    const spy = new IntersectionObserver(es => es.forEach(en => { if (en.isIntersecting) box.querySelectorAll('[data-goto]').forEach(x => x.classList.toggle('on', 's-' + x.dataset.goto === en.target.id)); }),
      { rootMargin: '-80px 0px -70% 0px' });
    box.querySelectorAll('.sset').forEach(sec => spy.observe(sec));
  }
  box.querySelectorAll('[data-tokgo]').forEach(b => b.onclick = ev => { ev.preventDefault(); const n = box.querySelector(`.setnav [data-goto="${b.dataset.tokgo}"]`); if (n) n.click(); });
  { const tb = $('tokBox'); if (tb) tb.addEventListener('toggle', () => LS.set('tokOpen', tb.open)); }
  box.querySelectorAll('[data-goto]').forEach(btn => btn.onclick = () => {
    box.querySelectorAll('[data-goto]').forEach(x => x.classList.toggle('on', x === btn));
    $('s-' + btn.dataset.goto).scrollIntoView({ behavior: matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth', block: 'start' });
  });
}
// -- Microsoft 365 (0.28): Anmeldung und Stand
let M3_DEV = null;
async function renderM3Status() {
  const box = $('m3-status'); if (!box) return;
  let st = null;
  try { st = await api('GET', '/api/m365'); } catch (e) { box.innerHTML = `<div class="banner bad">${esc(e.message)}</div>`; return; }
  if (!st || !st.enabled) { box.innerHTML = '<div class="small quiet">Aus. Einschalten, Tenant und Client-ID eintragen, speichern, dann anmelden.</div>'; return; }
  if (!st.ready && !st.demo) { box.innerHTML = '<div class="small quiet">Tenant und Client-ID eintragen und speichern, dann erscheint «Anmelden».</div>'; return; }
  const err = Object.entries(st.errors || {}).map(([k, v]) => `<div class="small" style="color:var(--bad)">${esc(k)}: ${esc(v)}</div>`).join('');
  box.innerHTML = st.logged_in
    ? `<div class="row" style="gap:10px;flex-wrap:wrap"><span class="okk">Angemeldet${st.me ? ' als ' + esc(st.me) : ''}</span>${st.ts ? `<span class="small quiet">Stand ${hhmm(st.ts)}</span>` : ''}
        <button id="m3-refresh">Jetzt lesen</button><button id="m3-out" class="quiet-btn">Abmelden</button></div>${st.error ? `<div class="banner warn">${esc(st.error)}</div>` : ''}${err}`
    : `${st.login_error ? `<div class="banner warn">${esc(st.login_error)}</div>` : ''}<div class="row" style="gap:10px;flex-wrap:wrap"><button class="primary" id="m3-in">Anmelden</button>
        <button id="m3-dev" title="Falls die Rückleitung auf localhost bei euch nicht geht: Code auf microsoft.com/devicelogin eingeben">Mit Code anmelden</button>
        <span class="small quiet">Öffnet die Microsoft-Anmeldung mit deiner 2FA. Danach kommst du hierher zurück.</span></div><div id="m3-code"></div>`;
  if ($('m3-in')) $('m3-in').onclick = async () => { try { location.href = (await post('/api/m365/login', {})).url; } catch (e) { toast(e.message); } };
  if ($('m3-out')) $('m3-out').onclick = async () => { try { await post('/api/m365/logout', {}); toast('Abgemeldet'); renderM3Status(); load(); } catch (e) { toast(e.message); } };
  if ($('m3-refresh')) $('m3-refresh').onclick = async () => { try { await post('/api/m365/refresh', {}); renderM3Status(); load(); } catch (e) { toast(e.message); } };
  if ($('m3-dev')) $('m3-dev').onclick = async () => {
    try {
      const d = await post('/api/m365/device', {});
      $('m3-code').innerHTML = `<div class="banner warn" style="margin-top:8px">Öffne <a href="${esc(d.uri)}" target="_blank" rel="noopener">${esc(d.uri)}</a> und gib diesen Code ein: <b style="font-size:20px;letter-spacing:.08em">${esc(d.user_code)}</b> <button class="quiet-btn" data-copy="${esc(d.user_code)}">${ic('copy')} kopieren</button><div class="small">tinyops wartet auf die Anmeldung …</div></div>`;
      clearInterval(M3_DEV);
      M3_DEV = setInterval(async () => {
        let x; try { x = await post('/api/m365/device_state', {}); } catch (e) { return; }
        if (x.state === 'fertig') { clearInterval(M3_DEV); toast('Bei Microsoft 365 angemeldet'); renderM3Status(); load(); }
        else if (x.state === 'fehler') { clearInterval(M3_DEV); $('m3-code').innerHTML = `<div class="banner bad">${esc(x.error)}</div>`; }
      }, 3000);
    } catch (e) { toast(e.message); }
  };
}
function renderBookmarklet() {
  const box = $('us-bm'); if (!box) return;
  const href = 'javascript:' + encodeURIComponent(S.usage.bookmarklet_src.replace('__ORIGIN__', location.origin));
  box.innerHTML = `<b>Mistral per Lesezeichen:</b> Diesen Link in die Lesezeichenleiste ziehen: <a class="pchip" href="${esc(href)}" onclick="return false" draggable="true">tinyops: Mistral lesen</a><br>
    Dann <a href="${MISTRAL_URL}" target="_blank" rel="noopener">admin.mistral.ai/subscription</a> öffnen (eingeloggt) und dort das Lesezeichen anklicken. Das Lesezeichen liest dort die Budgetzahlen und öffnet tinyops mit nur diesen Zahlen (Prozent, Budget, Reset). Cookies und Zugangsdaten gehen nie an tinyops. Mistral ändert die Seite gelegentlich: dann meldet das Lesezeichen «Keine Budgetdaten gefunden». Im Container muss das Panel vom Browser aus unter derselben Adresse erreichbar sein, die du gerade benutzt.`;
}
function renderJiraSecret() {
  const basic = $('ji-auth').value === 'basic';
  $('ji-userbox').hidden = !basic;
  const name = basic ? 'jira_password' : 'jira_token';
  const old = $('ji-secret') ? $('ji-secret').value : '';
  $('ji-secbox').innerHTML = field('ji-secret', basic ? 'Passwort' : 'Personal Access Token', old, {
    type: 'password', err: name, ph: S.secrets[name].set ? '•••••••• gespeichert' : '',
    help: secretHelp(name, basic ? 'Passwort' : 'Token') + (basic ? ' Achtung: Mehrere falsche Passwörter in Folge können das Konto in Jira sperren; tinyops pausiert deshalb nach einem Fehlversuch 30 Sekunden.'
      : ` Anlegen in Jira: Profil → Personal Access Tokens. Ein Jira-Token hat die Rechte deines Kontos.`) });
}
// Fokusbereiche und Helpdesk (0.23)
let FA = [];
function renderFocusAreas() {
  const fixed = id => ['dev'].includes(id);
  $('fa-list').innerHTML = FA.map((a, i) => `<div class="agbox ${arCls(a.id)}" data-fa="${i}">
    <div class="grid3">
      ${field('fa-n' + i, 'Name', a.name, { err: 'focus.areas' })}
      ${field('fa-p' + i, 'Wochenziel in %', a.target_pct, { type: 'number', err: 'focus.areas.' + i + '.target_pct', help: fixed(a.id) ? 'Entwicklung ist der Rest, meist 0.' : '' })}
      ${field('fa-t' + i, 'Buchen auf', a.ticket, { ph: 'Ticket oder Position', help: 'Für Zeit ohne Vorhaben (Block, Sitzung im Bereich). Leer: der Name des Bereichs.' })}
    </div>
    ${fixed(a.id) ? '' : `<div class="grid3">
      ${field('fa-a' + i, 'Tätigkeiten', a.activities, { err: 'focus.areas.' + i + '.activities', help: 'Komma getrennt. Wählst du in der Sitzung; sie landen im Buchungstext.' })}
      ${field('fa-c' + i, 'Kategorien im Board', a.pools, { err: 'focus.areas.' + i + '.pools', help: 'Vorhaben in diesen Kategorien zählen zu diesem Bereich.' })}
      ${field('fa-b' + i, 'Feste Wochenblöcke', a.blocks_text || '', { ph: 'Di 13:30-17:00, Do 08:00-10:00', err: 'focus.areas.' + i + '.blocks', help: 'Format: Tag von-bis, mehrere mit Komma. Tage: Mo Di Mi Do Fr Sa So. Beispiel: <code>Di 13:30-17:00, Do 08:00-10:00</code>.' })}
    </div>
    <div class="row"><button class="quiet-btn" data-fadel="${i}">Bereich entfernen</button></div>`}
  </div>`).join('');
  const sum = FA.reduce((n, a) => n + (+a.target_pct || 0), 0);
  $('fa-sum').textContent = `Ziele zusammen: ${sum} %` + (sum > 100 ? ' (zu viel)' : '');
}
function readFocusAreas() {
  FA.forEach((a, i) => {
    const g = k => $('fa-' + k + i) ? $('fa-' + k + i).value : null;
    a.name = g('n'); a.target_pct = g('p'); a.ticket = g('t');
    if (g('a') !== null) { a.activities = g('a'); a.pools = g('c'); a.blocks_text = g('b'); }
  });
  return FA;
}
document.addEventListener('click', ev => { const d = ev.target.closest && ev.target.closest('[data-fadel]'); if (d) { readFocusAreas(); FA.splice(+d.dataset.fadel, 1); renderFocusAreas(); } });
document.addEventListener('input', ev => { if (ev.target.id && /^fa-p\d+$/.test(ev.target.id)) { readFocusAreas(); $('fa-sum').textContent = `Ziele zusammen: ${FA.reduce((n, a) => n + (+a.target_pct || 0), 0)} %`; } });
document.addEventListener('click', ev => {
  const b = ev.target.closest && ev.target.closest('.jqlp [data-jql]');
  if (b) { ev.preventDefault(); const f = $(b.parentElement.dataset.jqlfor); f.value = b.dataset.jql; f.dispatchEvent(new Event('input', { bubbles: true })); f.focus(); }
});
function renderHdSecret() {
  const basic = $('hd-auth').value !== 'bearer', name = basic ? 'helpdesk_password' : 'helpdesk_token';
  const old = $('hd-secret') ? $('hd-secret').value : '';
  $('hd-user').closest('.field').hidden = !basic;
  $('hd-secbox').innerHTML = field('hd-secret', basic ? 'Passwort' : 'Personal Access Token', old, { type: 'password', err: name, ph: S.secrets[name].set ? '•••••••• gespeichert' : '',
    help: secretHelp(name, basic ? 'Passwort' : 'Token') + (basic ? ' Jira 8.5 kennt keine Personal Access Tokens. Nach einem Fehlversuch pausiert der Test 30 Sekunden, damit das Konto nicht gesperrt wird.' : '') });
}
const hdForm = () => ({ url: val('hd-url'), auth: val('hd-auth'), username: val('hd-user'), secret: $('hd-secret').value, ca_bundle: val('gl-ca'), assigned_jql: val('hd-jql'), queue_jql: val('hd-qjql'), watch_jql: val('hd-wjql') });
function renderLlmKey() {
  const show = $('lm-prov').value === 'openai';
  const old = $('lm-secret') ? $('lm-secret').value : '';
  $('lm-keybox').innerHTML = show ? field('lm-secret', 'Zugangsschlüssel (optional)', old, { type: 'password', err: 'llm_key', ph: S.secrets.llm_key.set ? '•••••••• gespeichert' : '',
    help: secretHelp('llm_key', 'Schlüssel') + ' Lokale Server brauchen meist keinen.' }) : '';
}
function llmForm() { return { provider: val('lm-prov'), url: val('lm-url'), model: val('lm-model'), allow_remote: $('lm-remote').checked, timeout: val('lm-timeout'), secret: $('lm-secret') ? $('lm-secret').value : '' }; }
async function testLlm() {
  const out = $('lm-result');
  await busy($('lm-test'), 'Teste …', async () => {
    try {
      const r = await api('POST', '/api/settings/test/llm', llmForm());
      const models = (r.models || []).length ? `<div style="margin-top:8px" class="quiet">Gefundene Modelle (Klick = übernehmen):</div><div>${r.models.map(m => `<button class="pchip" data-setmodel="${esc(m)}">${esc(m)}</button>`).join('')}</div>` : '';
      const warn = r.steps.some(x => x.status === 'warn');
      out.innerHTML = stepsHtml(r).replace('Verbindung in Ordnung.', warn ? 'Server und Modell sind erreichbar, aber der Testentwurf hat nicht geklappt (siehe oben und das Log).' : 'Das Modell antwortet.').replace('class="verdict ok"', warn ? 'class="verdict" style="background:var(--warn-bg);color:var(--warn)"' : 'class="verdict ok"') + models;
    } catch (e) { out.innerHTML = `<div class="banner bad">${esc(e.message)}</div>`; }
  });
}
$('viewSettings').addEventListener('click', ev => { const b = ev.target.closest('[data-setmodel]'); if (b) $('lm-model').value = b.dataset.setmodel; });
function clearErrors() { document.querySelectorAll('.ferr').forEach(e => e.textContent = ''); }
function showErrors(errs) {
  clearErrors();
  Object.entries(errs || {}).forEach(([k, m]) => document.querySelectorAll(`.ferr[data-err="${k}"]`).forEach(e => e.textContent = m));
}
async function busy(btn, label, fn) {
  const old = btn.textContent; btn.disabled = true; btn.textContent = label;
  try { return await fn(); } finally { btn.disabled = false; btn.textContent = old; }
}
function glForm() { return { url: val('gl-url'), ca_bundle: val('gl-ca'), token: $('gl-token').value, projects: P.map(p => p.id) }; }
function jiForm() {
  return { url: val('ji-url'), auth: val('ji-auth'), username: val('ji-user'), secret: $('ji-secret').value, ca_bundle: val('gl-ca'),
    project_keys: split(val('ji-keys')), issue_types: split(val('ji-types')), jql: val('ji-jql'), story_limit: val('ji-limit'),
    only_active_sprints: $('ji-sprint').checked };
}
async function testUsage() {
  const out = $('us-result');
  await busy($('us-test'), 'Frage …', async () => {
    try {
      const r = await api('GET', '/api/usage?fresh=1');
      out.innerHTML = r.enabled ? r.items.map(a => a.ok ? `<div class="banner" style="background:var(--ok-bg);color:var(--ok)">${esc(a.name)}: ${a.windows.map(w => esc(w.label) + ' ' + esc(w.left_pct) + ' % frei').join(', ')}</div>` : `<div class="banner bad">${esc(a.name)}: ${esc(a.error)}</div>`).join('')
        : '<div class="banner warn">Nichts eingeschaltet (oder noch nicht gespeichert).</div>';
    } catch (e) { out.innerHTML = `<div class="banner bad">${esc(e.message)}</div>`; }
  });
}
function sqForm() { return { url: val('sq-url'), ca_bundle: val('gl-ca'), secret: $('sq-secret').value, projects: P }; }
async function testSonar() {
  const out = $('sq-result');
  await busy($('sq-test'), 'Teste …', async () => {
    try { out.innerHTML = stepsHtml(await api('POST', '/api/settings/test/sonar', sqForm())); }
    catch (e) { out.innerHTML = `<div class="banner bad">${esc(e.message)}</div>`; }
  });
}
async function testGitlab() {
  const out = $('gl-result');
  await busy($('gl-test'), 'Teste …', async () => {
    try { const r = await api('POST', '/api/settings/test/gitlab', glForm()); out.innerHTML = stepsHtml(r); window.glUser = r.user; }
    catch (e) { out.innerHTML = `<div class="banner bad">${esc(e.message)}</div>`; }
  });
}
async function testJira() {
  const out = $('ji-result');
  await busy($('ji-test'), 'Teste …', async () => {
    try {
      const r = await api('POST', '/api/settings/test/jira', jiForm());
      let extra = '';
      if (r.projects && r.projects.length) extra += `<div style="margin-top:8px" class="quiet">Sichtbare Projekt-Keys (Klick = hinzufügen):</div><div>${r.projects.slice(0, 40).map(k => `<button class="pchip" data-addkey="${esc(k)}">${esc(k)}</button>`).join('')}</div>`;
      if (r.types && r.types.length) extra += `<div style="margin-top:4px" class="quiet">Vorgangstypen (Klick = hinzufügen):</div><div>${r.types.map(k => `<button class="pchip" data-addtype="${esc(k)}">${esc(k)}</button>`).join('')}</div>`;
      out.innerHTML = stepsHtml(r) + extra;
    } catch (e) { out.innerHTML = `<div class="banner bad">${esc(e.message)}</div>`; }
  });
}
$('viewSettings').addEventListener('click', ev => {
  const k = ev.target.closest('[data-addkey]'), t = ev.target.closest('[data-addtype]');
  if (k) $('ji-keys').value = uniq(split(val('ji-keys')).concat(k.dataset.addkey)).join(', ');
  if (t) $('ji-types').value = uniq(split(val('ji-types')).concat(t.dataset.addtype)).join(', ');
});
// Review-Umgebung je Projekt (0.32)
function renderReviewEnvs() {
  const box = $('renv-list'); if (!box) return;
  const K = S.review_kinds || [], H = S.hints || { projects: {}, repos: [], infra: [] };
  box.innerHTML = P.length ? P.map((p, i) => {
    const e = p.review_env || {}, h = H.projects[String(p.id)] || { compose: [], dockerfile: false };
    const sv = e.services || [];
    const suggest = !e.kind && (h.compose.length || h.dockerfile)
      ? `<button class="quiet-btn" data-resug="${i}" title="Erkannt im Checkout">Vorschlag: Docker Compose${h.compose.length ? ' mit ' + esc(h.compose[0]) : ' aus dem Dockerfile'}</button>` : '';
    const compose = e.kind === 'compose' ? `<div class="grid3" style="margin-top:6px">
        <label class="sm">Compose-Datei im Repo<select data-ref="${i}:compose_file"><option value="">${h.compose.length ? 'automatisch (' + esc(h.compose[0]) + ')' : h.dockerfile ? 'keine, aus dem Dockerfile bauen' : 'keine gefunden'}</option>${h.compose.map(f => `<option ${e.compose_file === f ? 'selected' : ''}>${esc(f)}</option>`).join('')}</select></label>
        <label class="sm">Port der Anwendung im Container<input type="number" data-ref="${i}:app_port" value="${esc(e.app_port || 8080)}" min="1" max="65535"></label></div>
      <div class="small" style="margin-top:6px"><b>Umsysteme</b> <span class="quiet">laufen mit, ohne Ports nach aussen. Erreichbar unter ihrem Namen, z. B. <code>postgres:5432</code>.</span></div>
      <div class="rsvc">${H.infra.map(x => `<label class="check"><input type="checkbox" data-resvc="${i}" value="${x.id}" ${sv.includes(x.id) ? 'checked' : ''}><span>${esc(x.label)}</span></label>`).join('')}</div>
      ${H.repos.length ? `<div class="rsvc">${H.repos.filter(r => !(h.ws_path && r.path === h.ws_path) && r.path !== p.repo_path).map(r => `<label class="check"><input type="checkbox" data-resvc="${i}" value="repo:${esc(r.path)}" ${sv.includes('repo:' + r.path) ? 'checked' : ''}><span class="picn">${repoIcon(r.name, 14)}${esc(r.name)}</span></label>`).join('')}</div>
        <div class="small quiet">Repos aus Workspaces mit Dockerfile, gebaut aus deinem lokalen Stand.</div>` : '<div class="small quiet">Weitere Repos als Umsysteme: erst unter Workspaces deine Ordner eintragen.</div>'}` : '';
    return `<div class="renv">
    <div class="row" style="gap:8px"><span class="picn">${repoIcon(p.name || String(p.id), 18)}<b>${esc(p.name || '#' + p.id)}</b></span>
      <select data-rek="${i}" aria-label="Art der Review-Umgebung für ${esc(p.name)}"><option value="">keine</option>${K.map(k => `<option value="${k.id}" ${e.kind === k.id ? 'selected' : ''}>${esc(k.label)}</option>`).join('')}</select>${suggest}</div>
    ${compose}
    ${e.kind ? `<details class="small" ${e.kind === 'compose' ? '' : 'open'} style="margin-top:6px"><summary class="quiet">Befehle${e.kind === 'compose' ? ' (vorbefüllt, anpassbar)' : ''}</summary><div class="grid3" style="margin-top:6px">${['up', 'down', 'url'].map(f => `<label class="sm">${{ up: 'Starten', down: 'Stoppen', url: 'Adresse zum Öffnen' }[f]}<input type="text" data-ref="${i}:${f}" value="${esc(e[f] || '')}" spellcheck="false" style="font-family:var(--mono);font-size:12.5px"></label>`).join('')}</div></details>` : ''}</div>`;
  }).join('')
    : '<div class="empty">Erst Projekte unter GitLab wählen.</div>';
}
$('viewSettings').addEventListener('change', ev => {
  const t = ev.target;
  if (t.dataset.rek !== undefined) {
    const p = P[+t.dataset.rek], d = (S.review_kinds || []).find(x => x.id === t.value);
    p.review_env = d ? { kind: d.id, up: d.up, down: d.down, url: d.url, services: [], app_port: 8080, compose_file: '' } : null;
    renderReviewEnvs();
  } else if (t.dataset.resvc !== undefined) {
    const e = P[+t.dataset.resvc].review_env, set = new Set(e.services || []);
    t.checked ? set.add(t.value) : set.delete(t.value);
    e.services = [...set];
  } else if (t.dataset.ref !== undefined && t.tagName === 'SELECT') {
    const [i, f] = t.dataset.ref.split(':'); P[+i].review_env = Object.assign({}, P[+i].review_env, { [f]: t.value });
  }
});
$('viewSettings').addEventListener('click', ev => {
  const b = ev.target.closest('[data-resug]'); if (!b) return;
  const p = P[+b.dataset.resug], d = (S.review_kinds || []).find(x => x.id === 'compose');
  p.review_env = { kind: 'compose', up: d.up, down: d.down, url: d.url, services: [], app_port: 8080, compose_file: '' };
  renderReviewEnvs();
});
$('viewSettings').addEventListener('input', ev => {
  const k = ev.target.dataset.ref; if (k === undefined || ev.target.tagName === 'SELECT') return;
  const [i, f] = k.split(':'); P[+i].review_env = Object.assign({}, P[+i].review_env, { [f]: ev.target.value });
});
// Lokale Checkouts für IntelliJ (0.20)
function renderIdeRepos() {
  const box = $('ide-list'); if (!box) return;
  const rows = P.map((p, i) => ({ k: 'p', i, name: p.name || '#' + p.id, v: p.repo_path || '', src: 'GitLab' }))
    .concat((typeof GH !== 'undefined' ? GH : []).map((r, i) => ({ k: 'g', i, name: r.full, v: r.repo_path || '', src: 'GitHub' })));
  box.innerHTML = rows.length ? `<div class="ptab" role="table" aria-label="Lokale Checkouts"><div class="ph" role="row" style="grid-template-columns:200px 80px minmax(0,1fr)"><span>Projekt</span><span>Quelle</span><span>Pfad zum lokalen Checkout</span></div>` +
    rows.map(r => { const ws = r.k === 'p' && ((S.hints || { projects: {} }).projects[String(P[r.i].id)] || {}).ws_path;
      return `<div class="pr" role="row" style="grid-template-columns:200px 80px minmax(0,1fr)"><span>${esc(r.name)}</span><span class="quiet">${r.src}</span><span><input type="text" data-rp="${r.k}${r.i}" value="${esc(r.v)}" placeholder="${ws ? 'aus Workspaces: ' + esc(ws) : '~/work/' + esc(String(r.name).split('/').pop())}" aria-label="Pfad zum Checkout von ${esc(r.name)}">${ws && !r.v ? '<span class="small quiet">Leer lassen: tinyops nimmt den Checkout aus Workspaces.</span>' : ''}</span></div>`; }).join('') + '</div>'
    : '<div class="empty">Erst Projekte unter GitLab oder GitHub wählen.</div>';
}
$('viewSettings').addEventListener('input', ev => {
  const k = ev.target.dataset.rp; if (k === undefined) return;
  const list = k[0] === 'p' ? P : GH, i = +k.slice(1);
  if (list[i]) list[i].repo_path = ev.target.value;
});
// Projekte
function renderProjects() {
  $('pj-list').innerHTML = P.length ? `<div class="ptab" role="table" aria-label="Projekte"><div class="ph" role="row"><span>ID</span><span>Anzeigename</span><span>Sonar-Schlüssel</span><span title="Ordner des Repositories unter dem Arbeitsordner eines Agenten (leer = Anzeigename)">Agent-Ordner</span><span title="restricted: nur lokale Agenten · internal: Cloud-Agenten erlaubt, optional nur freigegebene Pfade · public: ohne Einschränkung">Datenklasse</span><span title="Nur bei internal: Cloud-Agenten bekommen einen Export nur dieser Pfade (kommagetrennt). Leer = ganzes Repo">Cloud-Pfade</span><span></span></div>` +
    P.map((p, i) => `<div class="pr" role="row"><span class="quiet">#${esc(p.id)}</span>
    <input type="text" data-pn="${i}" value="${esc(p.name)}" aria-label="Anzeigename">
    <input type="text" data-pk="${i}" value="${esc(p.sonar_key || '')}" placeholder="—" aria-label="Sonar-Projektschlüssel">
    <input type="text" data-pa="${i}" value="${esc(p.agent_dir || '')}" placeholder="${esc(p.name)}" aria-label="Agent-Ordner">
    ${classSel('pcl', i, p.data_class)}
    <input type="text" data-pcp="${i}" value="${esc(pathsStr(p.cloud_paths))}" placeholder="${p.data_class === 'internal' ? 'ganzes Repo' : '—'}" ${p.data_class === 'internal' ? '' : 'disabled'} aria-label="Freigegebene Pfade für Cloud-Agenten">
    <button class="quiet-btn" data-pdel="${i}" title="Projekt entfernen" aria-label="Projekt entfernen">×</button></div>`).join('') + '</div>'
    : '<div class="empty">Noch kein Projekt.</div>';
  renderIdeRepos(); renderReviewEnvs();
}
$('viewSettings').addEventListener('input', ev => { const i = ev.target.dataset.pn; if (i !== undefined) P[+i].name = ev.target.value; const k = ev.target.dataset.pk; if (k !== undefined) P[+k].sonar_key = ev.target.value; const a = ev.target.dataset.pa; if (a !== undefined) P[+a].agent_dir = ev.target.value; });
const pathsStr = x => Array.isArray(x) ? x.join(', ') : (x || '');
function classSel(attr, i, cur) {
  const c = cur || 'restricted';
  return `<select data-${attr}="${i}" aria-label="Datenklasse">${(S.data_classes || []).map(x => `<option value="${esc(x.id)}" ${x.id === c ? 'selected' : ''} title="${esc(x.label)}">${esc(x.id)}</option>`).join('')}</select>`;
}
$('viewSettings').addEventListener('change', ev => {
  const t = ev.target;
  if (t.dataset.pcl !== undefined) { P[+t.dataset.pcl].data_class = t.value; renderProjects(); }
  if (t.dataset.ghcl !== undefined) { GH[+t.dataset.ghcl].data_class = t.value; renderGhRepos(); }
});
$('viewSettings').addEventListener('input', ev => {
  const t = ev.target;
  if (t.dataset.pcp !== undefined) P[+t.dataset.pcp].cloud_paths = t.value;
  if (t.dataset.ghcp !== undefined) GH[+t.dataset.ghcp].cloud_paths = t.value;
});
$('viewSettings').addEventListener('click', ev => {
  const d = ev.target.closest('[data-pdel]');
  if (d) { P.splice(+d.dataset.pdel, 1); renderProjects(); }
  const a = ev.target.closest('[data-padd]');
  if (a && !P.some(p => p.id === +a.dataset.padd)) { P.push({ id: +a.dataset.padd, name: a.dataset.name }); renderProjects(); a.disabled = true; a.textContent = 'hinzugefügt'; }
});
async function searchProjects() {
  const q = val('pj-q'), out = $('pj-res');
  await busy($('pj-search'), 'Suche …', async () => {
    try {
      const r = await api('POST', '/api/settings/projects', { url: val('gl-url'), ca_bundle: val('gl-ca'), token: $('gl-token').value, q });
      if (r.error) { out.innerHTML = `<div class="banner bad">${esc(r.error)}<br><span class="quiet">Erst oben die GitLab-Verbindung testen.</span></div>`; return; }
      out.innerHTML = r.items.length ? `<table class="mini">${r.items.map(p => `<tr><td>${esc(p.full || p.name)}</td><td>#${esc(p.id)}</td>
        <td><button data-padd="${esc(p.id)}" data-name="${esc(p.name)}">Hinzufügen</button></td></tr>`).join('')}</table>`
        : '<div class="empty">Nichts gefunden (es werden nur Projekte gezeigt, in denen du Mitglied bist).</div>';
    } catch (e) { out.innerHTML = `<div class="banner bad">${esc(e.message)}</div>`; }
  });
}
// Identität aus Commits vorschlagen
async function suggestIdentity() {
  const out = $('id-result');
  if (!P.length) { out.innerHTML = '<div class="banner warn">Erst unter GitLab ein Projekt hinzufügen.</div>'; return; }
  await busy($('id-suggest'), 'Lese Commits …', async () => {
    try {
      const r = await api('POST', '/api/settings/identity', { url: val('gl-url'), ca_bundle: val('gl-ca'), token: $('gl-token').value, project_id: P[0].id });
      if (r.error) { out.innerHTML = `<div class="banner bad">${esc(r.error)}</div>`; return; }
      out.innerHTML = `<div class="quiet">Autoren der letzten ${r.commits} Commits in ${esc(P[0].name)}. Kreuze an, wer du bist und wer dein Agent ist.</div>
        <table class="mini"><tr><th>Name</th><th>E-Mail</th><th>Commits</th><th>ich</th><th>Agent</th></tr>
        ${r.authors.map((a, i) => `<tr><td>${esc(a.name)}</td><td>${esc(a.email)}</td><td>${a.count}</td>
          <td><input type="checkbox" data-me="${i}" ${a.is_me ? 'checked' : ''}></td><td><input type="checkbox" data-ag="${i}"></td></tr>`).join('')}</table>
        ${r.trailers.length ? `<div class="quiet" style="margin-top:6px">Agent-Zeilen in Commit-Nachrichten (nur der stabile Anfang wird übernommen):</div>
          ${r.trailers.map((t, i) => `<label class="row"><input type="checkbox" data-tr="${i}" ${/claude|bot/i.test(t.pattern) ? 'checked' : ''}> ${esc(t.pattern)} <span class="quiet">(${t.count}×)</span></label>`).join('')}` : ''}
        <div class="row" style="margin:8px 0"><button class="primary" id="id-apply">Übernehmen</button></div>`;
      $('id-apply').onclick = () => {
        const sel = (attr) => r.authors.filter((a, i) => out.querySelector(`[${attr}="${i}"]`).checked);
        const me = sel('data-me'), ag = sel('data-ag');
        $('bf-emails').value = uniq(split(val('bf-emails')).concat(me.map(a => a.email).filter(Boolean))).join(', ');
        $('bf-names').value = uniq(split(val('bf-names')).concat(me.map(a => a.name).filter(Boolean))).join(', ');
        $('bf-aemails').value = uniq(split(val('bf-aemails')).concat(ag.map(a => a.email).filter(Boolean))).join(', ');
        $('bf-anames').value = uniq(split(val('bf-anames')).concat(ag.map(a => a.name).filter(Boolean))).join(', ');
        const pats = r.trailers.filter((t, i) => out.querySelector(`[data-tr="${i}"]`).checked).map(t => t.pattern);
        $('bf-pat').value = uniq(split(val('bf-pat')).concat(pats)).join(', ');
        toast('Übernommen. Noch speichern.');
      };
    } catch (e) { out.innerHTML = `<div class="banner bad">${esc(e.message)}</div>`; }
  });
}
// ---- GitHub: Repos
function ghForm() { return { api_url: val('gh-api'), ca_bundle: val('gl-ca'), secret: $('gh-secret').value, repos: GH }; }
function renderGhRepos() {
  const box = $('gh-list'); if (!box) return;
  box.innerHTML = GH.length ? `<div class="ptab gh" role="table" aria-label="GitHub-Repos"><div class="ph" role="row"><span>Repo</span><span title="Ordner des Repositories unter dem Arbeitsordner eines Agenten (leer = Repo-Name)">Agent-Ordner</span><span>Datenklasse</span><span title="Nur bei internal: Cloud-Agenten bekommen einen Export nur dieser Pfade">Cloud-Pfade</span><span></span></div>` +
    GH.map((r, i) => `<div class="pr" role="row"><span title="${r.id ? 'Repo-ID ' + esc(r.id) : 'ID wird beim Test ermittelt'}">${esc(r.full)}</span>
      <input type="text" data-gha="${i}" value="${esc(r.agent_dir || '')}" placeholder="${esc(r.full.split('/').pop())}" aria-label="Agent-Ordner">
      ${classSel('ghcl', i, r.data_class)}
      <input type="text" data-ghcp="${i}" value="${esc(pathsStr(r.cloud_paths))}" placeholder="${r.data_class === 'internal' ? 'ganzes Repo' : '—'}" ${r.data_class === 'internal' ? '' : 'disabled'} aria-label="Freigegebene Pfade">
      <button class="quiet-btn" data-ghdel="${i}" aria-label="Repo entfernen" title="Repo entfernen">×</button></div>`).join('') + '</div>' : '<div class="empty">Noch kein Repo.</div>';
  renderIdeRepos();
}
$('viewSettings').addEventListener('input', ev => { const a = ev.target.dataset.gha; if (a !== undefined) GH[+a].agent_dir = ev.target.value; });
$('viewSettings').addEventListener('click', ev => {
  const d = ev.target.closest('[data-ghdel]'); if (d) { GH.splice(+d.dataset.ghdel, 1); renderGhRepos(); }
  const a = ev.target.closest('[data-ghadd]');
  if (a && !GH.some(r => r.full.toLowerCase() === a.dataset.ghadd.toLowerCase())) { GH.push({ full: a.dataset.ghadd, id: +a.dataset.id }); renderGhRepos(); a.disabled = true; a.textContent = 'hinzugefügt'; }
});
async function searchGithub() {
  const out = $('gh-res');
  await busy($('gh-search'), 'Suche …', async () => {
    try {
      const r = await api('POST', '/api/settings/github/repos', { ...ghForm(), q: val('gh-q') });
      if (r.error) { out.innerHTML = `<div class="banner bad">${esc(r.error)}</div>`; return; }
      out.innerHTML = r.items.length ? `<table class="mini">${r.items.map(x => `<tr><td>${esc(x.full)}${x.private ? ' <span class="chip">privat</span>' : ''}</td>
        <td><button data-ghadd="${esc(x.full)}" data-id="${x.id}">Hinzufügen</button></td></tr>`).join('')}</table>` : '<div class="empty">Nichts gefunden. «owner/name» findet auch ein einzelnes Repo.</div>';
    } catch (e) { out.innerHTML = `<div class="banner bad">${esc(e.message)}</div>`; }
  });
}
async function testGithub() {
  const out = $('gh-result');
  await busy($('gh-test'), 'Teste …', async () => {
    try {
      const r = await api('POST', '/api/settings/test/github', ghForm());
      Object.entries(r.ids || {}).forEach(([full, id]) => { const x = GH.find(g => g.full === full); if (x && id) x.id = id; });
      out.innerHTML = stepsHtml(r);
    } catch (e) { out.innerHTML = `<div class="banner bad">${esc(e.message)}</div>`; }
  });
}
// ---- Agenten: Einstellungen
const agSlug = t => String(t || '').trim().toLowerCase().replace(/[^a-z0-9_-]+/g, '-').replace(/^-+|-+$/g, '').slice(0, 31);
const connOptions = sel => '<option value="local"' + (sel === 'local' ? ' selected' : '') + '>lokal (dieser Rechner)</option>' + CN.map(c => { const id = c.id || agSlug(c.name); return `<option value="${esc(id)}" ${sel === id ? 'selected' : ''}>${esc(c.name || id)} (SSH)</option>`; }).join('');
function refreshConnOptions() {   // nur die Auswahllisten, damit beim Tippen kein Feld den Fokus verliert
  document.querySelectorAll('select[data-ag][data-f="connection"]').forEach(sel => { const a = AGC[+sel.dataset.ag]; sel.innerHTML = connOptions(a.connection || 'local'); });
}
function renderAgentCfg() {
  const kinds = (S.agent_kinds || []);
  const cn = $('cn-list'), ag = $('ag-list');
  if (!cn || !ag) return;
  cn.innerHTML = CN.length ? CN.map((c, i) => `<div class="agbox"><div class="grid3">
      <label class="sm">Name<input type="text" data-cn="${i}" data-f="name" value="${esc(c.name || '')}" placeholder="dev-vm" maxlength="40"></label>
      <label class="sm">Rechner<input type="text" data-cn="${i}" data-f="host" value="${esc(c.host || '')}" placeholder="dev.example.intern"></label>
      <label class="sm">Benutzer<input type="text" data-cn="${i}" data-f="user" value="${esc(c.user || '')}" placeholder="adrian"></label>
      <label class="sm">Port<input type="number" data-cn="${i}" data-f="port" value="${esc(c.port || 22)}"></label>
      <label class="sm">Schlüsseldatei (optional)<input type="text" data-cn="${i}" data-f="identity_file" value="${esc(c.identity_file || '')}" placeholder="~/.ssh/id_ed25519"></label>
      <label class="sm">Host-Schlüssel<select data-cn="${i}" data-f="host_key"><option value="strict" ${c.host_key !== 'accept-new' ? 'selected' : ''}>streng (muss bekannt sein)</option><option value="accept-new" ${c.host_key === 'accept-new' ? 'selected' : ''}>beim ersten Mal vertrauen</option></select></label>
    </div><div class="row"><button data-cndel="${i}">Entfernen</button></div>
    <div class="ferr" data-err="connections.${i}.name"></div><div class="ferr" data-err="connections.${i}.host"></div><div class="ferr" data-err="connections.${i}.user"></div><div class="ferr" data-err="connections.${i}.port"></div><div class="ferr" data-err="connections.${i}.identity_file"></div></div>`).join('')
    : '<div class="quiet small" style="margin-bottom:8px">Noch keine SSH-Verbindung. Für Agenten auf diesem Rechner ist keine nötig.</div>';
  const conOpts = connOptions;
  ag.innerHTML = AGC.length ? AGC.map((a, i) => `<div class="agbox"><div class="grid3">
      <label class="sm">Name<input type="text" data-ag="${i}" data-f="name" value="${esc(a.name || '')}" placeholder="claude-devvm" maxlength="40"></label>
      <label class="sm">Art<select data-ag="${i}" data-f="kind">${kinds.map(k => `<option value="${esc(k.id)}" ${a.kind === k.id ? 'selected' : ''}>${esc(k.label)}</option>`).join('')}</select></label>
      <label class="sm">Verbindung<select data-ag="${i}" data-f="connection">${conOpts(a.connection || 'local')}</select></label>
      <label class="sm">Arbeitsordner<input type="text" data-ag="${i}" data-f="workspace_root" value="${esc(a.workspace_root || '')}" placeholder="/home/me/work"></label>
      <label class="sm">Zusätzliche Argumente<input type="text" data-ag="${i}" data-f="extra_args" value="${esc(a.extra_args || '')}" placeholder="--model opus"></label>
      <label class="sm" title="Danach wird der Lauf beendet (Prozesse und tmux-Sitzung). 0 = kein Limit">Zeitlimit in Minuten<input type="number" min="0" max="1440" data-ag="${i}" data-f="max_minutes" value="${esc(a.max_minutes ?? 60)}"></label>
      ${['goose', 'opencode'].includes(a.kind) ? `<label class="sm" title="Modellname, wie ihn der Anbieter oder Proxy kennt. Laufen alle Modelle über denselben Proxy: je Modell einen eigenen Agenten anlegen.">Modell<input type="text" data-ag="${i}" data-f="model" value="${esc(a.model || '')}" placeholder="qwen2.5-coder:32b"></label>
      <label class="sm" title="Anbieter, wie ${a.kind === 'goose' ? 'Goose (GOOSE_PROVIDER)' : 'opencode'} ihn nennt. ${a.kind === 'goose' ? 'Leer: Goose nimmt den Anbieter aus seiner eigenen Konfiguration (goose configure), tinyops setzt nur das Modell.' : ''}">Anbieter<input type="text" data-ag="${i}" data-f="provider" list="agProviders" value="${esc(a.provider ?? 'ollama')}" placeholder="${a.kind === 'goose' ? 'leer = wie in Goose eingestellt' : 'ollama'}"></label>` : ''}
      <label class="sm" title="Fehlt ein Projekt beim Agenten, bietet der Zuweisen-Dialog das Klonen an. SSH braucht einen Schlüssel des Zielrechners bei GitLab/GitHub, HTTPS dort gespeicherte Zugangsdaten.">Klonen über<select data-ag="${i}" data-f="clone_via"><option value="ssh" ${a.clone_via !== 'https' ? 'selected' : ''}>SSH</option><option value="https" ${a.clone_via === 'https' ? 'selected' : ''}>HTTPS</option></select></label>
      <label class="sm" title="Worktree: jeder Lauf bekommt einen eigenen Ordner und Branch agent/<key>-<nr>; der Hauptcheckout bleibt unberührt">Isolation<select data-ag="${i}" data-f="isolation"><option value="worktree" ${a.isolation !== 'shared' ? 'selected' : ''}>Worktree je Lauf (empfohlen)</option><option value="shared" ${a.isolation === 'shared' ? 'selected' : ''}>gemeinsamer Ordner (wie bis 0.15)</option></select></label>
      <label class="sm" title="Für welche Phasen der Agent da ist, und mit welchem Befehl sein Prompt beginnt (z. B. eigene Slash-Befehle auf dem Agenten-Rechner). Leer: alle Phasen, ohne Befehl.">Rollen<input type="text" data-ag="${i}" data-f="roles" value="${esc(rolesText(a.roles))}" placeholder="plan=/planner, develop=/developer, review=/reviewer, test=/tester"></label>
      <label class="sm" title="Welches Abo dieser Agent verbraucht. Die Auswahl beim Zuweisen zeigt dann, wie viel davon noch frei ist.">Kontingent<select data-ag="${i}" data-f="quota">${[['claude', 'Claude'], ['codex', 'Codex (ChatGPT)'], ['mistral', 'Mistral'], ['none', 'keins']].map(([v, l]) => `<option value="${v}" ${(a.quota || QUOTA_DEF[a.kind] || 'none') === v ? 'selected' : ''}>${l}</option>`).join('')}</select></label>
      <label class="sm check" style="align-self:end" title="Der Agent pusht am Ende genau seinen Lauf-Branch (git push -u origin HEAD), nie main, master, develop oder release/*. tinyops selbst pusht nie."><input type="checkbox" data-ag="${i}" data-f="push" ${a.push ? 'checked' : ''}><span>pusht seinen Branch</span></label>
      <div class="sm" style="align-self:end"><button type="button" data-agroles="${i}" title="Rollen mit /planner, /developer, /reviewer, /tester füllen">Rollen-Vorschlag</button></div>
    </div>
    ${['goose', 'opencode'].includes(a.kind) ? `<div class="quiet small"><label><input type="checkbox" data-ag="${i}" data-f="cloud" ${a.cloud ? 'checked' : ''}> sendet Daten an einen Cloud-Anbieter</label> · Aus lassen nur, wenn dieses Modell wirklich im eigenen Netz läuft. Nur dann darf der Agent an restricted-Projekte. Läuft alles über denselben Proxy, sieht tinyops den Unterschied nicht: Du sagst es hier je Agent.</div><datalist id="agProviders"><option value="ollama"><option value="openai"><option value="litellm"><option value="openrouter"></datalist>` : ''}
    ${a.kind === 'custom' ? `<div class="quiet small">Eigener Befehl: ${a.has_command ? 'in der config.json hinterlegt (<code>command</code>, mit <code>{prompt_file}</code> für die Prompt-Datei).' : '<strong>fehlt</strong>: in der config.json beim Agenten <code>"command"</code> eintragen. Die Oberfläche setzt ihn absichtlich nicht.'} <label><input type="checkbox" data-ag="${i}" data-f="cloud" ${a.cloud ? 'checked' : ''}> sendet Daten an einen Cloud-Anbieter</label></div>` : ''}
    <div class="row"><button data-agtest="${i}">Testen</button><button data-agdel="${i}">Entfernen</button><span class="quiet small">Prüft Verbindung, tmux, Arbeitsordner und Programm. Gespeichert wird erst mit «Speichern».</span></div>
    <div id="ag-res-${i}"></div>
    <div class="ferr" data-err="agents.${i}.name"></div><div class="ferr" data-err="agents.${i}.connection"></div><div class="ferr" data-err="agents.${i}.workspace_root"></div><div class="ferr" data-err="agents.${i}.extra_args"></div><div class="ferr" data-err="agents.${i}.max_minutes"></div><div class="ferr" data-err="agents.${i}.roles"></div><div class="ferr" data-err="agents.${i}.quota"></div><div class="ferr" data-err="agents.${i}.model"></div><div class="ferr" data-err="agents.${i}.provider"></div></div>`).join('')
    : '<div class="quiet small" style="margin-bottom:8px">Noch kein Agent.</div>';
}
$('viewSettings').addEventListener('input', ev => {
  const t = ev.target, f = t.dataset.f;
  if (!f) return;
  const v = t.type === 'checkbox' ? t.checked : t.value;
  if (t.dataset.cn !== undefined) CN[+t.dataset.cn][f] = v;
  if (t.dataset.ag !== undefined) AGC[+t.dataset.ag][f] = v;
});
$('viewSettings').addEventListener('change', ev => {
  const t = ev.target, f = t.dataset.f;
  if (!f) return;
  if (t.dataset.cn !== undefined) { CN[+t.dataset.cn][f] = t.value; if (f === 'name') refreshConnOptions(); }
  if (t.dataset.ag !== undefined) { const a = AGC[+t.dataset.ag]; a[f] = t.type === 'checkbox' ? t.checked : t.value; if (f === 'kind') renderAgentCfg(); }
});
$('viewSettings').addEventListener('click', async ev => {
  const b = ev.target.closest('button');
  if (!b) return;
  if (b.id === 'cn-add') { CN.push({ name: '', host: '', user: '', port: 22, identity_file: '', host_key: 'strict' }); renderAgentCfg(); }
  if (b.id === 'ag-add') { AGC.push({ name: '', kind: 'claude', connection: 'local', workspace_root: '', extra_args: '', isolation: 'worktree', max_minutes: 60 }); renderAgentCfg(); }
  if (b.dataset.cndel !== undefined) { const c = CN.splice(+b.dataset.cndel, 1)[0]; const id = c.id || agSlug(c.name); AGC.forEach(a => { if (a.connection === id) a.connection = 'local'; }); renderAgentCfg(); }
  if (b.dataset.agdel !== undefined) { AGC.splice(+b.dataset.agdel, 1); renderAgentCfg(); }
  if (b.dataset.agroles !== undefined) { AGC[+b.dataset.agroles].roles = 'plan=/planner, develop=/developer, review=/reviewer, test=/tester'; renderAgentCfg(); }
  if (b.dataset.agtest !== undefined) {
    const i = +b.dataset.agtest, a = AGC[i], out = $('ag-res-' + i);
    const c = a.connection && a.connection !== 'local' ? CN.find(x => (x.id || agSlug(x.name)) === a.connection) : null;
    if (a.connection && a.connection !== 'local' && !c) { out.innerHTML = '<div class="banner bad">Diese Verbindung gibt es nicht.</div>'; return; }
    await busy(b, 'Teste …', async () => {
      try { out.innerHTML = stepsHtml(await api('POST', '/api/settings/test/agent', { connection: c ? { ...c, id: c.id || agSlug(c.name) } : null, agent: { kind: a.kind, workspace_root: a.workspace_root } })); }
      catch (e) { out.innerHTML = `<div class="banner bad">${esc(e.message)}</div>`; }
    });
  }
});
// Speichern
function collect() {
  const secrets = {};
  if ($('gl-token').value.trim()) secrets.gitlab_token = $('gl-token').value;
  if ($('ji-secret').value.trim()) secrets[val('ji-auth') === 'basic' ? 'jira_password' : 'jira_token'] = $('ji-secret').value;
  if ($('sq-secret').value.trim()) secrets.sonar_token = $('sq-secret').value;
  if ($('gh-secret').value.trim()) secrets.github_token = $('gh-secret').value;
  if ($('lm-secret') && $('lm-secret').value.trim()) secrets.llm_key = $('lm-secret').value;
  if ($('bc-secret') && $('bc-secret').value.trim()) secrets.bcs_token = $('bc-secret').value;
  if ($('hd-secret') && $('hd-secret').value.trim()) secrets[val('hd-auth') === 'bearer' ? 'helpdesk_token' : 'helpdesk_password'] = $('hd-secret').value;
  return {
    gitlab: { url: val('gl-url'), ca_bundle: val('gl-ca') },
    projects: P, connections: CN, agents: AGC, agent_log_days: val('ag-days'), agent_guards: { max_files: val('ag-gf'), max_lines: val('ag-gl'), extra: val('ag-gx') }, ide_command: val('ide-cmd'),
    time: { enabled: $('tm-on').checked, round_minutes: val('tm-round'), min_minutes: val('tm-min'), idle_minutes: val('tm-idle'), 
      bcs: { enabled: $('bc-on').checked, url: val('bc-url'), apprentices: $('bc-appr').checked, allow_lan: $('bc-lan').checked } },
    github: { enabled: $('gh-on').checked, api_url: val('gh-api'), repos: GH },
    branch_filter: { emails: split(val('bf-emails')), names: split(val('bf-names')), agent_emails: split(val('bf-aemails')), agent_names: split(val('bf-anames')),
      agent_message_patterns: split(val('bf-pat')), max_branches: val('bf-max'), max_age_days: val('bf-age'), ignore_branches: split(val('bf-ignore')) },
    jira: { url: val('ji-url'), auth: val('ji-auth'), username: val('ji-user'), project_keys: split(val('ji-keys')), story_limit: val('ji-limit'),
      wip_issue_types: split(val('ji-types')), group_link_types: split(val('ji-grp')), jql_in_progress: val('ji-jql'), only_active_sprints: $('ji-sprint').checked,
      allow_create: $('ji-create').checked, create_type: val('ji-ctype') },
    usage: { claude: $('us-claude').checked, codex: $('us-codex').checked, mistral: $('us-mistral').checked, claude_file: val('us-claude-file'), codex_file: val('us-codex-file'), cache_seconds: val('us-cache') },
    sonar: { enabled: $('sq-on').checked, url: val('sq-url'), cache_seconds: val('sq-cache'), max_items: val('sq-max'), report_max: val('sq-rep') },
    llm: { enabled: $('lm-on').checked, provider: val('lm-prov'), url: val('lm-url'), model: val('lm-model'), allow_remote: $('lm-remote').checked, timeout: val('lm-timeout') },
    features: { ideas: $('ft-ideas').checked, ai: $('ft-ai').checked, score: $('ft-score').checked },
    ux: { enabled: $('ux-on').checked, days: val('ux-days') },
    workspaces: { enabled: $('ws-on').checked, roots: val('ws-roots'), depth: val('ws-depth'), stale_days: val('ws-stale'), scan_minutes: val('ws-scan') },
    app: { phone_url: val('app-phone'), origins: val('app-origins') },
    m365: { enabled: $('m3-on').checked, tenant: val('m3-tenant'), client_id: val('m3-client'), mail: $('m3-mail').checked, calendar: $('m3-cal').checked,
      teams: $('m3-teams').checked, calendar_write: $('m3-write').checked, reply_days: val('m3-days'), refresh_minutes: val('m3-every') },
    helpdesk: { enabled: $('hd-on').checked, url: val('hd-url'), name: val('hd-name'), auth: val('hd-auth'), username: val('hd-user'), assigned_jql: val('hd-jql'),
                queue_jql: val('hd-qjql'), watch_jql: val('hd-wjql'), sla_hours: val('hd-sla'), area: val('hd-area') },
    focus: { week_hours: val('fo-hours'), day_start: val('fo-start'), day_end: val('fo-end'),
             areas: readFocusAreas().map(a => ({ id: a.id, name: a.name, target_pct: a.target_pct, ticket: a.ticket, pools: a.pools, activities: a.activities, blocks_text: a.blocks_text || '' })) },
    secrets,
  };
}
async function saveSettings() {
  clearErrors();
  await busy($('st-save'), 'Speichere …', async () => {
    try {
      const r = await api('POST', '/api/settings/save', collect());
      const where = Object.entries(r.secrets || {}).map(([k, v]) => `${k}: ${v}`).join('; ');
      toast('Gespeichert' + (where ? ' (' + where + ')' : ''));
      await loadSettings(); usageData = null; await load();
      if (S.gitlab.url) testGitlab();
      if (S.jira.url) testJira();
      if (S.sonar.enabled && S.sonar.url) testSonar();
      if (S.github && S.github.enabled) testGithub();
      if (S.helpdesk.enabled && S.helpdesk.url) $('hd-test').click();
    } catch (e) {
      showErrors(e.data && e.data.errors);
      toast(e.message);
      const first = document.querySelector('.ferr:not(:empty)'); if (first) first.scrollIntoView({ block: 'center' });
    }
  });
}
async function delSecrets(names, label) {
  if (!confirm(label + ' wirklich aus dem Speicher löschen?')) return;
  try { await api('POST', '/api/settings/save', { ...collect(), secrets: {}, delete_secrets: names }); toast('Gelöscht'); await loadSettings(); await load(); }
  catch (e) { showErrors(e.data && e.data.errors); toast(e.message); }
}
