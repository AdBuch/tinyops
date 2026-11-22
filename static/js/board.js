// Board und Ideen: Karten je Station, Kategorien, Ideen bewerten und festhalten.
// ---- Board: eine Karte pro Aufgabe, alle MRs und Branches eines Tickets zusammengeführt
const STAGES = ['idea', 'planned', 'impl', 'review', 'test', 'tested', 'done'];
const STAGE_LABEL = { idea: 'Ideen', planned: 'Geplant', impl: 'Umsetzung', review: 'Prüfen', test: 'Testen', tested: 'Mergen', done: 'Fertig' };
$('bAddStage').innerHTML = STAGES.filter(x => x !== 'idea' || true).map(x => `<option value="${x}" ${x === 'planned' ? 'selected' : ''}>${STAGE_LABEL[x]}</option>`).join('');
let selPool = LS.get('bPool', 0);    // 0 = alle
let showOrph = LS.get('bOrph', true);
$('bOrph').checked = showOrph;
$('bOrph').addEventListener('change', ev => { showOrph = ev.target.checked; LS.set('bOrph', showOrph); renderBoard(); });
function poolOptions(sel, placeholder) {
  const ps = (state.board && state.board.pools) || [];
  return (placeholder ? '<option value="">Kategorie wählen …</option>' : '<option value="">ohne Kategorie</option>') + ps.map(p => `<option value="${p.id}" ${p.id === sel ? 'selected' : ''}>${esc(p.name)}</option>`).join('');
}
function boardCard(c) {
  const isIdea = !!c.idea_id;
  const d = state.flow && state.flow.items[c.id], n = d && d.next;
  const key = c.key ? `<span class="bkey ${c.local ? 'loc' : 'jira'}">${esc(c.key)}</span>` : `<span class="bkey loc">${c.orphan ? 'ohne Ticket' : 'Idee'}</span>`;
  const chips = [c.status && !c.local ? `<span class="chip" title="Status in Jira">${esc(c.status)}</span>` : '',
    ...c.pools.map(p => `<span class="chip tk" title="Kategorie">${esc(p.name)}${c.idea_id ? '' : `<button class="x" data-bpoolrem="${esc(c.id)}" data-pool="${p.id}" title="Aus der Kategorie nehmen" aria-label="Aus der Kategorie nehmen">×</button>`}</span>`)].join('');
  const title = c.title || (c.known === false ? '(Ticket nicht lesbar)' : '');
  const refs = c.items.map(x => `<span class="mrchip" draggable="true" data-rp="${x.project_id}" data-rb="${esc(x.branch)}" title="${esc(x.project)} · ${esc(x.branch)}${x.draft ? ' · Draft' : ''} (ziehen = mit einer anderen Karte verknüpfen)"><span class="pd ${esc(x.pipeline)}"></span>${x.iid ? '!' + esc(x.iid) : esc(short(x.branch, 24))}${x.sonar === 'ERROR' ? ' <span class="sqdot bad" title="Quality Gate rot">●</span>' : ''}</span>`).join('');
  const runs = ((state.agents && state.agents.runs) || []).filter(r => r.ticket === c.id && (r.active || r.status === 'zugewiesen')).slice(0, 2)
    .map(r => `<button class="chip ${AG_ST[r.status] || ''}" data-arun="${r.id}">${r.active ? '<span class="agspin"></span>' : ''}${esc(r.agent_name)}</button>`).join('');
  const nx = n && n.kind !== 'done' && !isIdea ? `<div class="bnext k-${esc(n.kind)}" title="${esc(n.why)}">${OWNER[n.owner] ? ic(OWNER[n.owner]) : (n.kind === 'blocked' ? ic('alert') : ic('chevron2'))}<span>${esc(n.label)}</span></div>` : '';
  const act = isIdea ? `<div class="bplan"><select data-bplansel="${c.idea_id}" aria-label="Kategorie wählen">${poolOptions(selPool, true)}</select><button data-bplan="${c.idea_id}" title="Als Aufgabe in «Geplant» übernehmen (braucht eine Kategorie)">Planen</button></div>` : '';
  const comps = (c.companions || []).map(x => `<span class="comp" title="${esc(x.summary)}${x.why ? ' · ' + esc(x.why) : ''}">+ ${esc(x.key)} ${typeChip(x.type)}</span>`).join('');
  return `<div class="bcard ${n ? 'k-' + esc(n.kind) : ''}" draggable="true" data-bid="${esc(c.id)}" ${c.key ? `data-bkey="${esc(c.key)}"` : ''} title="Klick: Details · Ziehen: andere Station">
    <div class="btop">${key}${c.type && c.type !== 'Idee' && !c.local ? typeChip(c.type) : ''}${chips}</div><div class="bsum">${esc(title)}</div>${comps ? `<div class="comps">${comps}</div>` : ''}${refs || runs ? `<div class="links">${refs}${runs}</div>` : ''}${nx}${act ? `<div class="bact">${act}</div>` : ''}</div>`;
}
document.addEventListener('click', ev => {
  const b = ev.target.closest && ev.target.closest('.bcard[data-bid]');
  if (b && !ev.target.closest('a, button, select, input, .mrchip')) openFx(b.dataset.bid);
});
function renderBoard() {
  const b = state && state.board, el = $('bcols');
  if (!b || !state.configured) { el.innerHTML = '<div class="bempty">Noch nicht verbunden.</div>'; return; }
  if (selPool && !b.pools.some(p => p.id === selPool)) { selPool = 0; LS.set('bPool', 0); }
  renderPoolBar(b);
  const cards = b.cards.filter(c => (showOrph || !c.orphan) && (!selPool || c.pools.some(p => p.id === selPool)));
  const col = st => cards.filter(c => colStage(c) === st).sort((a, z) => (a.key || a.title).localeCompare(z.key || z.title, 'de', { numeric: true }));
  const wip = state.jira ? ` · ${state.jira.count} von ${state.jira.limit} im Jira-Panel` : '';
  el.innerHTML = `<div class="bgroup">In Arbeit${esc(wip)}</div>` + STAGES.map((st, n) => {
    const cs = col(st), work = ['impl', 'review', 'test'].includes(st);
    return `<div class="bcol ${work ? 'work' : ''}" data-stage="${st}" style="grid-column:${n + 1}"><div class="bcolhead"><h3>${STAGE_LABEL[st]}</h3><span class="count">${cs.length}</span></div>
      ${cs.map(boardCard).join('') || '<div class="bempty">Leer</div>'}${st === 'done' && b.done_hidden ? `<div class="bempty">+ ${b.done_hidden} ältere nicht angezeigt</div>` : ''}</div>`;
  }).join('');
}
function renderPoolBar(b) {
  const total = b.cards.length;
  const old = $('poolNew'), oldV = old ? old.value : '', hadFocus = old && old === document.activeElement;
  $('bpools').innerHTML = `<span class="bpool ${selPool ? '' : 'on'}" data-poolsel="0">Alle <span class="count">${total}</span></span>` +
    b.pools.map(p => `<span class="bpool ${selPool === p.id ? 'on' : ''}" data-poolsel="${p.id}" data-pool="${p.id}" title="Karten hierher ziehen, um sie dieser Kategorie zuzuordnen">${esc(p.name)} <span class="count">${p.count}</span></span>`).join('') +
    `<input type="text" id="poolNew" placeholder="Neue Kategorie, z. B. Agenten-VM" maxlength="60" autocomplete="off"><button id="poolNewBtn">Anlegen</button>` +
    (selPool ? `<button class="quiet-btn" data-poolren="${selPool}">Umbenennen</button><button class="quiet-btn" data-pooldel="${selPool}">Löschen</button>` : '');
  if (oldV) { $('poolNew').value = oldV; if (hadFocus) $('poolNew').focus(); }
  const sel = $('bAddPool'), cur = sel.value;
  sel.innerHTML = poolOptions(selPool || (+cur || 0), false);
}
async function boardAdd() {
  const i = $('bAddText'), v = i.value.trim();
  if (!v) return;
  const stage = $('bAddStage').value, pool = $('bAddPool').value;
  if (!pool && stage !== 'idea' && !/^[A-Za-z][A-Za-z0-9_]{1,19}-\d{1,9}$/.test(v)) { toast('Ab «Geplant» braucht eine Aufgabe ohne Jira eine Kategorie. Wähle eine oder lege sie im Ideenpool ab.'); return; }
  i.value = '';
  await act(() => post('/api/board/add', { title: v, stage, pool_id: pool ? +pool : null }), 'Hinzugefügt');
}
$('bAdd').onclick = boardAdd;
$('bAddText').addEventListener('keydown', ev => { if (ev.key === 'Enter') { ev.preventDefault(); boardAdd(); } });
$('viewBoard').addEventListener('click', ev => {
  const ps = ev.target.closest('[data-poolsel]');
  if (ps) { selPool = +ps.dataset.poolsel; LS.set('bPool', selPool); renderBoard(); }
});
$('viewBoard').addEventListener('keydown', ev => { if (ev.key === 'Enter' && ev.target.id === 'poolNew') { ev.preventDefault(); $('poolNewBtn').click(); } });
$('viewBoard').addEventListener('click', async ev => {
  const b = ev.target.closest('button');
  if (!b) return;
  const find = id => (state.board.cards.find(c => c.id === id) || {});
  if (b.id === 'poolNewBtn') {
    const i = $('poolNew'); if (!i.value.trim()) return;
    const v = i.value; i.value = '';
    const r = await act(() => post('/api/pools', { name: v }), 'Kategorie angelegt');
    if (r && r.id) { selPool = r.id; LS.set('bPool', selPool); renderBoard(); }
    return;
  }
  if (b.dataset.poolren) { const n = prompt('Neuer Name', ((state.board.pools.find(p => p.id === +b.dataset.poolren) || {}).name) || ''); if (n && n.trim()) await act(() => post('/api/pools/rename', { id: +b.dataset.poolren, name: n })); return; }
  if (b.dataset.pooldel) {
    const p = state.board.pools.find(x => x.id === +b.dataset.pooldel) || {};
    if (confirm(`Kategorie «${p.name}» löschen? Aufgaben, Tickets und Branches bleiben bestehen, verlieren nur die Zuordnung.`)) { selPool = 0; LS.set('bPool', 0); await act(() => post('/api/pools/delete', { id: +b.dataset.pooldel }), 'Kategorie gelöscht'); }
    return;
  }
  if (b.dataset.bpoolrem) {
    const c = find(b.dataset.bpoolrem);
    const body = c.key ? { key: c.key, pool_id: +b.dataset.pool } : { ref: c.id, pool_id: +b.dataset.pool };
    try { await post('/api/board/unassign', body); toast('Aus der Kategorie genommen'); await load(); }
    catch (e) {
      if (e.data && e.data.to_pool && confirm(e.message + '\n\nDie Aufgabe kommt zurück in die Ideen und behält ihren Text.')) {
        try { await post('/api/board/unassign', Object.assign({ to_pool: true }, body)); toast('Zurück im Ideenpool'); await load(); } catch (e2) { toast(e2.message); }
      } else if (!(e.data && e.data.to_pool)) toast(e.message);
    }
    return;
  }
  if (b.dataset.bmove) {
    const c = find(b.dataset.bmove), to = STAGES[STAGES.indexOf(c.stage) + (+b.dataset.dir)];
    if (to) await moveCard(c, to);
  } else if (b.dataset.bplan) {
    const sel = document.querySelector(`[data-bplansel="${b.dataset.bplan}"]`);
    if (!sel.value) { toast('Wähle zuerst eine Kategorie. Ohne Kategorie bleibt die Idee im Ideenpool.'); return; }
    await act(() => post('/api/board/plan_idea', { id: +b.dataset.bplan, pool_id: +sel.value }), 'Geplant');
  } else if (b.dataset.brem) {
    if (b.dataset.local === '1' && !confirm('Aufgabe «' + b.dataset.t + '» löschen?')) return;
    await act(() => post('/api/board/remove', { key: b.dataset.brem }), b.dataset.local === '1' ? 'Gelöscht' : 'Zurückgesetzt');
  }
});
// Spalte = Station aus dem Ablauf, solange niemand von Hand verschoben hat (sonst wären Board und Fokus uneins)
const PHASE_COL = ['planned', 'impl', 'impl', 'impl', 'review', 'test', 'tested', 'done'];
function colStage(c) {
  if (c.idea_id || c.manual_stage) return c.stage;
  const d = state.flow && state.flow.items[c.id];
  return d ? PHASE_COL[d.phase] : c.stage;
}
function moveCard(c, stage) {
  if (!c || colStage(c) === stage || c.idea_id) return Promise.resolve();
  const body = c.key ? { key: c.key, stage } : { ref: c.id, stage };
  return act(() => post('/api/board/stage', body), STAGE_LABEL[stage]);
}
// ------------------------------------------------ Ideen bewerten und als Ticket ausformulieren (0.20)
const REC_T = { jetzt: 'Jetzt angehen', 'später': 'Später', verwerfen: 'Verwerfen' };
function assessLine(a) {
  return [a.recommendation ? REC_T[a.recommendation] : '', a.category, a.benefit ? 'Nutzen ' + a.benefit : '', a.effort ? 'Aufwand ' + a.effort : ''].filter(Boolean).join(' · ');
}
function ideaHtml(id) {
  const i = (state.ideas || []).find(x => x.id === id);
  if (!i) return '';
  const a = i.assessment;
  const sim = a && a.similar && a.similar.length ? `<div class="small">Ähnlich: ${a.similar.map(x => `<span class="chip" title="Übereinstimmung ${Math.round(x.score * 100)} %">${esc(x.id)} ${esc(x.label.slice(0, 60))}</span>`).join(' ')}</div>` : '';
  const dups = a && a.duplicates && a.duplicates.length ? `<div class="small">Dubletten laut Modell: ${a.duplicates.map(n => '#' + n).join(', ')}</div>` : '';
  const llmOk = state.ticket && state.ticket.llm;
  return `<div><h3>Bewertung <small>${a ? (a.source === 'modell' ? 'Vorschlag des lokalen Modells' + (a.model ? ' (' + esc(a.model) + ')' : '') : 'von dir') : 'noch keine'}</small></h3>
    <div class="ideaas">${a ? `<div><span class="rec ${esc(a.recommendation)}">${esc(REC_T[a.recommendation] || a.recommendation)}</span> · ${esc([a.category, a.benefit ? 'Nutzen ' + a.benefit + '/3' : '', a.effort ? 'Aufwand ' + a.effort : ''].filter(Boolean).join(' · '))}</div>
      ${a.why ? `<div class="small">${esc(a.why)}</div>` : ''}${a.effort_why ? `<div class="small quiet">Aufwand: ${esc(a.effort_why)}</div>` : ''}${dups}${sim}` : '<div class="small quiet">Kategorie, Nutzen, Aufwand und Dubletten. Die Bewertung bleibt ein Vorschlag; entscheiden tust du.</div>'}
      <div class="grid"><button data-iassess="${i.id}" ${llmOk ? '' : 'disabled title="Lokales Modell nicht eingerichtet (Einstellungen → KI-Entwurf)"'}>${ic('bulb')} ${a ? 'Neu bewerten' : 'Mit dem lokalen Modell bewerten'}</button><button data-iself="${i.id}">Selbst bewerten</button><button class="primary" data-iticket="${i.id}">${ic('ticket')} Ticket daraus</button></div>
      <div id="ideaForm${i.id}"></div></div></div>
    ${i.text.includes('\n') ? `<div><h3>Idee</h3><div class="small" style="white-space:pre-wrap">${esc(i.text)}</div></div>` : ''}`;
}
document.addEventListener('click', async ev => {
  const t = ev.target.closest && ev.target.closest('[data-iassess],[data-iself],[data-iticket],[data-isave],[data-ide],[data-ideclose]');
  if (!t) return;
  ev.preventDefault(); ev.stopPropagation();
  if (t.dataset.iassess) {
    await busy(t, 'Das Modell bewertet …', async () => {
      try { const a = await post(`/api/ideas/${t.dataset.iassess}/assess`, {}); toast(`Bewertet: ${assessLine(a)}`); await load(); } catch (e) { toast(e.message); }
    });
    return;
  }
  if (t.dataset.iself) {
    const id = t.dataset.iself, box = $('ideaForm' + id), a = ((state.ideas || []).find(x => x.id === +id) || {}).assessment || {};
    const sel = (k, opts) => `<select data-if="${k}" aria-label="${k}"><option value="">${{ recommendation: 'Empfehlung', category: 'Kategorie', benefit: 'Nutzen', effort: 'Aufwand' }[k]} …</option>${opts.map(o => `<option ${String(a[k]) === String(o) ? 'selected' : ''}>${o}</option>`).join('')}</select>`;
    if (box) box.innerHTML = `<div class="ideaform">${sel('recommendation', ['jetzt', 'später', 'verwerfen'])}${sel('category', ['Bugfix', 'Feature', 'Betrieb', 'Doku', 'Forschung'])}${sel('benefit', [1, 2, 3])}${sel('effort', ['S', 'M', 'L'])}
      <textarea data-if="why" placeholder="Warum? (optional)">${esc(a.why || '')}</textarea><div><button class="primary" data-isave="${id}">Bewertung speichern</button></div></div>`;
    return;
  }
  if (t.dataset.isave) {
    const id = t.dataset.isave, box = $('ideaForm' + id), b = { manual: true };
    box.querySelectorAll('[data-if]').forEach(x => { b[x.dataset.if] = x.value; });
    try { await post(`/api/ideas/${id}/assess`, b); toast('Bewertung gespeichert'); await load(); } catch (e) { toast(e.message); }
    return;
  }
  if (t.dataset.iticket) return openTicket(null, +t.dataset.iticket);
  if (t.dataset.ide) {
    await busy(t, 'Öffne …', async () => {
      try {
        const r = await post('/api/ide/open', JSON.parse(t.dataset.ide));
        if (r.launched) toast(`IntelliJ öffnet ${r.sha.slice(0, 8)}. Die Abnahme nimmt diesen Commit.`);
        else { await copyText(r.path, 'Pfad des Worktrees'); toast(r.hint || 'Pfad kopiert'); }
        await load();
      } catch (e) { toast(e.message); }
    });
    return;
  }
  if (t.dataset.ideclose) {
    try { await post('/api/ide/close', { ref: t.dataset.ideclose }); toast('Worktree entfernt'); }
    catch (e) {
      if (e.data && e.data.dirty && confirm(e.message)) { try { await post('/api/ide/close', { ref: t.dataset.ideclose, force: true }); toast('Worktree entfernt'); } catch (e2) { toast(e2.message); } }
      else toast(e.message);
    }
    await load();
  }
});
function openIdeaDrop() { const d = $('ideaDlg'); WISH_VIEW = typeof view !== 'undefined' ? view : ''; if (!d.open) d.showModal(); $('ideaWish').checked = false; $('ideaQuick').focus(); }
const WISH_RE = /^\s*tinyops\s*:\s*/i;
async function saveWish(text) {        // Wunsch an tinyops: wörtlich in den Nutzungsbericht, mit Ansicht und den letzten Klicks
  await api('POST', '/api/ux/wish', { text: text.replace(WISH_RE, ''), view: WISH_VIEW || (typeof view !== 'undefined' ? view : ''), trail: UX.trail.slice(-6), sess: UX.sess });
  toast('Für tinyops notiert: steht im nächsten Nutzungsbericht');
}
async function saveIdeaDrop() {
  const el = $('ideaQuick'); if (!el.value.trim()) return;
  try {
    if ($('ideaWish').checked || WISH_RE.test(el.value)) { await saveWish(el.value); el.value = ''; $('ideaDlg').close(); return; }
    await api('POST', '/api/ideas', { text: el.value }); el.value = ''; $('ideaDlg').close(); toast('In der Ideenbox'); await load();
  } catch (e) { toast(e.message); }
}
$('ideaBtn').onclick = openIdeaDrop; $('ideaSave').onclick = saveIdeaDrop; $('ideaCancel').onclick = () => $('ideaDlg').close();
$('ideaQuick').addEventListener('keydown', ev => { if (ev.key === 'Enter' && !ev.shiftKey) { ev.preventDefault(); saveIdeaDrop(); } });
document.addEventListener('keydown', ev => {
  if (ev.key === 'i' && !ev.ctrlKey && !ev.metaKey && !ev.altKey && !/INPUT|TEXTAREA|SELECT/.test(document.activeElement.tagName) && state && state.features.ideas && !document.querySelector('dialog[open]')) { ev.preventDefault(); openIdeaDrop(); }
});
// Ideen
document.getElementById('ideaText').addEventListener('keydown', async ev => {
  if (ev.key !== 'Enter' || ev.shiftKey) return;
  ev.preventDefault();
  const el = ev.target;
  if (!el.value.trim()) return;
  try { if (WISH_RE.test(el.value)) { WISH_VIEW = view; await saveWish(el.value); el.value = ''; return; } await api('POST', '/api/ideas', { text: el.value }); el.value = ''; await load(); } catch (e) { toast(e.message); }
});
document.getElementById('ideas').addEventListener('click', async ev => {
  const btn = ev.target.closest('button[data-ia]');
  if (!btn) return;
  const id = btn.closest('.idea').dataset.id;
  const status = { park: 'geparkt', done: 'erledigt', drop: 'verworfen' }[btn.dataset.ia];
  try { await api('PATCH', '/api/ideas/' + id, { status }); await load(); } catch (e) { toast(e.message); }
});
document.getElementById('triage').addEventListener('click', async () => {
  try { const r = await api('GET', '/api/ideas/triage-prompt'); await copyText(r.prompt, 'Triage-Prompt'); } catch (e) { toast(e.message); }
});
