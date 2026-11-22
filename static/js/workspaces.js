// Workspaces und Microsoft 365 in der Seitenleiste.
// ---- Workspaces (0.25): lokale Repos, ungepushte Arbeit, Worktrees der Agenten
let WS = null, WSF = LS.get('wsFilter', 'todo'), WSBUSY = false;
const WS_HOST = { gitlab: ['gl', 'GitLab'], github: ['gh', 'GitHub'], other: ['other', 'anderer Host'], none: ['none', 'kein Remote'] };
const dAge = d => d == null ? '' : d < 1 ? 'heute' : d < 2 ? 'seit gestern' : `seit ${Math.round(d)} Tagen`;
async function loadWs(fresh) {
  if (WSBUSY) return;
  WSBUSY = true; if (fresh || !WS) renderWs();
  try { WS = await api('GET', '/api/workspaces' + (fresh ? '?fresh=1' : '')); } catch (e) { WS = { enabled: true, error: e.message, repos: [], plain: [], roots: [], totals: {} }; }
  WSBUSY = false; renderWs();
}
function wsFacts(r) {
  if (!r.ok) return `<span class="chip bad">nicht lesbar: ${esc(r.error || '')}</span>`;
  const f = [], old = WS.stale_days;
  if (r.secrets && r.secrets.length) f.push(`<span class="chip bad" title="Der Geheimnis-Scan hat in ungepushten Commits oder offenen Änderungen etwas gefunden, das nach Zugangsdaten aussieht. Vor dem Push ansehen.">${r.secrets.length} Geheimnis${r.secrets.length === 1 ? '' : 'se'}?</span>`);
  if (r.unpushed_commits) f.push(`<span class="chip ${r.oldest_days >= old ? 'bad' : 'warn'}" title="Commits, die auf keinem Remote liegen">${r.unpushed_commits} Commit${r.unpushed_commits === 1 ? '' : 's'} nicht gepusht${r.unpushed_branches > 1 ? ` auf ${r.unpushed_branches} Branches` : ''}${r.oldest_days != null ? ', ' + dAge(r.oldest_days) : ''}</span>`);
  if (r.no_upstream) f.push(`<span class="chip warn" title="Diese Branches gibt es nur auf diesem Rechner">${r.no_upstream} ohne Upstream</span>`);
  if (r.dirty.total) f.push(`<span class="chip warn" title="${r.dirty.changed} geändert, ${r.dirty.staged} vorgemerkt, ${r.dirty.new} neu">${r.dirty.total} Datei${r.dirty.total === 1 ? '' : 'en'} offen</span>`);
  if (r.stashes) f.push(`<span class="chip ${r.stash_age_days >= 7 ? 'bad' : 'warn'}" title="Stashes liegen nur lokal und gehen leicht vergessen">${r.stashes} Stash${r.stashes === 1 ? '' : 'es'}${r.stash_age_days >= 1 ? ', ältester ' + Math.round(r.stash_age_days) + ' d' : ''}</span>`);
  if (r.agent_branches) f.push(`<span class="chip ag-run" title="Branches von Agenten, die du noch nicht gepusht oder gelöscht hast">${r.agent_branches} Agent-Branch${r.agent_branches === 1 ? '' : 'es'}</span>`);
  const behind = (r.branches.find(b => b.current) || {}).behind;
  if (behind) f.push(`<span class="chip" title="Der aktuelle Branch liegt hinter seinem Upstream (Stand des letzten Abholens)">${behind} hinter Upstream</span>`);
  if (!f.length) f.push('<span class="okk">alles gepusht</span>');
  if (r.fetched_days != null && r.fetched_days >= 3) f.push(`<span class="quiet" title="Voraus und hinter beziehen sich auf den Stand des letzten Abholens">abgeholt vor ${Math.round(r.fetched_days)} d</span>`);
  return f.join('');
}
function secretList(list, lead) {
  if (!list || !list.length) return '';
  return `<div class="banner bad" style="margin:0"><b>${list.length} mögliche${list.length === 1 ? 's Geheimnis' : ' Geheimnisse'}.</b> ${esc(lead)}: Der Scan erkennt Muster, er kann sich irren.
    <ul class="agfiles" style="max-height:none">${list.map(x => `<li data-copyfile="${esc(x.file)}:${x.line}" title="Klick kopiert Datei und Zeile" style="cursor:copy"><code>${esc(x.file)}:${x.line}</code><span>${esc(x.rule)} ${esc(x.excerpt)}${x.where ? ' · ' + esc(x.where) : ''}</span></li>`).join('')}</ul>
    <span class="small">Sind es Testdaten: die Zeile mit <code>tinyops:allow-secret</code> kommentieren. Ist es echt: aus dem Commit entfernen und das Geheimnis wechseln.</span></div>`;
}
function wsRepo(r, i) {
  const [hk, hl] = WS_HOST[r.host] || WS_HOST.other;
  const cls = !r.ok ? 'stale' : !r.todo ? 'clean' : (r.oldest_days >= WS.stale_days || r.stash_age_days >= 7) ? 'stale' : 'todo';
  const known = r.project ? '' : `<span class="st st-other" title="Kein eingerichtetes Projekt in tinyops: ohne MRs, Pipeline und Agenten. Aufnehmen unter Einstellungen → Projekte.">nicht in tinyops</span>`;
  const dc = r.project ? WS.classes[r.project.pid] : null;
  const agents = r.project && WS.agents.length ? `<select data-wsag="${i}" aria-label="Agent zuweisen" title="Einem Agenten in diesem Repo Arbeit geben"><option value="">Agent zuweisen …</option>${WS.agents.map(a => {
    const no = dc === 'restricted' && a.cloud; return `<option value="${esc(a.id)}" ${no ? 'disabled' : ''}>${esc(a.name)}${no ? ' · nicht für restricted' : ''}</option>`; }).join('')}</select>` : '';
  const brs = (r.branches || []).filter(b => b.ahead || b.behind || b.current || !b.upstream).slice(0, 30).map(b => {
    const run = WS.runs[b.name];
    return `<div class="wsbr ${b.current ? 'cur' : ''}"><code title="${esc(b.name)}">${esc(b.name)}</code>
      <span class="${b.upstream ? 'up' : 'noup'}" title="${esc(b.subject)}">${b.upstream ? '→ ' + esc(b.upstream) : b.gone ? 'Upstream gelöscht' : 'kein Upstream'}</span>
      <span class="ah">${b.ahead ? `<b>${b.ahead} voraus</b>` : ''}${b.behind ? ` ${b.behind} hinter` : ''}${!b.ahead && !b.behind ? '<small>gleich</small>' : ''}</span><small>${b.age_days != null ? Math.round(b.age_days) + ' d' : ''}</small>
      <span class="wsact">${run ? `<button class="chip ${AG_ST[run.status] || ''}" data-arun="${run.id}" title="Lauf von ${esc(run.agent)} öffnen">${esc(run.agent)}</button>` : ''}${b.ahead && r.remotes.length ? `<button class="quiet-btn" data-wscopy="git -C &quot;${esc(r.path)}&quot; push${b.upstream ? '' : ' -u origin'} ${esc(b.name)}" title="tinyops pusht nie selbst: Befehl kopieren und im Terminal ausführen">${ic('copy')} push-Befehl</button>` : ''}</span></div>`; }).join('');
  const wts = (r.worktrees || []).map(w => {
    const run = WS.runs[w.branch];
    return `<div class="wsbr"><code title="${esc(w.path)}">${esc(w.path)}</code><span class="up">${w.detached ? 'Commit ' + esc(w.sha) : esc(w.branch)}</span>
      <span class="ah">${w.missing ? '<b>Ordner fehlt</b>' : w.dirty ? `<b>${w.dirty} offen</b>` : '<small>sauber</small>'}</span><small>${w.agent ? (w.path.includes('.tinyops-wt') ? 'tinyops' : 'Agent') : ''}</small>
      <span class="wsact">${run ? `<button class="chip ${AG_ST[run.status] || ''}" data-arun="${run.id}">${esc(run.agent)} · ${esc(run.status)}</button>` : ''}<button class="quiet-btn" data-wscopy="${esc(w.path)}">${ic('copy')} Pfad</button>${!w.dirty ? `<button class="quiet-btn" data-wtrm="${esc(w.path)}" data-wtrepo="${esc(r.path)}" title="${w.missing ? 'Eintrag entfernen, der Ordner fehlt schon' : 'Worktree entfernen. Nur wenn sauber, und nur wenn sein Commit noch auf einem Branch liegt'}">${w.missing ? 'Eintrag entfernen' : 'Entfernen'}</button>` : ''}</span></div>`; }).join('');
  return `<details class="wsrepo ${cls}" ${LS.get('wsOpen.' + r.path, false) ? 'open' : ''} data-wsrepo="${esc(r.path)}"><summary>
      <div class="wsname"><b>${esc(r.name)}</b><span class="st st-${hk}">${hl}</span>${known}<small title="${esc(r.path)}">${esc(r.rel || r.path)}${r.remote ? ' · ' + esc(r.remote) : ''}${r.head ? ' · auf ' + esc(r.head) : ''}</small></div>
      <div class="wsfacts">${wsFacts(r)}</div>
      <div class="wsact">${agents}${r.remotes && r.remotes.length ? `<button data-wsfetch="${i}" title="git fetch --prune: holt den Stand vom Remote, ändert nichts an deinen Branches">Abholen</button>` : ''}</div></summary>
    <div class="wsbody">${r.ok ? `${secretList(r.secrets, 'Vor dem Push ansehen')}<div><h4>Branches</h4>${brs || '<div class="small quiet">Keine lokalen Branches.</div>'}</div>${wts ? `<div><h4>Worktrees</h4>${wts}</div>` : ''}
      ${!r.remotes.length ? '<div class="banner warn" style="margin:0">Dieses Repo hat kein Remote: Alles liegt nur auf diesem Rechner.</div>' : ''}
      <div class="row"><button class="quiet-btn" data-wscopy="${esc(r.path)}">${ic('copy')} Pfad kopieren</button>${r.remotes.map(x => `<span class="quiet small">${esc(x.name)}: ${esc(x.url)}</span>`).join('')}</div>` : ''}</div></details>`;
}
function renderWs() {
  const el = $('viewWs');
  if (!WS) { el.innerHTML = '<div class="empty">Durchsuche die Workspaces …</div>'; return; }
  if (WS.enabled === false) { el.innerHTML = '<div class="empty">Workspaces sind ausgeschaltet (Einstellungen → Workspaces).</div>'; return; }
  const t = WS.totals || {}, repos = WS.repos || [];
  const flt = { todo: r => r.todo || !r.ok, all: () => true, agent: r => r.agent_branches || (r.worktrees || []).some(w => w.agent), unknown: r => !r.project,
                wt: r => (r.worktrees || []).length };
  const wtAll = t.worktrees || 0, wtStale = t.worktrees_tidy || 0;
  const shown = repos.map((r, i) => [r, i]).filter(([r]) => (flt[WSF] || flt.all)(r));
  const fbtn = (k, l, n) => `<button class="${WSF === k ? 'on' : ''}" data-wsf="${k}">${l}${n != null ? ' ' + n : ''}</button>`;
  const roots = (WS.roots || []).map(r => `<div class="wsplain"><code>${esc(r.path)}</code><span class="quiet small">${esc(r.why)}</span><span class="sp"></span><span class="${r.ok ? 'quiet' : 'chip bad'} small">${r.ok ? `${r.repos} Repos${r.plain ? ', ' + r.plain + ' ohne Git' : ''}` : 'Ordner nicht gefunden'}</span></div>`).join('');
  el.innerHTML = `<div class="wshead"><h2>Workspaces</h2><span class="quiet small">${WS.ts ? 'Stand ' + new Date(WS.ts * 1000).toLocaleTimeString('de-CH', { hour: '2-digit', minute: '2-digit' }) : ''}${WS.secs ? ` · ${WS.secs} s` : ''}${WS.partial ? ' · unvollständig (Zeitlimit)' : ''}</span><span class="sp"></span>
      <button id="wsReload" ${WSBUSY ? 'disabled' : ''}>${WSBUSY ? 'Lese …' : 'Neu einlesen'}</button></div>
    ${WS.error ? `<div class="banner bad">${esc(WS.error)}</div>` : ''}
    <div class="wssum"><div data-wsf="todo" role="button" tabindex="0" title="Diese Repos zeigen"><b class="${t.todo ? 'hot' : ''}">${t.todo || 0}</b><span>von ${t.repos || 0} Repos mit lokaler Arbeit</span></div><div data-wsf="todo" role="button" tabindex="0" title="Repos mit nicht gepushten Commits zeigen"><b class="${t.commits ? 'hot' : ''}">${t.commits || 0}</b><span>Commits nicht gepusht</span></div>
      <div data-wsf="todo" role="button" tabindex="0"><b>${t.dirty || 0}</b><span>Repos mit offenen Dateien</span></div><div data-wsf="todo" role="button" tabindex="0"><b>${t.stashes || 0}</b><span>Stashes</span></div><div data-wsf="agent" role="button" tabindex="0" title="Repos mit Agent-Branches zeigen"><b>${t.agent_branches || 0}</b><span>Agent-Branches</span></div>
      <div data-wsf="wt" role="button" tabindex="0" title="Repos mit Worktrees zeigen"><b class="${wtStale ? 'hot' : ''}">${wtAll}</b><span>Worktrees${wtStale ? `, ${wtStale} aufzuräumen` : ''}</span></div></div>
    ${!(WS.roots || []).length ? `<div class="banner warn">Noch kein Workspace bekannt. Trage unter Einstellungen → Workspaces den Ordner ein, in dem deine Projekte liegen (z. B. <code>~/work</code>).</div>` : ''}
    <div class="wsfilter">${fbtn('todo', 'Mit lokaler Arbeit', t.todo || 0)}${fbtn('all', 'Alle', repos.length)}${fbtn('agent', 'Agenten', repos.filter(flt.agent).length)}${fbtn('unknown', 'Nicht in tinyops', t.unknown || 0)}${fbtn('wt', 'Worktrees', repos.filter(flt.wt).length)}</div>
    ${shown.map(([r, i]) => wsRepo(r, i)).join('') || `<div class="empty">${WSF === 'todo' && repos.length ? 'Alles gepusht. Nichts liegt nur auf diesem Rechner.' : 'Keine Repos in dieser Ansicht.'}</div>`}
    ${(WS.plain || []).length ? `<h3 style="margin:22px 0 6px">Projekte ohne Git <small class="quiet">nicht versioniert, nicht gesichert</small></h3>${WS.plain.map(p => `<div class="wsplain"><b>${esc(p.name)}</b><span class="chip">${esc(p.kind)}</span><span class="quiet small">${esc(p.rel)}</span><span class="sp"></span><button class="quiet-btn" data-wscopy="git -C &quot;${esc(p.path)}&quot; init" title="Befehl kopieren">${ic('copy')} git init</button></div>`).join('')}` : ''}
    ${roots ? `<h3 style="margin:22px 0 6px">Durchsuchte Ordner</h3>${roots}<div class="small quiet" style="margin-top:8px">tinyops liest nur lokal und pusht nie. «Voraus» und «hinter» gelten für den Stand des letzten Abholens.</div>` : ''}`;
}
function wsBadge() {
  const w = state && state.workspaces, b = $('wsBadge');
  const tab = document.querySelector('.tab[data-view="ws"]'); if (tab) tab.hidden = !w;
  if (!b) return;
  const n = w ? (w.stale || []).length : 0;
  b.hidden = !n; b.textContent = n;
}
// -- Microsoft 365 im Fokus (0.28): Termine heute, was auf dich wartet
const hhmm = ts => new Date(ts * 1000).toLocaleTimeString('de-CH', { hour: '2-digit', minute: '2-digit', hour12: false });
function m365Rail() {
  const m = state && state.m365;
  if (!m || !m.enabled) return '';
  if (!m.logged_in) return `<section class="rcard"><h3>Microsoft 365</h3><div class="small quiet">Nicht angemeldet.</div><button data-goset="m365">Anmelden …</button></section>`;
  let h = '';
  const cal = m.calendar, now = Date.now() / 1000;
  if (cal) {
    const ev = e => `<li class="mev ${e.end <= now ? 'past' : e.start <= now ? 'now' : ''}"><span class="t">${e.all_day ? 'ganztags' : hhmm(e.start)}</span>
      <a href="${esc(e.url)}" target="_blank" rel="noopener" title="${esc(e.subject)}${e.location ? ' · ' + esc(e.location) : ''}">${esc(e.subject)}</a>
      ${e.join && e.end > now && e.start - now < 900 ? `<a class="chip ok" href="${esc(e.join)}" target="_blank" rel="noopener">Beitreten</a>` : ''}
      ${e.end <= now && (cal.past_unbooked || []).some(x => x.id === e.id) && FOC() ? `<button class="quiet-btn" data-mbook="${esc(e.id)}" title="Diesen Termin als Zeit in die Zeiterfassung übernehmen">als Zeit</button>` : ''}</li>`;
    const nx = cal.next, mins = nx ? Math.round((nx.start - now) / 60) : null;
    h += `<section class="rcard"><h3>Heute <small>${cal.today.length ? `${cal.today.length} Termin${cal.today.length === 1 ? '' : 'e'}, ${Math.round(cal.meeting_minutes / 6) / 10} h belegt` : 'keine Termine'}</small></h3>
      ${nx && mins <= 60 ? `<div class="small" style="margin-bottom:6px"><b>${mins <= 0 ? 'Jetzt' : 'In ' + mins + ' min'}:</b> ${esc(nx.subject)}</div>` : ''}
      ${cal.today.length ? `<ul class="mlist">${cal.today.map(ev).join('')}</ul>` : ''}${m.errors && m.errors.calendar ? `<div class="small" style="color:var(--bad)">${esc(m.errors.calendar)}</div>` : ''}</section>`;
  }
  const mail = m.mail, tm = m.teams;
  if (mail || tm) {
    const row = x => `<li><a href="${esc(x.url)}" target="_blank" rel="noopener" title="${esc(x.preview || x.subject || x.topic)}">${esc(x.subject || x.topic)}</a><small>${esc(x.from)}${x.age_h != null ? ' · ' + hAge(x.age_h) : ''}</small></li>`;
    const n = (mail ? mail.waiting_total + mail.flagged.length : 0) + (tm ? tm.unread_total : 0);
    h += `<section class="rcard"><h3>Wartet auf dich <small>${n || 'nichts'}</small></h3>
      ${mail && mail.waiting.length ? `<div class="small quiet">Mail, direkt an dich und noch nicht beantwortet</div><ul class="mlist">${mail.waiting.slice(0, 5).map(row).join('')}</ul>` : ''}
      ${mail && mail.flagged.length ? `<div class="small quiet">Mit Fähnchen</div><ul class="mlist">${mail.flagged.slice(0, 3).map(row).join('')}</ul>` : ''}
      ${tm && tm.unread.length ? `<div class="small quiet">Teams, ungelesen</div><ul class="mlist">${tm.unread.slice(0, 5).map(row).join('')}</ul>` : ''}
      ${!n ? '<div class="small quiet">Keine offene Mail und kein ungelesener Chat.</div>' : ''}
      ${m.outdated ? `<div class="small" style="color:var(--warn)">Stand ist alt: ${esc(m.error || '')}</div>` : ''}${['mail', 'teams'].filter(k => m.errors && m.errors[k]).map(k => `<div class="small" style="color:var(--bad)">${esc(m.errors[k])}</div>`).join('')}</section>`;
  }
  return h;
}
function openMeetBook(id) {
  const ev = ((state.m365 || {}).calendar || {}).past_unbooked.find(x => x.id === id); if (!ev) return;
  const f = FOC(), pin = state.flow && state.flow.pinned;
  const opts = [...new Set([ev.key, pin && !pin.startsWith('hd:') ? pin : '', ...(f ? f.areas.map(a => a.ticket || a.name) : [])].filter(Boolean))];
  $('wsDlgBody').innerHTML = `<div style="display:grid;gap:12px"><div><strong>Termin als Zeit übernehmen</strong><div class="quiet small">${esc(ev.subject)}, ${hhmm(ev.start)}–${hhmm(ev.end)} (${Math.round((ev.end - ev.start) / 60)} min). Landet in der Zeiterfassung; gebucht wird erst, wenn du den Entwurf bestätigst.</div></div>
    <div class="field"><label for="mbKey">Worauf</label><input id="mbKey" class="full" list="mbOpts" value="${esc(opts[0] || '')}" placeholder="Ticket (z. B. DLP-120) oder Bereich"><datalist id="mbOpts">${opts.map(o => `<option value="${esc(o)}">`).join('')}</datalist></div>
    ${f ? `<div class="field"><label for="mbArea">Bereich</label><select id="mbArea" class="full"><option value="">automatisch</option>${f.areas.map(a => `<option value="${esc(a.id)}">${esc(a.name)}</option>`).join('')}</select></div>` : ''}
    <div class="row"><button class="primary" id="mbGo">Übernehmen</button><button id="mbNo">Abbrechen</button></div></div>`;
  $('wsDlg').showModal(); $('mbKey').focus();
  $('mbNo').onclick = () => $('wsDlg').close();
  $('mbGo').onclick = async () => {
    try { const r = await post('/api/m365/book', { id, key: $('mbKey').value, area: $('mbArea') ? $('mbArea').value : '' }); $('wsDlg').close(); toast(`${r.minutes} min übernommen`); await load(); }
    catch (e) { toast(e.message); }
  };
}
document.addEventListener('click', ev => {
  const b = ev.target.closest && ev.target.closest('[data-mbook]'); if (b) { ev.stopPropagation(); openMeetBook(b.dataset.mbook); return; }
  const g = ev.target.closest && ev.target.closest('[data-goset]'); if (g) { setView('settings'); setTimeout(() => { const x = document.getElementById('s-' + g.dataset.goset); if (x) x.scrollIntoView(); }, 400); return; }
  const c = ev.target.closest && ev.target.closest('[data-copy]'); if (c) { copyText(c.dataset.copy, 'Kopieren'); return; }
  const li = ev.target.closest && ev.target.closest('[data-copyfile]'); if (li) copyText(li.dataset.copyfile, 'Datei und Zeile');
});
function wsRail() {
  const w = state && state.workspaces;
  if (!w || w.scanning || !w.todo) return '';
  const st = (w.stale || []).slice(0, 3).map(x => `<div class="small"><b>${esc(x.name)}</b> <span class="quiet">${x.commits ? x.commits + ' Commits, ' : ''}${dAge(x.days)}</span></div>`).join('');
  return `<section class="rcard" data-wsgo="1" style="cursor:pointer" role="button" tabindex="0"><h3>Nicht gepusht <small>${w.todo} Repo${w.todo === 1 ? '' : 's'}</small></h3>
    <div class="small">${w.commits ? `${w.commits} Commits` : 'Offene Dateien oder Stashes'} liegen nur auf diesem Rechner${w.agent_branches ? `, ${w.agent_branches} Agent-Branch${w.agent_branches === 1 ? '' : 'es'}` : ''}.</div>
    ${w.secrets ? `<div class="small" style="color:var(--bad)"><b>${w.secrets} mögliche${w.secrets === 1 ? 's Geheimnis' : ' Geheimnisse'}</b> vor dem Push ansehen: ${esc((w.secret_repos || []).join(', '))}</div>` : ''}${st}</section>`;
}
function openWsTask(repo, agentId) {
  const a = WS.agents.find(x => x.id === agentId);
  $('wsDlgBody').innerHTML = `<div style="display:grid;gap:12px"><div><strong>Arbeit für ${esc(a.name)} in ${esc(repo.name)}</strong>
      <div class="quiet small">tinyops legt dazu eine lokale Aufgabe an. Danach siehst du den Auftrag an den Agenten und startest ihn. Der Agent arbeitet in einem eigenen Worktree; pushen bleibt bei dir.</div></div>
    <div class="field"><label for="wsTitle">Was soll er tun?</label><input id="wsTitle" class="full" maxlength="200" placeholder="z. B. Unit-Tests für den Retry im Vendex-Adapter"></div>
    <div class="field"><label for="wsBranch">Ausgehend von</label><select id="wsBranch" class="full">${repo.branches.filter(b => !b.agent).map(b => `<option ${b.current ? 'selected' : ''}>${esc(b.name)}</option>`).join('')}</select></div>
    <div class="row"><button class="primary" id="wsGo">Weiter zum Auftrag</button><button id="wsNo">Abbrechen</button></div></div>`;
  $('wsDlg').showModal(); $('wsTitle').focus();
  $('wsNo').onclick = () => $('wsDlg').close();
  const go = async () => {
    try {
      const r = await post('/api/workspaces/task', { path: repo.path, title: $('wsTitle').value, branch: $('wsBranch').value });
      $('wsDlg').close(); await load();
      agCtx[r.key] = { key: r.key, title: r.title, url: '', items: [{ project_id: r.project_id, branch: r.branch }] };
      openAgentDlg({ agent: agentId, ticket: r.key, pid: r.project_id });
    } catch (e) { toast(e.message); }
  };
  $('wsGo').onclick = go;
  $('wsTitle').onkeydown = ev => { if (ev.key === 'Enter') { ev.preventDefault(); go(); } };
}
document.addEventListener('click', async ev => {
  const t = ev.target;
  if (t.closest('[data-wsgo]')) { setView('ws'); return; }
  if (!t.closest('#viewWs')) return;
  if (t.id === 'wsReload') { loadWs(true); return; }
  const f = t.closest('[data-wsf]'); if (f) { WSF = f.dataset.wsf; LS.set('wsFilter', WSF); renderWs(); return; }
  const wr = t.closest('[data-wtrm]');
  if (wr) { ev.preventDefault();
    if (!confirm(`Worktree entfernen?\n\n${wr.dataset.wtrm}\n\ntinyops entfernt ihn nur, wenn er sauber ist und sein Commit noch auf einem Branch oder Remote liegt.`)) return;
    try { const res = await post('/api/workspaces/wt_remove', { path: wr.dataset.wtrepo, worktree: wr.dataset.wtrm }); WS = res; toast(res.message || 'Entfernt'); renderWs(); } catch (e) { toast(e.message); }
    return; }
  const c = t.closest('[data-wscopy]'); if (c) { ev.preventDefault(); await copyText(c.dataset.wscopy, 'Kopiert'); toast('Kopiert'); return; }
  const fe = t.closest('[data-wsfetch]');
  if (fe) { ev.preventDefault(); const r = WS.repos[+fe.dataset.wsfetch]; fe.disabled = true; fe.textContent = 'Hole …';
    try { WS = await post('/api/workspaces/fetch', { path: r.path }); toast(`${r.name}: abgeholt`); } catch (e) { toast(e.message); } renderWs(); return; }
  if (t.closest('select')) ev.stopPropagation();
});
document.addEventListener('change', ev => {
  const s = ev.target.closest && ev.target.closest('[data-wsag]');
  if (s && s.value) { const r = WS.repos[+s.dataset.wsag], a = s.value; s.value = ''; openWsTask(r, a); }
});
document.addEventListener('toggle', ev => { const d = ev.target; if (d.dataset && d.dataset.wsrepo) LS.set('wsOpen.' + d.dataset.wsrepo, d.open); }, true);
