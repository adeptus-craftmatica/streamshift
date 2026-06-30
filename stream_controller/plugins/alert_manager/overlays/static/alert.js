const ICONS = {
  follower:   '👤',
  subscriber: '⭐',
  gift_sub:   '🎁',
  bits:       '💎',
  raid:       '⚔️',
  donation:   '💰',
};

function escapeHtml(s) {
  return String(s)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;');
}

function showAlert(data) {
  const container = document.getElementById('alert-container');
  const card = document.createElement('div');
  card.className = 'alert-card';
  card.innerHTML = `
    <span class="alert-icon">${ICONS[data.type] || '🎉'}</span>
    <div class="alert-body">
      <div class="alert-name">${escapeHtml(data.name || '')}</div>
      <div class="alert-message">${escapeHtml(data.message || '')}</div>
    </div>
  `;
  container.appendChild(card);

  // Trigger slide-in animation on next frame
  requestAnimationFrame(() => {
    card.classList.add('visible');
    const duration = typeof data.duration === 'number' ? data.duration : 5000;
    const hideDelay = Math.max(duration - 600, 400);
    setTimeout(() => {
      card.classList.add('hiding');
      setTimeout(() => card.remove(), 600);
    }, hideDelay);
  });
}

async function poll() {
  while (true) {
    try {
      const r = await fetch('/poll');
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const data = await r.json();
      if (data.type !== 'ping') {
        showAlert(data);
      }
    } catch (e) {
      // Brief backoff on error before retrying
      await new Promise(r => setTimeout(r, 2000));
    }
  }
}

poll();
