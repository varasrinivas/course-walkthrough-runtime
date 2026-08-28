/* Walkthrough runtime — dependency-free port of the priorauth-sdd-course
   walkthrough widget (walkthrough/src/components/*.jsx).

   Scenarios are data. A scenario is stepped through one step at a time; each
   step pairs intent (narrative + YOU DO + CLAUDE'S MOVE) with evidence (a
   replayed terminal and a before/after state panel).

   Usage in a page:
     <div data-wt="kg-147-files"></div>
     <script>WT.register([ ...scenarios... ]); WT.mountAll();</script>

   Mounting re-runs under a MutationObserver, because the kit-format course
   players replace their content wrapper's innerHTML on every module change.

   Schema (see README.md for the full reference):
     scenario { id, badge, color, time, title, spec, intro, provenance, steps[] }
     step     { title, narrative[], youDo, claudeSays, terminal[], state }
     terminal line { kind: prompt|claude|tool|out|out-pass|out-fail|gate, text }
     state    { label, before:{title,view}, after:{title,view} }
     view     json | spec | rows | diff | tests | note | stack
              | receipt | bars | window        (added for these courses)
*/
(function (global) {
  'use strict';

  var REDUCED = !!(global.matchMedia &&
    global.matchMedia('(prefers-reduced-motion: reduce)').matches);

  var LINE_DELAY = 420;   // ms between revealed lines
  var TYPE_SPEED = 16;    // ms per character on prompt lines
  var PROMPT_HOLD = 260;  // ms pause after a prompt line finishes typing

  var REGISTRY = {};

  /* ---------------------------------------------------------------- utils */

  function el(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text != null) n.textContent = text;
    return n;
  }

  function html(tag, cls, markup) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (markup != null) n.innerHTML = markup;
    return n;
  }

  function add(parent) {
    for (var i = 1; i < arguments.length; i++) {
      if (arguments[i]) parent.appendChild(arguments[i]);
    }
    return parent;
  }

  function num(n) {
    return typeof n === 'number' ? n.toLocaleString('en-US') : String(n);
  }

  /* Layer palette for receipt/window views, in canonical layer order. */
  var LAYER_COLORS = ['#33506B', '#1F7A4D', '#B45309', '#7A3E9D', '#A63A3A',
                      '#2D7D8A', '#8A6D2F'];

  /* ---------------------------------------------------------------- views */

  function jsonView(v) {
    var pre = el('pre', 'json');
    var keys = Object.keys(v.data);
    var hl = v.highlight || [];
    pre.appendChild(document.createTextNode('{'));
    keys.forEach(function (k, i) {
      var row = el('div', 'json-row' + (hl.indexOf(k) >= 0 ? ' hl' : ''));
      var val = v.data[k];
      var isNum = typeof val === 'number';
      row.appendChild(document.createTextNode('  '));
      add(row, el('span', 'jk', '"' + k + '"'));
      row.appendChild(document.createTextNode(': '));
      add(row, el('span', isNum ? 'jn' : 'js', isNum ? num(val) : '"' + val + '"'));
      if (i < keys.length - 1) row.appendChild(document.createTextNode(','));
      pre.appendChild(row);
    });
    pre.appendChild(document.createTextNode('}'));
    return pre;
  }

  function specView(v) {
    var box = el('div', 'spec-mini');
    var bar = el('div', 'spec-mini-bar');
    add(bar, el('span', null, v.id),
             el('span', 'stamp stamp-' + String(v.status).toLowerCase().replace(/[^a-z]/g, ''), v.status));
    var body = el('div', 'spec-mini-body');
    (v.rows || []).forEach(function (r) {
      var row = el('div', 'spec-mini-row');
      add(row, el('span', 'smk', r[0]), html('span', 'smv', r[1]));
      body.appendChild(row);
    });
    return add(box, bar, body);
  }

  function rowsView(v) {
    var t = el('table', 'rows');
    var thead = el('thead'), htr = el('tr');
    (v.columns || []).forEach(function (c) { add(htr, el('th', null, c)); });
    add(thead, htr);
    var tb = el('tbody');
    (v.rows || []).forEach(function (r) {
      var tr = el('tr', r.new ? 'row-new' : (r.tone ? 'row-' + r.tone : null));
      (r.cells || []).forEach(function (c) { add(tr, html('td', null, String(c))); });
      add(tb, tr);
    });
    return add(t, thead, tb);
  }

  function diffView(v) {
    var box = el('div', 'diff');
    add(box, el('div', 'diff-file', v.file));
    var pre = el('pre');
    (v.lines || []).forEach(function (l) {
      add(pre, el('div', 'dl dl-' + l[0], l[1]));
    });
    return add(box, pre);
  }

  function testsView(v) {
    var pass = !v.failures;
    var box = el('div', 'tests ' + (pass ? 'tests-pass' : 'tests-fail'));
    add(box, el('div', 'tests-big', v.big || (pass ? 'BUILD SUCCESS' : 'BUILD FAILURE')));
    if (v.run != null) {
      add(box, el('div', 'tests-nums',
        'Tests run: ' + v.run + ' · Failures: ' + (v.failures || 0) + ' · Errors: 0'));
    }
    if (v.note) add(box, html('div', 'tests-note', v.note));
    return box;
  }

  /* A horizontal stacked bar shared by the receipt and window views. */
  function stackedBar(layers, total, highlight) {
    var bar = el('div', 'lbar');
    layers.forEach(function (l, i) {
      var seg = el('div', 'lseg' + (highlight && highlight.indexOf(l.label) >= 0 ? ' lseg-hl' : ''));
      seg.style.width = (total ? (l.tokens / total) * 100 : 0) + '%';
      seg.style.background = l.color || LAYER_COLORS[i % LAYER_COLORS.length];
      seg.title = l.label + ' · ' + num(l.tokens);
      add(bar, seg);
    });
    return bar;
  }

  /* receipt — the Token Lens: layered bar, itemised lines, verdict stamp. */
  function receiptView(v) {
    var box = el('div', 'receipt');
    var head = el('div', 'rc-head');
    add(head, el('span', 'rc-mode', (v.mode || '') + ' · token receipt'));
    if (v.question) add(head, el('span', 'rc-q', v.question));
    add(box, head);

    var layers = v.layers || [];
    var sum = layers.reduce(function (a, l) { return a + l.tokens; }, 0);
    add(box, stackedBar(layers, sum, v.highlight));

    var list = el('div', 'rc-lines');
    layers.forEach(function (l, i) {
      var row = el('div', 'rc-line' + (v.highlight && v.highlight.indexOf(l.label) >= 0 ? ' hl' : ''));
      var sw = el('span', 'rc-sw');
      sw.style.background = l.color || LAYER_COLORS[i % LAYER_COLORS.length];
      add(row, sw, el('span', 'rc-k', l.label), el('span', 'rc-dots'),
               el('span', 'rc-v', num(l.tokens)));
      add(list, row);
    });
    add(box, list);

    var tot = el('div', 'rc-total');
    add(tot, el('span', 'rc-k', 'Input total'), el('span', 'rc-dots'),
             el('span', 'rc-v', num(v.inputTotal != null ? v.inputTotal : sum)));
    add(box, tot);

    if (v.output != null) {
      var o = el('div', 'rc-line rc-sub');
      add(o, el('span', 'rc-k', 'Output'), el('span', 'rc-dots'), el('span', 'rc-v', num(v.output)));
      add(box, o);
    }

    var meta = el('div', 'rc-meta');
    if (v.cost) add(meta, el('span', 'rc-chip', v.cost));
    if (v.cacheRead) add(meta, el('span', 'rc-chip', 'cache read ' + v.cacheRead));
    if (v.latency) add(meta, el('span', 'rc-chip', v.latency));
    if (meta.childNodes.length) add(box, meta);

    if (v.verdict) {
      var vk = String(v.verdict).toLowerCase();
      var label = vk === 'verified' ? '✓ Correct'
                : vk === 'failed' ? '✕ FAILED — savings void'
                : '– Ungraded';
      var stamp = el('div', 'rc-verdict rcv-' + vk);
      add(stamp, el('span', 'stamp stamp-' + (vk === 'verified' ? 'verified' : vk === 'failed' ? 'refused' : 'draft'), label));
      if (v.verdictNote) add(stamp, el('span', 'rcv-note', v.verdictNote));
      add(box, stamp);
    }
    return box;
  }

  /* bars — comparative totals across arms/strategies. */
  function barsView(v) {
    var box = el('div', 'bars');
    var items = v.items || [];
    var max = v.max || items.reduce(function (a, i) { return Math.max(a, i.value); }, 0);
    items.forEach(function (it) {
      var row = el('div', 'bars-row' + (it.tone ? ' bt-' + it.tone : ''));
      add(row, el('span', 'bars-k', it.label));
      var track = el('div', 'bars-track');
      var fill = el('div', 'bars-fill');
      fill.style.width = (max ? (it.value / max) * 100 : 0) + '%';
      add(track, fill);
      add(row, track, el('span', 'bars-v', num(it.value) + (v.unit ? ' ' + v.unit : '')));
      if (it.note) add(row, el('span', 'bars-note', it.note));
      add(box, row);
    });
    return box;
  }

  /* window — a context window's layer composition against its capacity. */
  function windowView(v) {
    var box = el('div', 'cwin');
    var layers = v.layers || [];
    var used = v.used != null ? v.used : layers.reduce(function (a, l) { return a + l.tokens; }, 0);
    var cap = v.capacity || used;

    var head = el('div', 'cwin-head');
    add(head, el('span', 'cwin-k', v.label || 'context window'),
              el('span', 'cwin-v', num(used) + ' / ' + num(cap) +
                 ' (' + Math.round((used / cap) * 100) + '% full)'));
    add(box, head);

    var track = el('div', 'cwin-track');
    var used_pct = Math.min(100, (used / cap) * 100);
    var inner = el('div', 'cwin-used');
    inner.style.width = used_pct + '%';
    add(inner, stackedBar(layers, used, v.highlight));
    add(track, inner);
    add(box, track);

    var legend = el('div', 'cwin-legend');
    layers.forEach(function (l, i) {
      var it = el('span', 'cwin-item' + (v.highlight && v.highlight.indexOf(l.label) >= 0 ? ' hl' : ''));
      var sw = el('span', 'rc-sw');
      sw.style.background = l.color || LAYER_COLORS[i % LAYER_COLORS.length];
      add(it, sw, el('span', null, l.label + ' ' + num(l.tokens)));
      add(legend, it);
    });
    add(box, legend);
    if (v.note) add(box, html('div', 'cwin-note', v.note));
    return box;
  }

  function renderView(v) {
    if (!v) return null;
    switch (v.type) {
      case 'json':    return jsonView(v);
      case 'spec':    return specView(v);
      case 'rows':    return rowsView(v);
      case 'diff':    return diffView(v);
      case 'tests':   return testsView(v);
      case 'receipt': return receiptView(v);
      case 'bars':    return barsView(v);
      case 'window':  return windowView(v);
      case 'note':    return html('div', 'state-note', v.text);
      case 'stack':
        var box = el('div', 'state-stack');
        (v.views || []).forEach(function (sub) {
          var r = renderView(sub);
          if (r) add(box, add(el('div'), r));
        });
        return box;
      default: return null;
    }
  }

  /* ------------------------------------------------------------- terminal */

  /* Replays a session: lines appear in order, prompt lines type out. */
  function Terminal(lines) {
    var shown = 0, typed = 0, skipped = REDUCED, timer = null;

    var root = el('div', 'term');
    var bar = el('div', 'term-bar');
    var dots = el('span', 'term-dots');
    add(dots, el('i'), el('i'), el('i'));
    var title = el('span', 'term-title', 'claude — session replay');
    var actions = el('span', 'term-actions');
    var btn = el('button');
    btn.type = 'button';
    add(actions, btn);
    add(bar, dots, title, actions);
    var body = el('div', 'term-body');
    add(root, bar, body);

    function clear() { if (timer) { clearTimeout(timer); timer = null; } }

    function paint() {
      body.textContent = '';
      var visible = skipped ? lines.length : Math.min(lines.length, shown + 1);
      for (var i = 0; i < visible; i++) {
        var line = lines[i];
        var isCurrent = !skipped && i === shown;
        var text = (line.kind === 'prompt' && isCurrent) ? line.text.slice(0, typed) : line.text;
        var row = el('div', 'tl tl-' + line.kind +
          (isCurrent && line.kind !== 'prompt' ? ' tl-appear' : ''));
        if (line.kind === 'prompt') add(row, el('span', 'tl-caret', '›'));
        if (line.kind === 'claude') add(row, el('span', 'tl-who', '⏺'));
        if (line.kind === 'tool')   add(row, el('span', 'tl-who tl-who-tool', '⚒'));
        var pre = el('pre', null, text);
        if (line.kind === 'prompt' && isCurrent && typed < line.text.length) {
          add(pre, el('span', 'cursor'));
        }
        add(row, pre);
        add(body, row);
      }
      body.scrollTop = body.scrollHeight;
      var done = skipped || shown >= lines.length;
      btn.textContent = done ? 'replay ↺' : 'show all';
    }

    function tick() {
      clear();
      if (skipped || shown >= lines.length) { paint(); return; }
      var line = lines[shown];
      if (line.kind === 'prompt' && typed < line.text.length) {
        timer = setTimeout(function () { typed++; paint(); tick(); }, TYPE_SPEED);
      } else {
        timer = setTimeout(function () {
          shown++; typed = 0; paint(); tick();
        }, line.kind === 'prompt' ? PROMPT_HOLD : LINE_DELAY);
      }
      paint();
    }

    btn.addEventListener('click', function () {
      var done = skipped || shown >= lines.length;
      if (done) { shown = 0; typed = 0; skipped = false; }
      else { skipped = true; }
      tick();
    });

    tick();
    return { el: root, destroy: clear };
  }

  /* ---------------------------------------------------------- state panel */

  function StatePanel(state) {
    var side = 'before';
    var single = !state.after;

    var root = el('div', 'state');
    var head = el('div', 'state-head');
    add(head, el('span', 'state-label', state.label || ''));

    var beforeBtn, afterBtn;
    if (!single) {
      var toggle = el('span', 'ba-toggle');
      toggle.setAttribute('role', 'tablist');
      beforeBtn = el('button', 'on', 'Before');
      afterBtn = el('button', null, 'After');
      beforeBtn.type = afterBtn.type = 'button';
      beforeBtn.addEventListener('click', function () { show('before'); });
      afterBtn.addEventListener('click', function () { show('after'); });
      add(toggle, beforeBtn, afterBtn);
      add(head, toggle);
    }

    var body = el('div', 'state-body sb-before');
    var apply = el('button', 'apply', 'Apply this step — see the after state →');
    apply.type = 'button';
    apply.addEventListener('click', function () { show('after'); });

    add(root, head, body);
    if (!single) add(root, apply);

    function show(next) {
      side = next;
      body.className = 'state-body sb-' + side;
      body.textContent = '';
      var cur = side === 'before' ? state.before : state.after;
      if (cur.title) add(body, el('div', 'state-title st-' + side, cur.title));
      var v = renderView(cur.view);
      if (v) add(body, v);
      if (!single) {
        beforeBtn.className = side === 'before' ? 'on' : '';
        afterBtn.className = side === 'after' ? 'on on-after' : '';
        apply.style.display = side === 'before' ? '' : 'none';
      }
    }

    show('before');
    return { el: root };
  }

  /* ----------------------------------------------------------- walkthrough */

  function provenanceEl(p) {
    if (!p) return null;
    var measured = p.kind === 'measured';
    var box = el('span', 'wt-prov wt-prov-' + (measured ? 'measured' : 'illustrative'));
    add(box, el('span', 'wt-prov-k', measured ? 'MEASURED' : 'ILLUSTRATIVE'));
    if (p.source) add(box, el('span', 'wt-prov-v', p.source));
    return box;
  }

  function renderScenario(host, scenario, opts) {
    opts = opts || {};
    var embedded = opts.embedded !== false;
    var stepIdx = 0;
    var live = [];   // teardown handles for the current step

    host.textContent = '';
    var theme = host.getAttribute('data-wt-theme') || opts.theme || '';
    host.className = 'wt' + (embedded ? ' wt-embed' : '') + (theme === 'dark' ? ' wt-dark' : '');
    host.style.setProperty('--scen-color', scenario.color || '#33506B');

    if (embedded) {
      var eh = el('div', 'wt-embed-head');
      add(eh, el('span', 'weh-badge', scenario.badge || 'WALKTHROUGH'),
              el('span', 'weh-title', scenario.title + ' — walk it step by step'));
      var prov = provenanceEl(scenario.provenance);
      if (prov) add(eh, prov);
      if (scenario.time) add(eh, el('span', 'weh-time', scenario.time));
      add(host, eh);
    } else {
      var sh = el('div', 'scen-head');
      var meta = el('div', 'scen-meta');
      add(meta, el('span', 'scen-badge', scenario.badge || 'WALKTHROUGH'));
      if (scenario.spec) add(meta, el('span', 'scen-spec', scenario.spec));
      var p2 = provenanceEl(scenario.provenance);
      if (p2) add(meta, p2);
      add(sh, meta, el('h2', null, scenario.title));
      if (scenario.intro) add(sh, html('p', 'scen-intro', scenario.intro));
      add(host, sh);
    }

    var progress = el('div', 'progress');
    var stepWrap = el('div');
    var nav = el('div', 'stepnav');
    var prevBtn = el('button', null, '← Previous');
    var nextBtn = el('button', 'primary', 'Next step →');
    prevBtn.type = nextBtn.type = 'button';
    add(nav, prevBtn, nextBtn);
    add(host, progress, stepWrap, nav);

    if (embedded && scenario.foot) {
      add(host, html('div', 'wt-embed-foot', scenario.foot));
    }

    prevBtn.addEventListener('click', function () { go(stepIdx - 1); });
    nextBtn.addEventListener('click', function () { go(stepIdx + 1); });

    host.setAttribute('tabindex', '-1');
    host.addEventListener('keydown', function (e) {
      if (e.key === 'ArrowRight') { go(stepIdx + 1); }
      else if (e.key === 'ArrowLeft') { go(stepIdx - 1); }
    });

    function teardown() {
      live.forEach(function (h) { if (h && h.destroy) h.destroy(); });
      live = [];
    }

    function go(i) {
      if (i < 0 || i >= scenario.steps.length) return;
      stepIdx = i;
      render();
    }

    function render() {
      teardown();
      var step = scenario.steps[stepIdx];
      var last = stepIdx === scenario.steps.length - 1;

      progress.textContent = '';
      scenario.steps.forEach(function (st, i) {
        var d = el('button', 'prog-dot' + (i === stepIdx ? ' on' : '') + (i < stepIdx ? ' done' : ''));
        d.type = 'button';
        d.title = st.title;
        d.setAttribute('aria-label', 'Step ' + (i + 1) + ': ' + st.title);
        add(d, el('span', null, String(i + 1)));
        d.addEventListener('click', function () { go(i); });
        add(progress, d);
      });
      add(progress, el('span', 'prog-label',
        'Step ' + (stepIdx + 1) + ' of ' + scenario.steps.length + ' — ' + step.title));

      stepWrap.textContent = '';
      var sec = el('section', 'step');

      var copy = el('div', 'step-copy');
      var h3 = el('h3');
      add(h3, el('span', 'step-n', 'STEP ' + (stepIdx + 1)));
      h3.appendChild(document.createTextNode(step.title));
      add(copy, h3);
      (step.narrative || []).forEach(function (p) { add(copy, html('p', null, p)); });
      if (step.youDo) {
        var yd = el('div', 'youdo');
        add(yd, el('div', 'youdo-k', 'YOU DO'), html('div', 'youdo-v', step.youDo));
        add(copy, yd);
      }
      if (step.claudeSays) {
        var cs = el('div', 'claudesays');
        add(cs, el('div', 'youdo-k cs-k', "CLAUDE'S MOVE"), html('div', 'youdo-v', step.claudeSays));
        add(copy, cs);
      }
      add(sec, copy);

      var screens = el('div', 'step-screens');
      if (step.terminal && step.terminal.length) {
        var t = Terminal(step.terminal);
        live.push(t);
        add(screens, t.el);
      }
      if (step.state) {
        add(screens, StatePanel(step.state).el);
      }
      if (step.source) {
        var cite = el('div', 'wt-cite');
        add(cite, el('span', 'wt-cite-k', 'MEASURED'), el('span', null, step.source));
        add(screens, cite);
      }
      add(sec, screens);
      add(stepWrap, sec);

      prevBtn.disabled = stepIdx === 0;
      nextBtn.disabled = last;
      nextBtn.textContent = last ? 'Walkthrough complete' : 'Next step →';
    }

    render();
    return { destroy: teardown };
  }

  /* --------------------------------------------------------------- mounts */

  function mountAll(root) {
    var scope = root || document;
    var nodes = scope.querySelectorAll('[data-wt]:not([data-wt-mounted])');
    for (var i = 0; i < nodes.length; i++) {
      var node = nodes[i];
      var sc = REGISTRY[node.getAttribute('data-wt')];
      if (!sc) continue;
      node.setAttribute('data-wt-mounted', '1');
      renderScenario(node, sc, { embedded: true });
    }
  }

  /* The course players swap innerHTML on module change, so watch for new
     mount points rather than relying on a single pass at load. */
  var pending = null;
  function observe() {
    if (!global.MutationObserver || !document.body) return;
    new MutationObserver(function () {
      if (pending) return;
      pending = setTimeout(function () { pending = null; mountAll(); }, 60);
    }).observe(document.body, { childList: true, subtree: true });
  }

  /* Standalone quick-reference page: every scenario behind a tab. */
  function standalone(host, ids) {
    var list = (ids && ids.length ? ids : Object.keys(REGISTRY))
      .map(function (id) { return REGISTRY[id]; })
      .filter(Boolean);
    if (!list.length) return;

    host.textContent = '';
    var tabs = el('div', 'wt-tabs');
    var stage = el('div', 'wt-stage');
    add(host, tabs, stage);
    var current = null;

    function open(sc, btn) {
      if (current && current.destroy) current.destroy();
      for (var i = 0; i < tabs.childNodes.length; i++) {
        tabs.childNodes[i].className = 'wt-tab';
      }
      btn.className = 'wt-tab on';
      btn.style.setProperty('--scen-color', sc.color || '#33506B');
      stage.textContent = '';
      var holder = el('div');
      add(stage, holder);
      current = renderScenario(holder, sc, { embedded: false });
    }

    list.forEach(function (sc, i) {
      var b = el('button', 'wt-tab');
      b.type = 'button';
      add(b, el('span', 'wt-tab-badge', sc.badge || ''), el('span', null, sc.title));
      b.style.setProperty('--scen-color', sc.color || '#33506B');
      b.addEventListener('click', function () { open(sc, b); });
      add(tabs, b);
      if (i === 0) setTimeout(function () { open(sc, b); }, 0);
    });
  }

  function register(scenarios) {
    (scenarios || []).forEach(function (s) { if (s && s.id) REGISTRY[s.id] = s; });
  }

  global.WT = {
    register: register,
    mountAll: mountAll,
    standalone: standalone,
    scenarios: REGISTRY
  };

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', function () { mountAll(); observe(); });
  } else {
    mountAll();
    observe();
  }
})(window);
