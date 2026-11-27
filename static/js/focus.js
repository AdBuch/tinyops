// Fokus: Einträge, nächster Schritt, Arbeitsfläche oben, Seitenleiste.
// Knopf je nächstem Schritt: Text und Symbol sagen, was beim Klick passiert
const ACT = {
  start: ['Loslegen', 'play'], branch: ['Befehl kopieren', 'copy'], mr_create: ['MR erstellen', 'mr'], ready: ['MR öffnen', 'ext'],
  rebase: ['MR öffnen', 'ext'], pipeline: ['Pipeline öffnen', 'ext'], sonar: ['Report kopieren', 'copy'], ci: ['Pipeline', 'ext'],
  threads: ['Offene Punkte', 'chat'], agent_question: ['Antworten', 'chat'], review: ['MR öffnen', 'ext'], test: ['Getestet', 'check'], merge: ['MR öffnen', 'merge'],
  close: ['Fertig', 'check'], check: ['Erledigt', 'check'], agent: ['Log ansehen', 'eye'], agent_failed: ['Lauf ansehen', 'eye'],
  agent_result: ['Prüfen', 'eye'], agent_start: ['Starten', 'play'], plan: ['Einplanen', 'list'], agent_back: ['Zurück ans Entwickeln', 'chat'], agent_next: ['Weiter', 'play'],
  retest: ['Getestet', 'check'], check_approval: ['MR öffnen', 'ext'], hd_work: ['Ticket ansehen', 'chevron2'],
  do_review: ['Review öffnen', 'ext'], assigned: ['MR öffnen', 'ext'], reviewer: ['Reviewer setzen', 'users'], ticket: ['tiny-Ticket anlegen', 'ticket'],
};
const OWNER = { me: '', ci: 'gear', others: 'users', agent: 'bot', none: '' };
const OWNER_T = { me: 'Du bist dran', ci: 'Wartet auf die CI', others: 'Wartet auf andere', agent: 'Ein Agent arbeitet', none: '' };
const MSTAT = { conflict: ['Konflikt', 'sq-bad'], need_rebase: ['Rebase nötig', 'sq-bad'], not_approved: ['Freigabe fehlt', 'warn'], discussions_not_resolved: ['Diskussionen offen', 'warn'],
  mergeable: ['mergebar', 'sq-ok'], ci_still_running: ['CI läuft', ''], draft_status: ['Draft', 'draft'] };
let fSkip = new Set(), fSel = -1, FXID = null;
try { fSkip = new Set(JSON.parse(sessionStorage.getItem('tinyops.skip') || '[]')); } catch (e) { /* egal */ }
function focusEntries() {
  const f = state && state.flow;
  if (!f || !state.board) return [];
  const cards = state.board.cards.filter(c => f.items[c.id]).map(c => ({ t: 'card', id: c.id, c, d: f.items[c.id], prio: f.items[c.id].prio }));
  const revs = (f.reviews || []).map(r => ({ t: 'review', id: 'rv:' + r.id, r, prio: 150 + Math.min(r.age_days || 0, 10) * 5,
    d: { next: r.next, phase: 4, phase_id: 'check', flags: [], checks: { done: 0, total: 0 }, checklist: [] } }));
  const hds = (f.helpdesk || []).map(h => ({ t: 'hd', id: h.id, h, prio: h.prio,
    d: { next: h.next, phase: null, hd: true, flags: h.over_sla ? ['SLA'] : [], checks: { done: 0, total: 0 }, checklist: [] } }));
  const wts = (f.hd_watch || []).concat(f.hd_queue || []).filter(h => !hds.some(x => x.h.key === h.key)).map(h => ({ t: 'hd', id: 'hdw:' + h.key, h, prio: 0, side: true,
    d: { next: { kind: 'wait', id: 'hd_watch', label: 'Nur lesen', why: h.assignee ? 'Bearbeitet von ' + h.assignee : 'Noch niemandem zugewiesen', owner: 'other', action: { url: h.url } },
         phase: null, hd: true, flags: [], checks: { done: 0, total: 0 }, checklist: [] } }));
  return cards.concat(revs, hds, wts);
}
const hdName = () => ((state.flow && state.flow.hd_info) || {}).name || 'Helpdesk';
const hAge = h => h == null ? '' : h < 1 ? Math.max(1, Math.round(h * 60)) + ' min' : h < 48 ? Math.round(h) + ' h' : Math.round(h / 24) + ' d';
const mrNo = x => (x.host === 'github' ? '#' : '!') + x.iid;
function eKey(e) { return e.t === 'hd' ? e.h.key : e.t === 'review' ? mrNo(e.r) : (e.c.key || (e.c.idea_id ? 'Idee' : 'ohne Ticket')); }
function eTitle(e) { return e.t === 'hd' ? e.h.title : e.t === 'review' ? e.r.title : (e.c.title || '(ohne Titel)'); }
function eUrl(e) { return e.t === 'hd' ? e.h.url : e.t === 'review' ? e.r.url : (e.c.url || ''); }
function srcTags(e) {
  const t = [];
  if (e.t === 'hd') t.push(['hd', hdName()]);
  else if (e.t === 'review') t.push(e.r.host === 'github' ? ['gh', 'GitHub'] : ['gl', 'GitLab']);
  else {
    const c = e.c;
    if (c.key && !c.local) t.push(['jira', 'Jira']);
    if (c.local || c.idea_id) t.push(['tiny', 'tiny']);
    if (c.items.some(x => x.host !== 'github')) t.push(['gl', 'GitLab']);
    if (c.items.some(x => x.host === 'github')) t.push(['gh', 'GitHub']);
  }
  return t.map(([k, l]) => `<span class="st st-${k}" title="Quelle: ${l === 'tiny' ? 'eigenes Board' : esc(l)}">${esc(l)}</span>`).join('');
}
function trackHtml(d, big, pick) {
  if (d.hd) return '';
  const ph = state.flow.phases, ps = state.flow.phase_stage || {};
  return `<ol class="trk ${big ? 'big' : ''} ${pick ? 'pick' : ''} k-${esc(d.next.kind)}" aria-label="Station ${d.phase + 1} von ${ph.length}: ${esc(ph[d.phase].label)}">` + ph.map((p, i) => {
    const s = i < d.phase ? 'past' : i === d.phase ? 'now' : 'todo';
    const st = pick && ps[i] ? ` data-st="${esc(ps[i])}" title="Auf «${esc(p.label)}» setzen"` : ` title="${esc(p.label)}${pick && !ps[i] ? ': ergibt sich aus GitLab' : ''}"`;
    return `<li class="${s}"${st}><i></i>${big ? `<span>${esc(p.label)}</span>` : ''}</li>`;
  }).join('') + '</ol>';
}
function metaOf(e) {
  if (e.t === 'hd') { const h = e.h; return `<span class="hdst">${esc(h.status)}</span>${h.priority ? `<span>${esc(h.priority)}</span>` : ''}${h.reporter ? `<span>von ${esc(h.reporter)}</span>` : ''}${h.age_h != null ? `<span class="${h.over_sla ? 'fflag' : ''}" title="${h.over_sla ? 'Über dem SLA' : 'Offen seit'}">seit ${hAge(h.age_h)}</span>` : ''}${h.outdated ? '<span class="fflag">veraltet</span>' : ''}`; }
  if (e.t === 'review') return `<span class="fm">${ic('mr')}${esc(e.r.project)}</span><span>von ${esc(e.r.author || '?')}</span><span>seit ${e.r.age_days} d</span>`;
  const c = e.c, d = e.d, p = [];
  const mrs = c.items.filter(x => x.iid), br = c.items.filter(x => !x.iid);
  if (mrs.length) p.push(`<span class="fm" title="Merge Requests">${ic('mr')}${mrs.map(x => esc(mrNo(x))).join(' ')}</span>`);
  if (br.length) p.push(`<span class="fm" title="${esc(br.map(x => x.branch).join(', '))}">${branchIcon(br[0].branch, 15)}${esc(br.length === 1 ? short(br[0].branch, 36) : br.length + ' Branches')}</span>`);
  const proj = [...new Set(c.items.map(x => x.project))];
  if (proj.length) p.push(`<span class="fm">${repoIcon(proj[0], 15)}${esc(short(proj.join(', '), 40))}</span>`);
  if (d.checks.total) p.push(`<span class="fm" title="Teilschritte">${ic('check')}${d.checks.done}/${d.checks.total}</span>`);
  (d.flags || []).forEach(f => p.push(`<span class="fflag">${esc(f)}</span>`));
  return p.join('');
}
function goBtn(e, cls) {
  const n = e.d.next;
  if (n.kind === 'done') return '';
  let [l, i] = ACT[n.id] || ['Öffnen', 'ext'];
  const items = e.t === 'review' ? [e.r] : e.t === 'hd' ? [] : e.c.items;
  if (items.length && items.every(x => x.host === 'github')) l = l.replace('MR', 'PR');
  return `<button class="${cls || 'fgo'} ${n.kind === 'wait' && !cls ? 'ghost' : ''}" data-fgo="${esc(e.id)}" title="${esc(l)}">${ic(i)}<span>${esc(l)}</span></button>`;
}
function testBtns(e, cls) {   // Testen: Review-App und IntelliJ auf dem Head-Commit (0.20)
  const a = (e.d.next || {}).action || {};
  const out = [];
  if (a.ide) out.push(`<button class="${cls || ''}" data-ide="${esc(JSON.stringify(a.ide))}" title="Worktree genau auf dem Commit des MR anlegen und in IntelliJ öffnen">${ic('ide')}<span>In IntelliJ öffnen</span></button>`);
  if (a.ide) out.push(`<button class="${cls || ''}" data-mrtry="${esc(JSON.stringify(a.ide))}" title="Prompts, git-Befehle und Review-Umgebung für diesen MR">${ic('flask')}<span>Ausprobieren</span></button>`);
  if (a.review_app) out.push(`<a class="btn ${cls || ''}" href="${esc(a.review_app)}" target="_blank" rel="noopener" title="Review-App aus GitLab">${ic('globe')}<span>Review-App</span></a>`);
  return out.join('');
}
function doneBtn(e, big) {
  const to = e.t === 'card' && e.d.complete_to;
  if (!to) return '';
  const ph = state.flow.phases, cur = ph[e.d.phase].label;
  return `<button class="${big ? 'big' : 'fdone'}" data-fdone="${esc(e.id)}" title="Station «${esc(cur)}» abschliessen, weiter zu «${esc(STAGE_LABEL[to] || to)}»" aria-label="Schritt erledigt">${ic('check')}${big ? '<span>Schritt erledigt</span>' : ''}</button>`;
}
function fRow(e) {
  const n = e.d.next;
  return `<div class="frow k-${esc(n.kind)} ${e.t === 'hd' ? 'hdrow' : ''}" data-fid="${esc(e.id)}">
    ${e.t === 'hd' ? `<span class="hdprio p${Math.min(5, e.h.prio_rank)}" title="Priorität ${esc(e.h.priority || 'ohne')}"></span>` : trackHtml(e.d)}
    <div class="fmain"><div class="fl1"><span class="fkey">${esc(eKey(e))}</span><span class="ftitle" title="${esc(eTitle(e))}">${esc(eTitle(e))}</span></div><div class="fl2">${srcTags(e)}${metaOf(e)}</div></div>
    <div class="fnext" title="${esc(OWNER_T[n.owner] || '')}"><span class="fown">${OWNER[n.owner] ? ic(OWNER[n.owner]) : ''}</span><div><b>${esc(n.label)}</b><small title="${esc(n.why)}">${esc(n.why)}</small></div></div>
    <div class="fbtns">${doneBtn(e)}${e.t === 'review' ? rvBtn(e) : ''}${goBtn(e)}</div></div>`;
}
// 0.36: Die Fokus-Aufgabe als Arbeitsfläche: worum es geht, wann es fertig ist, Teilschritte und Agenten direkt da
// (Wunsch: «das Fokus-Ticket ist wie ein Titel, nicht etwas, um daran zu arbeiten»)
function hdJiraBtn(key) {        // 0.36: aus einem Helpdesk-Ticket ein Jira-Ticket machen (nur mit Bestätigung, das Helpdesk-Ticket bleibt, wie es ist)
  const j = ((state.flow || {}).hd_jira || {})[key];
  return j ? `<div class="small">Jira-Ticket angelegt: <b>${esc(j)}</b> <button class="quiet-btn" data-hd2jira="${esc(key)}" title="Noch ein Ticket daraus anlegen">Weiteres …</button></div>`
    : `<button data-hd2jira="${esc(key)}">${ic('plus')} Jira-Ticket daraus anlegen</button><div class="small quiet" style="margin-top:4px">Entwurf mit Link, Problem und Kriterien. Du prüfst und bestätigst; das Helpdesk-Ticket bleibt unverändert.</div>`;
}
const HBRIEF = {};
function heroWork(e) {
  let main = '', side = '';
  if (e.t === 'card' && !e.c.idea_id) {
    const k = e.c.key || e.c.id, b = HBRIEF[k];
    if (b === undefined) {
      HBRIEF[k] = null;
      api('GET', `/api/focus/brief?key=${encodeURIComponent(k)}&title=${encodeURIComponent(e.c.title || '')}`)
        .then(x => { HBRIEF[k] = x; if (view === 'focus') renderFocus(); })
        .catch(err => { HBRIEF[k] = { error: err.message, goal: '', criteria: [] }; if (view === 'focus') renderFocus(); });
    }
    main = `<h4>Worum es geht</h4>${!b ? '<div class="quiet small">Lade das Ticket …</div>' : b.goal ? `<p class="hgoal">${esc(b.goal)}</p>`
      : `<div class="quiet small">${esc(b.error || 'Das Ticket sagt nicht, worum es geht.')} Schreib das Ziel als ersten Teilschritt auf, dann weisst du es morgen noch.</div>`}
      ${b && b.criteria.length ? `<h4>Fertig, wenn</h4><ul class="hcrit">${b.criteria.slice(0, 8).map(c => `<li>${esc(c)}</li>`).join('')}</ul>` : b ? '<h4>Fertig, wenn</h4><div class="quiet small">Keine Akzeptanzkriterien im Ticket. Zwei, drei Teilschritte rechts machen «fertig» greifbar.</div>' : ''}`;
    const ck = e.d.checklist || [], dn = ck.filter(x => x.done).length;
    side = `<h4>Teilschritte ${ck.length ? `<small>${dn} von ${ck.length}</small>` : ''}</h4>
      ${ck.length ? `<ul class="ck">${ck.map(x => `<li class="${x.done ? 'done' : ''}"><input type="checkbox" data-fck="${x.id}" ${x.done ? 'checked' : ''} aria-label="${esc(x.text)}"><span>${esc(x.text)}</span><button data-fckdel="${x.id}" title="Entfernen" aria-label="Entfernen">${ic('x')}</button></li>`).join('')}</ul>` : ''}
      <div class="ckadd"><input id="hCkNew" data-hck="${esc(e.c.id)}" maxlength="200" placeholder="${ck.length ? 'Nächster kleiner Schritt …' : 'Erster kleiner Schritt, z. B. «Fehler nachstellen»'}" autocomplete="off"><button data-hckadd="${esc(e.c.id)}">Hinzufügen</button></div>
      ${state.agents && state.agents.enabled ? `<h4>Agenten</h4>${agentRow(e.c.id, e.c.key || '', e.c.title, e.c.url, e.c.items)}` : ''}`;
  } else if (e.t === 'hd') {
    const d = HDD[e.h.key];
    if (d === undefined) hdLoad(e.h.key);
    const txt = d && d.description ? " ".concat(d.description).trim() : '';
    main = `<h4>Worum es geht</h4>${!d ? '<div class="quiet small">Lade das Ticket …</div>' : d.error ? `<div class="quiet small">${esc(d.error)}</div>`
      : txt ? `<p class="hgoal">${esc(txt.length > 420 ? txt.slice(0, 420) + ' …' : txt)}</p>` : '<div class="quiet small">Keine Beschreibung.</div>'}`;
    side = `<h4>Entwicklung nötig?</h4>${hdJiraBtn(e.h.key)}`;
  } else if (e.t === 'review') {
    main = `<h4>Stand</h4><p class="hgoal">${esc(e.r.status || '')}</p>`;
  }
  if (!main && !side) return '';
  return `<div class="hwork"><div class="hmain">${main}</div>${side ? `<div class="hside">${side}</div>` : ''}</div>`;
}
function heroHtml(e, g) {
  if (!e) return `<section class="hero calm"><div class="hcalm"><b>Nichts wartet gerade auf dich.</b><span>Was offen ist, liegt bei der CI, bei anderen oder bei einem Agenten. Gute Zeit für eine Idee aus dem Pool oder eine Pause.</span></div>${blockBanner()}</section>`;
  const n = e.d.next, url = eUrl(e);
  const pin = g && g.pinned;
  const lead = pin ? `Dein Fokus${n.kind === 'blocked' ? ' · blockiert' : n.kind === 'wait' ? ' · wartet' : ''}` : n.kind === 'blocked' ? `${ic('alert')} Blockiert: zuerst das` : e.t === 'review' ? `${ic('users')} Jemand wartet auf dich` : 'Jetzt dran';
  const bl = pin && g.blockers.length ? `<button class="quiet-btn fblk" data-fopen="${esc(g.blockers[0].id)}" title="${esc(g.blockers.map(b => eKey(b) + ': ' + b.d.next.label).join('\n'))}">${ic('alert')} ${g.blockers.length} Blocker anderswo</button>` : '';
  return `<section class="hero k-${esc(n.kind)}" data-fid="${esc(e.id)}">
    <div class="hhead">${srcTags(e)}<span class="fkey">${esc(eKey(e))}</span>${url ? `<a class="htitle" href="${esc(url)}" target="_blank" rel="noopener">${esc(eTitle(e))}</a>` : `<span class="htitle">${esc(eTitle(e))}</span>`}</div>
    ${e.t === 'card' && (e.c.items || []).length ? `<div class="hpics">${picLine(e.c, 26)}</div>` : e.t === 'review' ? `<div class="hpics"><span class="picn">${repoIcon(e.r.project, 26)}<span>${esc(e.r.project)}</span></span>${e.r.branch ? `<span class="picn">${branchIcon(e.r.branch, 26)}<code>${esc(short(e.r.branch, 44))}</code></span>` : ''}</div>` : ''}
    ${trackHtml(e.d, true)}
    ${pin ? timeChip(e) : ''}
    <div class="hnext"><div class="hstep"><span class="hlabel">${lead}</span><h2>${esc(n.label)}</h2><p>${esc(n.why)}</p></div>
      <div class="hbtns">${goBtn(e, 'primary big')}${rvBtn(e, 'big')}${testBtns(e, 'big')}${doneBtn(e, true)}${state.focus && e.t !== 'review' ? `<button class="big" data-fsess="${esc(e.id)}" title="Fokus-Sitzung mit Zeitbox: Ablenkungen parken, Zeit läuft auf diese Aufgabe">${ic('clock')} Fokus</button>` : ''}<button class="big" data-fopen="${esc(e.id)}">Details</button>
        ${pin ? `<button class="quiet-btn big" data-fpin="" title="Fokus lösen: wieder automatisch das Wichtigste zeigen">${ic('x')} Fokus lösen</button>` : `<button class="quiet-btn big" data-fskip="${esc(e.id)}" title="Nicht jetzt: die nächste Aufgabe zeigen (gilt bis du den Tab schliesst)">${ic('skip')} Nicht jetzt</button>`}</div></div>${bl}
    ${heroWork(e)}
  </section>`;
}
function focusGroups() {
  const all = focusEntries().filter(e => !e.side);   // beobachtete und Queue-Tickets haben eigene Listen
  const act = all.filter(e => ['do', 'blocked'].includes(e.d.next.kind)).sort((a, z) => z.prio - a.prio);
  const cand = act.filter(e => !(e.t === 'card' && (e.c.idea_id || (e.d.phase === 0 && !e.c.jira_in_progress))));
  const pinned = state.flow.pinned && all.find(e => e.id === state.flow.pinned);
  const hero = pinned || cand.find(e => !fSkip.has(e.id)) || (cand.length && fSkip.size ? (fSkip.clear(), cand[0]) : null);
  const rest = x => !hero || x.id !== hero.id;
  return {
    hero, all,
    mine: cand.filter(e => e.t === 'card' && rest(e)),
    hd: cand.filter(e => e.t === 'hd' && rest(e)),
    reviews: cand.filter(e => e.t === 'review' && rest(e)),
    wait: all.filter(e => e.d.next.kind === 'wait' && rest(e)), pinned: !!pinned,
    blockers: pinned ? act.filter(e => e.d.next.kind === 'blocked' && rest(e)) : [],
    plan: act.filter(e => !cand.includes(e)),
    done: all.filter(e => e.d.next.kind === 'done').length,
  };
}
function fGroup(title, hint, list, empty, collapsed) {
  if (!list.length && !empty) return '';
  const body = list.length ? `<div class="flist">${list.map(fRow).join('')}</div>` : `<div class="flist"><div class="fempty">${esc(empty)}</div></div>`;
  if (collapsed) return `<div class="fgroup"><details ${LS.get('fopen.' + title, false) ? 'open' : ''} data-fgrp="${esc(title)}"><summary>${esc(title)} <span class="count">${list.length}</span>${hint ? `<small>${hint}</small>` : ''}</summary>${body}</details></div>`;
  return `<div class="fgroup"><h3>${esc(title)} <span class="count">${list.length}</span>${hint ? `<small>${hint}</small>` : ''}</h3>${body}</div>`;
}
function fAlerts() {
  const out = [];
  if (!state.configured) out.push(['Noch nicht verbunden. ' + state.problems.join(' '), 'Einstellungen']);
  (state.errors || []).forEach(m => out.push([m, /sonar/i.test(m) ? 'Sonar prüfen' : 'Einstellungen']));
  if (state.jira && state.jira.ok === false) out.push(['Jira: ' + (state.jira.error || 'antwortet nicht'), 'Einstellungen']);
  return out.filter(([m]) => !fSkip.has('al:' + m)).map(([m, b]) => `<div class="falert" role="status">${ic('alert')}<span>${esc(m)}</span><button data-fset="1">${esc(b)}</button><button class="quiet-btn" data-falx="${esc(m)}" title="Bis zum Schliessen des Tabs ausblenden" aria-label="Ausblenden">${ic('x')}</button></div>`).join('');
}
function fSources() {
  const src = state.sources || [];
  if (!src.length) return '';
  const ago = ts => { const m = Math.max(0, Math.round((Date.now() / 1000 - ts) / 60)); return m < 1 ? 'gerade' : m < 120 ? `vor ${m} min` : `vor ${Math.round(m / 60)} h`; };
  return `<div class="fsrc" aria-label="Stand je Quelle">${src.map(x => x.ok ? `<span class="ok" title="${esc(x.name)}: letzter Abgleich erfolgreich">${esc(x.name)} ${ago(x.ts)}</span>`
    : `<span class="bad" title="${esc(x.name)}: letzter Abgleich fehlgeschlagen. Angezeigt wird der Stand vom letzten Erfolg, als «veraltet» markiert.">${esc(x.name)}: Fehler${x.last_ok ? ', Stand ' + ago(x.last_ok) : ''}</span>`).join('')}</div>`;
}
function renderFocus() {
  if (!state) return;
  const box = $('fList');
  if (!state.flow) { box.innerHTML = fAlerts() + (state.configured ? '<div class="flist"><div class="fempty">lädt …</div></div>' : ''); $('fHero').innerHTML = ''; renderRail(); return; }
  const g = focusGroups();
  $('fAlerts').innerHTML = fAlerts() + fSources();
  const hk = $('hCkNew'), hkv = hk ? [hk.dataset.hck, hk.value, document.activeElement === hk] : null;      // Eingabe im Hero über das Neuzeichnen retten
  $('fHero').innerHTML = heroHtml(g.hero, g);
  if (hkv && $('hCkNew') && $('hCkNew').dataset.hck === hkv[0]) { $('hCkNew').value = hkv[1]; if (hkv[2]) $('hCkNew').focus(); }
  const tests = g.mine.filter(e => e.d.phase === 5 && e.d.next.kind === 'do'), mine = g.mine.filter(e => !tests.includes(e));      // 0.42: Testen bleibt nicht liegen
  box.innerHTML = fGroup('Wartet auf deinen Test', 'Details → «Jetzt testen»: Stand in IntelliJ, Prüfliste, Abnahme', tests, '')
    + fGroup('Du bist dran', 'Blocker zuerst, dann was am weitesten ist', mine, g.hero || tests.length ? '' : 'Nichts. Alles andere wartet auf CI, andere oder Agenten.')
    + fGroup('Andere warten auf dich', 'Reviews und dir zugeteilte MRs', g.reviews, '')
    + fGroup(hdName(), 'Dir zugewiesen, nach Priorität und SLA', g.hd, '')
    + hdQueue()
    + fGroup('Läuft gerade', 'CI, Review, Agent: nichts zu tun, nur im Blick', g.wait, '')
    + fGroup('Geplant und Ideen', 'noch nicht begonnen', g.plan, '', true)
    + `<div class="fkeys"><kbd>j</kbd> <kbd>k</kbd> auswählen · <kbd>Enter</kbd> Details · <kbd>a</kbd> nächsten Schritt ausführen · <kbd>n</kbd> neue Aufgabe · <kbd>i</kbd> Idee · <kbd>Esc</kbd> schliessen${g.done ? ` · ${g.done} erledigt im Board` : ''}</div>`;
  const rows = [...document.querySelectorAll('#viewFocus [data-fid]')];
  if (fSel >= rows.length) fSel = rows.length - 1;
  if (fSel >= 0 && rows[fSel]) rows[fSel].classList.add('sel');
  renderRail();
  celebrateNew();
  if (FXID) renderFx();
  const ses = FOC() && FOC().session;
  if (ses && !FM_OPEN && !LS.get('fmMin', false) && !$('fsDlg').open) FM_OPEN = true;
  renderFmode();
}
// Neue Erfolge seit dem letzten Blick: kurz feiern
function celebrateNew() {
  const s = state.flow && state.flow.stats;
  if (!s || F().score === false) return;
  const last = LS.get('fxLast', null);
  LS.set('fxLast', s.last_id);
  if (last === null || s.last_id <= last) return;
  const news = s.recent.filter(r => r.id > last).slice(0, 3);
  news.forEach((r, i) => setTimeout(() => xpToast(r), i * 700));
  if (news.length) burstAt($('fRing') || document.body);
}
function eventText(r) {
  const ph = state.flow.phases;
  if (r.kind === 'check') return `Teilschritt erledigt: ${r.text}`;
  if (r.kind === 'agent') return `${r.key}: ${r.text}`;
  return `${r.key} ${r.phase === 7 ? 'ist fertig' : 'ist bei ' + ((ph[r.phase] || {}).label || '?')}`;
}
function xpToast(r) { const t = document.createElement('div'); t.className = 'toast xpt'; t.textContent = `+${r.xp} XP · ${eventText(r)}`; stackToast(t); document.body.appendChild(t); setTimeout(() => t.remove(), 3400); }
function burstAt(el) {
  if (matchMedia('(prefers-reduced-motion: reduce)').matches || !el || !el.getBoundingClientRect) return;
  const r = el.getBoundingClientRect(), b = document.createElement('div');
  b.className = 'burst'; b.style.left = (r.left + r.width / 2) + 'px'; b.style.top = (r.top + r.height / 2) + 'px';
  const cols = ['var(--xp)', 'var(--focus)', 'var(--ok)', 'var(--jira)'];
  for (let i = 0; i < 16; i++) {
    const a = (i / 16) * Math.PI * 2 + Math.random() * .4, d = 34 + Math.random() * 30, p = document.createElement('i');
    p.style.cssText = `--x:${Math.cos(a) * d}px;--y:${Math.sin(a) * d}px;--r:${Math.random() * 360}deg;--c:${cols[i % cols.length]}`;
    b.appendChild(p);
  }
  document.body.appendChild(b); setTimeout(() => b.remove(), 900);
}
function renderRail() {
  const s = F().score === false ? null : state.flow && state.flow.stats;      // E3 (0.35): Spielstand an einer Stelle, abschaltbar
  let h = '';
  if (s) {
    const C = 2 * Math.PI * 34, pct = Math.min(1, s.today_steps / Math.max(1, s.goal));
    const left = Math.max(0, s.goal - s.today_steps);
    const mx = Math.max(1, ...s.week.map(w => w.n));
    const today = s.week.length ? s.week[s.week.length - 1].day : '';
    const wd = d => ['So', 'Mo', 'Di', 'Mi', 'Do', 'Fr', 'Sa'][new Date(d + 'T12:00:00').getDay()];
    h += `<section class="rcard score ${s.goal_met ? 'met' : ''}">
      <div class="ring" id="fRing" title="Schritte heute: ${s.today_steps} von ${s.goal}"><svg viewBox="0 0 86 86"><circle class="bg" cx="43" cy="43" r="34"/><circle class="fg" cx="43" cy="43" r="34" stroke-dasharray="${C.toFixed(1)}" stroke-dashoffset="${(C * (1 - pct)).toFixed(1)}"/></svg>
        <div class="rin"><b>${s.today_steps}</b></div><small>von ${s.goal}</small></div>
      <div class="sinfo"><b>${s.goal_met ? 'Tagesziel geschafft' : left === s.goal ? 'Erster Schritt wartet' : `Noch ${left} bis zum Tagesziel`}</b>
        <span class="xp">+${s.today_xp} XP heute</span>
        <span class="streak ${s.streak ? '' : 'off'}" title="Tage in Folge mit mindestens einem Schritt">${ic('flame')} ${s.streak ? s.streak + (s.streak === 1 ? ' Tag' : ' Tage') + ' in Folge' : 'Noch keine Serie'}</span></div>
      <div class="week" aria-label="Schritte der letzten 7 Tage">${s.week.map(w => `<i class="${w.n ? '' : 'zero'} ${w.day === today ? 'today' : ''}" style="--h:${(w.n / mx).toFixed(2)}" title="${esc(w.day)}: ${w.n} Schritt${w.n === 1 ? '' : 'e'}"></i>`).join('')}</div>
      <div class="wdays">${s.week.map(w => `<span>${wd(w.day)}</span>`).join('')}</div>
      ${s.recent.length ? `<ul class="recent">${s.recent.slice(0, LS.get('scoreOpen', false) ? 12 : 4).map(r => `<li><b class="xp">+${r.xp}</b><span title="${esc(eventText(r))}">${esc(eventText(r))}</span></li>`).join('')}</ul>` : ''}
      <div class="small quiet">${LS.get('scoreOpen', false) ? 'XP gibt es für erledigte Schritte, Teilschritte, Abnahmen, Reviews und Fokus-Sitzungen ab 20 min. Abschalten: Einstellungen → Fokus. Klick: weniger zeigen.' : 'Klick: mehr vom Verlauf'}</div>
    </section>`;
  }
  h += m365Rail();
  h += focusRail();
  h += wsRail();
  const j = state.jira;
  if (j && j.ok) {
    const n = Math.max(j.limit, j.count);
    h += `<section class="rcard wip"><h3>In Arbeit <small>${j.count} von ${j.limit} Stories</small></h3><div class="wipbar">${Array.from({ length: n }, (_, i) => `<i class="${i < j.count ? (i >= j.limit ? 'over' : 'on') : ''}"></i>`).join('')}</div>
      ${j.over ? '<div class="small" style="color:var(--bad)">Über dem Limit. Erst etwas abschliessen, dann Neues beginnen.</div>' : j.count < j.limit ? '<div class="small quiet">Platz für eine weitere Story.</div>' : '<div class="small quiet">Voll. Fertig machen geht vor Anfangen.</div>'}</section>`;
  }
  const runs = ((state.agents && state.agents.runs) || []).filter(r => r.active || r.status === 'zugewiesen').slice(0, 6);
  if (state.agents && state.agents.enabled) {
    const drag = state.agents.agents.map(a => { const q = agQuota(a); return `<span class="agdrag ${q ? q.cls : ''}" draggable="true" data-agdrag="${esc(a.id)}" title="Klick: der Aufgabe oben (oder der offenen) zuweisen. Oder auf eine Aufgabe im Fokus oder im Board ziehen${a.roles.length < 4 ? '. Rollen: ' + a.roles.map(x => ROLE_L[x]).join(', ') : ''}">${ic('play')}${esc(a.name)}${q ? ` <small>${esc(q.text)}</small>` : ''}</span>`; }).join('');
    h += `<section class="rcard"><h3>Agenten <small>${runs.filter(r => r.active).length} aktiv</small></h3>${drag ? `<div class="agdrags">${drag}</div>` : ''}${runs.length ? runs.map(r => `<div class="ragent" data-arun="${r.id}">${r.active ? '<span class="agspin"></span>' : ic('clock')}<b>${esc(r.agent_name)}</b><span>${esc(r.ticket)} · ${esc(r.status)}</span></div>`).join('') : '<div class="small quiet">Kein Agent beschäftigt. Zuweisen geht im Detail jeder Aufgabe.</div>'}</section>`;
  }
  if (F().ideas) h += `<section class="rcard"><h3>Ideen <small>${(state.ideas || []).filter(i => ['neu', 'geparkt'].includes(i.status) && !i.expired).length}/${state.idea_cap || ''} im Pool</small></h3><button data-fidea="1">Idee festhalten <kbd class="small quiet">i</kbd></button></section>`;
  $('fRailCards').innerHTML = h;
}
