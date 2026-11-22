// Zeit und BCS: Fokus-Zeit, Entwürfe, Buchen.
// ------------------------------------------------ Fokus-Zeit (0.19): läuft nur für den angehefteten Fokus, Lücken statt stiller Pausen
const hm = secs => { const m = Math.max(0, Math.round(secs / 60)); return `${Math.floor(m / 60)}:${String(m % 60).padStart(2, '0')}`; };
let timeAt = Date.now();
function timeChip(e) {
  const t = state.time || {};
  if (!t.enabled || !['card', 'hd'].includes(e.t)) return '';
  const r = t.running;
  if (r && r.key === (e.t === 'hd' ? e.h.key : e.id)) {
    return `<div class="htime" data-tbase="${r.today_secs}"><span class="dot"></span><span>Zeit läuft</span><b class="tval">${hm(r.today_secs)}</b><span>heute bei diesem Vorhaben</span>
      <button class="quiet-btn" data-tpause="1" title="Zeit anhalten; der Fokus bleibt">Pause</button><button class="quiet-btn" data-tview="1">Tag ansehen</button></div>`;
  }
  return `<div class="htime paused"><span class="dot"></span><span>Zeit angehalten</span><button class="quiet-btn" data-tresume="1">Weiter</button>${t.gaps ? `<button class="quiet-btn" data-tview="1">${t.gaps} Lücke${t.gaps === 1 ? '' : 'n'} entscheiden</button>` : ''}</div>`;
}
setInterval(() => {   // die Anzeige zählt zwischen zwei Abfragen weiter
  document.querySelectorAll('.htime[data-tbase] .tval').forEach(el => { const b = +el.parentElement.dataset.tbase; el.textContent = hm(b + (Date.now() - timeAt) / 1000); });
}, 20000);
let lastInput = Date.now();
['keydown', 'pointerdown', 'pointermove', 'wheel', 'focus'].forEach(t => window.addEventListener(t, () => { lastInput = Date.now(); }, { passive: true, capture: true }));
setInterval(async () => {   // Lebenszeichen: nur wenn das Panel sichtbar ist und du in den letzten 5 Minuten etwas getan hast
  const t = state && state.time;
  if (!t || !t.enabled || !t.running || document.visibilityState !== 'visible' || Date.now() - lastInput > 5 * 60000) return;
  try { const was = t.running && t.gaps; state.time = await post('/api/time/ping', {}); timeAt = Date.now(); renderFbar(); if (state.time.gaps !== (t.gaps || 0) || was !== state.time.gaps) renderFocus(); } catch (e) { /* nächstes Mal */ }
}, 60000);
document.addEventListener('click', async ev => {
  const t = ev.target.closest && ev.target.closest('[data-tpause],[data-tresume],[data-tview]');
  if (!t) return;
  ev.stopPropagation();
  if (t.dataset.tview) { setView('time'); return; }
  try { state.time = await post(t.dataset.tpause ? '/api/time/pause' : '/api/time/resume', {}); timeAt = Date.now(); renderFocus(); } catch (e) { toast(e.message); }
});
let TDAY = null, TDATA = null;
async function loadTime() {
  try { TDATA = await api('GET', '/api/time/day' + (TDAY ? '?date=' + TDAY : '')); TDAY = TDATA.date; renderTime(); renderBcs(); }
  catch (e) { $('viewTime').innerHTML = `<div class="pview"><div class="banner bad">${esc(e.message)}</div></div>`; }
}
const T_ST = { offen: '', bestätigt: 'tk', gebucht: 'sq-ok', abgelehnt: 'sq-bad', fehlgeschlagen: 'warn', verworfen: 'sq-none' };
function shiftDay(d, n) { const x = new Date(d + 'T12:00:00'); x.setDate(x.getDate() + n); return x.toISOString().slice(0, 10); }
let TEXTS = {};
async function renderBcs() {
  const box = $('bcsCard'), d = TDATA;
  if (!box || !d.bcs || !d.bcs.on) return;
  let r;
  try { r = await api('GET', '/api/bcs/day?date=' + d.date); } catch (e) { box.innerHTML = `<h3>BCS</h3><div class="banner bad">${esc(e.message)}</div>`; return; }
  if (!$('bcsCard') || TDATA !== d) return;
  const day = r.day, wk = r.week, H = m => m == null ? '–' : hm(m * 60);
  const ready = d.drafts.filter(x => ['bestätigt', 'fehlgeschlagen'].includes(x.state) && x.bcs_task);
  const noTask = d.drafts.filter(x => ['bestätigt', 'fehlgeschlagen'].includes(x.state) && !x.bcs_task);
  const unclear = d.drafts.filter(x => x.state === 'unklar');
  $('bcsCard').innerHTML = `<h3>BCS <span class="quiet small">${d.bcs.demo ? 'Demo-Middleware' : 'über deine Middleware'}${day.closed ? ' · Tag abgeschlossen' : ''}</span></h3>
    <div class="psum" style="margin-bottom:8px"><span>Anwesenheit <b>${H(day.attendance_minutes)}</b></span><span>gebucht in BCS <b>${H(day.work_minutes)}</b></span><span>nicht verteilt <b>${H(day.unallocated_minutes)}</b></span>
      ${wk && wk.targetMinutes != null ? `<span title="Woche bis heute, kein offizieller Saldo">Woche <b>${H(wk.actualMinutes)}</b> von ${H(wk.targetMinutes)}</span>` : ''}</div>
    ${day.issues.length ? `<div class="banner warn">${day.issues.map(esc).join('<br>')}</div>` : ''}
    ${unclear.length ? `<div class="banner bad">${unclear.length} Entw${unclear.length === 1 ? 'urf ist' : 'ürfe sind'} unklar: Das Bestätigen brach ab. tinyops wiederholt nie von selbst. <button class="primary" id="bcsRec">Mit BCS abgleichen</button></div>` : ''}
    ${noTask.length ? `<div class="small" style="color:var(--warn)">${noTask.length} bestätigte${noTask.length === 1 ? 'r Entwurf hat' : ' Entwürfe haben'} noch keine BCS-Aufgabe.</div>` : ''}
    <div class="row" style="gap:8px;flex-wrap:wrap;margin-top:6px">${ready.length ? `<button class="primary" id="bcsPrev">${ready.length} bestätigte in BCS prüfen (${hm(ready.reduce((a, x) => a + x.minutes * 60, 0))})</button>` : '<span class="quiet small">Bestätigte Entwürfe mit BCS-Aufgabe lassen sich hier prüfen und buchen.</span>'}</div>
    <details style="margin-top:8px"><summary class="quiet small">${day.entries.length} Einträge in BCS an diesem Tag</summary><ul class="mlist">${day.entries.map(e => `<li><span class="t">${esc(e.start || '')}</span><a>${esc(e.kind === 'work' ? (e.task || 'Arbeit') : e.kind === 'pause' ? 'Pause' : e.kind === 'attendance' ? 'Anwesenheit' : e.kind)}${e.description ? ' · ' + esc(e.description) : ''}</a><small>${e.minutes != null ? H(e.minutes) : ''}</small></li>`).join('')}</ul></details>
    ${state.focus || (S && S.time) ? '<details id="bcsAppr" style="margin-top:6px"><summary class="quiet small">Lernende</summary><div class="quiet small">lädt beim Aufklappen</div></details>' : ''}`;
  if ($('bcsPrev')) $('bcsPrev').onclick = bcsPreview;
  if ($('bcsRec')) $('bcsRec').onclick = async () => { try { const x = await post('/api/bcs/reconcile', { date: d.date }); toast(`${x.booked} gefunden, ${x.back} neu zu prüfen`); await loadTime(); } catch (e) { toast(e.message); } };
  const ap = $('bcsAppr');
  if (ap) ap.addEventListener('toggle', async () => {
    if (!ap.open || ap.dataset.done) return;
    try {
      const x = await post('/api/bcs/apprentices', {}); ap.dataset.done = '1';
      ap.querySelector('div').outerHTML = x.members.length ? `<table class="bcsappr"><tr><th>Name</th><th>Woche</th><th>Jahr</th><th>Ferien übrig</th></tr>${x.members.map(m => m.error ? `<tr><td>${esc(m.name)}</td><td colspan="3" class="quiet">${esc(m.error)}</td></tr>`
        : `<tr><td>${esc(m.name)}</td><td>${m.week == null ? '–' : (m.week < 0 ? '−' : '+') + hm(Math.abs(m.week) * 60)}</td><td>${m.ytd == null ? '–' : (m.ytd < 0 ? '−' : '+') + hm(Math.abs(m.ytd) * 60)}</td><td>${m.vacation_left == null ? '–' : m.vacation_left + ' Tage'}</td></tr>`).join('')}</table><div class="quiet small">Nur lesen, Stand laut BCS${x.members[0] && x.members[0].as_of ? ' vom ' + esc(x.members[0].as_of) : ''}.</div>`
        : `<div class="quiet small">${x.configured ? 'Keine Lernenden sichtbar.' : 'In der Middleware ist kein Lernendenbereich eingerichtet.'}</div>`;
    } catch (e) { ap.querySelector('div').textContent = e.message; }
  });
}
async function bcsPreview() {
  const d = TDATA;
  let r;
  try { r = await post('/api/bcs/preview', { date: d.date }); } catch (e) { toast(e.message); return; }
  const warn = r.warnings.map(w => `<li>${esc(w.message || '')}${w.candidates && w.candidates.length ? ': ' + w.candidates.map(c => esc(c.name)).join(', ') : ''}</li>`).join('');
  $('wsDlgBody').innerHTML = `<div style="display:grid;gap:10px"><div><strong>${r.status === 'ready' ? 'Bereit zum Buchen' : 'Nicht buchbar'}</strong> <span class="quiet small">${esc(d.date)} · ${esc(r.message || '')}</span></div>
    <ul class="mlist">${r.included.map(x => `<li><span class="t">${hm(x.minutes * 60)}</span><a>${esc(x.description)}</a></li>`).join('')}</ul>
    ${r.skipped.length ? `<div class="small quiet">Nicht dabei (keine BCS-Aufgabe): ${r.skipped.map(x => esc(x.ticket)).join(', ')}</div>` : ''}
    ${warn ? `<div class="banner warn"><ul style="margin:0;padding-left:18px">${warn}</ul></div>` : ''}
    ${r.deletions.length ? `<div class="banner bad">Die Middleware würde ${r.deletions.length} Eintrag/Einträge löschen. tinyops bucht so nicht: bitte in BCS prüfen.</div>` : ''}
    ${r.dry_run ? '<div class="banner warn">Die Middleware läuft im Probelauf: Bestätigen schreibt nichts.</div>' : ''}
    <div class="row">${r.status === 'ready' && r.draft_id && !r.deletions.length ? `<button class="primary" id="bcsGo">In BCS buchen</button>` : ''}<button id="bcsNo">${r.status === 'ready' ? 'Abbrechen' : 'Schliessen'}</button>
      ${r.expires ? `<span class="quiet small">Die Vorschau gilt bis ${hhmm(Date.parse(r.expires) / 1000)}.</span>` : ''}</div></div>`;
  $('wsDlg').showModal();
  $('bcsNo').onclick = () => $('wsDlg').close();
  if ($('bcsGo')) $('bcsGo').onclick = async () => {
    $('bcsGo').disabled = true;
    try {
      const x = await post('/api/bcs/commit', { date: d.date, draft_id: r.draft_id });
      $('wsDlg').close();
      toast(x.status === 'committed' ? 'In BCS gebucht' : x.status === 'unklar' ? 'Unklar, ob gebucht: bitte abgleichen' : `${x.status}: ${x.message}`);
    } catch (e) { toast(e.message); $('wsDlg').close(); }
    await loadTime();
  };
}
async function bcsMap(id) {
  const x = TDATA.drafts.find(y => y.id === id); if (!x) return;
  let sug = [];
  try { sug = ((await post('/api/bcs/suggestions', { date: TDATA.date })).suggestions || []).map(s => s.task).filter(Boolean); } catch (e) { /* ohne Vorschläge */ }
  const isKey = /^[A-Z][A-Z0-9_]*-\d+$/.test(x.ticket);
  const list = items => items.map(t => `<label class="check bcst"><input type="radio" name="bcsT" value="${esc(t.id)}" data-name="${esc(t.name)}" data-path="${esc((t.path || []).join(' › '))}"><span><b>${esc(t.name)}</b> <span class="quiet small">${esc((t.path || []).join(' › '))}</span>${t.favorite ? ' <span class="chip">Favorit</span>' : ''}</span></label>`).join('');
  $('wsDlgBody').innerHTML = `<div style="display:grid;gap:10px"><div><strong>BCS-Aufgabe für ${esc(x.ticket)}</strong><div class="quiet small">${esc(x.title || x.text)}</div></div>
    <div class="row"><input id="bcsQ" class="full" placeholder="In BCS suchen (Projekt, Aufgabe)" value="${esc(x.project_hint || '')}"><button id="bcsS">Suchen</button></div>
    <div id="bcsList" style="max-height:40vh;overflow:auto">${sug.length ? '<div class="quiet small">Oft gebucht</div>' + list(sug) : ''}</div>
    ${isKey ? `<label class="check"><input type="checkbox" id="bcsProj" checked><span>Für alle Tickets <b>${esc(x.ticket.split('-')[0])}-…</b> merken</span></label>` : ''}
    <div class="row"><button class="primary" id="bcsSave">Zuordnen</button>${x.bcs_task ? '<button id="bcsDel" class="quiet-btn">Zuordnung entfernen</button>' : ''}<button id="bcsC">Abbrechen</button></div></div>`;
  $('wsDlg').showModal();
  const search = async () => {
    try { const r = await post('/api/bcs/targets', { date: TDATA.date, query: $('bcsQ').value }); $('bcsList').innerHTML = r.items.length ? list(r.items) : '<div class="quiet small">Nichts gefunden.</div>'; }
    catch (e) { toast(e.message); }
  };
  $('bcsS').onclick = search; $('bcsQ').onkeydown = e => { if (e.key === 'Enter') search(); };
  $('bcsC').onclick = () => $('wsDlg').close();
  const save = async (tid, name, path) => {
    try { await post('/api/bcs/map', { ticket: x.ticket, task_id: tid, name, path, scope: $('bcsProj') && $('bcsProj').checked ? 'project' : 'ticket' }); $('wsDlg').close(); await loadTime(); }
    catch (e) { toast(e.message); }
  };
  $('bcsSave').onclick = () => { const c = $('wsDlgBody').querySelector('input[name=bcsT]:checked'); if (!c) return toast('Bitte eine Aufgabe wählen.'); save(c.value, c.dataset.name, c.dataset.path); };
  if ($('bcsDel')) $('bcsDel').onclick = () => { if ($('bcsProj')) $('bcsProj').checked = x.bcs_task.pattern.endsWith('*'); save('', '', ''); };
}
function renderTime() {
  const d = TDATA, box = $('viewTime');
  const dd = new Date(d.date + 'T12:00:00').toLocaleDateString('de-CH', { weekday: 'long', day: '2-digit', month: '2-digit', year: 'numeric' });
  const open = d.drafts.filter(x => x.state === 'offen' && x.ticket_ok && x.minutes > 0);
  const sameDay = id => d.drafts.filter(x => x.id !== id && x.state === 'offen');
  const draft = x => {
    const lock = x.state === 'gebucht' || x.state === 'verworfen';
    const acts = [];
    if (x.state === 'unklar') acts.push('<span class="chip warn">unklar, ob gebucht</span>');
    if (x.state === 'offen') acts.push(`<button class="primary" data-tconf="${esc(x.id)}" ${x.ticket_ok && x.minutes > 0 ? '' : 'disabled'} title="${x.ticket_ok ? 'Bestätigen. Gebucht wird danach in BCS' : 'Erst ein Ticket eintragen'}">Bestätigen</button>`);
    if (d.bcs && d.bcs.on && !lock) acts.push(x.bcs_task ? `<button class="quiet-btn" data-bcsmap="${esc(x.id)}" title="${esc(x.bcs_task.path || x.bcs_task.name)}${x.bcs_task.pattern.endsWith('*') ? ' (für ' + esc(x.bcs_task.pattern) + ')' : ''}">BCS: ${esc(short(x.bcs_task.name, 28))}</button>`
      : `<button data-bcsmap="${esc(x.id)}" class="warn-btn" title="Ohne BCS-Aufgabe lässt sich dieser Entwurf nicht buchen">BCS-Aufgabe wählen</button>`);
    if (TEXTS[x.id] && !lock) acts.push(`<button class="quiet-btn" data-ttext="${esc(x.id)}" title="${esc(TEXTS[x.id])}">Vorschlag übernehmen</button>`);
    if (x.state === 'offen' && sameDay(x.id).length) acts.push(`<select data-tmerge="${esc(x.id)}" title="In einen anderen Entwurf legen"><option value="">Zusammenlegen …</option>${sameDay(x.id).map(o => `<option value="${esc(o.id)}">mit ${esc(o.ticket)}</option>`).join('')}</select>`);
    if (!lock) acts.push(`<button class="quiet-btn" data-tdisc="${esc(x.id)}">Verwerfen</button>`);
    if (x.state === 'verworfen') acts.push(`<button class="quiet-btn" data-trest="${esc(x.id)}">Wiederherstellen</button>`);
    const calc = x.edited && !x.manual && x.calc_minutes !== x.minutes ? ` <span class="quiet small" title="gemessen und gerundet">(gemessen ${x.calc_minutes})</span>` : '';
    return `<div class="tdraft st-${esc(x.state)}">
      <input type="text" data-tedit="${esc(x.id)}" data-f="ticket" value="${esc(x.ticket)}" ${lock ? 'readonly' : ''} aria-label="Ticket" title="${esc(x.title)}">
      <span><input data-tedit="${esc(x.id)}" data-f="minutes" type="number" min="0" max="1440" step="${d.round}" value="${x.minutes}" ${lock ? 'readonly' : ''} aria-label="Minuten" style="width:72px"> min${calc}</span>
      <input type="text" class="tx" data-tedit="${esc(x.id)}" data-f="text" value="${esc(x.text)}" maxlength="300" ${lock ? 'readonly' : ''} aria-label="Text">
      <div class="acts"><span class="chip ${T_ST[x.state] || ''}">${esc(x.state)}${x.edited && x.state === 'offen' ? ' · bearbeitet' : ''}${x.manual ? ' · von Hand' : ''}</span>${acts.join('')}</div>
      ${x.evidence.length || !x.ticket_ok ? `<div class="ev">${!x.ticket_ok ? '<span class="chip warn">kein Ticket: Branch ohne Ticket, erst ein Ticket eintragen</span>' : ''}${x.evidence.map(e => `<span>${esc(e)}</span>`).join('')}</div>` : ''}
      ${TEXTS[x.id] && !lock ? `<div class="msg quiet">Vorschlag: ${esc(TEXTS[x.id])}</div>` : ''}
      ${x.reference || x.message ? `<div class="msg ${x.state === 'gebucht' ? 'quiet' : ''}">${x.reference ? 'Referenz: <code>' + esc(x.reference) + '</code> ' : ''}${esc(x.message)}${x.attempts ? ` <span class="quiet">(${x.attempts}× gesendet)</span>` : ''}</div>` : ''}
    </div>`;
  };
  box.innerHTML = `<div class="phead"><button data-tday="-1" aria-label="Tag davor">‹</button><h1>${esc(dd)}</h1><button data-tday="1" aria-label="Tag danach">›</button>
      <button class="quiet-btn" data-tday="0">Heute</button><span class="sp"></span>
      <div class="psum"><span>gemessen <b>${hm(d.total_secs)}</b></span><span>Entwürfe <b>${hm(d.draft_minutes * 60)}</b></span><span>gebucht <b>${hm(d.booked_minutes * 60)}</b></span></div>
      ${d.llm && d.drafts.some(x => !['gebucht', 'verworfen', 'unklar'].includes(x.state)) ? '<button id="tTexts" title="Das eingestellte Sprachmodell schlägt kurze Buchungstexte vor. Übernommen wird nur, was du anklickst.">Texte vorschlagen</button>' : ''}
      ${open.length ? `<button class="primary" id="tAll">Alle ${open.length} offenen bestätigen</button>` : ''}</div>
    ${d.earlier_open.length ? `<div class="banner warn">Offene Entwürfe an früheren Tagen: ${d.earlier_open.map(x => `<button class="quiet-btn" data-tgo="${x}">${new Date(x + 'T12:00:00').toLocaleDateString('de-CH', { day: '2-digit', month: '2-digit' })}</button>`).join(' ')}</div>` : ''}
    ${d.bcs ? `<div class="pcard" id="bcsCard"><h3>BCS <span class="quiet small">${d.bcs.demo ? 'Demo-Middleware' : 'über deine Middleware'}</span></h3>${d.bcs.error ? `<div class="banner bad">${esc(d.bcs.error)}</div>` : '<div class="quiet small">lese den Tag …</div>'}</div>` : ''}
    ${d.gaps.length ? `<div class="pcard"><h3>Lücken <span class="quiet small">Pausen über der Leerlaufgrenze. Sie zählen erst, wenn du sie annimmst.</span></h3>${d.gaps.map(g => `<div class="tgap"><time>${g.from_}–${g.to}</time><b>${g.minutes} min</b><span class="sp">${esc(g.key)} ${esc(g.title)}</span><button data-tgap="${g.id}" data-c="1">Zählen</button><button class="quiet-btn" data-tgap="${g.id}" data-c="0">Verwerfen</button></div>`).join('')}</div>` : ''}
    <div class="pcard"><h3>Entwürfe <span class="quiet small">je Ticket, auf ${d.round} min gerundet. Gebucht wird erst nach «Bestätigen»${d.bcs && d.bcs.on ? ' und dann oben «In BCS prüfen» und «In BCS buchen»' : ', danach in BCS (Einstellungen → Zeiterfassung → BCS-Middleware)'}.</span></h3>
      ${d.drafts.length ? d.drafts.map(draft).join('') : '<div class="quiet small">Noch nichts. Zeit entsteht, solange ein Vorhaben als Fokus angeheftet ist.</div>'}
      <div class="tdraft" style="border-top:1px dashed var(--line)"><input type="text" id="tNewT" placeholder="Ticket, z. B. DLP-123" aria-label="Ticket"><span><input id="tNewM" type="number" min="0" max="1440" step="${d.round}" value="${d.round}" style="width:72px" aria-label="Minuten"> min</span><input type="text" id="tNewX" placeholder="Text (z. B. Meeting, Review)" maxlength="300" aria-label="Text"><div class="acts"><button id="tNew">Von Hand hinzufügen</button></div></div>
    </div>
    <details class="pcard"><summary><b>Abschnitte</b> <span class="quiet small">${d.segments.length} gemessen, nur Fokus-Zeit (Agentenlaufzeit zählt nie)</span></summary>
      ${d.segments.map(x => `<div class="tseg"><time>${x.from_}–${x.open ? 'jetzt' : x.to}</time><b>${hm(x.secs)}</b><span class="sp">${esc(x.key)} ${esc(x.title)}</span><span class="quiet small">${esc(x.source)}</span></div>`).join('') || '<div class="quiet small">keine</div>'}
    </details>`;
}
$('viewTime').addEventListener('click', async ev => {
  const t = ev.target;
  const dayB = t.closest('[data-tday]'); if (dayB) { const n = +dayB.dataset.tday; TDAY = n ? shiftDay(TDATA.date, n) : null; return loadTime(); }
  const go = t.closest('[data-tgo]'); if (go) { TDAY = go.dataset.tgo; return loadTime(); }
  const run = async (path, body, msg) => { try { const r = await post(path, body); if (msg) toast(typeof msg === 'function' ? msg(r) : msg); await loadTime(); } catch (e) { toast(e.message); await loadTime(); } };
  const g = t.closest('[data-tgap]'); if (g) return run('/api/time/gap', { id: +g.dataset.tgap, count: g.dataset.c === '1' }, g.dataset.c === '1' ? 'Lücke zählt' : 'Lücke verworfen');
  const c = t.closest('[data-tconf]'); if (c) return run('/api/time/confirm', { id: c.dataset.tconf }, 'Bestätigt');
  const bm = t.closest('[data-bcsmap]'); if (bm) return bcsMap(bm.dataset.bcsmap);
  const tt = t.closest('[data-ttext]'); if (tt) { const id = tt.dataset.ttext, v = TEXTS[id]; delete TEXTS[id]; return run('/api/time/edit', { id, text: v }, 'Text übernommen'); }
  if (t.id === 'tTexts') { t.disabled = true; t.textContent = 'Modell denkt …'; try { TEXTS = (await post('/api/time/texts', { date: TDATA.date })).texts; toast(Object.keys(TEXTS).length + ' Vorschläge'); } catch (e) { toast(e.message); } return renderTime(); }
  const di = t.closest('[data-tdisc]'); if (di) return run('/api/time/discard', { id: di.dataset.tdisc }, 'Verworfen');
  const re = t.closest('[data-trest]'); if (re) return run('/api/time/restore', { id: re.dataset.trest });
  if (t.id === 'tNew') return run('/api/time/add', { date: TDATA.date, ticket: $('tNewT').value, minutes: $('tNewM').value, text: $('tNewX').value }, 'Hinzugefügt');
  if (t.id === 'tAll') {
    const open = TDATA.drafts.filter(x => x.state === 'offen' && x.ticket_ok && x.minutes > 0);
    if (!confirm(`${open.length} Entwürfe (${hm(open.reduce((a, x) => a + x.minutes * 60, 0))}) bestätigen?`)) return;
    let ok = 0, bad = 0;
    for (const x of open) { try { const r = await post('/api/time/confirm', { id: x.id }); (r.state === 'gebucht' || r.state === 'bestätigt') ? ok++ : bad++; } catch (e) { bad++; } }
    toast(`${ok} bestätigt${bad ? ', ' + bad + ' mit Fehler' : ''}`); return loadTime();
  }
});
$('viewTime').addEventListener('change', async ev => {
  const t = ev.target;
  if (t.dataset.tmerge !== undefined && t.value) {
    try { await post('/api/time/merge', { id: t.dataset.tmerge, into: t.value }); toast('Zusammengelegt'); } catch (e) { toast(e.message); }
    return loadTime();
  }
  if (t.dataset.tedit) {
    try { await post('/api/time/edit', { id: t.dataset.tedit, [t.dataset.f]: t.value }); } catch (e) { toast(e.message); }
    return loadTime();
  }
});
