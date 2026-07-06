// ui/pages/paper.js - split from app.js (ARCH-5), see CHANGELOG

// ═══════════════════════════════════════════════════════════════
// PHASE 4: PAPER PORTFOLIO PAGE RENDERER + HYDRATION
// ═══════════════════════════════════════════════════════════════

// ── Paper Portfolio renderer ─────────────────────────────────
function renderPaperPortfolio() {
  // Delegate entirely to hydratePaperPortfolio() — live backend data
  const pbody = el('pp-full-positions-body');
  if (pbody) pbody.innerHTML = '<tr><td colspan="12" style="color:var(--text-muted);text-align:center;padding:16px">Loading positions…</td></tr>';
  const tbody = el('pp-trades-body');
  if (tbody) tbody.innerHTML = '<tr><td colspan="13" style="color:var(--text-muted);text-align:center;padding:16px">Loading trades…</td></tr>';
}

function _downloadBlob(blob, filename) {
  const url = URL.createObjectURL(blob);
  const a   = document.createElement('a');
  a.href     = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  setTimeout(() => { URL.revokeObjectURL(url); a.remove(); }, 1000);
}

async function exportTradingViewPine() {
  const btn = document.querySelector('[onclick="exportTradingViewPine()"]');
  const orig = btn ? btn.textContent : '';
  if (btn) { btn.textContent = '⟳ Generating…'; btn.disabled = true; }
  try {
    const res = await fetch(`${API_CONFIG.BASE}/paper-portfolio/export/tradingview`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const cd   = res.headers.get('Content-Disposition') || '';
    const name = cd.match(/filename="?([^"]+)"?/)?.[1] || 'aqrti_portfolio.pine';
    const blob = await res.blob();
    _downloadBlob(blob, name);
    if (btn) { btn.textContent = '✓ Downloaded!'; setTimeout(() => { btn.textContent = orig; btn.disabled = false; }, 2000); }
  } catch(e) {
    alert('Export failed: ' + e.message);
    if (btn) { btn.textContent = orig; btn.disabled = false; }
  }
}

async function exportPositionsCSV() {
  const btn = document.querySelector('[onclick="exportPositionsCSV()"]');
  const orig = btn ? btn.textContent : '';
  if (btn) { btn.disabled = true; }
  try {
    const res = await fetch(`${API_CONFIG.BASE}/paper-portfolio/export/csv`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const cd   = res.headers.get('Content-Disposition') || '';
    const name = cd.match(/filename="?([^"]+)"?/)?.[1] || 'aqrti_positions.csv';
    const blob = await res.blob();
    _downloadBlob(blob, name);
    if (btn) { btn.disabled = false; }
  } catch(e) {
    alert('CSV export failed: ' + e.message);
    if (btn) { btn.disabled = false; }
  }
}

async function triggerBacktest() {
  const statusEl = document.getElementById('pp-backtest-status');
  const btn = document.querySelector('[onclick="triggerBacktest()"]');
  if (statusEl) { statusEl.textContent = '⟳ Starting backtest…'; statusEl.style.color = 'var(--accent)'; }
  if (btn) { btn.disabled = true; btn.textContent = '⏳ Starting…'; }
  try {
    const res = await Api.runBacktest(null, 2);
    if (res.status === 'started') {
      if (statusEl) {
        statusEl.textContent = `✓ Running: ${res.strategy_name} — results in Algo Arena tab`;
        statusEl.style.color = 'rgba(139,92,246,0.9)';
      }
      // Poll status after 30s
      setTimeout(async () => {
        try {
          const st = await Api.backtestStatus();
          if (st.available && statusEl) {
            statusEl.textContent = `Last: ${st.strategy_name} — ${(st.total_return_pct||0).toFixed(1)}% return, ${st.total_trades||0} trades`;
          }
        } catch(e) {}
      }, 30000);
    } else if (res.status === 'no_strategy') {
      if (statusEl) { statusEl.textContent = '⚠ No active strategies yet — promote one first'; statusEl.style.color = '#ff9900'; }
    }
  } catch(e) {
    if (statusEl) { statusEl.textContent = '✗ Error: ' + e.message; statusEl.style.color = '#ff4444'; }
  } finally {
    if (btn) { btn.disabled = false; btn.textContent = '▶ Run Backtest'; }
  }
}

async function triggerPaperCycle() {
  const statusEl = document.getElementById('pp-cycle-status');
  const btn = document.querySelector('[onclick="triggerPaperCycle()"]');
  if (statusEl) statusEl.textContent = '⟳ Running cycle…';
  if (btn) btn.disabled = true;
  try {
    const res = await fetch(`${API_CONFIG.BASE}/admin/paper-trade`, { method: 'POST' });
    const data = await res.json();
    const opened  = (data.opened || []).length;
    const closed  = (data.closed || []).length;
    const slClosed = (data.stopLossClosed || []).length;
    const tpClosed = (data.takeProfitClosed || []).length;
    const value   = Math.round(data.portfolioValue || 0).toLocaleString('en-IN');
    let msg = `✓ NAV ₹${value}`;
    if (opened)   msg += `  · Opened: ${opened}`;
    if (closed)   msg += `  · Closed: ${closed}`;
    if (slClosed) msg += `  · SL hit: ${slClosed}`;
    if (tpClosed) msg += `  · TP hit: ${tpClosed}`;
    if (data.status === 'no_signals') msg = '⚠ No signals today — NAV marked to market';
    if (statusEl) { statusEl.textContent = msg; statusEl.style.color = 'var(--accent)'; }
    await hydratePaperPortfolio();
  } catch(e) {
    if (statusEl) { statusEl.textContent = '✗ Error: ' + e.message; statusEl.style.color = '#ff4444'; }
  } finally {
    if (btn) btn.disabled = false;
  }
}

async function triggerPaperCycleForStrategy() {
  const input = document.getElementById('pp-strategy-id-input');
  const statusEl = document.getElementById('pp-strategy-cycle-status');
  const btn = document.querySelector('[onclick="triggerPaperCycleForStrategy()"]');
  const strategyId = (input ? input.value.trim() : '');
  if (!strategyId) {
    if (statusEl) { statusEl.textContent = '⚠ Enter a strategy ID first'; statusEl.style.color = '#ff9900'; }
    return;
  }
  if (statusEl) { statusEl.textContent = '⟳ Running…'; statusEl.style.color = 'var(--text-muted)'; }
  if (btn) btn.disabled = true;
  try {
    const res = await fetch(`${API_CONFIG.BASE}/admin/paper-trade-strategy`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ strategy_id: strategyId }),
    });
    const data = await res.json();
    if (data.status === 'error') {
      if (statusEl) { statusEl.textContent = '✗ ' + (data.error || 'Unknown error'); statusEl.style.color = '#ff4444'; }
    } else {
      const opened = (data.opened || []).length;
      const value  = Math.round(data.portfolioValue || 0).toLocaleString('en-IN');
      let msg = `✓ NAV ₹${value}`;
      if (opened) msg += `  · Opened: ${opened}`;
      if (data.status === 'no_signals') msg = '⚠ No signals for this strategy';
      if (statusEl) { statusEl.textContent = msg; statusEl.style.color = 'var(--accent)'; }
      await hydratePaperPortfolio();
    }
  } catch(e) {
    if (statusEl) { statusEl.textContent = '✗ ' + e.message; statusEl.style.color = '#ff4444'; }
  } finally {
    if (btn) btn.disabled = false;
  }
}

// ── Live hydration ────────────────────────────────────────────
async function hydratePaperPortfolio() {
  // Silently backfill equity curve from trade history on first load (idempotent)
  if (!sessionStorage.getItem('aqrti_eq_backfilled')) {
    Api.backfillEquity().then(() => sessionStorage.setItem('aqrti_eq_backfilled', '1'));
  }

  const [pp, perf, curve, alloc, trades, btStatus] = await Promise.all([
    Api.paperPortfolio().catch(() => { showError('Failed to load portfolio'); return null; }),
    Api.performance().catch(() => null),
    Api.equityCurve(90).catch(() => null),
    Api.paperAllocation().catch(() => null),
    Api.paperTrades(100).catch(() => null),
    Api.backtestStatus().catch(() => null),
  ]);

  if (!pp || !pp.positions) {
    showError('Portfolio API returned no positions data');
    return;
  }

  // Show last backtest result
  const btEl = document.getElementById('pp-backtest-status');
  if (btEl && btStatus && btStatus.available) {
    const ret = (btStatus.total_return_pct || 0).toFixed(1);
    const wr  = (btStatus.win_rate || 0).toFixed(0);
    const cls = parseFloat(ret) >= 0 ? 'color:#00cc66' : 'color:#ef4444';
    btEl.innerHTML = `Last: <b>${btStatus.strategy_name}</b> — <span style="${cls}">${ret}%</span> return · ${wr}% win rate · ${btStatus.total_trades||0} trades · ${btStatus.status||''}`;
  }

  const fmt  = (v, dec = 2) => (v != null && !isNaN(v)) ? Number(v).toFixed(dec) : '—';
  const fmtRs = v => v != null ? `₹${Math.round(v).toLocaleString('en-IN')}` : '—';
  const pnlCls = v => (v || 0) >= 0 ? 'positive' : 'negative';
  const pnlSign = v => (v || 0) >= 0 ? '+' : '';

  // ── KPI row ──
  if (pp && pp.portfolio) {
    const port = pp.portfolio;
    setDataPoint('pp-kpi-value',    fmtRs(port.totalValue), 'paper');
    setDataPoint('pp-kpi-cash',     fmtRs(port.currentCash), 'paper');
    setDataPoint('pp-kpi-cash-pct', `${fmt(port.cashPct, 1)}% of Portfolio`, 'paper');
    setDataPoint('pp-kpi-invested', `${fmtRs(port.investedCapital)} Deployed`, 'paper');
    const retEl = el('pp-kpi-return');
    if (retEl) {
      const ret = port.totalReturnPct || 0;
      retEl.textContent = `${pnlSign(ret)}${fmt(ret)}%`;
      retEl.className = 'kpi-sub ' + pnlCls(ret);
      retEl.title = `Source: paper | ${new Date().toISOString()}`;
    }
  }

  // Unrealized P&L across open positions
  if (pp && pp.positions && pp.positions.length) {
    const totalUnreal = pp.positions.reduce((s, p) => s + (p.unrealizedPnl || 0), 0);
    const totalInvested = pp.positions.reduce((s, p) => s + (p.capitalDeployed || 0), 0);
    const unrPct = totalInvested > 0 ? totalUnreal / totalInvested * 100 : 0;
    const urEl = el('pp-kpi-unrealized');
    if (urEl) { urEl.textContent = `${pnlSign(totalUnreal)}${fmtRs(totalUnreal)}`; urEl.className = 'kpi-value ' + pnlCls(totalUnreal); urEl.title = `Source: paper | ${new Date().toISOString()}`; }
    setDataPoint('pp-kpi-unrealized-pct', `${pnlSign(unrPct)}${fmt(unrPct, 2)}% open`, 'paper');
    setDataPoint('pp-kpi-positions', pp.positions.length, 'paper');
  }

  if (perf && perf.available) {
    const wr = perf.winRatePct || 0;
    const wrEl = el('pp-kpi-winrate');
    if (wrEl) { wrEl.textContent = `${fmt(wr, 1)}%`; wrEl.className = 'kpi-value ' + (wr >= 50 ? 'positive' : 'negative'); wrEl.title = `Source: paper | ${new Date().toISOString()}`; }
    setDataPoint('pp-kpi-trades',   `${perf.closedTrades || 0} Closed Trades`, 'paper');
    setDataPoint('pp-kpi-maxdd',    `${fmt(perf.maxDrawdownPct)}%`, 'paper');
    setDataPoint('pp-kpi-sharpe',   `Sharpe: ${fmt(perf.sharpeRatio)}`, 'paper');

    // Analytics tables
    const sign = v => (v || 0) >= 0 ? '+' : '';
    setDataPoint('pp-an-total-ret',  `${sign(perf.totalReturnPct)}${fmt(perf.totalReturnPct)}%`, 'paper');
    setDataPoint('pp-an-cagr',       `${fmt(perf.cagrPct)}%`, 'paper');
    setDataPoint('pp-an-sharpe',     fmt(perf.sharpeRatio), 'paper');
    setDataPoint('pp-an-sortino',    fmt(perf.sortinoRatio), 'paper');
    setDataPoint('pp-an-maxdd',      `${fmt(perf.maxDrawdownPct)}%`, 'paper');
    setDataPoint('pp-an-vol',        `${fmt(perf.volatilityAnn)}%`, 'paper');
    setDataPoint('pp-an-winrate',    `${fmt(perf.winRatePct)}%`, 'paper');
    setDataPoint('pp-an-pf',         fmt(perf.profitFactor), 'paper');
    setDataPoint('pp-an-expectancy', `${fmt(perf.expectancyPct)}%`, 'paper');
    setDataPoint('pp-an-avgwin',     `${fmt(perf.avgWinPct)}%`, 'paper');
    setDataPoint('pp-an-avgloss',    `${fmt(perf.avgLossPct)}%`, 'paper');
    setDataPoint('pp-an-hold',       fmt(perf.avgHoldingDays), 'paper');
    setDataPoint('pp-an-expo',       `${fmt(perf.avgExposurePct)}%`, 'paper');
    setDataPoint('pp-an-turnover',   `${fmt(perf.turnoverPct)}%`, 'paper');
  }

  // ── Strategy badge — show which strategy is driving trades ──
  const stratBadge = el('pp-strategy-badge');
  if (stratBadge) {
    const pos0 = pp && pp.positions && pp.positions[0];
    const stratName = pos0 && (pos0.strategyName || pos0.strategyId);
    stratBadge.textContent = stratName ? `◈ Algo: ${stratName}` : `◈ Best Fitness Algo (auto-selected)`;
  }

  // ── Equity curve chart ──
  const curveCanvas = el('ppEquityCurveChart');
  const curveEmpty  = el('pp-equity-empty');
  if (curve && curve.labels && curve.labels.length > 1) {
    if (curveCanvas) curveCanvas.style.display = '';
    if (curveEmpty)  curveEmpty.style.display  = 'none';
    ChartRegistry.create('ppEquityCurveChart', {
      type: 'line',
      data: {
        labels: curve.labels,
        datasets: [{
          data: curve.values,
          borderColor: '#ff8c00', borderWidth: 2, pointRadius: 0, tension: 0.3, fill: true,
          backgroundColor: (ctx) => {
            const g = ctx.chart.ctx.createLinearGradient(0, 0, 0, ctx.chart.height);
            g.addColorStop(0, 'rgba(255,140,0,0.18)');
            g.addColorStop(1, 'rgba(255,140,0,0.00)');
            return g;
          },
        }],
      },
      options: {
        responsive: true, maintainAspectRatio: false,
        plugins: { legend: { display: false }, tooltip: { callbacks: { label: ctx => ` ₹${Math.round(ctx.parsed.y).toLocaleString('en-IN')}` }}},
        scales: {
          x: { ticks: { maxTicksLimit: 8, maxRotation: 0, color: '#888', font: { size: 9 }}, grid: { color: 'rgba(255,255,255,0.04)' }},
          y: { ticks: { callback: v => `₹${(v/1000).toFixed(0)}K`, maxTicksLimit: 5, color: '#888', font: { size: 9 }}, grid: { color: 'rgba(255,255,255,0.04)' }},
        },
      },
    });
  } else {
    if (curveCanvas) curveCanvas.style.display = 'none';
    if (curveEmpty)  { curveEmpty.style.display = ''; curveEmpty.textContent = 'No equity history yet — run paper cycles to build the curve.'; }
  }

  // ── Allocation doughnut ──
  const allocData = (alloc && alloc.some(a => a.type === 'equity'))
    ? alloc
    : (pp && pp.positions && pp.positions.length)
        ? [...pp.positions.map(p => ({ symbol: p.symbol, weightPct: p.weightPct, type: 'equity' })),
           { symbol: 'CASH', weightPct: pp.portfolio ? pp.portfolio.cashPct : 0, type: 'cash' }]
        : alloc;

  const totalExpo = allocData ? allocData.filter(a => a.type === 'equity').reduce((s, a) => s + (a.weightPct || 0), 0) : 0;
  _set('pp-alloc-exposure', `${fmt(totalExpo, 0)}% Invested`);

  if (allocData && allocData.length) {
    const PALETTE = ['rgba(255,140,0,0.85)','rgba(34,197,94,0.7)','rgba(59,130,246,0.7)',
      'rgba(245,158,11,0.7)','rgba(239,68,68,0.7)','rgba(147,51,234,0.7)',
      'rgba(236,72,153,0.7)','rgba(0,170,255,0.7)','rgba(251,146,60,0.7)',
      'rgba(20,184,166,0.7)','rgba(248,113,113,0.7)','rgba(167,243,208,0.7)',
      'rgba(255,255,255,0.12)'];
    ChartRegistry.create('ppAllocationChart', {
      type: 'doughnut',
      data: {
        labels: allocData.map(a => a.symbol),
        datasets: [{ data: allocData.map(a => a.weightPct), backgroundColor: allocData.map((_, i) => PALETTE[i % 13]), borderWidth: 1, borderColor: 'rgba(255,255,255,0.06)' }],
      },
      options: {
        responsive: true, maintainAspectRatio: false,
        plugins: { legend: { position: 'right', labels: { color: '#aaa', font: { size: 10 }, boxWidth: 10 }}, tooltip: { callbacks: { label: ctx => ` ${ctx.label}: ${ctx.parsed.toFixed(1)}%` }}},
        cutout: '55%',
      },
    });
  }

  // ── Open positions table — full trader view ──
  const pbody = el('pp-full-positions-body');
  if (pbody) {
    const positions = pp && pp.positions || [];
    _set('pp-open-count', `${positions.length} position${positions.length !== 1 ? 's' : ''}`);
    if (positions.length) {
      pbody.innerHTML = positions.map(p => {
        const pc  = pnlCls(p.unrealizedPct);
        const ps  = pnlSign(p.unrealizedPct);
        const slPct = p.entryPrice > 0 ? ((p.stopLoss - p.entryPrice) / p.entryPrice * 100) : 0;
        const tpPct = p.entryPrice > 0 ? ((p.target   - p.entryPrice) / p.entryPrice * 100) : 0;
        const heldDays = p.entryDate ? Math.floor((Date.now() - new Date(p.entryDate)) / 86400000) : 0;
        const maxDays = 20;
        const daysLeft = maxDays - heldDays;
        const heldColor = daysLeft <= 3 ? 'var(--negative)' : daysLeft <= 7 ? '#f5a623' : 'var(--text-muted)';
        return `<tr>
          <td><strong>${p.symbol}</strong></td>
          <td style="color:var(--text-muted);font-size:0.7rem">${p.sector || '—'}</td>
          <td style="color:var(--text-muted)">${p.entryDate || '—'}</td>
          <td style="color:${heldColor};font-size:0.75rem;white-space:nowrap" title="${daysLeft}d until auto-close">${heldDays}d <span style="opacity:0.6">/ ${maxDays}d</span></td>
          <td>₹${fmt(p.entryPrice)}</td>
          <td><strong>₹${fmt(p.currentPrice)}</strong></td>
          <td style="color:var(--text-muted)">${fmt(p.shares, 2)}</td>
          <td>${fmtRs(p.capitalDeployed)}</td>
          <td class="${pc}"><strong>${ps}₹${Math.round(p.unrealizedPnl || 0).toLocaleString('en-IN')}</strong><br><span style="font-size:0.68rem">${ps}${fmt(p.unrealizedPct)}%</span></td>
          <td class="negative" title="Stop Loss">₹${fmt(p.stopLoss)}<br><span style="font-size:0.65rem">${fmt(slPct)}%</span></td>
          <td class="positive" title="Target">₹${fmt(p.target)}<br><span style="font-size:0.65rem">+${fmt(tpPct)}%</span></td>
          <td style="font-size:0.68rem;color:var(--accent);white-space:nowrap" title="${p.strategyId || ''}">${p.strategyName || p.strategyId || '<span style="color:var(--text-muted)">—</span>'}</td>
          <td>${confBarHTML(Math.round(p.confidence || 0))}</td>
          <td>${dirBadge(p.direction || '—')}</td>
        </tr>`;
      }).join('');
    } else {
      pbody.innerHTML = `<tr><td colspan="13" style="color:var(--text-muted);text-align:center;padding:20px">No open positions — click ▶ Run Trade Cycle</td></tr>`;
    }
  }

  // ── Trade history table — full detail ──
  const tbody = el('pp-trades-body');
  if (tbody) {
    const tradeList = trades || [];
    _set('pp-trades-count', `${tradeList.length} closed`);
    if (tradeList.length) {
      tbody.innerHTML = tradeList.map(t => {
        const pc = pnlCls(t.grossPnlPct);
        const ps = pnlSign(t.grossPnlPct);
        const reasonColor = t.exitReason === 'stop_loss' ? 'negative' : t.exitReason === 'take_profit' ? 'positive' : '';
        return `<tr>
          <td><strong>${t.symbol}</strong></td>
          <td style="color:var(--text-muted);font-size:0.7rem">${t.sector || '—'}</td>
          <td style="color:var(--text-muted)">${t.entryDate || '—'}</td>
          <td style="color:var(--text-muted)">${t.exitDate || '—'}</td>
          <td style="color:var(--text-muted)">${t.holdingDays || 0}d</td>
          <td>₹${fmt(t.entryPrice)}</td>
          <td>₹${fmt(t.exitPrice)}</td>
          <td style="color:var(--text-muted)">${fmt(t.shares, 2)}</td>
          <td>${fmtRs(t.capitalDeployed)}</td>
          <td class="${pc}"><strong>${ps}${fmtRs(t.grossPnl)}</strong></td>
          <td class="${pc}"><strong>${ps}${fmt(t.grossPnlPct)}%</strong></td>
          <td class="${reasonColor}" style="font-size:0.7rem;letter-spacing:0.03em">${(t.exitReason || '—').replace(/_/g,' ').toUpperCase()}</td>
          <td style="font-size:0.68rem;color:var(--accent);white-space:nowrap" title="${t.strategyId || ''}">${t.strategyName || t.strategyId || '<span style="color:var(--text-muted)">—</span>'}</td>
          <td>${confBarHTML(Math.round(t.confidence || 0))}</td>
        </tr>`;
      }).join('');
    } else {
      tbody.innerHTML = `<tr><td colspan="13" style="color:var(--text-muted);text-align:center;padding:20px">No closed trades yet — run a cycle and let positions close</td></tr>`;
    }
  }
}

// ── Intraday MTM trigger ─────────────────────────────────────
async function triggerMTM() {
  const statusEl = document.getElementById('pp-cycle-status');
  try {
    if (statusEl) { statusEl.textContent = '⟳ Marking to market…'; statusEl.style.color = 'var(--accent)'; }
    const res  = await fetch(`${API_CONFIG.BASE}/admin/paper-mtm`, { method: 'POST' });
    const data = await res.json();
    const sl = (data.stopLossClosed || []).length;
    const tp = (data.takeProfitClosed || []).length;
    const ex = (data.expired || []).length;
    const nav = Math.round(data.totalValue || 0).toLocaleString('en-IN');
    let msg = `✓ NAV ₹${nav}`;
    if (sl) msg += `  · SL hit: ${sl}`;
    if (tp) msg += `  · TP hit: ${tp}`;
    if (ex) msg += `  · Expired: ${ex}`;
    if (data.lossesRefined) msg += `  · Algos refined: ${data.lossesRefined}`;
    if (statusEl) { statusEl.textContent = msg; statusEl.style.color = sl || ex ? '#f59e0b' : 'var(--positive)'; }
    await hydratePaperPortfolio();
  } catch(e) {
    if (statusEl) { statusEl.textContent = '✗ MTM error: ' + e.message; statusEl.style.color = '#ff4444'; }
  }
}

// ── Real-time paper portfolio polling ────────────────────────
let _ppPollInterval = null;

function startPaperPolling() {
  if (_ppPollInterval) return;
  // Poll every 60s — refresh positions with live prices and check SL/TP/expiry
  _ppPollInterval = setInterval(async () => {
    const page = document.querySelector('.page.active');
    if (!page || page.id !== 'page-paper') return;
    // Lightweight: just refresh the UI from current backend state (no full cycle)
    await hydratePaperPortfolio();
    // Also run intraday MTM silently to close any triggered SL/TP
    try {
      await fetch(`${API_CONFIG.BASE}/admin/paper-mtm`, { method: 'POST' });
    } catch(_) {}
  }, 60000);
}

function stopPaperPolling() {
  if (_ppPollInterval) { clearInterval(_ppPollInterval); _ppPollInterval = null; }
}


