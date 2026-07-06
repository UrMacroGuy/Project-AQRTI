// ui/pages/live-prices.js - split from app.js (ARCH-5), see CHANGELOG

// ── Live Prices — real-time index/commodity quotes ────────────
let _livePricesTimer = null;

async function hydrateLivePrices() {
  await refreshLivePrices();
  // Auto-refresh every 5 seconds while the page is visible
  if (_livePricesTimer) clearInterval(_livePricesTimer);
  _livePricesTimer = setInterval(() => {
    const page = document.getElementById('page-live-prices');
    if (page && page.classList.contains('active')) refreshLivePrices();
    else clearInterval(_livePricesTimer);
  }, 5000);
  loadCandleChart();
}

async function refreshLivePrices() {
  const grid      = document.getElementById('live-prices-grid');
  const tableBody = document.getElementById('live-prices-table-body');
  const updatedEl = document.getElementById('live-prices-updated');

  const data = await Api.livePrices();

  if (!data || !data.length) {
    if (grid) grid.innerHTML = '<div class="kpi-card" style="grid-column:1/-1;text-align:center;color:var(--text-muted)">Live prices unavailable — backend offline</div>';
    return;
  }

  if (updatedEl) updatedEl.textContent = 'Updated: ' + new Date().toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit', second: '2-digit' });

  // ── KPI grid ────────────────────────────────────────────────
  const ICONS = { nifty50: '◈', sensex: '◎', banknifty: '◉', niftyit: '▦', usdinr: '₹', gold: '◆', crude: '◉' };
  const FMT = {
    nifty50:   v => v.toLocaleString('en-IN', { maximumFractionDigits: 2 }),
    sensex:    v => v.toLocaleString('en-IN', { maximumFractionDigits: 2 }),
    banknifty: v => v.toLocaleString('en-IN', { maximumFractionDigits: 2 }),
    niftyit:   v => v.toLocaleString('en-IN', { maximumFractionDigits: 2 }),
    usdinr:    v => '₹' + v.toFixed(2),
    gold:      v => '$' + v.toLocaleString('en-IN', { maximumFractionDigits: 2 }),
    crude:     v => '$' + v.toFixed(2),
  };

  if (grid) {
    grid.innerHTML = data.map(d => {
      if (d.price == null) return `
        <div class="kpi-card" style="text-align:center">
          <div class="kpi-label">${ICONS[d.key] || '◎'} ${d.label}</div>
          <div class="kpi-value" style="color:var(--text-muted)">—</div>
          <div class="kpi-sub">Unavailable</div>
        </div>`;
      const isUp    = (d.changePct || 0) >= 0;
      const color   = isUp ? 'var(--positive)' : 'var(--negative)';
      const arrow   = isUp ? '▲' : '▼';
      const sign    = isUp ? '+' : '';
      const fmtFn   = FMT[d.key] || (v => v.toLocaleString('en-IN', { maximumFractionDigits: 2 }));
      return `
        <div class="kpi-card" style="text-align:center;border-color:${isUp ? 'rgba(255,140,0,0.2)' : 'rgba(255,51,51,0.2)'}">
          <div class="kpi-label">${ICONS[d.key] || '◎'} ${d.label}</div>
          <div class="kpi-value" style="color:${color};font-size:1.05rem">${fmtFn(d.price)}</div>
          <div class="kpi-sub" style="color:${color}">${arrow} ${sign}${d.change != null ? Math.abs(d.change).toLocaleString('en-IN', {maximumFractionDigits:2}) : '—'} (${sign}${(d.changePct || 0).toFixed(2)}%)</div>
        </div>`;
    }).join('');
  }

  // ── Table ────────────────────────────────────────────────────
  if (tableBody) {
    tableBody.innerHTML = data.map(d => {
      if (d.price == null) return `<tr><td>${d.label}</td><td colspan="4" style="color:var(--text-muted)">Unavailable</td></tr>`;
      const isUp  = (d.changePct || 0) >= 0;
      const cls   = isUp ? 'positive' : 'negative';
      const sign  = isUp ? '+' : '';
      const fmtFn = FMT[d.key] || (v => v.toLocaleString('en-IN', { maximumFractionDigits: 2 }));
      return `
        <tr>
          <td><strong>${d.label}</strong></td>
          <td>${fmtFn(d.price)}</td>
          <td class="${cls}">${sign}${d.change != null ? d.change.toLocaleString('en-IN', {maximumFractionDigits:2}) : '—'}</td>
          <td class="${cls}">${sign}${(d.changePct || 0).toFixed(2)}%</td>
          <td><span style="color:${isUp?'var(--positive)':'var(--negative)'};font-size:1.1rem">${isUp ? '▲' : '▼'}</span></td>
        </tr>`;
    }).join('');
  }

  // ── Charts: Nifty50 + Sensex history from DB ─────────────────
  const [niftyHist, sensexHist] = await Promise.all([
    Api.indexHistory('NIFTY50', 30).catch(() => null),
    Api.indexHistory('BANKNIFTY', 30).catch(() => null),
  ]);

  function buildHistChart(canvasId, histData, label, color) {
    // API returns a flat array directly
    const hist = Array.isArray(histData) ? histData : (histData?.history || []);
    if (!hist.length) return;
    ChartRegistry.create(canvasId, {
      type: 'line',
      data: {
        labels: hist.map(h => h.date?.slice(5)),
        datasets: [{
          label,
          data: hist.map(h => h.close),
          borderColor: color,
          borderWidth: 2,
          pointRadius: 0,
          tension: 0.3,
          fill: true,
          backgroundColor: (ctx) => {
            const g = ctx.chart.ctx.createLinearGradient(0, 0, 0, ctx.chart.height);
            const rgba = (a) => color.startsWith('rgb(') ? color.replace('rgb(', 'rgba(').replace(')', `,${a})`) : color;
            g.addColorStop(0, rgba(0.18));
            g.addColorStop(1, rgba(0.00));
            return g;
          },
        }],
      },
      options: {
        responsive: true, maintainAspectRatio: false,
        plugins: { legend: { display: false }, tooltip: { callbacks: { label: ctx => ` ${ctx.parsed.y.toLocaleString('en-IN', {maximumFractionDigits:2})}` }}},
        scales: {
          x: { ticks: { maxTicksLimit: 8, maxRotation: 0 }, grid: { color: '#0d0d0d' }},
          y: { ticks: { maxTicksLimit: 5, callback: v => v.toLocaleString('en-IN', {maximumFractionDigits:0}) }, grid: { color: '#0d0d0d' }},
        },
      },
    });
  }

  buildHistChart('liveNiftyChart',  niftyHist,  'Nifty 50',  'rgb(255,140,0)');
  buildHistChart('liveSensexChart', sensexHist, 'Bank Nifty', 'rgb(0,170,255)');
}

// ── Risk Center — live hydration ─────────────────────────────
// CANDLESTICK CHART + TECHNICAL OVERLAYS
// ══════════════════════════════════════════════════════════════
const _candleState = { overlays: { ema: true, bb: false, vol: true }, data: null };

async function loadCandleChart() {
  const sym  = document.getElementById('candle-symbol')?.value || 'RELIANCE';
  const days = document.getElementById('candle-days')?.value  || 90;
  const data = await Api.stockOhlcv(sym, days);
  if (!data || !data.candles || !data.candles.length) return;
  _candleState.data = data;
  renderCandleChart(data);
  const last = data.candles[data.candles.length - 1];
  if (last) {
    setDataPoint('ci-open',  `₹${(last.open  || 0).toFixed(1)}`, 'live-prices');
    setDataPoint('ci-high',  `₹${(last.high  || 0).toFixed(1)}`, 'live-prices');
    setDataPoint('ci-low',   `₹${(last.low   || 0).toFixed(1)}`, 'live-prices');
    setDataPoint('ci-close', `₹${(last.close || 0).toFixed(1)}`, 'live-prices');
    setDataPoint('ci-vol',   last.volume ? `${(last.volume / 1e5).toFixed(1)}L` : '—', 'live-prices');
    const lastRsi = (data.rsi || []).filter(v => v !== null).pop();
    setDataPoint('ci-rsi', lastRsi ? lastRsi.toFixed(1) : '—', 'live-prices');
  }
}

function toggleCandleOverlay(name) {
  _candleState.overlays[name] = !_candleState.overlays[name];
  const btn = document.getElementById(`candle-overlay-${name}`);
  if (btn) btn.style.borderColor = _candleState.overlays[name] ? '#ff8c00' : '#333';
  if (_candleState.data) renderCandleChart(_candleState.data);
}

function renderCandleChart(data) {
  const candles = data && data.candles ? data.candles : [];
  if (candles.length === 0) {
    ['chart-candlestick', 'chart-rsi', 'chart-macd'].forEach(id => {
      const existing = Chart.getChart(id);
      if (existing) existing.destroy();
    });
    document.getElementById('chart-area').innerHTML = '<div class="empty-state">NO DATA — source unavailable</div>';
    return;
  }
  const labels  = candles.map(c => c.date);

  ['chart-candlestick', 'chart-rsi', 'chart-macd'].forEach(id => {
    const existing = Chart.getChart(id);
    if (existing) existing.destroy();
  });

  // ── Price chart ──
  const priceDsets = [{
    label: 'Close', data: candles.map(c => c.close),
    type: 'line', borderColor: '#ff8c00', borderWidth: 1.5,
    pointRadius: 0, fill: false, tension: 0, order: 1,
  }];
  if (_candleState.overlays.ema && data.ema20) {
    priceDsets.push({ label: 'EMA20', data: data.ema20, type: 'line', borderColor: '#00aaff', borderWidth: 1, pointRadius: 0, fill: false, tension: 0, order: 2 });
  }
  if (_candleState.overlays.ema && data.ema50) {
    priceDsets.push({ label: 'EMA50', data: data.ema50, type: 'line', borderColor: '#ffcc00', borderWidth: 1, pointRadius: 0, fill: false, tension: 0, order: 3 });
  }
  if (_candleState.overlays.bb && data.bb_upper) {
    priceDsets.push({ label: 'BB Upper', data: data.bb_upper, type: 'line', borderColor: 'rgba(0,204,102,0.5)', borderWidth: 1, pointRadius: 0, fill: false, tension: 0, borderDash: [3, 3], order: 4 });
    priceDsets.push({ label: 'BB Lower', data: data.bb_lower, type: 'line', borderColor: 'rgba(0,204,102,0.5)', borderWidth: 1, pointRadius: 0, fill: false, tension: 0, borderDash: [3, 3], order: 5 });
    priceDsets.push({ label: 'BB Mid',   data: data.bb_mid,   type: 'line', borderColor: 'rgba(0,204,102,0.3)', borderWidth: 1, pointRadius: 0, fill: false, tension: 0, order: 6 });
  }

  const _chartOpts = (extra = {}) => ({
    responsive: true, maintainAspectRatio: false, animation: false,
    plugins: {
      legend: { display: true, labels: { color: '#666', font: { size: 9 }, boxWidth: 12 } },
      tooltip: { mode: 'index', intersect: false, backgroundColor: '#111', borderColor: '#333', borderWidth: 1, titleColor: '#888', bodyColor: '#ccc', titleFont: { size: 9 }, bodyFont: { size: 9 } },
    },
    scales: {
      x: { ticks: { color: '#444', font: { size: 8 }, maxTicksLimit: 8, maxRotation: 0 }, grid: { color: '#0d0d0d' } },
      y: { ticks: { color: '#666', font: { size: 8 } }, grid: { color: '#111' }, position: 'right' },
      ...extra,
    },
  });

  const priceCanvas = document.getElementById('chart-candlestick');
  if (priceCanvas) new Chart(priceCanvas, { type: 'line', data: { labels, datasets: priceDsets }, options: _chartOpts() });

  // ── RSI sub-chart ──
  const rsiCanvas = document.getElementById('chart-rsi');
  if (rsiCanvas) new Chart(rsiCanvas, {
    type: 'line',
    data: { labels, datasets: [{ label: 'RSI', data: data.rsi, borderColor: '#ff8c00', borderWidth: 1.5, pointRadius: 0, fill: false, tension: 0 }] },
    options: {
      responsive: true, maintainAspectRatio: false, animation: false,
      plugins: { legend: { display: false }, tooltip: { mode: 'index', intersect: false, backgroundColor: '#111', borderColor: '#333', borderWidth: 1, titleFont: { size: 9 }, bodyFont: { size: 9 } } },
      scales: {
        x: { display: false },
        y: { min: 0, max: 100, ticks: { color: '#444', font: { size: 8 }, stepSize: 30 }, grid: { color: '#111' }, position: 'right' },
      },
    },
  });

  // ── MACD sub-chart ──
  const macdCanvas = document.getElementById('chart-macd');
  if (macdCanvas) new Chart(macdCanvas, {
    type: 'bar',
    data: {
      labels,
      datasets: [
        { label: 'MACD Hist', data: data.macd_hist, backgroundColor: (data.macd_hist || []).map(v => (v || 0) >= 0 ? 'rgba(0,204,102,0.6)' : 'rgba(255,51,51,0.6)'), type: 'bar', order: 3 },
        { label: 'MACD',   data: data.macd,        borderColor: '#00aaff', borderWidth: 1.5, type: 'line', pointRadius: 0, fill: false, tension: 0, order: 1 },
        { label: 'Signal', data: data.macd_signal, borderColor: '#ff8c00', borderWidth: 1,   type: 'line', pointRadius: 0, fill: false, tension: 0, order: 2 },
      ],
    },
    options: {
      responsive: true, maintainAspectRatio: false, animation: false,
      plugins: { legend: { display: false }, tooltip: { mode: 'index', intersect: false, backgroundColor: '#111', borderColor: '#333', borderWidth: 1, titleFont: { size: 9 }, bodyFont: { size: 9 } } },
      scales: { x: { display: false }, y: { ticks: { color: '#444', font: { size: 8 } }, grid: { color: '#111' }, position: 'right' } },
    },
  });
}

// ══════════════════════════════════════════════════════════════
