/* ARA Brief deck runtime
   Navigation: arrow keys, space, on-screen prev/next, overview (key: o), deep link #/N
*/
(function () {
  'use strict';

  var slides, current, stepIndex, steps;

  function init() {
    slides = Array.from(document.querySelectorAll('.deck > section[data-index]'));
    if (!slides.length) return;

    // Deep-link: #/N (1-based)
    var hash = window.location.hash.replace('#/', '');
    current = (parseInt(hash, 10) - 1) || 0;
    current = Math.max(0, Math.min(current, slides.length - 1));

    goTo(current, true);
    buildOverview();

    document.addEventListener('keydown', onKey);
    document.getElementById('btn-prev').addEventListener('click', prev);
    document.getElementById('btn-next').addEventListener('click', next);
    document.getElementById('btn-overview').addEventListener('click', toggleOverview);
  }

  function goTo(idx, skipReveal) {
    slides.forEach(function (s) { s.classList.remove('active'); });
    current = Math.max(0, Math.min(idx, slides.length - 1));
    slides[current].classList.add('active');

    // Reset steps for new slide
    steps = Array.from(slides[current].querySelectorAll('.step'));
    stepIndex = skipReveal ? steps.length : 0;
    steps.forEach(function (s, i) {
      s.classList.toggle('visible', skipReveal || false);
    });

    updateNav();
    updateHash();
    updateOverviewCurrent();
  }

  function next() {
    // If there are unrevealed steps, reveal next one
    if (stepIndex < steps.length) {
      steps[stepIndex].classList.add('visible');
      stepIndex++;
      return;
    }
    if (current < slides.length - 1) goTo(current + 1);
  }

  function prev() {
    if (current > 0) goTo(current - 1);
  }

  function onKey(e) {
    if (document.getElementById('overview').classList.contains('open')) {
      if (e.key === 'Escape' || e.key === 'o') { closeOverview(); }
      return;
    }
    switch (e.key) {
      case 'ArrowRight': case 'ArrowDown': case ' ': e.preventDefault(); next(); break;
      case 'ArrowLeft':  case 'ArrowUp':            e.preventDefault(); prev(); break;
      case 'o': toggleOverview(); break;
    }
  }

  function updateNav() {
    document.getElementById('btn-prev').disabled = current === 0;
    document.getElementById('btn-next').disabled = current === slides.length - 1 && stepIndex >= steps.length;
    document.getElementById('slide-counter').textContent = (current + 1) + ' / ' + slides.length;
  }

  function updateHash() {
    history.replaceState(null, '', '#/' + (current + 1));
  }

  function buildOverview() {
    var grid = document.getElementById('overview');
    slides.forEach(function (slide, i) {
      var thumb = document.createElement('div');
      thumb.className = 'overview-thumb';
      var num = document.createElement('div');
      num.className = 'overview-num';
      num.textContent = i + 1;
      var title = slide.querySelector('.slide-title, .slide-heading, h2, h3');
      var label = document.createElement('div');
      label.textContent = title ? title.textContent.slice(0, 60) : '';
      label.style.fontSize = '11px';
      label.style.color = '#343741';
      thumb.appendChild(num);
      thumb.appendChild(label);
      thumb.addEventListener('click', function () { goTo(i); closeOverview(); });
      grid.appendChild(thumb);
    });
  }

  function updateOverviewCurrent() {
    var thumbs = document.querySelectorAll('.overview-thumb');
    thumbs.forEach(function (t, i) {
      t.classList.toggle('current', i === current);
    });
  }

  function toggleOverview() {
    var ov = document.getElementById('overview');
    ov.classList.toggle('open');
    updateOverviewCurrent();
  }
  function closeOverview() {
    document.getElementById('overview').classList.remove('open');
  }

  document.addEventListener('DOMContentLoaded', init);
}());
