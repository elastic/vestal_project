/* ARA Brief page status indicator (alignment A4, spec 02 section 3.6). One copy for every
   Brief page; page.py inlines it and its check diffs the inlined copy against this file.
   Polls /status.json every 10 s until ready or failed. The indicator is a courtesy; the
   Brief's check is the gate. */
(function () {
  var el = document.getElementById('status');
  if (!el) { return; }
  function show(state, text) {
    el.className = 'status-' + state;
    el.textContent = text;
  }
  function poll() {
    fetch('/status.json', { cache: 'no-store' })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (s) {
        if (s && s.ready) {
          show('ready', 'Environment ready. Select Check.');
          return;
        }
        if (s && s.error) {
          show('failed', 'Provisioning failed during ' + s.error + '. Stop this track and start it again.');
          return;
        }
        if (s) {
          var where = s.step_n ? 'step ' + s.step_n + ' of ' + s.step_total + ', ' + s.step : 'starting';
          var mins = s.started ? Math.max(0, Math.floor((Date.now() / 1000 - s.started) / 60)) : 0;
          show('waiting', 'Provisioning: ' + where + ' (' + mins + ' min)');
        }
        setTimeout(poll, 10000);
      })
      .catch(function () { setTimeout(poll, 10000); });
  }
  poll();
}());
