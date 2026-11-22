// Detail-Panel: alles zu einer Aufgabe, Strecke zum Übersteuern, Teilschritte.
// ---- Detail-Panel (halbe Seite): alles zu einer Aufgabe, Strecke zum Übersteuern
function renderFx() {
  const e = focusEntries().find(x => x.id === FXID);
  if (!e) { closeFx(); return; }
  const n = e.d.next, url = eUrl(e);
  const keep = ['fxCkNew', 'fxNote', 'fxEnv'].filter(id => $(id)).map(id => ({ id, v: $(id).value, f: document.activeElement === $(id) }));
  const head = `<div class="fxtop">${srcTags(e)}<span class="fkey">${esc(eKey(e))}</span>${url ? `<a class="ibtn" href="${esc(url)}" target="_blank" rel="noopener">${ic('ext')} ${e.t === 'review' ? 'MR' : e.t === 'hd' ? 'Helpdesk' : 'Ticket'} öffnen</a>` : ''}<span class="sp"></span><button class="quiet-btn" data-fxclose="1" aria-label="Schliessen" title="Schliessen (Esc)">${ic('x')}</button></div><h2>${esc(eTitle(e))}</h2>`;
  let body = `<div>${trackHtml(e.d, true, e.t === 'card' && !e.c.idea_id)}${e.t === 'card' && e.d.override && !e.c.local ? `<div class="small quiet" style="margin-top:8px">Von Hand gesetzt (aus den Daten: ${esc(state.flow.phases[e.d.data_phase].label)}). <button class="quiet-btn" data-fxauto="1">Automatisch</button></div>` : e.t === 'card' && !e.c.idea_id ? '<div class="small quiet" style="margin-top:8px">Klick auf eine Station setzt sie von Hand. Branch und MR ergeben sich aus GitLab.</div>' : ''}</div>
    <div class="fxnext k-${esc(n.kind)}"><div><b>${esc(n.label)}</b><span>${esc(n.why)}</span></div><div class="hbtns">${n.kind === 'done' ? '' : e.t === 'hd' ? `<a class="ibtn big" href="${esc(e.h.url)}" target="_blank" rel="noopener">${ic('ext')} Im Helpdesk öffnen</a>` : goBtn(e, 'primary big')}${testBtns(e, 'big')}${doneBtn(e, true)}</div>
      ${(n.action || {}).accept ? `<div class="fxacc"><input id="fxNote" maxlength="500" placeholder="Was hast du getestet? (optional)" autocomplete="off"><input id="fxEnv" maxlength="120" placeholder="Umgebung (optional)" autocomplete="off"></div>` : ''}</div>
    ${accHtml(e.d.acceptance || [])}`;
  if (e.t === 'hd') {
    const h = e.h, info = state.flow.hd_info || {}, d = HDD[h.key], mine = !e.side;
    if (d === undefined) hdLoad(h.key);
    body += `<div><h3>${esc(hdName())} <small>nur lesend</small></h3><div class="fxitem"><span class="hdprio p${Math.min(5, h.prio_rank)}" style="width:44px"></span><div class="nm"><b>${esc(h.key)} ${esc(h.title)}</b><small><span class="hdst">${esc(h.status)}</span><span>${esc(h.priority || 'ohne Priorität')}</span>${h.reporter ? `<span>von ${esc(h.reporter)}</span>` : ''}${h.assignee && !mine ? `<span>bei ${esc(h.assignee)}</span>` : ''}${h.age_h != null ? `<span class="${h.over_sla && mine ? 'chip warn' : ''}">offen seit ${hAge(h.age_h)}${h.over_sla && mine ? `, über ${info.sla_hours} h SLA` : ''}</span>` : ''}${h.idle_h != null ? `<span>zuletzt geändert vor ${hAge(h.idle_h)}</span>` : ''}${h.due ? `<span>fällig ${esc(h.due)}</span>` : ''}</small></div>
</div></div>`;
    body += `<div><h3>Beschreibung</h3>${!d ? '<div class="small quiet">Lade das Ticket …</div>' : d.error ? `<div class="banner bad">${esc(d.error)}</div>` : d.description ? `<div class="hdtxt">${esc(d.description)}</div>` : '<div class="small quiet">Keine Beschreibung.</div>'}</div>`;
    if (d && !d.error) body += `<div><h3>Letzte Kommentare <small>${d.comments.length}${d.comments_total > d.comments.length ? ' von ' + d.comments_total : ''}</small></h3>${d.comments.length ? `<div class="hdcm">${d.comments.map(c => `<div><small>${esc(c.author || 'unbekannt')}${c.age_h != null ? ' · vor ' + hAge(c.age_h) : ''}</small><p>${esc(c.body)}</p></div>`).join('')}</div>` : '<div class="small quiet">Noch keine Kommentare.</div>'}</div>`;
    body += `<div><h3>Entwicklung nötig?</h3>${hdJiraBtn(h.key)}</div>`;
    if (mine) body += `<div class="small quiet">Angeheftet läuft die Zeit auf ${esc(h.key)} (Bereich Helpdesk) und landet in den Zeitentwürfen.</div>
      <div class="fxfoot">${state.flow.pinned === e.id ? '<button data-fpin="">Fokus lösen</button>' : `<button class="primary" data-fpin="${esc(e.id)}">${ic('chevron2')} Als Fokus anheften, Zeit starten</button>`}${FOC() ? `<button data-fsess="${esc(e.id)}">${ic('clock')} Fokus-Sitzung</button>` : ''}<button data-hdreload="${esc(h.key)}">Neu lesen</button></div>`;
    else body += `<div class="small quiet">Nicht dir zugewiesen. Arbeitest du trotzdem daran, heftest du es an: Die Zeit läuft auf ${esc(h.key)} (Bereich Helpdesk), zuweisen bleibt im Helpdesk.</div>
      <div class="fxfoot"><button class="primary" data-fpin="hd:${esc(h.key)}">${ic('chevron2')} Als Fokus anheften, Zeit starten</button>${FOC() ? `<button data-fsess="hd:${esc(h.key)}">${ic('clock')} Fokus-Sitzung</button>` : ''}<button data-hdreload="${esc(h.key)}">Neu lesen</button></div>`;
  } else if (e.t === 'review') {
    body += `<div><h3>Merge Request</h3><div class="fxitem"><span class="pd ${esc(e.r.pipeline)}" title="${esc(pipelineLabel[e.r.pipeline] || e.r.pipeline)}"></span><div class="nm"><b>!${esc(e.r.iid)} ${esc(e.r.title)}</b><small>${esc(e.r.project)} · von ${esc(e.r.author)} · seit ${e.r.age_days} d</small></div><div class="ibtns"><button class="ibtn" data-topics="${esc(JSON.stringify({ host: e.r.host || 'gitlab', project_id: e.r.project_id, iid: e.r.iid }))}" title="Offene Review-Kommentare ansehen und exportieren">${ic('chat')} Offene Punkte</button><a class="ibtn" href="${esc(e.r.url)}" target="_blank" rel="noopener">${ic('ext')} Öffnen</a></div></div></div>`;
  } else {
    const c = e.c;
    if (c.key && !c.local && !c.idea_id) body += `<div><h3>Tickets in diesem Task <small>${1 + (c.companions || []).length}</small></h3><div class="fxitem"><div class="nm"><b>${esc(c.key)} ${typeChip(c.type)}</b><small>${esc(c.status || '')} · Task</small></div></div>
      ${(c.companions || []).map(x => `<div class="fxitem"><div class="nm"><b>${x.url ? `<a href="${esc(x.url)}" target="_blank" rel="noopener">${esc(x.key)}</a>` : esc(x.key)} ${typeChip(x.type)}</b><small>${esc(x.summary)} · ${esc(x.status || '')} · ${esc(x.why || '')}</small></div></div>`).join('')}
      <button class="quiet-btn" data-grp="${esc(c.key)}">Gruppieren …</button></div>`;
    if (!c.idea_id) {
      body += `<div><h3>Teilschritte <small>Kleine Haken${F().score === false ? '' : ', je erledigter +3 XP'}</small></h3><ul class="ck">${e.d.checklist.map(x => `<li class="${x.done ? 'done' : ''}"><input type="checkbox" data-fck="${x.id}" ${x.done ? 'checked' : ''} aria-label="${esc(x.text)}"><span>${esc(x.text)}</span><button data-fckdel="${x.id}" title="Entfernen" aria-label="Entfernen">${ic('x')}</button></li>`).join('')}</ul>
        <div class="ckadd"><input id="fxCkNew" maxlength="200" placeholder="${e.d.checklist.length ? 'Nächster kleiner Schritt …' : 'In kleine Schritte zerlegen, z. B. «Test für Retry schreiben»'}" autocomplete="off"><button data-fckadd="1">Hinzufügen</button></div></div>`;
    }
    if (c.items.length) body += `<div><h3>MRs und Branches <small>${c.items.length}</small></h3>${c.items.map(x => fxItem(c, x)).join('')}</div>`;
    else if (!c.idea_id) body += `<div><h3>MRs und Branches</h3><div class="small quiet">Noch keiner. Ein Branch mit ${esc(c.key || 'dem Key')} im Namen erscheint hier von selbst; sonst einen Branch auf die Karte im Board ziehen.</div></div>`;
    if (state.agents && state.agents.enabled && !c.idea_id) body += `<div><h3>Agenten</h3>${agentRow(c.id, c.key || '', c.title, c.url, c.items)}</div>`;
    if (c.idea_id) body += ideaHtml(c.idea_id);
    if (!c.idea_id) body += `<div><h3>Verlauf <small>Was du entschieden hast</small></h3><ol class="aud short" id="fxHist">${HIST.id === c.id ? audRows(HIST.rows, true) : '<li class="quiet small" style="display:block">lädt …</li>'}</ol></div>`;
    const foot = [];
    if (!c.idea_id) foot.push(state.flow.pinned === c.id ? '<button data-fpin="">Fokus lösen</button>' : `<button data-fpin="${esc(c.id)}">${ic('chevron2')} Als Fokus anheften</button>`);
    if (!c.idea_id && FOC()) foot.push(`<button data-fsess="${esc(c.id)}">${ic('clock')} Fokus-Sitzung</button>`);
    if (c.idea_id) foot.push('<button data-fxboard="1">Im Board einplanen</button>');
    else foot.push('<button data-fxboard="1">Im Board zeigen</button>');
    if (c.local && !c.idea_id) foot.push(`<button data-fxdel="1">Aufgabe löschen</button>`);
    body += `<div class="fxfoot">${foot.join('')}${c.pools.length ? `<span class="small quiet">Kategorie: ${c.pools.map(p => esc(p.name)).join(', ')}</span>` : ''}</div>`;
  }
  $('fx').innerHTML = `<div class="fxhead">${head}</div><div class="fxbody">${body}</div>`;
  keep.forEach(k => { const el = $(k.id); if (el) { el.value = k.v; if (k.f) el.focus(); } });
  if (e.t === 'card' && !e.c.idea_id) loadHist(e.c);
}
// Verlauf je Vorhaben: Ticket plus alle Branches der Karte. Bei jedem Neuzeichnen frisch, aber höchstens einmal je Sekunde.
let HIST = { id: null, rows: [], t: 0, sig: '' };
async function loadHist(c) {
  const targets = [c.id, c.key, ...(c.items || []).map(x => x.ref || (x.project_id != null && x.branch ? `${x.project_id}:${x.branch}` : ''))].filter(Boolean);
  const sig = c.id + '|' + targets.join(',');
  if (HIST.sig === sig && Date.now() - HIST.t < 1000) return;
  HIST.sig = sig; HIST.t = Date.now();
  try {
    const r = await api('GET', '/api/audit?limit=30&' + [...new Set(targets)].map(t => 'target=' + encodeURIComponent(t)).join('&'));
    HIST = { ...HIST, id: c.id, rows: r.rows };
    const el = $('fxHist'); if (el && FXID === c.id) el.innerHTML = audRows(r.rows, true);
  } catch (e) { const el = $('fxHist'); if (el) el.innerHTML = `<li class="quiet small" style="display:block">${esc(e.message)}</li>`; }
}
function reviewChips(x) {
  if (!x.iid || (x.reviewers == null && x.approved == null)) return '';
  const out = [];
  const by = x.approved_by || [];
  if (by.length) out.push(`<span class="chip sq-ok" title="Freigegeben von ${esc(by.join(', '))}">${ic('check')} ${esc(by.map(u => '@' + u).join(' '))}</span>`);
  if (x.upvotes) out.push(`<span class="chip sq-ok" title="Daumen hoch">👍 ${x.upvotes}</span>`);
  if ((x.reviewers || []).length) { if (!by.length) out.push(`<span class="chip" title="Reviewer">${ic('users')} ${esc(x.reviewers.map(u => '@' + u).join(' '))}</span>`); }
  else if (!by.length) out.push('<span class="chip warn">kein Reviewer</span>');
  if (x.approvals_left) out.push(`<span class="chip warn" title="Regeln im Projekt">noch ${x.approvals_left} Freigabe${x.approvals_left === 1 ? '' : 'n'}</span>`);
  return out.join('');
}
function accHtml(list) {
  if (!list.length) return '';
  const when = ts => ts ? new Date(ts * 1000).toLocaleString('de-CH', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' }) : '';
  return `<div><h3>Abnahme <small>gilt nur für den Commit, auf dem getestet wurde</small></h3>${list.map(a => a.state === 'ok'
    ? `<div class="small"><span class="chip sq-ok">${ic('check')} ${esc(a.label)} auf ${esc(a.sha)}</span> ${esc(when(a.ts))}${a.env ? ' · ' + esc(a.env) : ''}${a.note ? ' · ' + esc(a.note) : ''}</div>`
    : a.state === 'stale' ? `<div class="small"><span class="chip warn">${esc(a.label)}: getestet ${esc(a.sha)}, jetzt ${esc(a.cur)}</span> Test vom ${esc(when(a.ts))} gilt nicht mehr</div>`
    : `<div class="small"><span class="chip warn">${esc(a.label)}: noch nicht abgenommen</span> aktueller Stand ${esc(a.cur || '?')}</div>`).join('')}</div>`;
}
function fxItem(c, x) {
  const ms = MSTAT[x.merge_status];
  const sq = SQ[x.sonar] ? `<a class="chip ${SQ[x.sonar][1]}" href="${esc(x.sonar_url || '#')}" target="_blank" rel="noopener" title="${esc(x.sonar_detail || '')}">${esc(SQ[x.sonar][0])}</a>${trendBadge(x)}` : '';
  const b = [`<a class="ibtn" href="${esc(x.url)}" target="_blank" rel="noopener" title="In ${x.host === 'github' ? 'GitHub' : 'GitLab'} öffnen">${ic('ext')} ${x.iid ? (x.host === 'github' ? 'PR' : 'MR') : 'Branch'}</a>`];
  if (x.pipeline_url) b.push(`<a class="ibtn" href="${esc(x.pipeline_url)}" target="_blank" rel="noopener">${ic('gear')} Pipeline</a>`);
  if (SQ_HAS[x.sonar]) b.push(`<button class="ibtn" ${sqRepAttrs(x)} title="Findings als Markdown in die Zwischenablage (Pfade und Meldungen, kein Quelltext)">${ic('copy')} Report</button>`);
  if (x.review_app) b.push(`<a class="ibtn" href="${esc(x.review_app)}" target="_blank" rel="noopener" title="${esc(x.review_env || 'Review-App')}">${ic('globe')} Review-App</a>`);
  if (x.iid && x.ide) b.push(`<button class="ibtn" data-ide="${esc(JSON.stringify({ host: x.host || 'gitlab', project_id: x.project_id, iid: x.iid }))}" title="Worktree genau auf ${esc((x.sha || '').slice(0, 8))} und IntelliJ öffnen">${ic('ide')} IntelliJ</button>`);
  if (x.iid) b.push(`<button class="ibtn" data-topics="${esc(JSON.stringify({ host: x.host || 'gitlab', project_id: x.project_id, iid: x.iid }))}" data-tcard="${esc(c.id)}" title="Offene Review-Kommentare ansehen, als Prompt oder JSON exportieren, einem Agenten geben">${ic('chat')} Offene Punkte</button>`);
  if (!x.iid && x.create_mr_url) b.push(`<a class="ibtn" href="${esc(x.create_mr_url)}" target="_blank" rel="noopener">${ic('mr')} ${x.host === 'github' ? 'PR' : 'MR'} erstellen</a>`);
  if (!c.key && state.jira && state.jira.ok) {
    b.push(`<button class="ibtn" data-tk="1" data-p="${x.project_id}" data-i="${x.iid ?? ''}" data-b="${esc(x.branch)}" data-cu="">${ic('ticket')} Ticket anlegen</button>`);
  }
  if (state.jira && state.jira.ok) b.push(`<button class="ibtn" data-assign="1" data-p="${x.project_id}" data-b="${esc(x.branch)}" data-t="${esc(x.title || c.title)}" data-iid="${x.iid ?? ''}">${ic('link')} ${c.key ? 'Ticket ändern' : 'Zuordnen'}</button>`);
  if (x.iid) b.push(`<button class="ibtn" data-mrtry="${esc(JSON.stringify({ host: x.host || 'gitlab', project_id: x.project_id, iid: x.iid }))}" title="Prompts, git-Befehle und Review-Umgebung">${ic('flask')} Ausprobieren</button>`);
  return `<div class="fxitem">${x.iid ? `<span class="pd ${esc(x.pipeline)}" title="${esc(pipelineLabel[x.pipeline] || x.pipeline)}"></span>` : branchIcon(x.branch, 20)}
    <div class="nm"><b title="${esc(x.branch)}">${x.iid ? esc(mrNo(x)) + ' ' : ''}${esc(x.title || x.branch)}</b><small><span class="picn">${branchIcon(x.branch, 15)}<code data-copy="${esc(x.branch)}" title="Klick kopiert den Branch">${esc(short(x.branch, 48))}</code></span><span class="picn">${repoIcon(x.project, 15)}${esc(x.project)}</span>${x.draft ? '<span class="chip draft">Draft</span>' : ''}${ms && !(x.draft && x.merge_status === 'draft_status') ? `<span class="chip ${ms[1]}">${ms[0]}</span>` : ''}${reviewChips(x)}${sq}${x.by_agent ? '<span class="chip agent">Agent</span>' : ''}${x.ide_wt ? `<span class="chip ${x.ide_wt.stale ? 'warn' : 'tk'}" title="${esc(x.ide_wt.path)}">IntelliJ auf ${esc(x.ide_wt.sha.slice(0, 8))}${x.ide_wt.stale ? ' (veraltet)' : ''}<button class="x" data-ideclose="${esc(x.ref || (x.project_id + ':' + x.branch))}" title="Worktree entfernen" aria-label="Worktree entfernen">×</button></span>` : ''}${x.manual ? `<button class="quiet-btn" data-unlink="1" data-p="${x.project_id}" data-b="${esc(x.branch)}" title="Von Hand verknüpft. Verknüpfung lösen">Lösen</button>` : ''}</small></div>
    <div class="ibtns">${b.join('')}</div></div>`;
}
function openFx(id) { FXID = id; renderFx(); const p = $('fx'); p.hidden = false; document.body.classList.add('fxopen'); requestAnimationFrame(() => p.classList.add('on')); }
function closeFx() { FXID = null; const p = $('fx'); p.classList.remove('on'); document.body.classList.remove('fxopen'); setTimeout(() => { if (!FXID) p.hidden = true; }, 200); }
// 0.39: Klicks im Detail-Panel tun etwas (Nutzungsbericht: 30 tote Klicks auf Code, Namen, Chips und Titel).
// Code und Namen kopieren, Chips erklären sich, der Titel eines MR oder Branches öffnet ihn.
$('fx').addEventListener('click', ev => {
  const t = ev.target;
  if (!t.closest || t.closest('a, button, input, textarea, select, label, summary')) return;
  const cp = t.closest('code, .picn, [data-copy]');
  if (cp) { const v = cp.dataset.copy || (cp.querySelector('code') || cp).textContent.trim(); if (v) copyText(v, 'Kopiert'); return; }
  const chip = t.closest('.chip[title]');
  if (chip) { toast(chip.title); return; }
  const it = t.closest('.fxitem'), a = it && t.closest('.nm b') && it.querySelector('.ibtns a.ibtn[href^="http"]');
  if (a) window.open(a.href, '_blank', 'noopener');
});
function fEntry(id) { return focusEntries().find(x => x.id === id); }
async function fStage(c, stage) {
  await post('/api/board/stage', c.key ? { key: c.key, stage } : { ref: c.id, stage });
}
async function doNext(e, btn) {
  const n = e.d.next, a = n.action || {};
  try {
    if (a.run) return openRunDlg(a.run);
    if (a.open) return openFx(a.open);
    if (a.topics) return openTopics(a.topics, e.t === 'card' ? e.c : null);
    if (a.tiny) { const r = await post('/api/flow/tiny', a.tiny); toast(`${r.key} angelegt (Kategorie ${r.pool}). Der Branch hängt jetzt daran.`); burstAt(btn); closeFx(); await load(); return; }
    if (n.id === 'plan') { setView('board'); return; }
    if (a.check) { await fCheck(a.check, true, btn); return; }
    if (a.accept && e.t === 'card') {
      const note = FXID === e.id && $('fxNote') ? $('fxNote').value : '', envv = FXID === e.id && $('fxEnv') ? $('fxEnv').value : '';
      const r = await post('/api/flow/accept', { id: e.c.id, note, env: envv });
      toast(`Abgenommen auf ${r.commits.map(c => c.sha).join(', ') || 'dem aktuellen Stand'}. Neue Commits machen das ungültig.`);
      burstAt(btn); await load(); return;
    }
    if (a.report) {
      const r = await api('GET', `/api/sonar/report?project_id=${encodeURIComponent(a.report.project_id)}&iid=${encodeURIComponent(a.report.iid ?? '')}&branch=${encodeURIComponent(a.report.branch || '')}`);
      await copyText(r.text, 'Sonar-Report'); toast(`Report kopiert: ${r.issues} Findings. Einem Agenten geben oder selbst abarbeiten.`); return;
    }
    if (a.copy) { await copyText(a.copy, 'Befehl'); toast('Befehl kopiert. Im Repository einfügen, dann erscheint der Branch hier.'); }
    if (a.stage && e.t === 'card') { await fStage(e.c, a.stage); burstAt(btn); await load(); return; }
    if (a.url) window.open(a.url, '_blank', 'noopener');
  } catch (err) { toast(err.message); }
}
async function fCheck(id, done, el) {
  try {
    const r = await post('/api/flow/toggle', { id, done });
    if (r.done) burstAt(el);
    await load();
  } catch (err) { toast(err.message); }
}
async function fQuickAdd() {
  const i = $('fAdd'), v = i.value.trim();
  if (!v) return;
  const isKey = /^[A-Za-z][A-Za-z0-9_]{1,19}-\d{1,9}$/.test(v);
  i.value = '';
  await act(() => post('/api/board/add', { title: v, stage: isKey ? 'planned' : 'idea', pool_id: null }), isKey ? `${v.toUpperCase()} eingeplant` : 'Im Ideenpool. Mit Kategorie einplanen, wenn es losgeht.');
}
$('fAddBtn').onclick = fQuickAdd;
$('fAdd').addEventListener('keydown', ev => { if (ev.key === 'Enter') { ev.preventDefault(); fQuickAdd(); } });
document.addEventListener('toggle', ev => { const d = ev.target; if (d.dataset && d.dataset.fgrp) LS.set('fopen.' + d.dataset.fgrp, d.open); }, true);
document.addEventListener('click', async ev => {
  const t = ev.target;
  const go = t.closest('[data-fgo]');
  if (go) { ev.stopPropagation(); const e = fEntry(go.dataset.fgo); if (e) await doNext(e, go); return; }
  const op = t.closest('[data-fopen]'); if (op) { openFx(op.dataset.fopen); return; }
  const pn = t.closest('[data-fpin]');
  if (pn) { ev.stopPropagation(); try { await post('/api/flow/pin', { id: pn.dataset.fpin || null }); toast(pn.dataset.fpin ? 'Als Fokus angeheftet' : 'Fokus gelöst'); await load(); } catch (err) { toast(err.message); } return; }
  const dn = t.closest('[data-fdone]');
  if (dn) { ev.stopPropagation(); const e = fEntry(dn.dataset.fdone); if (!e) return;
    try { const r = await post('/api/flow/complete', { id: e.c.id, phase: e.d.phase }); burstAt(dn); toast(`Weiter zu «${STAGE_LABEL[r.stage] || r.stage}»`); await load(); } catch (err) { toast(err.message); } return; }
  const sk = t.closest('[data-fskip]');
  if (sk) { fSkip.add(sk.dataset.fskip); try { sessionStorage.setItem('tinyops.skip', JSON.stringify([...fSkip])); } catch (e) { /* egal */ } renderFocus(); return; }
  const ax = t.closest('[data-falx]'); if (ax) { fSkip.add('al:' + ax.dataset.falx); renderFocus(); return; }
  if (t.closest('[data-fset]')) { setView('settings'); return; }
  if (t.closest('[data-fidea]')) { openIdeaDrop(); return; }
  if (t.closest('[data-fxclose]')) { closeFx(); return; }
  const e = FXID && fEntry(FXID);
  const st = t.closest('#fx li[data-st]');
  if (st && e && e.t === 'card') { try { await fStage(e.c, st.dataset.st); burstAt(st); await load(); } catch (err) { toast(err.message); } return; }
  if (t.closest('[data-fxauto]') && e) { await act(() => post('/api/board/remove', { key: e.c.id }), 'Station wieder aus den Daten'); return; }
  if (t.closest('[data-fxboard]')) { closeFx(); setView('board'); return; }
  if (t.closest('[data-fxdel]') && e) { if (confirm(`Aufgabe ${e.c.key} «${e.c.title}» löschen?`)) { closeFx(); await act(() => post('/api/board/remove', { key: e.c.key }), 'Gelöscht'); } return; }
  const ckd = t.closest('[data-fckdel]'); if (ckd) { await act(() => post('/api/flow/delete', { id: +ckd.dataset.fckdel })); return; }
  if (t.closest('[data-fckadd]') && e) { const v = $('fxCkNew').value.trim(); if (!v) return; $('fxCkNew').value = ''; await act(() => post('/api/flow/add', { key: e.c.id, text: v })); $('fxCkNew') && $('fxCkNew').focus(); return; }
  const tk = t.closest('#fx [data-tk]'); if (tk) { openTicket(tk); return; }
  const h2j = t.closest('[data-hd2jira]'); if (h2j) { openTicket(null, null, h2j.dataset.hd2jira); return; }
  const hca = t.closest('[data-hckadd]');
  if (hca) { const inp = $('hCkNew'), v = inp.value.trim(); if (!v) { inp.focus(); return; } await act(() => post('/api/flow/add', { key: hca.dataset.hckadd, text: v })); $('hCkNew') && $('hCkNew').focus(); return; }

  const row = t.closest('#viewFocus .frow, #viewFocus .hero');
  if (!row && FXID && !t.closest('#fx, header, #fbar, dialog, #fmode, a, button, input, select, textarea, summary, label, [data-fopen], .rcard, .bcard[data-bid], .slot[data-skey]')) { closeFx(); return; }   // 0.30: Klick auf eine Board-Karte öffnet, statt sofort wieder zu schliessen
  if (row && !t.closest('a, button, select, input, textarea, .hwork')) { fSel = [...document.querySelectorAll('#viewFocus [data-fid]')].indexOf(row); openFx(row.dataset.fid); }
});
document.addEventListener('change', ev => { const c = ev.target.closest && ev.target.closest('[data-fck]'); if (c) fCheck(+c.dataset.fck, c.checked, c); });
document.addEventListener('keydown', ev => {
  if (ev.target.id === 'fxCkNew' && ev.key === 'Enter') { ev.preventDefault(); document.querySelector('[data-fckadd]').click(); return; }
  if (ev.target.id === 'hCkNew' && ev.key === 'Enter') { ev.preventDefault(); document.querySelector('[data-hckadd]').click(); return; }
  if (ev.key === 'Escape' && FXID && !document.querySelector('dialog[open]')) { closeFx(); return; }
  if (/INPUT|TEXTAREA|SELECT/.test(document.activeElement.tagName) || ev.ctrlKey || ev.metaKey || ev.altKey || document.querySelector('dialog[open]')) return;
  if (view !== 'focus') return;
  const rows = [...document.querySelectorAll('#viewFocus [data-fid]')];
  const sel = i => { fSel = Math.max(0, Math.min(rows.length - 1, i)); rows.forEach((r, k) => r.classList.toggle('sel', k === fSel)); rows[fSel] && rows[fSel].scrollIntoView({ block: 'nearest' }); if (FXID && rows[fSel]) openFx(rows[fSel].dataset.fid); };
  if (ev.key === 'j' || ev.key === 'ArrowDown') { ev.preventDefault(); sel(fSel + 1); }
  else if (ev.key === 'k' || ev.key === 'ArrowUp') { ev.preventDefault(); sel(fSel - 1); }
  else if (ev.key === 'Enter' && rows[Math.max(0, fSel)]) { ev.preventDefault(); openFx(rows[Math.max(0, fSel)].dataset.fid); }
  else if (ev.key === 'a') { const r = rows[Math.max(0, fSel)]; const e = r && fEntry(r.dataset.fid); if (e) { ev.preventDefault(); doNext(e, r.querySelector('[data-fgo]') || r); } }
  else if (ev.key === 'n') { ev.preventDefault(); $('fAdd').focus(); }
});
