/* StreamShift Now Playing — shared overlay runtime */
(function () {
  'use strict';

  /* ── URL param helpers ─────────────────────────────────────────────────── */
  const _p = new URLSearchParams(window.location.search);
  function param(key, def)    { const v = _p.get(key); return v !== null ? v : def; }
  function paramNum(key, def) { return parseFloat(param(key, def)); }
  function paramBool(key, def){ const v = _p.get(key); if (v === null) return def; return v === '1' || v === 'true'; }

  window.NP_THEME = {
    accent:          '#' + param('accent', '3f94bf'),
    bgColor:         '#' + param('bg_color', '0a121c'),
    bgOpacity:       paramNum('bg', 88) / 100,
    blur:            paramNum('blur', 14),
    hideWhenStopped: paramBool('hide_stopped', false),
    textColor:       '#' + param('text', 'eef6ff'),
  };

  /* ── DOM helpers ───────────────────────────────────────────────────────── */
  function el(id)           { return document.getElementById(id); }
  function set(id, val)     { const e = el(id); if (e && e.textContent !== val) e.textContent = val; }
  function attr(id, a, val) { const e = el(id); if (e) e.setAttribute(a, val); }

  /* ── Time format ───────────────────────────────────────────────────────── */
  function fmt(s) {
    s = Math.max(0, Math.floor(s || 0));
    return Math.floor(s / 60) + ':' + String(s % 60).padStart(2, '0');
  }

  /* ── Hex → rgba ────────────────────────────────────────────────────────── */
  function hexRgba(hex, a) {
    const c = (hex || '#000').replace('#', '');
    const r = parseInt(c.slice(0,2), 16) || 0;
    const g = parseInt(c.slice(2,4), 16) || 0;
    const b = parseInt(c.slice(4,6), 16) || 0;
    return `rgba(${r},${g},${b},${a})`;
  }

  /* ── Apply CSS vars from theme ─────────────────────────────────────────── */
  function applyTheme() {
    const t = window.NP_THEME;
    const r = document.documentElement;
    r.style.setProperty('--accent',     t.accent);
    r.style.setProperty('--bg-color',   t.bgColor);
    r.style.setProperty('--bg-opacity', t.bgOpacity);
    r.style.setProperty('--blur',       t.blur + 'px');
    r.style.setProperty('--text-hi',    t.textColor);
    r.style.setProperty('--text-lo',    hexRgba(t.textColor, 0.60));
  }

  /* ════════════════════════════════════════════════════════════════════════
   * MARQUEE — smooth horizontal scroll for overflowing text
   * ════════════════════════════════════════════════════════════════════════ */
  const _marqueeState = new WeakMap();

  function setupMarquee(element) {
    if (!element) return;
    // Reset first so we can measure natural width
    element.style.transform = '';
    element.style.animation  = 'none';
    element.style.transition = 'none';

    requestAnimationFrame(() => {
      const overflow = element.scrollWidth - element.offsetWidth;
      if (overflow <= 4) {
        // fits — clear any running marquee
        _marqueeState.delete(element);
        element.style.transform = '';
        element.style.animation = '';
        return;
      }
      // Store target and start a rAF-driven marquee
      const SPEED    = 38;   // px/s
      const PAUSE_MS = 1800; // hold at each end
      const travel   = overflow;
      const duration = (travel / SPEED) * 1000; // ms

      _marqueeState.set(element, {
        travel,
        duration,
        pause: PAUSE_MS,
        phase: 'pause-start',
        phaseStart: performance.now(),
        x: 0,
      });
    });
  }

  function tickMarquees(now) {
    _marqueeState.forEach((state, elem) => {
      const elapsed = now - state.phaseStart;

      if (state.phase === 'pause-start') {
        if (elapsed >= state.pause) {
          state.phase = 'scroll-fwd';
          state.phaseStart = now;
        }
        // x stays 0
      } else if (state.phase === 'scroll-fwd') {
        const t = Math.min(elapsed / state.duration, 1);
        state.x = easeInOut(t) * state.travel;
        if (t >= 1) {
          state.phase = 'pause-end';
          state.phaseStart = now;
        }
      } else if (state.phase === 'pause-end') {
        if (elapsed >= state.pause) {
          state.phase = 'scroll-back';
          state.phaseStart = now;
        }
      } else if (state.phase === 'scroll-back') {
        const t = Math.min(elapsed / state.duration, 1);
        state.x = (1 - easeInOut(t)) * state.travel;
        if (t >= 1) {
          state.phase = 'pause-start';
          state.phaseStart = now;
          state.x = 0;
        }
      }

      elem.style.transform   = `translateX(${-state.x.toFixed(2)}px)`;
      elem.style.whiteSpace  = 'nowrap';
      elem.style.display     = 'inline-block';
    });
  }

  function easeInOut(t) {
    return t < 0.5 ? 2 * t * t : -1 + (4 - 2 * t) * t;
  }

  /* ════════════════════════════════════════════════════════════════════════
   * CIRCLE OVERLAY — SVG renderer split into static + dynamic layers
   * ════════════════════════════════════════════════════════════════════════ */
  let _circleLastTrack = null;

  function renderCircleStatic(state) {
    const svg = el('circle-svg');
    if (!svg) return;

    const t      = window.NP_THEME;
    const accent = t.accent;
    const dim    = hexRgba(accent, 0.16);
    const done   = hexRgba(accent, 0.88);

    const total = Math.max(1, state.queue_total || 1);
    const idx   = state.queue_index || 0;
    const cx = 150, cy = 150;
    const outerR = 132, outerW = 10;
    const innerR = 114, innerW = 7;
    const GAP    = Math.min(4, 280 / total);
    const SEG    = (360 - total * GAP) / total;

    function px(deg, r) { return cx + r * Math.cos(deg * Math.PI / 180); }
    function py(deg, r) { return cy + r * Math.sin(deg * Math.PI / 180); }
    function arc(startDeg, sweep, r) {
      const end = startDeg + sweep;
      const x1 = px(startDeg, r), y1 = py(startDeg, r);
      const x2 = px(end,      r), y2 = py(end,      r);
      const lg = sweep > 180 ? 1 : 0;
      return `M${x1.toFixed(2)},${y1.toFixed(2)} A${r},${r} 0 ${lg},1 ${x2.toFixed(2)},${y2.toFixed(2)}`;
    }

    let segs = '';
    for (let i = 0; i < total; i++) {
      const s = -90 + i * (SEG + GAP);
      const d = arc(s, SEG, outerR - outerW / 2);
      let color = dim;
      if (i < idx)  color = done;
      if (i === idx) color = accent;
      const cls = i === idx ? ' class="seg-active"' : '';
      segs += `<path d="${d}" stroke="${color}" stroke-width="${outerW}" fill="none"${cls}/>`;
    }

    const durStr = fmt(state.duration);
    const total2 = state.queue_total > 1 ? `${idx + 1} / ${total}` : '';

    svg.innerHTML =
      `<defs>` +
        `<filter id="glow" x="-20%" y="-20%" width="140%" height="140%">` +
          `<feGaussianBlur stdDeviation="3" result="blur"/>` +
          `<feMerge><feMergeNode in="blur"/><feMergeNode in="SourceGraphic"/></feMerge>` +
        `</filter>` +
      `</defs>` +
      /* outer ring bg track */
      `<circle cx="${cx}" cy="${cy}" r="${outerR - outerW/2}" fill="none" stroke="${hexRgba(accent, 0.06)}" stroke-width="${outerW + 2}"/>` +
      /* outer ring segments */
      segs +
      /* inner ring bg — full circle track */
      `<circle cx="${cx}" cy="${cy}" r="${innerR - innerW/2}" stroke="${hexRgba(accent, 0.10)}" stroke-width="${innerW}" fill="none"/>` +
      /* inner ring fill — dashoffset circle; rAF drives stroke-dashoffset for smooth motion */
      `<circle id="inner-fill" cx="${cx}" cy="${cy}" r="${innerR - innerW/2}" stroke="${accent}" stroke-width="${innerW}" fill="none" stroke-linecap="round" transform="rotate(-90 ${cx} ${cy})" filter="url(#glow)" style="stroke-dasharray:${(2*Math.PI*(innerR-innerW/2)).toFixed(2)};stroke-dashoffset:${(2*Math.PI*(innerR-innerW/2)).toFixed(2)}"/>` +
      /* centre icon — title/artist are HTML overlays below, so icon sits just above centre */
      `<text x="${cx}" y="${cy - 24}" text-anchor="middle" font-size="24" fill="${hexRgba(accent, 0.45)}">♪</text>` +
      /* duration */
      (durStr ? `<text x="${cx}" y="${cy + 44}" text-anchor="middle" font-size="9.5" fill="${hexRgba(accent, 0.4)}">${_esc(durStr)}</text>` : '') +
      /* track number */
      (total2 ? `<text x="${cx}" y="${cy + 58}" text-anchor="middle" font-size="9" fill="${hexRgba(accent, 0.28)}">${_esc(total2)}</text>` : '');

    _circleLastTrack = state.title;
  }

  function renderCircleDynamic(pos, duration) {
    const fill = el('inner-fill');
    if (!fill) return;
    const innerR = 114, innerW = 7;
    const circ = 2 * Math.PI * (innerR - innerW / 2);
    const pct = (duration > 0) ? Math.min(1, pos / duration) : 0;
    // stroke-dashoffset drives fill length — no trig needed each frame
    fill.style.strokeDashoffset = (circ * (1 - pct)).toFixed(4);
  }

  function _esc(s) {
    return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
  }

  /* ════════════════════════════════════════════════════════════════════════
   * API FETCH
   * ════════════════════════════════════════════════════════════════════════ */
  let _failCount  = 0;
  let _reloading  = false;
  const _FAIL_LIMIT = 10; // ~5 s at 500 ms default interval

  async function fetchState() {
    try {
      const r = await fetch('/api/state?_=' + Date.now(), { cache: 'no-store' });
      if (!r.ok) return null;
      _failCount = 0;
      return await r.json();
    } catch {
      _failCount++;
      if (_failCount >= _FAIL_LIMIT && !_reloading) {
        _reloading = true;
        setTimeout(() => window.location.reload(), 3000);
      }
      return null;
    }
  }

  /* ════════════════════════════════════════════════════════════════════════
   * MAIN LOOP
   * ════════════════════════════════════════════════════════════════════════ */
  let _latest      = null;   // last API response
  let _pollAt      = 0;      // timestamp of last poll
  let _lastTitle   = null;
  let _marqueeTitl = null;   // element currently marquee-d as title
  let _marqueeArt  = null;

  /* ── Smooth position accumulator ───────────────────────────────────────────
   * Instead of re-computing position from the server value on every frame
   * (which causes visible jumps every 500ms when the two clocks drift),
   * we advance _smoothPos in real time via rAF dt and only resync when the
   * server position is meaningfully different (seek, new track, etc.).
   * ──────────────────────────────────────────────────────────────────────── */
  let _smoothPos  = 0;
  let _lastRafNow = null;

  function _syncSmooth(serverPos, status) {
    if (status !== 'playing') { _smoothPos = serverPos; return; }
    // Resync only if genuinely out of range (seek or initial load)
    if (Math.abs(serverPos - _smoothPos) > 1.5) {
      _smoothPos = serverPos;
    }
    // Otherwise keep accumulating — avoids backward/forward jumps from poll jitter
  }

  function rafLoop(now) {
    requestAnimationFrame(rafLoop);

    // Advance smooth position by real wall-clock dt when playing
    if (_latest && _latest.status === 'playing') {
      if (_lastRafNow !== null) {
        const dt = (now - _lastRafNow) / 1000;
        const dur = _latest.duration || Infinity;
        _smoothPos = Math.min(_smoothPos + dt, dur);
      }
    }
    _lastRafNow = now;

    const pos = _smoothPos;

    /* progress bar — smooth at 60fps */
    const fill = el('now-progress-fill');
    if (fill && _latest && _latest.duration) {
      const w = (Math.min(1, pos / _latest.duration) * 100).toFixed(3);
      fill.style.width = w + '%';
    }

    /* position label */
    const posEl = el('now-position');
    if (posEl) {
      const t = fmt(pos);
      if (posEl.textContent !== t) posEl.textContent = t;
    }

    /* circle inner ring */
    if (_latest && el('circle-svg')) {
      renderCircleDynamic(pos, _latest.duration || 0);
    }

    /* marquee tick */
    tickMarquees(now);

    /* per-overlay rAF hook (e.g. vinyl progress ring) */
    if (_rafOpts && _rafOpts.onRaf) _rafOpts.onRaf(pos, _latest);
  }

  let _rafOpts = null;

  function onNewState(s, opts) {
    if (!s) return;

    const isStopped = s.status === 'stopped';
    const isPlaying = s.status === 'playing';

    /* hide/show root */
    const root = el('now-playing-root');
    const hide = isStopped && (opts.hideWhenStopped || window.NP_THEME.hideWhenStopped);
    if (root) root.classList.toggle('hidden', hide);

    /* track change */
    const trackChanged = s.title !== _lastTitle;
    if (trackChanged) {
      _lastTitle = s.title;
      _smoothPos = s.position || 0;   // hard reset on track change
      _lastRafNow = null;
      if (opts.onTrackChange) opts.onTrackChange(s);
    } else {
      _syncSmooth(s.position || 0, s.status);
    }

    /* text fields */
    set('now-title',    s.title  || '—');
    set('now-artist',   s.artist || '');
    set('now-duration', fmt(s.duration));

    /* marquee: recalculate after DOM update (skip if caller opted out) */
    if (!opts.noMarquee) {
      const titleEl  = el('now-title');
      const artistEl = el('now-artist');
      if (trackChanged || !_marqueeTitl) {
        if (titleEl)  setupMarquee(titleEl);
        if (artistEl) setupMarquee(artistEl);
        _marqueeTitl = titleEl;
        _marqueeArt  = artistEl;
      }
    }

    /* animated dot */
    const dot = el('now-dot');
    if (dot) dot.classList.toggle('paused', !isPlaying);

    /* circle: full redraw only when track changes or playlist position changes */
    if (el('circle-svg') && (trackChanged || s.queue_index !== (_latest && _latest.queue_index))) {
      renderCircleStatic(s);
    }

    if (opts.onUpdate) opts.onUpdate(s);
  }

  /* ════════════════════════════════════════════════════════════════════════
   * PUBLIC API
   * ════════════════════════════════════════════════════════════════════════ */
  // Startup probe — prime fail counter immediately if server is down so the
  // reload fires on the next polling tick rather than after N full intervals.
  fetch('/api/state', { cache: 'no-store' }).catch(() => { _failCount = _FAIL_LIMIT - 1; });

  window.startNowPlaying = function (opts) {
    opts = opts || {};
    _rafOpts = opts;
    applyTheme();
    requestAnimationFrame(rafLoop);

    async function poll() {
      const s = await fetchState();
      if (s) {
        _pollAt  = performance.now();
        _latest  = s;
        onNewState(s, opts);
      }
    }

    poll();
    setInterval(poll, opts.interval || 500);
  };
})();
