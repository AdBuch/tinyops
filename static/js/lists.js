// Listen (die frühere Übersicht): Kacheln, Ticket anlegen, KI-Kontingent, Verknüpfen.
// ---------------------------------------------------------------- Übersicht
const pipelineLabel = { success: 'Pipeline grün', failed: 'Pipeline rot', running: 'Pipeline läuft', pending: 'Pipeline wartet', none: 'keine Pipeline' };
const filt = { q: '', proj: LS.get('proj', ''), agent: LS.get('agent', false), notk: LS.get('notk', false), stale: LS.get('stale', false) };
// Warum steht das hier? Eine Zeile, die sagt, was von dir erwartet wird.
const SQ = { OK: ['Gate grün', 'sq-ok'], ERROR: ['Gate rot', 'sq-bad'], WARN: ['Gate Warnung', 'warn'], NONE: ['Sonar: keine Analyse', 'sq-none'], UNKNOWN: ['Sonar: Fehler', 'sq-none'] };
const SQ_HAS = { OK: 1, WARN: 1, ERROR: 1 };
function sqRepAttrs(x) { return `data-sqrep="1" data-p="${x.project_id}" data-i="${x.iid ?? ''}" data-b="${esc(x.branch || '')}"`; }
// Kleine Links hinter einem MR-Chip: Sonar-Dashboard, Findings in Sonar, Findings als Markdown ins Clipboard
function sqLinks(x) {
  const a = [];
  const tb = trendBadge(x);
  if (!x.iid && x.create_mr_url) a.push(`<a class="sqlink" href="${esc(x.create_mr_url)}" target="_blank" rel="noopener" title="In GitLab einen Merge Request für diesen Branch anlegen">MR erstellen</a>`);
  if (!SQ_HAS[x.sonar] && !x.sonar_url) return a.length ? `<span class="sqlinks">${a.join('')}</span>` : '';
  if (tb) a.push(tb);
  if (x.sonar_url) a.push(`<a class="sqlink" href="${esc(x.sonar_url)}" target="_blank" rel="noopener" title="Dashboard in Sonar">Sonar</a>`);
  if (x.sonar_issues_url && SQ_HAS[x.sonar]) a.push(`<a class="sqlink" href="${esc(x.sonar_issues_url)}" target="_blank" rel="noopener" title="Offene Findings in Sonar">Findings</a>`);
  if (SQ_HAS[x.sonar]) a.push(`<button class="sqlink" ${sqRepAttrs(x)} title="Findings als Markdown-Report in die Zwischenablage (Pfade und Meldungen, kein Quelltext)">Report kopieren</button>`);
  return `<span class="sqlinks">${a.join('')}</span>`;
}
// Verlauf der Findings: kleine Kurve und Änderung seit der ersten Analyse. Weniger ist besser (grün), mehr ist schlechter (rot).
function trendOf(x) { return x && typeof x.sonar === 'object' && x.sonar ? x.sonar.trend : (x ? x.sonar_trend : null); }
function trendBadge(x) {
  const t = trendOf(x);
  if (!t || !t.points || t.points.length < 2) return '';
  const p = t.points, w = 42, h = 14, mn = Math.min(...p), mx = Math.max(...p), span = (mx - mn) || 1;
  const pts = p.map((v, i) => `${(i * (w - 2) / (p.length - 1) + 1).toFixed(1)},${(h - 2 - (v - mn) / span * (h - 4)).toFixed(1)}`).join(' ');
  const cls = t.delta < 0 ? 'tdn' : t.delta > 0 ? 'tup' : 'tfl';
  const sign = t.delta < 0 ? '▼ ' + Math.abs(t.delta) : t.delta > 0 ? '▲ ' + t.delta : '= 0';
  const since = t.since ? new Date(t.since * 1000).toLocaleDateString('de-CH', { day: '2-digit', month: '2-digit' }) : '';
  const tip = `Findings ${t.first} → ${t.last}${since ? ' seit ' + since : ''} (${t.n} Messpunkte, Quelle: ${t.source})`;
  return `<span class="sqtrend ${cls}" title="${esc(tip)}"><svg width="${w}" height="${h}" viewBox="0 0 ${w} ${h}" aria-hidden="true"><polyline points="${pts}" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linejoin="round" stroke-linecap="round"/></svg>${sign}</span>`;
}
function sonarChip(it) {
  const s = it.sonar; if (!s || !SQ[s.status]) return '';
  const [t, c] = SQ[s.status];
  const why = (s.failed || []).concat(s.detail ? [s.detail] : []).join('\n');
  const tag = `<span style="opacity:.75">Sonar</span> ${esc(t.replace('Sonar: ', ''))}`;
  return s.url ? `<a class="chip ${c}" href="${esc(s.url)}" target="_blank" rel="noopener" title="${esc(why)}">${tag}</a>` : `<span class="chip ${c}" title="${esc(why)}">${tag}</span>`;
}
function reasonOf(it) {
  if (it.kind === 'review') return { t: 'Review wartet auf dich', c: 'focus' };
  if (it.kind === 'assigned') return { t: 'Dir zugeteilt', c: 'focus' };
  if (it.kind === 'branch') return { t: it.ahead ? `${it.ahead} Commit${it.ahead === 1 ? '' : 's'} ohne MR` : 'Branch ohne MR', c: '' };
  if (it.draft) return { t: 'Draft', c: '' };
  if (it.pipeline === 'failed') return { t: 'Pipeline rot', c: 'bad' };
  if (it.sonar && it.sonar.status === 'ERROR') return { t: 'Quality Gate rot', c: 'bad' };
  if (it.pipeline === 'success') return { t: 'Bereit zum Mergen', c: 'focus' };
  if (['running', 'pending', 'created', 'waiting_for_resource'].includes(it.pipeline)) return { t: 'Pipeline läuft', c: '' };
  return { t: 'Offen', c: '' };
}
function railOf(it) {
  const r = reasonOf(it);
  if (r.c === 'bad') return 'bad';
  if (it.stale) return 'warn';
  return r.c === 'focus' ? 'focus' : '';
}
function ticketChip(it) {
  const j = state.jira;
  if (!j || !j.ok) return '';
  if (it.ticket) {
    const t = it.ticket;
    const out = j.only_active && t.in_sprint === false;
    const cls = out ? 'chip out' : 'chip tk';  // Jira-Ticket
    const hint = esc(t.summary) + (t.sprint ? ' · ' + esc(t.sprint) : out ? ' · nicht in einem aktiven Sprint' : '');
    const man = it.manual_link ? ` <button class="x" data-unlink="1" data-p="${it.project_id}" data-b="${esc(it.branch)}" title="Von Hand verknüpft. Verknüpfung lösen">×</button>` : '';
    return `<a class="${cls}" data-key="${esc(t.key)}" href="${esc(t.url)}" target="_blank" rel="noopener" title="${hint}${it.manual_link ? ' · von Hand verknüpft' : ''}"><span style="opacity:.75">${t.local ? 'Lokal' : 'Jira'}</span> ${esc(t.key)} · ${esc(t.status)}${out ? ' · außerhalb Sprint' : ''}${it.manual_link ? ' · manuell' : ''}</a>${man}`;
  }
  if (it.ticket_unknown) return `<span class="chip warn" title="Dieser Key wurde in Jira nicht gefunden">${esc(it.ticket_unknown)}?</span>${it.manual_link ? ` <button class="x" data-unlink="1" data-p="${it.project_id}" data-b="${esc(it.branch)}" title="Verknüpfung lösen">×</button>` : ''}`;
  if (it.no_ticket) return '<span class="chip warn">ohne Ticket</span>';
  return '';
}
function ageHtml(it) {
  const txt = it.age_days === 0 ? 'heute' : it.age_days === 1 ? 'seit gestern' : `seit ${it.age_days} Tagen`;
  return `<span class="age ${it.stale ? 'stale' : ''}">${txt}</span>`;
}
function row(it) {
  const r = reasonOf(it);
  const mr = it.iid ? `!${it.iid}` : '';
  const chips = [ticketChip(it), sonarChip(it) + trendBadge(it)];
  if (it.draft && it.kind !== 'branch') chips.push('<span class="chip draft">Draft</span>');
  if (it.by_agent) chips.push('<span class="chip agent" title="Commits vom Agenten (Konto oder Co-Authored-By)">Agent</span>');
  else if (it.kind === 'branch' && it.by_me) chips.push('<span class="chip" title="Mindestens ein Commit von dir">von mir</span>');
  const pipe = it.kind === 'branch' ? '' : `<span class="pd ${esc(it.pipeline)}" title="${esc(pipelineLabel[it.pipeline] || it.pipeline)}"></span>`;
  const acts = [];
  if (it.pipeline_url) acts.push(`<a href="${esc(it.pipeline_url)}" target="_blank" rel="noopener">Pipeline</a>`);
  if (it.sonar && it.sonar.url) {
    acts.push(`<a href="${esc(it.sonar.url)}" target="_blank" rel="noopener" title="Dashboard in Sonar">Sonar</a>`);
    if (SQ_HAS[it.sonar.status] && it.sonar.issues_url) acts.push(`<a href="${esc(it.sonar.issues_url)}" target="_blank" rel="noopener" title="Offene Findings in Sonar">Findings</a>`);
    if (SQ_HAS[it.sonar.status]) acts.push(`<button class="quiet-btn" ${sqRepAttrs(it)} title="Findings als Markdown-Report in die Zwischenablage (Pfade und Meldungen, kein Quelltext)">Report kopieren</button>`);
  }
  if (it.no_ticket) acts.push(`<button data-tk="1" data-p="${it.project_id}" data-i="${it.iid ?? ''}" data-b="${esc(it.branch)}" data-cu="${esc(it.create_url || '')}">Ticket anlegen</button>`);
  if (state.jira && state.jira.ok) acts.push(`<button class="quiet-btn" data-assign="1" data-p="${it.project_id}" data-b="${esc(it.branch)}" data-t="${esc(it.title)}" data-iid="${it.iid ?? ''}" title="Ticket von Hand zuordnen (oder die Zeile auf eine Story ziehen)">${it.ticket || it.ticket_unknown ? 'Ticket ändern' : 'Zuordnen'}</button>`);
  if (it.kind === 'branch' && it.create_mr_url) acts.push(`<a class="btn" href="${esc(it.create_mr_url)}" target="_blank" rel="noopener" title="In GitLab einen Merge Request für diesen Branch anlegen">MR erstellen</a>`);
  acts.push(`<a class="btn" href="${esc(it.url)}" target="_blank" rel="noopener" title="${it.kind === 'branch' ? 'Branch in GitLab' : 'Merge Request in GitLab'}">${it.kind === 'branch' ? 'Branch öffnen' : 'MR öffnen'}</a>`);
  const parts = [];
  if (it.iid) parts.push(`<button data-mrtry="${esc(JSON.stringify({ host: it.host || 'gitlab', project_id: it.project_id, iid: it.iid }))}" title="Prompts, git-Befehle und Review-Umgebung für diesen MR">Ausprobieren …</button>`);
  if (it.no_ticket && F().ideas) parts.push(`<button data-act="idea" data-text="${esc('Branch ' + it.branch + ': ' + it.title)}">In Ideenbox parken</button>`);
  return `<div class="item" draggable="true" data-dp="${it.project_id}" data-db="${esc(it.branch)}">
    <div class="rail ${railOf(it)}"></div>
    <div>
      <div class="l1">${pipe}<a class="t" href="${esc(it.url)}" target="_blank" rel="noopener">${esc(it.title)}</a>${chips.join('')}</div>
      <div class="l2"><span class="reason ${r.c}">${esc(r.t)}</span><span class="src gl" title="GitLab">${it.kind === 'branch' ? 'Branch' : 'MR ' + mr}</span><span>${esc(it.project)}</span><code title="${esc(it.branch)}">${esc(it.branch)}</code>${ageHtml(it)}</div>
    </div>
    <div class="acts">${acts.join('')}</div>
    ${parts.length ? `<div class="l3" data-p="${it.project_id}" data-i="${it.iid ?? ''}">${parts.join('')}</div>` : ''}
  </div>`;
}
function matches(it) {
  if (filt.proj && it.project !== filt.proj) return false;
  if (filt.agent && !it.by_agent) return false;
  if (filt.notk && !it.no_ticket) return false;
  if (filt.stale && !it.stale) return false;
  if (filt.q) {
    const hay = [it.title, it.branch, it.project, it.ticket && it.ticket.key, it.ticket && it.ticket.summary, it.ticket_unknown].join(' ').toLowerCase();
    if (!filt.q.toLowerCase().split(/\s+/).every(w => hay.includes(w))) return false;
  }
  return true;
}
function group(title, items, empty, hint) {
  const body = items.length ? `<div class="list">${items.map(row).join('')}</div>` : `<div class="list"><div class="empty">${esc(empty)}</div></div>`;
  return `<div class="group"><div class="secthead"><h2>${esc(title)}</h2><span class="count">${items.length}</span>${hint ? `<span class="right">${hint}</span>` : ''}</div>${body}</div>`;
}
// -- Tasks: Tickets, die zusammengehören (0.30). Bug + Begleitticket: der Bug ist der Task.
const typeChip = t => !t ? '' : `<span class="chip ${/^(bug|fehler|defect|defekt|störung|incident)$/i.test(t) ? 'bug' : 'tk'}" title="Vorgangstyp in Jira">${esc(t)}</span>`;
function compList(s) {
  const cs = s.companions || [];
  const btn = s.local ? '' : `<button class="quiet-btn small" data-grp="${esc(s.key)}" title="Andere Tickets in Arbeit diesem Task zuordnen oder ihn eigenständig machen">${cs.length ? 'Gruppe' : 'Gruppieren …'}</button>`;
  if (!cs.length) return btn ? `<div class="comps">${btn}</div>` : '';
  return `<div class="comps">${cs.map(c => `<span class="comp" title="${esc(c.summary)}${c.why ? ' · ' + esc(c.why) : ''}">+ ${c.url ? `<a href="${esc(c.url)}" target="_blank" rel="noopener">${esc(c.key)}</a>` : esc(c.key)} ${typeChip(c.type)}<span class="quiet">${esc(short(c.summary || '', 40))}</span></span>`).join('')}${btn}</div>`;
}
function openGroup(key) {
  const st = (state.jira && state.jira.stories) || [];
  const head = st.find(s => s.key === key) || st.find(s => (s.companions || []).some(c => c.key === key));
  const tickets = st.flatMap(s => [s, ...(s.companions || [])]).filter(t => !t.local);
  const me = tickets.find(t => t.key === key) || { key, summary: '' };
  const isComp = head && head.key !== key;
  $('wsDlgBody').innerHTML = `<div style="display:grid;gap:10px"><div><strong>${esc(key)} gruppieren</strong><div class="quiet small">${esc(me.summary || '')}</div></div>
    <div class="small quiet">Ein Task ist, woran du arbeitest. Gehören mehrere Tickets in Arbeit zusammen (Bug und Begleitticket, Story und Unteraufgaben), erscheinen sie als ein Task mit allen MRs und Branches, zählen einmal zum Limit, und ein Agent bekommt den Auftrag des Tasks. tinyops gruppiert verknüpfte Tickets von selbst; hier entscheidest du von Hand.</div>
    <div class="field"><label for="grpHead">${esc(key)} gehört zu</label><select id="grpHead" class="full"><option value="">– niemandem: eigener Task –</option>
      ${tickets.filter(t => t.key !== key && !(head && head.key === key && (head.companions || []).some(c => c.key === t.key) && false)).map(t => `<option value="${esc(t.key)}" ${isComp && head.key === t.key ? 'selected' : ''}>${esc(t.key)} ${esc(t.type ? '(' + t.type + ') ' : '')}${esc(short(t.summary || '', 50))}</option>`).join('')}</select></div>
    ${head && !isComp && (head.companions || []).length ? `<div class="small">Zu ${esc(key)} gehören: ${head.companions.map(c => `<b>${esc(c.key)}</b> <span class="quiet">(${esc(c.why || '')})</span>`).join(', ')}. Ein Begleitticket lösen: dort «Gruppe» wählen.</div>` : ''}
    <div class="row"><button class="primary" id="grpSave">Speichern</button><button id="grpAuto" class="quiet-btn" title="Von Hand gesetzte Zuordnung entfernen, tinyops erkennt wieder selbst">Automatisch</button><button id="grpNo">Abbrechen</button></div></div>`;
  $('wsDlg').showModal();
  $('grpNo').onclick = () => $('wsDlg').close();
  const go = async body => { try { await post('/api/groups', body); $('wsDlg').close(); toast('Gespeichert, wird neu gruppiert'); await api('POST', '/api/refresh', {}); await load(); } catch (e) { toast(e.message); } };
  $('grpSave').onclick = () => go({ key, head: $('grpHead').value });
  $('grpAuto').onclick = () => go({ key, reset: true });
}
document.addEventListener('click', ev => { const g = ev.target.closest && ev.target.closest('[data-grp]'); if (g) { ev.stopPropagation(); openGroup(g.dataset.grp); } }, true);
function storiesTile() {
  const j = state.jira;
  if (!j) return null;
  if (j.loading) return { title: 'Tasks in Arbeit', count: '', hint: '', body: '<div class="empty busy">lädt …</div>' };
  if (!j.ok) return { title: 'Tasks in Arbeit', count: '', hint: 'Jira antwortet nicht', body: '<div class="empty">Jira ist eingerichtet, antwortet aber nicht. Details im Banner und unter Einstellungen.</div>' };
  const slots = [];
  const counted = j.stories.filter(s => s.counts !== false), rest = j.stories.filter(s => s.counts === false);
  const ordered = counted.concat(rest);
  const n = Math.max(j.limit, counted.length) + rest.length;
  let ci = 0;
  for (let i = 0; i < n; i++) {
    const s = ordered[i];
    if (!s) { slots.push('<div class="slot free"><strong>Platz frei</strong><span>Du kannst einen neuen Task beginnen.</span></div>'); continue; }
    const over = s.counts !== false && ci++ >= j.limit;
    const mrs = s.items.map(x => `<a class="mrchip" href="${esc(x.url)}" target="_blank" rel="noopener"><span class="pd ${esc(x.pipeline)}"></span><b>${x.iid ? 'MR' : 'Branch'}</b> ${x.iid ? '!' + esc(x.iid) : esc(x.branch)}${x.sonar === 'ERROR' ? ' <span class="sqdot bad" title="Quality Gate rot">●</span>' : x.sonar === 'OK' ? ' <span class="sqdot ok" title="Quality Gate grün">●</span>' : ''}${x.manual ? ` <button class="x" data-unlink="1" data-p="${x.project_id}" data-b="${esc(x.branch)}" title="Von Hand verknüpft. Verknüpfung lösen">×</button>` : ''}</a>${sqLinks(x)}`).join('');
    slots.push(`<div class="slot ${over ? 'over' : ''}" data-skey="${esc(s.key)}" draggable="true" title="Branch oder MR hierher ziehen, um ihn mit ${esc(s.key)} zu verknüpfen">
      <div class="top"><span class="key">${esc(s.key)}</span>${typeChip(s.type)}${s.local ? '<span class="chip">Lokal</span>' : `<span class="chip">${esc(s.status)}</span>`}${s.counts === false ? '<span class="chip" title="Dieser Typ zählt nicht zum Limit (Einstellungen → Jira)">zählt nicht</span>' : ''}<span class="chip tk" title="Stufe im Board">${esc(STAGE_LABEL[s.stage] || '')}</span>${s.sprint ? `<span class="chip tk" title="Aktiver Sprint">${esc(s.sprint)}</span>` : ''}</div>
      ${s.url ? `<a class="sum" href="${esc(s.url)}" target="_blank" rel="noopener">${esc(s.summary)}</a>` : `<span class="sum">${esc(s.summary)}</span>`}
      ${compList(s)}
      <div class="links">${mrs}${s.no_mr ? '<span class="nolink">Noch kein MR oder Branch mit diesem Key</span>' : ''}</div>
      ${agentRow(s.key, s.key, s.summary, s.url, s.items)}
    </div>`);
  }
  const sp = (j.sprints || []).map(s => `${esc(s.name)}${s.days_left !== null && s.days_left !== undefined ? (s.days_left >= 0 ? ` · noch ${s.days_left} Tage` : ' · überfällig') : ''}`).join(', ');
  return { title: 'Tasks in Arbeit', count: `${j.count} von ${j.limit}`, bad: j.over, hint: (j.only_active ? 'nur aktive Sprints' : 'alle Sprints') + (sp ? ': ' + sp : '') + (j.tickets > j.stories.length ? ` · ${j.tickets} Tickets` : ''),
    body: `<div class="slots">${slots.join('')}</div>${j.over ? `<div class="overnote">${j.count} Tasks in Arbeit, Limit ${j.limit}. Einen abschließen oder zurücksetzen, bevor etwas Neues beginnt.</div>` : ''}` };
}
const LOGO_MISS = new Set();      // fehlt ein Logo, wird es nicht bei jedem Neuzeichnen wieder angefragt
const logo = n => LOGO_MISS.has(n) ? '' : `<img class="logo" src="/logo/${n === 'gl' ? 'gitlab' : n}" alt="" onerror="LOGO_MISS.add('${n}');this.remove()">`;
let openTiles = LS.get('open', []);
function applyLayout(l) {
  document.body.classList.toggle('layout-list', l === 'list');
  document.querySelectorAll('#layoutSeg button').forEach(b => b.classList.toggle('on', b.dataset.layout === l));
}
applyLayout(LS.get('layout', 'tiles'));
$('layoutSeg').addEventListener('click', ev => { const b = ev.target.closest('button[data-layout]'); if (b) { LS.set('layout', b.dataset.layout); applyLayout(b.dataset.layout); } });
function tileHtml(id, t, open, mini) {
  const src = id === 'stories' ? 'jira' : (id === 'pools' || id === 'ai' || id === 'usage') ? 'local' : 'gl';
  const body = t.body;
  return `<section class="tile t-${src} ${open ? 'open' : ''} ${mini ? 'mini' : ''}" data-tile="${id}">
    <div class="thead" data-toggle="${id}" role="button" tabindex="0" aria-expanded="${open}" title="${open ? 'Verkleinern' : 'Auf halbe Bildschirmbreite öffnen'}">
      <h2>${esc(t.title)}</h2><span class="src ${src}">${logo(src)}${src === 'jira' ? 'Jira' : src === 'local' ? 'Lokal' : 'GitLab'}</span><span class="count" ${t.bad ? 'style="color:var(--bad)"' : ''}>${esc(t.count)}</span>
      <span class="thint">${t.hint || ''}</span><button class="expand quiet-btn" tabindex="-1" aria-hidden="true">${open ? '⤡' : '⤢'}</button></div>
    <div class="tbody">${body}</div></section>`;
}
function listBody(items, empty) {
  if (items.length) return `<div class="list">${items.map(row).join('')}</div>`;
  if (state.sync && state.sync.running) return '<div class="empty busy">lädt …</div>';
  return `<div class="empty">${esc(empty)}</div>`;
}
// 0.35.1: Zugänge auf einen Blick, oben in den Einstellungen, zugeklappt
const TOKS = [['gitlab_token', 'GitLab', 'gitlab'], ['jira_token', 'Jira', 'jira'], ['jira_password', 'Jira (Passwort)', 'jira'], ['github_token', 'GitHub', 'github'],
  ['sonar_token', 'Sonar', 'sonar'], ['helpdesk_token', 'Helpdesk', 'helpdesk'], ['helpdesk_password', 'Helpdesk (Passwort)', 'helpdesk'], ['llm_key', 'KI-Entwurf', 'llm'], ['bcs_token', 'BCS', 'time']];
function tokBox(S) {
  const rows = TOKS.filter(([k]) => S.secrets[k]).map(([k, label, sec]) => ({ k, label, sec, ...S.secrets[k] }));
  const on = rows.filter(r => r.set || r.error), off = rows.filter(r => !r.set && !r.error);
  const errs = ((state.sync && state.sync.steps) || []).filter(x => x.status === 'err');
  const src = s => /^Datei/.test(s || '') ? 'Datei' : (s || '');
  const chip = r => `<span class="tk ${r.error ? 'bad' : r.set ? '' : 'off'}" title="${esc(r.error || src(r.source))}"><i></i>${esc(r.label)}</span>`;
  const sum = `<b>Zugänge</b> ${on.map(chip).join('')}${on.length ? '' : '<span class="quiet small">noch keine gespeichert</span>'}
    ${errs.length ? `<span class="tk bad"><i></i>letzter Abgleich: ${errs.length} Fehler</span>` : ''}<span class="quiet small">${esc(S.storage.keyring ? 'im Schlüsselbund' : 'in einer Datei')}</span>`;
  const tr = r => `<tr><td>${esc(r.label)}</td><td>${r.error ? `<span class="bad">${esc(r.error)}</span>` : r.set ? 'gespeichert' : '<span class="quiet">nicht gesetzt</span>'}</td>
    <td class="quiet">${esc(src(r.source))}</td><td><button data-tokgo="${r.sec}">${r.set ? 'Ändern' : 'Eintragen'}</button></td></tr>`;
  return `<details class="tokbox" id="tokBox" ${LS.get('tokOpen', false) ? 'open' : ''}><summary>${sum}</summary>
    <table>${on.map(tr).join('')}${off.map(tr).join('')}</table>
    ${errs.length ? `<div class="tkfoot small"><b>Letzter Abgleich:</b> ${errs.map(x => esc(x.title) + (x.detail ? ': ' + esc(x.detail) : '')).join(' · ')}</div>` : ''}
    <div class="tkfoot small quiet">Tokens werden nie angezeigt, nur ob sie da sind und woher sie kommen. Microsoft 365 meldet sich ohne Token an (Abschnitt Microsoft 365).</div></details>`;
}
// Sync-Anzeige: was wird gerade abgeglichen, danach eine ruhige Zusammenfassung
let syncOpen = LS.get('syncOpen', false);
function renderSync() {
  const el = $('syncbar'), sy = state.sync;
  if (!sy || !sy.total || !state.configured) { el.hidden = true; return; }
  const errs = sy.steps.filter(x => x.status === 'err').length;
  const cur = sy.steps.filter(x => x.status === 'run').map(x => x.title);
  const pct = Math.round(100 * sy.done / sy.total);
  const when = sy.finished ? new Date(sy.finished * 1000).toLocaleTimeString('de-CH', { hour: '2-digit', minute: '2-digit', second: '2-digit' }) : '';
  const head = sy.running
    ? `<span class="sy-dot run"></span><span><b>Synchronisiere</b> ${sy.done} von ${sy.total}${cur.length ? ': ' + esc(cur.join(', ')) : ''}</span><span class="sy-prog"><i style="width:${pct}%"></i></span>`
    : `<span class="sy-dot ${errs ? 'err' : 'ok'}"></span><span>${errs ? `Synchronisiert mit ${errs} Fehler${errs > 1 ? 'n' : ''}` : 'Synchronisiert'} um ${when} in ${sy.secs} s</span>`;
  const steps = sy.steps.map(x => `<span class="sy-step ${x.status}" title="${esc(x.detail)}"><span class="sy-dot ${x.status}"></span>${esc(x.title)}${x.detail && x.status !== 'run' ? ' · ' + esc(x.detail) : ''}${x.secs != null ? ` (${x.secs} s)` : ''}</span>`).join('');
  const open = sy.running || syncOpen;
  el.hidden = false;
  el.innerHTML = `<details ${open ? 'open' : ''}><summary>${head}</summary><div class="sy-steps">${steps}</div></details>`;
  const d = el.querySelector('details');
  d.addEventListener('toggle', () => { if (!sy.running) { syncOpen = d.open; LS.set('syncOpen', syncOpen); } });
}
function renderLeft() {
  let banners = '';
  if (!state.configured) {
    banners += `<div class="banner warn"><strong>Noch nicht verbunden.</strong> ${state.problems.map(esc).join(' ')}
      <div style="margin-top:8px"><button class="primary" onclick="setView('settings')">Einstellungen öffnen</button></div></div>`;
  }
  if (state.errors.length) banners += `<div class="banner bad">${state.errors.map(esc).join('<br>')}</div>`;
  $('banners').innerHTML = banners;
  renderSync();
  const tb = $('toolbar');
  if (!state.configured) { $('board').innerHTML = ''; tb.hidden = true; return; }

  const all = state.review.concat(state.assigned, state.mine);
  const projs = [...new Set(all.map(i => i.project))].sort();
  const sel = $('fproj');
  if (filt.proj && !projs.includes(filt.proj)) filt.proj = '';
  sel.innerHTML = '<option value="">Alle Projekte</option>' + projs.map(p => `<option ${p === filt.proj ? 'selected' : ''}>${esc(p)}</option>`).join('');
  $('fagent').checked = filt.agent; $('fnotk').checked = filt.notk; $('fstale').checked = filt.stale;
  tb.hidden = false;
  $('fnotk').parentElement.hidden = !(state.jira && state.jira.ok);

  const mine = state.mine;
  const needs = state.review.concat(state.assigned, mine.filter(i => i.kind === 'mr' && (i.pipeline === 'failed' || (i.sonar && i.sonar.status === 'ERROR') || (i.pipeline === 'success' && !i.draft)))).filter(matches);
  const needSet = new Set(needs);
  const mrs = mine.filter(i => i.kind === 'mr' && matches(i) && !needSet.has(i));
  const branches = mine.filter(i => i.kind === 'branch' && matches(i));
  const shown = needs.length + mrs.length + branches.length;
  $('fcount').textContent = shown === all.length ? `${all.length} Einträge` : `${shown} von ${all.length}`;

  const tiles = {};
  const st = storiesTile();
  if (st) tiles.stories = st;
  tiles.need = { title: 'Braucht dich', count: needs.length, body: listBody(needs, 'Nichts wartet auf dich.') };
  tiles.mrs = { title: 'Meine MRs', count: mrs.length, body: listBody(mrs, 'Keine weiteren offenen MRs.') };
  tiles.br = { title: 'Offene Branches', count: branches.length, body: listBody(branches, 'Keine offenen Branches mit Commits von dir oder deinem Agenten.'),
    hint: state.ignore_patterns && state.ignore_patterns.length ? `ignoriert: ${state.ignore_patterns.map(esc).join(', ')}` : '' };
  if (F().ai) tiles.ai = { title: 'KI-Konten', src: 'local', count: (state.ai || []).length, hint: 'Stand trägst du ein, der Anbieter liefert ihn nicht', body: aiBody() };
  const ids = Object.keys(tiles);
  openTiles = openTiles.filter(id => ids.includes(id)).slice(-2);
  const open = ids.filter(id => openTiles.includes(id));
  const board = $('board');
  const keep = [...document.querySelectorAll('[data-aiin]')].map(e => ({ sel: `[data-aiin="${e.dataset.aiin}"]`, v: e.value, f: e === document.activeElement }));
  board.className = 'board o' + open.length;
  if (open.length === 2) {
    const closed = ids.filter(id => !open.includes(id));
    board.innerHTML = `<div class="strip">${closed.map(id => tileHtml(id, tiles[id], false, true)).join('')}</div>` + open.map(id => tileHtml(id, tiles[id], true, false)).join('');
  } else {
    board.innerHTML = ids.map(id => tileHtml(id, tiles[id], open.includes(id), false)).join('');
  }
  keep.forEach(k => { const e = document.querySelector(k.sel); if (e && k.v) { e.value = k.v; if (k.f) e.focus(); } });
}
function renderIdeas() {
  const ideas = state.ideas;
  const open = ideas.filter(i => ['neu', 'geparkt'].includes(i.status) && !i.expired).length;
  document.getElementById('ideaCount').textContent = `${open}/${state.idea_cap}`;
  const bd = $('ideaBadge'); bd.textContent = open; bd.hidden = !open;
  const list = ideas.filter(i => !['verworfen', 'erledigt'].includes(i.status));
  document.getElementById('ideas').innerHTML = list.length ? list.map(i => `
    <div class="idea ${i.expired ? 'expired' : ''}" data-id="${i.id}">
      <div>${esc(i.text)}</div>
      <div class="meta">${i.expired ? 'verfallen · ' : ''}${esc(i.status)} · ${i.age_days} Tage${i.assessment ? ' · ' + esc(assessLine(i.assessment)) : ''}</div>
      <div class="row" style="margin-top:4px">
        <button data-iassess="${i.id}" title="Kategorie, Nutzen, Aufwand, Dubletten">${i.assessment ? 'Neu bewerten' : 'Bewerten'}</button><button data-iticket="${i.id}">Ticket daraus</button>
        ${i.status === 'neu' && !i.expired ? '<button data-ia="park">Parken</button>' : ''}
        <button data-ia="done">Erledigt</button>
        <button data-ia="drop">Verwerfen</button>
      </div>
    </div>`).join('') : '<div class="empty">Leer. Das ist ein gutes Zeichen.</div>';
}
function renderHeader() {
  const gl = $('pGl'), ji = $('pJi');
  gl.style.display = ''; ji.style.display = '';
  const dot = (cls, text, title) => `<span class="dot ${cls}"></span>${text}`;
  if (!state.configured) { gl.innerHTML = dot('off', 'GitLab'); gl.title = 'Nicht verbunden'; }
  else if (state.errors.some(e => !e.startsWith('Jira'))) { gl.innerHTML = dot('bad', 'GitLab'); gl.title = 'Fehler, Details im Banner'; }
  else { gl.innerHTML = dot('ok', 'GitLab'); gl.title = 'Verbunden'; }
  if (state.jira && state.jira.ok) { ji.innerHTML = dot('ok', 'Jira'); ji.title = 'Verbunden'; }
  else if (state.jira) { ji.innerHTML = dot('bad', 'Jira'); ji.title = state.jira.error; }
  else { ji.innerHTML = dot('off', 'Jira'); ji.title = 'Nicht eingerichtet'; }
  $('demo').style.display = state.demo ? '' : 'none';
  $('ver').textContent = state.version ? 'v' + state.version : '';
  const u = state.update;    // Hinweis vom Starter (start.py): einmal zeigen
  const ub = $('updBanner');
  ub.hidden = !u;
  if (u) ub.innerHTML = `<div class="banner ${u.ok ? '' : 'warn'} upd">${u.ok
      ? `<b>Aktualisiert auf ${esc(u.to)}</b> <span class="quiet">(vorher ${esc(u.from)})</span>${u.qa_new ? ` · ${u.qa_new === 1 ? '1 neuer Prüfpunkt' : u.qa_new + ' neue Prüfpunkte'}` : ''} <button class="quiet-btn" data-upd="qa">${u.qa_new ? 'Jetzt prüfen' : 'Prüfliste'}</button><button class="quiet-btn" data-upd="log">Was ist neu?</button>`
      : `<b>Update nicht übernommen.</b> ${esc(u.message)}`}<button class="x" data-upd="seen" aria-label="Hinweis schliessen">×</button></div>`;
  const syncing = state.sync && state.sync.running;
  $('fetched').textContent = syncing ? 'synchronisiert …' : 'Stand ' + new Date(state.fetched * 1000).toLocaleTimeString('de-CH', { hour: '2-digit', minute: '2-digit' });
  $('refresh').disabled = !!syncing;
}
function renderAside() {
  const f = F();
  $('ideasBox').hidden = !f.ideas;
  $('ideaBtn').hidden = !f.ideas;
  const hasUsage = !!(state.usage_providers || []).length;
  $('usageBox').hidden = !hasUsage;
  renderUsageBox();
  const on = !!f.ideas;
  $('aside').hidden = !on;
  document.querySelector('.bn[data-view=ideas]').hidden = !f.ideas;
  $('viewOverview').classList.toggle('withaside', on);
}
let firstLoad = true, pollT = null;
// 0.35: Verbindung weg (Neustart, Update, Rechner schlief): ein Hinweis oben, selbst wieder verbinden statt Fehlermeldungen
let OFFLINE = false, offT = null, offN = 0;
function setOffline(on) {
  OFFLINE = on; clearTimeout(offT);
  let b = $('offline');
  if (!on) { offN = 0; if (b) b.remove(); return; }
  if (!b) { b = document.createElement('div'); b.id = 'offline'; b.className = 'offline'; b.setAttribute('role', 'status'); document.body.appendChild(b); }
  const wait = Math.min(30, [2, 3, 5, 10, 20][offN] || 30); offN++;
  b.innerHTML = `Keine Verbindung zu tinyops. Neuer Versuch in ${wait} s. <button id="offRetry">Jetzt verbinden</button>`;
  $('offRetry').onclick = () => { clearTimeout(offT); load(); };
  offT = setTimeout(load, wait * 1000);
}
async function load() {
  clearTimeout(pollT);
  try {
    const prevSes = state && state.focus && state.focus.session ? state.focus.session.id : null;
    state = await api('GET', '/api/overview');
    const le = state.focus && !state.focus.session && state.focus.last_ended;
    if (prevSes && le && le.id === prevSes && FOCUS_AUTO[le.result]) {      // die Sitzung hat sich selbst beendet: sagen, warum
      FM_OPEN = false; document.title = 'tinyops';
      toast(`Fokus-Sitzung beendet (${le.minutes} min): ${FOCUS_AUTO[le.result]}`);
    }
    renderHeader(); renderLeft(); renderAside(); renderBoard(); renderFocus(); loadUsage(false); wsBadge();
    if (view === 'time') loadTime();
    if (state.features.ideas) renderIdeas();
    if (firstLoad) { firstLoad = false; if (!state.configured && !state.demo) setView('settings'); }
  } catch (e) { if (e.offline) { setOffline(true); return; } toast(e.message); }
  // Solange synchronisiert wird, schnell nachfragen: Teilergebnisse erscheinen, ohne dass man warten muss
  if (state && state.sync && state.sync.running) pollT = setTimeout(load, 900);
}
// Kacheln öffnen (höchstens zwei, jede nimmt die halbe Breite)
function toggleTile(id) {
  if (matchMedia('(max-width: 960px)').matches) return;
  openTiles = openTiles.includes(id) ? openTiles.filter(x => x !== id) : openTiles.concat(id).slice(-2);
  LS.set('open', openTiles); renderLeft();
}
$('board').addEventListener('click', ev => { const h = ev.target.closest('[data-toggle]'); if (h && !ev.target.closest('a')) toggleTile(h.dataset.toggle); });
$('board').addEventListener('keydown', ev => { const h = ev.target.closest('[data-toggle]'); if (h && (ev.key === 'Enter' || ev.key === ' ')) { ev.preventDefault(); toggleTile(h.dataset.toggle); } });
// Filter
function applyFilters() { renderLeft(); }
$('fq').addEventListener('input', ev => { filt.q = ev.target.value; applyFilters(); });
$('fproj').addEventListener('change', ev => { filt.proj = ev.target.value; LS.set('proj', filt.proj); applyFilters(); });
[['fagent', 'agent'], ['fnotk', 'notk'], ['fstale', 'stale']].forEach(([id, k]) =>
  $(id).addEventListener('change', ev => { filt[k] = ev.target.checked; LS.set(k, filt[k]); applyFilters(); }));
document.addEventListener('keydown', ev => {
  if (ev.key === '/' && !/INPUT|TEXTAREA|SELECT/.test(document.activeElement.tagName) && view === 'overview') { ev.preventDefault(); $('fq').focus(); }
});
// Aktionen auf Karten
document.getElementById('board').addEventListener('click', async ev => {
  const btn = ev.target.closest('button[data-act]');
  if (!btn) return;
  if (btn.dataset.act === 'idea') {
    try { await api('POST', '/api/ideas', { text: btn.dataset.text }); toast('In der Ideenbox'); await load(); } catch (e) { toast(e.message); }
    return;
  }
});
// ---------------------------------------------------------------- Ticket anlegen (inline)
let TK = null;   // {item, meta, project, types}
function tkMsg(html, cls) { $('tkMsg').innerHTML = html ? `<div class="banner ${cls || 'warn'}" style="margin:10px 0 0">${html}</div>` : ''; }
function tkTypes(types, sel) { return types.map(t => `<option ${t === sel ? 'selected' : ''}>${esc(t)}</option>`).join(''); }
async function openTicket(btn, ideaId, hdKey) {
  const item = hdKey ? { hd_key: hdKey } : ideaId ? { idea_id: ideaId } : { project_id: +btn.dataset.p, iid: btn.dataset.i ? +btn.dataset.i : null, branch: btn.dataset.b, create_url: btn.dataset.cu };
  $('tkSrc').innerHTML = hdKey ? `<span class="src hd">${esc(hdName())}</span> <code>${esc(hdKey)}</code>` : ideaId ? `<span class="src tiny">Idee #${ideaId}</span>` : `<span class="src gl">${item.iid ? 'MR !' + item.iid : 'Branch'}</span> <code>${esc(item.branch)}</code>`;
  $('tkBody').innerHTML = '<div class="quiet">Lade Entwurf …</div>';
  if (!$('tkDlg').open) $('tkDlg').showModal();
  try {
    const r = await api('POST', '/api/ticket/draft', item);
    TK = { item, meta: r.meta, project: r.project, types: r.issue_types };
    renderTicket(r);
  } catch (e) { $('tkBody').innerHTML = `<div class="banner bad">${esc(e.message)}</div>`; }
}
function renderTicket(r) {
  const m = r.meta, d = r.draft;
  const projects = m.projects.length ? m.projects : [r.project || ''];
  $('tkBody').innerHTML = `
    <div class="grid2">
      <div class="field"><label for="tk-proj">Jira-Projekt</label><select class="full" id="tk-proj">${projects.map(p => `<option ${p === r.project ? 'selected' : ''}>${esc(p)}</option>`).join('')}</select></div>
      <div class="field"><label for="tk-type">Vorgangstyp</label><select class="full" id="tk-type">${tkTypes(r.issue_types, d.issue_type)}</select></div>
    </div>
    <div class="field"><label for="tk-sum">Titel</label><input type="text" id="tk-sum" value="${esc(d.summary)}" maxlength="255"></div>
    <div class="field"><label for="tk-desc">Beschreibung <span class="quiet small" style="font-weight:400">(Jira-Wiki-Format)</span></label>
      <textarea class="full" id="tk-desc" rows="12" spellcheck="false">${esc(d.description)}</textarea></div>
    ${r.linked ? `<div class="banner warn" style="margin:0 0 10px">Aus diesem Helpdesk-Ticket hast du schon <b>${esc(r.linked)}</b> angelegt.</div>` : ''}
    <div class="small quiet" id="tkSource">Entwurf: ${r.source === 'helpdesk' ? 'Vorlage aus dem Helpdesk-Ticket (Link, Problem, Kriterien), bitte prüfen' : r.source === 'ki' ? 'vom lokalen Modell, bitte prüfen' : TK.item.idea_id ? 'Vorlage aus der Idee (Story, Akzeptanzkriterien, Risiken, Tests, Abhängigkeiten)' : 'Vorlage aus Branch, MR und Commit-Titeln'}</div>
    ${TK.item.idea_id ? `<label class="check" style="margin-top:8px"><input type="checkbox" id="tk-cl" checked><span>Akzeptanzkriterien als Teilschritte übernehmen</span></label>` : ''}
    <div id="tkMsg">${r.warning ? `<div class="banner warn" style="margin:10px 0 0">${esc(r.warning)}</div>` : ''}</div>
    ${m.llm ? `<div class="row" style="margin-top:10px"><input type="text" id="tk-hint" style="flex:1;min-width:200px" placeholder="Hinweis an das Modell (optional), z. B. «Fokus auf Tests»">
      <button id="tk-ai">Entwurf mit KI</button></div><div class="quiet small">${TK.item.idea_id ? `Gesendet wird der Text der Idee und ihre Bewertung an ${esc(m.llm_label || 'das lokale Modell')}.` : `Gesendet werden Titel, Branch, MR-Beschreibung und Commit-Titel an ${esc(m.llm_label || 'das lokale Modell')}. Keine Diffs, kein Code.`}</div>` : ''}
    <div class="row" style="margin-top:14px">
      ${m.can_create ? '<button class="primary" id="tk-create">In Jira anlegen</button>'
        : TK.item.idea_id || TK.item.hd_key ? '' : `<a class="btn" id="tk-open" href="${esc(TK.item.create_url || '#')}" target="_blank" rel="noopener">In Jira öffnen</a>`}
      ${TK.item.idea_id ? `<select id="tk-pool" aria-label="Kategorie">${poolOptions(null, true)}</select><button id="tk-tiny" ${m.can_create ? '' : 'class="primary"'} title="Lokale Aufgabe in tinyops statt Jira">Als tiny-Ticket</button>` : ''}
      <button id="tk-copy">Text kopieren</button>
    </div>
    ${m.can_create ? '' : '<div class="quiet small" style="margin-top:6px">Direktes Anlegen ist aus. Einschalten: Einstellungen → Jira → «Tickets aus dem Panel anlegen». Bis dahin: Text kopieren und in Jira einfügen.</div>'}`;
  $('tk-proj').onchange = async () => {
    try {
      const x = await api('POST', '/api/ticket/draft', { ...TK.item, project: $('tk-proj').value });
      TK.types = x.issue_types; $('tk-type').innerHTML = tkTypes(x.issue_types, $('tk-type').value);
    } catch (e) { tkMsg(esc(e.message), 'bad'); }
  };
  $('tk-copy').onclick = () => copyText(`${$('tk-sum').value}\n\n${$('tk-desc').value}`, 'Ticket-Text');
  if ($('tk-tiny')) $('tk-tiny').onclick = () => busy($('tk-tiny'), 'Lege an …', async () => {
    try {
      const pool = $('tk-pool').value;
      const x = await post(`/api/ideas/${TK.item.idea_id}/tiny`, { summary: $('tk-sum').value, description: $('tk-desc').value, pool_id: pool ? +pool : null, checklist: $('tk-cl').checked });
      $('tkBody').innerHTML = `<div class="banner" style="background:var(--ok-bg);color:var(--ok)"><strong>Angelegt:</strong> ${esc(x.key)}${x.checks ? ` mit ${x.checks} Teilschritten` : ''}${pool ? '' : ' (im Ideenpool, bis du eine Kategorie wählst)'}</div><div class="row" style="margin-top:10px"><button class="primary" id="tk-done">Fertig</button></div>`;
      $('tk-done').onclick = () => $('tkDlg').close();
      load();
    } catch (e) { tkMsg(esc(e.message), 'bad'); }
  });
  if ($('tk-ai')) $('tk-ai').onclick = () => busy($('tk-ai'), 'Das Modell schreibt …', async () => {
    try {
      const x = await api('POST', '/api/ticket/draft', { ...TK.item, project: $('tk-proj').value, use_llm: true, hint: $('tk-hint').value });
      if ((($('tk-desc').value.trim() && !confirm('Titel und Beschreibung durch den KI-Entwurf ersetzen?'))) && x.source === 'ki') return;
      $('tk-sum').value = x.draft.summary; $('tk-desc').value = x.draft.description; $('tk-type').innerHTML = tkTypes(x.issue_types, x.draft.issue_type);
      $('tkSource').textContent = x.source === 'ki' ? 'Entwurf: vom lokalen Modell, bitte prüfen' : 'Entwurf: Vorlage';
      tkMsg(x.warning ? esc(x.warning) : '');
    } catch (e) { tkMsg(esc(e.message), 'bad'); }
  });
  if ($('tk-create')) $('tk-create').onclick = async () => {
    const body = { project: $('tk-proj').value, issue_type: $('tk-type').value, summary: $('tk-sum').value, description: $('tk-desc').value };
    if (TK.item.idea_id) { body.idea_id = TK.item.idea_id; body.checklist = $('tk-cl').checked; }
    if (TK.item.hd_key) body.hd_key = TK.item.hd_key;
    if (!body.summary.trim()) { tkMsg('Der Titel fehlt.', 'bad'); return; }
    if (!confirm(`In Jira ${body.project} als «${body.issue_type}» anlegen?\n\n${body.summary}`)) return;
    await busy($('tk-create'), 'Lege an …', async () => {
      let x = null;
      try {
        x = await api('POST', '/api/ticket/create', body);
      } catch (e) {
        const dup = e.data && e.data.duplicate;
        if (!dup) { tkMsg(esc(e.message), 'bad'); return; }
        // Doppelt-Schutz: dasselbe Ticket in den letzten 10 min. Nur auf ausdrücklichen Wunsch ein zweites.
        if (!confirm(`${e.message}\n\nTrotzdem ein zweites Ticket anlegen?`)) {
          tkMsg(`${esc(e.message)} ${e.data.url ? `<a href="${esc(e.data.url)}" target="_blank" rel="noopener">${esc(dup)} öffnen</a>` : ''}`, 'bad');
          return;
        }
        try { x = await api('POST', '/api/ticket/create', { ...body, force: true }); } catch (e2) { tkMsg(esc(e2.message), 'bad'); return; }
      }
      $('tkBody').innerHTML = `<div class="banner" style="background:var(--ok-bg);color:var(--ok)"><strong>Angelegt:</strong> <a href="${esc(x.url)}" target="_blank" rel="noopener">${esc(x.key)}</a>${x.checks ? ` mit ${x.checks} Teilschritten` : ''}</div>
        <div class="small" style="margin:10px 0">Nimm den Key in den Branch-Namen auf (zum Beispiel <code>feature/${esc(x.key)}-…</code>), dann verknüpft das Panel Ticket und Branch von selbst.</div>
        <div class="row"><button id="tk-ck">Key kopieren</button><button class="primary" id="tk-done">Fertig</button></div>`;
      $('tk-ck').onclick = () => copyText(x.key, 'Ticket-Key');
      $('tk-done').onclick = () => $('tkDlg').close();
      load();
    });
  };
}
$('tkClose').onclick = () => $('tkDlg').close();
$('board').addEventListener('click', ev => { const b = ev.target.closest('button[data-tk]'); if (b) openTicket(b); });
// ---------------------------------------------------------------- Verknüpfen (Drag and drop) und Pools
const MIME = 'application/x-tinyops';
const AI_PRESETS = { claude: ['Claude.ai', 5, 100, '%'], chatgpt: ['ChatGPT', 5, 100, '%'], mistral: ['Mistral Vibe', 5, 100, '%'], local: ['Lokales Modell', 24, 0, 'Anfragen'], other: ['Anderes Konto', 5, 100, '%'] };
const AI_LABEL = { claude: 'Claude', chatgpt: 'ChatGPT', mistral: 'Mistral', local: 'Lokal', other: 'Konto' };
function fmtReset(secs) { if (secs < 86400) return fmtLeft(secs); const h = Math.round(secs / 3600), d = Math.floor(h / 24); return d + ' d' + (h % 24 ? ' ' + (h % 24) + ' h' : ''); }
function fmtAgo(ts) { const m = Math.max(0, Math.round((Date.now() / 1000 - ts) / 60)); return m >= 2880 ? Math.round(m / 1440) + ' Tagen' : m >= 120 ? Math.round(m / 60) + ' h' : m + ' min'; }
function fmtLeft(secs) { const m = Math.max(0, Math.round(secs / 60)); return m >= 60 ? `${Math.floor(m / 60)} h ${m % 60} min` : `${m} min`; }
let usageData = null, usageT = 0, usageOpen = false;   // nach einem Reload ist die Box immer zu: sie öffnet sich nur per Klick
const WIN_SHORT = { '5 h': '5 h', 'Woche': 'Woche', 'Woche Opus': 'Opus', 'Vibe Monat': 'Vibe', 'API Monat': 'API' };
// Tempo (0.22): Verbrauch gegen vergangene Zeit. Für «Token-Maxing»: was am Ende des Fensters übrig bleibt, verfällt.
function paceLine(w) {
  if (w.time_left_pct == null || w.left_pct <= 0) return '';
  if (w.projected_pct == null) return '<div class="aimeta"><span class="aipace quiet">Fenster hat gerade erst begonnen, noch keine Hochrechnung.</span></div>';
  if (w.empty_in_secs != null && w.empty_in_secs < w.secs_left) return `<div class="aimeta"><span class="aipace fast">Zu schnell: Bei diesem Tempo leer in ${fmtReset(w.empty_in_secs)}, ${fmtReset(w.secs_left - w.empty_in_secs)} vor dem Reset.</span></div>`;
  const waste = Math.max(0, Math.round(100 - w.projected_pct));
  if (w.ahead >= 10 && waste >= 10) return `<div class="aimeta"><span class="aipace ahead">Vorsprung: Bei diesem Tempo verfallen etwa ${waste} %. Du kannst mehr nutzen.</span></div>`;
  return '<div class="aimeta"><span class="aipace quiet">Im Plan: Verbrauch passt zur Zeit.</span></div>';
}
function renderUsageBox() {
  if (!(state && (state.usage_providers || []).length)) return;
  const det = $('usageDet');
  const sum = !usageData ? '<span class="ucp na">frage ab …</span>' : usageData.items.map(a => {
    if (!a.ok) return `<span class="ucp na" title="${esc(a.error)}">${esc(a.name.split(' ')[0])}: n/a</span>`;
    return a.windows.map(w => {
      const c = w.left_pct <= 0 ? 'empty' : w.left_pct < 20 ? 'low' : '';
      const mini = w.time_left_pct == null ? '' : `<span class="ucb" aria-hidden="true"><i style="width:${w.left_pct}%"></i><b style="left:${w.time_left_pct}%"></b></span>`;
      return `<span class="ucp ${c}" title="${esc(a.name)}, ${esc(w.label)}: ${esc(w.left_pct)} % frei${w.time_left_pct == null ? '' : ', ' + w.time_left_pct + ' % der Zeit übrig'}${a.stale ? ' (veraltet)' : ''}">${esc(a.name.split(' ')[0])} ${esc(WIN_SHORT[w.label] || w.label)} ${Math.round(w.left_pct)} %${mini}${a.stale ? ' ⚠' : ''}</span>`;
    }).join('');
  }).join('');
  $('usageSum').innerHTML = sum;
  if (det.open !== usageOpen) det.open = usageOpen;
  $('usageDetail').innerHTML = usageOpen ? usageBody() : '';
  if ($('us-live')) $('us-live').innerHTML = usageData ? usageBody() : '';
}
document.addEventListener('click', ev => {
  const a = ev.target.closest && ev.target.closest('.aipace');
  if (a) { const d = $('usageDet'); if (d && !d.open) { d.open = true; d.scrollIntoView({ block: 'nearest' }); } else toast('Tempo: Der Strich im Balken zeigt, wie viel Zeit vom Fenster übrig ist. Rechts vom Strich: Vorsprung; links davon: schneller als die Zeit.'); }
  const sc = ev.target.closest && ev.target.closest('.rcard.score');
  if (sc && !ev.target.closest('button, a')) { LS.set('scoreOpen', !LS.get('scoreOpen', false)); renderRail(); }
});
document.addEventListener('keydown', ev => { if (ev.key === 'Enter' && ev.target.matches && ev.target.matches('[data-fopen][tabindex]')) ev.target.click(); });
document.addEventListener('toggle', ev => { if (ev.target && ev.target.id === 'usageDet') { usageOpen = ev.target.open; renderUsageBox(); } }, true);
const MISTRAL_URL = 'https://admin.mistral.ai/subscription';
function usageBody() {
  if (!usageData) return '<div class="empty">Frage Kontingent ab …</div>';
  const rows = usageData.items.map(a => {
    const mlink = a.id === 'mistral' ? ` <a href="${MISTRAL_URL}" target="_blank" rel="noopener" title="Dort das Lesezeichen «tinyops: Mistral lesen» anklicken">Mistral-Abo öffnen</a>` : '';
    if (!a.ok) return `<div class="aiacc"><div class="aihead"><b>${esc(a.name)}</b><span class="chip warn">nicht abrufbar</span></div><div class="aimeta"><span>${esc(a.error)}${mlink}</span></div></div>`;
    const ws = a.windows.map(w => {
      const st = w.left_pct <= 0 ? 'empty' : w.left_pct < 20 ? 'low' : 'ok';
      const mark = w.time_left_pct == null ? '' : `<b style="left:${w.time_left_pct}%" title="${w.time_left_pct} % der Zeit im Fenster übrig"></b>`;
      return `<div class="aibar s-${st}" title="${esc(w.used_pct)} % verbraucht${w.time_left_pct == null ? '' : ' · Strich: ' + w.time_left_pct + ' % der Zeit übrig'}"><i style="width:${w.left_pct}%"></i>${mark}</div>
        <div class="aimeta"><span><b>${esc(w.left_pct)} %</b> frei im Fenster ${esc(w.label)}${w.detail ? ' <span class="quiet">(' + esc(w.detail) + ')</span>' : ''}</span><span>${w.secs_left == null ? '' : 'Reset in ' + fmtReset(w.secs_left)}</span></div>
        ${paceLine(w)}`;
    }).join('');
    const age = a.manual ? `<div class="aimeta"><span class="quiet small">${a.stale ? '<b style="color:var(--warn)">Stand ist alt.</b> ' : ''}Zuletzt per Lesezeichen gesendet vor ${fmtAgo(a.fetched)}.${mlink}</span></div>` : '';
    return `<div class="aiacc"><div class="aihead"><b>${esc(a.name)}</b>${a.stale ? '<span class="chip warn">veraltet</span>' : ''}</div>${ws}${age}</div>`;
  }).join('');
  const ago = Math.max(0, Math.round((Date.now() / 1000 - usageData.fetched) / 60));
  return rows + `<div class="aimeta"><span class="quiet small">Stand vor ${ago} min · <a href="#" data-usage-refresh="1">neu abfragen</a></span></div>`;
}
async function loadUsage(fresh) {
  if (!(state && (state.usage_providers || []).length)) { usageData = null; return; }
  if (!fresh && usageData && Date.now() - usageT < 30000) return;
  usageT = Date.now();
  try { usageData = await api('GET', '/api/usage' + (fresh ? '?fresh=1' : '')); renderUsageBox(); if (state.agents && state.agents.enabled && $('fRailCards')) renderRail(); } catch (e) { /* nächstes Mal */ }
}
document.addEventListener('click', async ev => {
  const b = ev.target.closest && ev.target.closest('[data-sqrep]');
  if (!b) return;
  ev.preventDefault(); ev.stopPropagation();
  const old = b.textContent; b.disabled = true; b.textContent = 'Lese Sonar …';
  try {
    const r = await api('GET', `/api/sonar/report?project_id=${encodeURIComponent(b.dataset.p)}&iid=${encodeURIComponent(b.dataset.i)}&branch=${encodeURIComponent(b.dataset.b)}`);
    await copyText(r.text, 'Sonar-Report');
    toast(`Report kopiert: ${r.issues}${r.truncated ? ' von ' + r.total : ''} Findings, ${r.hotspots} Hotspots`);
  } catch (e) { toast(e.message); }
  finally { b.disabled = false; b.textContent = old; }
}, true);
document.addEventListener('click', ev => { if (ev.target.closest && ev.target.closest('[data-usage-refresh]')) { ev.preventDefault(); loadUsage(true); } });
function aiBody() {
  const acc = state.ai || [];
  const rows = acc.map(a => {
    const bud = a.budget > 0;
    const stateTxt = !a.running ? 'Fenster frei' : `Reset in ${fmtLeft(a.secs_left)}`;
    const main = bud ? `<b>${esc(a.left)} ${esc(a.unit)}</b> übrig von ${esc(a.budget)}` : `<b>${esc(a.used)} ${esc(a.unit)}</b> im Fenster, kein Limit`;
    return `<div class="aiacc" data-ai="${a.id}">
      <div class="aihead"><b title="${esc(a.name)}">${esc(a.name)}</b><span class="chip">${esc(AI_LABEL[a.kind] || a.kind)}</span><button class="x" data-aidel="${a.id}" data-name="${esc(a.name)}" title="Konto entfernen">×</button></div>
      ${bud ? `<div class="aibar s-${a.state}"><i style="width:${a.pct}%"></i></div>` : ''}
      <div class="aimeta"><span>${main}</span><span>${stateTxt} (${esc(a.window_hours)} h)</span></div>
      ${a.kind === 'local' ? '<div class="aimeta">Zählt Anfragen des Panels an dein lokales Modell, automatisch.</div>' : `<div class="aiact">
        <button data-aidelta="${a.id}" data-d="-10" title="Verbrauch um 10 senken">−10</button><button data-aidelta="${a.id}" data-d="10" title="Verbrauch um 10 erhöhen">+10</button>
        <input type="number" min="0" step="any" data-aiin="u${a.id}" placeholder="Verbraucht" title="Verbraucht, in ${esc(a.unit)}">
        <input type="number" min="0" step="1" data-aiin="r${a.id}" placeholder="Reset in min" title="«Zurücksetzung in» laut Anbieter, in Minuten">
        <button data-aiset="${a.id}">Stand setzen</button></div>`}
    </div>`;
  }).join('');
  const kinds = Object.keys(AI_PRESETS).map(k => `<option value="${k}">${esc(AI_LABEL[k])}</option>`).join('');
  const add = `<details class="aiadd" ${acc.length ? '' : 'open'}><summary>Konto hinzufügen</summary><div class="aiform"><select data-aiin="kind">${kinds}</select><input type="text" data-aiin="name" placeholder="Name" maxlength="40" value="Claude.ai">
    <input type="number" data-aiin="win" min="0.1" step="any" value="5" title="Fenster in Stunden"><span class="quiet small">h</span>
    <input type="number" data-aiin="bud" min="0" step="any" value="100" title="Budget (0 = kein Limit)"><input type="text" data-aiin="unit" value="%" size="6" maxlength="12" title="Einheit">
    <button data-aiadd>Anlegen</button></div></details>`;
  const note = acc.length ? '' : '<div class="empty">Abos wie Claude.ai, ChatGPT oder Mistral Vibe bieten keine Abfrage für das Restlimit. Lege ein Konto an, trage den Stand aus der Anzeige des Anbieters ein (verbraucht und «Reset in»), das Panel rechnet das Fenster weiter.</div>';
  return rows + note + add;
}
document.addEventListener('change', ev => {
  if (ev.target.dataset && ev.target.dataset.aiin === 'kind') {
    const p = AI_PRESETS[ev.target.value], g = n => document.querySelector(`[data-aiin="${n}"]`);
    g('name').value = p[0]; g('win').value = p[1]; g('bud').value = p[2]; g('unit').value = p[3];
  }
});
function openLink(btn) {
  const item = state.review.concat(state.assigned, state.mine).find(i => String(i.project_id) === btn.dataset.p && i.branch === btn.dataset.b);
  LK = { p: +btn.dataset.p, b: btn.dataset.b };
  $('lkSrc').innerHTML = `<span class="src gl">${btn.dataset.iid ? 'MR !' + esc(btn.dataset.iid) : 'Branch'}</span> ${esc(btn.dataset.t)} <code>${esc(btn.dataset.b)}</code>`;
  const stories = (state.jira && state.jira.stories) || [];
  $('lkPick').innerHTML = stories.map(s => `<button data-lkpick="${esc(s.key)}" title="${esc(s.summary)}"><b>${esc(s.key)}</b> ${esc(s.summary.slice(0, 34))}</button>`).join('') || '<span class="quiet small">Keine Story in Arbeit.</span>';
  $('lkPools').innerHTML = (state.pools || []).length ? `<div class="small quiet" style="margin-top:12px">Oder einer Kategorie zuordnen:</div><div class="pick">${state.pools.map(p => `<button data-lkpool="${p.id}">${esc(p.name)}</button>`).join('')}</div>` : '';
  $('lkKey').value = (item && item.manual_link) || '';
  $('lkUnlink').hidden = !(item && item.manual_link);
  $('lkMsg').innerHTML = '';
  $('linkDlg').showModal(); $('lkKey').focus();
}
async function lkDo(fn, ok) {
  try { await fn(); toast(ok); $('linkDlg').close(); await load(); } catch (e) { $('lkMsg').innerHTML = `<div class="banner bad" style="margin-top:10px">${esc(e.message)}</div>`; }
}
$('lkClose').onclick = () => $('linkDlg').close();
$('lkSave').onclick = () => lkDo(() => post('/api/links', { project_id: LK.p, branch: LK.b, ticket: $('lkKey').value }), 'Verknüpft');
$('lkKey').addEventListener('keydown', ev => { if (ev.key === 'Enter') { ev.preventDefault(); $('lkSave').click(); } });
$('lkUnlink').onclick = () => lkDo(() => post('/api/links/delete', { project_id: LK.p, branch: LK.b }), 'Verknüpfung gelöst');
$('linkDlg').addEventListener('click', ev => {
  const k = ev.target.closest('[data-lkpick]'); if (k) { $('lkKey').value = k.dataset.lkpick; $('lkSave').click(); }
  const pl = ev.target.closest('[data-lkpool]'); if (pl) lkDo(() => post('/api/pools/add', { id: +pl.dataset.lkpool, kind: 'ref', project_id: LK.p, branch: LK.b }), 'Im Pool');
});
// Ideen-Drop: überall ein Tastendruck oder Klick entfernt
let WISH_VIEW = '';
