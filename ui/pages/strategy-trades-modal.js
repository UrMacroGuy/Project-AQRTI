// ui/pages/strategy-trades-modal.js - split from app.js (ARCH-5), see CHANGELOG

// ═══════════════════════════════════════════════════════════════
// STRATEGY TRADE LOG + REPLAY MODAL
// ═══════════════════════════════════════════════════════════════

let _stmChart = null;
let _stmCurrentId = null;

async function openStrategyTrades(strategyId) {
  _stmCurrentId = strategyId;

  // ── Inline inspector panel (strategy tab) ────────────────────
  const inspBody = document.getElementById('src-inspector-body');
  const inspLabel = document.getElementById('src-inspector-label');
  if (inspBody) {
    if (inspLabel) inspLabel.textContent = 'Loading…';
    inspBody.innerHTML = '<div style="padding:1rem;color:var(--text-muted);font-size:0.8rem">Fetching backtest trades…</div>';
  }

  const modal = document.getElementById('strategy-trades-modal');
  if (modal) modal.style.display = 'block';
  setDataPoint('stm-title', 'Loading…', 'strategy-trades');
  setDataPoint('stm-kpi-trades', '…', 'strategy-trades');
  setDataPoint('stm-kpi-wr', '…', 'strategy-trades');
  setDataPoint('stm-kpi-sharpe', '…', 'strategy-trades');
  setDataPoint('stm-kpi-fitness', '…', 'strategy-trades');
  const tradesBody = document.getElementById('stm-trades-body');
  if (tradesBody) tradesBody.innerHTML =
    '<tr><td colspan="9" style="text-align:center;color:var(--text-muted);padding:20px">Fetching trades…</td></tr>';
  const replayStatus = document.getElementById('stm-replay-status');
  if (replayStatus) replayStatus.textContent = '';

  const data = await apiFetch('/strategies/' + strategyId + '/trades');
  if (!data) {
    setDataPoint('stm-title', 'Error — backend offline', 'strategy-trades');
    if (inspBody) inspBody.innerHTML = '<div style="padding:1rem;color:var(--negative)">Could not load trades — backend offline.</div>';
    return;
  }

  setDataPoint('stm-title', data.name || strategyId, 'strategy-trades');
  const metaEl = document.getElementById('stm-meta');
  if (metaEl) metaEl.innerHTML =
    '<span>Family: ' + (data.family || '—') + '</span>' +
    '<span>Status: ' + (data.status || '').toUpperCase() + '</span>' +
    '<span>ID: ' + strategyId + '</span>';
  setDataPoint('stm-kpi-trades', data.trade_count || 0, 'strategy-trades');
  setDataPoint('stm-kpi-wr',     data.win_rate  != null ? data.win_rate.toFixed(1)  + '%' : '—', 'strategy-trades');
  setDataPoint('stm-kpi-sharpe', data.sharpe    != null ? data.sharpe.toFixed(2)         : '—', 'strategy-trades');
  setDataPoint('stm-kpi-fitness',data.fitness   != null ? data.fitness.toFixed(1)        : '—', 'strategy-trades');

  // Try strategy P&L chart from /strategy-performance/{id}/chart first
  const chartData = await apiFetch('/strategy-performance/' + strategyId + '/chart');
  if (chartData && chartData.cumulative_pnl && chartData.cumulative_pnl.length > 1) {
    _stmDrawChart(chartData.cumulative_pnl, chartData.labels, true);
  } else {
    _stmDrawChart(data.equityCurve || [], (data.trades || []).map(t => t.exitDate || ''));
  }

  const tradeRowsHtml = (data.trades && data.trades.length) ? data.trades.map((t, i) => {
    const col  = (t.pnlPct||0) > 0 ? 'var(--positive)' : (t.pnlPct||0) < 0 ? 'var(--negative)' : 'var(--text-muted)';
    const sign = (t.pnlPct||0) > 0 ? '+' : '';
    return '<tr style="border-bottom:1px solid var(--border-faint)">' +
      '<td style="padding:5px 8px;color:var(--text-muted)">' + (i+1) + '</td>' +
      '<td style="padding:5px 8px;font-weight:600">' + t.symbol + '</td>' +
      '<td style="padding:5px 8px;color:var(--text-muted);font-size:0.68rem">' + (t.entryDate||'—') + '</td>' +
      '<td style="padding:5px 8px;color:var(--text-muted);font-size:0.68rem">' + (t.exitDate||'—') + '</td>' +
      '<td style="padding:5px 8px;text-align:right">' + (t.entryPrice!=null?t.entryPrice.toFixed(2):'—') + '</td>' +
      '<td style="padding:5px 8px;text-align:right">' + (t.exitPrice!=null?t.exitPrice.toFixed(2):'—') + '</td>' +
      '<td style="padding:5px 8px;text-align:right;color:' + col + ';font-weight:600">' + (t.pnlPct!=null?sign+t.pnlPct.toFixed(2)+'%':'—') + '</td>' +
      '<td style="padding:5px 8px;text-align:right;color:var(--text-muted)">' + (t.holdingDays||0) + '</td>' +
      '<td style="padding:5px 8px;color:var(--text-muted);font-size:0.68rem">' + (t.exitReason||'—') + '</td>' +
      '</tr>';
  }).join('') : '<tr><td colspan="9" style="text-align:center;color:var(--text-muted);padding:20px">No backtest trades yet. Click Replay Backtest to generate them.</td></tr>';

  const tbody = document.getElementById('stm-trades-body');
  if (tbody) tbody.innerHTML = tradeRowsHtml;

  // ── Update inline inspector panel on strategy tab ─────────────
  if (inspBody) {
    if (inspLabel) inspLabel.textContent = data.name || strategyId;
    const statusColor = { active: 'var(--positive)', promoted: 'var(--accent)', shadow: 'var(--text-muted)' }[data.status] || 'var(--text-muted)';
    const wins  = (data.trades || []).filter(t => (t.pnlPct||0) > 0).length;
    const total = (data.trades || []).length;
    inspBody.innerHTML = `
      <div style="display:grid;grid-template-columns:repeat(4,1fr);gap:8px;padding:10px 0;border-bottom:1px solid var(--border-faint);margin-bottom:8px">
        <div style="text-align:center"><div style="font-size:0.65rem;color:var(--text-muted)">STATUS</div><div style="font-size:0.75rem;font-weight:700;color:${statusColor}">${(data.status||'—').toUpperCase()}</div></div>
        <div style="text-align:center"><div style="font-size:0.65rem;color:var(--text-muted)">FITNESS</div><div style="font-size:0.75rem;font-weight:700;color:var(--accent)">${data.fitness!=null?data.fitness.toFixed(1):'—'}</div></div>
        <div style="text-align:center"><div style="font-size:0.65rem;color:var(--text-muted)">SHARPE</div><div style="font-size:0.75rem;font-weight:700">${data.sharpe!=null?data.sharpe.toFixed(2):'—'}</div></div>
        <div style="text-align:center"><div style="font-size:0.65rem;color:var(--text-muted)">WIN RATE</div><div style="font-size:0.75rem;font-weight:700;color:var(--positive)">${data.win_rate!=null?data.win_rate.toFixed(0)+'%':'—'}</div></div>
      </div>
      <div style="font-size:0.68rem;color:var(--text-muted);padding:0 0 8px;font-family:var(--font-mono)">${data.family||''} — Gen ${data.generation||0} — ${total} trades (${wins}W/${total-wins}L)</div>
      <div style="max-height:200px;overflow-y:auto">
        <table class="data-table compact" style="font-size:0.68rem">
          <thead><tr><th>#</th><th>Symbol</th><th>Entry</th><th>Exit</th><th>P&L%</th><th>Days</th><th>Reason</th></tr></thead>
          <tbody>${total ? (data.trades||[]).slice(0,20).map((t,i) => {
            const c = (t.pnlPct||0)>0?'var(--positive)':(t.pnlPct||0)<0?'var(--negative)':'var(--text-muted)';
            const s = (t.pnlPct||0)>0?'+':'';
            return `<tr><td style="color:var(--text-muted)">${i+1}</td><td><b>${t.symbol}</b></td><td style="color:var(--text-muted)">${t.entryDate||'—'}</td><td style="color:var(--text-muted)">${t.exitDate||'—'}</td><td style="color:${c};font-weight:600">${t.pnlPct!=null?s+t.pnlPct.toFixed(2)+'%':'—'}</td><td style="color:var(--text-muted)">${t.holdingDays||0}d</td><td style="color:var(--text-muted)">${t.exitReason||'—'}</td></tr>`;
          }).join('') : '<tr><td colspan="7" style="color:var(--text-muted);text-align:center;padding:10px">No trades</td></tr>'}</tbody>
        </table>
      </div>`;
  }
}

function _stmDrawChart(values, labels, isCumPnl = false) {
  const canvas = document.getElementById('stm-equity-chart');
  if (!canvas) return;
  if (_stmChart) { _stmChart.destroy(); _stmChart = null; }
  if (!values.length) return;
  const isPositive = values[values.length - 1] >= (isCumPnl ? 0 : 100);
  const lineColor  = isPositive ? 'var(--positive)' : 'var(--negative)';
  const fillColor0 = isPositive ? 'rgba(240,240,242,0.14)' : 'rgba(154,154,159,0.14)';
  _stmChart = new Chart(canvas, {
    type: 'line',
    data: {
      labels: labels,
      datasets: [
        { label: isCumPnl ? 'Cum. P&L %' : 'Equity', data: values, borderColor: lineColor, borderWidth: 2,
          pointRadius: values.length > 60 ? 0 : 3, tension: 0.3, fill: true,
          backgroundColor: function(ctx){ const g=ctx.chart.ctx.createLinearGradient(0,0,0,ctx.chart.height); g.addColorStop(0,fillColor0); g.addColorStop(1,'rgba(0,0,0,0.00)'); return g; } },
        { label: 'Baseline', data: new Array(values.length).fill(isCumPnl ? 0 : 100), borderColor: 'rgba(255,255,255,0.15)', borderWidth: 1, borderDash: [4,4], pointRadius: 0 },
      ],
    },
    options: {
      responsive: true, maintainAspectRatio: false, animation: { duration: 400 },
      plugins: { legend: { display: false },
        tooltip: { callbacks: { label: ctx => isCumPnl ? `${ctx.parsed.y >= 0 ? '+' : ''}${ctx.parsed.y.toFixed(2)}%` : `${ctx.parsed.y.toFixed(2)}` } },
      },
      scales: {
        x: { ticks: { maxTicksLimit: 10, maxRotation: 0, font: { size: 9 } }, grid: { color: 'rgba(255,255,255,0.04)' } },
        y: { ticks: { font: { size: 9 } }, grid: { color: 'rgba(255,255,255,0.04)' } },
      },
    },
  });
}

async function runStrategyReplay() {
  if (!_stmCurrentId) return;
  const btn    = document.getElementById('stm-replay-btn');
  const status = document.getElementById('stm-replay-status');
  if (btn) { btn.disabled = true; btn.textContent = 'Replaying…'; }
  if (status) status.textContent = 'Running backtest…';
  try {
    const data = await apiPost('/strategies/' + _stmCurrentId + '/replay');
    if (!data || !data.frames) { if (status) status.textContent = 'Replay failed'; return; }
    if (status) status.textContent = data.trade_count + ' trades · sharpe ' + (data.sharpe||0).toFixed(2) + ' · equity ' + (data.finalEquity||100).toFixed(1);

    const frames = data.frames;
    if (_stmChart) { _stmChart.destroy(); _stmChart = null; }
    const canvas = document.getElementById('stm-equity-chart');
    if (!canvas) return;
    const eqData = new Array(frames.length).fill(null);
    _stmChart = new Chart(canvas, {
      type: 'line',
      data: {
        labels: frames.map(f => f.exitDate || '—'),
        datasets: [
          { label: 'Equity', data: eqData, borderColor: 'var(--accent)', borderWidth: 2,
            pointRadius: frames.length > 80 ? 0 : 4,
            pointBackgroundColor: frames.map(f => f.result==='win'?'rgba(240,240,242,0.9)':f.result==='loss'?'rgba(154,154,159,0.9)':'rgba(255,255,255,0.3)'),
            tension: 0.2, fill: true, backgroundColor: 'rgba(232,232,234,0.06)' },
          { label: 'Base', data: new Array(frames.length).fill(100), borderColor: 'rgba(255,255,255,0.12)', borderWidth: 1, borderDash: [4,4], pointRadius: 0 },
        ],
      },
      options: {
        responsive: true, maintainAspectRatio: false, animation: false,
        plugins: { legend: { display: false } },
        scales: {
          x: { ticks: { maxTicksLimit: 10, font: { size: 9 } }, grid: { color: 'rgba(255,255,255,0.04)' } },
          y: { ticks: { font: { size: 9 } }, grid: { color: 'rgba(255,255,255,0.04)' } },
        },
      },
    });

    const tbody = document.getElementById('stm-trades-body');
    if (tbody) {
      tbody.innerHTML = frames.map(function(f, idx) {
        const col  = f.result==='win'?'var(--positive)':f.result==='loss'?'var(--negative)':'var(--text-muted)';
        const sign = (f.pnlPct||0) > 0 ? '+' : '';
        return '<tr id="stm-row-' + idx + '" style="border-bottom:1px solid var(--border-faint)">' +
          '<td style="padding:5px 8px;color:var(--text-muted)">' + (idx+1) + '</td>' +
          '<td style="padding:5px 8px;font-weight:600">' + f.symbol + '</td>' +
          '<td style="padding:5px 8px;color:var(--text-muted);font-size:0.68rem">' + (f.entryDate||'—') + '</td>' +
          '<td style="padding:5px 8px;color:var(--text-muted);font-size:0.68rem">' + (f.exitDate||'—') + '</td>' +
          '<td style="padding:5px 8px;text-align:right">' + (f.entryPrice!=null?f.entryPrice.toFixed(2):'—') + '</td>' +
          '<td style="padding:5px 8px;text-align:right">' + (f.exitPrice!=null?f.exitPrice.toFixed(2):'—') + '</td>' +
          '<td style="padding:5px 8px;text-align:right;color:' + col + ';font-weight:600">' + (f.pnlPct!=null?sign+f.pnlPct.toFixed(2)+'%':'—') + '</td>' +
          '<td style="padding:5px 8px;text-align:right;color:var(--text-muted)">' + (f.holdingDays||0) + '</td>' +
          '<td style="padding:5px 8px;color:var(--text-muted);font-size:0.68rem">' + (f.exitReason||'—') + '</td>' +
          '</tr>';
      }).join('');
    }

    let i = 0;
    const delay = Math.max(10, Math.min(80, 3000 / frames.length));
    (function step() {
      if (i >= frames.length) return;
      eqData[i] = frames[i].equityAfter;
      _stmChart.data.datasets[0].data = eqData.slice();
      _stmChart.update('none');
      const row = document.getElementById('stm-row-' + i);
      if (row) {
        row.style.background = frames[i].result==='win'?'rgba(240,240,242,0.08)':frames[i].result==='loss'?'rgba(154,154,159,0.08)':'';
        row.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
      }
      i++;
      setTimeout(step, delay);
    }());
  } finally {
    if (btn) { btn.disabled = false; btn.textContent = '▶ Replay Backtest'; }
  }
}

function closeStrategyTradesModal() {
  const modal = document.getElementById('strategy-trades-modal');
  if (modal) modal.style.display = 'none';
  if (_stmChart) { _stmChart.destroy(); _stmChart = null; }
  _stmCurrentId = null;
}

document.addEventListener('click', function(e) {
  const modal = document.getElementById('strategy-trades-modal');
  if (modal && e.target === modal) closeStrategyTradesModal();
});

