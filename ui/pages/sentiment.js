// ui/pages/sentiment.js - split from app.js (ARCH-5), see CHANGELOG
async function hydrateSentiment() {
  const data = await Api.sentiment();
  if (!data) {
    const offlineMsg = '<div style="padding:32px;text-align:center;color:var(--text-muted);font-size:0.78rem">Backend offline — start the backend server to load sentiment data.</div>';
    const velBody = el('sentiment-velocity-body');
    if (velBody) velBody.innerHTML = offlineMsg;
    const compCanvas = el('companySentimentChart');
    if (compCanvas && compCanvas.parentElement) compCanvas.parentElement.innerHTML = offlineMsg;
    const secCanvas = el('sectorSentimentChart');
    if (secCanvas && secCanvas.parentElement) secCanvas.parentElement.innerHTML = offlineMsg;
    return;
  }

  const { companies = [], sectors = [], market } = data;

  // KPI cards — prefer data.market fields, fall back to deriving from companies
  if (market && market.label) {
    setDataPoint('sent-kpi-market', market.label, 'sentiment');
    const score = market.score != null ? market.score : '—';
    setDataPoint('sent-kpi-market-sub', score !== '—' ? `Score: ${Math.round(score)} / 100` : 'No data yet', 'sentiment');
    const fg = market.fearGreed != null ? market.fearGreed : (market.score != null ? Math.round(market.score) : null);
    if (fg != null) {
      const zone = fg >= 75 ? 'Extreme Greed' : fg >= 60 ? 'Greed Zone' : fg >= 40 ? 'Neutral Zone' : fg >= 25 ? 'Fear Zone' : 'Extreme Fear';
      setDataPoint('sent-kpi-fear-greed', fg, 'sentiment');
      setDataPoint('sent-kpi-fear-greed-sub', zone, 'sentiment');
    }
  } else if (companies.length) {
    const avgScore = companies.reduce((s, c) => s + (c.score || 0), 0) / companies.length;
    const sentiment = avgScore >= 70 ? 'Optimistic' : avgScore >= 50 ? 'Neutral' : 'Pessimistic';
    setDataPoint('sent-kpi-market', sentiment, 'sentiment');
    setDataPoint('sent-kpi-market-sub', `Score: ${avgScore.toFixed(0)} / 100`, 'sentiment');
    const fearGreed = Math.round(avgScore);
    const zone = fearGreed >= 75 ? 'Extreme Greed' : fearGreed >= 60 ? 'Greed Zone' : fearGreed >= 40 ? 'Neutral Zone' : fearGreed >= 25 ? 'Fear Zone' : 'Extreme Fear';
    setDataPoint('sent-kpi-fear-greed', fearGreed, 'sentiment');
    setDataPoint('sent-kpi-fear-greed-sub', zone, 'sentiment');
  }

  if (companies.length) {
    const sorted = [...companies].sort((a, b) => (b.score || 0) - (a.score || 0));
    const best = sorted[0];
    const worst = sorted[sorted.length - 1];
    if (best) { setDataPoint('sent-kpi-best', best.entity || '—', 'sentiment'); setDataPoint('sent-kpi-best-score', `Score: ${Math.round(best.score || 0)}`, 'sentiment'); }
    if (worst) { setDataPoint('sent-kpi-worst', worst.entity || '—', 'sentiment'); setDataPoint('sent-kpi-worst-score', `Score: ${Math.round(worst.score || 0)}`, 'sentiment'); }
  }

  const emptyMsg = '<div style="padding:32px;text-align:center;color:var(--text-muted);font-size:0.78rem">No sentiment data in database.<br>Run pipeline from Research Ops → trigger ingestion.</div>';

  if (companies.length) {
    const top = companies.slice(0, 10);
    ChartRegistry.create('companySentimentChart', {
      type: 'bar',
      data: {
        labels: top.map(s => s.entity),
        datasets: [{
          label: 'Sentiment Score',
          data: top.map(s => s.score),
          backgroundColor: top.map(s =>
            s.score >= 70 ? 'rgba(34,197,94,0.7)'
            : s.score >= 50 ? 'rgba(255,140,0,0.7)'
            : 'rgba(239,68,68,0.6)'
          ),
          borderRadius: 4,
        }],
      },
      options: {
        responsive: true, maintainAspectRatio: false,
        plugins: { legend: { display: false } },
        scales: { y: { min: 0, max: 100, ticks: { stepSize: 25 } } },
      },
    });

    const velBody = el('sentiment-velocity-body');
    if (velBody) {
      const sorted = [...companies].sort((a, b) => Math.abs(b.velocity||0) - Math.abs(a.velocity||0)).slice(0, 10);
      velBody.innerHTML = sorted.map(s => {
        const vel   = s.velocity || 0;
        const isPos = vel > 0;
        const barW  = Math.min(Math.abs(vel) * 1000, 100);
        const color = isPos ? 'var(--positive)' : 'var(--negative)';
        return `
          <div class="velocity-item">
            <span class="velocity-symbol">${s.entity}</span>
            <div class="velocity-bar-wrap">
              <div class="score-bar-track">
                <div class="score-bar-fill" style="width:${barW}%; background:${color}"></div>
              </div>
            </div>
            <span class="velocity-label" style="color:${color}">${isPos ? '+' : ''}${vel.toFixed(3)}</span>
          </div>`;
      }).join('');
    }
  } else {
    const compCanvas = el('companySentimentChart');
    if (compCanvas && compCanvas.parentElement) compCanvas.parentElement.innerHTML = emptyMsg;
    const velBody = el('sentiment-velocity-body');
    if (velBody) velBody.innerHTML = emptyMsg;
  }

  if (sectors && sectors.length) {
    ChartRegistry.create('sectorSentimentChart', {
      type: 'radar',
      data: {
        labels: sectors.map(s => s.entity),
        datasets: [{
          label: 'Sector Sentiment',
          data: sectors.map(s => s.score),
          borderColor: '#ff8c00',
          backgroundColor: 'rgba(255,140,0,0.08)',
          pointBackgroundColor: '#ff8c00',
          borderWidth: 1.5, pointRadius: 3,
        }],
      },
      options: {
        responsive: true, maintainAspectRatio: false,
        plugins: { legend: { display: false } },
        scales: { r: { min: 0, max: 100, ticks: { stepSize: 25, backdropColor: 'transparent' }, grid: { color: 'rgba(255,255,255,0.06)' }, angleLines: { color: 'rgba(255,255,255,0.06)' } } },
      },
    });
  } else {
    const secCanvas = el('sectorSentimentChart');
    if (secCanvas && secCanvas.parentElement) secCanvas.parentElement.innerHTML = emptyMsg;
  }
}

// ── Market Intelligence — regime badge hydration ──────────────
