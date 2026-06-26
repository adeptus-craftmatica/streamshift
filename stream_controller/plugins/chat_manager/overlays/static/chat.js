/* ── Chat Overlay Shared JS ──────────────────────────────────────────────── */

(function() {
  var _apiBase = (location.protocol + '//' + location.host);
  var _lastId = '';
  var _opts = {};

  function param(name, def) {
    var m = location.search.match(new RegExp('[?&]' + name + '=([^&]*)'));
    return m ? decodeURIComponent(m[1]) : def;
  }

  function hexRgb(hex) {
    var h = hex.replace('#', '');
    if (h.length === 3) h = h[0]+h[0]+h[1]+h[1]+h[2]+h[2];
    var n = parseInt(h, 16);
    return [(n >> 16) & 255, (n >> 8) & 255, n & 255].join(',');
  }

  function applyTheme() {
    var root = document.documentElement;
    var accent  = '#' + param('accent',  '7c3aed');
    var bg      = '#' + param('bg',      '0d0d0f');
    var opacity = (parseInt(param('opacity', '90')) / 100).toFixed(2);
    var textHi  = '#' + param('text',    'f0f0ff');
    var fontSize = param('size', '14') + 'px';

    root.style.setProperty('--accent',     accent);
    root.style.setProperty('--bg',         bg);
    root.style.setProperty('--bg-opacity', opacity);
    root.style.setProperty('--bg-rgb',     hexRgb(bg));
    root.style.setProperty('--text-hi',    textHi);
    root.style.setProperty('--text-lo',    'rgba(' + hexRgb(textHi) + ',0.60)');
    root.style.setProperty('--font-size',  fontSize);
  }

  function fetchMessages(callback) {
    var url = _apiBase + '/api/messages?since=' + encodeURIComponent(_lastId);
    fetch(url)
      .then(function(r) { return r.json(); })
      .then(function(data) {
        var msgs = data.messages || [];
        if (msgs.length > 0) {
          _lastId = msgs[msgs.length - 1].id;
        }
        callback(msgs, data.status, data.channel);
      })
      .catch(function() {});
  }

  // ── Feed overlay ──────────────────────────────────────────────────────────

  function startFeed(opts) {
    opts = opts || {};
    _opts = opts;
    applyTheme();

    var container = document.getElementById('chat-feed');
    var maxVisible = parseInt(param('max', '12'));
    var fadeDelay  = parseInt(param('fade', '0')) * 1000; // ms, 0 = no fade

    function addMessage(msg) {
      var el = document.createElement('div');
      el.className = 'chat-msg';
      el.style.setProperty('--msg-color', msg.color || 'var(--accent)');
      if (msg.deleted) el.classList.add('deleted');

      var badges = (msg.badges || []).join(' ');
      el.innerHTML =
        '<div class="msg-badges">' + (badges ? escHtml(badges) + ' ' : '') + '</div>' +
        '<div class="msg-body">' +
          '<div class="msg-header">' +
            '<span class="msg-name">' + escHtml(msg.display_name) + '</span>' +
          '</div>' +
          '<div class="msg-text">' + escHtml(msg.text) + '</div>' +
        '</div>';

      container.appendChild(el);

      // trim old messages
      while (container.children.length > maxVisible) {
        container.removeChild(container.firstChild);
      }

      // optional fade-out
      if (fadeDelay > 0) {
        setTimeout(function() { el.classList.add('fade-out'); }, fadeDelay);
        setTimeout(function() {
          if (el.parentNode) el.parentNode.removeChild(el);
        }, fadeDelay + 600);
      }
    }

    function poll() {
      fetchMessages(function(msgs) {
        msgs.forEach(function(msg) {
          if (!msg.deleted) addMessage(msg);
        });
      });
    }

    var interval = parseInt(param('interval', '750'));
    setInterval(poll, interval);
    poll();
  }

  // ── Popup overlay ─────────────────────────────────────────────────────────

  function startPopup(opts) {
    opts = opts || {};
    applyTheme();

    var card = document.getElementById('popup-card');
    var nameEl = document.getElementById('popup-name');
    var textEl = document.getElementById('popup-text');
    var displayDuration = parseInt(param('duration', '6')) * 1000;
    var _hideTimer = null;
    var _lastShownId = '';

    function showMsg(msg) {
      if (msg.id === _lastShownId) return;
      _lastShownId = msg.id;
      if (_hideTimer) clearTimeout(_hideTimer);

      card.classList.remove('fade-out');
      card.style.setProperty('--msg-color', msg.color || 'var(--accent)');
      nameEl.textContent = msg.display_name;
      var badges = (msg.badges || []).join(' ');
      nameEl.textContent = (badges ? badges + ' ' : '') + msg.display_name;
      textEl.textContent = msg.text;
      card.style.display = 'flex';

      _hideTimer = setTimeout(function() {
        card.classList.add('fade-out');
        setTimeout(function() { card.style.display = 'none'; }, 500);
      }, displayDuration);
    }

    function poll() {
      fetchMessages(function(msgs) {
        if (msgs.length > 0) showMsg(msgs[msgs.length - 1]);
      });
    }

    card.style.display = 'none';
    var interval = parseInt(param('interval', '500'));
    setInterval(poll, interval);
    poll();
  }

  // ── Ticker overlay ────────────────────────────────────────────────────────

  function startTicker(opts) {
    applyTheme();
    var scroll = document.getElementById('ticker-scroll');
    var _buffer = [];
    var _displayed = [];

    function rebuildTicker() {
      var items = _displayed.slice(-20);
      var html = items.map(function(msg) {
        return '<span class="ticker-item">' +
          '<span class="ticker-item-name" style="color:' + (msg.color || 'var(--accent)') + '">' +
          escHtml(msg.display_name) + '</span>: ' +
          escHtml(msg.text) + '</span>';
      }).join(' ★ ');
      scroll.innerHTML = html + ' ★ ' + html; // doubled for seamless loop
    }

    function poll() {
      fetchMessages(function(msgs) {
        msgs.forEach(function(msg) {
          if (!msg.deleted) {
            _displayed.push(msg);
            if (_displayed.length > 30) _displayed.shift();
          }
        });
        if (msgs.length > 0) rebuildTicker();
      });
    }

    var interval = parseInt(param('interval', '1000'));
    setInterval(poll, interval);
    poll();
  }

  function escHtml(text) {
    return String(text)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  // expose
  window.startChatFeed   = startFeed;
  window.startChatPopup  = startPopup;
  window.startChatTicker = startTicker;
})();
