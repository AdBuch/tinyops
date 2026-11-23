// 0.42: Testen von Hand im Detail-Panel. Prüfliste je Ticket aus Kriterien, Testschritten und eigenen Punkten;
// «Jetzt testen» holt den Stand in IntelliJ (und startet die Review-Umgebung), Fehler gehen mit einem Klick zurück ans Entwickeln,
// alles ok wird zur Abnahme am Commit.
let TC = { key: null, d: null, t: 0, fail: null, steps: null };
function tcShow(e) { return e.t === 'card' && e.c && e.c.key && !e.c.idea_id && e.d.phase >= 4 && e.d.phase < 7; }
function tcHtml(e) {
  const key = e.c.key;
  if (TC.key !== key) { TC = { key, d: null, t: 0, fail: null, steps: null }; }
  if (!TC.d || Date.now() - TC.t > 20000) setTimeout(() => tcLoad(key), 0);
  const d = TC.d, sum = d && !d.error ? `${d.ok} ok${d.fail ? `, ${d.fail} Fehler` : ''}${d.open ? `, ${d.open} offen` : ''}` : '';
  return `<div class="tcsec${e.d.phase === 5 ? ' now' : ''}"><h3>Testen von Hand <small>${esc(sum)}</small></h3><div id="tcBox">${d ? tcInner(d) : '<div class="small quiet">Prüfliste lädt …</div>'}</div></div>`;
}
async function tcLoad(key) {
  TC.t = Date.now();
  try { const d = await post('/api/test/list', { key }); if (TC.key === key) TC.d = d; }
  catch (err) { if (TC.key === key) TC.d = { error: err.message }; }
  tcDraw();
}
function tcDraw() {
  const el = $('tcBox'); if (!el || !TC.d) return;
  const keep = ['tcNew', 'tcNote', 'tcBackNote'].filter(id => $(id)).map(id => ({ id, v: $(id).value, f: document.activeElement === $(id) }));
  el.innerHTML = tcInner(TC.d);
  const h = el.parentElement.querySelector('h3 small'), d = TC.d;
  if (h && !d.error) h.textContent = `${d.ok} ok${d.fail ? `, ${d.fail} Fehler` : ''}${d.open ? `, ${d.open} offen` : ''}`;
  keep.forEach(k => { const x = $(k.id); if (x) { x.value = k.v; if (k.f) x.focus(); } });
  if (TC.fail && $('tcNote') && !keep.some(k => k.f)) $('tcNote').focus();
}
function tcTarget(d) {
  const t = d.target || {};
  return t.mr ? `MR !${t.mr.iid}${t.mr.sha ? ' auf ' + t.mr.sha : ''}` : t.run ? `Branch von Lauf ${t.run}` : '';
}
function tcInner(d) {
  if (d.error) return `<div class="banner bad">${esc(d.error)}</div>`;
  const tgt = tcTarget(d);
  const top = `<div class="tctop">${tgt ? `<button class="primary" data-tcstart="1" title="Worktree auf ${esc(tgt)}, IntelliJ darauf, Review-Umgebung starten, wenn eingetragen. Nur auf diesem Rechner.">${ic('play')} Jetzt testen</button><span class="small quiet">${esc(tgt)}</span>` : '<span class="small quiet">Noch kein MR und kein Agenten-Branch zum Auschecken.</span>'}<span class="sp"></span><button class="quiet-btn" data-tccopy="1" title="Prüfliste als Markdown, z. B. für den MR">${ic('copy')} Kopieren</button></div>`;
  const steps = TC.steps ? `<ul class="tcsteps">${TC.steps.map(s => `<li class="${s.ok ? 'ok' : 'bad'}">${ic(s.ok ? 'check' : 'x')}<b>${esc(s.step)}</b><span>${esc(s.msg || '')}</span>${s.url ? `<a href="${esc(s.url)}" target="_blank" rel="noopener">${ic('ext')} Öffnen</a>` : ''}</li>`).join('')}</ul>` : '';
  const rows = d.items.map(i => {
    const src = `<span class="chip tcsrc" title="${esc(i.hint ? i.source + ': ' + i.hint : i.source)}">${esc(i.source === 'du' ? 'eigener' : i.source)}</span>`;
    const failing = TC.fail === i.id;
    return `<li class="tc-${i.state || 'open'}" data-tcid="${esc(i.id)}">
      <span class="tcbtn"><button class="tcok${i.state === 'ok' ? ' on' : ''}" data-tcset="ok" title="Geht" aria-label="Geht">${ic('check')}</button><button class="tcfail${i.state === 'fail' ? ' on' : ''}" data-tcset="fail" title="Geht nicht (mit einem Satz, was)" aria-label="Geht nicht">${ic('x')}</button></span>
      <div class="tctxt"><span>${esc(i.text)}</span>${i.note && !failing ? `<small>${esc(i.note)}</small>` : ''}${failing ? `<div class="tcnote"><input id="tcNote" maxlength="1000" placeholder="Was ging nicht? Geht so an den Entwickler." value="${esc(i.note || '')}" autocomplete="off"><button data-tcfailgo="1">Speichern</button></div>` : ''}</div>
      ${src}${i.own ? `<button class="quiet-btn" data-tcdel="1" title="Entfernen" aria-label="Entfernen">${ic('x')}</button>` : ''}</li>`;
  }).join('');
  const add = `<div class="ckadd"><input id="tcNew" maxlength="300" placeholder="Eigenen Prüfpunkt ergänzen, z. B. «Export mit 10'000 Zeilen»" autocomplete="off"><button data-tcadd="1">Hinzufügen</button></div>`;
  let foot = '';
  if (d.fail) foot = d.dev_run
    ? `<div class="tcfoot"><input id="tcBackNote" maxlength="1000" placeholder="Dazu (optional)" autocomplete="off"><button class="primary" data-tcback="1" title="Die Punkte mit Fehler und deine Notizen gehen in die Sitzung von ${esc(d.dev_agent)}">↺ ${d.fail} Fehler zurück an ${esc(d.dev_agent)}</button></div>`
    : `<div class="tcfoot"><button data-tccopy="fail">${ic('copy')} ${d.fail} Fehler kopieren</button><span class="small quiet">Kein Agent an diesem Ticket: selbst weitergeben.</span></div>`;
  else foot = `<div class="tcfoot">${d.open ? `<button data-tcdone="force" title="Abnahme am Commit, ${d.open} Punkt(e) bleiben offen">Trotzdem abnehmen (${d.open} offen)</button>` : `<button class="primary" data-tcdone="1" title="Abnahme am aktuellen Commit; neue Commits machen sie ungültig">${ic('check')} Alles ok: Getestet</button>`}</div>`;
  return top + steps + `<ul class="tc">${rows}</ul>` + add + foot;
}
function tcText(d, onlyFail) {
  const mark = { ok: '[x]', fail: '[ ] ✗', '': '[ ]' };
  return d.items.filter(i => !onlyFail || i.state === 'fail').map(i => `- ${mark[i.state || '']} ${i.text}${i.note ? ' — ' + i.note : ''}`).join('\n') + '\n';
}
async function tcPost(action, body) {
  try { const d = await post('/api/test/' + action, { key: TC.key, ...body }); if (d && d.items) { TC.d = d; TC.t = Date.now(); } tcDraw(); return d; }
  catch (err) { toast(err.message); return null; }
}
$('fx').addEventListener('click', async ev => {
  const t = ev.target, box = t.closest && t.closest('#tcBox');
  if (!box || !TC.key) return;
  const li = t.closest('[data-tcid]'), id = li && li.dataset.tcid;
  const set = t.closest('[data-tcset]');
  if (set && id) {
    const it = TC.d.items.find(x => x.id === id), want = set.dataset.tcset;
    if (want === 'fail' && TC.fail !== id && it.state !== 'fail') { TC.fail = id; tcDraw(); return; }
    TC.fail = null;
    await tcPost('check', { id, state: it.state === want ? '' : want });
    if (want === 'ok' && it.state !== 'ok') burstAt(set);
    return;
  }
  if (t.closest('[data-tcfailgo]') && TC.fail) { const note = $('tcNote').value.trim(); if (!note) { $('tcNote').focus(); toast('Ein Satz, was nicht ging.'); return; } const fid = TC.fail; TC.fail = null; await tcPost('check', { id: fid, state: 'fail', note }); return; }
  if (t.closest('[data-tcdel]') && id) { await tcPost('remove', { id }); return; }
  if (t.closest('[data-tcadd]')) { const v = $('tcNew').value.trim(); if (!v) { $('tcNew').focus(); return; } $('tcNew').value = ''; await tcPost('add', { text: v }); $('tcNew') && $('tcNew').focus(); return; }
  const cp = t.closest('[data-tccopy]');
  if (cp) { await copyText(tcText(TC.d, cp.dataset.tccopy === 'fail'), cp.dataset.tccopy === 'fail' ? 'Fehler' : 'Prüfliste'); return; }
  const st = t.closest('[data-tcstart]');
  if (st) {
    st.disabled = true;
    try { const r = await post('/api/test/start', { key: TC.key }); TC.steps = r.steps; const ok = r.steps.every(s => s.ok); toast(ok ? 'Stand liegt bereit. Viel Erfolg beim Testen.' : 'Nicht alles ging. Siehe oben in der Prüfliste.'); }
    catch (err) { toast(err.message); }
    st.disabled = false; tcDraw(); return;
  }
  const bk = t.closest('[data-tcback]');
  if (bk) {
    bk.disabled = true;
    const r = await tcPost('back', { note: $('tcBackNote') ? $('tcBackNote').value : '' });
    if (r) { toast(`${r.sent} Fehler an ${TC.d.dev_agent || 'den Entwickler'}${r.session ? ' (gleiche Sitzung)' : ''}: Lauf ${r.id}`); TC.t = 0; await load(); }
    else bk.disabled = false;
    return;
  }
  const dn = t.closest('[data-tcdone]');
  if (dn) {
    const r = await tcPost('done', { force: dn.dataset.tcdone === 'force' });
    if (r) { toast(`Abgenommen auf ${(r.commits || []).map(c => c.sha).join(', ') || 'dem aktuellen Stand'}. Neue Commits machen das ungültig.`); burstAt(dn); TC.t = 0; await load(); }
  }
});
document.addEventListener('keydown', ev => {
  if (ev.key !== 'Enter') return;
  if (ev.target.id === 'tcNew') { ev.preventDefault(); document.querySelector('[data-tcadd]').click(); }
  else if (ev.target.id === 'tcNote') { ev.preventDefault(); document.querySelector('[data-tcfailgo]').click(); }
  else if (ev.target.id === 'tcBackNote') { ev.preventDefault(); document.querySelector('[data-tcback]').click(); }
});
