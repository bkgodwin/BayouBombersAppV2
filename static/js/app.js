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
      liveStatus.innerHTML = '';
      payload.forEach((row) => {
        if (!row.athlete) {
          console.warn('Live status payload missing athlete name', row);
        }
        const card = document.createElement('article');
        card.className = 'status-card';

        const title = document.createElement('h3');
        title.textContent = row.athlete || 'Athlete';
        const completion = document.createElement('p');
        completion.textContent = `Completion: ${row.completion || 0}%`;
        const mark = document.createElement('p');
        mark.textContent = `Best Mark: ${row.best_mark || 'N/A'}`;
        const status = document.createElement('p');
        status.textContent = `Status: ${row.alert || 'N/A'}`;

        card.appendChild(title);
        card.appendChild(completion);
        card.appendChild(mark);
        card.appendChild(status);
        liveStatus.appendChild(card);
      });
    } catch (_error) {
      console.error('Live status polling failed');
    }
  }

  setInterval(refreshLiveStatus, Math.max(10, pollSeconds) * 1000);
}
