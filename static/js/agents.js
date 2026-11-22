// Agenten: Zuweisen, Zyklus, Lauf-Dialog, Review-Punkte, Ziehen auf Aufgaben.
// ---- Agenten auf Karten
const AG = () => (state && state.agents) || { enabled: false, agents: [], runs: [], projects: [] };
const AG_ST = { 'zugewiesen': 'tk', 'läuft': 'agent', 'fertig': 'sq-ok', 'fehlgeschlagen': 'sq-bad', 'abgebrochen': 'sq-none', 'verloren': 'warn', 'abgelaufen': 'warn' };
const agCtx = {};
// 0.36: Rollen und Kontingent der Agenten
const QUOTA_DEF = { claude: 'claude', codex: 'codex', vibe: 'mistral' };
const ROLE_L = { plan: 'Planer', develop: 'Entwickler', review: 'Reviewer', test: 'Tester' };
function rolesText(r) { return r && typeof r === 'object' ? Object.entries(r).map(([k, v]) => k + '=' + v).join(', ') : (r || ''); }
function agQuota(a) {          // freier Anteil des Abos, das der Agent verbraucht: { pct, text, cls }
  const q = a.quota; if (!q || !usageData) return null;
  const it = usageData.items.find(x => x.id === q); if (!it) return null;
  if (!it.ok || !(it.windows || []).length) return { pct: null, text: 'Kontingent unbekannt', cls: '' };
  const w = (q === 'mistral' && a.kind === 'vibe' && it.windows.find(x => /vibe/i.test(x.label))) || it.windows.reduce((m, x) => x.left_pct < m.left_pct ? x : m);
  const pct = Math.round(w.left_pct);
  return { pct, text: pct <= 0 ? 'Kontingent leer' : pct + ' % frei', cls: pct <= 0 ? 'empty' : pct < 20 ? 'low' : '' };
}
function agOptLabel(a, phase) {
  const q = agQuota(a), role = phase && a.roles && a.roles.length < 4 ? (a.roles.includes(phase) ? ROLE_L[phase] : 'nicht als ' + ROLE_L[phase]) : '';
  return [a.name + (a.where ? ' (' + a.where + ')' : ''), role, q ? q.text : ''].filter(Boolean).join(' · ');
}
function agBest(phase, prefer) {   // passender Agent für eine Phase: Rolle passt, Kontingent nicht leer, sonst der bisherige
  const ag = AG().agents, ok = a => (a.roles || []).includes(phase) && !(agQuota(a) && agQuota(a).pct === 0);
  return (ag.find(a => a.id === prefer && ok(a)) || ag.find(ok) || ag.find(a => a.id === prefer) || ag[0] || {}).id;
}
function agentRow(ticket, key, title, url, items) {
  const ag = AG();
  if (!ag.enabled || !ticket) return '';
  agCtx[ticket] = { key, title, url, items: items || [] };
  const chips = ag.runs.filter(r => r.ticket === ticket).slice(0, 4).map(r =>
    `<button class="chip ${r.question ? 'warn' : AG_ST[r.status] || ''}" data-arun="${r.id}" title="${esc(r.agent_name)} · ${esc(r.where)}${r.question ? ' · fragt: ' + esc(r.question.question) : r.note ? ' · ' + esc(r.note) : ''}">${r.question ? ic('chat') : r.active ? '<span class="agspin"></span>' : ''}${esc(r.agent_name)} · ${r.question ? 'fragt' : esc(r.status)}${!r.active && r.ak && r.ak.total && r.status !== 'zugewiesen' ? ` · ${r.ak.ok}/${r.ak.total} AK` : ''}</button>`).join('');
  const pid = (items && items[0]) ? items[0].project_id : null;
  const cls = (ag.projects.find(p => p.id === pid) || {}).data_class;
  return `<div class="bagent">${chips}<select data-aassign="1" data-ticket="${esc(ticket)}" aria-label="Agent zuweisen"><option value="">Agent zuweisen …</option>${ag.agents.map(a => {
    const no = cls === 'restricted' && a.cloud;
    return `<option value="${esc(a.id)}" ${no ? 'disabled' : ''}>${esc(agOptLabel(a, 'develop'))}${no ? ' · nicht für restricted' : ''}</option>`; }).join('')}</select></div>`;
}
const fmtSecs = n => n >= 3600 ? Math.floor(n / 3600) + ' h ' + Math.floor(n % 3600 / 60) + ' min' : n >= 60 ? Math.floor(n / 60) + ' min ' + (n % 60) + ' s' : n + ' s';
let agTimer = null;
let agCloneT = null;
function agClose() { clearInterval(agTimer); agTimer = null; clearTimeout(agCloneT); $('agDlg').close(); }
// 0.39: Das Agentenfenster ist ein Seitenpanel (Nutzungsbericht: 182 Klicks, 24 Wutklicks im Dialog). Fokus und Listen bleiben
// daneben bedienbar. Ist schon ein anderer Dialog offen (z. B. Workspaces), öffnet es wie bisher darüber.
function agShow() {
  const d = $('agDlg'), modal = [...document.querySelectorAll('dialog')].some(x => x !== d && x.open && x.matches(':modal'));
  d.classList.toggle('side', !modal);
  if (!(d.open && d.matches(':modal') === modal)) {
    if (d.open) d.close();
    if (modal) d.showModal(); else d.show();
  }
  d.scrollTop = 0;
}
document.addEventListener('keydown', ev => {   // Esc schliesst das Seitenpanel, solange kein Dialog darüber liegt
  const d = $('agDlg');
  if (ev.key !== 'Escape' || !d.open || d.matches(':modal') || document.querySelector('dialog:modal')) return;
  ev.preventDefault(); ev.stopPropagation(); agClose();
}, true);
$('agDlg').addEventListener('close', () => { clearInterval(agTimer); agTimer = null; });
async function openAgentDlg(o) {
  const ag = AG(), ctx = agCtx[o.ticket] || { key: '', title: '', url: '', items: [] };
  const a = ag.agents.find(x => x.id === o.agent);
  if (!a) return;
  let pid = o.review ? o.review.project_id : o.pid ?? (ctx.items[0] ? ctx.items[0].project_id : (ag.projects[0] ? ag.projects[0].id : null));
  const branch = o.review ? o.review.branch : (ctx.items.find(x => x.project_id === pid) || ctx.items[0] || {}).branch || '';
  const box = $('agBody');
  let bopt = null, dirty = false, phase = o.phase || (o.review || o.followup || o.prereview ? '' : LS.get('agphase', 'develop'));
  async function draw() {
    let info;
    try { info = await api('POST', '/api/agents/prompt', { agent: a.id, ticket: o.ticket, project_id: pid, branch, title: ctx.title, key: ctx.key, url: ctx.url, review: o.review || undefined,
      brief: bopt || undefined, followup: o.followup || undefined, note: o.note || undefined, answers: o.answers || undefined, prereview: o.prereview || undefined, phase: phase || undefined, parent: o.parent || undefined }); }
    catch (e) { toast(e.message); return; }
    dirty = false;
    if (info.followup || info.prereview) pid = info.project_id;
    clearTimeout(agCloneT);
    const repoBox = rp => { const cl = rp && rp.clone || {};
      return !rp || !pid ? '' : rp.error ? `<div class="small quiet">Ob das Projekt beim Agenten liegt, liess sich nicht prüfen: ${esc(rp.error)}</div>`
      : cl.state === 'läuft' ? '<div class="banner warn">Das Projekt wird beim Agenten geklont … Bei grossen Repos dauert das einige Minuten. Du kannst den Dialog offen lassen.</div>'
      : rp.state === 'git' ? `<div class="small"><span class="okk">Repository liegt beim Agenten</span>${rp.remote ? ` <span class="quiet">(${esc(rp.remote)})</span>` : ''}${rp.mismatch ? ` <b style="color:var(--bad)">${esc(rp.mismatch)}</b>` : ''}</div>`
      : rp.state === 'dir' ? '<div class="banner bad">Am Zielpfad liegt ein Ordner, aber kein Git-Repository. tinyops überschreibt nichts: Ordner prüfen oder beim Projekt einen anderen Agenten-Ordner eintragen.</div>'
      : rp.state === 'missing' ? `<div class="banner warn"><b>Das Projekt liegt beim Agenten noch nicht.</b>${cl.state === 'fehler' ? `<div class="small" style="white-space:pre-wrap;margin:6px 0">Klonen fehlgeschlagen: ${esc(cl.msg)}</div>` : ''}
          <div class="row" style="margin-top:6px"><button id="agClone" class="primary">Jetzt klonen</button><select id="agVia" aria-label="Klonen über"><option value="ssh" ${rp.via !== 'https' ? 'selected' : ''}>über SSH</option><option value="https" ${rp.via === 'https' ? 'selected' : ''}>über HTTPS</option></select>
          <span class="small">nach <code>${esc(rp.path || info.workdir)}</code>, mit den Git-Zugangsdaten des Zielrechners. tinyops gibt kein Token weiter.</span></div></div>` : ''; };
    const repoReady = rp => !rp || !pid || !!rp.error || rp.state === 'git';
    const wireRepo = rp => {
      $('agRepo').innerHTML = repoBox(rp);
      $('agStart').disabled = !info.allowed || !repoReady(rp);
      if ($('agClone')) $('agClone').onclick = async () => { try { wireRepo((await post('/api/agents/clone', { agent: a.id, project_id: pid, via: $('agVia').value })).repo); } catch (e) { toast(e.message); } };
      if (rp && (rp.clone || {}).state === 'läuft') agCloneT = setTimeout(async () => {      // nachsehen, bis der Klon fertig ist; der Prompt bleibt unberührt
        if (!$('agDlg').open || !$('agRepo')) return;
        let x = rp; try { x = (await post('/api/agents/access', { agent: a.id, project_id: pid })).repo; } catch (e) { /* nächstes Mal */ }
        if (x !== rp && (x.clone || {}).state !== 'läuft' && x.state === 'git') toast('Projekt beim Agenten geklont');
        wireRepo(x);
      }, 2500);
    };
    const bf = info.brief;
    const briefBox = !bf ? '' : `<div class="agbrief"><h4>Auftrag aus ${bf.source === 'lokal' ? 'der Aufgabe' : bf.source === 'helpdesk' ? 'dem Helpdesk-Ticket' : 'dem Ticket'} ${esc(bf.key)}</h4>
      ${bf.error ? `<div class="small quiet">${esc(bf.error)} Der Prompt enthält nur Key und Titel.</div>` : `
      <div class="opts">${bf.desc_chars ? `<label><input type="checkbox" data-bf="desc" ${bf.desc ? 'checked' : ''}><span>Beschreibung mitschicken (${bf.desc_chars} Zeichen)</span></label>` : '<span class="small quiet">Keine Beschreibung.</span>'}
        ${bf.comments_n ? `<label><input type="checkbox" data-bf="comments" ${bf.comments ? 'checked' : ''}><span>${bf.comments_n === 1 ? 'Letzten Kommentar' : 'Letzte ' + bf.comments_n + ' Kommentare'} mitschicken</span></label>` : ''}</div>
      ${bf.careful ? '<div class="small quiet">Helpdesk-Texte enthalten oft Kundendaten. Bei einem Cloud-Agenten ist die Beschreibung deshalb erst nach deinem Haken dabei.</div>' : ''}
      ${bf.criteria.length ? `<div class="small"><b>Akzeptanzkriterien</b> <span class="quiet">(der Agent meldet jedes einzeln zurück)</span></div>${bf.criteria.map(c => `<label><input type="checkbox" data-bfc="${c.n}" ${c.on ? 'checked' : ''}><span>${esc(c.text)}</span></label>`).join('')}`
        : `<div class="small quiet">${bf.source === 'lokal' ? 'Keine offenen Teilschritte: Lege Teilschritte an, dann werden sie zu Kriterien.' : 'Im Ticket steht kein Abschnitt «Akzeptanzkriterien». Der Agent bekommt gesagt, dass er nachfragen soll.'}</div>`}
      ${bf.masked ? `<div class="small quiet">${bf.masked} mögliche${bf.masked === 1 ? 's Geheimnis' : ' Geheimnisse'} (Passwort, Token) geschwärzt. Lies den Prompt trotzdem durch.</div>` : ''}`}</div>`;
    const projSel = ag.projects.length > 1 && !o.review ? `<label class="sm">Projekt<select id="agProj">${ag.projects.map(p => { const st = (info.access || {})[p.id]; return `<option value="${p.id}" ${p.id === pid ? 'selected' : ''}>${esc(p.name)}${st === 'missing' ? ' · fehlt beim Agenten' : st === 'dir' ? ' · kein Git-Repo' : ''}</option>`; }).join('')}</select></label>` : '';
    const canPick = !o.review && !info.followup && !info.prereview && !o.parent;
    const phaseSel = canPick ? `<div class="row small" style="margin:0 0 8px"><span class="quiet">Phase:</span><span class="seg" role="group" aria-label="Phase">${['plan', 'develop'].map(p => `<button type="button" data-aph="${p}" class="${(info.phase || 'develop') === p ? 'on' : ''}" title="${p === 'plan' ? 'Der Agent liest nur und schreibt einen Plan. Du gibst ihn frei, dann wird umgesetzt.' : 'Der Agent ändert Code auf einem eigenen Branch.'}">${PH_L[p]}</button>`).join('')}</span>
      <span class="quiet">${(info.phase || 'develop') === 'plan' ? 'Erst planen: kleiner Plan, den du in fünf Minuten prüfst.' : 'Direkt umsetzen. Bei grösseren Aufgaben lieber zuerst planen.'}</span></div>` : '';
    const plab = o.review ? `Prompt: ${o.review.count} offene Review-Punkte auf <code>${esc(branch)}</code>` : info.followup ? `Prompt: Nachbessern von Lauf ${info.followup} auf <code>${esc(info.branch || 'Hauptbranch')}</code>`
      : info.phase === 'review' ? `Prompt: Review von Lauf ${info.parent} auf <code>${esc(info.branch)}</code> (der Agent ändert nichts)` : info.phase === 'test' ? `Prompt: Test von Lauf ${info.parent} auf <code>${esc(info.branch)}</code>`
      : info.phase === 'plan' ? 'Prompt: Plan (der Agent ändert nichts)' : info.parent ? `Prompt: Umsetzen nach Plan aus Lauf ${info.parent}` : 'Prompt';
    box.innerHTML = `<div class="row" style="justify-content:space-between"><strong>${esc(ctx.key || 'Aufgabe')} an ${esc(a.name)}</strong><span class="quiet small">${esc(info.kind)}</span></div>
      <div class="quiet small" style="margin:4px 0 4px">${esc(ctx.title)}</div>
      ${agCycleHtml(o.ticket)}
      ${phaseSel}
      <div class="agbox"><div class="grid3">${projSel}<div class="quiet small">Ziel: ${esc(info.where)}<br>Repository: <code>${esc(info.workdir || '—')}</code><br>Datenklasse: <b>${esc(info.data_class || '?')}</b>${info.model ? `<br>Modell: <code>${esc(info.model)}</code>` : ''}</div>
        <div class="quiet small">${info.mode === 'export' ? `Arbeitet in einem <b>Export</b> nur dieser Pfade: <code>${esc(info.cloud_paths.join(', '))}</code>. Eigenes Git ohne den Rest des Repos. Ergebnis per «Übernehmen» als Branch.` : info.mode === 'worktree' ? 'Arbeitet in einem <b>eigenen Worktree</b> auf Branch <code>agent/…</code>; dein Checkout bleibt unberührt.' : 'Arbeitet im <b>gemeinsamen Ordner</b> (ohne Isolation).'}</div></div></div>
      ${(info.review_skipped || []).length ? `<div class="banner warn">Nicht im Prompt, weil ausserhalb der freigegebenen Pfade (Export): ${esc(info.review_skipped.join(', '))}. Diese Punkte selbst oder mit einem lokalen Agenten bearbeiten.</div>` : ''}
      ${info.cloud ? `<div class="banner ${info.allowed ? 'warn' : 'bad'}">${info.allowed ? `Dieser Agent sendet Prompt und Code an ${esc(info.provider)}${bf && (bf.desc || bf.comments) ? ', auch den Tickettext unten' : ''}. Das Projekt ist dafür freigegeben.` : esc(info.reason)}</div>` : (!info.allowed ? `<div class="banner bad">${esc(info.reason)}</div>` : '')}
      <div id="agRepo"></div>
      ${(info.hints || []).map(h => `<div class="banner warn">${esc(h)}</div>`).join('')}
      ${briefBox}
      ${promptBoxHtml('agPrompt', plab + ' <span class="quiet">· so geht er an den Agenten</span>', info.prompt, true)}
      <div class="row" style="margin-top:8px;justify-content:flex-end"><button id="agCancel">Abbrechen</button>${o.run ? '' : '<button id="agAssign">Nur zuweisen</button>'}<button class="primary" id="agStart" ${info.allowed ? '' : 'disabled'}>${o.run ? 'Starten' : 'Zuweisen &amp; starten'}</button></div>`;
    if ($('agProj')) $('agProj').onchange = ev => { pid = +ev.target.value; draw(); };
    $('agPrompt').oninput = () => { dirty = true; };
    wirePromptBox(box, 'agPrompt');
    box.querySelectorAll('[data-aph]').forEach(b => b.onclick = () => {
      if (b.dataset.aph === (info.phase || 'develop')) return;
      if (dirty && !confirm('Der Prompt wird für die andere Phase neu aufgebaut. Deine Änderungen am Text gehen verloren.')) return;
      phase = b.dataset.aph; LS.set('agphase', phase); draw();
    });
    wireRepo(info.repo);
    box.querySelectorAll('[data-bf],[data-bfc]').forEach(c => c.onchange = () => {
      if (dirty && !confirm('Der Prompt wird neu aufgebaut. Deine Änderungen am Text gehen verloren.')) { c.checked = !c.checked; return; }
      bopt = { desc: !!(box.querySelector('[data-bf=desc]') || {}).checked, comments: !!(box.querySelector('[data-bf=comments]') || {}).checked,
        off: [...box.querySelectorAll('[data-bfc]')].filter(x => !x.checked).map(x => +x.dataset.bfc) };
      draw();
    });
    $('agCancel').onclick = agClose;
    const go = async start => {
      try {
        let run = o.run;
        const br = info.followup || info.prereview || info.phase === 'review' || info.phase === 'test' ? info.branch : branch;
        if (!run) run = (await post('/api/agents/assign', { agent: a.id, ticket: o.ticket, project_id: pid, branch: br, title: ctx.title })).id;
        if (start) await post('/api/agents/start', { run, prompt: $('agPrompt').value, project_id: pid, branch: br, phase: info.phase || 'develop', parent: info.parent || undefined });
        agClose(); toast(start ? 'Gestartet' : 'Zugewiesen'); await load();
      } catch (e) { toast(e.message); await load(); }
    };
    $('agStart').onclick = () => go(true);
    if ($('agAssign')) $('agAssign').onclick = () => go(false);
  }
  await draw();
  agShow();
}
const PH_ORDER = ['plan', 'develop', 'review', 'test'], PH_L = { plan: 'Planen', develop: 'Umsetzen', review: 'Review', test: 'Test' };
const NEXT_PH = { plan: 'develop', develop: 'review', review: 'test' };
// Zyklus eines Tickets: je Phase der jüngste Lauf und wo er steht
function agCycleHtml(ticket, curId) {
  const runs = AG().runs.filter(x => x.ticket === ticket);
  return `<div class="cycle" aria-label="Agenten-Zyklus">${PH_ORDER.map(p => {
    const r = runs.find(x => (x.phase || 'develop') === p);
    const [cls, txt] = !r ? ['', 'noch nicht'] : r.active ? ['wait', 'läuft'] : r.status === 'zugewiesen' ? ['', 'zugewiesen']
      : r.gate === 'ok' ? ['ok', 'freigegeben'] : r.gate === 'back' ? ['back', 'zurückgegeben'] : ['wait', r.status === 'fertig' ? 'wartet auf dich' : r.status];
    return `<div class="ph ${cls} ${r && r.id === curId ? 'cur' : ''}" title="${esc(PH_L[p])}: ${esc(txt)}${r ? ' (Lauf ' + r.id + ')' : ''}"><b>${PH_L[p]}</b><span>${esc(txt)}</span></div>`;
  }).join('')}</div>`;
}
function agManualHtml(r) {
  const m = r.manual || [];
  if (r.active || r.status === 'zugewiesen' || !m.length) return '';
  const K = { review: 'Review', test: 'Test' };
  return `<div class="small"><b>Deine Prüfung von Hand</b> <span class="quiet">${r.manual_done} von ${m.length} abgehakt. Trifft etwas nicht zu: abhaken und eine Notiz schreiben.</span>
    <ul class="mchk">${m.map(x => `<li class="${x.done ? 'done' : ''}"><input type="checkbox" data-mck="${x.i}" ${x.done ? 'checked' : ''} aria-label="${esc(x.step)} erledigt">
      <div><div class="st"><span class="kd">${K[x.kind] || ''}</span>${esc(x.step)}</div>${x.expect ? `<div class="ex">Erwartet: ${esc(x.expect)}</div>` : ''}</div>
      ${x.done || x.note ? `<input type="text" class="mn" data-mnote="${x.i}" maxlength="500" value="${esc(x.note)}" placeholder="Notiz, falls etwas nicht ganz zutrifft" aria-label="Notiz zu ${esc(x.step)}">` : ''}</li>`).join('')}</ul></div>`;
}
function agGateHtml(r) {
  if (r.active || r.status === 'zugewiesen') return '';
  const lab = r.phase_label || 'Umsetzen', m = r.manual || [], left = m.length - (r.manual_done || 0);
  const warn = (r.guard_warnings || []).length ? `<ul class="gwarn">${r.guard_warnings.map(w => `<li>${esc(w)}</li>`).join('')}</ul>` : '';
  const agentSel = (id, ph) => { const best = agBest(ph, r.agent); return `<select id="${id}" aria-label="Agent für die nächste Phase">${AG().agents.map(a => `<option value="${esc(a.id)}" ${a.id === best ? 'selected' : ''}>${esc(agOptLabel(a, ph))}${a.cloud ? '' : ' · lokal'}</option>`).join('')}</select>`; };
  if (r.gate === 'ok') {
    const nx = NEXT_PH[r.phase];
    return `<div class="gatebox ok"><h3>${esc(lab)} freigegeben</h3>${r.gate_note ? `<div class="small">${esc(r.gate_note)}</div>` : ''}
      <div class="row" style="margin-top:6px">${nx ? `<span class="small">Weiter mit <b>${PH_L[nx]}</b> durch</span>${agentSel('agNxA', nx)}<button class="primary" id="agNext" data-ph="${nx}">${PH_L[nx]} vorbereiten …</button>` : '<span class="small">Der Zyklus ist durch. Jetzt MR, Review im Team und Merge wie gewohnt.</span>'}
      <button class="quiet-btn" id="agGateReset" title="Freigabe zurücknehmen">Zurücknehmen</button></div></div>`;
  }
  if (r.gate === 'back') return `<div class="gatebox back"><h3>${esc(lab)} zurückgegeben</h3><div class="small">${esc(r.gate_note)}</div>
      <div class="row" style="margin-top:6px"><button class="primary" id="agBackGo" title="Neuer Lauf desselben Agenten mit deiner Notiz, auf dem Branch dieses Laufs">Nachbessern lassen …</button><button class="quiet-btn" id="agGateReset">Zurücknehmen</button></div></div>`;
  const what = r.phase === 'plan' ? 'Ist der Plan klein, klar und richtig? Erst dann wird umgesetzt.' : r.phase === 'review' ? 'Teilst du den Befund? Dann folgt der Test.'
    : r.phase === 'test' ? 'Ist es im laufenden System wirklich erfüllt?' : 'Hast du den Code gelesen und verstanden? Dann prüft ein Review.';
  return `<div class="gatebox"><h3>${esc(lab)}: deine Freigabe</h3><div class="small">${what}</div>${warn}
    <textarea id="agGateNote" maxlength="1000" placeholder="Notiz. Bei «Zurückgeben» Pflicht: was soll anders werden?" aria-label="Notiz zur Freigabe"></textarea>
    <div class="row"><button class="primary" id="agGateOk" ${left > 0 || r.status !== 'fertig' ? 'disabled' : ''} title="${r.status !== 'fertig' ? 'Nur ein fertiger Lauf lässt sich freigeben' : left > 0 ? 'Erst alle Prüfpunkte abhaken' : 'Phase freigeben'}">${ic('check')} Freigeben${left > 0 ? ` (noch ${left} Prüfpunkt${left === 1 ? '' : 'e'})` : ''}</button>
      <button id="agGateBack">Zurückgeben</button></div></div>`;
}
// «Ausprobieren …» für einen MR (0.34, E2): direkt ausführen über die Review-Umgebung, alles auch zum Kopieren,
// falls kein Agent da ist oder du es lieber selbst machst.
async function openMrTry(m) {
  const box = $('wsDlgBody');
  const draw = async () => {
    let st;
    try { st = await post('/api/mr/env', Object.assign({ do: 'state' }, m)); } catch (e) { box.innerHTML = `<div class="banner bad">${esc(e.message)}</div>`; return; }
    const ref = m.host === 'github' ? `pull/${m.iid}/head` : `merge-requests/${m.iid}/head`;
    const git = `git fetch origin refs/${ref}\ngit switch --detach FETCH_HEAD\n`;
    const e = st.env, s2 = st.state || {}, busy = s2.state === 'startet' || s2.state === 'stoppt';
    const L = { startet: 'startet …', 'läuft': 'läuft', stoppt: 'stoppt …', gestoppt: 'gestoppt', fehler: 'Fehler', unklar: 'unklar (tinyops neu gestartet)' };
    box.innerHTML = `<h3 style="margin:0 0 4px">Ausprobieren: ${m.host === 'github' ? 'PR' : 'MR'} !${m.iid}</h3>
      <div class="small quiet" style="margin-bottom:10px">Direkt ausführen oder kopieren. Nichts davon pusht oder ändert den MR.</div>
      <div class="trybox" style="border:0;padding:0;margin:0"><b>Prompt kopieren</b><div class="row small" style="margin:6px 0 10px"><select id="mtPrompt" aria-label="Prompt">${(state.prompts || []).map(p => `<option>${esc(p)}</option>`).join('')}</select><button id="mtCopyP">${ic('copy')} Kopieren</button>
        <span class="quiet">für einen Agenten oder ein Chatfenster</span></div>
      <b>Auschecken</b><div class="row small" style="margin:6px 0 10px"><button id="mtIde" data-ide="${esc(JSON.stringify(m))}">${ic('ide')} In IntelliJ öffnen</button><button id="mtGit">${ic('copy')} git-Befehle kopieren</button></div>
      <b>Review-Umgebung</b>
      ${e ? `<div class="small" style="margin:4px 0">${esc(e.label)} · Name <code>${esc(e.name)}</code> · Port <code>${esc(e.port)}</code>${s2.state ? ` · <b class="${s2.state === 'fehler' ? 'bad-t' : ''}">${esc(L[s2.state] || s2.state)}</b>` : ''}</div>
        <div class="row small" style="margin:6px 0"><button class="primary" id="mtUp" ${busy ? 'disabled' : ''}>${ic('play')} Starten</button>
          ${['läuft', 'fehler', 'unklar'].includes(s2.state) ? `<button id="mtDown" ${busy ? 'disabled' : ''}>Stoppen</button>` : ''}
          ${s2.state === 'läuft' && e.url ? `<button id="mtOpen">${ic('ext')} Öffnen</button>` : ''}<button id="mtCmd">${ic('copy')} Befehle kopieren</button></div>
        ${s2.log ? `<details><summary class="quiet small">Ausgabe</summary><pre class="log" style="max-height:24vh">${esc(s2.log)}</pre></details>` : ''}`
      : `<div class="small quiet" style="margin:4px 0">Für dieses Projekt ist keine eingetragen. <button class="quiet-btn" id="mtSet">Einstellungen → IntelliJ und Review-Umgebung</button></div>`}</div>
      <div class="row" style="justify-content:flex-end;margin-top:12px"><button id="mtClose">Schliessen</button></div>`;
    $('mtClose').onclick = () => $('wsDlg').close();
    $('mtCopyP').onclick = async () => { try { const r = await post('/api/prompt', { project_id: m.project_id, iid: m.iid, name: $('mtPrompt').value }); copyText(r.prompt, 'Prompt'); } catch (x) { toast(x.message); } };
    $('mtGit').onclick = () => copyText(git, 'git-Befehle');
    if ($('mtSet')) $('mtSet').onclick = () => { $('wsDlg').close(); setView('settings'); setTimeout(() => { const el = document.getElementById('s-ide'); if (el) el.scrollIntoView(); }, 300); };
    if ($('mtCmd')) $('mtCmd').onclick = () => copyText(`# im Worktree des MR ausführen (${st.worktree || 'erst «In IntelliJ öffnen» oder git-Befehle'})\n# starten\n${e.up}\n# stoppen\n${e.down || '(kein Stopp-Befehl eingetragen)'}\n`, 'Befehle');
    if ($('mtOpen')) $('mtOpen').onclick = () => window.open(s2.url || e.url, '_blank', 'noopener');
    const env = async d => { if (d === 'up' && !confirm(`Review-Umgebung starten?\n\nDas führt den Start-Befehl aus deinen Einstellungen auf diesem Rechner aus (${e.label}, Name ${e.name}).`)) return;
      try { await post('/api/mr/env', Object.assign({ do: d }, m)); } catch (x) { toast(x.message); } draw(); setTimeout(draw, 1500); };
    if ($('mtUp')) $('mtUp').onclick = () => env('up');
    if ($('mtDown')) $('mtDown').onclick = () => env('down');
    if (busy) setTimeout(() => { if ($('wsDlg').open) draw(); }, 3000);
  };
  box.innerHTML = '<div class="small quiet">Lade …</div>';
  $('wsDlg').showModal();
  draw();
}
document.addEventListener('click', ev => {
  const b = ev.target.closest('[data-mrtry]');
  if (!b) return;
  ev.stopPropagation();
  try { openMrTry(JSON.parse(b.dataset.mrtry)); } catch (e) { toast(e.message); }
}, true);
function agQuestionHtml(r) {
  const q = r.question;
  return `<div class="agq ${q.decision ? 'dec' : ''}"><b>${ic('chat')} ${esc(r.agent_name)} ${q.decision ? 'braucht eine Entscheidung' : 'fragt'}${q.blocking === false ? ' (arbeitet weiter)' : ' und wartet'}:</b><div style="margin-top:4px;white-space:pre-wrap">${esc(q.question)}</div>
    ${(q.options || []).length ? `<div class="opts">${q.options.map(o => `<button data-qopt="${esc(o)}">${esc(o)}</button>`).join('')}</div>` : ''}
    <textarea id="agAns" maxlength="4000" placeholder="Eigene Antwort (Ctrl+Enter schickt)" spellcheck="true"></textarea>
    <div class="row" style="justify-content:flex-end;margin-top:6px"><button class="primary" id="agAnsGo">Antwort schicken</button></div></div>`;
}
// «Kurz vorab» (0.32): in zwei Minuten wissen, was sich geändert hat und warum, wo anfangen, wie ausprobieren
function agBriefHtml(r, b) {
  const ST = { A: ['neu', 'ok'], M: ['geändert', ''], D: ['gelöscht', 'bad'], R: ['umbenannt', ''] };
  const files = b.files.map(f => `<li><span class="fst ${(ST[f.st] || ['', ''])[1]}" title="${esc((ST[f.st] || [f.st])[0])}">${esc(f.st)}</span>
      <div class="fp"><code>${esc(f.path)}</code><span class="fn">+${f.add || 0} −${f.del || 0}${f.comments ? ` · <span class="warn-t" title="Neue Kommentarzeilen. Begründungen gehören in den Bericht.">${f.comments} Kommentar${f.comments === 1 ? '' : 'e'}</span>` : ''}</span>
      <div class="fw ${f.why ? '' : 'none'}">${f.why ? esc(f.why) : 'Keine Begründung im Bericht.'}</div></div></li>`).join('');
  return `<section class="brief" aria-label="Kurz vorab"><h3>Kurz vorab</h3>
    ${b.short ? `<div class="mdv bshort">${mdHtml(b.short)}</div>` : '<div class="small quiet">Der Bericht hat keinen Abschnitt «Kurz».</div>'}
    <div class="bfacts small">${b.branch ? `<span class="picn">${branchIcon(b.branch, 18)}<code>${esc(b.branch)}</code></span>` : ''}<span>${esc(b.stat || 'keine Änderungen')}</span>
      ${b.ak ? `<span>${b.ak_ok}/${b.ak} Kriterien gemeldet</span>` : ''}<span class="${b.checks && b.checks_ok === b.checks ? '' : 'warn-t'}">${b.checks ? `${b.checks_ok}/${b.checks} Belege grün` : 'keine Belege'}</span>
      ${b.files.length ? `<span class="${b.without_reason ? 'warn-t' : ''}">${b.without_reason ? `${b.without_reason} von ${b.files.length} Dateien ohne Begründung` : 'jede Datei begründet'}</span>` : ''}</div>
    ${files ? `<ul class="bfiles">${files}</ul>` : ''}
    ${b.first ? `<div class="small"><b>Zuerst ansehen</b><div class="mdv">${mdHtml(b.first)}</div></div>` : ''}
    ${b.notdone ? `<details class="small"><summary><b>Bewusst nicht gemacht</b></summary><div class="mdv">${mdHtml(b.notdone)}</div></details>` : ''}
    <div id="agTry" class="trybox" aria-live="polite"></div></section>`;
}
async function agTryLoad(id) {
  const box = $('agTry'); if (!box) return;
  let t;
  try { t = await post('/api/agents/try', { run: id }); } catch (e) { box.innerHTML = `<div class="small quiet">${esc(e.message)}</div>`; return; }
  const es = t.env_state || {}, ESL = { startet: 'startet …', 'läuft': 'läuft', stoppt: 'stoppt …', gestoppt: 'gestoppt', fehler: 'Fehler', unklar: 'unklar (tinyops neu gestartet)' };
  const busy = es.state === 'startet' || es.state === 'stoppt';
  box.innerHTML = `<b>Ausprobieren</b>
    ${!t.branch ? '<div class="small quiet">Dieser Lauf hat keinen eigenen Branch zum Auschecken.</div>' : `<div class="row small" style="flex-wrap:wrap;gap:8px;margin-top:6px">
      <button class="primary" id="tyIde" ${t.clone || state.demo ? '' : 'disabled'} title="${t.clone ? 'Branch in deinen Checkout holen (eigener Worktree daneben, dein Stand bleibt) und IntelliJ öffnen' : 'Pfad zu deinem lokalen Checkout fehlt: Einstellungen → IntelliJ und Review-Umgebung'}">${ic('ext')} In IntelliJ öffnen</button>
      <button id="tyCmd" title="git-Befehle, um den Branch selbst zu holen, und die Befehle der Review-Umgebung">${ic('copy')} Befehle kopieren</button>
      ${t.env ? `<button id="tyUp" ${busy ? 'disabled' : ''} title="${esc(t.env.label)}: Start-Befehl aus den Einstellungen, im Worktree des Laufs. Name ${esc(t.env.name)}, Port ${esc(t.env.port)}">${ic('play')} Review-Umgebung starten</button>
        ${es.state === 'läuft' || es.state === 'fehler' || es.state === 'unklar' ? `<button id="tyDown" ${busy ? 'disabled' : ''}>Stoppen</button>` : ''}
        ${es.state === 'läuft' && es.url ? `<button id="tyOpen" title="${esc(es.url)}">${ic('ext')} Öffnen</button>` : ''}` : '<span class="quiet">Review-Umgebung (Docker Compose, Kubernetes): Einstellungen → IntelliJ und Review-Umgebung.</span>'}</div>
      ${t.worktree ? `<div class="small quiet" style="margin-top:4px">Worktree: <code>${esc(t.worktree)}</code> auf <code>${esc(t.sha)}</code></div>` : ''}
      ${es.state ? `<div class="small" style="margin-top:4px">Review-Umgebung: <b class="${es.state === 'fehler' ? 'bad-t' : ''}">${esc(ESL[es.state] || es.state)}</b>${es.url && es.state === 'läuft' ? ` · <a href="${esc(es.url)}" target="_blank" rel="noopener">${esc(es.url)}</a>` : ''}
        ${es.log ? `<details><summary class="quiet">Ausgabe</summary><pre class="log" style="max-height:24vh">${esc(es.log)}</pre></details>` : ''}</div>` : ''}`}`;
  if ($('tyCmd')) $('tyCmd').onclick = () => copyText(t.commands + (t.push ? '\n# Für Reviewer im Team: pushen machst du\n' + t.push + '\n' : '')
    + (t.env ? `\n# Review-Umgebung (${t.env.label}), im Worktree ausführen\n${t.env.up}\n# stoppen\n${t.env.down || '(kein Stopp-Befehl eingetragen)'}\n` : ''), 'Befehle');
  if ($('tyIde')) $('tyIde').onclick = async () => { const b2 = $('tyIde'); b2.disabled = true; try { const x = await post('/api/agents/checkout', { run: id, ide: true }); toast(x.launched ? 'IntelliJ öffnet ' + x.path : (x.hint || 'Worktree bereit: ' + x.path)); if (!x.launched) copyText(x.path, 'Pfad'); } catch (e) { toast(e.message); } agTryLoad(id); };
  const env = async (d) => { if (d === 'up' && !confirm(`Review-Umgebung starten?\n\nDas führt den Start-Befehl aus deinen Einstellungen auf diesem Rechner aus (${t.env.label}, Name ${t.env.name}).`)) return;
    try { await post('/api/agents/env', { run: id, do: d }); } catch (e) { toast(e.message); } agTryLoad(id); setTimeout(() => agTryLoad(id), 1500); };
  if ($('tyUp')) $('tyUp').onclick = () => env('up');
  if ($('tyDown')) $('tyDown').onclick = () => env('down');
  if ($('tyOpen')) $('tyOpen').onclick = () => window.open(es.url, '_blank', 'noopener');
  if (busy) setTimeout(() => { if ($('agTry')) agTryLoad(id); }, 3000);
}
// 0.36: Lauf direkt weiterführen, offene Entscheidungen beantworten
function agContinueHtml(r) {
  const od = r.open_decisions || [];
  const dec = od.length ? `<div class="agdecs"><b>${ic('chat')} Offene Entscheidungen</b> <span class="quiet small">Der Agent hat hier nicht geraten. Deine Antworten gehen mit dem nächsten Lauf an ihn.</span>
    ${od.map(d => `<div class="agdec"><div>${d.n}. ${esc(d.q)}</div>${d.options.length ? `<div class="opts">${d.options.map(o => `<button type="button" data-decopt="${d.n}" data-v="${esc(o)}">${esc(o)}</button>`).join('')}</div>` : ''}
      <input type="text" data-dec="${d.n}" maxlength="600" placeholder="Deine Entscheidung" aria-label="Entscheidung ${d.n}"></div>`).join('')}</div>` : '';
  return `<div class="agcont">${dec}
    <label class="small" for="agCont"><b>Weiterführen</b> <span class="quiet">${esc(r.agent_name)} arbeitet auf dem Branch dieses Laufs weiter. Offene Kriterien und fehlgeschlagene Belege gehen automatisch mit.</span></label>
    <textarea id="agCont" maxlength="4000" placeholder="Was soll als Nächstes passieren? (Ctrl+Enter startet)" spellcheck="true"></textarea>
    <div class="row" style="justify-content:flex-end;margin-top:6px"><button class="primary" id="agContGo">Weiterführen</button></div></div>`;
}
function agReportHtml(r) {
  const qa = (r.qa || []).map(x => `<li><span class="quiet">Frage ${x.id}:</span> ${esc(x.q)}<br><span class="quiet">Antwort:</span> ${esc(x.a)}</li>`).join('');
  const ck = (r.checks || []).map(c => `<li><span class="chip ${c.exit === 0 ? 'sq-ok' : 'sq-bad'}">Exit ${c.exit}</span><code>${esc(c.cmd)}</code><span class="quiet">${c.secs} s</span></li>`).join('');
  const AKS = { ok: ['sq-ok', 'erfüllt'], open: ['sq-bad', 'offen'], unclear: ['warn', 'unklar'], '': ['sq-none', 'nicht gemeldet'] };
  const crit = r.criteria || [];
  const ak = crit.map(c => `<li><span class="chip ${AKS[c.state][0]}">${AKS[c.state][1]}</span><span class="txt"><b>AK${c.n}</b> ${esc(c.text)}</span>${c.note ? `<span class="note">${esc(c.note)}</span>` : ''}</li>`).join('');
  if (r.active && !qa && !ck && !ak) return '';
  const parts = [], rb = !r.active ? r.review_brief : null;
  if (!r.active) parts.push(`<div class="row" style="justify-content:space-between"><h3 style="margin:0">Ergebnis</h3><button class="quiet-btn" id="agRep" title="Bericht, Belege und Änderungen neu vom Zielrechner lesen">Neu lesen</button></div>`);
  if (rb) parts.push(agBriefHtml(r, rb));
  if (ak) parts.push(`<div class="small"><b>Akzeptanzkriterien</b> <span class="quiet">${r.active ? '(Stand bei Abschluss)' : `${r.ak.ok} von ${r.ak.total} als erfüllt gemeldet. Das sind Angaben des Agenten: Beleg prüfen.`}</span><ul class="aklist">${ak}</ul></div>`);
  const res = r.result;
  if (!r.active && res && res.secrets && res.secrets.length) parts.push(secretList(res.secrets, 'Vor dem Übernehmen ansehen'));
  if (!r.active && res) parts.push(`<div class="small"><b>Änderungen</b> <span class="quiet">${res.stat ? esc(res.stat) : 'keine gegenüber dem Ausgangsstand'} · ${res.commits.length} Commit${res.commits.length === 1 ? '' : 's'}${res.dirty ? ` · ${res.dirty} Datei${res.dirty === 1 ? '' : 'en'} nicht committet` : ''}</span>
    ${res.commits.length ? `<ul class="agfiles">${res.commits.map(c => `<li><code>${esc(c.sha)}</code><span>${esc(c.subject)}</span></li>`).join('')}</ul>` : ''}
    ${res.files.length && !rb ? `<details><summary class="quiet">${res.files.length} Datei${res.files.length === 1 ? '' : 'en'}</summary><ul class="agfiles">${res.files.map(f => `<li><b title="A neu, M geändert, D gelöscht, R umbenannt">${esc(f.st)}</b><code>${esc(f.path)}</code></li>`).join('')}</ul></details>` : ''}</div>`);
  parts.push(ck ? `<div class="small"><b>Belege</b> <span class="quiet">(mit tinyops-check gelaufen, Exit-Code zählt)</span><ul class="agchk">${ck}</ul></div>`
    : (!r.active ? '<div class="small quiet">Keine Belege: Der Agent hat keine Tests über <code>tinyops-check</code> laufen lassen. Was er im Bericht «getestet» nennt, ist nicht belegt.</div>' : ''));
  if (!r.active) parts.push(r.summary ? `<details class="small" ${rb && r.phase !== 'review' ? '' : 'open'}><summary><b>${r.phase === 'plan' ? 'Plan des Agenten' : r.phase === 'review' ? 'Befund des Agenten' : 'Ganzer Bericht des Agenten'}</b> <span class="quiet">(seine Angaben, nicht geprüft)</span></summary><div class="mdv">${mdHtml(r.summary)}</div></details>`
    : '<div class="small quiet">Kein Bericht (<code>tinyops-report</code> nicht benutzt). Das Log unten zeigt, was passiert ist.</div>');
  if (qa) parts.push(`<details class="small"><summary>Rückfragen (${r.qa.length})</summary><ul class="agchk">${qa}</ul></details>`);
  if ((r.decisions || []).length) parts.push(`<div class="small"><b>Entscheidungen</b> <span class="quiet">(von dir, gehen in Review und MR-Beschreibung)</span><ul class="agchk">${r.decisions.map(d => `<li>${esc(d.q)} → <b>${esc(d.a)}</b></li>`).join('')}</ul></div>`);
  if (!r.active && r.status !== 'zugewiesen') parts.push(agContinueHtml(r));
  if (!r.active && r.status !== 'zugewiesen') parts.push(`<div class="agfollow">
    <button id="agFollow" title="Wie «Weiterführen», aber zuerst mit Vorschau und Bearbeiten des ganzen Prompts">Mit Vorschau …</button>
    <button id="agComment" title="Ergebnis als Kommentar-Entwurf in die Zwischenablage. tinyops schreibt nichts ins Ticket.">Als Ticket-Kommentar kopieren</button>
    ${rb ? '<button id="agMrDesc" title="Beschreibung für den MR: worum es geht, was und warum je Datei, wie testen. Für Reviewer im Team. tinyops erstellt keinen MR.">Als MR-Beschreibung kopieren</button>' : ''}</div>`);
  parts.push(agManualHtml(r), agGateHtml(r));
  return `<div class="agrep">${parts.join('')}</div>`;
}
// ------------------------------------------------ Offene Review-Punkte: ansehen, als Prompt oder JSON exportieren, einem Agenten geben
const RV_CLASS = { restricted: 'Kommentare können Code oder Kundendaten enthalten. Projekt ist restricted: nur an lokale Werkzeuge und lokale Agenten geben.',
  internal: 'Projekt ist internal: Cloud nur im Rahmen der freigegebenen Pfade.', public: '' };
async function openTopics(t, card) {
  const box = $('rvBody');
  let data = null, sel = null;
  async function fetchIt(fresh) {
    box.innerHTML = '<div class="quiet">Lese offene Punkte …</div>';
    if (!$('rvDlg').open) $('rvDlg').showModal();
    try { data = await post('/api/review/topics', { ...t, fresh: !!fresh }); }
    catch (e) { box.innerHTML = `<div class="banner bad">${esc(e.message)}</div><div class="rvacts"><button id="rvClose">Schliessen</button></div>`; $('rvClose').onclick = () => $('rvDlg').close(); return; }
    sel = new Set(data.topics.map(x => x.id));
    draw();
  }
  const ids = () => data.topics.filter(x => sel.has(x.id)).map(x => x.id);
  function draw() {
    const m = data.mr, no = (m.host === 'github' ? 'PR #' : 'MR !') + m.iid;
    const ag = AG(), canAgent = card && ag.enabled && !card.idea_id;
    const warn = data.configured ? RV_CLASS[data.data_class] : 'Projekt ist in tinyops nicht eingetragen und gilt als restricted.';
    box.innerHTML = `<div class="row" style="justify-content:space-between"><strong>Offene Punkte · ${esc(no)} ${esc(m.title)}</strong><span class="chip">${esc(data.data_class)}</span></div>
      <div class="quiet small" style="margin:4px 0"><code>${esc(m.branch)}</code> → <code>${esc(m.target_branch || '?')}</code> · Stand <code>${esc((m.sha || '').slice(0, 10))}</code> · ${esc(m.project)}</div>
      ${warn ? `<div class="banner ${data.data_class === 'restricted' ? 'warn' : ''}">${esc(warn)}</div>` : ''}
      ${data.note ? `<div class="small quiet">${esc(data.note)}</div>` : ''}
      ${data.topics.length ? `<ul class="rvlist">${data.topics.map(x => `<li class="${sel.has(x.id) ? '' : 'off'}"><input type="checkbox" data-rvsel="${esc(x.id)}" ${sel.has(x.id) ? 'checked' : ''} aria-label="Punkt auswählen">
        <div class="wh">${esc(x.file ? x.file + (x.line ? ':' + (x.range || x.line) : '') : x.kind === 'review' ? 'Review: Änderungen angefordert' : 'allgemein')}${x.outdated ? ' <span class="chip warn" title="Kommentar auf einem älteren Commit. Die Zeile kann sich verschoben haben.">älterer Stand</span>' : ''}${x.resolved === null ? ' <span class="chip" title="GitHub liefert den Status über REST nicht">Status?</span>' : ''}</div>
        <div class="bd">${esc(x.body)}</div>
        <div class="mt">@${esc(x.author)}${x.created ? ' · ' + esc(x.created.slice(0, 10)) : ''}${x.replies.length ? ` · ${x.replies.length} Antwort${x.replies.length === 1 ? '' : 'en'}` : ''}${x.url ? ` · <a href="${esc(x.url)}" target="_blank" rel="noopener">öffnen</a>` : ''}</div></li>`).join('')}</ul>`
        : '<div class="banner" style="margin-top:10px">Keine offenen Punkte. Alles aufgelöst oder noch nichts kommentiert.</div>'}
      <div class="rvacts"><span class="quiet small" style="margin-right:auto">${sel.size} von ${data.topics.length} ausgewählt</span>
        <button id="rvFresh">Neu laden</button>
        ${data.topics.length ? `<button id="rvJson">${ic('down')} JSON</button><button ${canAgent ? '' : 'class="primary"'} id="rvMd">${ic('copy')} Als Prompt kopieren</button>` : ''}
        ${data.topics.length && canAgent ? `<select id="rvAgent" aria-label="Agent beauftragen"><option value="">Agent beauftragen …</option>${ag.agents.map(a => { const no2 = data.data_class === 'restricted' && a.cloud; return `<option value="${esc(a.id)}" ${no2 ? 'disabled' : ''}>${esc(a.name)} (${esc(a.where)})${no2 ? ' · nicht für restricted' : ''}</option>`; }).join('')}</select>` : ''}
        <button id="rvClose">Schliessen</button></div>`;
    box.querySelectorAll('[data-rvsel]').forEach(cb => cb.onchange = () => { cb.checked ? sel.add(cb.dataset.rvsel) : sel.delete(cb.dataset.rvsel); draw(); });
    $('rvClose').onclick = () => $('rvDlg').close();
    $('rvFresh').onclick = () => fetchIt(true);
    const exp = async fmt => {
      if (!sel.size) { toast('Keine Punkte ausgewählt.'); return null; }
      return post('/api/review/export', { ...t, ids: ids(), format: fmt });
    };
    if ($('rvMd')) $('rvMd').onclick = async () => { try { const r = await exp('md'); if (r) await copyText(r.text, `Prompt mit ${r.count} Punkten`); } catch (e) { toast(e.message); } };
    if ($('rvJson')) $('rvJson').onclick = async () => {
      try {
        const r = await exp('json'); if (!r) return;
        const a = document.createElement('a'); a.href = URL.createObjectURL(new Blob([r.text], { type: 'application/json' })); a.download = r.filename; a.click();
        setTimeout(() => URL.revokeObjectURL(a.href), 2000); toast('Gespeichert: ' + r.filename);
      } catch (e) { toast(e.message); }
    };
    if ($('rvAgent')) $('rvAgent').onchange = ev => {
      const aid = ev.target.value; if (!aid) return;
      if (!sel.size) { toast('Keine Punkte ausgewählt.'); ev.target.value = ''; return; }
      agentRow(card.id, card.key || '', card.title, card.url, card.items);     // Kontext für den Dialog
      $('rvDlg').close();
      openAgentDlg({ ticket: card.id, agent: aid, review: { ...t, ids: ids(), branch: m.branch, count: sel.size } });
    };
  }
  await fetchIt(false);
}
document.addEventListener('click', ev => {
  const b = ev.target.closest && ev.target.closest('[data-topics]');
  if (!b) return;
  ev.preventDefault(); ev.stopPropagation();
  const card = b.dataset.tcard ? (focusEntries().find(x => x.t === 'card' && x.c.id === b.dataset.tcard) || {}).c : null;
  try { openTopics(JSON.parse(b.dataset.topics), card || null); } catch (e) { toast(e.message); }
});
async function openRunDlg(id) {
  const box = $('agBody');
  const get = () => (AG().runs.find(r => r.id === id));
  let r = get();
  if (!r) return;
  if (r.status === 'zugewiesen') { return openAgentDlg({ ticket: r.ticket, agent: r.agent, run: r.id, pid: r.project_id }); }
  async function draw(first) {
    r = get();
    if (!r) { agClose(); return; }
    draw.shape = JSON.stringify({ ...r, secs: 0 });
    const draft = $('agAns') ? { v: $('agAns').value, f: document.activeElement === $('agAns') } : null;
    let text = '';
    try { text = (await post('/api/agents/tail', { run: id, lines: 120 })).text; } catch (e) { text = e.message; }
    const atBottom = !$('agLog') || $('agLog').scrollTop + $('agLog').clientHeight >= $('agLog').scrollHeight - 30;
    const gdraft = $('agGateNote') ? $('agGateNote').value : '';
    const cdraft = $('agCont') ? $('agCont').value : '', ddraft = [...document.querySelectorAll('#agBody [data-dec]')].map(x => [x.dataset.dec, x.value]);
    box.innerHTML = `<div class="row" style="justify-content:space-between"><strong>${esc(r.phase_label || 'Umsetzen')} · ${esc(r.agent_name)} · ${esc(r.ticket)}</strong><span class="chip ${AG_ST[r.status] || ''}">${r.active ? '<span class="agspin"></span>' : ''}${esc(r.status)}${r.exit_code !== null && r.exit_code !== undefined && !r.active ? ' (Exit ' + r.exit_code + ')' : ''}</span></div>
      <div class="quiet small" style="margin:4px 0">${esc(r.title)}</div>
      ${agCycleHtml(r.ticket, r.id)}
      <div class="quiet small">Ziel: ${esc(r.where)} · ${r.mode === 'export' ? 'Export' : r.mode === 'worktree' ? 'Worktree' : 'Ordner'}: <code>${esc(r.wt || r.workdir)}</code>${r.out_branch ? ' · Ergebnis-Branch: <code>' + esc(r.out_branch) + '</code>' + (r.mode === 'export' && !r.taken ? ' (nach «Übernehmen»)' : '') : ''} · Dauer: ${esc(fmtSecs(r.secs))}</div>
      ${r.note ? `<div class="banner warn">${esc(r.note)}</div>` : ''}
      ${r.question ? agQuestionHtml(r) : ''}
      ${agReportHtml(r)}
      <pre class="log" id="agLog">${esc(text)}</pre>
      <details style="margin-top:6px"><summary class="quiet small">Gesendeter Prompt</summary>${promptBoxHtml('agSent', 'So ging er an den Agenten', r.prompt_text || '(nur beim Start gesendet)', false)}</details>
      <div class="row" style="margin-top:8px;justify-content:flex-end">
        ${r.attach ? '<button id="agAttach" title="Im Terminal einfügen, um live mitzulesen und einzugreifen">Befehl zum Mitlesen kopieren</button>' : ''}
        <button id="agReload">Aktualisieren</button>
        ${!r.active && r.mode === 'export' && !r.taken && r.status !== 'zugewiesen' ? '<button class="primary" id="agTake" title="Änderungen prüfen (nur freigegebene Pfade) und als Branch ins Repository übernehmen. Pushen machst du.">Übernehmen</button>' : ''}
        ${r.active ? '<button id="agStop">Stoppen</button>' : '<button id="agRemove">Entfernen</button>'}
        <button class="primary" id="agClose">Schließen</button></div>`;
    const lg = $('agLog'); if (lg && (first || atBottom)) lg.scrollTop = lg.scrollHeight;
    $('agClose').onclick = agClose;
    const sendAnswer = async text => {
      if (!text.trim()) { toast('Die Antwort fehlt.'); return; }
      try { await post('/api/agents/answer', { run: id, qid: r.question.id, text }); toast('Antwort geschickt. Der Agent arbeitet weiter.'); await load(); await draw(); }
      catch (e) { toast(e.message); }
    };
    box.querySelectorAll('[data-qopt]').forEach(b => b.onclick = () => sendAnswer(b.dataset.qopt));
    if ($('agAnsGo')) $('agAnsGo').onclick = () => sendAnswer($('agAns').value);
    if ($('agAns')) $('agAns').addEventListener('keydown', ev => { if (ev.key === 'Enter' && (ev.metaKey || ev.ctrlKey)) { ev.preventDefault(); sendAnswer($('agAns').value); } });
    if (draft && $('agAns')) { $('agAns').value = draft.v; if (draft.f) $('agAns').focus(); }
    if (gdraft && $('agGateNote')) $('agGateNote').value = gdraft;
    if (cdraft && $('agCont')) $('agCont').value = cdraft;
    ddraft.forEach(([n, v]) => { const x = box.querySelector(`[data-dec="${n}"]`); if (x && v) x.value = v; });
    wirePromptBox(box, 'agSent');
    if ($('agTry')) agTryLoad(id);
    if ($('agMrDesc')) $('agMrDesc').onclick = async () => { try { copyText((await post('/api/agents/mrdesc', { run: id })).text, 'MR-Beschreibung'); } catch (e) { toast(e.message); } };
    const mpost = async (i, done, note) => { try { await post('/api/agents/manual', { run: id, i, done, note }); await load(); await draw(); } catch (e) { toast(e.message); } };
    box.querySelectorAll('[data-mck]').forEach(c => c.onchange = () => mpost(+c.dataset.mck, c.checked, (box.querySelector(`[data-mnote="${c.dataset.mck}"]`) || {}).value || ''));
    box.querySelectorAll('[data-mnote]').forEach(n => n.onchange = () => mpost(+n.dataset.mnote, !!(box.querySelector(`[data-mck="${n.dataset.mnote}"]`) || {}).checked, n.value));
    const gate = async (g, note) => { try { await post('/api/agents/gate', { run: id, gate: g, note }); toast(g === 'ok' ? 'Freigegeben' : g === 'back' ? 'Zurückgegeben' : 'Freigabe zurückgenommen'); await load(); await draw(); } catch (e) { toast(e.message); } };
    if ($('agGateOk')) $('agGateOk').onclick = () => gate('ok', $('agGateNote').value);
    if ($('agGateBack')) $('agGateBack').onclick = () => { if (!$('agGateNote').value.trim()) { toast('Schreib kurz, was anders werden soll.'); $('agGateNote').focus(); return; } gate('back', $('agGateNote').value); };
    if ($('agGateReset')) $('agGateReset').onclick = () => gate('', '');
    if ($('agNext')) $('agNext').onclick = () => { const nx = $('agNext').dataset.ph, aid = $('agNxA').value; agClose(); openAgentDlg({ ticket: r.ticket, agent: aid, phase: nx, parent: r.id, pid: r.project_id }); };
    if ($('agBackGo')) $('agBackGo').onclick = () => { agClose(); openAgentDlg({ ticket: r.ticket, agent: r.agent, followup: r.id, note: r.gate_note, pid: r.project_id }); };
    if ($('agRep')) $('agRep').onclick = async () => { try { await post('/api/agents/report', { run: id }); await load(); await draw(); } catch (e) { toast(e.message); } };
    $('agReload').onclick = async () => { try { await post('/api/agents/refresh', {}); await load(); await draw(); } catch (e) { toast(e.message); } };
    if ($('agAttach')) $('agAttach').onclick = () => copyText(r.attach, 'Befehl zum Mitlesen');
    if ($('agComment')) $('agComment').onclick = async () => { try { copyText((await post('/api/agents/comment', { run: id })).text, 'Kommentar-Entwurf'); } catch (e) { toast(e.message); } };
    const contAnswers = () => { const o = {}; box.querySelectorAll('[data-dec]').forEach(x => { if (x.value.trim()) o[x.dataset.dec] = x.value.trim(); }); return o; };
    box.querySelectorAll('[data-decopt]').forEach(b => b.onclick = () => { const inp = box.querySelector(`[data-dec="${b.dataset.decopt}"]`); inp.value = b.dataset.v;
      box.querySelectorAll(`[data-decopt="${b.dataset.decopt}"]`).forEach(x => x.classList.toggle('on', x === b)); });
    if ($('agFollow')) $('agFollow').onclick = () => { const note = $('agCont') ? $('agCont').value : ''; const answers = contAnswers(); agClose(); openAgentDlg({ ticket: r.ticket, agent: r.agent, followup: r.id, note, answers, pid: r.project_id }); };
    const contGo = async () => {
      const text = $('agCont').value.trim(), answers = contAnswers();
      if (!text && !Object.keys(answers).length) { toast('Schreib, wie es weitergehen soll, oder beantworte eine Entscheidung.'); $('agCont').focus(); return; }
      await busy($('agContGo'), 'Starte …', async () => {
        try { const x = await post('/api/agents/continue', { run: id, text, answers }); toast('Weitergeführt als Lauf ' + x.id); await load(); openRunDlg(x.id); }
        catch (e) { toast(e.message); }
      });
    };
    if ($('agContGo')) $('agContGo').onclick = contGo;
    if ($('agCont')) $('agCont').addEventListener('keydown', ev => { if (ev.key === 'Enter' && (ev.metaKey || ev.ctrlKey)) { ev.preventDefault(); contGo(); } });
    if ($('agStop')) $('agStop').onclick = async () => { if (!confirm('Den Agenten wirklich stoppen? Die Sitzung wird beendet.')) return; try { await post('/api/agents/stop', { run: id }); await load(); await draw(); } catch (e) { toast(e.message); } };
    if ($('agTake')) $('agTake').onclick = async () => { try { const t = await post('/api/agents/takeover', { run: id }); toast(`Übernommen: Branch ${t.branch} (${t.files.length} Dateien)`); await load(); await draw(); } catch (e) { toast(e.message); } };
    if ($('agRemove')) $('agRemove').onclick = async () => {
      try { await post('/api/agents/remove', { run: id }); agClose(); await load(); }
      catch (e) {
        if (/noch nicht übernommen/.test(e.message) && confirm(e.message + '\n\nTrotzdem entfernen? Die Änderungen gehen verloren.')) {
          try { await post('/api/agents/remove', { run: id, force: true }); agClose(); await load(); } catch (e2) { toast(e2.message); }
        } else toast(e.message);
      }
    };
  }
  await draw(true);
  agShow();
  if (!r.active && r.status !== 'zugewiesen' && !r.ack) post('/api/agents/ack', { run: id }).then(load).catch(() => {});
  clearInterval(agTimer);
  const shape = x => JSON.stringify({ ...x, secs: 0 });
  draw.shape = shape(r);
  agTimer = setInterval(async () => {
    if (!$('agDlg').open) return;
    await load(); const cur = get(); if (!cur) return;
    if (shape(cur) !== draw.shape) { draw.shape = shape(cur); draw(false); return; }      // nur bei echten Änderungen neu aufbauen
    if (!cur.active || !$('agLog')) return;
    const lg = $('agLog'), atB = lg.scrollTop + lg.clientHeight >= lg.scrollHeight - 30;   // sonst nur das Log nachführen, Klicks gehen nicht verloren
    try { const tx = (await post('/api/agents/tail', { run: id, lines: 120 })).text; if (lg.textContent !== tx) { lg.textContent = tx; if (atB) lg.scrollTop = lg.scrollHeight; } } catch (e) { /* nächstes Mal */ }
  }, 4000);
}
document.addEventListener('change', ev => {
  const s = ev.target.closest && ev.target.closest('select[data-aassign]');
  if (s && s.value) { const v = s.value; s.value = ''; openAgentDlg({ ticket: s.dataset.ticket, agent: v }); }
});
document.addEventListener('click', ev => { const b = ev.target.closest && ev.target.closest('[data-arun]'); if (b) { ev.preventDefault(); openRunDlg(+b.dataset.arun); } });
// Ziehen
document.addEventListener('dragstart', ev => {
  const ad = ev.target.closest && ev.target.closest('[data-agdrag]');
  if (ad) {                                                       // 0.36: Agent auf eine Aufgabe ziehen
    ev.dataTransfer.setData(MIME, JSON.stringify({ t: 'agent', id: ad.dataset.agdrag })); ev.dataTransfer.effectAllowed = 'copy';
    dragKind = 'agent'; ad.classList.add('dragging'); return;
  }
  const bc = ev.target.closest && ev.target.closest('.bcard[data-bid]');
  const mc = ev.target.closest && ev.target.closest('.mrchip[data-rp]');
  if (mc || bc) {
    ev.dataTransfer.setData(MIME, JSON.stringify(mc ? { t: 'ref', p: +mc.dataset.rp, b: mc.dataset.rb } : { t: 'card', id: bc.dataset.bid }));
    ev.dataTransfer.effectAllowed = 'copyMove';
    dragKind = mc ? 'ref' : 'card';
    (mc ? mc : bc).classList.add('dragging');
    return;
  }
  const chip = ev.target.closest && ev.target.closest('a.chip[data-key]');
  const slot = ev.target.closest && ev.target.closest('.slot[data-skey]');
  const item = ev.target.closest && ev.target.closest('.item[data-dp]');
  let payload = null;
  if (chip) payload = { t: 'ticket', key: chip.dataset.key };
  else if (slot) payload = { t: 'ticket', key: slot.dataset.skey };
  else if (item) payload = { t: 'ref', p: +item.dataset.dp, b: item.dataset.db };
  if (!payload) return;
  ev.dataTransfer.setData(MIME, JSON.stringify(payload));
  ev.dataTransfer.effectAllowed = 'copyLink';
  (slot || item || chip).classList.add('dragging');
});
document.addEventListener('dragend', () => { dragKind = ''; document.querySelectorAll('.dragging, .dropok').forEach(e => e.classList.remove('dragging', 'dropok')); });
let dragKind = '';
function agentDrop(aid, t) {
  let c = null;
  if (t.dataset.bid) c = state.board.cards.find(x => x.id === t.dataset.bid);
  else { const e = fEntry(t.id === 'fx' ? FXID : t.dataset.fid); if (e && e.t === 'card') c = e.c;
    else if (e) { toast(e.t === 'review' ? 'Reviews: im MR «Mit Agent» die offenen Punkte wählen.' : 'Helpdesk-Tickets erst als Jira-Ticket anlegen, dann zuweisen.'); return; } }
  if (!c) { toast('Hier lässt sich kein Agent zuweisen.'); return; }
  if (c.idea_id) { toast('Ideen zuerst einplanen, dann einen Agenten zuweisen.'); return; }
  agentRow(c.id, c.key || '', c.title, c.url, c.items);
  openAgentDlg({ ticket: c.id, agent: aid });
}
function target(ev) {
  const c = x => ev.target.closest && ev.target.closest(x);
  if (dragKind === 'card') return c('.bpool[data-pool]') || c('.bcol[data-stage]');
  if (dragKind === 'agent') return c('#viewFocus [data-fid]') || c('#fx') || c('.bcard[data-bid]');
  return c('.bcard[data-bkey]') || c('.slot[data-skey]');
}
document.addEventListener('dragover', ev => {
  if (!ev.dataTransfer || !ev.dataTransfer.types.includes(MIME)) return;
  const t = target(ev);
  document.querySelectorAll('.dropok').forEach(e => { if (e !== t) e.classList.remove('dropok'); });
  if (t) { ev.preventDefault(); ev.dataTransfer.dropEffect = 'copy'; t.classList.add('dropok'); }
});
document.addEventListener('drop', async ev => {
  const t = target(ev);
  if (!t || !ev.dataTransfer.types.includes(MIME)) return;
  ev.preventDefault();
  document.querySelectorAll('.dropok, .dragging').forEach(e => e.classList.remove('dropok', 'dragging'));
  const d = JSON.parse(ev.dataTransfer.getData(MIME));
  if (d.t === 'agent') { agentDrop(d.id, t); return; }
  if (t.classList.contains('bpool')) {                    // Karte in eine Kategorie ziehen
    const c = state.board.cards.find(x => x.id === d.id);
    if (c && !c.idea_id) await act(() => post('/api/board/assign', c.key ? { key: c.key, pool_id: +t.dataset.pool } : { ref: c.id, pool_id: +t.dataset.pool }), 'Kategorie gesetzt');
    else toast('Ideen werden mit «Planen» einer Kategorie zugeordnet.');
    return;
  }
  if (t.dataset.bkey || t.dataset.stage) {                // Board
    if (d.t === 'card' && t.dataset.stage) { await moveCard(state.board.cards.find(c => c.id === d.id), t.dataset.stage); return; }
    if (d.t === 'ref' && t.dataset.bkey) { await act(() => post('/api/links', { project_id: d.p, branch: d.b, ticket: t.dataset.bkey }), `Mit ${t.dataset.bkey} verknüpft`); return; }
    if (d.t === 'ref' && t.dataset.stage) { toast('Branches und MRs auf eine Karte ziehen, nicht in eine Spalte.'); }
    return;
  }
  if (t.dataset.skey) {                                  // auf eine Story: Branch/MR verknüpfen
    if (d.t !== 'ref') { toast('Auf eine Story lassen sich nur Branches und MRs ziehen.'); return; }
    await act(() => post('/api/links', { project_id: d.p, branch: d.b, ticket: t.dataset.skey }), `Mit ${t.dataset.skey} verknüpft`);
  }
});
// Klicks: lösen, zuordnen, Pools
document.addEventListener('click', async ev => {
  const un = ev.target.closest('[data-unlink]');
  if (un) { ev.preventDefault(); ev.stopPropagation(); await act(() => post('/api/links/delete', { project_id: +un.dataset.p, branch: un.dataset.b }), 'Verknüpfung gelöst'); return; }
  const as = ev.target.closest('[data-assign]');
  if (as) { openLink(as); return; }
  const ab = ev.target.closest('button');
  if (ab && (ab.dataset.aiadd !== undefined || ab.dataset.aidel || ab.dataset.aidelta || ab.dataset.aiset)) {
    const g = n => document.querySelector(`[data-aiin="${n}"]`);
    if (ab.dataset.aiadd !== undefined) {
      const body = { name: g('name').value, kind: g('kind').value, window_hours: g('win').value, budget: g('bud').value, unit: g('unit').value };
      await act(() => post('/api/ai/save', body), 'Konto angelegt'); return;
    }
    if (ab.dataset.aidel) { if (confirm(ab.dataset.name + ' entfernen?')) await act(() => post('/api/ai/delete', { id: +ab.dataset.aidel }), 'Entfernt'); return; }
    if (ab.dataset.aidelta) { await act(() => post('/api/ai/set', { id: +ab.dataset.aidelta, delta: +ab.dataset.d })); return; }
    const id = +ab.dataset.aiset, u = g('u' + id).value, r = g('r' + id).value, body = { id };
    if (u === '' && r === '') { toast('Verbraucht oder «Reset in» eintragen'); return; }
    if (u !== '') body.used = u;
    if (r !== '') body.resets_in_min = r;
    g('u' + id).value = ''; g('r' + id).value = '';
    await act(() => post('/api/ai/set', body), 'Stand gesetzt'); return;
  }
});
// Dialog «Ticket zuordnen» (auch für Touch-Geräte, wo Ziehen nicht geht)
let LK = null;
