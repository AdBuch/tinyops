// Start: erster Abgleich, Takt, Sprung zur Ansicht aus der Adresse. Muss als letztes stehen.
mistralPush(); addEventListener('hashchange', mistralPush);
if (location.hash === '#settings') setTimeout(() => setView('settings'), 0);
if (location.hash === '#board') setTimeout(() => setView('board'), 0);
if (location.hash === '#ws') setTimeout(() => setView('ws'), 0);
if (location.hash === '#overview' || location.hash === '#lists') setTimeout(() => setView('overview'), 0);
if (!location.hash || location.hash === '#focus') setTimeout(() => setView('focus'), 0);
$('fRailUsage').appendChild($('usageBox'));
load();
setInterval(() => { if (!(state && state.sync && state.sync.running)) load(); }, 300000);   // der Server gleicht ohnehin nur alle cache_seconds ab
setInterval(() => {   // laufende Agenten: Stand nachfragen, aber keine offene Auswahl wegrendern
  const ae = document.activeElement;
  if (state && state.agents && state.agents.runs.some(r => r.active) && !$('agDlg').open && !(ae && ae.dataset && ae.dataset.aassign)) load();
}, 5000);
checkUpdate(false); setInterval(() => checkUpdate(false), 6 * 3600 * 1000);   // 0.40: neue Version?
