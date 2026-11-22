// App und Handy: als App installieren, Geräte koppeln.
// 0.36: tinyops als App (PWA) und Handy koppeln
const PWA = { prompt: null, installed: window.matchMedia && matchMedia('(display-mode: standalone)').matches };
window.addEventListener('beforeinstallprompt', ev => { ev.preventDefault(); PWA.prompt = ev; if ($('app-install')) { $('app-install').disabled = false; $('app-inst-msg').textContent = 'Öffnet tinyops in einem eigenen Fenster, mit Symbol im Dock oder Startmenü.'; } });
window.addEventListener('appinstalled', () => { PWA.prompt = null; PWA.installed = true; toast('tinyops ist als App installiert.'); });
if ('serviceWorker' in navigator && window.isSecureContext && !navigator.webdriver) navigator.serviceWorker.register('/sw.js').catch(() => { /* ohne App-Hülle geht es auch */ });
let appCodeT = null;
async function appDevices() {
  const box = $('app-devs'); if (!box) return;
  try {
    const r = await api('GET', '/api/pair/devices');
    box.innerHTML = r.devices.length ? `<b class="small">Gekoppelte Geräte</b><ul class="devlist">${r.devices.map(d => `<li><span>${esc(d.name)}</span><span class="quiet small">gekoppelt ${fmtDay(d.created)} · zuletzt ${d.last_seen ? devAgo(d.last_seen) : 'nie'}</span><button data-devrm="${d.id}">Entfernen</button></li>`).join('')}</ul>`
      : '<div class="small quiet">Noch kein Gerät gekoppelt.</div>';
  } catch (e) { box.innerHTML = `<div class="small quiet">${esc(e.message)}</div>`; }
}
const fmtDay = ts => new Date(ts * 1000).toLocaleDateString('de-CH');
const devAgo = ts => { const m = Math.round((Date.now() / 1000 - ts) / 60); return m < 2 ? 'gerade' : m < 60 ? `vor ${m} min` : m < 1440 ? `vor ${Math.round(m / 60)} h` : fmtDay(ts); };
function wireApp() {
  if (!$('app-code')) return;
  appDevices();
  $('app-install').onclick = async () => { if (!PWA.prompt) return; PWA.prompt.prompt(); try { await PWA.prompt.userChoice; } catch (e) { /* egal */ } PWA.prompt = null; $('app-install').disabled = true; };
  $('app-code').onclick = async () => {
    try {
      const r = await post('/api/pair/start', {}), url = (r.phone_url || val('app-phone') || 'https://<Adresse>') + '/pair';
      clearInterval(appCodeT);
      const tick = () => { const s = r.expires - Math.floor(Date.now() / 1000); const el = $('app-cdown'); if (!el) { clearInterval(appCodeT); return; }
        if (s <= 0) { $('app-codebox').innerHTML = '<div class="small quiet">Code abgelaufen. Bei Bedarf einen neuen erzeugen.</div>'; clearInterval(appCodeT); appDevices(); return; }
        el.textContent = `noch ${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`; };
      // 0.39: QR-Code (Prüfbericht r36-05): Kamera aufs Bild, der Code steht dann schon im Feld
      $('app-codebox').innerHTML = `<div class="paircode${r.qr ? ' withqr' : ''}">${r.qr ? `<div class="pqr" title="Mit der Kamera des Handys scannen">${r.qr}</div>` : ''}<div><div class="pc">${esc(r.code)}</div><div class="small">${r.qr ? 'Mit der Kamera scannen, oder auf' : 'Auf'} dem Handy öffnen: <b>${esc(url)}</b> <button class="quiet-btn" id="app-cpy">kopieren</button><br>${r.qr ? 'Der Code steht nach dem Scannen schon im Feld' : 'Code eintippen'}. Gilt einmal, <span id="app-cdown"></span>.</div>
        ${r.phone_url ? '' : '<div class="small" style="color:var(--warn)">Oben noch die Adresse fürs Handy eintragen und speichern, sonst lässt tinyops das Handy nicht herein.</div>'}</div></div>`;
      $('app-cpy').onclick = () => copyText(url, 'Adresse');
      tick(); appCodeT = setInterval(tick, 1000);
      const poll = setInterval(() => { if (!$('app-cdown')) { clearInterval(poll); return; } appDevices(); }, 5000);
    } catch (e) { toast(e.message); }
  };
  $('app-devs').onclick = async ev => {
    const b = ev.target.closest('[data-devrm]'); if (!b) return;
    if (!confirm('Dieses Gerät entfernen? Es sieht tinyops danach nicht mehr, bis du es neu koppelst.')) return;
    try { await post('/api/pair/revoke', { id: +b.dataset.devrm }); appDevices(); toast('Gerät entfernt'); } catch (e) { toast(e.message); }
  };
}
