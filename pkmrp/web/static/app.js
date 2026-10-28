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
    } else if (e.key === 'd' && document.activeElement.classList.contains('card')) {
      const card = document.activeElement;
      setDone(card, !card.classList.contains('done'));
      if (card.classList.contains('done')) focus(at + 1);
    }
  });

  // "Why?" opens and closes the same panel (any page): fetched once, then toggled.
  document.addEventListener('click', function (e) {
    const btn = e.target.closest('.why-btn[data-why]');
    if (!btn) return;
    const box = document.querySelector(btn.dataset.target);
    if (!box) return;
    const open = btn.getAttribute('aria-expanded') === 'true';
    if (open) {
      box.hidden = true;
      btn.setAttribute('aria-expanded', 'false');
      btn.textContent = btn.dataset.label || btn.textContent;
      return;
    }
    btn.dataset.label = btn.dataset.label || btn.textContent;
    btn.setAttribute('aria-expanded', 'true');
    btn.textContent = 'Hide';
    box.hidden = false;
    if (!box.dataset.loaded) {
      box.innerHTML = '<p class="muted small">Loading…</p>';
      fetch(btn.dataset.why, { credentials: 'same-origin' })
        .then(r => r.text()).then(html => { box.innerHTML = html; box.dataset.loaded = '1'; })
        .catch(() => { box.innerHTML = '<p class="muted small">Could not load — try again.</p>'; });
    }
  });

  // Done: fold a card to one line, remembered in this browser for this plan.
  const list = document.querySelector('.cards[data-plan]');
  const key = list ? 'pkmrp-done-' + list.dataset.plan : null;
  let doneSet = new Set();
  try { if (key) doneSet = new Set(JSON.parse(localStorage.getItem(key) || '[]')); } catch (e) {}
  function save() { try { if (key) localStorage.setItem(key, JSON.stringify([...doneSet])); } catch (e) {} }
  function count() {
    const el = document.querySelector('.done-count');
    if (!el || !cards.length) return;
    const n = cards.filter(c => c.classList.contains('done')).length;
    el.textContent = n ? n + ' of ' + cards.length + ' done' + (n === cards.length ? ' — all clear 🎉' : '') : '';
    return n;
  }
  function setDone(card, done, quiet) {
    card.classList.toggle('done', done);
    card.querySelector('.done-line').hidden = !done;
    if (done) doneSet.add(card.dataset.part); else doneSet.delete(card.dataset.part);
    save();
    const n = count();
    if (!quiet && done && n === cards.length) confetti(90);
  }
  cards.forEach(function (card) {
    if (doneSet.has(card.dataset.part)) setDone(card, true, true);
    card.querySelector('.done-btn').addEventListener('click', e => { e.stopPropagation(); setDone(card, true); });
    card.querySelector('.undo-btn').addEventListener('click', e => { e.stopPropagation(); setDone(card, false); });
  });
  count();

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


// Search, everywhere it helps: the same rules as core/search.py, light.
// Words in any order, any case; dashes and spaces in part numbers ignored.
(function () {
  const squash = s => (s || '').toLowerCase().replace(/[\s\-_.]/g, '');
  const ALIASES = { assembly: ['assy', 'asy'], board: ['ecb', 'pcb'], cable: ['cbl', 'cable'],
                    option: ['opt', 'option'], power: ['pwr', 'power'], motor: ['mtr', 'motor'] };
  function forms(w) {
    w = w.toLowerCase();
    const out = [w];
    if (w.length > 3 && w.endsWith('s')) out.push(w.slice(0, -1));
    out.slice().forEach(f => (ALIASES[f] || []).forEach(a => out.push(a)));
    return out;
  }
  function matches(text, q) {
    const low = text.toLowerCase(), sq = squash(text);
    return q.split(/[\s,;/]+/).filter(Boolean).every(w =>
      forms(w).some(f => low.includes(f)) || (squash(w).length >= 3 && sq.includes(squash(w))));
  }

  // Table filters (All buys, Committed, Lead times)
  document.querySelectorAll('.table-filter').forEach(function (box) {
    const wrap = box.closest('.table-tools').nextElementSibling;
    const rows = Array.from(wrap.querySelectorAll('tbody tr')).filter(r => !r.classList.contains('cp-row'));
    const count = box.parentElement.querySelector('.filter-count');
    box.addEventListener('input', function () {
      const q = box.value.trim();
      let shown = 0;
      rows.forEach(function (r) {
        const ok = !q || matches(r.textContent, q);
        r.hidden = !ok;
        const detail = r.nextElementSibling;
        if (detail && detail.classList.contains('cp-row')) detail.hidden = !ok;
        if (ok) shown++;
      });
      count.textContent = q ? shown + ' of ' + rows.length : '';
    });
  });

  // Part picker with descriptions (Promise)
  document.querySelectorAll('input[data-suggest]').forEach(function (input) {
    const list = input.parentElement.querySelector('.suggest');
    let items = [], at = -1, timer = null;
    function render() {
      list.innerHTML = items.map((p, i) =>
        '<li role="option" data-i="' + i + '" class="' + (i === at ? 'on' : '') + '">' +
        '<b>' + p.part + '</b> <span class="d">' + p.description.toLowerCase() + '</span>' +
        '<span class="t">' + p.type + (p.on_hand ? ' · ' + p.on_hand + ' on hand' : '') + '</span></li>').join('');
      list.hidden = !items.length;
      input.setAttribute('aria-expanded', items.length ? 'true' : 'false');
    }
    function pick(i) {
      if (!items[i]) return;
      input.value = items[i].part;
      items = []; render();
      const qty = input.form.querySelector('[name=qty]');
      if (qty) qty.focus();
    }
    input.addEventListener('input', function () {
      clearTimeout(timer);
      const q = input.value.trim();
      if (q.length < 2) { items = []; render(); return; }
      timer = setTimeout(function () {
        fetch(input.dataset.suggest + '?q=' + encodeURIComponent(q), { credentials: 'same-origin' })
          .then(r => r.json()).then(d => { items = d.parts || []; at = items.length ? 0 : -1; render(); })
          .catch(() => {});
      }, 140);
    });
    input.addEventListener('keydown', function (e) {
      if (list.hidden) return;
      if (e.key === 'ArrowDown') { at = Math.min(at + 1, items.length - 1); render(); e.preventDefault(); }
      else if (e.key === 'ArrowUp') { at = Math.max(at - 1, 0); render(); e.preventDefault(); }
      else if (e.key === 'Enter' && at >= 0) { pick(at); e.preventDefault(); }
      else if (e.key === 'Escape') { items = []; render(); }
    });
    list.addEventListener('mousedown', function (e) {
      const li = e.target.closest('li'); if (li) { pick(+li.dataset.i); e.preventDefault(); }
    });
    input.addEventListener('blur', () => setTimeout(() => { items = []; render(); }, 150));
  });
})();


// Shelf order: copy "vendor-part qty" lines for a quick-order paste.
document.querySelectorAll('.copy-cart').forEach(function (btn) {
  btn.addEventListener('click', function () {
    navigator.clipboard.writeText(btn.dataset.lines).then(
      () => { const t = btn.textContent; btn.textContent = 'Copied ✓'; setTimeout(() => btn.textContent = t, 1800); },
      () => { btn.textContent = 'Select and copy below'; });
  });
});
