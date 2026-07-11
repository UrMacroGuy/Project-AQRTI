// ui/pages/news.js - split from app.js (ARCH-5), see CHANGELOG
// ═══════════════════════════════════════════════════════════════
// INIT
// ═══════════════════════════════════════════════════════════════
// ═══════════════════════════════════════════════════════════════
// LIVE DATA INTEGRATION
// These functions hydrate rendered pages with real backend data.
// ═══════════════════════════════════════════════════════════════

// ── News Intelligence — live hydration ───────────────────────
async function hydrateNews() {
  const data = await Api.news({ limit: 50, hours: 168 });

  if (!data) {
    const msg = '<div style="padding:32px;text-align:center;color:var(--text-muted);font-size:0.78rem">Backend offline — start the backend server to load news data.</div>';
    const hi = el('news-high-impact'); if (hi) hi.innerHTML = msg;
    const feed = el('news-feed'); if (feed) feed.innerHTML = msg;
    return;
  }
  if (!Array.isArray(data) || !data.length) {
    setDataPoint('news-kpi-count', '0', 'news');
    setDataPoint('news-kpi-high-impact', '0', 'news');
    setDataPoint('news-kpi-entities', '0', 'news');
    const msg = '<div style="padding:32px;text-align:center;color:var(--text-muted);font-size:0.78rem">No news articles in database.<br>Run pipeline from Research Ops → trigger ingestion.</div>';
    const hi = el('news-high-impact'); if (hi) hi.innerHTML = msg;
    const feed = el('news-feed'); if (feed) feed.innerHTML = msg;
    return;
  }

  // KPI cards
  setDataPoint('news-kpi-count', data.length, 'news');
  const highImpactItems = data.filter(n => (n.impactScore ?? n.impact_score ?? 0) >= 80);
  setDataPoint('news-kpi-high-impact', highImpactItems.length, 'news');
  const sentScores = data.map(n => n.sentimentScore || 0).filter(s => s !== 0);
  if (sentScores.length) {
    const avg = sentScores.reduce((a, b) => a + b, 0) / sentScores.length;
    const avgEl = el('news-kpi-avg-sentiment');
    if (avgEl) { avgEl.textContent = `${avg >= 0 ? '+' : ''}${avg.toFixed(2)}`; avgEl.className = 'kpi-value ' + (avg >= 0 ? 'positive' : 'negative'); avgEl.title = `Source: news | ${new Date().toISOString()}`; }
    setDataPoint('news-kpi-sentiment-sub', avg >= 0.1 ? 'Positive Bias Today' : avg <= -0.1 ? 'Negative Bias Today' : 'Neutral Today', 'news');
  }
  const entities = new Set(data.map(n => n.company).filter(Boolean));
  setDataPoint('news-kpi-entities', entities.size || '—', 'news');

  function impactSeverity(score) {
    if (score >= 75) return 'critical';
    if (score >= 55) return 'high';
    if (score >= 35) return 'medium';
    return 'low';
  }

  function sentTag(label) {
    const map = { positive: 'pos', negative: 'neg', neutral: 'neu' };
    return map[label] || 'neu';
  }

  const mapped = data.map(n => ({
    headline:  n.headline,
    source:    n.source || '—',
    company:   n.company || '—',
    sector:    n.sector  || '—',
    eventType: n.event_type || n.eventType || 'General',
    impact:    Math.round(n.impact_score ?? n.impactScore ?? 0),
    severity:  impactSeverity(n.impact_score ?? n.impactScore ?? 0),
    sentiment: sentTag(n.sentiment),
    time:      n.timestamp ? new Date(n.timestamp).toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit' }) : '—',
  }));

  const sentLabels = { pos: 'Positive', neg: 'Negative', neu: 'Neutral' };
  const sevMap     = { critical: 'critical', high: 'high', medium: 'medium', low: 'low' };

  function newsItemHTML(item) {
    return `
      <div class="news-item">
        <div class="news-impact-badge ${sevMap[item.severity]}">${item.impact}</div>
        <div class="news-content">
          <div class="news-headline">${item.headline}</div>
          <div class="news-meta">
            <span>${item.source}</span>
            <span>${item.company}</span>
            <span>${item.sector}</span>
            <span>${item.eventType}</span>
            <span>${item.time} IST</span>
            <span class="news-sentiment-tag ${item.sentiment}">${sentLabels[item.sentiment]}</span>
          </div>
        </div>
      </div>`;
  }

  const highImpact = el('news-high-impact');
  if (highImpact) {
    const hi = mapped.filter(n => n.impact >= 70);
    if (hi.length) highImpact.innerHTML = hi.map(newsItemHTML).join('');
  }

  const feed = el('news-feed');
  if (feed && mapped.length) {
    feed.innerHTML = mapped.map(newsItemHTML).join('');
  }

  // Rebuild sentiment trend chart from live timestamps
  if (mapped.length) {
    const hourBuckets = {};
    mapped.forEach(n => {
      if (!n.time || n.time === '—') return;
      const hr = n.time.split(':')[0];
      if (!hourBuckets[hr]) hourBuckets[hr] = [];
      const raw = data.find(d => d.headline === n.headline);
      const score = raw ? (raw.sentiment_score ?? raw.sentimentScore ?? (n.sentiment === 'pos' ? 0.5 : n.sentiment === 'neg' ? -0.5 : 0)) : 0;
      hourBuckets[hr].push(score);
    });
    const hours = Array.from({length: 24}, (_, i) => `${String(i).padStart(2,'0')}:00`);
    const sentVals = hours.map((_, i) => {
      const key = String(i).padStart(2,'0');
      const bucket = hourBuckets[key];
      return bucket && bucket.length ? bucket.reduce((a, b) => a + b, 0) / bucket.length : null;
    });
    ChartRegistry.create('newsSentimentTrendChart', {
      type: 'line',
      data: {
        labels: hours,
        datasets: [{
          label: 'Avg Sentiment',
          data: sentVals,
          borderColor: 'var(--accent)',
          borderWidth: 2,
          pointRadius: 2,
          pointBackgroundColor: 'var(--accent)',
          tension: 0.4,
          fill: true,
          backgroundColor: 'rgba(232,232,234,0.06)',
          spanGaps: true,
        }],
      },
      options: {
        responsive: true, maintainAspectRatio: false,
        plugins: { legend: { display: false } },
        scales: {
          y: { min: -1, max: 1, ticks: { stepSize: 0.5, callback: v => v > 0 ? `+${v}` : v } },
          x: { ticks: { maxTicksLimit: 8 } },
        },
      },
    });
  }
}

// ── Research Synthesis — LLM-derived per-symbol thesis, cited sources ──
// Part of the merged Research page (news.js + sentiment.js, see CLAUDE.md
// §7 UI revamp). Every row must trace to real source_event_ids — if the
// synthesizer hasn't run yet for a symbol, that symbol shows NO DATA
// rather than a fabricated thesis.
async function hydrateResearchSynthesis() {
  const body = el('research-synthesis-body');
  if (!body) return;
  const data = await Api.researchSynthesisLatest();
  if (!data) {
    body.innerHTML = '<div style="text-align:center;color:var(--text-muted);padding:20px;font-size:0.78rem">Backend offline — start the backend server to load research synthesis.</div>';
    return;
  }
  const rows = data.synthesis || [];
  if (!rows.length) {
    body.innerHTML = '<div style="text-align:center;color:var(--text-muted);padding:20px;font-size:0.78rem">NO DATA — no research synthesis generated yet. Run the research pipeline from Research Ops.</div>';
    return;
  }
  const dirCls = d => d === 'bullish' ? 'positive' : d === 'bearish' ? 'negative' : '';
  body.innerHTML = `
    <div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:10px">
      ${rows.map(r => {
        const catalysts = (r.key_catalysts || []).slice(0, 3);
        const risks = (r.risk_flags || []).slice(0, 2);
        const sourceCount = (r.source_event_ids || []).length;
        return `
        <div class="panel" style="margin:0">
          <div class="panel-header" style="padding:8px 10px">
            <span class="panel-title" style="font-size:0.82rem">${r.symbol}</span>
            <span class="${dirCls(r.thesis_direction)}" style="margin-left:auto;font-size:0.72rem;font-weight:600;text-transform:uppercase">${r.thesis_direction}</span>
          </div>
          <div class="panel-body" style="padding:8px 10px;font-size:0.74rem">
            <div style="color:var(--text-muted);font-size:0.68rem">${r.synthesis_date} · ${r.model_used || '—'}${r.confidence != null ? ' · conf ' + Math.round(r.confidence * 100) + '%' : ''}</div>
            ${catalysts.length ? `<div style="margin-top:6px"><strong>Catalysts:</strong> ${catalysts.join(', ')}</div>` : ''}
            ${risks.length ? `<div style="margin-top:4px;color:var(--negative)"><strong>Risks:</strong> ${risks.join(', ')}</div>` : ''}
            ${r.management_change_flag ? `<div style="margin-top:4px;color:var(--warning)">⚠ Management change flagged</div>` : ''}
            <a href="javascript:void(0)" onclick="showCockpitSources('${r.symbol}')" style="display:inline-block;margin-top:6px;font-size:0.68rem;color:var(--accent)">${sourceCount} cited source${sourceCount !== 1 ? 's' : ''} →</a>
          </div>
        </div>`;
      }).join('')}
    </div>`;
}

// ── Sentiment Center — live hydration ────────────────────────
