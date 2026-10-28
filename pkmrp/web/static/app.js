// PK-MRP: keyboard moves through the top buys, and a small celebration when
// buys came off the list since the last run (once a day per browser).
(function () {
  const cards = Array.from(document.querySelectorAll('.card'));
  let at = -1;
  function focus(i) {
    if (!cards.length) return;
    at = Math.max(0, Math.min(cards.length - 1, i));
    cards[at].focus();
    cards[at].scrollIntoView({ block: 'nearest', behavior: 'smooth' });
  }
  document.addEventListener('keydown', function (e) {
    if (e.target.closest('input, select, textarea')) return;
    if (e.key === 'j') focus(at + 1);
    else if (e.key === 'k') focus(at - 1);
    else if (e.key === 'Enter' && document.activeElement.classList.contains('card')) {
      const btn = document.activeElement.querySelector('.why-btn');
      if (btn) btn.click();
    }
  });

  function confetti(n) {
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;
    const colours = ['#009576', '#70ffcd', '#facc15', '#53ffff', '#007a61'];
    for (let i = 0; i < n; i++) {
      const c = document.createElement('i');
      c.className = 'confetti';
      c.style.left = Math.random() * 100 + 'vw';
      c.style.background = colours[i % colours.length];
      c.style.animationDelay = Math.random() * 0.6 + 's';
      c.style.transform = 'rotate(' + Math.random() * 360 + 'deg)';
      document.body.appendChild(c);
      setTimeout(() => c.remove(), 3200);
    }
  }
  const win = document.querySelector('.tile.win.lit, .allclear[data-confetti]');
  if (win) {
    const key = 'pkmrp-cheered-' + new Date().toISOString().slice(0, 10);
    let seen = false;
    try { seen = localStorage.getItem(key); localStorage.setItem(key, '1'); } catch (e) {}
    if (!seen) confetti(70);
  }
})();
