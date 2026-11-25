// 0.42 (E14): Review eines MR mit Agent. ▶ startet den Reviewer auf genau dem Commit des MR; seine Befunde (Datei, Zeile)
// werden auf Klick deine Entwürfe in GitLab, die nur du siehst und selbst abschickst. Ohne Review-Token: Kopieren.
// 0.42.1: ▶ öffnet erst einen kurzen Start: Agent wählen, Ticket und Ziel des MR mitgeben, dann «Review starten».
let RV = { k: null, d: null, t: 0, off: {}, form: null };
const RV_LAST = 'tinyops.rvAgent';
function rvLastAgent() { try { return localStorage.getItem(RV_LAST) || ''; } catch (e) { return ''; } }
function rvOk(e) { return e.t === 'review' && (e.r.host || 'gitlab') === 'gitlab' && state.agents && state.agents.enabled; }
function rvRef(r) { return { host: 'gitlab', project_id: r.project_id, iid: r.iid }; }
function rvBtn(e, cls) {
  if (!rvOk(e)) return '';
  return `<button class="${cls || 'fgo ghost'}" data-rvfx="${esc(e.id)}" title="Agent wählen, Ticket und Ziel mitgeben, Review auf ${esc((e.r.sha || '').slice(0, 8))} starten">${ic('play')}<span>Review mit Agent</span></button>`;
}
function rvHtml(e) {
  const k = `${e.r.project_id}:${e.r.iid}`;
  if (RV.k !== k) RV = { k, d: null, t: 0, off: {}, form: RV.pending === k ? { loading: true } : null };
  if (RV.form && RV.form.loading && !RV.form.req) { RV.form.req = 1; setTimeout(() => rvOpenForm(e.r), 0); }
  const busy = RV.d && (RV.d.runs || []).some(r => r.active);
  if (!RV.d || Date.now() - RV.t > (busy ? 8000 : 30000)) setTimeout(() => rvLoad(e.r), 0);
  return `<div class="rvsec"><h3>Review mit Agent <small>Befunde werden Entwürfe in GitLab; abschicken machst du dort</small></h3><div id="rvBox">${RV.d ? rvInner(RV.d) : '<div class="small quiet">lädt …</div>'}</div></div>`;
}
async function rvLoad(r) {
  const k = `${r.project_id}:${r.iid}`;
  RV.t = Date.now();
  try { const d = await post('/api/review/state', rvRef(r)); if (RV.k === k) RV.d = d; }
  catch (err) { if (RV.k === k) RV.d = { error: err.message }; }
  rvDraw();
}
function rvDraw() { const el = $('rvBox'); if (el && RV.d) el.innerHTML = rvInner(RV.d); }
async function rvOpenForm(r, ticket) {
  const k = `${r.project_id}:${r.iid}`, keep = RV.form && RV.form.v;
  RV.pending = null; RV.form = { loading: true, req: 1, v: keep };
  rvDraw();
  try {
    const o = await post('/api/review/options', ticket === undefined ? rvRef(r) : { ...rvRef(r), ticket });
    if (RV.k !== k) return;
    const ok = o.agents.filter(a => a.ok), last = rvLastAgent();
    const pre = RV.prefill || {}; RV.prefill = null;      // 0.43: aus einem Sprachbefehl
    const v = keep || { agent: (ok.find(a => a.id === (pre.agent || last)) || ok[0] || {}).id || '', ticket: pre.ticket ?? (o.ticket ? o.ticket.key : ''), goal: pre.goal || '' };
    if (ticket !== undefined) v.ticket = ticket;
    RV.form = { o, v };
  } catch (err) { RV.form = { error: err.message, v: keep }; }
  rvDraw();
  const g = $('rvGoal'); if (g && !g.value) g.focus();
}
function rvFormHtml() {
  const f = RV.form;
  if (f.loading) return '<div class="rvform"><div class="small quiet">Agenten und Ticket werden gelesen …</div></div>';
  if (f.error) return `<div class="rvform"><div class="banner bad">${esc(f.error)}</div><button data-rvcancel="1">Abbrechen</button></div>`;
  const o = f.o, v = f.v, byId = Object.fromEntries((AG().agents || []).map(a => [a.id, a]));
  const opts = o.agents.map(a => { const ag = byId[a.id] || { name: a.id };
    return `<option value="${esc(a.id)}" ${a.ok ? '' : 'disabled'} ${a.id === v.agent ? 'selected' : ''}>${esc(agOptLabel(ag, 'review'))}${a.ok ? '' : ' · ' + esc(a.why)}</option>`; }).join('');
  const tk = o.ticket, tkInfo = !v.ticket ? 'Kein Ticket: der Reviewer leitet das Ziel aus Beschreibung, Titel und Commits ab.'
    : !tk ? '' : tk.error ? `<span class="bad">${esc(tk.error)}</span>`
    : `${esc(tk.title || '')}${tk.status ? ' · ' + esc(tk.status) : ''} · ${tk.criteria ? tk.criteria + ' Akzeptanzkriterien, je eines wird geprüft' : 'keine Akzeptanzkriterien'}${tk.desc ? ' · Beschreibung geht mit' : ''}`;
  const keys = o.keys.length > 1 ? `<span class="small">Im MR erkannt: ${o.keys.map(k => `<button class="linkish" data-rvkey="${esc(k)}">${esc(k)}</button>`).join(' ')}</span>` : '';
  return `<div class="rvform">
    <label class="rvrow"><span>Agent</span><select id="rvAgent">${opts || '<option value="">Kein Agent eingerichtet</option>'}</select></label>
    <label class="rvrow"><span>Ticket</span><input id="rvTicket" value="${esc(v.ticket || '')}" placeholder="z. B. DLP-123, leer für keins" autocomplete="off" spellcheck="false"></label>
    <div class="small quiet rvinfo">${tkInfo} ${keys}</div>
    <label class="rvrow top"><span>Ziel</span><textarea id="rvGoal" rows="3" maxlength="2000" placeholder="Worum geht es im MR, worauf soll der Reviewer achten? Geht wörtlich an ihn (optional)">${esc(v.goal || '')}</textarea></label>
    <div class="small quiet rvinfo">${o.mr_desc ? 'Die Beschreibung des MR geht mit (' + o.mr_desc + ' Zeichen).' : 'Der MR hat keine Beschreibung.'}${o.target ? ' Verglichen wird mit <code>' + esc(o.target) + '</code>.' : ''}</div>
    <div class="tcfoot"><button class="primary" data-rvrun="1" ${v.agent ? '' : 'disabled'}>${ic('play')} Review starten</button><button data-rvcancel="1">Abbrechen</button></div></div>`;
}
const SEV_CHIP = { hoch: 'warn', mittel: '', klein: 'tk' };
function rvInner(d) {
  if (d.error) return `<div class="banner bad">${esc(d.error)}</div>`;
  if (RV.form) return rvFormHtml();
  const run = (d.runs || [])[0];
  const start = d.can_start ? `<button class="${run ? '' : 'primary'}" data-rvgo="1" title="Neuer Lauf des Reviewers auf ${esc(d.sha)}">${ic('play')} ${run ? 'Neu prüfen' : 'Review starten'}</button>` : '<span class="small quiet">Noch kein Agent eingerichtet (Einstellungen → Coding-Agenten).</span>';
  const drafts = d.drafts ? `<a class="ibtn" href="${esc(d.url)}" target="_blank" rel="noopener" title="In GitLab: oben «Review abschicken» (Submit review)">${ic('ext')} ${d.drafts} Entwurf${d.drafts === 1 ? '' : 'e'} von tinyops in GitLab</a>` : '';
  if (!run) return `<div class="tctop">${start}${drafts}</div><div class="small quiet">Der Reviewer holt genau den Stand ${esc(d.sha)} in einen eigenen Worktree, ändert nichts und schreibt Befunde mit Datei und Zeile.</div>`;
  if (run.active || run.status === 'zugewiesen') return `<div class="tctop"><span class="chip"><span class="agspin"></span> ${esc(run.agent)} prüft ${esc(run.sha)}</span><button class="linkish" data-arun="${run.id}">Lauf ${run.id} öffnen</button>${drafts}</div>`;
  const f = run.findings || [];
  const n = f.filter((x, i) => !RV.off[run.id + ':' + i]).length;
  const list = f.length ? `<ul class="rvf">${f.map((x, i) => `<li><div class="rvh"><label><input type="checkbox" data-rvsel="${i}" ${RV.off[run.id + ':' + i] ? '' : 'checked'} aria-label="In GitLab übernehmen"><span class="chip ${SEV_CHIP[x.severity] || ''}">${esc(x.severity)}</span></label><code data-copy="${esc(x.path + (x.line ? ':' + x.line : ''))}" title="Klick kopiert">${esc(short(x.path, 52))}${x.line ? ':' + x.line : ''}</code></div><p>${esc(x.text)}</p></li>`).join('')}</ul>`
    : `<div class="small quiet">${run.status === 'fertig' ? 'Keine Befunde mit Ort. Der Bericht steht im Lauf.' : esc(run.agent) + ': ' + esc(run.status)}</div>`;
  const act = f.length ? `<div class="tcfoot">${d.token ? `<button class="primary" data-rvdraft="${run.id}" ${n ? '' : 'disabled'} title="Ersetzt die Entwürfe, die tinyops an diesem MR angelegt hat; deine eigenen bleiben">${ic('chat')} ${n} als Entwürfe in GitLab</button>` : '<span class="small quiet">Für Entwürfe in GitLab: Review-Token unter Einstellungen → GitLab.</span>'}<button data-rvcopy="${run.id}">${ic('copy')} Kopieren</button></div>` : '';
  const sum = run.summary ? `<details class="small"><summary>Bericht von ${esc(run.agent)}</summary><div class="hdtxt">${esc(run.summary)}</div></details>` : '';
  return `<div class="tctop">${start}<button class="linkish" data-arun="${run.id}">Lauf ${run.id}</button><span class="small quiet">${esc(run.agent)} auf ${esc(run.sha)}${run.sha && d.sha && run.sha !== d.sha ? ` · MR jetzt auf ${esc(d.sha)}` : ''}</span><span class="sp"></span>${drafts}</div>${list}${act}${sum}`;
}
function rvOnly(run) { return (run.findings || []).map((x, i) => i).filter(i => !RV.off[run.id + ':' + i]); }
document.addEventListener('click', async ev => {
  const t = ev.target;
  const fx = t.closest && t.closest('[data-rvfx]');
  if (fx) {                                    // ▶ aus Liste, Hero oder Detail: Details auf, Start-Formular im Abschnitt «Review mit Agent»
    ev.stopPropagation(); ev.preventDefault();
    const e = fEntry(fx.dataset.rvfx); if (!e) return;
    const k = `${e.r.project_id}:${e.r.iid}`;
    if (FXID === e.id && RV.k === k) rvOpenForm(e.r); else { RV.pending = k; openFx(e.id); }
    setTimeout(() => { const s = document.querySelector('#fx .rvsec'); if (s) s.scrollIntoView({ block: 'start', behavior: 'smooth' }); }, 250);
    return;
  }
  if (!t.closest || !t.closest('#rvBox') || !RV.d) return;
  const e = FXID && fEntry(FXID);
  if (t.closest('[data-rvgo]') && e) { rvOpenForm(e.r); return; }
  if (t.closest('[data-rvcancel]')) { RV.form = null; rvDraw(); return; }
  const kb = t.closest('[data-rvkey]');
  if (kb && e) { rvOpenForm(e.r, kb.dataset.rvkey); return; }
  const go = t.closest('[data-rvrun]');
  if (go && e && RV.form && RV.form.v) {
    const v = RV.form.v; go.disabled = true;
    try {
      const r = await post('/api/review/start', { ...rvRef(e.r), agent: v.agent, ticket: v.ticket || '', goal: v.goal || '' });
      try { localStorage.setItem(RV_LAST, v.agent); } catch (x) { /* nur Komfort */ }
      toast(`${r.agent} prüft (Lauf ${r.id}). Die Befunde erscheinen hier.`); RV.form = null; RV.t = 0; await load();
    } catch (err) { toast(err.message); go.disabled = false; }
    return;
  }
  const run = (RV.d.runs || [])[0];
  const sel = t.closest('[data-rvsel]');
  if (sel && run) { RV.off[run.id + ':' + sel.dataset.rvsel] = !sel.checked; $('rvBox').innerHTML = rvInner(RV.d); return; }
  const cp = t.closest('[data-rvcopy]');
  if (cp && run) { try { const r = await post('/api/review/copy', { run: run.id, only: rvOnly(run) }); await copyText(r.text, 'Befunde'); } catch (err) { toast(err.message); } return; }
  const dr = t.closest('[data-rvdraft]');
  if (dr && run) {
    dr.disabled = true;
    try {
      const r = await post('/api/review/drafts', { run: run.id, only: rvOnly(run) });
      toast(`${r.created} Entwürfe in GitLab (${r.positioned} an der Zeile${r.general ? `, ${r.general} allgemein` : ''}${r.replaced ? `, ${r.replaced} alte ersetzt` : ''}). Abschicken in GitLab.`);
      RV.t = 0; const e = FXID && fEntry(FXID); if (e && e.t === 'review') await rvLoad(e.r);
    } catch (err) { toast(err.message); dr.disabled = false; }
  }
}, true);
// Eingaben im Start-Formular überleben das Neuzeichnen (Abgleich alle paar Sekunden)
document.addEventListener('input', ev => {
  const id = ev.target && ev.target.id; if (!RV.form || !RV.form.v) return;
  if (id === 'rvGoal') RV.form.v.goal = ev.target.value;
  else if (id === 'rvTicket') RV.form.v.ticket = ev.target.value.trim().toUpperCase();
  else if (id === 'rvAgent') { RV.form.v.agent = ev.target.value; const b = document.querySelector('[data-rvrun]'); if (b) b.disabled = !ev.target.value; }
});
document.addEventListener('change', ev => {          // anderes Ticket eingetragen: Titel und Kriterien neu lesen
  if (!ev.target || ev.target.id !== 'rvTicket' || !RV.form || !RV.form.o) return;
  const e = FXID && fEntry(FXID); if (e) rvOpenForm(e.r, ev.target.value.trim().toUpperCase());
});
