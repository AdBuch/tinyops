// Update aus dem Panel und tinyops als Dienst (0.40): neue Version erkennen, mit einem Klick aktualisieren, unter Linux als Dienst einrichten.
let UPD = null;
async function checkUpdate(force) {
  try { UPD = await api('GET', '/api/update/check' + (force ? '?force=1' : '')); } catch (e) { return; }
  renderUpdBar();
  if ($('upd-box')) renderUpdBox();
  // der erste Blick läuft im Hintergrund: kurz danach noch einmal holen
  if (!UPD.checked && !(UPD.service || {}).demo && !checkUpdate.again) { checkUpdate.again = true; setTimeout(() => checkUpdate(false), 20000); }
}
function updHidden() { try { return UPD && localStorage.getItem('tinyops.updhide') === UPD.latest; } catch (e) { return false; } }
function renderUpdBar() {
  const b = $('updAvail');
  if (!b) return;
  const show = UPD && UPD.available && !updHidden();
  b.hidden = !show;
  if (!show) return;
  b.innerHTML = `<div class="banner upd"><b>tinyops ${esc(UPD.latest)} ist da</b> <span class="quiet">(du hast ${esc(UPD.current)})</span>
    ${UPD.url ? `<a class="quiet-btn" href="${esc(UPD.url)}" target="_blank" rel="noopener">Was ist neu?</a>` : ''}
    ${UPD.can_update ? '<button class="quiet-btn" data-updrun>Jetzt aktualisieren</button>' : `<span class="quiet small">${esc(UPD.why)}</span>`}
    <button class="x" data-updhide aria-label="Für diese Version ausblenden">×</button></div>`;
}
async function runUpdate(btn) {
  if (!confirm(`tinyops auf ${UPD.latest} aktualisieren? Selbsttest danach, bei Fehlern zurück auf ${UPD.current}. tinyops startet dabei neu.`)) return;
  await busy(btn, 'Aktualisiere …', async () => {
    let r;
    try { r = await post('/api/update/run', {}); } catch (e) { toast(e.message); return; }
    if (!r.changed) { toast(r.text ? r.text.split('\n').slice(-3).join(' ') : 'Nichts aktualisiert.'); await checkUpdate(true); return; }
    waitRestart('v' + r.version);
  });
}
// Nach Update oder Wechsel zum Dienst: warten, bis tinyops wieder antwortet, dann neu laden
function waitRestart(want) {
  const ov = document.createElement('div');
  ov.className = 'restart';
  ov.innerHTML = `<div><b>tinyops startet neu …</b><div class="quiet small">${want ? 'auf ' + esc(want) : ''} Die Seite lädt gleich von selbst.</div></div>`;
  document.body.appendChild(ov);
  const t0 = Date.now();
  const tick = async () => {
    try {
      const r = await fetch('/healthz', { cache: 'no-store' });
      const j = await r.json();
      if (r.ok && (!want || 'v' + j.version === want) && Date.now() - t0 > 1500) { location.reload(); return; }
    } catch (e) { /* noch weg */ }
    if (Date.now() - t0 > 120000) { ov.querySelector('.quiet').textContent = 'Antwortet nicht. Läuft tinyops noch? Seite von Hand neu laden.'; return; }
    setTimeout(tick, 1000);
  };
  setTimeout(tick, 1200);
}
function renderUpdBox() {
  const u = UPD || {}, s = u.service || {};
  const when = u.checked ? new Date(u.checked * 1000).toLocaleString('de-CH', { dateStyle: 'short', timeStyle: 'short' }) : 'noch nicht';
  $('upd-box').innerHTML = `<div class="small"><b>Version:</b> ${esc(u.current || '')}${u.latest ? ` · neuestes Release: <b>${esc(u.latest)}</b>` : ''} <span class="quiet">(nachgesehen: ${esc(when)})</span>
      ${u.url ? ` · <a href="${esc(u.url)}" target="_blank" rel="noopener">Was ist neu?</a>` : ''}</div>
    ${u.why ? `<div class="small quiet">${esc(u.why)}</div>` : ''}
    <div class="row" style="margin-top:6px"><button id="upd-check">Jetzt nachsehen</button>${u.can_update ? `<button class="primary" data-updrun>${esc(u.latest)} installieren</button>` : ''}</div>
    <h3 style="margin:16px 0 6px">Als Dienst (Linux)</h3>
    ${!s.supported ? '<div class="small quiet">Nur unter Linux mit systemd. Unter macOS und Windows startet der Launcher tinyops.</div>'
      : `<div class="small">${s.installed ? `Dienst eingerichtet${s.enabled ? ', startet bei der Anmeldung' : ', aber ausgeschaltet'}${s.active ? ', läuft' : ''}.` : 'Noch kein Dienst.'}
        ${s.running_as_service ? ' Dieses tinyops läuft als Dienst.' : ''} <span class="quiet">(<code>${esc(s.unit || '')}</code>)</span></div>
        ${s.installed && !s.linger ? '<div class="small quiet">Damit tinyops auch ohne Anmeldung läuft (z. B. nach einem Neustart des Rechners), einmal im Terminal: <code>loginctl enable-linger $USER</code></div>' : ''}
        <div class="row" style="margin-top:6px">${s.demo ? '<span class="small quiet">Im Demo-Modus aus.</span>' : !s.installed
          ? '<button class="primary" id="upd-svc-now" title="Dienst anlegen, dieses tinyops beenden, der Dienst startet es neu">Als Dienst einrichten und neu starten</button><button id="upd-svc" title="Nur anlegen und einschalten; gilt ab der nächsten Anmeldung">Nur einrichten</button>'
          : '<button id="upd-svc-rm">Dienst entfernen</button>'}</div>`}`;
  $('upd-check').onclick = () => busy($('upd-check'), 'Sehe nach …', () => checkUpdate(true));
  const svc = async (btn, body, label) => busy(btn, label, async () => {
    try {
      const s2 = await post('/api/update/service', body);
      if (body.now && !s2.running_as_service) { waitRestart(''); return; }
      toast(body.do === 'remove' ? 'Dienst entfernt' : 'Dienst eingerichtet'); UPD.service = s2; renderUpdBox();
    } catch (e) { toast(e.message); }
  });
  if ($('upd-svc-now')) $('upd-svc-now').onclick = () => { if (confirm('tinyops als Dienst einrichten? Dieses tinyops endet, der Dienst startet es sofort neu.')) svc($('upd-svc-now'), { do: 'install', now: true }, 'Richte ein …'); };
  if ($('upd-svc')) $('upd-svc').onclick = () => svc($('upd-svc'), { do: 'install' }, 'Richte ein …');
  if ($('upd-svc-rm')) $('upd-svc-rm').onclick = () => { if (confirm('Dienst entfernen? tinyops startet dann nicht mehr von selbst.')) svc($('upd-svc-rm'), { do: 'remove' }, 'Entferne …'); };
}
document.addEventListener('click', ev => {
  const t = ev.target.closest && ev.target.closest('[data-updrun],[data-updhide]');
  if (!t) return;
  if (t.hasAttribute('data-updhide')) { try { localStorage.setItem('tinyops.updhide', UPD.latest); } catch (e) { /* egal */ } renderUpdBar(); return; }
  runUpdate(t);
});
