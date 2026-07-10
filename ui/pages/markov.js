// ui/pages/markov.js — standalone Markov regime module (isolated from the
// main strategy/algo pipeline; see backend/markov/). This page never reads
// from Strategy Research / Arena data — everything comes from /api/v1/markov/*.
// ══════════════════════════════════════════════════════════════
async function hydrateMarkov() {
  await hydrateMarkovStatus();
  await hydrateMarkovWatchlist();
  await hydrateMarkovStrategies();
}

async function hydrateMarkovStatus() {
  const box = document.getElementById('markov-status-body');
  if (!box) return;
  box.innerHTML = '<div class="loading-text">Loading…</div>';

  const data = await Api.markovStatus();
  if (data === null) {
    box.innerHTML = '<div class="offline-text">Markov module offline — backend unreachable.</div>';
    return;
  }

  const chain = data.observable_chain;
  const hmm = data.hmm;
  box.innerHTML = `
    <div class="markov-status-grid">
      <div class="markov-status-card">
        <div class="markov-status-title">Observable Chain (3-state)</div>
        ${chain ? `
          <div>Date: ${chain.date}</div>
          <div>Regime: <strong>${chain.regime_state}</strong></div>
          <div>Regime bias (Bull&minus;Bear): ${chain.regime_bias != null ? chain.regime_bias.toFixed(3) : '—'}</div>
          <div>Persistence: ${chain.regime_persistence != null ? (chain.regime_persistence * 100).toFixed(1) + '%' : '—'}</div>
        ` : '<div class="offline-text">No data yet — click Refresh.</div>'}
      </div>
      <div class="markov-status-card">
        <div class="markov-status-title">Hidden Markov Model</div>
        ${hmm ? `
          <div>Date: ${hmm.date}</div>
          <div>Regime class: <strong>${hmm.state_label || hmm.regime_class}</strong></div>
          <div>Confidence: ${hmm.confidence_pct != null ? hmm.confidence_pct.toFixed(1) + '%' : '—'}</div>
        ` : '<div class="offline-text">No HMM data yet (hmmlearn missing or not yet fit).</div>'}
      </div>
    </div>
  `;
}

async function markovRefresh() {
  const btn = document.getElementById('markov-refresh-btn');
  if (btn) { btn.disabled = true; btn.textContent = 'Refreshing…'; }
  await Api.markovRefresh();
  if (btn) { btn.disabled = false; btn.textContent = 'Refresh'; }
  await hydrateMarkovStatus();
}

async function hydrateMarkovWatchlist() {
  const list = document.getElementById('markov-watchlist-body');
  if (!list) return;
  const data = await Api.markovWatchlist();
  if (data === null) {
    list.innerHTML = '<div class="offline-text">Backend offline.</div>';
    return;
  }
  const symbols = data.symbols || [];
  if (!symbols.length) {
    list.innerHTML = '<div class="empty-text">No symbols on the Markov watchlist yet.</div>';
    return;
  }
  list.innerHTML = symbols.map(s => `
    <span class="markov-watchlist-chip">
      ${s}
      <button class="markov-chip-remove" onclick="markovRemoveSymbol('${s}')">&times;</button>
    </span>
  `).join('');
}

async function markovAddSymbol() {
  const input = document.getElementById('markov-add-symbol-input');
  if (!input || !input.value.trim()) return;
  const symbol = input.value.trim().toUpperCase();
  await Api.markovWatchlistAdd(symbol);
  input.value = '';
  await hydrateMarkovWatchlist();
}

async function markovRemoveSymbol(symbol) {
  await Api.markovWatchlistRemove(symbol);
  await hydrateMarkovWatchlist();
}

async function hydrateMarkovStrategies() {
  const tbody = document.getElementById('markov-strategies-body');
  if (!tbody) return;
  tbody.innerHTML = '<tr><td colspan="5" class="loading-text">Loading…</td></tr>';

  const data = await Api.markovStrategies();
  if (data === null) {
    tbody.innerHTML = '<tr><td colspan="5" class="offline-text">Backend offline.</td></tr>';
    return;
  }
  const rows = data.strategies || [];
  if (!rows.length) {
    tbody.innerHTML = '<tr><td colspan="5" class="empty-text">No candidates generated yet — pick a symbol and click Generate.</td></tr>';
    return;
  }
  tbody.innerHTML = rows.map(r => `
    <tr>
      <td>${r.strategy_id}</td>
      <td>${r.family}</td>
      <td>${r.sharpe != null ? r.sharpe.toFixed(2) : '—'}</td>
      <td>${r.win_rate != null ? r.win_rate.toFixed(1) + '%' : '—'}</td>
      <td>${r.trade_count}</td>
    </tr>
  `).join('');
}

async function markovGenerateStrategies() {
  const symInput = document.getElementById('markov-gen-symbol-input');
  const symbol = (symInput && symInput.value.trim()) || 'RELIANCE';
  const btn = document.getElementById('markov-generate-btn');
  if (btn) { btn.disabled = true; btn.textContent = 'Generating…'; }
  await Api.markovGenerateStrategies(symbol.toUpperCase());
  if (btn) { btn.disabled = false; btn.textContent = 'Generate'; }
  await hydrateMarkovStrategies();
}
