// Rahmen: Verlauf und Log, Kopfzeile, Wechsel der Ansichten.
// Dialog
let LOGVIEW = 'audit';
try { LOGVIEW = localStorage.getItem('tinyops.logview') || 'audit'; } catch (e) { /* ohne Speicher: Verlauf */ }
const AUD_KEYS = { stage: 'Station', ticket: 'Ticket', accepted: 'Abgenommen auf', note: 'Notiz', env: 'Umgebung', summary: 'Titel', issue_type: 'Typ',
  agent: 'Agent', where: 'wo', data_class: 'Datenklasse', mode: 'Modus', branch: 'Branch', out_branch: 'Ergebnis-Branch', prompt_hash: 'Prompt',
  files: 'Dateien', status: 'Status', exit_code: 'Exit', minutes: 'min', max_minutes: 'Limit min', sections: 'Bereiche', stored: 'Zugangsdaten gespeichert',
  namespace: 'Namespace', tag: 'Tag', title: 'Titel', name: 'Name', force: 'erzwungen', forced: 'trotz Doppelt', blocked: 'blockiert', error: 'Fehler',
  local: 'lokal gelöscht', remote: 'entfernt gelöscht', days: 'Tage', phase: 'Station', pool_id: 'Kategorie' };
function audDetail(d) {
  const out = [];
  for (const [k, lab] of Object.entries(AUD_KEYS)) {
    let v = d[k];
    if (v === undefined || v === null || v === '' || v === false || (Array.isArray(v) && !v.length)) continue;
    if (k === 'phase' && state && state.flow && state.flow.phases[v]) v = state.flow.phases[v].label;
    if (Array.isArray(v)) v = v.join(', ');
    else if (typeof v === 'object') v = Object.entries(v).map(([a, b]) => a + ' ' + b).join(', ');
    else if (v === true) v = 'ja';
    out.push(`${lab}: ${esc(v)}`);
  }
  return out.join(' · ');
}
const audWhen = (ts, short) => new Date(ts * 1000).toLocaleString('de-CH', short ? { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' } : { day: '2-digit', month: '2-digit', year: '2-digit', hour: '2-digit', minute: '2-digit' });
function audRows(rows, short) {
  if (!rows.length) return `<li class="quiet small" style="display:block">${short ? 'Noch nichts entschieden.' : 'Noch keine Einträge.'}</li>`;
  return rows.map(r => {
    const det = audDetail(r.detail || {});
    const by = r.actor && r.actor !== 'du' ? `<span class="by">${esc(r.actor)}</span>` : '';
    return `<li class="${r.ok ? '' : 'fail'}"><time datetime="${new Date(r.ts * 1000).toISOString()}" title="#${r.id} · ${esc(r.hash.slice(0, 12))}">${audWhen(r.ts, short)}</time><div class="what"><b>${esc(r.label)}</b>${short ? '' : `<span class="tg">${esc(r.target)}</span>`}${by}</div>${det ? `<div class="det">${det}</div>` : ''}</li>`;
  }).join('');
}
function setLogView(v) {
  LOGVIEW = v; try { localStorage.setItem('tinyops.logview', v); } catch (e) { /* egal */ }
  document.querySelectorAll('#logSeg button').forEach(b => b.classList.toggle('on', b.dataset.logview === v));
  $('logPane').hidden = v !== 'log'; $('logTools').hidden = v !== 'log';
  $('audPane').hidden = v !== 'audit'; $('audTools').hidden = v !== 'audit';
}
async function showAudit() {
  const r = await api('GET', '/api/audit?limit=500');
  $('audList').innerHTML = audRows(r.rows, false);
  $('audState').innerHTML = `<span class="quiet">${r.rows.length} neueste Einträge · Instanz <code>${esc(r.instance)}</code></span>`;
}
document.querySelectorAll('#logSeg button').forEach(b => b.onclick = () => { setLogView(b.dataset.logview); showLog(); });
document.getElementById('audExport').onclick = async () => {
  try {
    const r = await fetch('/api/audit/export', { headers: H });
    if (!r.ok) throw new Error('Export fehlgeschlagen (HTTP ' + r.status + ')');
    const name = ((r.headers.get('Content-Disposition') || '').match(/filename="([^"]+)"/) || [])[1] || 'tinyops-audit.json';
    const a = document.createElement('a'); a.href = URL.createObjectURL(await r.blob()); a.download = name; a.click();
    setTimeout(() => URL.revokeObjectURL(a.href), 2000);
    toast('Verlauf exportiert: ' + name);
  } catch (e) { toast(e.message); }
};
document.getElementById('audVerify').onclick = async () => {
  try {
    const v = await api('GET', '/api/audit/verify');
    $('audState').innerHTML = v.ok ? `<span class="chip sq-ok">${ic('check')} Kette in Ordnung</span> <span class="quiet">${v.count} Einträge, letzter Hash <code>${esc((v.last_hash || '').slice(0, 16))}</code></span>`
      : `<span class="chip warn">Kette gebrochen bei #${esc(v.broken_at)}</span> <span>${esc(v.reason)}</span>`;
  } catch (e) { toast(e.message); }
};
async function showLog() {
  const dlg = document.getElementById('logDlg');
  setLogView(LOGVIEW);
  if (LOGVIEW === 'audit') {
    try { await showAudit(); if (!dlg.open) dlg.showModal(); } catch (e) { toast(e.message); }
    return;
  }
  try {
    const r = await api('GET', '/api/log?n=400&level=' + document.getElementById('logLevel').value);
    document.getElementById('logFile').textContent = 'Datei: ' + r.file + ' (Stufe: ' + r.level + ')';
    const pre = document.getElementById('logText');
    pre.textContent = r.lines.length ? r.lines.join('\n') : '(noch keine Einträge in dieser Stufe)';
    if (!dlg.open) dlg.showModal();
    pre.scrollTop = pre.scrollHeight;
  } catch (e) { toast(e.message); }
}
document.getElementById('logBtn').onclick = showLog;
document.getElementById('logReload').onclick = showLog;
document.getElementById('logLevel').onchange = showLog;
document.getElementById('logClose').onclick = () => document.getElementById('logDlg').close();
document.getElementById('dlgClose').onclick = () => document.getElementById('dlg').close();
document.getElementById('dlgCopy').onclick = () => {
  const t = document.getElementById('dlgText'); t.select();
  document.execCommand('copy'); toast('Kopiert');
};
document.getElementById('refresh').onclick = async () => {
  try { await api('POST', '/api/refresh', {}); } catch (e) { toast(e.message); }
  load();
};
// ---------------------------------------------------------------- Einstellungen
let S = null;          // Antwort von /api/settings
let P = [];            // Arbeitskopie der Projekte
let CN = [], AGC = []; // Arbeitskopien der SSH-Verbindungen und Agenten
let GH = [];           // Arbeitskopie der GitHub-Repos
let view = 'focus';
function setView(v) {
  uxPush({ k: 'view', t: v });
  if (v === 'ideas' && !matchMedia('(max-width: 960px)').matches) v = 'focus';
  view = v;
  $('viewFocus').hidden = v !== 'focus';
  document.getElementById('viewOverview').hidden = ['settings', 'board', 'focus', 'time', 'qa', 'ws'].includes(v);
  $('viewWs').hidden = v !== 'ws';
  if (v === 'ws') loadWs(false);
  $('viewTime').hidden = v !== 'time';
  $('viewQa').hidden = v !== 'qa';
  document.getElementById('viewBoard').hidden = v !== 'board';
  document.getElementById('viewSettings').hidden = v !== 'settings';
  $('viewOverview').classList.toggle('showideas', v === 'ideas');
  document.querySelectorAll('.tab, .bn').forEach(t => t.classList.toggle('on', t.dataset.view === v));
  try { history.replaceState(null, '', '#' + v); } catch (e) { /* egal */ }
  if (v === 'settings') loadSettings();
  if (v === 'time') loadTime();
  if (v === 'qa') loadQa();
}
document.querySelectorAll('.tab, .bn').forEach(t => t.onclick = () => setView(t.dataset.view));
document.querySelectorAll('#pGl, #pJi').forEach(a => a.addEventListener('click', ev => { ev.preventDefault(); setView('settings'); }));
// Lesezeichen von admin.mistral.ai: «#mistral=<JSON>» enthält nur Prozent, Budget und Reset, nie Cookies
async function mistralPush() {
  const m = /^#mistral=(.+)$/.exec(location.hash);
  if (!m) return;
  history.replaceState(null, '', location.pathname + location.search);
  try {
    const r = await api('POST', '/api/usage/push', JSON.parse(decodeURIComponent(m[1])));
    usageData = null; toast('Mistral-Stand übernommen'); loadUsage(true);
  } catch (e) { toast(e.message); }
}
