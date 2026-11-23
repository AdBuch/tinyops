// 0.42 (E14): Review eines MR mit Agent. ▶ startet den Reviewer auf genau dem Commit des MR; seine Befunde (Datei, Zeile)
// werden auf Klick deine Entwürfe in GitLab, die nur du siehst und selbst abschickst. Ohne Review-Token: Kopieren.
let RV = { k: null, d: null, t: 0, off: {} };
function rvOk(e) { return e.t === 'review' && (e.r.host || 'gitlab') === 'gitlab' && state.agents && state.agents.enabled; }
function rvRef(r) { return { host: 'gitlab', project_id: r.project_id, iid: r.iid }; }
function rvBtn(e, cls) {
  if (!rvOk(e)) return '';
  return `<button class="${cls || 'fgo ghost'}" data-rvstart="${esc(JSON.stringify(rvRef(e.r)))}" title="Reviewer-Agent auf ${esc((e.r.sha || '').slice(0, 8))} starten: holt den Stand selbst, ändert nichts, hält Befunde mit Datei und Zeile fest">${ic('play')}<span>Review mit Agent</span></button>`;
}
function rvHtml(e) {
  const k = `${e.r.project_id}:${e.r.iid}`;
  if (RV.k !== k) RV = { k, d: null, t: 0, off: {} };
  const busy = RV.d && (RV.d.runs || []).some(r => r.active);
  if (!RV.d || Date.now() - RV.t > (busy ? 8000 : 30000)) setTimeout(() => rvLoad(e.r), 0);
  return `<div class="rvsec"><h3>Review mit Agent <small>Befunde werden Entwürfe in GitLab; abschicken machst du dort</small></h3><div id="rvBox">${RV.d ? rvInner(RV.d) : '<div class="small quiet">lädt …</div>'}</div></div>`;
}
async function rvLoad(r) {
  const k = `${r.project_id}:${r.iid}`;
  RV.t = Date.now();
  try { const d = await post('/api/review/state', rvRef(r)); if (RV.k === k) RV.d = d; }
  catch (err) { if (RV.k === k) RV.d = { error: err.message }; }
  const el = $('rvBox'); if (el && RV.d) el.innerHTML = rvInner(RV.d);
}
const SEV_CHIP = { hoch: 'warn', mittel: '', klein: 'tk' };
function rvInner(d) {
  if (d.error) return `<div class="banner bad">${esc(d.error)}</div>`;
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
  const st = t.closest && t.closest('[data-rvstart], [data-rvgo]');
  if (st) {
    ev.stopPropagation();
    const e = FXID && fEntry(FXID), ref = st.dataset.rvstart ? JSON.parse(st.dataset.rvstart) : e && rvRef(e.r);
    if (!ref) return;
    st.disabled = true;
    try { const r = await post('/api/review/start', ref); toast(`${r.agent} prüft (Lauf ${r.id}). Befunde erscheinen unter Details.`); RV.t = 0; await load(); }
    catch (err) { toast(err.message); }
    st.disabled = false; return;
  }
  if (!t.closest || !t.closest('#rvBox') || !RV.d) return;
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
