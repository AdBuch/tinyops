// Einen Branch in einen anderen übernehmen (0.41): z. B. den Branch eines Agenten in den Feature-Branch des Tickets.
// Fast-Forward, Merge, Rebase (Commits obendrauf) oder Cherry-Pick, lokal in deinem Checkout. tinyops pusht nie.
const BR_HOW = [
  ['ff', 'Fast-Forward', 'Nur wenn der Ziel-Branch nichts Eigenes hat. Keine neuen Commits, einfach nachgezogen.'],
  ['rebase', 'Rebase', 'Die Commits obendrauf, gerade Geschichte. Die Commits bekommen neue Kennungen.'],
  ['merge', 'Merge', 'Ein Merge-Commit führt beide zusammen. Die Geschichte bleibt, wie sie war.'],
  ['pick', 'Cherry-Pick', 'Nur die angehakten Commits, in dieser Reihenfolge.'],
];
// Ziele für einen Branch: die anderen Branches der Aufgabe, MR-Branches zuerst, Agenten-Branches zuletzt
function brTargets(c, x) {
  const seen = new Set([x.branch]), out = [];
  const items = [...(c.items || [])].sort((a, b) => (!!a.by_agent - !!b.by_agent) || (!!b.iid - !!a.iid));
  for (const it of items) {
    if (!it.branch || seen.has(it.branch) || it.project_id !== x.project_id) continue;
    seen.add(it.branch); out.push(it.branch);
  }
  return out;
}
let BR = null;
async function openBranchDlg(o) {
  BR = { o, target: o.targets[0], plan: null, how: null, res: null };
  $('brDlg').showModal();
  await brLoad();
}
async function brLoad() {
  const { o } = BR;
  BR.plan = null; BR.res = null;
  brDraw();
  try { BR.plan = await post('/api/branch/plan', { host: o.host, project_id: o.project_id, source: o.source, target: BR.target }); }
  catch (e) { BR.err = e.message; }
  if (BR.plan) BR.how = BR.plan.can_ff ? 'ff' : (BR.plan.conflicts && BR.plan.conflicts.length ? 'merge' : 'rebase');
  brDraw();
}
function brDraw() {
  const { o, plan: p, res } = BR;
  const head = `<h2 style="margin-top:0">${ic('merge')} Übernehmen</h2>
    <div class="row small" style="gap:6px;align-items:center"><span class="picn">${branchIcon(o.source, 15)}<code>${esc(o.source)}</code></span> →
      ${o.targets.length > 1 ? `<select id="brTarget" aria-label="Ziel-Branch">${o.targets.map(t => `<option ${t === BR.target ? 'selected' : ''}>${esc(t)}</option>`).join('')}</select>`
        : `<span class="picn">${branchIcon(BR.target, 15)}<code>${esc(BR.target)}</code></span>`}</div>`;
  let body;
  if (res && res.ok) {
    body = `<div class="gatebox ok"><b>${res.added ? `${res.added} Commit${res.added === 1 ? '' : 's'} in ${esc(res.target)} übernommen` : esc(res.note || 'Nichts zu tun.')}</b>
        <div class="small">${res.ahead ? `Dein lokaler ${esc(res.target)} ist ${res.ahead} Commit${res.ahead === 1 ? '' : 's'} vor GitLab. ` : ''}${res.checked_out ? `In ${esc(res.checked_out)} nachgezogen. ` : ''}${res.note && res.added ? esc(res.note) : ''}</div>
        <div class="small" style="margin-top:6px">Pushen machst du (tinyops pusht nie): <code>${esc(res.push)}</code> <button class="quiet-btn" id="brPush">kopieren</button></div></div>`;
  } else if (res && res.conflict) {
    body = `<div class="gatebox back"><b>Konflikt in ${res.conflict.length} Datei${res.conflict.length === 1 ? '' : 'en'}</b>
        <ul class="small">${res.conflict.slice(0, 12).map(f => `<li><code>${esc(f)}</code></li>`).join('')}</ul>
        ${res.token ? `<div class="small">Der Worktree <code>${esc(res.worktree)}</code> ist ${res.ide ? 'in IntelliJ offen' : 'bereit'}. ${esc(res.hint)}${res.ide ? '' : ' ' + esc(res.ide_msg || '')}</div>
          <div class="row" style="margin-top:6px"><button class="primary" id="brFinish">Abschliessen</button><button id="brAbort">Abbrechen, nichts übernehmen</button></div>`
          : `<div class="small">${esc(res.text || '')} Nimm «Bei Konflikt in IntelliJ lösen» oder einen anderen Weg.</div>`}</div>`;
  } else if (!p) {
    body = BR.err ? `<div class="err small">${esc(BR.err)}</div>` : '<div class="small quiet">Hole beide Branches und sehe nach …</div>';
  } else {
    const cf = p.conflicts === null ? '<span class="quiet">Konflikte: unbekannt (git zu alt für eine Vorschau).</span>'
      : p.conflicts.length ? `<span class="chip warn">Konflikt erwartet</span> in ${p.conflicts.slice(0, 6).map(f => `<code>${esc(f)}</code>`).join(', ')}${p.conflicts.length > 6 ? ' …' : ''}`
        : '<span class="chip sq-ok">keine Konflikte erwartet</span>';
    const warn = [p.diverged ? `Dein lokaler ${esc(p.target)} und der auf GitLab sind auseinandergelaufen. Erst selbst zusammenführen (pull).` : '',
      p.dirty ? `${esc(p.target)} ist in <code>${esc(p.checked_out)}</code> ausgecheckt und hat geänderte Dateien. Erst committen oder beiseitelegen.` : '',
      p.behind_origin ? `Dein lokaler ${esc(p.target)} ist hinter GitLab; tinyops nimmt den Stand von GitLab als Ausgang.` : ''].filter(Boolean);
    body = p.up_to_date ? `<div class="gatebox ok small">${esc(p.source)} ist schon ganz in ${esc(p.target)}. Nichts zu tun.</div>` : `
      <div class="small">${p.count} Commit${p.count === 1 ? '' : 's'} aus ${esc(p.source)}${p.stat ? ' · ' + esc(p.stat.trim()) : ''} · ${cf}</div>
      ${warn.map(w => `<div class="small warnline">${w}</div>`).join('')}
      <div class="brcommits">${p.commits.map(c => `<label class="small${c.applied ? ' quiet' : ''}"><input type="checkbox" data-brc="${esc(c.sha)}" ${c.applied ? '' : 'checked'} ${BR.how === 'pick' ? '' : 'disabled'}>
        <code>${esc(c.short)}</code> ${esc(c.subject)} <span class="quiet">· ${esc(c.author)}, ${esc(c.when)}${c.applied ? ' · schon drin' : ''}</span></label>`).join('')}</div>
      <fieldset class="brhow"><legend class="small"><b>Wie?</b></legend>${BR_HOW.map(([k, l, d]) => `<label class="small${k === 'ff' && !p.can_ff ? ' quiet' : ''}"><input type="radio" name="brhow" value="${k}" ${BR.how === k ? 'checked' : ''} ${k === 'ff' && !p.can_ff ? 'disabled' : ''}>
        <b>${l}</b> <span class="quiet">${k === 'ff' && !p.can_ff ? `Geht nicht: ${esc(p.target)} hat Commits, die ${esc(p.source)} nicht kennt.` : d}</span></label>`).join('')}</fieldset>
      <label class="small"><input type="checkbox" id="brIde" checked> Bei Konflikt den Worktree in IntelliJ öffnen, statt abzubrechen</label>
      <div class="small quiet" style="margin-top:4px">Gearbeitet wird in einem eigenen Worktree in <code>${esc(p.repo)}</code>; dein Arbeitsordner wird nicht umgeschaltet. ${esc(p.target)} rückt nur vor, nie zurück. Gepusht wird nicht.</div>
      <div class="row" style="justify-content:flex-end;margin-top:8px"><button class="primary" id="brGo" ${p.diverged || p.dirty ? 'disabled' : ''}>In ${esc(p.target)} übernehmen</button></div>`;
  }
  $('brDlgBody').innerHTML = head + `<div style="margin-top:10px">${body}</div>`;
  if ($('brTarget')) $('brTarget').onchange = ev => { BR.target = ev.target.value; brLoad(); };
  document.querySelectorAll('input[name=brhow]').forEach(r => r.onchange = () => { BR.how = r.value; brDraw(); });
  if ($('brGo')) $('brGo').onclick = () => busy($('brGo'), 'Übernehme …', async () => {
    const commits = [...document.querySelectorAll('[data-brc]:checked')].map(x => x.dataset.brc);
    if (BR.how === 'pick' && !commits.length) { toast('Mindestens einen Commit anhaken.'); return; }
    try {
      BR.res = await post('/api/branch/run', { host: o.host, project_id: o.project_id, source: o.source, target: BR.target, how: BR.how, commits, ide: $('brIde').checked });
      brDraw(); if (BR.res.ok) load();
    } catch (e) { toast(e.message); }
  });
  if ($('brPush')) $('brPush').onclick = () => copyText(res.push, 'Push-Befehl kopiert');
  if ($('brFinish')) $('brFinish').onclick = () => busy($('brFinish'), 'Schliesse ab …', async () => {
    try { BR.res = await post('/api/branch/finish', { token: res.token }); brDraw(); load(); } catch (e) { toast(e.message); }
  });
  if ($('brAbort')) $('brAbort').onclick = () => busy($('brAbort'), 'Breche ab …', async () => {
    try { await post('/api/branch/abort', { token: res.token }); toast('Abgebrochen, nichts übernommen'); $('brDlg').close(); } catch (e) { toast(e.message); }
  });
}
document.addEventListener('click', ev => {
  const b = ev.target.closest && ev.target.closest('[data-brinto]');
  if (b) openBranchDlg(JSON.parse(b.dataset.brinto));
});
