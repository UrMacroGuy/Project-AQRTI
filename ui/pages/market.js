// ui/pages/market.js - split from app.js (ARCH-5), see CHANGELOG
async function hydrateMarketRegime() {
  const data = await Api.marketRegime();
  if (!data) return;

  const topbarRegime = el('topbar-regime');
  if (topbarRegime) {
    topbarRegime.textContent = data.regime || 'LOADING…';
  }

  const pill = document.getElementById('regime-pill');
  if (pill) {
    pill.className = 'regime-badge badge-' + (data.regime || '').toLowerCase().replace(/\s+/g, '-');
  }

  // Overview page regime card
  const rName = el('overview-regime-name');
  if (rName) rName.textContent = data.regime || '—';
  const rConf = el('overview-regime-conf');
  if (rConf) rConf.textContent = data.confidence != null ? `Confidence: ${(data.confidence * 100).toFixed(0)}%` : 'Confidence: —';
  const rDesc = el('overview-regime-desc');
  if (rDesc) rDesc.textContent = data.description || data.regime_description || '';
}

// ── Add marketRegime endpoint to Api layer ────────────────────
// (Extends api.js Api object — safe to call even if api.js already loaded)
if (typeof Api !== 'undefined' && !Api.marketRegime) {
  Api.marketRegime = async function() {
    return apiFetch('/market-regime');
  };
}
async function hydrateMarket() {
  hydrateMarketRegime();  // update regime badge

  const data = await Api.market();
  if (!data) {
    const offlineRow = '<tr><td colspan="6" style="padding:32px;text-align:center;color:var(--text-muted);font-size:0.78rem">Backend offline — start the backend server to load data.</td></tr>';
    const moversBody = el('top-movers-body');
    if (moversBody) moversBody.innerHTML = offlineRow;
    const sectorDetail = el('sector-detail-body');
    if (sectorDetail) sectorDetail.innerHTML = offlineRow;
    return;
  }

  // NIFTY / BANKNIFTY — topbar ticker + market page KPI cards
  const { indices, sectorStrength, topMovers } = data;
  if (indices) {
    const nifty = indices.nifty50 || {};
    const bank  = indices.banknifty || {};

    if (nifty.value != null) {
      const fmt = nifty.value.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
      const niftyEl = el('nifty-value');
      if (niftyEl) niftyEl.textContent = fmt;
      setDataPoint('market-nifty-val', fmt, 'market');
      const pct = (nifty.returns || 0) * 100;
      const chgText = `${pct >= 0 ? '+' : ''}${pct.toFixed(2)}%`;
      const chgCls  = pct >= 0 ? 'positive' : 'negative';
      const niftyChg = el('nifty-change');
      if (niftyChg) { niftyChg.textContent = chgText; niftyChg.className = 'ticker-change ' + chgCls; }
      const mNiftyChg = el('market-nifty-chg');
      if (mNiftyChg) { mNiftyChg.textContent = chgText; mNiftyChg.className = 'kpi-sub ' + chgCls; }
    }
    if (bank.value != null) {
      const fmt = bank.value.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
      const bankEl = el('banknifty-value');
      if (bankEl) bankEl.textContent = fmt;
      setDataPoint('market-banknifty-val', fmt, 'market');
      const pct = (bank.returns || 0) * 100;
      const chgText = `${pct >= 0 ? '+' : ''}${pct.toFixed(2)}%`;
      const chgCls  = pct >= 0 ? 'positive' : 'negative';
      const bankChg = el('banknifty-change');
      if (bankChg) { bankChg.textContent = chgText; bankChg.className = 'ticker-change ' + chgCls; }
      const mBankChg = el('market-banknifty-chg');
      if (mBankChg) { mBankChg.textContent = chgText; mBankChg.className = 'kpi-sub ' + chgCls; }
    }
  }

  // Market breadth — fetch separately
  Api.marketBreadth().then(breadth => {
    if (!breadth) return;
    const adv = breadth.advancing || breadth.advancers || 0;
    const dec = breadth.declining || breadth.decliners || 0;
    const total = adv + dec;
    if (total > 0) {
      const pct = Math.round(adv / total * 100);
      setDataPoint('market-breadth-val', `${pct}%`, 'market');
      setDataPoint('market-breadth-sub', `${adv} Adv / ${dec} Dec`, 'market');
      const bEl = el('market-breadth-val');
      if (bEl) bEl.className = 'kpi-value ' + (pct >= 50 ? 'positive' : 'negative');
    }
  });

  // Sector strength bar chart + detail cards
  if (sectorStrength && sectorStrength.length) {
    ChartRegistry.create('sectorStrengthChart', {
      type: 'bar',
      data: {
        labels: sectorStrength.map(s => s.name),
        datasets: [{
          label: 'Strength Score',
          data: sectorStrength.map(s => s.score),
          backgroundColor: sectorStrength.map(s =>
            s.score >= 80 ? 'rgba(34,197,94,0.7)'
            : s.score >= 60 ? 'rgba(255,140,0,0.7)'
            : s.score >= 45 ? 'rgba(245,158,11,0.6)'
            : 'rgba(239,68,68,0.6)'
          ),
          borderRadius: 4, borderSkipped: false,
        }],
      },
      options: {
        indexAxis: 'y', responsive: true, maintainAspectRatio: false,
        plugins: { legend: { display: false } },
        scales: { x: { min: 0, max: 100, ticks: { stepSize: 20 } }, y: { ticks: { font: { size: 11 } } } },
      },
    });

    const sectorDetail = el('sector-detail-body');
    if (sectorDetail) {
      sectorDetail.innerHTML = sectorStrength.map(s => {
        const col = s.score >= 75 ? 'var(--positive)' : s.score >= 50 ? 'var(--accent)' : s.score >= 35 ? 'var(--warning)' : 'var(--negative)';
        return `
          <div class="sector-card">
            <div class="sector-row">
              <span class="sector-name">${s.name}</span>
              <span class="sector-score" style="color:${col}">${s.score}</span>
            </div>
            <div class="score-bar-track">
              <div class="score-bar-fill" style="width:${s.score}%; background:${col}"></div>
            </div>
            <div class="sector-meta">
              <span>RS: ${s.rs || '—'}</span>
              <span>Momentum: ${s.momentum || '—'}</span>
            </div>
          </div>`;
      }).join('');
    }
  }

  // Top movers table
  const moversBody = el('top-movers-body');
  if (moversBody) {
    if (topMovers && topMovers.length) {
      moversBody.innerHTML = topMovers.map(m => {
        const pct = (m.change || 0) * 100;
        return `
          <tr>
            <td><strong>${m.symbol}</strong></td>
            <td style="color:var(--text-muted)">${m.sector || '—'}</td>
            <td>${m.price != null ? m.price.toFixed(2) : '—'}</td>
            <td class="${m.direction === 'up' ? 'positive' : 'negative'}">${pct >= 0 ? '+' : ''}${pct.toFixed(2)}%</td>
            <td style="color:var(--text-muted)">—</td>
          </tr>`;
      }).join('');
    } else {
      moversBody.innerHTML = '<tr><td colspan="5" style="color:var(--text-muted);text-align:center;padding:16px">No intraday data — run daily ingestion to populate</td></tr>';
    }
  }
}

// GLOBAL UNIVERSE
// ═══════════════════════════════════════════════════════════════

async function loadUniverseSummary() {
  try {
    const summary = await Api.universeSummary();
    if (!summary) return;
    setDataPoint('uni-total',    (summary.universe_size || 0).toLocaleString(), 'market');
    setDataPoint('uni-indb',     (summary.stocks_in_db  || 0).toLocaleString(), 'market');
    setDataPoint('uni-withdata', (summary.symbols_with_data || 0).toLocaleString(), 'market');
    setDataPoint('uni-rows',     (summary.total_price_rows  || 0).toLocaleString(), 'market');

    const tag = document.getElementById('universe-size-tag');
    if (tag) tag.textContent = `${summary.universe_size || 0} STOCKS`;

    const regionBody = document.getElementById('uni-region-body');
    if (regionBody && summary.by_region) {
      regionBody.innerHTML = Object.entries(summary.by_region)
        .map(([r, n]) => `<tr><td>${r}</td><td class="accent">${n}</td></tr>`)
        .join('');
    }
    const sectorBody = document.getElementById('uni-sector-body');
    if (sectorBody && summary.by_sector) {
      sectorBody.innerHTML = Object.entries(summary.by_sector)
        .map(([s, n]) => `<tr><td>${s}</td><td class="accent">${n}</td></tr>`)
        .join('');
    }

    // Also check if a download is running
    const status = await Api.universeDownloadStatus().catch(() => null);
    const alert = document.getElementById('universe-download-alert');
    if (alert) {
      if (status && status.running) {
        alert.style.display = 'block';
        alert.textContent = `Downloading global universe… started ${status.started_at || ''}`;
        setTimeout(loadUniverseSummary, 10000);
      } else if (status && status.last_result) {
        const r = status.last_result;
        alert.style.display = 'block';
        alert.style.background = 'rgba(34,197,94,0.08)';
        alert.style.borderColor = 'rgba(34,197,94,0.3)';
        alert.style.color = '#22c55e';
        alert.textContent = `Last download: ${r.downloaded} downloaded, ${r.skipped} skipped, ${r.errors} errors, ${(r.total_rows||0).toLocaleString()} rows total`;
      } else {
        alert.style.display = 'none';
      }
    }
  } catch (e) {
    console.warn('Universe summary failed:', e);
  }
}

async function seedAndDownloadUniverse(region = 'all') {
  const label = region === 'all' ? 'all regions' : `region: ${region}`;
  const confirmed = confirm(`Download 3yr price data for ${label}?\n\nThis will run in the background — it may take 10-30 minutes for all stocks.`);
  if (!confirmed) return;

  const alert = document.getElementById('universe-download-alert');
  if (alert) {
    alert.style.display = 'block';
    alert.style.background = 'rgba(251,191,36,0.1)';
    alert.style.borderColor = 'rgba(251,191,36,0.3)';
    alert.style.color = '#fbbf24';
    alert.textContent = 'Starting download…';
  }

  try {
    const result = await Api.downloadUniverse(3, region, 4);
    if (alert) {
      if (result.status === 'already_running') {
        alert.textContent = 'Download already running — check back in a few minutes.';
      } else {
        alert.textContent = `Download started: ${result.tickers} tickers from ${result.start_date}. Refreshing status every 10s…`;
        setTimeout(loadUniverseSummary, 10000);
      }
    }
  } catch (e) {
    if (alert) {
      alert.style.color = '#ef4444';
      alert.textContent = `Download failed: ${e.message || e}`;
    }
  }
}

