/* Polls /status.json every 10 s; turns the last-slide indicator green when ready. */
(function () {
  function poll() {
    fetch('/status.json', { cache: 'no-store' })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (data) {
        if (data && data.ready) {
          var dots = document.querySelectorAll('.status-dot');
          var texts = document.querySelectorAll('.status-text');
          dots.forEach(function (d) { d.classList.add('ready'); });
          texts.forEach(function (t) { t.textContent = 'Environment ready — select Check'; });
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
