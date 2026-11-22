// UI-Nutzung lokal erfassen (nur mit Schalter, nie Eingabetext).
// ------------------------------------------------ UI-Nutzung (0.22): lokal erfassen, damit die Oberfläche besser wird
// Erfasst Klicks (Element-Beschreibung, keine Inhalte), tote Klicks, Tasten ausserhalb von Feldern, Dialoge, Ansichten,
// Mausweg und grobe Verteilung. Nie: Text aus Feldern, Titel von Zeilen und Karten. Ausschalten: Einstellungen → Weiteres.
const UX = { q: [], sess: Math.random().toString(36).slice(2, 12), hover: null, hoverT: 0, move: {}, lastMove: null, lastMoveT: 0, typing: null, trail: [] };
const uxOn = () => !!(state && state.ux && state.ux.enabled);
function uxPush(e) {
  if (!uxOn() && !(state === undefined || state === null)) return;
  e.ts = Date.now() / 1000; e.v = e.v || (typeof view !== 'undefined' ? view : '');
  UX.q.push(e);
  if (UX.q.length > 400) UX.q.splice(0, UX.q.length - 400);
  if (['click', 'dead', 'view', 'dialog', 'fail'].includes(e.k)) { UX.trail.push(`${e.k === 'view' ? 'Ansicht' : e.k === 'dead' ? 'tot' : e.k === 'fail' ? 'Fehler' : e.k === 'dialog' ? 'Dialog' : 'Klick'} ${e.t || ''}`.slice(0, 80)); if (UX.trail.length > 8) UX.trail.shift(); }
}
const UX_ACT = '.wsrepo > summary,[data-wsgo],button,a,input,select,textarea,summary,label,[role=button],[tabindex],[data-fopen],[data-fgo],[data-open],.frow,.hero[data-fid],.bcard,.tab,.chip[data-arun],.rcard.score,.aipace,#fbar,dialog';
function uxDesc(el) {
  if (!el || el === document.body || el === document.documentElement) return 'body';
  const tag = el.tagName.toLowerCase();
  let d = tag + (el.id ? '#' + el.id : '');
  const da = [...el.attributes].map(a => a.name).find(n => n.startsWith('data-') && !['data-tbase'].includes(n));
  if (da) d += '[' + da.slice(5) + ']';
  else if (!el.id && el.classList.length) d += '.' + el.classList[0];
  const labelled = tag === 'button' || tag === 'summary' || el.classList.contains('tab') || el.getAttribute('role') === 'button';
  if (labelled) {
    const t = (el.getAttribute('aria-label') || el.textContent || '').replace(/\s+/g, ' ').trim().replace(/\d+/g, '#');
    if (t && t.length <= 40) d += ' «' + t + '»';
  } else if (tag === 'a') d += el.target === '_blank' ? ' (extern)' : ' (intern)';
  else if (tag === 'input') d += '(' + (el.type || 'text') + ')';
  return d.slice(0, 110);
}
function uxCtx(el) {
  const c = el && el.closest && el.closest('dialog[id],#fx,#fbar,.rcard,.hero,.fgroup,.sset,.wsrepo,#viewWs,#viewTime,#viewQa,#viewSettings,#fHero,#fList,#fRail,#board,#left,#aside,header,nav');
  return c ? (c.id ? c.id : [...c.classList].slice(0, 2).join('.') || c.tagName.toLowerCase()) : '';
}
document.addEventListener('pointerover', ev => {
  const el = ev.target.closest && ev.target.closest(UX_ACT);
  if (el !== UX.hover) { UX.hover = el; UX.hoverT = performance.now(); }
}, { passive: true, capture: true });
document.addEventListener('click', ev => {
  if (!uxOn()) return;
  const el = ev.target.closest && ev.target.closest(UX_ACT);
  const x = ev.clientX / Math.max(1, innerWidth), y = ev.clientY / Math.max(1, innerHeight);
  if (!el) { uxPush({ k: 'dead', t: uxDesc(ev.target), c: uxCtx(ev.target), x, y }); return; }
  const h = el === UX.hover ? Math.round(performance.now() - UX.hoverT) : null;
  uxPush({ k: 'click', t: uxDesc(el), c: uxCtx(el), x, y, e: h != null && ev.detail ? { h } : (ev.detail ? {} : { kb: 1 }) });
}, { capture: true });
document.addEventListener('keydown', ev => {
  if (!uxOn()) return;
  const t = ev.target, field = t && (t.isContentEditable || /^(input|textarea|select)$/i.test(t.tagName));
  if (field) {     // nur zählen, nie den Inhalt
    const d = uxDesc(t);
    if (!UX.typing || UX.typing.t !== d) { uxFlushTyping(); UX.typing = { t: d, c: uxCtx(t), n: 0 }; }
    UX.typing.n++;
    if (['Enter', 'Escape', 'Tab'].includes(ev.key)) uxPush({ k: 'key', t: ev.key + ' in Feld' });
    return;
  }
  if (['Shift', 'Control', 'Alt', 'Meta'].includes(ev.key)) return;
  const k = (ev.ctrlKey ? 'Ctrl+' : '') + (ev.metaKey ? 'Cmd+' : '') + (ev.altKey ? 'Alt+' : '') + (ev.key.length === 1 ? ev.key.toLowerCase() : ev.key);
  uxPush({ k: 'key', t: k.slice(0, 24) });
}, { capture: true });
function uxFlushTyping() { if (UX.typing && UX.typing.n) uxPush({ k: 'type', t: UX.typing.t, c: UX.typing.c, e: { n: UX.typing.n } }); UX.typing = null; }
document.addEventListener('focusout', () => uxFlushTyping(), true);
document.addEventListener('pointermove', ev => {
  if (!uxOn() || ev.pointerType === 'touch') return;
  const now = performance.now();
  if (now - UX.lastMoveT < 80) return;
  UX.lastMoveT = now;
  const v = typeof view !== 'undefined' ? view : '', m = UX.move[v] || (UX.move[v] = { d: 0, g: {} });
  const x = ev.clientX / Math.max(1, innerWidth), y = ev.clientY / Math.max(1, innerHeight);
  if (UX.lastMove) m.d += Math.hypot(x - UX.lastMove[0], (y - UX.lastMove[1]) * innerHeight / Math.max(1, innerWidth));
  UX.lastMove = [x, y];
  const cell = Math.min(11, Math.floor(x * 12)) + ',' + Math.min(7, Math.floor(y * 8));
  m.g[cell] = (m.g[cell] || 0) + 1;
}, { passive: true });
window.addEventListener('error', ev => { if (uxOn()) uxPush({ k: 'error', t: String(ev.message || 'Fehler').slice(0, 100) + (ev.lineno ? ' (Zeile ' + ev.lineno + ')' : '') }); });
(() => {      // Dialoge auf/zu
  const so = HTMLDialogElement.prototype.showModal, cl = HTMLDialogElement.prototype.close;
  HTMLDialogElement.prototype.showModal = function () { if (!this.open) uxPush({ k: 'dialog', t: this.id || 'dialog', e: { s: 'open' } }); return so.apply(this, arguments); };
  HTMLDialogElement.prototype.close = function () { if (this.open) uxPush({ k: 'dialog', t: this.id || 'dialog', e: { s: 'close' } }); return cl.apply(this, arguments); };
  document.addEventListener('cancel', ev => { if (ev.target.tagName === 'DIALOG') uxPush({ k: 'dialog', t: ev.target.id || 'dialog', e: { s: 'close' } }); }, true);
})();
let uxEnvSent = false;
async function uxFlush(keepalive) {
  if (!uxOn()) { UX.q = []; UX.move = {}; return; }
  uxFlushTyping();
  if (!uxEnvSent) { uxPush({ k: 'env', e: { w: innerWidth, h: innerHeight, dpr: devicePixelRatio, touch: matchMedia('(pointer: coarse)').matches, ver: state && state.version,
    views: [...document.querySelectorAll('.tab[data-view]')].filter(t => !t.hidden && t.offsetParent).map(t => t.dataset.view) } }); uxEnvSent = true; }
  for (const [v, m] of Object.entries(UX.move)) if (m.d || Object.keys(m.g).length) UX.q.push({ k: 'move', v, ts: Date.now() / 1000, e: { d: Math.round(m.d * 100) / 100, g: m.g } });
  UX.move = {};
  if (!UX.q.length) return;
  const events = UX.q.splice(0, UX.q.length);
  try { await fetch('/api/ux/events', { method: 'POST', headers: H, body: JSON.stringify({ sess: UX.sess, events }), keepalive: !!keepalive }); }
  catch (e) { if (!keepalive) UX.q.unshift(...events.slice(-200)); }
}
setInterval(() => uxFlush(false), 15000);
document.addEventListener('visibilitychange', () => { if (document.visibilityState === 'hidden') uxFlush(true); });
window.addEventListener('pagehide', () => uxFlush(true));
