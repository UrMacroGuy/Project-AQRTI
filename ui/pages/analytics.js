// ui/pages/analytics.js - split from app.js (ARCH-5), see CHANGELOG
// MARKET ANALYTICS — Sector Breadth + Correlation Matrix
// ══════════════════════════════════════════════════════════════
async function hydrateAnalytics() {
  loadSectorBreadth();
  loadCorrelationMatrix();
}

async function loadSectorBreadth() {
  const data    = await Api.sectorBreadth();
  if (data === null) {
    const tbody = document.getElementById('breadth-table-body');
    if (tbody) tbody.innerHTML = '<tr><td colspan="6" style="text-align:center;color:var(--text-muted);padding:32px">Backend offline — start the backend server to load data.</td></tr>';
    return;
  }
  const sectors = data?.sectors || [];

  const labels   = sectors.map(s => s.name.replace(' & ', '/').substring(0, 12));
  const above20  = sectors.map(s => s.above_20ma_pct  || 0);
  const above50  = sectors.map(s => s.above_50ma_pct  || 0);
  const above200 = sectors.map(s => s.above_200ma_pct || 0);

  const existing = Chart.getChart('chart-sector-breadth');
  if (existing) existing.destroy();

  const canvas = document.getElementById('chart-sector-breadth');
  if (canvas) new Chart(canvas, {
    type: 'bar',
    data: { labels, datasets: [
      { label: 'Above 20MA',  data: above20,  backgroundColor: 'rgba(0,204,102,0.7)' },
      { label: 'Above 50MA',  data: above50,  backgroundColor: 'rgba(0,170,255,0.6)' },
      { label: 'Above 200MA', data: above200, backgroundColor: 'rgba(255,140,0,0.5)' },
    ]},
    options: {
      responsive: true, maintainAspectRatio: false, animation: false,
      plugins: { legend: { labels: { color: '#666', font: { size: 9 } } }, tooltip: { mode: 'index', intersect: false, backgroundColor: '#111', borderColor: '#333', borderWidth: 1, titleFont: { size: 9 }, bodyFont: { size: 9 } } },
      scales: {
        x: { ticks: { color: '#555', font: { size: 8 }, maxRotation: 30 }, grid: { color: '#0d0d0d' } },
        y: { min: 0, max: 100, ticks: { color: '#666', font: { size: 8 }, callback: v => v + '%' }, grid: { color: '#111' }, position: 'right' },
      },
    },
  });

  const tbody = document.getElementById('breadth-table-body');
  if (tbody) {
    tbody.innerHTML = sectors.map(s => {
      const trend   = s.above_20ma_pct >= 60 ? 'BULLISH' : s.above_20ma_pct <= 40 ? 'BEARISH' : 'MIXED';
      const trendCls = trend === 'BULLISH' ? 'positive' : trend === 'BEARISH' ? 'negative' : 'neutral';
      return `<tr>
        <td>${s.name}</td>
        <td>${s.stocks_total}</td>
        <td class="${s.above_20ma_pct  >= 50 ? 'positive' : 'negative'}">${(s.above_20ma_pct  || 0).toFixed(0)}%</td>
        <td class="${s.above_50ma_pct  >= 50 ? 'positive' : 'negative'}">${(s.above_50ma_pct  || 0).toFixed(0)}%</td>
        <td class="${s.above_200ma_pct >= 50 ? 'positive' : 'negative'}">${(s.above_200ma_pct || 0).toFixed(0)}%</td>
        <td class="${trendCls}">${trend}</td>
      </tr>`;
    }).join('') || '<tr><td colspan="6" style="text-align:center;color:#444;padding:16px">Insufficient price data</td></tr>';
  }
}

async function loadCorrelationMatrix() {
  const days      = document.getElementById('corr-days')?.value || 60;
  const container = document.getElementById('corr-matrix-container');
  if (!container) return;
  container.innerHTML = '<div style="text-align:center;color:#666;padding:16px">Computing correlations…</div>';

  const data = await Api.correlationMatrix(days);
  if (data === null) {
    container.innerHTML = '<div style="text-align:center;color:var(--text-muted);padding:20px">Backend offline — start the backend server to load data.</div>';
    return;
  }
  if (!data || !data.symbols || !data.symbols.length) {
    container.innerHTML = '<div style="text-align:center;color:#444;padding:20px">Insufficient price data for correlation</div>';
    return;
  }

  const { symbols, matrix } = data;
  const n        = symbols.length;
  const cellSize = 28;
  let html = `<table style="border-collapse:collapse;font-size:0.6rem;font-family:inherit">`;
  html += '<tr><td style="width:56px"></td>';
  for (const sym of symbols) {
    html += `<td style="width:${cellSize}px;height:56px;vertical-align:bottom;padding-bottom:2px;overflow:hidden">
      <div style="transform:rotate(-45deg);transform-origin:0 100%;white-space:nowrap;color:#666;font-size:0.55rem;width:${cellSize}px">${sym}</div>
    </td>`;
  }
  html += '</tr>';
  for (let i = 0; i < n; i++) {
    html += `<tr><td style="padding:1px 4px;color:#888;white-space:nowrap;text-align:right;font-size:0.58rem">${symbols[i]}</td>`;
    for (let j = 0; j < n; j++) {
      const val = matrix[i][j];
      if (val === null) { html += `<td style="width:${cellSize}px;height:${cellSize}px;background:#111"></td>`; continue; }
      const r     = val < 0 ? Math.round(255 * Math.abs(val)) : 0;
      const g     = val > 0 ? Math.round(180 * val) : 0;
      const alpha = Math.min(0.9, Math.abs(val) * 0.8 + 0.1);
      const bg    = i === j ? '#1a1a1a' : `rgba(${r},${g},0,${alpha})`;
      const tc    = Math.abs(val) > 0.55 ? '#fff' : '#888';
      const disp  = i === j ? '1.0' : val.toFixed(2);
      html += `<td title="${symbols[i]} vs ${symbols[j]}: ${disp}" style="width:${cellSize}px;height:${cellSize}px;background:${bg};text-align:center;vertical-align:middle;color:${tc};font-size:0.52rem;cursor:default">${disp}</td>`;
    }
    html += '</tr>';
  }
  html += '</table>';
  container.innerHTML = html;
}

