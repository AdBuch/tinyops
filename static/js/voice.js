// 0.43: Voice Prompting. Diktieren in Prompt-Felder und Sprachbefehle an Agenten, erkannt von deinem lokalen Server.
// Aufnahme im Browser (Web Audio), als WAV 16 kHz mono an tinyops; zurück kommt nur Text. Gespeichert wird die Aufnahme nirgends.
const VOICE_FIELDS = ['#agPrompt', '#agCont', '#agGateNote', '#agAns', '#rvGoal', '#ideaQuick', '#ideaText', '#tcNote', '#tcNew', '#tcBackNote', '#fxNote', '#tk-desc'];
const VREC = { on: false, busy: false, ctx: null, stream: null, src: null, node: null, chunks: [], rate: 48000, t0: 0, level: 0, timer: 0, done: null };
function voiceOn() { return !!(state && state.voice && state.voice.enabled); }
function voiceMax() { return (state && state.voice && state.voice.max) || 120; }

async function vStart(onTick) {
  if (VREC.on || VREC.busy) return false;
  if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
    toast(window.isSecureContext ? 'Dieser Browser kann nicht aufnehmen.' : 'Das Mikrofon geht nur am Rechner (localhost) oder über https. Auf dem Handy tinyops über https öffnen.');
    return false;
  }
  try { VREC.stream = await navigator.mediaDevices.getUserMedia({ audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true, autoGainControl: true } }); }
  catch (e) { toast(e && e.name === 'NotAllowedError' ? 'Kein Zugriff aufs Mikrofon: im Browser für diese Seite erlauben.' : 'Kein Mikrofon gefunden.'); return false; }
  const AC = window.AudioContext || window.webkitAudioContext;
  VREC.ctx = new AC(); VREC.rate = VREC.ctx.sampleRate; VREC.chunks = []; VREC.level = 0;
  VREC.src = VREC.ctx.createMediaStreamSource(VREC.stream);
  VREC.node = VREC.ctx.createScriptProcessor(4096, 1, 1);
  VREC.node.onaudioprocess = ev => {
    const d = ev.inputBuffer.getChannelData(0); VREC.chunks.push(new Float32Array(d));
    let s = 0; for (let i = 0; i < d.length; i += 8) s += d[i] * d[i]; VREC.level = Math.min(1, Math.sqrt(s / (d.length / 8)) * 6);
  };
  VREC.src.connect(VREC.node); VREC.node.connect(VREC.ctx.destination);
  VREC.on = true; VREC.t0 = performance.now();
  VREC.timer = setInterval(() => {
    const sec = (performance.now() - VREC.t0) / 1000;
    if (onTick) onTick(sec, VREC.level);
    if (sec >= voiceMax()) { toast(`Nach ${voiceMax()} s automatisch beendet.`); if (VREC.done) VREC.done(); }
  }, 150);
  return true;
}
function vRelease() {
  clearInterval(VREC.timer); VREC.on = false; VREC.done = null;
  try { VREC.node && VREC.node.disconnect(); VREC.src && VREC.src.disconnect(); } catch (e) { /* schon getrennt */ }
  if (VREC.stream) VREC.stream.getTracks().forEach(t => t.stop());
  if (VREC.ctx) VREC.ctx.close().catch(() => {});
  VREC.stream = VREC.ctx = VREC.src = VREC.node = null;
}
function encodeWav(chunks, rate) {        // Float32 beliebiger Rate → 16 kHz, 16 Bit, mono
  const n = chunks.reduce((a, c) => a + c.length, 0), all = new Float32Array(n);
  let o = 0; chunks.forEach(c => { all.set(c, o); o += c.length; });
  const ratio = rate / 16000, len = Math.floor(n / ratio), pcm = new Int16Array(len);
  for (let i = 0; i < len; i++) {
    const a = Math.floor(i * ratio), b = Math.min(n, Math.floor((i + 1) * ratio)); let s = 0;
    for (let j = a; j < b; j++) s += all[j];
    const v = Math.max(-1, Math.min(1, s / Math.max(1, b - a))); pcm[i] = v < 0 ? v * 0x8000 : v * 0x7fff;
  }
  const buf = new ArrayBuffer(44 + pcm.length * 2), dv = new DataView(buf), w = (p, s) => [...s].forEach((ch, i) => dv.setUint8(p + i, ch.charCodeAt(0)));
  w(0, 'RIFF'); dv.setUint32(4, 36 + pcm.length * 2, true); w(8, 'WAVE'); w(12, 'fmt '); dv.setUint32(16, 16, true); dv.setUint16(20, 1, true); dv.setUint16(22, 1, true);
  dv.setUint32(24, 16000, true); dv.setUint32(28, 32000, true); dv.setUint16(32, 2, true); dv.setUint16(34, 16, true); w(36, 'data'); dv.setUint32(40, pcm.length * 2, true);
  new Int16Array(buf, 44).set(pcm);
  return new Blob([buf], { type: 'audio/wav' });
}
async function vFinish(cancel) {          // Aufnahme beenden; gibt den erkannten Text zurück (oder null)
  if (!VREC.on) return null;
  const chunks = VREC.chunks, rate = VREC.rate, secs = (performance.now() - VREC.t0) / 1000;
  vRelease(); VREC.chunks = [];
  if (cancel) return null;
  if (secs < 0.5) { toast('Zu kurz. Knopf drücken, sprechen, nochmal drücken.'); return null; }
  VREC.busy = true;
  try {
    const r = await fetch('/api/voice/transcribe', { method: 'POST', headers: { 'X-Requested-With': 'tinyops', 'Content-Type': 'audio/wav' }, body: encodeWav(chunks, rate) });
    const j = await r.json().catch(() => ({}));
    if (!r.ok) { toast(j.error || 'Spracherkennung fehlgeschlagen.'); return null; }
    if (!j.text) { toast('Nichts verstanden. Näher ans Mikrofon oder lauter.'); return null; }
    return j.text;
  } catch (e) { toast('Keine Verbindung zu tinyops.'); return null; }
  finally { VREC.busy = false; }
}

// ---------------------------------------------------------------- Diktieren in ein Feld: Mikrofon oben rechts im Feld, Alt+M
let vField = null;
const vMic = document.createElement('button');
vMic.id = 'vMic'; vMic.type = 'button'; vMic.hidden = true; vMic.className = 'vmic';
vMic.setAttribute('aria-label', 'Diktieren (Alt+M)'); vMic.title = 'Diktieren (Alt+M): sprechen, nochmal klicken; der Text kommt an die Cursorstelle';
vMic.innerHTML = ic('mic') + '<span></span>';
function vIsField(el) { return !!(el && el.matches && VOICE_FIELDS.some(s => el.matches(s)) && !el.disabled && !el.readOnly); }
function vPlace() {
  if (!vField || !document.contains(vField)) { if (!VREC.on && !VREC.busy) vMic.hidden = true; return; }
  const host = vField.closest('dialog[open]') || document.body;
  if (vMic.parentElement !== host) host.appendChild(vMic);
  const r = vField.getBoundingClientRect(), hr = host === document.body || getComputedStyle(host).transform === 'none' ? { top: 0, right: document.documentElement.clientWidth } : host.getBoundingClientRect();
  vMic.style.top = (r.top - hr.top + 4) + 'px';                  // rechts angeschlagen: wächst beim Aufnehmen nach links, nie aus dem Feld
  vMic.style.left = 'auto';
  vMic.style.right = (hr.right - r.right + 6 + (vField.scrollHeight > vField.clientHeight ? 12 : 0)) + 'px';
  vMic.hidden = r.width < 120 || r.bottom < 0 || r.top > innerHeight;
}
function vInsert(el, text) {
  if (!el || !document.contains(el)) { copyText(text, 'Erkannter Text'); return; }
  const v = el.value, s = el.selectionStart ?? v.length, e = el.selectionEnd ?? v.length;
  const pre = s > 0 && !/\s$/.test(v.slice(0, s)) ? ' ' : '', post = e < v.length && !/^\s/.test(v.slice(e)) ? ' ' : '';
  el.setRangeText(pre + text + post, s, e, 'end');
  el.dispatchEvent(new Event('input', { bubbles: true }));
  el.focus();
}
function vMicState(cls, label) { vMic.className = 'vmic ' + cls; vMic.querySelector('span').textContent = label || ''; }
async function vToggleField() {
  if (VREC.busy) return;
  if (VREC.on) { VREC.done && VREC.done(); return; }
  const el = vField;
  if (!el) return;
  const ok = await vStart((sec, lvl) => { vMicState('rec', Math.floor(sec) + ' s'); vMic.style.setProperty('--lvl', lvl.toFixed(2)); });
  if (!ok) return;
  vMicState('rec', '0 s');
  VREC.done = async () => { vMicState('busy', '…'); const t = await vFinish(false); vMicState(''); if (t) vInsert(el, t); vPlace(); };
}
vMic.addEventListener('mousedown', ev => ev.preventDefault());       // Fokus bleibt im Feld
vMic.addEventListener('click', ev => { ev.preventDefault(); ev.stopPropagation(); vToggleField(); });
document.addEventListener('focusin', ev => { if (voiceOn() && vIsField(ev.target)) { vField = ev.target; vPlace(); } });
document.addEventListener('focusout', ev => { if (ev.target === vField) setTimeout(() => { if (document.activeElement !== vField && !VREC.on && !VREC.busy) vMic.hidden = true; }, 150); });
addEventListener('scroll', () => { if (!vMic.hidden) vPlace(); }, true);
addEventListener('resize', () => { if (!vMic.hidden) vPlace(); });
document.addEventListener('keydown', ev => {
  if (ev.altKey && ev.code === 'KeyM' && voiceOn() && (vIsField(document.activeElement) || (VREC.on && vField))) { ev.preventDefault(); vField = vIsField(document.activeElement) ? document.activeElement : vField; vToggleField(); }
  else if (ev.key === 'Escape' && VREC.on && !VC.open) { ev.preventDefault(); ev.stopPropagation(); vFinish(true); vMicState(''); toast('Aufnahme verworfen.'); }
}, true);

// ---------------------------------------------------------------- Sprachbefehl: Taste v oder Knopf oben; Vorschlag, dann bestätigen
const VC = { open: false, step: '', plan: null, text: '', err: '' };
const vBar = document.createElement('div');
vBar.id = 'vBar'; vBar.hidden = true; vBar.setAttribute('role', 'dialog'); vBar.setAttribute('aria-label', 'Sprachbefehl');
document.body.appendChild(vBar);
function vcPhaseOpts(p) {
  return ['develop', 'plan', 'review', 'test'].map(x => `<option value="${x}" ${x === p.phase ? 'selected' : ''}>${{ develop: 'Entwickeln', plan: 'Planen', review: 'Review', test: 'Test' }[x]}</option>`).join('');
}
function vcDraw() {
  if (!VC.open) { vBar.hidden = true; return; }
  vBar.hidden = false;
  const said = VC.text ? `<div class="vsaid">«${esc(VC.text)}»</div>` : '';
  if (VC.step === 'rec') { vBar.innerHTML = `<div class="vrow"><span class="vdot"></span><b>Ich höre zu</b><span class="small quiet" id="vSec">0 s</span><span class="sp"></span>
    <button class="primary" data-vc="stop">Fertig</button><button data-vc="cancel">Abbrechen</button></div>
    <div class="small quiet">Zum Beispiel: «DLP-123 an Qwen zum Entwickeln», «DLP-123 an Claude planen, nur zuweisen», «Review für MR 47 mit Qwen». Leertaste beendet, Esc bricht ab.</div>`; return; }
  if (VC.step === 'busy') { vBar.innerHTML = `${said}<div class="vrow"><span class="agspin"></span><span>${VC.text ? 'Verstehe den Befehl …' : 'Erkenne …'}</span></div>`; return; }
  if (VC.step === 'err') { vBar.innerHTML = `${said}<div class="banner bad">${esc(VC.err)}</div><div class="vrow"><span class="sp"></span><button class="primary" data-vc="again">${ic('mic')} Nochmal</button><button data-vc="cancel">Schliessen</button></div>`; return; }
  const p = VC.plan, ags = AG().agents || [];
  const what = p.kind === 'mr_review' ? `Review für <b>!${p.mr.iid}</b> ${esc(p.mr.title)}${p.ticket ? ` <span class="quiet">(${esc(p.ticket)})</span>` : ''}`
    : `<b>${esc(p.key || p.ticket)}</b> ${esc(p.title || '')}`;
  vBar.innerHTML = `${said}<div class="vplan"><div class="vwhat">${what}</div>
    <div class="vrow wrap"><label>Agent <select data-vcf="agent">${ags.map(a => `<option value="${esc(a.id)}" ${a.id === p.agent ? 'selected' : ''}>${esc(agOptLabel(a, p.phase))}</option>`).join('')}</select></label>
      ${p.kind === 'mr_review' ? '<span class="chip">Review des MR</span>' : `<label>Rolle <select data-vcf="phase">${vcPhaseOpts(p)}</select></label>
      <label class="check"><input type="checkbox" data-vcf="start" ${p.start ? 'checked' : ''}><span>gleich starten</span></label>`}</div>
    ${p.warn ? `<div class="small warn-t">${esc(p.warn)}</div>` : ''}${p.ok ? '' : `<div class="banner bad">${esc(p.why)}</div>`}
    <div class="small quiet">Verstanden mit ${esc(p.via || 'Regeln')}. Was du gesagt hast, geht wörtlich an den Agenten.</div></div>
    <div class="vrow"><span class="sp"></span><button class="primary" data-vc="run" ${p.ok ? '' : 'disabled'}>${ic('play')} ${p.kind === 'mr_review' || p.start ? 'Starten' : 'Zuweisen'}</button>
    <button data-vc="dialog" title="Im gewohnten Dialog öffnen, um Prompt oder Projekt anzupassen">Im Dialog öffnen</button><button data-vc="cancel">Verwerfen</button></div>`;
  const b = vBar.querySelector('[data-vc="run"]'); if (b && !b.disabled) b.focus();
}
async function vcOpen() {
  if (VC.open && VC.step === 'rec') return vcStop();
  if (!voiceOn()) { toast('Spracherkennung ist aus: Einstellungen → Sprache.'); return; }
  if (!(state.agents && state.agents.enabled)) { toast('Noch kein Agent eingerichtet.'); return; }
  Object.assign(VC, { open: true, step: 'rec', plan: null, text: '', err: '' }); vcDraw();
  const ok = await vStart(sec => { const s = $('vSec'); if (s) s.textContent = Math.floor(sec) + ' s'; });
  if (!ok) { VC.open = false; vcDraw(); return; }
  VREC.done = vcStop;
}
async function vcStop() {
  VC.step = 'busy'; vcDraw();
  const t = await vFinish(false);
  if (!t) { VC.open = false; vcDraw(); return; }
  VC.text = t; vcDraw();
  try { VC.plan = await post('/api/voice/command', { text: t }); VC.step = 'plan'; }
  catch (e) { VC.err = e.message; VC.step = 'err'; }
  vcDraw();
}
function vcClose() { if (VREC.on) vFinish(true); VC.open = false; vcDraw(); }
async function vcRecheck() {
  try { VC.plan = await post('/api/voice/command', { text: VC.text, plan: VC.plan }); } catch (e) { toast(e.message); }
  vcDraw();
}
vBar.addEventListener('change', ev => {
  const f = ev.target.dataset && ev.target.dataset.vcf; if (!f || !VC.plan) return;
  VC.plan[f] = f === 'start' ? ev.target.checked : ev.target.value;
  vcRecheck();
});
vBar.addEventListener('click', async ev => {
  const b = ev.target.closest('[data-vc]'); if (!b) return;
  const a = b.dataset.vc, p = VC.plan;
  if (a === 'stop') return vcStop();
  if (a === 'cancel') return vcClose();
  if (a === 'again') return vcOpen();
  if (a === 'dialog' && p) {
    vcClose();
    if (p.kind === 'mr_review') {
      const e = focusEntries().find(x => x.t === 'review' && x.r.iid === p.mr.iid && x.r.project_id === p.mr.project_id);
      if (!e) { toast('Den MR finde ich im Fokus nicht.'); return; }
      RV.prefill = { agent: p.agent, ticket: p.ticket || '', goal: VC.text }; RV.pending = `${e.r.project_id}:${e.r.iid}`; openFx(e.id);
      return;
    }
    agCtx[p.ticket] = agCtx[p.ticket] || { key: p.key || '', title: p.title || '', url: '', items: p.project_id != null ? [{ project_id: p.project_id, branch: p.branch }] : [] };
    openAgentDlg({ ticket: p.ticket, agent: p.agent, phase: p.phase, parent: p.parent || undefined });
    return;
  }
  if (a === 'run' && p) {
    b.disabled = true;
    try {
      const r = await post('/api/voice/run', { ...p, text: VC.text });
      toast(r.started ? `${r.agent} legt los (Lauf ${r.id}).` : `${r.agent} ist zugewiesen (Lauf ${r.id}). Starten im Agenten-Dialog.`);
      vcClose(); await load();
    } catch (e) { toast(e.message); b.disabled = false; }
  }
});
document.addEventListener('keydown', ev => {
  if (VC.open) {
    if (ev.key === 'Escape') { ev.preventDefault(); ev.stopPropagation(); vcClose(); return; }
    if (VC.step === 'rec' && ev.key === ' ') { ev.preventDefault(); vcStop(); return; }
    return;
  }
  if (ev.key === 'v' && !ev.ctrlKey && !ev.metaKey && !ev.altKey && voiceOn() && !/INPUT|TEXTAREA|SELECT/.test(document.activeElement.tagName)
      && !document.querySelector('dialog[open]:not(.side)') && state.agents && state.agents.enabled) { ev.preventDefault(); vcOpen(); }
}, true);
$('voiceBtn').innerHTML = ic('mic'); $('voiceBtn').setAttribute('aria-label', 'Sprachbefehl (Taste v)');
$('voiceBtn').onclick = () => vcOpen();
function renderVoice() { $('voiceBtn').hidden = !(voiceOn() && state.agents && state.agents.enabled); }
