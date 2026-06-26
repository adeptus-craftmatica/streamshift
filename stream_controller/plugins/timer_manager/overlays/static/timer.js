/* ── Timer Overlay Shared JS ──────────────────────────────────────────── */
(function() {
  function param(k, d) {
    var m = location.search.match(new RegExp('[?&]' + k + '=([^&]*)'));
    return m ? decodeURIComponent(m[1]) : d;
  }
  function hexRgb(h) {
    h = h.replace('#', '');
    if (h.length === 3) h = h[0]+h[0]+h[1]+h[1]+h[2]+h[2];
    var n = parseInt(h, 16);
    return [(n>>16)&255, (n>>8)&255, n&255].join(',');
  }
  var _appliedThemeKey = '';
  function applyThemeObj(t) {
    var accent  = (t && t.accent)  || param('accent', '7c3aed');
    var bg      = (t && t.bg)      || param('bg',     '0d0d0f');
    var text    = (t && t.text)    || param('text',   'f0f0ff');
    var opacity = (t && t.opacity != null) ? (t.opacity / 100).toFixed(2)
                : (parseInt(param('opacity', '92')) / 100).toFixed(2);
    var key = accent + '|' + bg + '|' + text + '|' + opacity;
    if (key === _appliedThemeKey) return;
    _appliedThemeKey = key;
    var R = document.documentElement;
    R.style.setProperty('--accent',      '#' + accent);
    R.style.setProperty('--accent-rgb',  hexRgb(accent));
    R.style.setProperty('--bg',          '#' + bg);
    R.style.setProperty('--bg-rgb',      hexRgb(bg));
    R.style.setProperty('--bg-opacity',  opacity);
    R.style.setProperty('--text-hi',     '#' + text);
    R.style.setProperty('--text-lo',     'rgba(' + hexRgb(text) + ',0.55)');
    if (window.__onThemeChange) window.__onThemeChange(accent);
  }
  function applyTheme() { applyThemeObj(null); }

  var _timerId    = param('id', '');
  var _apiBase    = location.protocol + '//' + location.host;
  var _interval   = parseInt(param('interval', '200'));
  var _hideAfter  = parseInt(param('hide_after', '5'));  // seconds; 0 = never
  var _lastState  = null;
  var _smoothPos  = 0;
  var _lastRaf    = null;
  var _callbacks  = {};
  var _hideTimer  = null;
  var _hidden     = false;
  var _prevStatus = '';

  function _showOverlay() {
    if (!_hidden) return;
    _hidden = false;
    document.body.style.transition = 'opacity 0.4s ease';
    document.body.style.opacity    = '1';
  }

  function _scheduleHide() {
    if (_hideAfter <= 0 || _hideTimer) return;
    _hideTimer = setTimeout(function() {
      _hidden = true;
      document.body.style.transition = 'opacity 0.6s ease';
      document.body.style.opacity    = '0';
      _hideTimer = null;
    }, _hideAfter * 1000);
  }

  function _cancelHide() {
    if (_hideTimer) { clearTimeout(_hideTimer); _hideTimer = null; }
  }

  var _failCount  = 0;
  var _reloading  = false;
  var _FAIL_LIMIT = 15; // ~3 s at 200 ms default interval

  function fetchState(cb) {
    var url = _apiBase + '/api/state' + (_timerId ? '?id=' + encodeURIComponent(_timerId) : '');
    fetch(url)
      .then(function(r) { return r.json(); })
      .then(function(data) {
        _failCount = 0;
        if (data._theme) applyThemeObj(data._theme);
        cb(data);
      })
      .catch(function() {
        _failCount++;
        if (_failCount >= _FAIL_LIMIT && !_reloading) {
          _reloading = true;
          setTimeout(function() { window.location.reload(); }, 2000);
        }
      });
  }

  function fmtSecs(s) {
    s = Math.max(0, s);
    var h = Math.floor(s / 3600);
    var m = Math.floor((s % 3600) / 60);
    var sec = Math.floor(s % 60);
    if (h > 0) return h + ':' + String(m).padStart(2,'0') + ':' + String(sec).padStart(2,'0');
    return String(m).padStart(2,'0') + ':' + String(sec).padStart(2,'0');
  }

  // Startup probe — runs immediately on every page load.
  // If the server is down (StreamShift not running), prime the fail counter so
  // the reload fires quickly instead of waiting for N polling intervals.
  // This makes the retry loop self-sustaining across successive reload attempts.
  fetch(_apiBase + '/api/state')
    .catch(function() { _failCount = _FAIL_LIMIT - 1; });

  function startTimer(opts) {
    opts = opts || {};
    applyTheme();
    _callbacks = opts;

    // Polling
    setInterval(function() {
      fetchState(function(s) {
        var prevId = _lastState ? _lastState.id : null;
        _lastState = s;
        // Sync smooth position: hard sync on track change or > 0.8s drift
        var serverTime = s.mode === 'countdown' ? s.remaining : s.elapsed;
        if (prevId !== s.id || Math.abs(serverTime - _smoothPos) > 0.8) {
          _smoothPos = serverTime;
        }
        // Auto-hide: schedule hide when finished, cancel+show when running again
        if (s.status === 'finished' && _prevStatus !== 'finished') {
          _scheduleHide();
        } else if (s.status !== 'finished' && _prevStatus === 'finished') {
          _cancelHide();
          _showOverlay();
        }
        _prevStatus = s.status;
        if (opts.onUpdate) opts.onUpdate(s, _smoothPos);
      });
    }, _interval);

    // rAF loop for smooth display
    function raf(now) {
      if (_lastRaf !== null && _lastState && _lastState.status === 'running') {
        var dt = (now - _lastRaf) / 1000;
        if (_lastState.mode === 'countdown') {
          _smoothPos = Math.max(0, _smoothPos - dt);
        } else {
          _smoothPos += dt;
        }
      }
      _lastRaf = now;
      if (opts.onRaf) opts.onRaf(_smoothPos, _lastState);
      requestAnimationFrame(raf);
    }
    requestAnimationFrame(raf);
  }

  window.startTimer = startTimer;
  window.fmtSecs   = fmtSecs;
  window.timerParam = param;
})();
