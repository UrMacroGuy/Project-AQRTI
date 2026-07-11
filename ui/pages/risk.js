// ui/pages/risk.js - split from app.js (ARCH-5), see CHANGELOG
async function hydrateRisk() {
  const data = await Api.risk();
  if (!data) {
    const offlineMsg = '<div style="padding:32px;text-align:center;color:var(--text-muted);font-size:0.78rem">Backend offline — start the backend server to load data.</div>';
    const posBody = el('risk-position-body');
    if (posBody) posBody.innerHTML = `<tr><td colspan="5" style="padding:32px;text-align:center;color:var(--text-muted);font-size:0.78rem">Backend offline — start the backend server to load data.</td></tr>`;
    const alertBody = el('risk-alerts-body');
    if (alertBody) alertBody.innerHTML = `<tr><td colspan="4" style="padding:32px;text-align:center;color:var(--text-muted);font-size:0.78rem">Backend offline — start the backend server to load data.</td></tr>`;
    return;
  }

  // Sector exposure doughnut
  if (data.sectorExposure && data.sectorExposure.length) {
    const exp = data.sectorExposure;
    ChartRegistry.create('sectorExposureChart', {
      type: 'doughnut',
      data: {
        labels: exp.map(e => e.sector),
        datasets: [{
          data: exp.map(e => e.weight),
          backgroundColor: exp.map((_, i) => [
            'rgba(240,240,242,0.85)', 'rgba(216,216,220,0.75)', 'rgba(196,196,200,0.7)',
            'rgba(176,176,180,0.7)', 'rgba(154,154,159,0.7)', 'rgba(132,132,138,0.7)',
            'rgba(110,110,116,0.7)', 'rgba(88,88,94,0.7)',
          ][i % 8]),
          borderWidth: 1, borderColor: 'rgba(255,255,255,0.06)',
        }],
      },
      options: {
        responsive: true, maintainAspectRatio: false,
        plugins: {
          legend: { position: 'right', labels: { font: { size: 11 } } },
          tooltip: { callbacks: { label: ctx => ` ${ctx.label}: ${ctx.parsed.toFixed(1)}%` } },
        },
        cutout: '50%',
      },
    });
  }

  // Drawdown history chart
  if (data.drawdownHistory && data.drawdownHistory.length) {
    const hist = data.drawdownHistory;
    ChartRegistry.create('drawdownChart', {
      type: 'line',
      data: {
        labels: hist.map(h => h.date),
        datasets: [{
          label: 'Drawdown %',
          data: hist.map(h => h.drawdown || 0),
          borderColor: 'var(--negative)', borderWidth: 1.5, pointRadius: 0, tension: 0.3, fill: true,
          backgroundColor: 'rgba(154,154,159,0.12)',
        }],
      },
      options: {
        responsive: true, maintainAspectRatio: false,
        plugins: { legend: { display: false } },
        scales: { y: { ticks: { callback: v => `${v}%` } }, x: { ticks: { maxTicksLimit: 8 } } },
      },
    });
  }

  // Position risk table
  if (data.positions) {
    const tbody = el('risk-position-body');
    if (tbody) {
      if (data.positions.length) {
        tbody.innerHTML = data.positions.map(p => `
          <tr>
            <td><strong>${p.symbol}</strong></td>
            <td>${p.weight}</td>
            <td class="negative">${p.var != null ? `₹${p.var.toFixed(0)}` : '—'}</td>
            <td>${p.volatility != null ? `${p.volatility.toFixed(1)}%` : '—'}</td>
            <td>${riskBadge(p.riskLevel || 'Medium')}</td>
          </tr>`).join('');
      } else {
        tbody.innerHTML = '<tr><td colspan="5" style="color:var(--text-muted);text-align:center">No open positions</td></tr>';
      }
    }
  }

  if (data.exposure != null)       setDataPoint('risk-exposure',   `${data.exposure}%`, 'risk');
  if (data.varDaily != null) {
    setDataPoint('risk-var-daily',  `−₹${Math.abs(data.varDaily).toFixed(0)}`, 'risk');
    const varPctEl = el('risk-var-pct');
    if (varPctEl && data.varPct != null) { varPctEl.textContent = `−${Math.abs(data.varPct).toFixed(2)}% of Capital`; varPctEl.title = `Source: risk | ${new Date().toISOString()}`; }
  }
  if (data.maxDrawdown30d != null) setDataPoint('risk-max-dd',     `${data.maxDrawdown30d.toFixed(2)}%`, 'risk');
  if (data.sharpe != null)         setDataPoint('risk-sharpe',     data.sharpe.toFixed(2), 'risk');

  // Largest position (sort by numeric weight descending)
  if (data.positions && data.positions.length) {
    const sorted = [...data.positions].sort((a, b) => {
      const wa = parseFloat(String(a.weight || '0').replace('%', '')) || 0;
      const wb = parseFloat(String(b.weight || '0').replace('%', '')) || 0;
      return wb - wa;
    });
    const largest = sorted[0];
    setDataPoint('risk-largest-pos', largest.symbol || '—', 'risk');
    setDataPoint('risk-largest-weight', largest.weight || '—', 'risk');
  }

  // Circuit breaker status
  if (data.circuitStatus) {
    const statusEl = el('circuit-breaker-status');
    if (statusEl) {
      statusEl.textContent = data.circuitStatus;
      statusEl.className = 'kpi-value ' + (data.circuitStatus === 'TRIGGERED' ? 'negative' : 'positive');
    }
  }

  // Live risk alerts panel — replace mock data
  const alertsBody = el('risk-alerts-body');
  if (alertsBody) {
    const alerts = [];
    if (data.circuitStatus === 'TRIGGERED') alerts.push({ level: 'critical', title: 'Circuit Breaker Triggered', desc: 'One or more drawdown limits breached. Trading paused.' });
    if (data.exposure > 70) alerts.push({ level: 'warning', title: 'High Exposure', desc: `Portfolio exposure at ${data.exposure.toFixed(1)}% — approaching 80% limit.` });
    if (data.maxDrawdown30d && Math.abs(data.maxDrawdown30d) > 5) alerts.push({ level: 'warning', title: 'Drawdown Alert', desc: `Max drawdown at ${Math.abs(data.maxDrawdown30d).toFixed(2)}% over 30 days.` });
    if (data.sharpe < 0.5 && data.sharpe !== 0) alerts.push({ level: 'info', title: 'Low Sharpe Ratio', desc: `Sharpe at ${data.sharpe.toFixed(2)} — risk-adjusted returns below target of 1.0.` });
    if (data.positions && data.positions.some(p => p.riskLevel === 'High')) alerts.push({ level: 'warning', title: 'High-Risk Positions', desc: 'One or more positions flagged as high volatility.' });
    if (!data.positions || data.positions.length === 0) alerts.push({ level: 'info', title: 'No Open Positions', desc: 'Portfolio is fully in cash. Run a paper trade cycle to deploy capital.' });

    if (alerts.length) {
      alertsBody.innerHTML = alerts.map(a => `
        <div class="risk-alert ${a.level}">
          <div class="risk-alert-title">${a.title}</div>
          <div class="risk-alert-sub">${a.desc}</div>
        </div>`).join('');
    } else {
      alertsBody.innerHTML = '<div class="risk-alert info"><div class="risk-alert-title">All Clear</div><div class="risk-alert-sub">No active risk alerts. All metrics within normal ranges.</div></div>';
    }
  }
  initStressTest();
}

// SCENARIO STRESS TEST
// ══════════════════════════════════════════════════════════════
async function initStressTest() {
  const data      = await Api.stressTestPresets().catch(() => null);
  const container = document.getElementById('st-presets');
  if (container && data?.presets) {
    container.innerHTML = data.presets.map(p =>
      `<button class="panel-action-btn" onclick="applyStressPreset(${p.nifty_shock_pct},'${p.sector_shock || ''}',${p.sector_shock_pct || 0})" style="font-size:0.6rem;padding:3px 8px">${p.name}</button>`
    ).join('');
  }
}

function applyStressPreset(niftyShock, sector, sectorShock) {
  const _sv = (id, v) => { const e = document.getElementById(id); if (e) e.value = v; };
  _sv('st-nifty-shock',  niftyShock);
  _sv('st-sector',       sector);
  _sv('st-sector-shock', sectorShock || -15);
  runStressTest();
}

async function runStressTest() {
  const niftyShock  = parseFloat(document.getElementById('st-nifty-shock')?.value  || '-10');
  const sector      = document.getElementById('st-sector')?.value || null;
  const sectorShock = parseFloat(document.getElementById('st-sector-shock')?.value || '-15');
  const data = await Api.stressTestRun(niftyShock, sector || null, sectorShock).catch(() => null);
  if (!data || data.error) return;

  const resultsDiv = document.getElementById('st-results');
  if (resultsDiv) resultsDiv.style.display = 'block';

  const _fmt = v => (v >= 0 ? '+' : '') + Math.round(v).toLocaleString('en-IN');
  setDataPoint('st-pnl',     `₹${_fmt(data.total_pnl_impact)}`, 'risk');
  const stPnlEl = document.getElementById('st-pnl');
  if (stPnlEl) stPnlEl.className = 'kpi-value ' + (data.total_pnl_impact >= 0 ? 'positive' : 'negative');
  setDataPoint('st-pnl-pct', `${(data.total_pnl_pct >= 0 ? '+' : '')}${data.total_pnl_pct.toFixed(2)}%`, 'risk');
  const stPnlPctEl = document.getElementById('st-pnl-pct');
  if (stPnlPctEl) stPnlPctEl.className = 'kpi-value ' + (data.total_pnl_pct >= 0 ? 'positive' : 'negative');
  setDataPoint('st-new-nav', `₹${(data.new_portfolio_value / 1000).toFixed(1)}K`, 'risk');

  const tbody = document.getElementById('st-positions-body');
  if (tbody && data.positions) {
    tbody.innerHTML = data.positions.map(p =>
      `<tr>
        <td><strong>${p.symbol}</strong></td>
        <td style="color:#666">${p.sector}</td>
        <td>${p.beta.toFixed(2)}</td>
        <td class="${p.stock_shock_pct >= 0 ? 'positive' : 'negative'}">${p.stock_shock_pct >= 0 ? '+' : ''}${p.stock_shock_pct.toFixed(1)}%</td>
        <td>₹${(p.current_value / 1000).toFixed(1)}K</td>
        <td class="${p.pnl_impact >= 0 ? 'positive' : 'negative'}">₹${_fmt(p.pnl_impact)}</td>
      </tr>`
    ).join('');
  }
}

// ══════════════════════════════════════════════════════════════
