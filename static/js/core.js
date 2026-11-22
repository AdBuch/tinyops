// Bausteine für alle Ansichten: API, Meldungen, Kopieren, Speicher, Felder, Dialoge, Markdown, Piktogramme.
const H = { 'X-Requested-With': 'tinyops', 'Content-Type': 'application/json' };
let state = null;
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
async function api(method, path, body) {
  const t0 = performance.now(), ep = method + ' ' + String(path).split('?')[0].replace(/\/\d+(?=\/|$)/g, '/#');
  const track = !/^\/api\/ux\//.test(path) && typeof uxPush === 'function';
  let r;
  try { r = await fetch(path, { method, headers: H, body: body ? JSON.stringify(body) : undefined }); }
  catch (e) {
    if (track && !OFFLINE) uxPush({ k: 'fail', t: ep, e: { m: 'Panel nicht erreichbar' } });
    const x = new Error('Keine Verbindung zu tinyops. Es läuft nicht oder startet gerade neu.'); x.offline = true; throw x;
  }
  if (OFFLINE) { setOffline(false); if (!String(path).startsWith('/api/overview')) setTimeout(load, 0); }      // wieder da: gleich den ganzen Stand holen
  const data = await r.json().catch(() => ({}));
  const ms = Math.round(performance.now() - t0);
  if (track && ms > 1500 && ep !== 'GET /api/overview') uxPush({ k: 'slow', t: ep, e: { ms } });
  if (!r.ok) {
    const e = new Error(data.error || ('HTTP ' + r.status)); e.data = data;
    if (track) uxPush({ k: 'fail', t: ep, e: { m: data.errors ? 'Felder: ' + Object.keys(data.errors).join(', ') : e.message, s: r.status } });
    throw e;
  }
  return data;
}
function stackToast(t) {   // mehrere Meldungen übereinander statt aufeinander
  const n = document.querySelectorAll('.toast').length;
  t.style.bottom = (70 + n * 52) + 'px';
}
function toast(msg) {
  const t = document.createElement('div');
  t.className = 'toast'; t.textContent = msg; stackToast(t);
  document.body.appendChild(t);
  setTimeout(() => t.remove(), 3200);
}
async function copyText(text, title) {
  try { await navigator.clipboard.writeText(text); toast('Kopiert'); return; } catch (e) { /* Fallback unten */ }
  document.getElementById('dlgTitle').textContent = title || 'Prompt';
  document.getElementById('dlgText').value = text;
  document.getElementById('dlg').showModal();
}
const $ = id => document.getElementById(id);
const F = () => (state && state.features) || {};
const LS = {
  get(k, d) { try { const v = localStorage.getItem('tinyops.' + k); return v === null ? d : JSON.parse(v); } catch (e) { return d; } },
  set(k, v) { try { localStorage.setItem('tinyops.' + k, JSON.stringify(v)); } catch (e) { /* egal */ } },
};
async function act(fn, ok) {
  try { const r = await fn(); if (ok) toast(ok); await load(); return r; } catch (e) { toast(e.message); }
}
const post = (path, body) => api('POST', path, body);
// 0.36: Jeder Dialog hat oben rechts ein ×, das beim Scrollen sichtbar bleibt, und schliesst mit einem Klick daneben,
// solange darin nichts Eingetipptes verloren ginge (Nutzungsbericht: 20 Wutklicks im Agentenfenster).
function dlgDirty(d) { return [...d.querySelectorAll('textarea, input[type=text], input:not([type])')].some(x => !x.readOnly && x.value !== x.defaultValue); }
document.querySelectorAll('dialog').forEach(d => {
  if (!d.querySelector(':scope > .dlgx')) {
    const x = document.createElement('button'); x.type = 'button'; x.className = 'dlgx'; x.textContent = '×'; x.title = 'Schliessen (Esc)'; x.setAttribute('aria-label', 'Schliessen');
    x.onclick = () => d.close(); d.prepend(x);
  }
  let downOut = false;
  const out = ev => { const r = d.getBoundingClientRect(); return ev.target === d && (ev.clientX < r.left || ev.clientX > r.right || ev.clientY < r.top || ev.clientY > r.bottom); };
  d.addEventListener('mousedown', ev => { downOut = out(ev); });
  d.addEventListener('click', ev => { if (downOut && out(ev)) { if (!dlgDirty(d)) d.close(); else toast('Noch nicht gespeichert. Schliessen mit × oder Esc.'); } downOut = false; });
});
// -- 0.31: Markdown lesbar anzeigen (sicher: erst alles escapen, dann wenige Formen), Zyklus, Prüfpunkte, Freigabe
function mdHtml(src) {
  const inl = t => esc(t).replace(/`([^`]+)`/g, '<code>$1</code>').replace(/\*\*([^*]+)\*\*/g, '<b>$1</b>');
  const out = []; let list = null, para = [], quote = [], fence = null, data = null;
  const flush = () => {
    if (para.length) { out.push('<p>' + para.map(inl).join('<br>') + '</p>'); para = []; }
    if (list) { out.push(`</${list}>`); list = null; }
    if (quote.length) { out.push('<blockquote>' + quote.map(inl).join('<br>') + '</blockquote>'); quote = []; }
  };
  for (const line of String(src || '').split('\n')) {
    if (fence !== null) { if (/^\s*```/.test(line)) { out.push('<pre>' + esc(fence.join('\n')) + '</pre>'); fence = null; } else fence.push(line); continue; }
    if (data !== null) { if (line.trim() === 'TICKET>>>') { out.push('<div class="mddata">' + esc(data.join('\n').trim()) + '</div>'); data = null; } else data.push(line); continue; }
    let m;
    if (/^\s*```/.test(line)) { flush(); fence = []; continue; }
    if (line.trim() === '<<<TICKET') { flush(); data = []; continue; }
    if (!line.trim()) { flush(); continue; }
    if ((m = line.match(/^(#{1,3})\s+(.*)$/))) { flush(); out.push(`<h${m[1].length + 2}>${inl(m[2])}</h${m[1].length + 2}>`); continue; }
    if ((m = line.match(/^>\s?(.*)$/))) { if (para.length || list) flush(); quote.push(m[1]); continue; }
    if ((m = line.match(/^\s{0,3}[-*]\s+(.*)$/)) || (m = line.match(/^\s{0,3}\d+[.)]\s+(.*)$/))) {
      const kind = /^\s{0,3}[-*]\s/.test(line) ? 'ul' : 'ol';
      if (para.length || quote.length || (list && list !== kind)) flush();
      if (!list) { list = kind; out.push(`<${kind}>`); }
      out.push('<li>' + inl(m[1]) + '</li>'); continue;
    }
    if (list && /^\s{2,}\S/.test(line)) { out[out.length - 1] = out[out.length - 1].replace(/<\/li>$/, '<br>' + inl(line.trim()) + '</li>'); continue; }
    if ((m = line.match(/^AK(\d{1,2}):\s*(.*)$/))) { flush(); out.push(`<span class="mdak"><b>AK${m[1]}</b> ${inl(m[2])}</span>`); continue; }
    if (quote.length) flush();
    para.push(line);
  }
  if (fence !== null) out.push('<pre>' + esc(fence.join('\n')) + '</pre>');
  if (data !== null) out.push('<div class="mddata">' + esc(data.join('\n').trim()) + '</div>');
  flush();
  return out.join('');
}
// Prompt als lesbares Markdown (Ansehen) oder als Text (Bearbeiten), immer kopierbar. Die Textarea bleibt die Quelle.
function promptBoxHtml(id, label, text, editable) {
  const mode = editable ? LS.get('agpv', 'view') : 'view';
  return `<div class="pbox"><div class="pbar"><label class="sm" for="${id}">${label}</label>
    ${editable ? `<span class="seg" role="group" aria-label="Ansicht"><button type="button" data-pv="view" class="${mode === 'view' ? 'on' : ''}">Ansehen</button><button type="button" data-pv="edit" class="${mode === 'edit' ? 'on' : ''}">Bearbeiten</button></span>` : ''}
    <button type="button" data-pcopy="${id}" title="Prompt in die Zwischenablage">${ic('copy')} Kopieren</button></div>
    <div class="mdv" data-pview="${id}" ${mode === 'edit' ? 'hidden' : ''}>${mdHtml(text)}</div>
    <textarea id="${id}" spellcheck="false" ${mode === 'view' ? 'hidden' : ''} ${editable ? '' : 'readonly'}>${esc(text)}</textarea></div>`;
}
function wirePromptBox(root, id) {
  const ta = $(id), pv = root.querySelector(`[data-pview="${id}"]`);
  root.querySelectorAll('[data-pv]').forEach(b => b.onclick = () => {
    const edit = b.dataset.pv === 'edit';
    root.querySelectorAll('[data-pv]').forEach(x => x.classList.toggle('on', x === b));
    if (!edit) pv.innerHTML = mdHtml(ta.value);
    pv.hidden = edit; ta.hidden = !edit; LS.set('agpv', b.dataset.pv);
    if (edit) ta.focus();
  });
  const cp = root.querySelector(`[data-pcopy="${id}"]`);
  if (cp) cp.onclick = () => copyText(ta.value, 'Prompt');
}
const val = id => ($(id) ? $(id).value : '').trim();
const split = t => t.split(/[,\n]/).map(x => x.trim()).filter(Boolean);
const uniq = a => [...new Set(a)];
function field(id, label, value, opts = {}) {
  const t = opts.type || 'text';
  const input = opts.area
    ? `<textarea class="full" id="${id}" rows="${opts.rows || 3}" spellcheck="false">${esc(value)}</textarea>`
    : `<input type="${t}" id="${id}" value="${esc(value)}" ${opts.ph ? `placeholder="${esc(opts.ph)}"` : ''} autocomplete="off" spellcheck="false">`;
  return `<div class="field"><label for="${id}">${esc(label)}</label>${input}
    ${opts.help ? `<div class="help">${opts.help}</div>` : ''}<div class="ferr" data-err="${esc(opts.err || '')}"></div></div>`;
}
// ================================================================ Fokus: jede Aufgabe fährt dieselbe Strecke, genau ein nächster Schritt
const ICONS = {
  ext: '<path d="M14 4h6v6M20 4l-9 9M18 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1h5"/>',
  chat: '<path d="M5 5h14a1 1 0 0 1 1 1v9a1 1 0 0 1-1 1h-8l-4 3.5V16H5a1 1 0 0 1-1-1V6a1 1 0 0 1 1-1z"/>',
  down: '<path d="M12 4v11M7 10.5l5 5 5-5M5 20h14"/>',
  ide: '<rect x="3.5" y="3.5" width="17" height="17" rx="2"/><path d="M7 16.5h5M7.5 7.5l3 3-3 3"/>',
  globe: '<circle cx="12" cy="12" r="8.5"/><path d="M3.5 12h17M12 3.5c2.5 2.6 3.5 5.4 3.5 8.5s-1 5.9-3.5 8.5c-2.5-2.6-3.5-5.4-3.5-8.5s1-5.9 3.5-8.5z"/>',
  bulb: '<path d="M9 18h6M10 21h4M12 3a6 6 0 0 0-4 10.5c.7.7 1 1.5 1 2.5h6c0-1 .3-1.8 1-2.5A6 6 0 0 0 12 3z"/>',
  copy: '<rect x="9" y="9" width="11" height="11" rx="2"/><path d="M5 15V5a1 1 0 0 1 1-1h10"/>',
  check: '<path d="M5 12.5l4.5 4.5L19 7.5"/>',
  play: '<path d="M8 5.5v13l10.5-6.5z"/>',
  eye: '<path d="M2.5 12S6 5.5 12 5.5 21.5 12 21.5 12 18 18.5 12 18.5 2.5 12 2.5 12z"/><circle cx="12" cy="12" r="2.8"/>',
  branch: '<circle cx="6" cy="5.5" r="2"/><circle cx="6" cy="18.5" r="2"/><circle cx="18" cy="7.5" r="2"/><path d="M6 7.5v9M18 9.5c0 4.5-6 3.5-11 7.5"/>',
  mr: '<circle cx="6" cy="5.5" r="2"/><circle cx="6" cy="18.5" r="2"/><circle cx="18" cy="18.5" r="2"/><path d="M6 7.5v9M18 16.5V9a3 3 0 0 0-3-3h-4M13 3.5 10.5 6 13 8.5"/>',
  merge: '<circle cx="6" cy="5.5" r="2"/><circle cx="6" cy="18.5" r="2"/><circle cx="18" cy="12" r="2"/><path d="M6 7.5v9M6 8c0 3 4 4 10 4"/>',
  alert: '<path d="M12 4 2.8 19.5h18.4z"/><path d="M12 10v4M12 17v.01"/>',
  clock: '<circle cx="12" cy="12" r="8.5"/><path d="M12 7.5V12l3 2"/>',
  bot: '<rect x="4.5" y="8" width="15" height="11" rx="3"/><path d="M12 4v4M9 13v.01M15 13v.01M9.5 16h5"/>',
  users: '<circle cx="9" cy="8.5" r="3"/><path d="M3.5 19c.6-3 2.8-4.5 5.5-4.5s4.9 1.5 5.5 4.5M16 5.8a3 3 0 0 1 0 5.4M17.5 14.7c1.6.6 2.7 2 3 4.3"/>',
  gear: '<circle cx="12" cy="12" r="3"/><path d="M12 2.8v2.4M12 18.8v2.4M2.8 12h2.4M18.8 12h2.4M5.5 5.5l1.7 1.7M16.8 16.8l1.7 1.7M5.5 18.5l1.7-1.7M16.8 7.2l1.7-1.7"/>',
  x: '<path d="M6 6l12 12M18 6 6 18"/>',
  flame: '<path d="M12 21c-4 0-6.5-2.6-6.5-6 0-3.6 3-5.6 3.5-9 2.4 1.4 3.6 3.6 3.6 5.6 1-.6 1.8-1.7 2-3 2 1.6 3.9 3.9 3.9 6.4 0 3.4-2.5 6-6.5 6z"/>',
  skip: '<path d="M6 6l7 6-7 6zM16 6v12"/>',
  list: '<path d="M9 6h11M9 12h11M9 18h11M4.5 6h.01M4.5 12h.01M4.5 18h.01"/>',
  chevron2: '<path d="M5 12h13M13 6.5 18.5 12 13 17.5"/>',
  ticket: '<path d="M4 7.5A1.5 1.5 0 0 1 5.5 6h13A1.5 1.5 0 0 1 20 7.5V10a2 2 0 0 0 0 4v2.5a1.5 1.5 0 0 1-1.5 1.5h-13A1.5 1.5 0 0 1 4 16.5V14a2 2 0 0 0 0-4z"/>',
  link: '<path d="M10 14a4 4 0 0 0 5.7 0l3-3a4 4 0 0 0-5.7-5.7l-1 1M14 10a4 4 0 0 0-5.7 0l-3 3a4 4 0 0 0 5.7 5.7l1-1"/>',
  flask: '<path d="M9.5 3.5h5M10.5 3.5v5L5 18.5A1.5 1.5 0 0 0 6.3 20.5h11.4a1.5 1.5 0 0 0 1.3-2L13.5 8.5v-5M7.5 14h9"/>',
};
const ic = (n, cls) => `<svg class="ic ${cls || ''}" viewBox="0 0 24 24" aria-hidden="true">${ICONS[n] || ''}</svg>`;
const short = (s, n) => (s = String(s || '')).length > n ? s.slice(0, n - 1) + '…' : s;
// -- 0.32: Piktogramme. Repo: symmetrisches 5×5-Muster, Branch: kleiner Git-Graph. Beide aus dem Namen errechnet,
// gleicher Name = gleiches Bild überall. Branch-Art steckt in der Form der Commits: feature ● · fix/bug/hotfix ◆ · agent ■ · sonst ●.
function hash32(s) { let h = 0x811c9dc5; for (const ch of String(s || '')) { h ^= ch.codePointAt(0); h = Math.imul(h, 0x01000193) >>> 0; } return h >>> 0; }
function repoIcon(name, sz = 18) {
  const h = hash32('repo:' + name), hue = h % 360, cells = [];
  for (let y = 0; y < 5; y++) for (let x = 0; x < 3; x++) if ((h >>> (y * 3 + x + 6)) & 1) { cells.push([x, y]); if (x < 2) cells.push([4 - x, y]); }
  return `<svg class="pic" width="${sz}" height="${sz}" viewBox="0 0 7 7" role="img" aria-label="Repo ${esc(name)}"><title>Repo ${esc(name)}</title><rect width="7" height="7" rx="1.6" fill="hsl(${hue} 60% 50%)" fill-opacity=".18"/>${cells.map(([x, y]) => `<rect x="${x + 1}" y="${y + 1}" width="1" height="1" fill="hsl(${hue} 60% 42%)"/>`).join('')}</svg>`;
}
function branchKind(b) { const l = String(b || '').toLowerCase(); return /^(fix|bug|bugfix|hotfix)[/-]/.test(l) ? 'fix' : /^agent\//.test(l) ? 'agent' : /^feat(ure)?[/-]/.test(l) ? 'feature' : 'other'; }
function branchIcon(name, sz = 18) {
  if (!name) return '';
  const h = hash32('branch:' + name), hue = (h % 12) * 30 + 8, n = 1 + (h >>> 8) % 3, fy = 13 - (h >>> 11) % 2 * 2, k = branchKind(name);
  const col = `hsl(${hue} 65% 42%)`, ys = [fy - 4, fy - 8, fy - 12].slice(0, n).map(y => Math.max(y, 2.5));
  const dot = (x, y) => k === 'fix' ? `<rect x="${x - 1.7}" y="${y - 1.7}" width="3.4" height="3.4" transform="rotate(45 ${x} ${y})" fill="${col}"/>`
    : k === 'agent' ? `<rect x="${x - 1.6}" y="${y - 1.6}" width="3.2" height="3.2" rx=".5" fill="${col}"/>` : `<circle cx="${x}" cy="${y}" r="1.8" fill="${col}"/>`;
  return `<svg class="pic" width="${sz}" height="${sz}" viewBox="0 0 18 18" role="img" aria-label="Branch ${esc(name)}"><title>Branch ${esc(name)}</title><rect width="18" height="18" rx="4" fill="${col}" fill-opacity=".14"/>
    <path d="M5 16V2" stroke="currentColor" stroke-opacity=".45" stroke-width="1.4"/><path d="M5 ${fy}C5 ${fy - 2.5} 12 ${fy - 1.5} 12 ${ys[0] + .5}V${ys[ys.length - 1]}" fill="none" stroke="${col}" stroke-width="1.6"/>
    <circle cx="5" cy="${fy}" r="1.5" fill="currentColor" fill-opacity=".55"/>${ys.map(y => dot(12, y)).join('')}</svg>`;
}
function picLine(c, sz = 18) {
  // Repo und Branch einer Karte als Piktogramme mit Namen
  const items = (c.items || []), proj = [...new Set(items.map(x => x.project).filter(Boolean))], brs = [...new Set(items.map(x => x.branch).filter(Boolean))];
  return `${proj.slice(0, 2).map(p => `<span class="picn">${repoIcon(p, sz)}<span>${esc(short(p, 28))}</span></span>`).join('')}${brs.slice(0, 2).map(b => `<span class="picn">${branchIcon(b, sz)}<code>${esc(short(b, 44))}</code></span>`).join('')}${brs.length > 2 ? `<span class="quiet">+${brs.length - 2}</span>` : ''}`;
}
