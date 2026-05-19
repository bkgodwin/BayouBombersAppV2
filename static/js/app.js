document.querySelectorAll('.expand-btn').forEach((button) => {
  button.addEventListener('click', (event) => {
    const card = event.target.closest('.module-card');
    if (!card) return;
    card.classList.toggle('expanded');
    event.target.textContent = card.classList.contains('expanded') ? 'Collapse' : 'Expand';
  });
});

const liveStatus = document.getElementById('liveStatus');
if (liveStatus) {
  const pollSeconds = Number(liveStatus.dataset.poll || 20);

  async function refreshLiveStatus() {
    try {
      const response = await fetch('/api/live-status', { headers: { Accept: 'application/json' } });
      if (!response.ok) return;
      const payload = await response.json();
      if (!Array.isArray(payload)) return;
      liveStatus.innerHTML = payload.map((row) => `
        <article class="status-card">
          <h3>${row.athlete}</h3>
          <p>Completion: ${row.completion}%</p>
          <p>Best Mark: ${row.best_mark || 'N/A'}</p>
          <p>Status: ${row.alert}</p>
        </article>
      `).join('');
    } catch (_error) {
      // no-op polling fallback
    }
  }

  setInterval(refreshLiveStatus, Math.max(10, pollSeconds) * 1000);
}
