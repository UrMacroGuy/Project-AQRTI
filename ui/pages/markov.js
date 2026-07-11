// ui/pages/markov.js — standalone Markov regime module (isolated from the
// main strategy/algo pipeline; see backend/markov/). This page never reads
// from Strategy Research / Arena data — everything comes from /api/v1/markov/*.
// ══════════════════════════════════════════════════════════════

// Curated universe (backend/aqrti/config/settings.py::universe) — fixed
// per CLAUDE.md hard rule 4. No live endpoint currently exposes this list
// to the Markov module, so it is mirrored here for the generate-strategy
// dropdown; keep in sync with settings.py if the curated universe changes.
const MARKOV_UNIVERSE = ['BEL', 'HDFCBANK', 'NTPC', 'ICICIBANK', 'INFY', 'CDSL', 'DRREDDY', 'LT', 'HAL'];

async function hydrateMarkov() {
  await hydrateMarkovStatus();
  await hydrateMarkovWatchlist();
  await hydrateMarkovStrategies();
  ensureMarkovSymbolDropdown();
}

function ensureMarkovSymbolDropdown() {
  const sel = document.getElementById('markov-gen-symbol-input');
  if (!sel || sel.dataset.populated) return;
  sel.innerHTML = MARKOV_UNIVERSE.map(s => `<option value="${s}">${s}</option>`).join('');
  sel.dataset.populated = '1';
}

function regimeBadgeClass(state) {
  if (state === 'BULL') return 'bull';
  if (state === 'BEAR') return 'bear';
  return 'sideways';
}

async function hydrateMarkovStatus() {
  const box = document.getElementById('markov-status-body');
  if (!box) return;
  box.innerHTML = '<div class="loading-text">Loading…</div>';

  let data = null;
  try { data = await Api.markovStatus(); } catch (_) { data = null; }

  if (data === null) {
    box.innerHTML = '<div class="offline-text">Markov module offline — backend unreachable.</div>';
    return;
  }

  const chain = data.observable_chain;
  const hmm = data.hmm;

  // ── Observable chain card ──────────────────────────────────────────
  let chainHtml;
  if (chain) {
    const badgeCls = regimeBadgeClass(chain.regime_state);
    const bias = chain.regime_bias;
    const persistence = chain.regime_persistence;
    // Diverging bar marker: map [-1, 1] -> [0%, 100%]
    const markerPct = bias != null ? Math.max(0, Math.min(100, ((bias + 1) / 2) * 100)) : 50;
    const persistPct = persistence != null ? Math.max(0, Math.min(100, persistence * 100)) : 0;
    chainHtml = `
      <div class="markov-regime-badge ${badgeCls}">${chain.regime_state}</div>
      <div class="markov-regime-date">as of ${chain.date}</div>

      <div class="markov-metric-label">
        <span>Regime bias (Bear&nbsp;&larr;&nbsp;&rarr;&nbsp;Bull)</span>
        <span class="markov-metric-val">${bias != null ? bias.toFixed(3) : '—'}</span>
      </div>
      <div class="diverging-bar">
        <div class="diverging-bar-marker ${bias != null && bias >= 0 ? 'bull' : 'bear'}" style="left:${markerPct}%"></div>
      </div>

      <div class="markov-metric-label" style="margin-top:14px">
        <span>Persistence ${persistence != null && persistence >= 0.7 ? '(sticky regime)' : ''}</span>
        <span class="markov-metric-val">${persistence != null ? (persistence * 100).toFixed(1) + '%' : '—'}</span>
      </div>
      <div class="persist-meter-track"><div class="persist-meter-fill" style="width:${persistPct}%"></div></div>
    `;
  } else {
    chainHtml = '<div class="empty-text">No observable-chain data yet — click Refresh.</div>';
  }

  // ── HMM card ────────────────────────────────────────────────────────
  let hmmHtml;
  if (hmm) {
    const label = hmm.state_label || `Class ${hmm.regime_class}`;
    const badgeCls = regimeBadgeClass(hmm.state_label);
    const conf = hmm.confidence_pct;
    const confPct = conf != null ? Math.max(0, Math.min(100, conf)) : 0;
    hmmHtml = `
      <div class="markov-regime-badge ${badgeCls}" style="font-size:1.1rem">CLASS ${hmm.regime_class}${hmm.state_label ? ' · ' + hmm.state_label : ''}</div>
      <div class="markov-regime-date">as of ${hmm.date}</div>
      <div class="markov-metric-label"><span>Confidence</span><span class="markov-metric-val">${conf != null ? conf.toFixed(1) + '%' : '—'}</span></div>
      <div style="display:flex;align-items:center;gap:8px">
        <div class="hmm-conf-track"><div class="hmm-conf-fill" style="width:${confPct}%"></div></div>
      </div>
      <div class="markov-meta-row">Fit date, n_states and BIC-selected note are not currently returned by the /markov/status endpoint — not available from current API response.</div>
    `;
  } else {
    hmmHtml = '<div class="empty-text">No HMM data yet — hmmlearn not fit, or missing from the environment.</div>';
  }

  box.innerHTML = `
    <div class="markov-hero-grid">
      <div class="card">
        <div class="card-title">Observable Chain (3-state)</div>
        ${chainHtml}
      </div>
      <div class="card">
        <div class="card-title">Hidden Markov Model</div>
        ${hmmHtml}
      </div>
    </div>
  `;

  hydrateMarkovTransitionMatrix(data);
}

// Row 2 — transition matrix heatmap. The /status endpoint currently returns
// only regime_state/regime_bias/regime_persistence for the observable chain
// (see backend/markov/routes.py::status) — it does NOT include the
// transition_matrix_json field that exists on the MarkovChainDaily model.
// Render an honest "not available" state rather than fabricating a matrix.
function hydrateMarkovTransitionMatrix(data) {
  const box = document.getElementById('markov-transition-body');
  if (!box) return;

  const chain = data && data.observable_chain;
  const matrix = chain && chain.transition_matrix;

  if (!matrix || !Array.isArray(matrix)) {
    box.innerHTML = '<div class="empty-text">Transition matrix not available from current API response.</div>';
    return;
  }

  const states = ['BEAR', 'SIDEWAYS', 'BULL'];
  const maxP = Math.max(...matrix.flat().map(v => (typeof v === 'number' ? v : 0)), 0.0001);
  const rows = matrix.map((row, i) => {
    const cells = row.map(p => {
      const val = typeof p === 'number' ? p : 0;
      const alpha = 0.08 + 0.55 * (val / maxP);
      return `<td style="background:rgba(255,149,0,${alpha.toFixed(2)})">${val.toFixed(3)}</td>`;
    }).join('');
    return `<tr><td class="row-label">${states[i] || i}</td>${cells}</tr>`;
  }).join('');

  box.innerHTML = `
    <div class="table-container">
      <table class="transition-matrix">
        <thead><tr><th></th>${states.map(s => `<th>${s}</th>`).join('')}</tr></thead>
        <tbody>${rows}</tbody>
      </table>
    </div>
    <div class="markov-meta-row" style="margin-top:8px">Rows = from-state, columns = to-state. Cell shading scales with probability magnitude.</div>
  `;
}

async function markovRefresh() {
  const btn = document.getElementById('markov-refresh-btn');
  if (btn) { btn.disabled = true; btn.textContent = 'Refreshing…'; }
  try { await Api.markovRefresh(); } catch (_) {}
  if (btn) { btn.disabled = false; btn.textContent = 'Refresh'; }
  await hydrateMarkovStatus();
}

async function hydrateMarkovWatchlist() {
  const list = document.getElementById('markov-watchlist-body');
  if (!list) return;
  list.innerHTML = '<div class="loading-text">Loading…</div>';

  let data = null;
  try { data = await Api.markovWatchlist(); } catch (_) { data = null; }

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
      <button class="markov-chip-remove" onclick="markovRemoveSymbol('${s}')" title="Remove ${s}">&times;</button>
    </span>
  `).join('');
}

async function markovAddSymbol() {
  const input = document.getElementById('markov-add-symbol-input');
  if (!input || !input.value.trim()) return;
  const symbol = input.value.trim().toUpperCase();
  try { await Api.markovWatchlistAdd(symbol); } catch (_) {}
  input.value = '';
  await hydrateMarkovWatchlist();
}

async function markovRemoveSymbol(symbol) {
  try { await Api.markovWatchlistRemove(symbol); } catch (_) {}
  await hydrateMarkovWatchlist();
}

async function hydrateMarkovStrategies() {
  const tbody = document.getElementById('markov-strategies-body');
  if (!tbody) return;
  tbody.innerHTML = '<tr><td colspan="5" class="loading-text">Loading…</td></tr>';

  let data = null;
  try { data = await Api.markovStrategies(); } catch (_) { data = null; }

  if (data === null) {
    tbody.innerHTML = '<tr><td colspan="5" class="offline-text">Backend offline.</td></tr>';
    return;
  }
  const rows = data.strategies || [];
  if (!rows.length) {
    tbody.innerHTML = '<tr><td colspan="5" class="empty-text">Not generated yet — pick a symbol and click Generate.</td></tr>';
    return;
  }
  tbody.innerHTML = rows.map(r => {
    const sharpeColor = r.sharpe == null ? 'var(--text-muted)' : (r.sharpe >= 0 ? 'var(--positive)' : 'var(--negative)');
    const wrColor = r.win_rate == null ? 'var(--text-muted)' : (r.win_rate >= 50 ? 'var(--positive)' : 'var(--negative)');
    return `
    <tr>
      <td>${r.strategy_id}</td>
      <td><span class="badge badge-neutral">${r.family}</span></td>
      <td style="text-align:right;color:${sharpeColor}">${r.sharpe != null ? r.sharpe.toFixed(2) : '—'}</td>
      <td style="text-align:right;color:${wrColor}">${r.win_rate != null ? r.win_rate.toFixed(1) + '%' : '—'}</td>
      <td style="text-align:right">${r.trade_count}</td>
    </tr>`;
  }).join('');
}

async function markovGenerateStrategies() {
  const symInput = document.getElementById('markov-gen-symbol-input');
  const symbol = (symInput && symInput.value.trim()) || MARKOV_UNIVERSE[0];
  const btn = document.getElementById('markov-generate-btn');
  if (btn) { btn.disabled = true; btn.textContent = 'Generating…'; }
  try { await Api.markovGenerateStrategies(symbol.toUpperCase()); } catch (_) {}
  if (btn) { btn.disabled = false; btn.textContent = 'Generate'; }
  await hydrateMarkovStrategies();
}
