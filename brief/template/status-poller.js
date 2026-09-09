/* Polls /status.json every 10 s; three states: waiting (amber), ready (green), failed (red). */
(function () {
  function setState(state, text) {
    var dots  = document.querySelectorAll('.status-dot');
    var texts = document.querySelectorAll('.status-text');
    dots.forEach(function (d) {
      d.classList.remove('ready', 'failed');
      if (state !== 'waiting') d.classList.add(state);
    });
    texts.forEach(function (t) { t.textContent = text; });
  }

  function poll() {
    fetch('/status.json', { cache: 'no-store' })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (data) {
        if (!data) {
          setTimeout(poll, 10000);
          return;
        }
        if (data.ready) {
          setState('ready', 'Environment ready - select Next');
        } else if (data.error) {
          setState('failed', 'Provisioning failed - stop this track and start it again');
        } else {
          setTimeout(poll, 10000);
        }
      })
      .catch(function () { setTimeout(poll, 10000); });
  }

  document.addEventListener('DOMContentLoaded', function () {
    setTimeout(poll, 5000);
  });
}());
