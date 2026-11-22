// Prüfen: Prüfliste, Testsitzung, Nutzungsbericht, Hinweis nach einem Update.
// ------------------------------------------------ Hinweis nach einem Update durch den Starter
document.addEventListener('click', async ev => {
  const b = ev.target.closest && ev.target.closest('[data-upd]');
  if (!b) return;
  const what = b.dataset.upd;
  if (what === 'qa') setView('qa');
  if (what === 'log') { try { const r = await api('GET', '/api/update/news'); $('logDlg').showModal(); setLogView('log'); $('logFile').textContent = 'CHANGELOG.md'; $('logText').textContent = r.text || 'Keine Einträge.'; } catch (e) { toast(e.message); } return; }
  try { await post('/api/update/seen', {}); state.update = null; renderHeader(); } catch (e) { toast(e.message); }
});
// ------------------------------------------------ UI-Nutzung im Tab «Prüfen»
let UXR = null;
function uxCard() {
  if (!UXR) return '<div class="quiet small">UI-Nutzung wird geladen …</div>';
  if (!UXR.enabled) return '<h3>UI-Nutzung</h3><div class="small quiet">Ausgeschaltet (Einstellungen → Weiteres).</div>';
  return `<div class="row" style="justify-content:space-between"><h3 style="margin:0">UI-Nutzung <span class="quiet small">letzte ${UXR.days} Tage, nur lokal</span></h3>
      <span class="row"><select id="uxDays" aria-label="Zeitraum">${[1, 7, 30].map(d => `<option value="${d}" ${d === UXR.days ? 'selected' : ''}>${d === 1 ? 'heute' : d + ' Tage'}</option>`).join('')}</select><button class="primary" id="uxCopy">Bericht kopieren</button><button class="quiet-btn" id="uxClear">Daten löschen</button></span></div>
    <div class="psum" style="margin:6px 0"><span>Sitzungen <b>${UXR.sessions}</b></span><span>aktiv <b>${UXR.active_min} min</b></span><span>Ereignisse <b>${UXR.events}</b></span>${UXR.wishes ? `<span>Wünsche an tinyops <b>${UXR.wishes}</b></span>` : ''}</div>
    ${UXR.hints.length ? `<ul class="small" style="margin:4px 0 0 18px;padding:0">${UXR.hints.map(h => `<li>${esc(h)}</li>`).join('')}</ul>` : '<div class="small quiet">Noch nichts Auffälliges. Der Bericht enthält Ansichten, Aktionen mit Zögern, tote Klicks, Tasten, Dialoge und eine Maus-Verteilung.</div>'}
    <div class="small quiet" style="margin-top:6px">Erfasst werden Klicks (welches Element, nicht was darin steht), Mausweg, Tasten ausserhalb von Feldern, Ansichtswechsel, Fehlermeldungen und langsame Antworten (ohne Einzelheiten) und die Version. Wörtlich nur, was du als «Wunsch an tinyops» schreibst. Kopiere den Bericht und gib ihn mir für die nächste Runde.</div>`;
}
async function loadUx(days) {
  try { await uxFlush(false); UXR = await api('GET', '/api/ux/report?days=' + (days || (UXR && UXR.days) || 7)); } catch (e) { UXR = null; }
  if ($('qUx')) $('qUx').innerHTML = uxCard();
}
$('viewQa').addEventListener('click', async ev => {
  if (ev.target.closest('#uxCopy')) { await loadUx(); if (UXR) await copyText(UXR.text, 'Bericht zur UI-Nutzung'); }
  if (ev.target.closest('#uxClear')) { if (!confirm('Alle erfassten UI-Daten löschen?')) return; try { const r = await post('/api/ux/clear', {}); toast(r.deleted + ' Ereignisse gelöscht'); } catch (e) { toast(e.message); } loadUx(); }
});
$('viewQa').addEventListener('change', ev => { if (ev.target.id === 'uxDays') loadUx(+ev.target.value); });
// ------------------------------------------------ Prüfen (0.19): Prüfliste je Release und Selbsttest
let QA = null, QAONLY = false, QARES = null, QAREST = LS.get('qarest', true);
const QNOTE = new Set(), QPEND = new Set();   // 0.35: Notiz per Klick auf den Text; Doppelklicks auf ok/Fehler nicht doppelt senden
try { QAONLY = localStorage.getItem('tinyops.qaonly') === '1'; } catch (e) { /* egal */ }
async function loadQa() {
  loadUx();
  try { QA = await api('GET', '/api/qa'); renderQa(); } catch (e) { $('viewQa').innerHTML = `<div class="banner bad">${esc(e.message)}</div>`; }
}
function renderQa() {
  const all = QA.sections.flatMap(x => x.items), done = all.filter(i => i.status !== 'offen').length, fails = all.filter(i => i.status === 'fehler').length;
  const keep = [...document.querySelectorAll('#viewQa textarea[data-qnote]')].map(t => [t.dataset.qnote, t.value, document.activeElement === t]);
  const openSet = new Set([...document.querySelectorAll('#viewQa details[data-qsec][open]')].map(d => d.dataset.qsec));
  const first = !document.querySelector('#viewQa details[data-qsec]');
  const md = t => esc(t).replace(/`([^`]+)`/g, '<code>$1</code>');
  const item = i => `<div class="qitem st-${esc(i.status)}"><span class="qb" role="group" aria-label="Ergebnis">
      <button class="${i.status === 'ok' ? 'on ok' : ''}" data-qset="${esc(i.id)}" data-s="ok" title="ok">${ic('check')}</button><button class="${i.status === 'fehler' ? 'on fehler' : ''}" data-qset="${esc(i.id)}" data-s="fehler" title="Fehler">${ic('x')}</button><button class="${i.status === 'übersprungen' ? 'on übersprungen' : ''}" data-qset="${esc(i.id)}" data-s="übersprungen" title="übersprungen">–</button></span>
    <div class="qtxt" data-qtxt="${esc(i.id)}" title="Klick: Notiz schreiben · Klick auf Code: kopieren"><div class="tx">${md(i.text)}</div>${i.expect ? `<div class="ex">erwartet: ${md(i.expect)}</div>` : ''}${i.changed ? '<div class="ex" style="color:var(--warn)">Text geändert, bitte neu prüfen</div>' : ''}</div>
    <span class="qid" title="${i.checked_in ? 'geprüft in ' + esc(i.checked_in) : ''}">${esc(i.id)}</span>
    ${i.status === 'fehler' ? `<textarea data-qnote="${esc(i.id)}" placeholder="Was ist passiert? (wird mit «Ergebnis kopieren» mitgegeben)">${esc(i.note)}</textarea><div style="grid-column:2/-1"><button class="quiet-btn" data-qtask="${esc(i.id)}">Als Aufgabe ins Board</button></div>`
      : QNOTE.has(i.id) || i.note ? `<textarea data-qnote="${esc(i.id)}" data-keep="1" placeholder="Notiz zu diesem Punkt (geht mit ok oder Fehler mit)">${esc(i.note)}</textarea>` : ''}</div>`;
  // Testsitzung (0.31): die nächsten fünf offenen Punkte, dieses Release zuerst. Ältere Releases ruhen, bis du sie holst.
  const vnum = v => (v || '0.0.0').split('.').map(Number);
  const cur = vnum(QA.version), recent = sec => !sec.version || sec.current || (vnum(sec.version)[0] === cur[0] && cur[1] - vnum(sec.version)[1] <= 1);
  const active = QA.sections.filter(x => !QAREST || recent(x)), resting = QA.sections.filter(x => QAREST && !recent(x));
  const prio = sec => (sec.current ? 0 : sec.version ? 1 + (cur[1] - vnum(sec.version)[1]) : 50);
  const queue = active.flatMap(sec => sec.items.filter(i => i.status === 'offen').map(i => [i.changed ? -1 : prio(sec), sec, i]))
    .sort((x, y) => x[0] - y[0]).map(x => x[2]);
  const next5 = queue.slice(0, 5), restOpen = resting.reduce((n, x) => n + x.total - x.done, 0);
  const sessDone = (() => { try { return JSON.parse(sessionStorage.getItem('tinyops.qsess') || '[]'); } catch (e) { return []; } })();
  $('viewQa').innerHTML = `<div class="phead"><h1>Prüfliste tinyops ${esc(QA.version)}</h1><span class="sp"></span>
      <div class="psum"><span>geprüft <b>${done}/${all.length}</b></span><span>Fehler <b>${fails}</b></span></div>
      <label class="check"><input type="checkbox" id="qOnly" ${QAONLY ? 'checked' : ''}><span>nur offene</span></label>
      <button id="qSelf">Selbsttest ausführen</button><button class="primary" id="qRep">Ergebnis kopieren</button></div>
    <section class="pcard qsess"><div class="row" style="justify-content:space-between"><h2 style="margin:0;font-size:16px">Als Nächstes testen</h2>
      <span class="quiet small">${sessDone.length ? `in dieser Sitzung ${sessDone.length} erledigt · ` : ''}noch ${queue.length} offen${restOpen ? `, ${restOpen} in älteren Releases ruhen` : ''}</span></div>
      <div class="small quiet" style="margin:2px 0 8px">Fünf Punkte auf einmal, das aktuelle Release zuerst. Was nicht zutrifft oder dich nicht betrifft: überspringen (–). Fehler mit einem Satz notieren.</div>
      ${next5.map(item).join('') || '<div class="banner" style="margin:0">Nichts offen in den aktuellen Releases. Gut so.</div>'}</section>
    <div class="pcard" id="qUx">${uxCard()}</div>
    <div id="qSelfRes">${QARES ? `<details class="pcard" ${QARES.ok ? '' : 'open'}><summary><b>${QARES.ok ? 'Selbsttest bestanden' : 'Selbsttest mit Fehlern'}</b> <span class="quiet small">${QARES.steps.length} Prüfungen, ${QARES.secs} s${QARES.steps.some(x => x.status === 'warn') ? ', mit Warnungen' : ''}</span></summary>${stepsHtml(QARES).replace(/<div class="verdict[^>]*>[^<]*<\/div>/, '')}</details>` : '<div class="small quiet" style="margin-bottom:10px">Der Selbsttest prüft Vorlagen, Hilfsskripte, Datenbank und Verlauf und spielt die Kernfunktionen mit Demo-Daten in einem leeren Ordner durch. Deine Daten bleiben unberührt.</div>'}</div>
    <div class="row small" style="margin:14px 0 6px"><b>Alle Abschnitte</b><span class="sp"></span><label class="check"><input type="checkbox" id="qRest" ${QAREST ? 'checked' : ''}><span>ältere Releases ruhen lassen</span></label></div>
    ${[...active].sort((a, z) => (z.version ? 1 : 0) - (a.version ? 1 : 0) || (z.version || '').localeCompare(a.version || '', undefined, { numeric: true })).map(sec => {
      const items = sec.items.filter(i => i.status !== 'auto' && (!QAONLY || i.status === 'offen')), autos = sec.items.filter(i => i.status === 'auto');
      const isOpen = first ? (!next5.length && sec.current) : openSet.has(sec.title);
      return `<details class="pcard qsec" data-qsec="${esc(sec.title)}" ${isOpen ? 'open' : ''}><summary>${esc(sec.title)}${sec.current ? ' <span class="chip tk">dieses Release</span>' : ''}<span class="sp"></span>${sec.fails ? `<span class="chip sq-bad">${sec.fails} Fehler</span>` : ''}<span class="quiet small">${sec.total ? `${sec.done}/${sec.total}` : 'alles automatisch'}</span><span class="qbar"><i style="width:${sec.total ? Math.round(100 * sec.done / sec.total) : 100}%"></i></span></summary>
        ${items.map(item).join('') || (sec.total ? '<div class="quiet small">alles geprüft</div>' : '')}
        ${autos.length ? `<details class="qauto"><summary class="quiet small">${autos.length} Punkt${autos.length === 1 ? '' : 'e'} prüft ein automatischer Test bei jedem Release</summary>
          <ul>${autos.map(i => `<li><span>${md(i.text)}${i.expect ? ` → ${md(i.expect)}` : ''}</span><code>${esc(i.auto)}</code></li>`).join('')}</ul></details>` : ''}</details>`;
    }).join('')}
    ${resting.length ? `<div class="quiet small" style="margin:6px 0">${resting.length} ältere Abschnitte ruhen (${restOpen} offen). Sie zählen nicht in «Als Nächstes». Zum Ansehen den Haken oben lösen.</div>` : ''}
    <div class="quiet small">Quelle: <code>${esc(QA.file)}</code>. Je Release kommt ein Abschnitt dazu, nur mit dem, was sich geändert hat.</div>`;
  keep.forEach(([id, v, f]) => { const t = document.querySelector(`#viewQa textarea[data-qnote="${CSS.escape(id)}"]`); if (t) { t.value = v; if (f) t.focus(); } });
}
$('viewQa').addEventListener('click', async ev => {
  const t = ev.target;
  const b = t.closest('[data-qset]');
  if (b) {
    if (QPEND.has(b.dataset.qset)) return;
    const cur = QA.sections.flatMap(x => x.items).find(i => i.id === b.dataset.qset);
    const s2 = cur && cur.status === b.dataset.s ? 'offen' : b.dataset.s;
    const ta0 = document.querySelector(`#viewQa textarea[data-qnote="${CSS.escape(b.dataset.qset)}"]`);
    const note = ta0 ? ta0.value : (cur && cur.note) || '';
    QPEND.add(b.dataset.qset);
    if (cur) { cur.status = s2; cur.note = note; renderQa(); }              // sofort zeigen, dann speichern
    try { await post('/api/qa/set', { id: b.dataset.qset, status: s2, note: s2 === 'offen' ? '' : note });
      try { const ss = new Set(JSON.parse(sessionStorage.getItem('tinyops.qsess') || '[]')); s2 === 'offen' ? ss.delete(b.dataset.qset) : ss.add(b.dataset.qset); sessionStorage.setItem('tinyops.qsess', JSON.stringify([...ss])); } catch (e2) { /* egal */ }
      QNOTE.delete(b.dataset.qset);
      await loadQa(); if (s2 === 'fehler') { const ta = document.querySelector(`#viewQa textarea[data-qnote="${CSS.escape(b.dataset.qset)}"]`); if (ta) ta.focus(); } } catch (e) { toast(e.message); await loadQa(); }
    finally { QPEND.delete(b.dataset.qset); }
    return;
  }
  const cd = t.closest('.qtxt code');
  if (cd) { copyText(cd.textContent, 'Befehl'); return; }
  const qt = t.closest('[data-qtxt]');
  if (qt && !window.getSelection().toString()) {
    const id = qt.dataset.qtxt; QNOTE.has(id) ? QNOTE.delete(id) : QNOTE.add(id); renderQa();
    const ta = document.querySelector(`#viewQa textarea[data-qnote="${CSS.escape(id)}"]`); if (ta) ta.focus();
    return;
  }
  const tk = t.closest('[data-qtask]');
  if (tk) { try { const r = await post('/api/qa/task', { id: tk.dataset.qtask }); toast(`${r.key} im Ideenpool angelegt`); } catch (e) { toast(e.message); } return; }
  if (t.closest('#qRep')) { try { const r = await post('/api/qa/report', {}); await copyText(r.text, 'Prüfergebnis'); } catch (e) { toast(e.message); } return; }
  if (t.closest('#qSelf')) {
    await busy($('qSelf'), 'Prüfe …', async () => { try { QARES = await post('/api/qa/selftest', {}); renderQa(); } catch (e) { toast(e.message); } });
  }
});
$('viewQa').addEventListener('change', async ev => {
  const t = ev.target;
  if (t.id === 'qRest') { QAREST = t.checked; LS.set('qarest', QAREST); renderQa(); return; }
  if (t.id === 'qOnly') { QAONLY = t.checked; try { localStorage.setItem('tinyops.qaonly', QAONLY ? '1' : '0'); } catch (e) { /* egal */ } renderQa(); return; }
  if (t.dataset.qnote && t.dataset.keep) { const it = QA.sections.flatMap(x => x.items).find(i => i.id === t.dataset.qnote); if (it) { it.note = t.value; if (it.status !== 'offen') { try { await post('/api/qa/set', { id: it.id, status: it.status, note: t.value }); } catch (e) { toast(e.message); } } } return; }
  if (t.dataset.qnote) { try { await post('/api/qa/set', { id: t.dataset.qnote, status: 'fehler', note: t.value }); const it = QA.sections.flatMap(x => x.items).find(i => i.id === t.dataset.qnote); if (it) it.note = t.value; } catch (e) { toast(e.message); } }
});
