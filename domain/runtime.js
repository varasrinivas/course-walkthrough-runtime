/* domain — link a course's own vocabulary to its definitions, at runtime.
 *
 * A course anchored on a domain explains that domain once, usually in module
 * zero, and then assumes it for thirty more. A reader who starts in the middle,
 * or who forgets what a UCC-3 or an OKF or an "arm" is by module fourteen, has
 * nowhere to look. This turns the first use of each domain word in each view
 * into a chip that opens its definition, and puts the whole glossary one key
 * away from anywhere.
 *
 * It runs over the RENDERED DOM and needs no change to the host player: like
 * the walkthrough runtime it hydrates itself off a MutationObserver, so a
 * player that swaps innerHTML on module change is re-linked without knowing we
 * exist. That is also why nothing here may touch what a module's source says —
 * the courses validate their authored markup against closed class vocabularies.
 *
 * No dependencies. Every class is dg-prefixed. window.DG is the only global.
 */
(function (global) {
  'use strict';

  var CFG = {
    scope: ['#mvBody', 'main.content', 'main', 'body'],
    skip: [],
    chrome: {},
    shortcut: 'g',
    title: 'Glossary',
    subtitle: '',
  };

  /* Never link inside these. Three groups, all load-bearing:
   *
   *   literal text   code/pre/kbd/samp — the reader is meant to read the bytes
   *   already live   a/button/select/... — a chip inside one eats its clicks,
   *                  and a button inside a button is invalid HTML
   *   foreign/owned  svg/math/canvas draw in another namespace, where an HTML
   *                  <button> does not render at all without a foreignObject;
   *                  [data-wt]/.wt is the walkthrough widget, which re-renders
   *                  its own steps and would destroy anything we put there;
   *                  .term-tooltip is a hand-authored definition and must never
   *                  be second-guessed by a generated one.
   *
   * `svg` is here because omitting it is not hypothetical: it put 27 of 160
   * chips inside diagram <text> nodes in context-eng-kit, where they neither
   * rendered nor let the real first prose occurrence be linked.
   */
  var BASE_SKIP = [
    'code', 'pre', 'kbd', 'samp', 'var', 'tt',
    'a', 'button', 'select', 'textarea', 'input', 'label', 'option',
    'svg', 'math', 'canvas',
    'h1', 'h2', 'h3', 'h4', 'h5', 'h6',
    'script', 'style', 'title', '[contenteditable]',
    '[data-wt]', '.wt',
    '.term-tooltip', '.tooltip-content',
    '.dg-ui', '.dg-chip', '[data-dg-skip]',
  ];

  var CORPUS = null;
  var INDEX = null;
  var LINKING = false;      // set while we mutate, so the observer ignores us
  var PENDING = null;
  var PASSES = 0;
  var openChip = null;
  var started = false;

  // ── index ────────────────────────────────────────────────────────────────
  function escapeRe(s) { return s.replace(/[.*+?^${}()|[\]\\-]/g, '\\$&'); }

  function buildIndex(corpus) {
    var byForm = Object.create(null);
    var forms = [];
    (corpus.glossary || []).forEach(function (g) {
      [g.term].concat(g.match || []).forEach(function (f) {
        byForm[f.toLowerCase()] = g;
        forms.push(f);
      });
    });
    // Longest first: JS alternation takes the first branch that matches, not
    // the longest, so "blanket lien" must be offered before "lien" and "UCC-3"
    // before "UCC".
    forms.sort(function (a, b) { return b.length - a.length; });
    if (!forms.length) return null;
    var alt = forms.map(escapeRe).join('|');
    return {
      byForm: byForm,
      re: new RegExp('\\b(' + alt + ')(s|es)?\\b', 'gi'),
    };
  }

  // A `cs: true` entry matches only its declared casing. One regex still does
  // the scanning; this rejects the hit afterwards. It is how MCP, OKF, EIN and
  // the EXTRACTED/INFERRED/AMBIGUOUS tags avoid matching ordinary prose.
  function resolve(hit) {
    var e = INDEX.byForm[hit.toLowerCase()];
    if (!e) return null;
    if (e.cs) {
      var forms = [e.term].concat(e.match || []);
      if (forms.indexOf(hit) === -1) return null;
    }
    return e;
  }

  // ── linking ──────────────────────────────────────────────────────────────
  function skipSelector() { return BASE_SKIP.concat(CFG.skip).join(','); }

  function resolveScope() {
    for (var i = 0; i < CFG.scope.length; i++) {
      var el = document.querySelector(CFG.scope[i]);
      if (el) return el;
    }
    return document.body;
  }

  /* The sentinel is a CHILD, deliberately.
   *
   * A kit-format player does `mvBody.innerHTML = html` — the scope element
   * itself survives, only its children are replaced. An attribute on the scope
   * would therefore outlive the swap and make this read "already linked"
   * forever. A child is erased by the swap, which is exactly the signal we
   * want, and costs one `:scope >` query per observer wake.
   */
  function isLinked(scope) { return !!scope.querySelector(':scope > [data-dg-mark]'); }

  function mark(scope) {
    var m = document.createElement('span');
    m.className = 'dg-ui';
    m.setAttribute('data-dg-mark', '');
    m.hidden = true;
    scope.appendChild(m);
  }

  function link(root) {
    if (!INDEX) return 0;
    var scope = root || resolveScope();
    if (!scope) return 0;

    LINKING = true;
    var made = 0;
    try {
      /* `used` is derived from the DOM, never carried in a JS variable.
       *
       * This is what makes a repeat pass a no-op instead of a corruption.
       * Chips already placed are inside .dg-chip, which the walker skips — so a
       * fresh in-memory set would believe every term unspent, miss the first
       * occurrence because it is now hidden inside a chip, and link the SECOND
       * one. Run it a few more times and the whole page ends up marked.
       */
      var used = Object.create(null);
      var existing = scope.querySelectorAll('.dg-chip[data-dg-term]');
      for (var i = 0; i < existing.length; i++) used[existing[i].getAttribute('data-dg-term')] = 1;

      var skip = skipSelector();
      var walker = document.createTreeWalker(scope, NodeFilter.SHOW_TEXT, {
        acceptNode: function (node) {
          if (!node.nodeValue || !node.nodeValue.trim()) return NodeFilter.FILTER_REJECT;
          var p = node.parentElement;
          if (!p || p.closest(skip)) return NodeFilter.FILTER_REJECT;
          return NodeFilter.FILTER_ACCEPT;
        },
      });

      // Collect before mutating: replacing a node under a live walker loses it.
      var nodes = [];
      var n;
      while ((n = walker.nextNode())) nodes.push(n);
      for (var j = 0; j < nodes.length; j++) made += linkTextNode(nodes[j], used);

      if (!isLinked(scope)) mark(scope);
      PASSES++;
    } finally {
      LINKING = false;
    }
    return made;
  }

  function linkTextNode(node, used) {
    var text = node.nodeValue;
    var frag = null, last = 0, made = 0, m;
    INDEX.re.lastIndex = 0;
    while ((m = INDEX.re.exec(text)) !== null) {
      var entry = resolve(m[1]);
      if (!entry || used[entry.term]) continue;
      used[entry.term] = 1;
      if (!frag) frag = document.createDocumentFragment();
      if (m.index > last) frag.appendChild(document.createTextNode(text.slice(last, m.index)));
      frag.appendChild(makeChip(entry, m[0]));
      last = m.index + m[0].length;
      made++;
    }
    if (!frag) return 0;
    if (last < text.length) frag.appendChild(document.createTextNode(text.slice(last)));
    node.parentNode.replaceChild(frag, node);
    return made;
  }

  function makeChip(entry, surface) {
    var b = document.createElement('button');
    b.type = 'button';
    b.className = 'dg-chip';
    b.textContent = surface;          // keep the author's casing and plural
    b.setAttribute('data-dg-term', entry.term);
    b.setAttribute('aria-expanded', 'false');
    b.setAttribute('title', entry.short || entry.term);
    return b;
  }

  // ── popover ──────────────────────────────────────────────────────────────
  function el(tag, cls, text) {
    var e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text != null) e.textContent = text;
    return e;
  }

  function popNode() {
    var p = document.getElementById('dgPop');
    if (!p) {
      p = el('div', 'dg-ui dg-pop');
      p.id = 'dgPop';
      p.addEventListener('click', function (e) { e.stopPropagation(); });
      document.body.appendChild(p);
    }
    return p;
  }

  function openPop(chip, entry) {
    if (openChip === chip) { closePop(); return; }
    closePop();
    var p = popNode();
    p.textContent = '';
    p.appendChild(el('div', 'dg-pop-t', entry.term));
    if (entry.short) p.appendChild(el('div', 'dg-pop-s', entry.short));
    if (entry.long) p.appendChild(el('div', 'dg-pop-l', entry.long));

    if (entry.see && entry.see.length) {
      var row = el('div', 'dg-pop-see');
      entry.see.forEach(function (t) {
        var b = el('button', 'dg-pop-ref', t);
        b.type = 'button';
        b.addEventListener('click', function () { openPanel(t); });
        row.appendChild(b);
      });
      p.appendChild(row);
    }

    var more = el('button', 'dg-pop-more', 'All terms \u2192');
    more.type = 'button';
    more.addEventListener('click', function () { openPanel(entry.term); });
    p.appendChild(more);

    openChip = chip;
    chip.setAttribute('aria-expanded', 'true');
    p.classList.add('dg-open');
    place(p, chip);

    // A scroll moves the anchor out from under a fixed popover; close instead
    // of chasing it.
    global.addEventListener('scroll', closePop, { passive: true, once: true });
  }

  function place(p, chip) {
    var r = chip.getBoundingClientRect();
    var w = p.offsetWidth || 320, h = p.offsetHeight || 120;
    var left = Math.min(Math.max(12, r.left), Math.max(12, global.innerWidth - w - 12));
    var top = r.bottom + 8;
    if (top + h > global.innerHeight - 12) top = Math.max(12, r.top - h - 8);
    p.style.left = left + 'px';
    p.style.top = top + 'px';
  }

  function closePop() {
    var p = document.getElementById('dgPop');
    if (p) p.classList.remove('dg-open');
    if (openChip) openChip.setAttribute('aria-expanded', 'false');
    openChip = null;
  }

  // ── panel ────────────────────────────────────────────────────────────────
  function buildPanel() {
    if (document.getElementById('dgPanel')) return;

    var back = el('div', 'dg-ui dg-backdrop');
    back.id = 'dgBackdrop';
    back.addEventListener('click', closePanel);

    var panel = el('aside', 'dg-ui dg-panel');
    panel.id = 'dgPanel';
    panel.setAttribute('role', 'dialog');
    panel.setAttribute('aria-modal', 'true');
    panel.setAttribute('aria-label', CFG.title);

    var close = el('button', 'dg-panel-x', '\u2715');
    close.type = 'button';
    close.setAttribute('aria-label', 'Close the glossary');
    close.addEventListener('click', closePanel);

    var head = el('div', 'dg-panel-head');
    head.appendChild(el('h2', 'dg-panel-h', CFG.title));
    if (CFG.subtitle) head.appendChild(el('div', 'dg-panel-sub', CFG.subtitle));

    var search = document.createElement('input');
    search.type = 'search';
    search.className = 'dg-search';
    search.id = 'dgSearch';
    search.placeholder = 'Filter terms\u2026';
    search.autocomplete = 'off';
    search.addEventListener('input', function () { filter(this.value); });
    head.appendChild(search);

    var list = el('div', 'dg-list');
    list.id = 'dgList';
    (CORPUS.glossary || []).forEach(function (g) {
      var row = el('div', 'dg-term');
      row.setAttribute('data-dg-key', g.term.toLowerCase());
      row.appendChild(el('span', 'dg-term-t', g.term));
      if (g.short) row.appendChild(el('span', 'dg-term-s', g.short));
      if (g.long) row.appendChild(el('span', 'dg-term-l', g.long));
      list.appendChild(row);
    });
    var empty = el('div', 'dg-empty', 'No term matches that.');
    empty.id = 'dgEmpty';
    empty.hidden = true;
    list.appendChild(empty);

    panel.appendChild(close);
    panel.appendChild(head);
    panel.appendChild(list);
    document.body.appendChild(back);
    document.body.appendChild(panel);
  }

  function openPanel(term) {
    buildPanel();
    closePop();
    var panel = document.getElementById('dgPanel');
    var back = document.getElementById('dgBackdrop');
    panel.classList.add('dg-open');
    back.classList.add('dg-open');
    document.documentElement.classList.add('dg-locked');

    var search = document.getElementById('dgSearch');
    search.value = '';
    filter('');
    if (term) {
      var row = document.querySelector('.dg-term[data-dg-key="' + cssEscape(String(term).toLowerCase()) + '"]');
      if (row) {
        row.classList.add('dg-hit');
        if (row.scrollIntoView) row.scrollIntoView({ block: 'center' });
      }
    } else if (search.focus) {
      search.focus();
    }
  }

  function closePanel() {
    var panel = document.getElementById('dgPanel');
    var back = document.getElementById('dgBackdrop');
    if (panel) panel.classList.remove('dg-open');
    if (back) back.classList.remove('dg-open');
    document.documentElement.classList.remove('dg-locked');
    var hit = document.querySelector('.dg-term.dg-hit');
    if (hit) hit.classList.remove('dg-hit');
  }

  function panelOpen() {
    var p = document.getElementById('dgPanel');
    return !!(p && p.classList.contains('dg-open'));
  }

  function filter(q) {
    var list = document.getElementById('dgList');
    if (!list) return;
    var needle = (q || '').trim().toLowerCase();
    var rows = list.querySelectorAll('.dg-term');
    var shown = 0;
    for (var i = 0; i < rows.length; i++) {
      var hit = !needle || rows[i].textContent.toLowerCase().indexOf(needle) !== -1;
      rows[i].hidden = !hit;
      if (hit) shown++;
    }
    document.getElementById('dgEmpty').hidden = shown > 0;
  }

  function cssEscape(s) { return s.replace(/["\\]/g, '\\$&'); }

  // ── chrome ───────────────────────────────────────────────────────────────
  /* Adopt the host's own top bar when it has one, so the opener looks native
   * and no course markup has to be edited; fall back to a floating button.
   */
  function buildOpener() {
    var label = '\u25EB';
    var sel = CFG.chrome && CFG.chrome.topbar;
    var anchor = sel && document.querySelector(sel);
    var b = el('button', '', label);
    b.type = 'button';
    b.id = 'dgOpen';
    b.setAttribute('aria-label', CFG.title + ' \u2014 press ' + CFG.shortcut);
    b.setAttribute('title', CFG.title + ' (' + CFG.shortcut + ')');
    b.addEventListener('click', function (e) { e.stopPropagation(); openPanel(); });

    if (anchor) {
      b.className = anchor.className + ' dg-adopted';
      anchor.parentNode.insertBefore(b, anchor);
    } else {
      b.className = 'dg-ui dg-fab';
      document.body.appendChild(b);
    }
  }

  // ── observer ─────────────────────────────────────────────────────────────
  function ours(node) {
    var e = node && (node.nodeType === 1 ? node : node.parentElement);
    if (!e || !e.closest) return false;
    return !!e.closest('.dg-ui,.dg-chip,[data-dg-mark],.wt,[data-wt]' +
      (CFG.skip.length ? ',' + CFG.skip.join(',') : ''));
  }

  /* Dropping our own records is not politeness, it is required. The walkthrough
   * runtime types a character every 16ms while a scenario plays; without this
   * filter each of those would schedule a full tree walk.
   */
  function relevant(records) {
    for (var i = 0; i < records.length; i++) {
      var r = records[i];
      if (ours(r.target)) continue;
      if (r.type !== 'childList') continue;
      var added = r.addedNodes, any = false;
      for (var j = 0; j < added.length; j++) { if (!ours(added[j])) { any = true; break; } }
      if (any || (!added.length && r.removedNodes.length)) return true;
    }
    return false;
  }

  function tick() {
    PENDING = null;
    if (openChip && !openChip.isConnected) closePop();
    var scope = resolveScope();
    if (scope && !isLinked(scope)) link(scope);
  }

  function observe() {
    if (!global.MutationObserver || !document.body) return;
    new MutationObserver(function (records) {
      if (LINKING || PENDING) return;
      if (!relevant(records)) return;
      PENDING = setTimeout(tick, 60);
    }).observe(document.body, { childList: true, subtree: true });
  }

  // ── keyboard ─────────────────────────────────────────────────────────────
  /* Capture phase, because host players bind Escape too — ultimate-context-eng
   * sends the reader back to the landing page on Escape. Ours must win and stop
   * there while our own UI is open.
   */
  function keys() {
    document.addEventListener('keydown', function (e) {
      var t = e.target || {};
      var typing = /^(INPUT|TEXTAREA|SELECT)$/.test(t.tagName || '') || t.isContentEditable;

      if (e.key === 'Escape') {
        if (panelOpen()) { closePanel(); e.stopPropagation(); e.preventDefault(); return; }
        if (openChip) { closePop(); e.stopPropagation(); e.preventDefault(); return; }
        return;
      }
      if (!typing && !e.metaKey && !e.ctrlKey && !e.altKey &&
          e.key && e.key.toLowerCase() === CFG.shortcut) {
        openPanel();
        e.stopPropagation();
        e.preventDefault();
      }
    }, true);
  }

  // ── boot ─────────────────────────────────────────────────────────────────
  function start() {
    if (started || !CORPUS) return;
    started = true;
    buildPanel();
    buildOpener();
    keys();

    // One delegated listener rather than one per chip: chips are rebuilt on
    // every module change, and re-binding 160 closures each time is churn.
    document.addEventListener('click', function (e) {
      var chip = e.target && e.target.closest && e.target.closest('.dg-chip');
      if (chip) {
        e.stopPropagation();
        var entry = INDEX && INDEX.byForm[chip.getAttribute('data-dg-term').toLowerCase()];
        if (entry) openPop(chip, entry);
        return;
      }
      closePop();
    });
    global.addEventListener('resize', closePop);

    link();
    observe();
  }

  global.DG = {
    configure: function (cfg) {
      cfg = cfg || {};
      if (cfg.scope) CFG.scope = cfg.scope;
      if (cfg.skip) CFG.skip = cfg.skip;
      if (cfg.chrome) CFG.chrome = cfg.chrome;
      if (cfg.shortcut) CFG.shortcut = cfg.shortcut;
      if (cfg.title) CFG.title = cfg.title;
      if (cfg.subtitle) CFG.subtitle = cfg.subtitle;
    },
    register: function (corpus) { CORPUS = corpus; INDEX = buildIndex(corpus); },
    start: start,
    link: link,
    open: openPanel,
    close: function () { closePanel(); closePop(); },
    state: function () {
      return {
        passes: PASSES,
        chips: document.querySelectorAll('.dg-chip').length,
        terms: CORPUS ? (CORPUS.glossary || []).length : 0,
        scope: (function () { var s = resolveScope(); return s ? (s.id || s.tagName.toLowerCase()) : null; })(),
        skip: skipSelector(),
      };
    },
  };
})(typeof window !== 'undefined' ? window : this);
