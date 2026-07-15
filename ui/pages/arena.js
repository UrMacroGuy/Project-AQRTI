// ui/pages/arena.js - split from app.js (ARCH-5), see CHANGELOG
// ══════════════════════════════════════════════════════════════════════════
// STRATEGY ARENA — autonomous self-learning loop
// ══════════════════════════════════════════════════════════════════════════

let _arenaRunsCache = [];  // full run list, re-used by filter
let _arenaEquityChart = null;

async function hydrateArena() {
  setDataPoint('arena-status-label', 'Loading…', 'arena');
  setDataPoint('arena-total', '—', 'arena');

  try {
    const [status, champions, runs, review] = await Promise.all([
      Api.arenaStatus().catch(() => null),
      Api.arenaChampions().catch(() => ({ champions: [], count: 0 })),
      Api.arenaRuns(200, 'all').catch(() => ({ runs: [] })),
      Api.arenaNeedsReview().catch(() => ({ strategies: [], count: 0 })),
    ]);

    // ── Status strip ──────────────────────────────────────────────
    if (status) {
      const isRunning = status.is_running;
      setDataPoint('arena-status-label', isRunning ? '⚡ RUNNING' : '● IDLE', 'arena');
      const statusEl = document.getElementById('arena-status-label');
      if (statusEl) statusEl.style.color = isRunning ? 'var(--accent)' : 'var(--text-secondary)';
      setDataPoint('arena-total',           status.total_runs ?? '—', 'arena');
      setDataPoint('arena-running',         isRunning ? '1' : '0', 'arena');
      setDataPoint('arena-champions-count', status.champions ?? '0', 'arena');
      setDataPoint('arena-refining',        status.refining ?? '0', 'arena');
      setDataPoint('arena-needs-review',    status.needs_review ?? '0', 'arena');
      setDataPoint('arena-last-cycle',      status.last_cycle ? new Date(status.last_cycle).toLocaleString() : 'Auto-runs hourly', 'arena');

      const badge = document.getElementById('badge-arena');
      if (badge) {
        const champs = status.champions ?? 0;
        badge.textContent = champs > 0 ? `${champs} CHAMP` : 'AUTO';
        badge.className = 'nav-badge ' + (champs > 0 ? 'accent' : 'accent');
      }
    } else {
      setDataPoint('arena-status-label', '— offline', 'arena');
    }

    // ── Champions table ───────────────────────────────────────────
    const champBody = document.getElementById('arena-champions-body');
    const champBadge = document.getElementById('arena-champ-badge');
    if (champBadge) champBadge.textContent = champions.count ?? 0;
    if (champBody) {
      if (!champions.champions || champions.champions.length === 0) {
        champBody.innerHTML = '<tr><td colspan="9" style="text-align:center;color:var(--text-secondary);padding:20px">No champions yet — arena is still training.</td></tr>';
      } else {
        champBody.innerHTML = champions.champions.map(c => `
          <tr style="cursor:pointer" onclick="loadArenaEquity('${c.strategy_id}','${escHtml(c.strategy_name)}')">
            <td><span style="color:var(--accent)">★</span> ${escHtml(c.strategy_name)}</td>
            <td style="text-align:center">Gen ${c.generation ?? 0}</td>
            <td class="${(c.total_return_pct ?? 0) >= 120 ? 'positive' : ''}" style="text-align:right">${fmt1(c.total_return_pct)}%</td>
            <td class="${(c.max_drawdown_pct ?? 0) >= -25 ? 'positive' : 'negative'}" style="text-align:right">${fmt1(c.max_drawdown_pct)}%</td>
            <td style="text-align:right">${fmt1(c.win_rate)}%</td>
            <td style="text-align:right">${c.total_trades ?? 0}</td>
            <td style="text-align:center">${c.round_reached ?? 1}</td>
            <td style="text-align:right">${fmt1(c.fitness_score)}</td>
            <td style="font-size:0.72rem;color:var(--text-secondary)">${c.completed_at ? new Date(c.completed_at).toLocaleDateString() : '—'}</td>
          </tr>
        `).join('');
      }
    }

    // ── Run history ───────────────────────────────────────────────
    _arenaRunsCache = runs.runs || [];
    renderArenaRunsTable(_arenaRunsCache);

    // ── Needs review ──────────────────────────────────────────────
    const reviewTable = document.getElementById('arena-review-table');
    const reviewEmpty = document.getElementById('arena-review-empty');
    const reviewBody  = document.getElementById('arena-review-body');
    if (review.count > 0 && reviewBody) {
      if (reviewTable) reviewTable.style.display = '';
      if (reviewEmpty) reviewEmpty.style.display = 'none';
      reviewBody.innerHTML = review.strategies.map(r => `
        <tr>
          <td>${escHtml(r.strategy_name)}</td>
          <td class="${(r.best_return_pct ?? 0) >= 0 ? 'positive' : 'negative'}" style="text-align:right">${fmt1(r.best_return_pct)}%</td>
          <td style="text-align:right">${fmt1(r.win_rate)}%</td>
          <td style="text-align:right">${r.losing_days ?? 0}</td>
          <td style="text-align:center">${r.rounds_completed ?? 0} / 10</td>
          <td style="text-align:center;white-space:nowrap">
            <button class="btn btn-secondary" style="font-size:10px;padding:2px 8px" onclick="retryArenaReview('${r.strategy_id}', this)">↻ Retry</button>
            <button class="btn btn-secondary" style="font-size:10px;padding:2px 8px;color:var(--alert)" onclick="retireArenaReview('${r.strategy_id}', this)">✕ Retire</button>
          </td>
        </tr>
      `).join('');
    } else {
      if (reviewTable) reviewTable.style.display = 'none';
      if (reviewEmpty) reviewEmpty.style.display = '';
    }

  } catch (e) {
    console.error('hydrateArena:', e);
    const s2 = (id, v) => { const e2 = document.getElementById(id); if (e2) e2.textContent = v; };
    s2('arena-status-label', 'Error loading');
  }
}

function renderArenaRunsTable(rows) {
  const tbody = document.getElementById('arena-runs-body');
  if (!tbody) return;
  if (!rows || rows.length === 0) {
    tbody.innerHTML = '<tr><td colspan="13" style="text-align:center;color:var(--text-secondary);padding:20px">No runs yet — trigger the arena or wait for the hourly cycle.</td></tr>';
    return;
  }

  const statusColor = {
    champion:    'var(--positive)',
    refining:    'var(--accent)',
    needs_review:'var(--alert)',
    running:     'var(--accent)',
    error:       'var(--alert)',
    pending:     'var(--text-secondary)',
  };

  tbody.innerHTML = rows.map(r => {
    const clrRet = (r.total_return_pct ?? 0) >= 120 ? 'positive' : ((r.total_return_pct ?? 0) >= 0 ? '' : 'negative');
    const clrDd  = (r.max_drawdown_pct ?? 0) >= -25 ? 'positive' : 'negative';
    const color  = statusColor[r.status] || 'var(--text-secondary)';
    const passIcons = [r.passes_return, r.passes_drawdown, r.passes_winrate].map(p => p ? '✓' : '✗').join(' ');
    return `
      <tr style="cursor:pointer" onclick="loadArenaEquity('${r.strategy_id}','${escHtml(r.strategy_name)}')">
        <td>${escHtml(r.strategy_name)}</td>
        <td style="text-align:center">${r.generation ?? 0}</td>
        <td style="text-align:center">${r.round ?? 1}</td>
        <td style="color:${color};font-weight:600">${r.status ?? '—'}</td>
        <td class="${clrRet}" style="text-align:right">${r.total_return_pct != null ? fmt1(r.total_return_pct)+'%' : '—'}</td>
        <td class="${clrDd}"  style="text-align:right">${r.max_drawdown_pct != null ? fmt1(r.max_drawdown_pct)+'%' : '—'}</td>
        <td style="text-align:right">${r.win_rate != null ? fmt1(r.win_rate)+'%' : '—'}</td>
        <td style="text-align:right">${r.total_trades ?? '—'}</td>
        <td style="text-align:right;color:var(--positive)">${r.winning_days ?? '—'}</td>
        <td style="text-align:right;color:var(--alert)">${r.losing_days ?? '—'}</td>
        <td style="font-size:0.72rem;color:var(--text-secondary)">${r.donor_name ? escHtml(r.donor_name) : '—'}</td>
        <td style="text-align:right">${r.donor_coverage != null ? fmt1(r.donor_coverage)+'%' : '—'}</td>
        <td style="font-size:0.72rem;color:var(--text-secondary)">${r.completed_at ? new Date(r.completed_at).toLocaleDateString() : '—'}</td>
      </tr>
    `;
  }).join('');
}

function filterArenaRuns() {
  const sel = document.getElementById('arena-filter-status');
  const status = sel ? sel.value : 'all';
  const filtered = status === 'all' ? _arenaRunsCache : _arenaRunsCache.filter(r => r.status === status);
  renderArenaRunsTable(filtered);
}

async function loadArenaEquity(strategyId, strategyName) {
  const card  = document.getElementById('arena-equity-card');
  const title = document.getElementById('arena-equity-title');
  const canvas = document.getElementById('arena-equity-chart');
  if (!card || !canvas) return;

  if (title) title.textContent = `Equity Curve — ${strategyName}`;
  card.style.display = '';
  card.scrollIntoView({ behavior: 'smooth', block: 'nearest' });

  try {
    const data = await Api.arenaEquity(strategyId);
    if (!data.labels || data.labels.length === 0) {
      if (title) title.textContent = `${strategyName} — no equity data yet`;
      return;
    }

    if (_arenaEquityChart) { _arenaEquityChart.destroy(); _arenaEquityChart = null; }

    const ctx = canvas.getContext('2d');
    _arenaEquityChart = new Chart(ctx, {
      type: 'line',
      data: {
        labels: data.labels,
        datasets: [{
          label: 'Portfolio Value (₹)',
          data: data.values,
          borderColor: 'rgba(139,92,246,0.85)',
          backgroundColor: 'rgba(139,92,246,0.08)',
          borderWidth: 1.5,
          pointRadius: 0,
          fill: true,
          tension: 0.3,
        }]
      },
      options: {
        responsive: true,
        plugins: {
          legend: { display: false },
          tooltip: {
            callbacks: {
              label: ctx2 => `₹${ctx2.parsed.y.toLocaleString('en-IN', { maximumFractionDigits: 0 })}`
            }
          }
        },
        scales: {
          x: { ticks: { maxTicksLimit: 12, color: 'rgba(255,255,255,0.4)', font: { size: 10 } }, grid: { color: 'rgba(255,255,255,0.05)' } },
          y: { ticks: { color: 'rgba(255,255,255,0.4)', font: { size: 10 }, callback: v => '₹' + (v/1000).toFixed(0) + 'K' }, grid: { color: 'rgba(255,255,255,0.05)' } }
        }
      }
    });

    if (title) title.textContent = `Equity Curve — ${strategyName} (${fmt1(data.total_return_pct)}% return)`;
  } catch (e) {
    console.error('loadArenaEquity:', e);
  }
}

async function triggerArenaRun() {
  const btn = document.querySelector('#page-arena .btn-primary');
  if (btn) { btn.textContent = '⏳ Starting…'; btn.disabled = true; }
  try {
    const res = await Api.triggerArena();
    if (btn) { btn.textContent = res.already_running ? '⚡ Already Running' : '✓ Cycle Started'; }
    setTimeout(() => {
      if (btn) { btn.textContent = '▶ Run Cycle'; btn.disabled = false; }
      hydrateArena();
    }, 3000);
  } catch (e) {
    if (btn) { btn.textContent = '✕ Error'; btn.disabled = false; }
    console.error('triggerArenaRun:', e);
  }
}

function fmt1(v) {
  if (v == null || isNaN(v)) return '—';
  return Number(v).toFixed(1);
}

function escHtml(str) {
  if (!str) return '';
  return String(str).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

async function retryArenaReview(strategyId, btn) {
  if (btn) { btn.disabled = true; btn.textContent = '⏳'; }
  try {
    await Api.arenaRetryReview(strategyId);
    hydrateArena();
  } catch (e) {
    console.error('retryArenaReview:', e);
    if (btn) { btn.disabled = false; btn.textContent = '↻ Retry'; }
  }
}

async function retireArenaReview(strategyId, btn) {
  if (!confirm('Retire this algo? It will stop competing in the arena and 2 fresh candidates will be bred to replace it.')) return;
  if (btn) { btn.disabled = true; btn.textContent = '⏳'; }
  try {
    await Api.retireStrategy(strategyId, 'arena_needs_review_manual_retire');
    hydrateArena();
  } catch (e) {
    console.error('retireArenaReview:', e);
    if (btn) { btn.disabled = false; btn.textContent = '✕ Retire'; }
  }
}
