// ui/pages/overview.js - split from app.js (ARCH-5), see CHANGELOG

// ── Overview — full live hydration ───────────────────────────
async function hydrateOverviewAlerts() {
  const body = el('alerts-body');
  if (!body) return;
  const data = await Api.findingsSummary(3);
  const items = [...(data?.critical || []), ...(data?.high || [])].slice(0, 6);
  const ICONS = { critical: '▲', high: '◎', normal: '◆', low: '◇' };
  const CLASS = { critical: 'critical', high: 'warning' };
  if (!items.length) {
    body.innerHTML = '<div style="color:var(--text-muted);text-align:center;padding:12px 0">No alerts today</div>';
    return;
  }
  body.innerHTML = items.map(f => `
    <div class="alert-item ${CLASS[f.urgency] || 'info'}">
      <div class="alert-icon">${ICONS[f.urgency] || '◆'}</div>
      <div class="alert-content">
        <div class="alert-title">${f.title || '—'}</div>
        <div class="alert-sub">${f.implication || f.description || ''}</div>
      </div>
    </div>`).join('');
}

function showErrorBanner(msg) {
  const target = document.getElementById('alerts-body');
  if (target) target.innerHTML = `<div class="alert-item critical"><div class="alert-icon">▲</div><div class="alert-content"><div class="alert-title">API Error</div><div class="alert-sub">${msg}</div></div></div>`;
}

async function hydrateOverview() {
  const [ov, curve] = await Promise.all([
    Api.overview().catch(() => { showErrorBanner('Failed to load overview data'); return null; }),
    Api.equityCurve(30).catch(() => null),
  ]);
  hydrateOverviewAlerts();
  if (!ov) return;

  if (ov.portfolioValue != null) {
    const pv = el('kpi-portfolio');
    if (pv) animateCounter(pv, Math.round(ov.portfolioValue), '₹', '', 1200);
  }
  if (ov.dailyPnl != null) {
    const pnlEl = el('kpi-daily-pnl');
    if (pnlEl) {
      pnlEl.textContent = `${ov.dailyPnl >= 0 ? '+' : ''}₹${Math.abs(Math.round(ov.dailyPnl)).toLocaleString('en-IN')}`;
      pnlEl.className = 'kpi-value ' + (ov.dailyPnl >= 0 ? 'positive' : 'negative');
      pnlEl.title = `Source: overview | ${new Date().toISOString()}`;
    }
    const pctEl = el('kpi-daily-pct');
    if (pctEl) {
      pctEl.textContent = `${ov.dailyPnlPct >= 0 ? '+' : ''}${(ov.dailyPnlPct || 0).toFixed(2)}%`;
      pctEl.className = 'kpi-sub ' + (ov.dailyPnl >= 0 ? 'positive' : 'negative');
    }
  }
  if (ov.openPositions != null) {
    setDataPoint('kpi-positions', ov.openPositions, 'overview');
    if (ov.deployedCapital != null) setDataPoint('kpi-deployed', `₹${Math.round(ov.deployedCapital).toLocaleString('en-IN')} Deployed`, 'overview');
  }
  if (ov.activePredictions != null) {
    setDataPoint('kpi-predictions', ov.activePredictions, 'overview');
    if (ov.avgConfidence != null) setDataPoint('kpi-avg-conf', `Avg Conf: ${(ov.avgConfidence||0).toFixed(0)}%`, 'overview');
  }
  if (ov.winRate30d != null) {
    setDataPoint('kpi-winrate', `${ov.winRate30d.toFixed(1)}%`, 'overview');
    if (ov.totalTrades30d != null) setDataPoint('kpi-trades-30d', `${ov.totalTrades30d} Trades`, 'overview');
  }
  // Knowledge score: show "Computing" if 0 but system is running
  if (ov.knowledgeScore != null) {
    const ks = ov.knowledgeScore;
    setDataPoint('kpi-knowledge', ks > 0 ? `${Math.round(ks)} / 100` : 'Computing…', 'overview');
    setDataPoint('kpi-knowledge-sub', ks > 0 ? `${ov.activeStrategies || 0} Active Algos` : `${ov.activeStrategies || 0} Algos Active`, 'overview');
  }
  // Show strategy count on overview
  if (ov.activeStrategies != null) {
    const stratEl = el('kpi-strategies');
    if (stratEl) { stratEl.textContent = ov.activeStrategies; }
  }
  if (ov.regime) {
    setDataPoint('topbar-regime', ov.regime, 'overview');
    const pill = document.getElementById('regime-pill');
    if (pill) pill.className = 'regime-badge badge-' + ov.regime.toLowerCase().replace(/\s+/g, '-');
  }

  // Nav badge — overview shows open position count
  if (ov.openPositions != null) {
    const ob = el('badge-overview');
    if (ob) ob.textContent = ov.openPositions;
  }

  // Equity curve
  if (curve && curve.labels && curve.labels.length) {
    ChartRegistry.create('equityCurveChart', {
      type: 'line',
      data: {
        labels: curve.labels,
        datasets: [{
          data: curve.values,
          borderColor: '#ff8c00', borderWidth: 2, pointRadius: 0, tension: 0.3, fill: true,
          backgroundColor: (ctx) => {
            const g = ctx.chart.ctx.createLinearGradient(0, 0, 0, ctx.chart.height);
            g.addColorStop(0, 'rgba(255,140,0,0.14)');
            g.addColorStop(1, 'rgba(255,140,0,0.00)');
            return g;
          },
        }],
      },
      options: {
        responsive: true, maintainAspectRatio: false,
        plugins: { legend: { display: false }, tooltip: { callbacks: { label: ctx => ` ₹${ctx.parsed.y.toLocaleString('en-IN')}` } } },
        scales: {
          x: { ticks: { maxTicksLimit: 8, maxRotation: 0 } },
          y: { ticks: { callback: v => `₹${(v / 1000).toFixed(0)}K`, maxTicksLimit: 5 } },
        },
      },
    });
  }

  // Top predictions table
  const preds = await Api.predictions({ limit: 8 });
  if (preds && preds.length) {
    const tbody = el('top-predictions-body');
    if (tbody) {
      tbody.innerHTML = preds.map(p => {
        const expRet = p.expectedReturn != null
          ? (p.expectedReturn >= 0 ? `+${p.expectedReturn.toFixed(2)}%` : `${p.expectedReturn.toFixed(2)}%`)
          : '—';
        return `
          <tr>
            <td><strong>${p.symbol}</strong></td>
            <td>${dirBadge(p.direction)}</td>
            <td>${confBarHTML(Math.round(p.confidence || 0))}</td>
            <td class="${(p.expectedReturn || 0) >= 0 ? 'positive' : 'negative'}">${expRet}</td>
            <td>${riskBadge(p.risk || 'Medium')}</td>
          </tr>`;
      }).join('');
    }
  }
  loadWatchlist();
}

// ── Market — full live hydration ──────────────────────────────
// ══════════════════════════════════════════════════════════════
// WATCHLIST
// ══════════════════════════════════════════════════════════════
async function loadWatchlist() {
  const [wlData, liveData] = await Promise.all([
    Api.watchlist().catch(() => null),
    Api.liveStockPrices().catch(() => null),
  ]);

  const symbols = wlData?.symbols || [];
  const liveMap = {};
  (liveData || []).forEach(s => { liveMap[s.key] = s; });

  const tbody = document.getElementById('watchlist-body');
  if (!tbody) return;
  if (!symbols.length) {
    tbody.innerHTML = '<tr><td colspan="5" style="text-align:center;color:#444;padding:12px">No symbols in watchlist</td></tr>';
    return;
  }

  tbody.innerHTML = symbols.map(sym => {
    const live   = liveMap[sym] || liveMap[sym.toLowerCase()] || null;
    const price  = live?.price;
    const chgPct = live?.changePct;
    const cls    = chgPct != null ? (chgPct >= 0 ? 'positive' : 'negative') : '';
    return `<tr>
      <td><strong>${sym}</strong></td>
      <td>${price != null ? '₹' + price.toFixed(1) : '—'}</td>
      <td class="${cls}">${chgPct != null ? (chgPct >= 0 ? '+' : '') + chgPct.toFixed(2) + '%' : '—'}</td>
      <td><span class="badge neutral">—</span></td>
      <td><button class="panel-action-btn" onclick="removeFromWatchlist('${sym}')" style="font-size:0.58rem;padding:2px 6px;color:#ff3333;border-color:#ff3333">✕</button></td>
    </tr>`;
  }).join('');
}

async function addToWatchlist() {
  const input = document.getElementById('watchlist-add-input');
  const sym   = input?.value?.toUpperCase().trim();
  if (!sym) return;
  await Api.watchlistAdd(sym);
  if (input) input.value = '';
  loadWatchlist();
}

async function removeFromWatchlist(sym) {
  await Api.watchlistRemove(sym);
  loadWatchlist();
}

// ── Overview strip — portfolio summary + performance ─────────
// (relocated here from paper.js: #pp-positions-body / #pp-position-count
// live inside <section id="page-overview">, not page-paper)
async function hydratePaperPortfolioStrip() {
  const [pp, perf] = await Promise.all([Api.paperPortfolio(), Api.performance()]);

  if (pp && pp.positions && pp.positions.length) {
    const tbody = el('pp-positions-body');
    if (tbody) {
      tbody.innerHTML = pp.positions.slice(0, 6).map(p => {
        const pnlClass = (p.unrealizedPct || 0) >= 0 ? 'positive' : 'negative';
        const sign     = (p.unrealizedPct || 0) >= 0 ? '+' : '';
        return `
          <tr>
            <td><strong>${p.symbol}</strong></td>
            <td style="color:var(--text-muted)">₹${(p.entryPrice || 0).toFixed(2)}</td>
            <td>₹${(p.currentPrice || 0).toFixed(2)}</td>
            <td>${(p.weightPct || 0).toFixed(1)}%</td>
            <td class="${pnlClass}">${sign}${(p.unrealizedPct || 0).toFixed(2)}%</td>
            <td>${confBarHTML(Math.round(p.confidence || 0))}</td>
          </tr>`;
      }).join('');
      const cnt = el('pp-position-count');
      if (cnt) cnt.textContent = `${pp.positions.length} Open`;
    }
  }

  if (perf && perf.available) {
    const ret = perf.totalReturnPct || 0;
    const retEl = el('pp-total-return');
    if (retEl) { retEl.textContent = `${ret >= 0 ? '+' : ''}${ret.toFixed(2)}%`; retEl.className = 'kpi-value ' + (ret >= 0 ? 'positive' : 'negative'); retEl.title = `Source: overview | ${new Date().toISOString()}`; }
    const shrEl = el('pp-sharpe');
    if (shrEl) { shrEl.textContent = (perf.sharpeRatio || 0).toFixed(2); shrEl.className = 'kpi-value ' + ((perf.sharpeRatio || 0) >= 1 ? 'positive' : 'neutral'); shrEl.title = `Source: overview | ${new Date().toISOString()}`; }
    const sorEl = el('pp-sortino');
    if (sorEl) { sorEl.textContent = (perf.sortinoRatio || 0).toFixed(2); sorEl.title = `Source: overview | ${new Date().toISOString()}`; }
    const ddEl = el('pp-max-dd');
    if (ddEl) { ddEl.textContent = `${(perf.maxDrawdownPct || 0).toFixed(2)}%`; ddEl.className = 'kpi-value negative'; ddEl.title = `Source: overview | ${new Date().toISOString()}`; }
    const wrEl = el('pp-win-rate');
    if (wrEl) { wrEl.textContent = `${(perf.winRatePct || 0).toFixed(1)}%`; wrEl.className = 'kpi-value ' + ((perf.winRatePct || 0) >= 50 ? 'positive' : 'negative'); wrEl.title = `Source: overview | ${new Date().toISOString()}`; }
    const pfEl = el('pp-profit-factor');
    if (pfEl) { pfEl.textContent = (perf.profitFactor || 0).toFixed(2); pfEl.className = 'kpi-value ' + ((perf.profitFactor || 0) >= 1 ? 'positive' : 'negative'); pfEl.title = `Source: overview | ${new Date().toISOString()}`; }
    const dateEl = el('pp-perf-date');
    if (dateEl) { dateEl.textContent = perf.date || '—'; dateEl.title = `Source: overview | ${new Date().toISOString()}`; }
  }
}

// ══════════════════════════════════════════════════════════════
