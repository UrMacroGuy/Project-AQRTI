// ui/pages/opportunity.js - split from app.js (ARCH-5), see CHANGELOG
async function loadTodaySignals() {
  const grid    = el('today-signals-grid');
  const banner  = el('do-not-trade-banner');
  const pill    = el('model-health-pill');
  const updated = el('today-signals-updated');
  if (!grid) return;

  grid.innerHTML = '<div style="color:var(--text-muted);padding:20px;text-align:center;grid-column:1/-1">Loading signals…</div>';

  let data;
  try {
    data = await apiFetch('/predictions/today');
  } catch (e) {
    data = null;
  }

  if (!data) {
    grid.innerHTML = '<div style="color:var(--text-muted);padding:20px;text-align:center;grid-column:1/-1">Backend offline — start the backend server to load signals.</div>';
    return;
  }

  // Model health pill
  const health = data.modelHealth || {};
  const healthColors = { green: '#22c55e', yellow: '#eab308', red: '#ef4444', no_data: 'var(--text-muted)' };
  const healthLabels = { green: '✓ Model Healthy', yellow: '⚡ Model Fair', red: '✗ Model Weak', no_data: '? No Model Data' };
  if (pill) {
    pill.style.background = healthColors[health.status] ? healthColors[health.status] + '22' : '';
    pill.style.color = healthColors[health.status] || 'var(--text-muted)';
    pill.style.border = `1px solid ${healthColors[health.status] || 'var(--border)'}`;
    pill.textContent = healthLabels[health.status] || '?';
    if (health.accuracy != null) pill.textContent += ` · ${health.accuracy}%`;
  }

  // DO NOT TRADE banner
  if (banner) banner.style.display = data.doNotTrade ? 'flex' : 'none';

  if (updated) updated.textContent = `Updated: ${data.date || '—'}`;

  const signals = data.signals || [];
  if (!signals.length) {
    grid.innerHTML = `<div style="color:var(--text-muted);padding:24px;text-align:center;grid-column:1/-1">
      No signals today — predictions run after 3:30 PM IST.<br>
      <span style="font-size:0.8rem">Check back after market close.</span>
    </div>`;
    return;
  }

  const gradeClass = { A: 'grade-a', B: 'grade-b', C: 'grade-c' };
  const gradeLbl   = { A: 'A', B: 'B', C: 'C' };

  grid.innerHTML = signals.map(s => {
    const gc      = gradeClass[s.signalGrade]  || 'grade-c';
    const gl      = gradeLbl[s.signalGrade]    || 'C';
    const glcss   = (s.signalGrade || 'c').toLowerCase();
    const entry   = s.lastPrice      != null ? `₹${s.lastPrice.toLocaleString('en-IN', {minimumFractionDigits:2, maximumFractionDigits:2})}` : '—';
    const sl      = s.stopLossPrice  != null ? `₹${s.stopLossPrice.toLocaleString('en-IN', {minimumFractionDigits:2, maximumFractionDigits:2})}` : '—';
    const tp      = s.targetPrice    != null ? `₹${s.targetPrice.toLocaleString('en-IN', {minimumFractionDigits:2, maximumFractionDigits:2})}` : '—';
    const slPct   = s.stopLossPct    != null ? `${s.stopLossPct.toFixed(1)}%` : '—';
    const tpPct   = s.takeProfitPct  != null ? `+${s.takeProfitPct.toFixed(1)}%` : '—';
    const rr      = s.riskRewardRatio != null ? `1:${s.riskRewardRatio.toFixed(1)}` : '—';
    const conf    = Math.round(s.confidence || 0);
    const wr      = s.strategyWinRate != null ? `${s.strategyWinRate.toFixed(1)}%WIN` : '';
    const tc      = s.strategyTrades  != null ? `${s.strategyTrades.toLocaleString()}T` : '';
    const stratLine = [s.strategyName, wr, tc].filter(Boolean).join(' · ') || '—';
    const reasoning = s.reasoning ? s.reasoning.slice(0, 120) + (s.reasoning.length > 120 ? '…' : '') : '';

    return `
    <div class="bbg-signal-card ${gc}">
      <div class="bbg-signal-head">
        <span class="bbg-signal-sym">${s.symbol}</span>
        <span class="bbg-signal-name">${s.sector || ''}</span>
        <span class="bbg-signal-grade ${glcss}">GRD ${gl}</span>
        <div class="bbg-signal-conf-bar" title="${conf}% confidence">
          <div class="bbg-signal-conf-fill ${glcss}" style="width:${conf}%"></div>
        </div>
        <span style="font-family:var(--font-mono);font-size:0.62rem;color:#888;min-width:28px">${conf}%</span>
      </div>
      <div class="bbg-signal-levels">
        <div class="bbg-signal-level">
          <div class="bbg-level-label">ENTRY · NSE CNC</div>
          <div class="bbg-level-price entry">${entry}</div>
          <div class="bbg-level-pct" style="color:#555">Today close</div>
        </div>
        <div class="bbg-signal-level">
          <div class="bbg-level-label">STOP LOSS</div>
          <div class="bbg-level-price sl">${sl}</div>
          <div class="bbg-level-pct sl">${slPct}</div>
        </div>
        <div class="bbg-signal-level">
          <div class="bbg-level-label">TARGET</div>
          <div class="bbg-level-price tp">${tp}</div>
          <div class="bbg-level-pct tp">${tpPct}</div>
        </div>
      </div>
      <div class="bbg-signal-footer">
        <span class="bbg-signal-strat" title="${stratLine}">${stratLine}</span>
        <span class="bbg-signal-rr">R:R ${rr}</span>
      </div>
      ${reasoning ? `<div style="padding:4px 10px 6px;font-size:0.62rem;color:#444;border-top:1px solid #111;line-height:1.4">${reasoning}</div>` : ''}
    </div>`;
  }).join('');
}

// ── Opportunity Rankings — live prediction hydration ─────────
async function hydrateOpportunities() {
  const rawData = await Api.predictions({ limit: 50 });
  if (!rawData) {
    const tbody = el('opportunity-body');
    if (tbody) tbody.innerHTML = '<tr><td colspan="10" style="color:var(--text-muted);text-align:center;padding:32px">Backend offline — start the backend server to load data.</td></tr>';
    return;
  }
  if (!rawData.length) return;

  // Only show bullish/buy signals as investable opportunities
  const data = rawData.filter(p => {
    const dir = (p.direction || '').toLowerCase();
    return dir.includes('bull') || dir.includes('buy');
  }).slice(0, 20);

  // Re-rank after filter
  data.forEach((p, i) => { p.rank = i + 1; });

  // Update nav badge
  const oppBadge = el('badge-opp');
  if (oppBadge) oppBadge.textContent = data.length;

  // KPI cards
  const strong = data.filter(p => (p.confidence || 0) >= 80);
  setDataPoint('opp-kpi-strong', strong.length, 'opportunity');
  const avgConf = data.length ? data.reduce((s, p) => s + (p.confidence || 0), 0) / data.length : 0;
  setDataPoint('opp-kpi-avg-conf', data.length ? `${avgConf.toFixed(1)}%` : '—', 'opportunity');
  const best = [...data].sort((a, b) => (b.expectedReturn || 0) - (a.expectedReturn || 0))[0];
  if (best) {
    const ret = best.expectedReturn;
    setDataPoint('opp-kpi-best-return', ret != null ? (ret >= 0 ? `+${ret.toFixed(2)}%` : `${ret.toFixed(2)}%`) : '—', 'opportunity');
    setDataPoint('opp-kpi-best-symbol', `${best.symbol || '—'}${best.horizon ? ' (' + best.horizon + ')' : ''}`, 'opportunity');
  }
  const riskCounts = { Low: 0, Medium: 0, High: 0 };
  data.forEach(p => { const r = p.risk || 'Medium'; if (riskCounts[r] != null) riskCounts[r]++; });
  const dominantRisk = data.length ? Object.entries(riskCounts).sort((a, b) => b[1] - a[1])[0][0] : '—';
  setDataPoint('opp-kpi-risk', dominantRisk, 'opportunity');

  const tbody = el('opportunity-body');
  if (tbody) {
    if (!data.length) {
      tbody.innerHTML = '<tr><td colspan="10" style="color:var(--text-muted);text-align:center;padding:20px">No bullish predictions today — model sees no clear long setups.</td></tr>';
    } else tbody.innerHTML = data.map(p => {
      const expRet = p.expectedReturn != null
        ? (p.expectedReturn >= 0 ? `+${p.expectedReturn.toFixed(2)}%` : `${p.expectedReturn.toFixed(2)}%`)
        : '—';
      const sentiment = p.sentimentScore != null ? Math.round(p.sentimentScore) : '—';
      return `
        <tr>
          <td><strong style="color:var(--accent)">#${p.rank}</strong></td>
          <td><strong>${p.symbol}</strong></td>
          <td style="color:var(--text-muted)">${p.sector || '—'}</td>
          <td>${dirBadge(p.direction)}</td>
          <td>${confBarHTML(Math.round(p.confidence || 0))}</td>
          <td class="${(p.expectedReturn || 0) >= 0 ? 'positive' : 'negative'}">${expRet}</td>
          <td>${riskBadge(p.risk || 'Medium')}</td>
          <td style="color:var(--text-secondary)">${p.confidenceDetail ? p.confidenceDetail.category : '—'}</td>
          <td class="${sentColor(typeof sentiment === 'number' ? sentiment : 50)}">${sentiment}</td>
          <td><strong>${p.positionSize || '—'}</strong></td>
        </tr>`;
    }).join('');

    // Re-apply existing filters against live data
    const confFilter = el('opp-conf-filter');
    const dirFilter  = el('opp-dir-filter');
    if (confFilter && dirFilter) {
      const rows = Array.from(tbody.querySelectorAll('tr'));
      rows.forEach((row, i) => {
        const p = data[i]; if (!p) return;
        const conf = p.confidence || 0;
        const confOk = confFilter.value === 'all'
          || (confFilter.value === 'strong' && conf >= 80)
          || (confFilter.value === 'good'   && conf >= 70 && conf < 80);
        const dirOk = dirFilter.value === 'all'
          || (dirFilter.value === 'bullish' && p.direction === 'Bullish')
          || (dirFilter.value === 'bearish' && p.direction === 'Bearish');
        row.style.display = (confOk && dirOk) ? '' : 'none';
      });
    }
  }

  // Rebuild confidence distribution chart from live data
  const confBuckets = [0, 0, 0, 0];
  data.forEach(p => {
    const c = p.confidence || 0;
    if (c >= 80) confBuckets[3]++;
    else if (c >= 70) confBuckets[2]++;
    else if (c >= 60) confBuckets[1]++;
    else confBuckets[0]++;
  });
  ChartRegistry.create('confDistChart', {
    type: 'doughnut',
    data: {
      labels: ['< 60 (Ignore)', '60–69 (Weak)', '70–79 (Good)', '80+ (Strong)'],
      datasets: [{
        data: confBuckets,
        backgroundColor: ['rgba(239,68,68,0.7)','rgba(245,158,11,0.7)','rgba(255,140,0,0.7)','rgba(34,197,94,0.7)'],
        borderWidth: 1, borderColor: 'rgba(255,255,255,0.08)',
      }],
    },
    options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { position: 'bottom' } }, cutout: '60%' },
  });
}


// ── Overview — live predictions summary patch ─────────────────
async function hydrateOverviewPredictions() {
  const [regime, summary] = await Promise.all([Api.marketRegime(), Api.predictionSummary()]);

  if (regime) {
    const topbarRegime = el('topbar-regime');
    if (topbarRegime) topbarRegime.textContent = regime.regime || 'LOADING…';
    const pill = document.getElementById('regime-pill');
    if (pill) pill.className = 'regime-badge badge-' + (regime.regime || '').toLowerCase().replace(/\s+/g, '-');
  }

  if (summary && summary.available) {
    const predCountEl = el('kpi-predictions');
    if (predCountEl) predCountEl.textContent = summary.total || '0';

    const confEl = el('kpi-avg-conf');
    if (confEl && summary.avgConfidence != null) confEl.textContent = `Avg Conf: ${summary.avgConfidence}%`;

    // Replace top 3 prediction cards on overview if elements exist
    if (summary.topPredictions && summary.topPredictions.length) {
      summary.topPredictions.forEach((p, i) => {
        const symEl = document.querySelector(`[data-pred-symbol="${i}"]`);
        if (symEl) symEl.textContent = p.symbol;
        const dirEl = document.querySelector(`[data-pred-dir="${i}"]`);
        if (dirEl) {
          dirEl.textContent  = p.direction;
          dirEl.className    = p.direction === 'Bullish' ? 'positive' : p.direction === 'Bearish' ? 'negative' : 'neutral';
        }
        const confEl2 = document.querySelector(`[data-pred-conf="${i}"]`);
        if (confEl2) confEl2.textContent = `${Math.round(p.confidence || 0)}%`;
      });
    }
  }
}

// Extend Api with new Phase 3 endpoints
if (typeof Api !== 'undefined') {
  if (!Api.predictions) {
    Api.predictions = async function(params = {}) {
      return apiFetch('/predictions', params);
    };
  }
  if (!Api.predictionSummary) {
    Api.predictionSummary = async function() {
      return apiFetch('/predictions/summary');
    };
  }
  if (!Api.todaySignals) {
    Api.todaySignals = async function() {
      return apiFetch('/predictions/today');
    };
  }
  if (!Api.modelHealth) {
    Api.modelHealth = async function() {
      return apiFetch('/predictions/model-health');
    };
  }
  if (!Api.models) {
    Api.models = async function(params = {}) {
      return apiFetch('/models', params);
    };
  }
  if (!Api.modelStats) {
    Api.modelStats = async function() {
      return apiFetch('/models/stats');
    };
  }
  if (!Api.confidence) {
    Api.confidence = async function(params = {}) {
      return apiFetch('/confidence', params);
    };
  }
  if (!Api.patterns) {
    Api.patterns = async function(params = {}) {
      return apiFetch('/patterns', params);
    };
  }
}

