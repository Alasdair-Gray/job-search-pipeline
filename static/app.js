/**
 * Job Pipeline — frontend JavaScript
 *
 * Handles:
 *   runTask(type)   - POST to /api/scrape or /api/score, then open overlay
 *   poll()          - GET /api/status every 2s while a task is running
 *   closeOverlay()  - hide overlay and reload page to show fresh data
 */

let _pollTimer = null;
let _lastLogLength = 0;

// ── Public: trigger a pipeline task ────────────────────────────────────────

function runTask(type) {
  const endpoint = type === 'scrape' ? '/api/scrape' : '/api/score';
  const title    = type === 'scrape' ? '🔍 Running Scraper…' : '⚡ Running Scorer…';

  fetch(endpoint, { method: 'POST' })
    .then(r => r.json())
    .then(data => {
      if (data.error) {
        alert(data.error);
        return;
      }
      openOverlay(title);
      startPolling();
    })
    .catch(err => {
      alert('Failed to start task: ' + err);
    });
}

// ── Overlay ─────────────────────────────────────────────────────────────────

function openOverlay(title) {
  document.getElementById('overlay-title').textContent = title;
  document.getElementById('overlay-log').textContent   = '';
  document.getElementById('overlay-close').style.display = 'none';
  document.getElementById('overlay-spinner').style.display = 'block';
  document.getElementById('task-overlay').classList.remove('hidden');
  _lastLogLength = 0;

  // Disable buttons while running
  setButtonsDisabled(true);
}

function closeOverlay() {
  document.getElementById('task-overlay').classList.add('hidden');
  stopPolling();
  // Reload to pick up fresh job data
  window.location.reload();
}

// ── Polling ──────────────────────────────────────────────────────────────────

function startPolling() {
  stopPolling(); // clear any existing timer
  _pollTimer = setInterval(poll, 1500);
}

function stopPolling() {
  if (_pollTimer) {
    clearInterval(_pollTimer);
    _pollTimer = null;
  }
}

function poll() {
  fetch('/api/status')
    .then(r => r.json())
    .then(state => {
      updateOverlayLog(state.log || []);

      if (!state.running) {
        // Task finished
        stopPolling();
        setButtonsDisabled(false);
        document.getElementById('overlay-spinner').style.display = 'none';

        const titleEl = document.getElementById('overlay-title');
        if (state.error) {
          titleEl.textContent = '✗ Task failed';
          titleEl.style.color = '#f87171';
        } else {
          titleEl.textContent = '✓ Done';
          titleEl.style.color = '#4ade80';
        }

        document.getElementById('overlay-close').style.display = 'inline-flex';
      }
    })
    .catch(() => {
      // Network blip — keep polling
    });
}

function updateOverlayLog(lines) {
  if (lines.length <= _lastLogLength) return;

  const logEl   = document.getElementById('overlay-log');
  const newLines = lines.slice(_lastLogLength);
  _lastLogLength = lines.length;

  newLines.forEach(line => {
    logEl.textContent += line + '\n';
  });

  // Auto-scroll to bottom
  logEl.scrollTop = logEl.scrollHeight;
}

// ── Helpers ──────────────────────────────────────────────────────────────────

function setButtonsDisabled(disabled) {
  const scrapeBtn = document.getElementById('btn-scrape');
  const scoreBtn  = document.getElementById('btn-score');
  if (scrapeBtn) scrapeBtn.disabled = disabled;
  if (scoreBtn)  scoreBtn.disabled  = disabled;
}

// ── On page load: resume polling if a task is already running ────────────────

document.addEventListener('DOMContentLoaded', () => {
  fetch('/api/status')
    .then(r => r.json())
    .then(state => {
      if (state.running) {
        const title = state.type === 'scrape' ? '🔍 Running Scraper…' : '⚡ Running Scorer…';
        openOverlay(title);
        // Pre-populate log with whatever's already there
        updateOverlayLog(state.log || []);
        startPolling();
      }
    })
    .catch(() => {});
});
