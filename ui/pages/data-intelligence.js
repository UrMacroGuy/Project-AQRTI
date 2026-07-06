// ui/pages/data-intelligence.js - split from app.js (ARCH-5), see CHANGELOG
// ══════════════════════════════════════════════════════════
// PHASE 8M — DATA INTELLIGENCE CENTER
// ══════════════════════════════════════════════════════════

const ChartRegistryDI = {};

async function hydrateDataIntelligence() {
  // ── Quality Dashboard ──
  const quality = await Api.dataQuality(7);
  if (quality) {
    const avgScore = quality.avg_quality_score;
    setDataPoint('di-kpi-quality', avgScore != null ? avgScore.toFixed(0) : '—', 'data-intelligence');
    const alertCount = (quality.alert_datasets || []).length;
    setDataPoint('di-kpi-quality-sub', `${alertCount} alert${alertCount !== 1 ? 's' : ''} · ${Object.keys(quality.datasets || {}).length} datasets`, 'data-intelligence');
    // Convert dict to list for table render
    const alertSet = new Set(quality.alert_datasets || []);
    const dsArr = Object.entries(quality.datasets || {}).map(([name, d]) => ({ dataset_name: name, status: alertSet.has(name) ? 'degraded' : 'ok', ...d }));
    _renderQualityTable(dsArr);
  }

  // ── Source Health ──
  const health = await Api.sourceHealth();
  if (health?.sources) {
    const online = health.sources.filter(s => s.status === 'ok').length;
    setDataPoint('di-kpi-sources', online, 'data-intelligence');
    setDataPoint('di-kpi-sources-sub', `of ${health.sources.length} monitored`, 'data-intelligence');
    _mergeQualityWithHealth(health.sources);
  }

  // ── FII/DII — delegate to enhanced chart loader ──
  await loadFiiDiiCharts();

  // ── Market Breadth ──
  const breadth = await Api.marketBreadth();
  if (breadth) {
    const ad = breadth.advance_decline_ratio;
    setDataPoint('di-kpi-breadth', ad != null ? ad.toFixed(2) : '—', 'data-intelligence');
    setDataPoint('di-kpi-breadth-sub', breadth.breadth_signal || '—', 'data-intelligence');
    setDataPoint('di-breadth-signal', breadth.breadth_signal || '—', 'data-intelligence');
  }
  const breadthHist = await Api.marketBreadthHistory(30);
  _renderBreadthChart(breadthHist || []);

  // ── Sector Rotation ──
  const sectors = await Api.sectorRotation();
  const secList = sectors?.sectors || [];
  const leading = secList.filter(s => s.rotation_phase === 'LEADING').length;
  setDataPoint('di-kpi-sectors', leading, 'data-intelligence');
  setDataPoint('di-kpi-sectors-sub', `LEADING out of ${secList.length}`, 'data-intelligence');
  _renderSectorTable(secList);

  // ── Options ──
  const opts = await Api.optionsSnapshot('NIFTY');
  if (opts) {
    setDataPoint('di-opt-pcr', opts.pcr_oi?.toFixed(2) ?? '—', 'data-intelligence');
    setDataPoint('di-opt-maxpain', opts.max_pain?.toLocaleString('en-IN') ?? '—', 'data-intelligence');
    setDataPoint('di-opt-iv', opts.atm_iv?.toFixed(2) ?? '—', 'data-intelligence');
    setDataPoint('di-opt-skew', opts.iv_skew?.toFixed(4) ?? '—', 'data-intelligence');
    setDataPoint('di-opt-call-strike', opts.highest_call_oi_strike?.toLocaleString('en-IN') ?? '—', 'data-intelligence');
    setDataPoint('di-opt-put-strike', opts.highest_put_oi_strike?.toLocaleString('en-IN') ?? '—', 'data-intelligence');
  }

  // ── Earnings Calendar — delegate to enhanced loader ──
  loadEarningsCalendar();
  loadOptionsChain();

  // ── Corporate Filings ──
  const corp = await Api.corporateFilings({ days: 30, limit: 50 });
  _renderCorpTable(corp?.filings || []);
}

function _renderFiiChart(fii, dii) {
  const canvas = document.getElementById('di-fii-chart');
  if (!canvas) return;
  const labels = fii.map(r => r.flow_date).reverse();
  const fiiNet = fii.map(r => r.net_investment ?? 0).reverse();
  const diiNet = dii.map(r => r.net_investment ?? 0).reverse();
  if (ChartRegistryDI['di-fii-chart']) { ChartRegistryDI['di-fii-chart'].destroy(); }
  ChartRegistryDI['di-fii-chart'] = new Chart(canvas, {
    type: 'bar',
    data: {
      labels,
      datasets: [
        { label: 'FII Net', data: fiiNet, backgroundColor: fiiNet.map(v => v >= 0 ? 'rgba(0,255,127,0.55)' : 'rgba(255,80,80,0.55)') },
        { label: 'DII Net', data: diiNet, backgroundColor: diiNet.map(v => v >= 0 ? 'rgba(100,180,255,0.55)' : 'rgba(255,150,50,0.55)') },
      ],
    },
    options: {
      responsive: true, maintainAspectRatio: false,
      plugins: { legend: { labels: { color: '#aaa', font: { size: 10 } } } },
      scales: {
        x: { ticks: { color: '#888', font: { size: 9 }, maxRotation: 45 }, grid: { color: 'rgba(255,255,255,0.04)' } },
        y: { ticks: { color: '#888', font: { size: 9 } }, grid: { color: 'rgba(255,255,255,0.04)' } },
      },
    },
  });
}

function _renderBreadthChart(history) {
  const canvas = document.getElementById('di-breadth-chart');
  if (!canvas || !history.length) return;
  const labels = history.map(r => r.breadth_date);
  const adRatio = history.map(r => r.advance_decline_ratio ?? null);
  if (ChartRegistryDI['di-breadth-chart']) { ChartRegistryDI['di-breadth-chart'].destroy(); }
  ChartRegistryDI['di-breadth-chart'] = new Chart(canvas, {
    type: 'line',
    data: {
      labels,
      datasets: [{
        label: 'A/D Ratio', data: adRatio, borderColor: '#00e5ff', backgroundColor: 'rgba(0,229,255,0.08)',
        borderWidth: 1.5, pointRadius: 0, fill: true,
      }],
    },
    options: {
      responsive: true, maintainAspectRatio: false,
      plugins: { legend: { display: false } },
      scales: {
        x: { ticks: { color: '#888', font: { size: 9 }, maxRotation: 45 }, grid: { color: 'rgba(255,255,255,0.04)' } },
        y: { ticks: { color: '#888', font: { size: 9 } }, grid: { color: 'rgba(255,255,255,0.04)' } },
      },
    },
  });
}

function _renderSectorTable(sectors) {
  const tbody = document.getElementById('di-sector-tbody');
  if (!tbody) return;
  if (!sectors.length) { tbody.innerHTML = '<tr><td colspan="8" style="text-align:center;color:var(--text-secondary)">No data</td></tr>'; return; }
  const phaseColor = { LEADING: '#00e676', WEAKENING: '#ffd740', LAGGING: '#ff5252', IMPROVING: '#40c4ff', NEUTRAL: '#aaa', UNKNOWN: '#666' };
  tbody.innerHTML = sectors.map(s => `
    <tr>
      <td>${s.sector}</td>
      <td style="color:${phaseColor[s.rotation_phase]??'#aaa'};font-weight:600">${s.rotation_phase || '—'}</td>
      <td>${s.rs_rank ?? '—'}</td>
      <td style="color:${(s.ret_20d??0)>=0?'#00e676':'#ff5252'}">${s.ret_20d!=null?s.ret_20d.toFixed(2)+'%':'—'}</td>
      <td style="color:${(s.ret_60d??0)>=0?'#00e676':'#ff5252'}">${s.ret_60d!=null?s.ret_60d.toFixed(2)+'%':'—'}</td>
      <td>${s.rs_vs_nifty_20d!=null?s.rs_vs_nifty_20d.toFixed(2):'—'}</td>
      <td>${s.avg_sentiment!=null?s.avg_sentiment.toFixed(1):'—'}</td>
      <td style="font-size:0.7rem">${(s.top_stocks||[]).slice(0,3).map(t=>t.symbol).join(', ')||'—'}</td>
    </tr>`).join('');
}

function _renderEarningsTable(calendar) {
  const tbody = document.getElementById('di-earnings-tbody');
  if (!tbody) return;
  if (!calendar.length) { tbody.innerHTML = '<tr><td colspan="5" style="text-align:center;color:var(--text-secondary)">No upcoming earnings</td></tr>'; return; }
  tbody.innerHTML = calendar.map(e => `
    <tr>
      <td>${e.earnings_date}</td>
      <td>${e.symbol}</td>
      <td style="font-size:0.72rem">${e.company_name||'—'}</td>
      <td>${e.period||'—'}</td>
      <td><span class="badge">${e.result_status||'scheduled'}</span></td>
    </tr>`).join('');
}

function _renderCorpTable(filings) {
  const tbody = document.getElementById('di-corp-tbody');
  if (!tbody) return;
  if (!filings.length) { tbody.innerHTML = '<tr><td colspan="5" style="text-align:center;color:var(--text-secondary)">No filings</td></tr>'; return; }
  tbody.innerHTML = filings.map(f => `
    <tr>
      <td>${f.filing_date}</td>
      <td>${f.symbol}</td>
      <td>${f.filing_type||'—'}</td>
      <td style="font-size:0.72rem;max-width:300px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">${f.subject||'—'}</td>
      <td>${f.impact_score!=null?f.impact_score.toFixed(0):'—'}</td>
    </tr>`).join('');
}

function _renderQualityTable(datasets) {
  const tbody = document.getElementById('di-quality-tbody');
  if (!tbody) return;
  if (!datasets.length) { tbody.innerHTML = '<tr><td colspan="7" style="text-align:center;color:var(--text-secondary)">No data</td></tr>'; return; }
  const gradeColor = { A: '#00e676', B: '#69f0ae', C: '#ffd740', D: '#ff9800', F: '#ff5252' };
  tbody.innerHTML = datasets.map(d => `
    <tr>
      <td>${d.dataset_name}</td>
      <td><span class="badge" style="background:${d.status==='ok'?'rgba(0,230,118,0.15)':'rgba(255,82,82,0.15)'};color:${d.status==='ok'?'#00e676':'#ff5252'}">${d.status||'—'}</span></td>
      <td style="color:${gradeColor[d.quality_grade]??'#aaa'};font-weight:700">${d.quality_grade||'—'}</td>
      <td>${d.quality_score!=null?d.quality_score.toFixed(0):'—'}</td>
      <td>${d.total_records!=null?d.total_records.toLocaleString():'—'}</td>
      <td>${d.freshness_hours!=null?d.freshness_hours.toFixed(1):'—'}</td>
      <td style="font-size:0.7rem">${d.last_success||'—'}</td>
    </tr>`).join('');
}

function _mergeQualityWithHealth(sources) {
  const tbody = document.getElementById('di-quality-tbody');
  if (!tbody || !tbody.querySelector('td[colspan]')) return;
  if (!sources.length) return;
  tbody.innerHTML = sources.map(s => `
    <tr>
      <td>${s.source_name}</td>
      <td><span class="badge" style="background:${s.status==='ok'?'rgba(0,230,118,0.15)':'rgba(255,82,82,0.15)'};color:${s.status==='ok'?'#00e676':'#ff5252'}">${s.status}</span></td>
      <td>—</td>
      <td>—</td>
      <td>${s.records_fetched??'—'}</td>
      <td>—</td>
      <td style="font-size:0.7rem">${s.last_success_at||'—'}</td>
    </tr>`).join('');
}

async function runDataSupremacyPipeline(btn) {
  const resEl = document.getElementById('di-pipeline-result');
  if (resEl) resEl.textContent = 'Running pipeline…';
  await _withBtnLoading(btn, async () => {
    const r = await Api.triggerDataSupremacy();
    if (resEl) resEl.textContent = r ? `Pipeline complete — ${r.steps_completed ?? '?'} steps` : 'Pipeline failed or backend offline.';
  });
  _liveHydrated.delete('data-intelligence');
  await hydrateDataIntelligence();
}

function _withBtnLoading(btn, fn) {
  if (!btn) return fn();
  const orig = btn.textContent;
  btn.textContent = 'Running…';
  btn.disabled = true;
  return Promise.resolve(fn()).finally(() => { btn.textContent = orig; btn.disabled = false; });
}

async function scrapeCorpFilings(btn) {
  await _withBtnLoading(btn, () => fetch(`${API_CONFIG.BASE}/corporate/scrape`, { method: 'POST' }));
  _liveHydrated.delete('data-intelligence');
  await hydrateDataIntelligence();
}

async function scrapeFiiDii(btn) {
  await _withBtnLoading(btn, () => fetch(`${API_CONFIG.BASE}/fii-dii/scrape`, { method: 'POST' }));
  _liveHydrated.delete('data-intelligence');
  await hydrateDataIntelligence();
}

async function computeBreadth(btn) {
  await _withBtnLoading(btn, () => fetch(`${API_CONFIG.BASE}/market-breadth/compute`, { method: 'POST' }));
  _liveHydrated.delete('data-intelligence');
  await hydrateDataIntelligence();
}

async function computeSectorRotation(btn) {
  await _withBtnLoading(btn, () => fetch(`${API_CONFIG.BASE}/sector-rotation/compute`, { method: 'POST' }));
  _liveHydrated.delete('data-intelligence');
  await hydrateDataIntelligence();
}

async function runQualityChecks(btn) {
  await _withBtnLoading(btn, () => fetch(`${API_CONFIG.BASE}/data-quality/run-checks`, { method: 'POST' }));
  _liveHydrated.delete('data-intelligence');
  await hydrateDataIntelligence();
}


// FII/DII FLOW TRACKER — enhanced charts
// ══════════════════════════════════════════════════════════════
async function loadFiiDiiCharts() {
  const days = document.getElementById('fiidii-days')?.value || 30;
  const data = await Api.fiiDii(days);
  // Backend returns { fii: [...], dii: [...], ... } in descending order (newest first)
  let fiiArr = [], diiArr = [];
  if (data?.fii && Array.isArray(data.fii)) {
    fiiArr = data.fii;
    diiArr = data.dii || [];
  } else if (Array.isArray(data)) {
    fiiArr = data;
  } else if (data?.records) {
    fiiArr = data.records;
  }
  if (!fiiArr.length) return;

  // Reverse to chronological order (oldest→newest) for chart display
  fiiArr = [...fiiArr].reverse();
  diiArr = [...diiArr].reverse();

  const _fld = (r, ...keys) => { for (const k of keys) if (r[k] != null) return r[k]; return 0; };
  const fiiNets   = fiiArr.map(r => _fld(r, 'net_investment', 'fii_net', 'fii_net_value'));
  const diiByDate = Object.fromEntries(diiArr.map(r => [r.flow_date || r.date, r]));
  const diiNets   = fiiArr.map(r => { const d = diiByDate[r.flow_date || r.date]; return d ? _fld(d, 'net_investment', 'dii_net', 'dii_net_value') : 0; });
  const fiiBuy    = fiiArr.map(r => _fld(r, 'gross_buy', 'fii_gross_buy'));
  const fiiSell   = fiiArr.map(r => _fld(r, 'gross_sell', 'fii_gross_sell'));
  const labels    = fiiArr.map(r => (r.flow_date || r.date || '').slice(5)); // show MM-DD

  // KPI cards — use all data (full period totals)
  const fiiNet30 = fiiNets.reduce((s, v) => s + v, 0);
  const diiNet30 = diiNets.reduce((s, v) => s + v, 0);
  const last5fii = fiiNets.slice(-5).filter(v => v > 0).length;
  const last5dii = diiNets.slice(-5).filter(v => v > 0).length;

  const _fmt = v => (v >= 0 ? '+' : '') + Math.round(v).toLocaleString('en-IN') + ' Cr';
  setDataPoint('fii-net-30d', _fmt(fiiNet30), 'data-intelligence');
  const fiiEl = document.getElementById('fii-net-30d');
  if (fiiEl) fiiEl.className = 'kpi-value ' + (fiiNet30 >= 0 ? 'positive' : 'negative');
  setDataPoint('dii-net-30d', _fmt(diiNet30), 'data-intelligence');
  const diiEl = document.getElementById('dii-net-30d');
  if (diiEl) diiEl.className = 'kpi-value ' + (diiNet30 >= 0 ? 'positive' : 'negative');
  setDataPoint('fii-trend', `${last5fii}/5 BUY`, 'data-intelligence');
  const fiiTrendEl = document.getElementById('fii-trend');
  if (fiiTrendEl) fiiTrendEl.className = 'kpi-value ' + (last5fii >= 3 ? 'positive' : 'negative');
  setDataPoint('dii-trend', `${last5dii}/5 BUY`, 'data-intelligence');
  const diiTrendEl = document.getElementById('dii-trend');
  if (diiTrendEl) diiTrendEl.className = 'kpi-value ' + (last5dii >= 3 ? 'positive' : 'negative');

  // Update combined signal badge
  const sigEl = document.getElementById('di-fii-signal');
  if (sigEl && data?.combined_signal) {
    sigEl.textContent = data.combined_signal;
    sigEl.className = 'badge ' + (data.combined_signal.includes('BULL') ? 'badge-green' : data.combined_signal.includes('BEAR') ? 'badge-red' : '');
  }

  // Destroy existing charts safely
  ['chart-fiidii-bar', 'chart-fiidii-cumulative'].forEach(id => {
    const el = document.getElementById(id);
    if (el) { const c = Chart.getChart(el); if (c) c.destroy(); }
  });

  const barCanvas = document.getElementById('chart-fiidii-bar');
  if (barCanvas) new Chart(barCanvas, {
    type: 'bar',
    data: { labels, datasets: [
      { label: 'FII Net (Cr)', data: fiiNets, backgroundColor: fiiNets.map(v => v >= 0 ? 'rgba(0,204,102,0.75)' : 'rgba(255,51,51,0.75)'), borderRadius: 2 },
      { label: 'DII Net (Cr)', data: diiNets, backgroundColor: diiNets.map(v => v >= 0 ? 'rgba(0,170,255,0.65)' : 'rgba(255,140,0,0.65)'), borderRadius: 2 },
    ]},
    options: {
      responsive: true, maintainAspectRatio: false, animation: false,
      plugins: {
        legend: { display: true, labels: { color: '#888', font: { size: 9 }, boxWidth: 10 } },
        tooltip: { mode: 'index', intersect: false, backgroundColor: '#111', borderColor: '#333', borderWidth: 1, titleFont: { size: 9 }, bodyFont: { size: 9 },
          callbacks: { label: ctx => ` ${ctx.dataset.label}: ${ctx.parsed.y >= 0 ? '+' : ''}${Math.round(ctx.parsed.y).toLocaleString('en-IN')} Cr` } },
      },
      scales: {
        x: { stacked: false, ticks: { color: '#555', font: { size: 8 }, maxTicksLimit: 12, maxRotation: 0 }, grid: { color: '#0d0d0d' } },
        y: { ticks: { color: '#666', font: { size: 8 }, callback: v => (v >= 0 ? '+' : '') + Math.round(v/100)/10 + 'k' }, grid: { color: '#111' }, position: 'right' },
      },
    },
  });

  let cumFii = 0, cumDii = 0;
  const cumFiiArr = fiiNets.map(v => { cumFii += v; return Math.round(cumFii); });
  const cumDiiArr = diiNets.map(v => { cumDii += v; return Math.round(cumDii); });
  const cumCanvas = document.getElementById('chart-fiidii-cumulative');
  if (cumCanvas) new Chart(cumCanvas, {
    type: 'line',
    data: { labels, datasets: [
      { label: 'Cumul. FII', data: cumFiiArr, borderColor: '#00cc66', backgroundColor: 'rgba(0,204,102,0.08)', borderWidth: 1.5, pointRadius: 0, fill: true, tension: 0.3 },
      { label: 'Cumul. DII', data: cumDiiArr, borderColor: '#00aaff', backgroundColor: 'rgba(0,170,255,0.08)', borderWidth: 1.5, pointRadius: 0, fill: true, tension: 0.3 },
    ]},
    options: {
      responsive: true, maintainAspectRatio: false, animation: false,
      plugins: {
        legend: { display: true, labels: { color: '#888', font: { size: 9 }, boxWidth: 10 } },
        tooltip: { mode: 'index', intersect: false, backgroundColor: '#111', borderColor: '#333', borderWidth: 1, titleFont: { size: 9 }, bodyFont: { size: 9 },
          callbacks: { label: ctx => ` ${ctx.dataset.label}: ${ctx.parsed.y >= 0 ? '+' : ''}${ctx.parsed.y.toLocaleString('en-IN')} Cr` } },
      },
      scales: {
        x: { ticks: { color: '#444', font: { size: 8 }, maxTicksLimit: 8, maxRotation: 0 }, grid: { color: '#0d0d0d' } },
        y: { ticks: { color: '#666', font: { size: 8 }, callback: v => (v >= 0 ? '+' : '') + Math.round(v/100)/10 + 'k' }, grid: { color: '#111' }, position: 'right' },
      },
    },
  });

  // Table — show last 10 sessions, newest first
  const tbody = document.getElementById('fiidii-table-body');
  if (tbody) {
    const _fmtCr = v => (v >= 0 ? '+' : '') + Math.round(v).toLocaleString('en-IN') + ' Cr';
    const rows = [];
    const count = fiiArr.length;
    // Iterate newest→oldest (reversed array is already oldest→newest, so go backwards)
    for (let i = count - 1; i >= Math.max(0, count - 10); i--) {
      const fn = fiiNets[i] || 0;
      const dn = diiNets[i] || 0;
      const gb = fiiBuy[i] || 0;
      const gs = fiiSell[i] || 0;
      const comb = fn + dn;
      const dateStr = fiiArr[i]?.flow_date || fiiArr[i]?.date || labels[i] || '—';
      rows.push(`<tr>
        <td>${dateStr}</td>
        <td class="positive">${Math.round(gb).toLocaleString('en-IN')} Cr</td>
        <td class="negative">${Math.round(gs).toLocaleString('en-IN')} Cr</td>
        <td class="${fn >= 0 ? 'positive' : 'negative'}">${_fmtCr(fn)}</td>
        <td class="${dn >= 0 ? 'positive' : 'negative'}">${_fmtCr(dn)}</td>
        <td class="${comb >= 0 ? 'positive' : 'negative'}">${_fmtCr(comb)}</td>
      </tr>`);
    }
    tbody.innerHTML = rows.join('');
  }
}

// ══════════════════════════════════════════════════════════════
// EARNINGS CALENDAR
// ══════════════════════════════════════════════════════════════
async function loadEarningsCalendar() {
  const aheadEl = document.getElementById('earnings-ahead');
  const ahead = aheadEl ? aheadEl.value : 14;
  const data = await Api.earningsCalendar(ahead);
  // Backend returns { calendar: [...] }
  const events  = data?.calendar || data?.events || (Array.isArray(data) ? data : []);
  const summary = data?.summary || {};

  setDataPoint('earn-upcoming', events.length || '0', 'data-intelligence');
  const today   = new Date();
  const weekEnd = new Date(today); weekEnd.setDate(today.getDate() + 7);
  const thisWeek = events.filter(e => { const d = new Date(e.date || e.earnings_date || ''); return d >= today && d <= weekEnd; }).length;
  setDataPoint('earn-this-week', thisWeek, 'data-intelligence');
  setDataPoint('earn-beat-rate', summary.beat_rate ? `${summary.beat_rate.toFixed(0)}%` : '—', 'data-intelligence');

  // Populate the earnings-cal-panel table (agent-added IDs)
  const tbody1 = document.getElementById('earnings-cal-body');
  // Also populate the existing di-earnings-tbody in data-intelligence page
  const tbody2 = document.getElementById('di-earnings-tbody');

  const rowHtml = events.map(e => {
    const surprise = e.surprise_pct;
    const ss = surprise != null ? `${surprise >= 0 ? '+' : ''}${surprise.toFixed(1)}%` : '—';
    const sc = surprise != null ? (surprise >= 0 ? 'positive' : 'negative') : '';
    const isPast = new Date(e.date || e.earnings_date || '') < today;
    return `<tr style="${!isPast ? 'background:rgba(255,140,0,0.04)' : ''}">
      <td>${e.date || e.earnings_date || '—'}</td>
      <td><strong>${e.symbol || '—'}</strong></td>
      <td style="color:#666">${e.company_name || e.sector || e.company || '—'}</td>
      <td>${e.quarter || 'Q Results'}</td>
      <td>${e.estimated_eps != null ? e.estimated_eps.toFixed(2) : '—'}</td>
      <td>${e.actual_eps != null ? e.actual_eps.toFixed(2) : '—'}</td>
      <td class="${sc}">${ss}</td>
    </tr>`;
  }).join('') || '<tr><td colspan="7" style="text-align:center;color:#444;padding:16px">No upcoming earnings data</td></tr>';

  if (tbody1) tbody1.innerHTML = rowHtml;
  if (tbody2) tbody2.innerHTML = rowHtml;
}

// ══════════════════════════════════════════════════════════════
// OPTIONS CHAIN VIEWER
// ══════════════════════════════════════════════════════════════
async function loadOptionsChain() {
  const sym    = document.getElementById('chain-symbol')?.value  || 'NIFTY';
  const expiry = document.getElementById('chain-expiry')?.value  || 0;
  const tbody  = document.getElementById('options-chain-body');
  if (tbody) tbody.innerHTML = '<tr><td colspan="9" style="text-align:center;color:#666;padding:16px">Fetching live options data…</td></tr>';

  const data = await Api.optionsChain(sym, expiry);

  setDataPoint('chain-spot',    data?.spot_price ? `₹${(data.spot_price).toLocaleString('en-IN')}` : '—', 'data-intelligence');
  const pcr = data?.pcr;
  setDataPoint('chain-pcr',     pcr ? pcr.toFixed(2) : '—', 'data-intelligence');
  const chainPcrEl = document.getElementById('chain-pcr');
  if (chainPcrEl && pcr) chainPcrEl.className = 'kpi-value ' + (pcr > 1 ? 'positive' : 'negative');
  setDataPoint('chain-maxpain', data?.max_pain ? `₹${data.max_pain.toLocaleString('en-IN')}` : '—', 'data-intelligence');
  setDataPoint('chain-atm',     data?.atm_strike ? `₹${data.atm_strike.toLocaleString('en-IN')}` : '—', 'data-intelligence');
  const expiryEl = document.getElementById('chain-expiry-label');
  if (expiryEl) expiryEl.textContent = `Expiry: ${data?.expiry || 'N/A'}`;

  const chain = data?.chain || [];
  if (!tbody) return;
  if (!chain.length) {
    const msg = data?.message || 'No options data — NSE options are only available during market hours (Mon-Fri 9:15am–3:30pm IST)';
    const spotInfo = data?.spot_price ? ` | Spot: ₹${data.spot_price.toLocaleString('en-IN')}` : '';
    tbody.innerHTML = `<tr><td colspan="9" style="text-align:center;color:#888;padding:24px">${msg}${spotInfo}</td></tr>`;
  } else {
    const atmStrike = data.atm_strike;
    const _fmtOI = v => !v ? '—' : v >= 1e5 ? `${(v / 1e5).toFixed(1)}L` : `${(v / 1000).toFixed(1)}K`;
    const _fmtIV = v => v ? `${v.toFixed(1)}%` : '—';
    tbody.innerHTML = chain.map(row => {
      const isAtm = row.strike === atmStrike;
      return `<tr style="${isAtm ? 'background:rgba(255,140,0,0.08)' : ''}">
        <td style="color:#00cc66;text-align:right">${_fmtOI(row.call_oi)}</td>
        <td style="color:#00cc66;text-align:right">${_fmtOI(row.call_vol)}</td>
        <td style="text-align:right">${_fmtIV(row.call_iv)}</td>
        <td style="color:#00cc66;text-align:right;font-weight:600">${row.call_ltp ? '₹' + row.call_ltp.toFixed(1) : '—'}</td>
        <td style="text-align:center;font-weight:600;background:#111;color:${isAtm ? '#ff8c00' : '#e0e0e0'}">${row.strike.toLocaleString('en-IN')}</td>
        <td style="color:#ff3333;text-align:left;font-weight:600">${row.put_ltp ? '₹' + row.put_ltp.toFixed(1) : '—'}</td>
        <td style="text-align:left">${_fmtIV(row.put_iv)}</td>
        <td style="color:#ff3333;text-align:left">${_fmtOI(row.put_vol)}</td>
        <td style="color:#ff3333;text-align:left">${_fmtOI(row.put_oi)}</td>
      </tr>`;
    }).join('');

    const oiCanvas = document.getElementById('chart-oi-distribution');
    if (oiCanvas) {
      const existing = Chart.getChart('chart-oi-distribution');
      if (existing) existing.destroy();
      const strikes  = chain.map(r => r.strike.toLocaleString('en-IN'));
      const callOIs  = chain.map(r => (r.call_oi || 0) / 1000);
      const putOIs   = chain.map(r => (r.put_oi  || 0) / 1000);
      new Chart(oiCanvas, {
        type: 'bar',
        data: { labels: strikes, datasets: [
          { label: 'Call OI (K)', data: callOIs,              backgroundColor: 'rgba(0,204,102,0.6)' },
          { label: 'Put OI (K)',  data: putOIs.map(v => -v),  backgroundColor: 'rgba(255,51,51,0.6)' },
        ]},
        options: {
          responsive: true, maintainAspectRatio: false, animation: false,
          plugins: { legend: { labels: { color: '#666', font: { size: 9 } } }, tooltip: { mode: 'index', intersect: false, backgroundColor: '#111', borderColor: '#333', borderWidth: 1, titleFont: { size: 9 }, bodyFont: { size: 9 } } },
          scales: {
            x: { ticks: { color: '#444', font: { size: 7 }, maxRotation: 45 }, grid: { color: '#0d0d0d' } },
            y: { ticks: { color: '#666', font: { size: 8 } }, grid: { color: '#111' }, position: 'right' },
          },
        },
      });
    }
  }
}

// ══════════════════════════════════════════════════════════════
