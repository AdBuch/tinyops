// Helpdesk, Bereiche und Fokus-Sitzung mit Leiste und Vollbild.
// ---- Helpdesk-Queue, Fokusbereiche, Fokus-Sitzung (0.23)
const HDD = {};   // Ticket-Details je Schlüssel: undefined = noch nicht geladen
async function hdLoad(key) {
  HDD[key] = null;
  try { HDD[key] = await api('GET', '/api/helpdesk/ticket?key=' + encodeURIComponent(key)); } catch (e) { HDD[key] = { error: e.message }; }
  if (FXID && fEntry(FXID) && fEntry(FXID).t === 'hd' && fEntry(FXID).h.key === key) renderFx();
  const w = ((state.flow || {}).hd_watch || []).find(x => x.key === key); if (w && w.new) { w.new = false; renderFocus(); }
}
const FOC = () => state && state.focus;
const FOCUS_AUTO = { abgelaufen: 'Zeitbox vorbei, die Zeit läuft auf der Aufgabe weiter', pausiert: 'das Panel war länger nicht erreichbar', 'abgelöst': 'Zeit läuft auf einer anderen Aufgabe' };
const arCls = id => ['dev', 'hd', 'bb'].includes(id) ? 'ar-' + id : 'ar-x';
function hdRows(list) {
  return list.map(x => `<div class="q ${x.new ? 'new' : ''}" data-fopen="hdw:${esc(x.key)}" role="button" tabindex="0" title="Im Panel lesen"><i></i><span class="fkey">${esc(x.key)}</span><span class="tt" title="${esc(x.title)}">${esc(x.title)}</span>
    <small>${esc(x.status || '')}${x.assignee ? ' · ' + esc(x.assignee) : ''}</small><small class="${x.over_sla ? 'sla' : ''}" title="zuletzt geändert">${hAge(x.idle_h)}</small></div>`).join('');
}
function hdList(grp, title, list, total, newText, noneText, seenArg, seenTitle) {
  if (!list.length) return '';
  const nw = list.filter(x => x.new).length;
  const open = nw > 0 || LS.get('fopen.' + grp, false);
  return `<div class="fgroup"><details ${open ? 'open' : ''} data-fgrp="${grp}"><summary>${esc(title)} <span class="count">${list.length}${total > list.length ? '/' + total : ''}</span><small>${nw ? nw + ' ' + newText : noneText}</small></summary>
    <div class="flist"><div class="hdq">${hdRows(list)}${nw ? `<div class="hdqh"><span class="sp"></span><button data-hdseen="${seenArg}" title="${esc(seenTitle)}">Alle gesehen</button></div>` : ''}</div></div></details></div>`;
}
function hdQueue() {
  const f = state.flow || {}, info = f.hd_info || {};
  if (!info.name) return '';
  return hdList('hdq', 'Queue ' + info.name, f.hd_queue || [], info.queue_total || 0, 'neu seit deinem letzten Blick', 'nichts Neues', 'queue', 'Alle als gesehen markieren; neue Tickets erscheinen wieder fett')
    + hdList('hdw', 'Ich beobachte', f.hd_watch || [], info.watched_total || 0, 'mit Änderung seit deinem letzten Blick', 'nichts geändert', 'watch', 'Alle als gesehen markieren; fett wird wieder, was sich danach ändert')
    + (info.watch_error ? `<div class="small quiet" style="padding:0 4px 8px">Beobachtete Tickets nicht lesbar: ${esc(info.watch_error)}</div>` : '');
}
function blockBanner() { return ''; }   // seit 0.24 steht das in der Fokus-Leiste (renderFbar)
// Fokus-Leiste: in jeder Ansicht sichtbar. Ist (Sitzung oder laufende Zeit) und Soll (Block, angeheftete Aufgabe).
function fbarModel() {
  const f = FOC();
  if (!f) return null;
  const ses = f.session, blk = f.block;
  if (ses) {      // die Leiste gibt es nur, solange eine Fokus-Sitzung läuft
    if (FM_OPEN) return null;
    return { kind: 'ses', area: ses.area, tag: ses.area_name, title: ses.title, sub: [ses.key !== ses.title ? ses.key : '', ses.activity].filter(Boolean).join(' · '),
             soll: meetSoon() || (blk && blk.area !== ses.area ? `Soll: ${blk.name}-Block bis ${blk.until}` : ''), ses };
  }
  return null;
}
function meetSoon() {      // ein Termin in den nächsten 15 Minuten: in der Fokus-Leiste sagen
  const c = state && state.m365 && state.m365.calendar, nx = c && c.next;
  if (!nx) return '';
  const m = Math.round((nx.start - Date.now() / 1000) / 60);
  return m >= 0 && m <= 15 ? `Termin in ${m} min: ${short(nx.subject, 40)}` : '';
}
function fbAutoText(ses) {
  const rest = Math.max(0, Math.ceil((fmLeft(ses) + (ses.grace_secs || 600)) / 60));
  return rest > 0 ? `endet von selbst in ${rest} min` : 'wird beendet …';
}
function renderFbar() {
  const el = $('fbar'), m = fbarModel();
  document.body.classList.toggle('hasbar', !!m);
  el.hidden = !m;
  if (!m) return;
  const left = fmLeft(m.ses), over = left < 0;
  el.className = arCls(m.area) + (over ? ' over' : '');
  el.dataset.over = over ? '1' : '';
  const right = `<span class="clock ${over ? 'over' : ''}" id="fbClock" title="${over ? 'Zeitbox vorbei' : 'Rest der Zeitbox'}">${over ? 'vorbei' : mmss(left)}</span>
      ${over ? `<span class="soll" id="fbAuto">${fbAutoText(m.ses)}</span><button data-fbext="15" title="Zeitbox um 15 Minuten ab jetzt verlängern">+15 min</button><button class="go" data-fbopen="1">Abschliessen</button>`
        : '<button class="go" data-fbopen="1" title="Sitzung im Vollbild: Uhr, Gedanken parken, abschliessen">Vollbild</button>'}
      <i class="prog" id="fbProg" style="width:${Math.max(0, Math.min(100, 100 * (1 - left / (m.ses.planned_min * 60)))).toFixed(1)}%"></i>`;
  el.innerHTML = `<span class="tag">${esc(m.tag)}</span><div class="now"><b title="${esc(m.title)}">${esc(m.title)}</b>${m.sub ? `<span>${esc(m.sub)}</span>` : ''}</div>
    ${m.soll ? `<span class="soll" title="Der feste Block gehört zu einem anderen Bereich als diese Sitzung">${esc(m.soll)}</span>` : ''}${m.warn ? '<span class="soll">anderer Bereich</span>' : ''}${right}`;
}
function focusRail() {
  const f = FOC();
  if (!f) return '';
  const w = f.week, H = s => s < 3600 ? Math.round(s / 60) + ' min' : (s / 3600).toFixed(1).replace('.0', '') + ' h';
  const shown = w.areas.filter(a => a.target_pct || a.secs);
  const tot = Math.max(1, w.total_secs);
  const rows = shown.map(a => {
    const max = Math.max(a.target_secs, a.secs, 1);
    const tgt = a.target_pct ? ` von ${H(a.target_secs)} (${a.target_pct} %)` : '';
    const lag = a.target_pct && a.behind_secs >= 1800 ? `<span class="lag">${H(a.behind_secs)} hinter Plan</span>` : a.target_pct && a.secs ? `<span class="lead">im Plan${a.ahead_secs >= 1800 ? ', ' + H(a.ahead_secs) + ' voraus' : ''}</span>` : '';
    return `<div class="farea ${arCls(a.id)}" ${f.session ? '' : `data-fsess="area:${esc(a.id)}" role="button" tabindex="0" title="Sitzung für ${esc(a.name)} starten"`}><div class="l1"><b>${esc(a.name)}</b><span>${H(a.secs)}${tgt}</span></div>
      ${a.target_pct ? `<div class="fabar" title="Soll bis jetzt: ${H(a.due_secs)}"><i style="width:${(100 * a.secs / max).toFixed(1)}%"></i><em style="left:${(100 * a.due_secs / max).toFixed(1)}%"></em></div>` : ''}
      ${lag}${a.target_pct ? `<button class="quiet-btn" data-fsess="area:${esc(a.id)}" style="justify-self:start">${ic('play')} ${esc(a.name)}-Block starten</button>` : ''}</div>`;
  }).join('');
  const share = shown.length ? `<div class="fshare" title="Verteilung dieser Woche">${w.areas.filter(a => a.secs).map(a => `<i class="${arCls(a.id)}" style="flex:${a.secs}" title="${esc(a.name)}: ${a.share_pct} %"></i>`).join('')}</div>` : '';
  const nb = f.next_block ? `<div class="small quiet">Nächster Block: ${esc(f.next_block.name)}, ${esc(f.next_block.label)}</div>` : '';
  const td = f.today.sessions ? `<div class="small quiet">Heute ${f.today.sessions} Fokus-Sitzung${f.today.sessions === 1 ? '' : 'en'}, ${f.today.minutes} min</div>` : '';
  return `<section class="rcard"><h3>Fokuszeit diese Woche <small>${H(w.total_secs)} erfasst</small></h3>${share}${rows || '<div class="small quiet">Noch nichts erfasst. Zeit läuft, sobald du eine Aufgabe als Fokus anheftest oder eine Sitzung startest.</div>'}${nb}${td}
    ${f.session ? '' : '<button data-fsess="">Fokus-Sitzung starten</button>'}</section>`;
}
// Sitzungs-Dialog: was, welche Tätigkeit, wie lange
let FS = { what: '', act: '', min: 50 };
function openFocusDlg(what) {
  const f = FOC();
  if (!f) { toast('Fokus-Sitzungen brauchen die Zeiterfassung (Einstellungen → Zeiterfassung).'); return; }
  if (f.session) { openFmode(); return; }
  const g = state.flow ? focusGroups() : { hero: null };
  const opts = [];
  if (g.hero && g.hero.t !== 'review') opts.push({ v: g.hero.id, l: `${eKey(g.hero)} ${eTitle(g.hero)}`, s: g.pinned ? 'angeheftet' : 'jetzt dran' });
  if (what && !what.startsWith('area:') && !opts.some(o => o.v === what)) { const e = fEntry(what); if (e) opts.unshift({ v: e.id, l: `${eKey(e)} ${eTitle(e)}`, s: 'diese Aufgabe' }); }
  f.areas.filter(a => a.id !== 'dev').forEach(a => opts.push({ v: 'area:' + a.id, l: a.name, s: a.ticket ? 'bucht auf ' + a.ticket : 'Bereich', area: a.id }));
  FS = { what: what || (opts[0] || {}).v || '', act: '', min: LS.get('fsMin', 50) };
  renderFocusDlg(opts);
  $('fsDlg').showModal();
}
function renderFocusDlg(opts) {
  const f = FOC();
  const area = FS.what.startsWith('area:') ? f.areas.find(a => 'area:' + a.id === FS.what) : null;
  const acts = area ? area.activities : [];
  $('fsBody').innerHTML = `<div class="${area ? arCls(area.id) : ''}" style="display:grid;gap:14px">
    <div><strong>Fokus-Sitzung</strong><div class="quiet small">Eine Sache, eine Zeitbox. Was dazwischenkommt, parkst du mit einem Satz und machst weiter.</div></div>
    <div class="what" role="radiogroup" aria-label="Woran">${opts.map(o => `<label class="${o.area ? arCls(o.area) : ''}"><input type="radio" name="fsw" value="${esc(o.v)}" ${o.v === FS.what ? 'checked' : ''}><span>${esc(short(o.l, 64))}</span><small>${esc(o.s)}</small></label>`).join('')}</div>
    ${acts.length ? `<div><div class="small quiet" style="margin-bottom:6px">Tätigkeit (landet im Text der Zeitbuchung)</div><div class="chips">${acts.map(a => `<button data-fsact="${esc(a)}" class="${FS.act === a ? 'on' : ''}">${esc(a)}</button>`).join('')}</div></div>` : ''}
    <div><div class="small quiet" style="margin-bottom:6px">Dauer</div><div class="chips">${[25, 50, 90].map(m => `<button data-fsmin="${m}" class="${FS.min === m ? 'on' : ''}">${m} min</button>`).join('')}</div></div>
    ${state.m365 && state.m365.logged_in && state.m365.calendar_write ? `<label class="check"><input type="checkbox" id="fsCal" ${LS.get('fsCal', false) ? 'checked' : ''}><span>Im Kalender als beschäftigt eintragen <span class="quiet small">(Termin «Fokus: …» für die Dauer der Zeitbox)</span></span></label>` : ''}
    <div class="row"><button class="primary" id="fsGo">Starten</button><button id="fsNo">Abbrechen</button></div></div>`;
  $('fsBody')._opts = opts;
}
$('fsDlg').addEventListener('click', async ev => {
  const t = ev.target, opts = $('fsBody')._opts;
  const a = t.closest('[data-fsact]'); if (a) { FS.act = FS.act === a.dataset.fsact ? '' : a.dataset.fsact; renderFocusDlg(opts); return; }
  const m = t.closest('[data-fsmin]'); if (m) { FS.min = +m.dataset.fsmin; LS.set('fsMin', FS.min); renderFocusDlg(opts); return; }
  if (t.id === 'fsNo') { $('fsDlg').close(); return; }
  if (t.id === 'fsGo') {
    const body = { minutes: FS.min, activity: FS.act, calendar: !!($('fsCal') && $('fsCal').checked) };
    if ($('fsCal')) LS.set('fsCal', $('fsCal').checked);
    if (FS.what.startsWith('area:')) body.area = FS.what.slice(5); else body.key = FS.what;
    try {
      const r = await post('/api/focus/start', body); state.focus = r; $('fsDlg').close();
      if (r.calendar) toast(r.calendar.ok ? 'Im Kalender eingetragen' : 'Kalender: ' + r.calendar.error);
      await load(); openFmode();
    } catch (e) { toast(e.message); }
  }
});
$('fsDlg').addEventListener('change', ev => { if (ev.target.name === 'fsw') { FS.what = ev.target.value; FS.act = ''; renderFocusDlg($('fsBody')._opts); } });
// Fokus-Modus: Vollbild mit Uhr, Tätigkeit, Gedanken parken, Abschluss
let FM_OPEN = false;
function openFmode() { FM_OPEN = true; LS.set('fmMin', false); renderFmode(); const i = $('fmPark'); i && i.focus(); }
function closeFmode() { FM_OPEN = false; LS.set('fmMin', true); renderFmode(); }
const mmss = s => { const a = Math.abs(Math.round(s)), m = Math.floor(a / 60); return `${s < 0 ? '+' : ''}${m}:${String(a % 60).padStart(2, '0')}`; };
function fmLeft(ses) { return ses.start + ses.planned_min * 60 - Date.now() / 1000; }
function renderFmode() {
  const f = FOC(), ses = f && f.session, el = $('fmode');
  renderFbar();
  if (!ses) { el.hidden = true; document.body.style.overflow = ''; return; }
  const left = fmLeft(ses), area = f.areas.find(a => a.id === ses.area) || { activities: [] };
  el.hidden = !FM_OPEN; document.body.style.overflow = FM_OPEN ? 'hidden' : '';
  if (!FM_OPEN) return;
  const keep = $('fmPark') ? $('fmPark').value : '', had = document.activeElement && document.activeElement.id === 'fmPark';
  const pct = Math.max(0, Math.min(100, 100 * (1 - left / (ses.planned_min * 60))));
  el.className = arCls(ses.area);
  el.innerHTML = `<div class="top"><span class="tag">${esc(ses.area_name)}</span><span>${esc(ses.planned_min)} min geplant${ses.parked ? ` · ${ses.parked} Gedanke${ses.parked === 1 ? '' : 'n'} geparkt` : ''}</span><span class="sp"></span><button class="quiet-btn" data-fmmin="1" title="Klein machen; die Sitzung läuft weiter (Esc)">${ic('x')} Klein machen</button></div>
    <div class="mid"><div class="clock ${left < 0 ? 'over' : ''}" id="fmClock" aria-live="off">${mmss(left)}</div>
      <div class="line"><i id="fmLine" style="width:${pct.toFixed(1)}%"></i></div>
      <div class="what">${esc(ses.title)}<small>${esc(ses.key !== ses.title ? ses.key : '')}${ses.activity ? (ses.key !== ses.title ? ' · ' : '') + esc(ses.activity) : ''}</small></div>
      ${area.activities.length ? `<div class="acts" aria-label="Tätigkeit wechseln">${area.activities.map(a => `<button data-fmact="${esc(a)}" class="${ses.activity === a ? 'on' : ''}">${esc(a)}</button>`).join('')}</div>` : ''}
      <div class="park"><input id="fmPark" maxlength="500" autocomplete="off" placeholder="Was dir gerade durch den Kopf geht: parken und weitermachen (Enter)" aria-label="Gedanken parken"><button data-fmpark="1">Parken</button></div>
      <div class="fmhint" id="fmHint">${left < 0 ? 'Zeitbox vorbei. Abschliessen oder bewusst weitermachen.' : 'Nur diese eine Sache. Mail, Teams und das Board warten.'}</div></div>
    <div class="bot"><button class="primary big" data-fmend="erledigt">${ic('check')} Erledigt</button><button class="big" data-fmend="weiter" title="Die Zeitbox endet, die Zeit läuft auf der Aufgabe weiter">Beenden, Zeit läuft weiter</button><button class="big quiet-btn" data-fmend="abgelenkt" title="Ehrlich notieren: hilft beim Planen der nächsten Blöcke">Abgelenkt worden</button><button class="big quiet-btn" data-fmend="abgebrochen">Abbrechen</button><button class="big quiet-btn" data-fmext="15" title="Zeitbox um 15 Minuten verlängern (ab jetzt, wenn sie schon vorbei ist)">+15 min</button></div>`;
  if (keep) $('fmPark').value = keep;
  if (had) $('fmPark').focus();
}
document.addEventListener('keydown', ev => {   // im Fokus-Modus keine Tastenkürzel des Panels
  if ($('fmode').hidden || $('fmode').contains(ev.target)) return;
  if (ev.key === 'Escape') { ev.preventDefault(); closeFmode(); }
  ev.stopPropagation();
}, true);
setInterval(() => {
  const f = FOC(), ses = f && f.session;
  if (!ses) return;
  const left = fmLeft(ses), t = mmss(left);
  if (!FM_OPEN && $('fbar').dataset.over !== (left < 0 ? '1' : '') && !$('fbar').hidden) renderFbar();      // Wechsel zu «vorbei»: Leiste neu zeichnen
  if (left < 0 && $('fbAuto')) $('fbAuto').textContent = fbAutoText(ses);
  if (left < -(ses.grace_secs || 600) - 5 && !FB_RELOAD) { FB_RELOAD = true; load().finally(() => { FB_RELOAD = false; }); }
  if (!FM_OPEN && $('fbClock')) { $('fbClock').textContent = left < 0 ? 'vorbei' : t; $('fbClock').classList.toggle('over', left < 0); if ($('fbProg')) $('fbProg').style.width = Math.max(0, Math.min(100, 100 * (1 - left / (ses.planned_min * 60)))).toFixed(1) + '%'; }
  const c = $('fmClock'); if (c) { c.textContent = t; c.classList.toggle('over', left < 0); }
  const l = $('fmLine'); if (l) l.style.width = Math.max(0, Math.min(100, 100 * (1 - left / (ses.planned_min * 60)))).toFixed(1) + '%';
  if (left < 0 && left > -1.2 && $('fmHint')) $('fmHint').textContent = 'Zeitbox vorbei. Abschliessen oder verlängern, sonst endet die Sitzung in zehn Minuten von selbst.';
  document.title = FM_OPEN ? `${t} · ${ses.area_name}` : 'tinyops';
}, 1000);
async function fmPark() {
  const i = $('fmPark'), v = i.value.trim();
  if (!v) return;
  try { const r = await post('/api/focus/park', { text: v }); i.value = ''; toast(r.to === 'ideen' ? 'Geparkt in der Ideenbox' : 'Geparkt in der Sitzungsnotiz'); state.focus.session.parked = r.parked; renderFmode(); $('fmPark').focus(); } catch (e) { toast(e.message); }
}
let FB_RELOAD = false;
$('fbar').addEventListener('click', async ev => {
  const x = ev.target.closest('[data-fbext]');
  if (x) { try { state.focus = await post('/api/focus/extend', { minutes: +x.dataset.fbext }); renderFmode(); toast('Zeitbox verlängert'); } catch (e) { toast(e.message); } return; }
  if (ev.target.closest('[data-fbopen]') || !ev.target.closest('button')) { if (FOC() && FOC().session) openFmode(); }
});
$('fmode').addEventListener('click', async ev => {
  const t = ev.target;
  if (t.closest('[data-fmmin]')) { closeFmode(); return; }
  if (t.closest('[data-fmpark]')) { fmPark(); return; }
  const fx = t.closest('[data-fmext]');
  if (fx) { try { state.focus = await post('/api/focus/extend', { minutes: +fx.dataset.fmext }); renderFmode(); toast('Zeitbox verlängert'); } catch (e) { toast(e.message); } return; }
  const a = t.closest('[data-fmact]');
  if (a) { try { state.focus = await post('/api/focus/activity', { activity: a.dataset.fmact }); renderFmode(); } catch (e) { toast(e.message); } return; }
  const en = t.closest('[data-fmend]');
  if (en) {
    try {
      const r = await post('/api/focus/end', { result: en.dataset.fmend });
      FM_OPEN = false; state.focus = r; renderFmode(); document.title = 'tinyops';
      toast(`Sitzung beendet: ${r.ended.minutes} min${r.ended.xp && F().score !== false ? ` · +${r.ended.xp} XP` : ''}${r.ended.parked ? ` · ${r.ended.parked} geparkt` : ''}`);
      await load();
    } catch (e) { toast(e.message); }
  }
});
$('fmode').addEventListener('keydown', ev => {
  if (ev.key === 'Enter' && ev.target.id === 'fmPark') { ev.preventDefault(); fmPark(); }
  else if (ev.key === 'Escape') { ev.preventDefault(); closeFmode(); }
  ev.stopPropagation();
});
document.addEventListener('click', async ev => {
  const t = ev.target;
  const fs = t.closest('[data-fsess]'); if (fs) { ev.stopPropagation(); openFocusDlg(fs.dataset.fsess); return; }
  const hr = t.closest('[data-hdreload]'); if (hr) { delete HDD[hr.dataset.hdreload]; renderFx(); return; }
  const hs = t.closest('[data-hdseen]');
  if (hs) { ev.stopPropagation(); await act(() => post('/api/helpdesk/seen', { all: hs.dataset.hdseen === 'watch' ? 'watch' : true }), 'Als gesehen markiert'); }
});
