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

  // Who's on it: picking a name saves straight away (Done lives in PK_Ops
  // and is checked against MAX on the next plan -- see buy_status.py).
  document.querySelectorAll('select.owner-pick').forEach(function (sel) {
    sel.addEventListener('change', function () { sel.form.submit(); });
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

// Vendor order: ticks drive the totals, the copy and the CSV.
document.querySelectorAll('table.vendor-order').forEach(function (table) {
  const rows = Array.from(table.querySelectorAll('tbody tr'));
  const all = table.querySelector('input.all');
  const count = document.querySelector('.sel-count');
  const total = document.querySelector('.sel-total');
  const money = n => n.toLocaleString('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 0 });
  const picked = () => rows.filter(r => r.querySelector('.pick').checked);
  function sum() {
    const p = picked();
    count.textContent = p.length + ' of ' + rows.length + ' parts';
    total.textContent = '· about ' + money(p.reduce((s, r) => s + (+r.dataset.spend || 0), 0));
    rows.forEach(r => r.classList.toggle('off', !r.querySelector('.pick').checked));
    all.checked = p.length === rows.length;
  }
  rows.forEach(r => r.querySelector('.pick').addEventListener('change', sum));
  all.addEventListener('change', () => { rows.forEach(r => r.querySelector('.pick').checked = all.checked); sum(); });
  const cells = r => [r.dataset.part, r.dataset.vpart, r.dataset.qty, r.dataset.unit, r.dataset.need];
  document.querySelector('.copy-po').addEventListener('click', function () {
    const btn = this;
    const text = picked().map(r => cells(r).join('\t')).join('\n');
    navigator.clipboard.writeText(text).then(
      () => { const t = btn.textContent; btn.textContent = 'Copied ✓'; setTimeout(() => btn.textContent = t, 1800); },
      () => { btn.textContent = 'Copy blocked — use CSV'; });
  });
  document.querySelector('.csv-po').addEventListener('click', function () {
    const q = s => '"' + String(s == null ? '' : s).replace(/"/g, '""') + '"';
    const head = ['Our part', 'Their part', 'Description', 'Qty', 'Unit cost', 'Extended', 'Need by'];
    const body = picked().map(r => [r.dataset.part, r.dataset.vpart, r.dataset.desc, r.dataset.qty,
      r.dataset.unit, r.dataset.spend, r.dataset.need].map(q).join(','));
    const blob = new Blob([[head.map(q).join(',')].concat(body).join('\r\n')], { type: 'text/csv' });
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = 'PO ' + table.dataset.vendor.replace(/[^\w .-]/g, '') + '.csv';
    a.click();
    setTimeout(() => URL.revokeObjectURL(a.href), 1000);
  });
  sum();
  const focus = table.querySelector('tr.focus');
  if (focus) focus.scrollIntoView({ block: 'center' });
});


// Ten overbuys cleared in a day: a celebration, once a day per browser. Three
// take turns -- a confetti storm, a rocket, and a present to open (which
// rickrolls). Reduced motion gets the words without the movement.
(function () {
  const mark = document.getElementById('celebrate');
  if (!mark) return;
  const day = mark.dataset.day, n = mark.dataset.n;
  let turn = 0;
  try {
    if (localStorage.getItem('pkmrp-ten-' + day)) return;
    localStorage.setItem('pkmrp-ten-' + day, '1');
    turn = Number(localStorage.getItem('pkmrp-ten-turn') || 0);
    localStorage.setItem('pkmrp-ten-turn', String((turn + 1) % 3));
  } catch (e) { turn = Math.floor(Math.random() * 3); }
  const still = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  function overlay(html) {
    const o = document.createElement('div');
    o.className = 'cheer';
    o.setAttribute('role', 'dialog');
    o.setAttribute('aria-modal', 'true');
    o.innerHTML = '<div class="cheer-card">' + html +
      '<button class="btn cheer-close" type="button">Back to work</button></div>';
    const close = () => o.remove();
    o.addEventListener('click', e => { if (e.target === o) close(); });
    o.querySelector('.cheer-close').addEventListener('click', close);
    document.addEventListener('keydown', function esc(e) {
      if (e.key === 'Escape') { close(); document.removeEventListener('keydown', esc); }
    });
    document.body.appendChild(o);
    return o;
  }
  function confetti(count) {
    if (still) return;
    const colours = ['#009576', '#70ffcd', '#facc15', '#53ffff', '#007a61', '#fb923c'];
    for (let i = 0; i < count; i++) {
      const c = document.createElement('i');
      c.className = 'confetti';
      c.style.left = Math.random() * 100 + 'vw';
      c.style.background = colours[i % colours.length];
      c.style.animationDelay = Math.random() * 1.2 + 's';
      c.style.transform = 'rotate(' + Math.random() * 360 + 'deg)';
      document.body.appendChild(c);
      setTimeout(() => c.remove(), 4400);
    }
  }
  const title = '<h2>' + n + ' overbuys cleared today!</h2>';

  if (turn === 0) {
    overlay(title + '<p>The list is the real work again. That\'s a tidy desk.</p>');
    confetti(160);
  } else if (turn === 1) {
    overlay(title + '<p>Overbuys down, morale to the moon.</p>');
    if (!still) {
      const r = document.createElement('div');
      r.className = 'rocket';
      r.innerHTML = '<svg class="rocket-ship" viewBox="0 0 40 80" width="48" height="96" aria-hidden="true">' +
        '<path d="M20 2 C31 14 33 30 31 52 H9 C7 30 9 14 20 2 Z" fill="#eef1f3" stroke="#14181d" stroke-width="2"/>' +
        '<circle cx="20" cy="26" r="6" fill="#53ffff" stroke="#14181d" stroke-width="2"/>' +
        '<path d="M9 40 L1 58 L9 54 Z M31 40 L39 58 L31 54 Z" fill="#009576" stroke="#14181d" stroke-width="2"/>' +
        '<path d="M13 52 Q20 80 27 52 Z" fill="#facc15"/><path d="M16 52 Q20 68 24 52 Z" fill="#fb923c"/></svg>';
      document.body.appendChild(r);
      for (let i = 0; i < 14; i++) {
        const p = document.createElement('i');
        p.className = 'puff';
        p.style.animationDelay = (i * 0.12) + 's';
        p.style.left = (48 + Math.random() * 4) + 'vw';
        document.body.appendChild(p);
        setTimeout(() => p.remove(), 3600);
      }
      setTimeout(() => r.remove(), 3400);
      setTimeout(() => confetti(60), 1800);
    }
  } else {
    const o = overlay(title + '<p>Something arrived for you. It was even on time.</p>' +
      '<button class="gift" type="button" aria-label="Open your present">' +
      '<span class="gift-lid"></span><span class="gift-box"></span></button>' +
      '<p class="muted small gift-hint">Click to open</p>');
    const gift = o.querySelector('.gift');
    gift.addEventListener('click', function () {
      gift.classList.add('open');
      o.querySelector('.gift-hint').textContent = '';
      setTimeout(function () {
        const v = document.createElement('div');
        v.className = 'gift-video';
        v.innerHTML = '<iframe src="https://www.youtube-nocookie.com/embed/dQw4w9WgXcQ?autoplay=1" ' +
          'title="Your present" allow="autoplay; encrypted-media" allowfullscreen></iframe>' +
          '<p class="small">Never gonna let your overbuys down. ' +
          '<a href="https://www.youtube.com/watch?v=dQw4w9WgXcQ" target="_blank" rel="noopener">Won\'t play? Open it here.</a></p>';
        gift.replaceWith(v);
        confetti(80);
      }, still ? 0 : 650);
    }, { once: true });
  }
})();


// Top menus: one open at a time; click outside or Escape closes.
(function () {
  const menus = Array.from(document.querySelectorAll('details.menu'));
  menus.forEach(m => m.addEventListener('toggle', () => {
    if (m.open) menus.forEach(o => { if (o !== m) o.open = false; });
  }));
  document.addEventListener('click', e => {
    if (!e.target.closest('details.menu')) menus.forEach(m => { m.open = false; });
  });
  document.addEventListener('keydown', e => {
    if (e.key === 'Escape') menus.forEach(m => { m.open = false; });
  });
})();
