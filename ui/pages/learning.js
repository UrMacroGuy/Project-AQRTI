// ui/pages/learning.js - split from app.js (ARCH-5), see CHANGELOG
async function renderLearning() {
  setDataPoint('lc-kpi-score', 'Loading…', 'learning');
  setDataPoint('lc-kpi-failures', '…', 'learning');
  setDataPoint('lc-kpi-lessons', '…', 'learning');

  // Fire all API calls in parallel — sequential awaits were causing 10s+ load time
  const [liveData, calibration, drift, featIntel, lessonsData] = await Promise.all([
    Api.learningOverview(30).catch(() => null),
    Api.calibrationCurve(30).catch(() => null),
    Api.driftSummary(90).catch(() => null),
    Api.featureRanking(30).catch(() => null),
    Api.lessons({ days: 30 }).catch(() => null),
  ]);

  let scoreHistory   = [];
  let failures       = [];
  let lessons        = [];

  if (liveData) {
    scoreHistory  = liveData.scoreHistory || [];
    failures      = liveData.recentFailures || [];
    lessons       = lessonsData?.lessons || [];

    // KPI updates
    const score = liveData.intelligenceScore || 0;
    const delta = liveData.scoreDelta || 0;
    setDataPoint('lc-kpi-score', `${score.toFixed(1)} / 100`, 'learning');
    setDataPoint('lc-kpi-delta', `${delta >= 0 ? '+' : ''}${delta.toFixed(1)} vs yesterday`, 'learning');
    setDataPoint('lc-kpi-failures', liveData.totalFailures ?? '—', 'learning');
    setDataPoint('lc-kpi-resolved', `${liveData.resolvedFailures ?? 0} resolved`, 'learning');
    setDataPoint('lc-kpi-lessons', liveData.totalLessons ?? '—', 'learning');
    setDataPoint('lc-kpi-applied', `${liveData.appliedLessons ?? 0} applied`, 'learning');
    setDataPoint('lc-kpi-critical', liveData.failuresBySeverity?.critical ?? 0, 'learning');
    if (calibration) {
      setDataPoint('lc-kpi-ece', `ECE: ${calibration.ece?.toFixed(4) ?? '—'}`, 'learning');
    }
    if (featIntel && featIntel.features) {
      const healthy = featIntel.features.filter(f => f.decay_severity === 'none').length;
      setDataPoint('lc-kpi-features-healthy', `${healthy} / ${featIntel.features.length}`, 'learning');
    }
  } else {
    setDataPoint('lc-kpi-score', 'No data', 'learning');
    setDataPoint('lc-kpi-failures', '—', 'learning');
    setDataPoint('lc-kpi-lessons', '—', 'learning');
    scoreHistory = [];
  }

  // ── Intelligence Score Growth ─────────────────────────────
  const growthLabels = scoreHistory.map(r => r.date?.slice(5) || '');
  const growthVals   = scoreHistory.map(r => r.overall_score ?? r.score ?? 0);
  // Always render chart — with real data or a single seed point so canvas is never blank
  const _growthL = growthLabels.length ? growthLabels : ['Today'];
  const _growthV = growthVals.length   ? growthVals   : [liveData?.intelligenceScore ?? 0];
  ChartRegistry.create('knowledgeGrowthChart', {
    type: 'line',
    data: {
      labels: _growthL,
      datasets: [{
        label: 'Intelligence Score',
        data: _growthV,
        borderColor: '#ff8c00',
        borderWidth: 2,
        pointRadius: _growthL.length <= 3 ? 4 : 0,
        tension: 0.4,
        fill: true,
        backgroundColor: 'rgba(255,140,0,0.08)',
      }],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: { legend: { display: false }, tooltip: { callbacks: { label: ctx => ` Score: ${ctx.parsed.y.toFixed(1)}` } } },
      scales: {
        y: { min: 0, max: 100, ticks: { maxTicksLimit: 5, color: '#666' }, grid: { color: 'rgba(255,255,255,0.04)' } },
        x: { ticks: { maxTicksLimit: 8, color: '#666' }, grid: { color: 'rgba(255,255,255,0.04)' } },
      },
    },
  });

  // ── Score Components radar ────────────────────────────────
  const comp = liveData?.components || {};
  // Use latest scoreHistory row for components if liveData.components is missing
  const lastHist = scoreHistory.length ? scoreHistory[scoreHistory.length - 1] : null;
  ChartRegistry.create('scoreComponentsChart', {
    type: 'radar',
    data: {
      labels: ['Prediction', 'Portfolio', 'Risk', 'Learning', 'Calibration', 'Features'],
      datasets: [{
        label: 'Score',
        data: [
          comp.predictionQuality  ?? lastHist?.prediction_quality  ?? 50,
          comp.portfolioQuality   ?? lastHist?.portfolio_quality   ?? 50,
          comp.riskQuality        ?? lastHist?.risk_quality        ?? 50,
          comp.learningQuality    ?? lastHist?.learning_quality    ?? 50,
          comp.calibrationQuality ?? lastHist?.calibration_quality ?? 50,
          comp.featureQuality     ?? lastHist?.feature_quality     ?? 50,
        ],
        borderColor: '#ff8c00',
        backgroundColor: 'rgba(255,140,0,0.10)',
        pointBackgroundColor: '#ff8c00',
        borderWidth: 1.5,
      }],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: { legend: { display: false } },
      scales: { r: { min: 0, max: 100, ticks: { stepSize: 25, color: '#666' }, grid: { color: 'rgba(255,255,255,0.06)' }, pointLabels: { color: '#aaa', font: { size: 11 } } } },
    },
  });

  // ── Failure Category Chart ────────────────────────────────
  const byCat    = liveData?.failuresByCategory || {};
  const catKeys  = Object.keys(byCat).length ? Object.keys(byCat) : ['No failures'];
  const catVals  = Object.keys(byCat).length ? Object.values(byCat) : [0];
  ChartRegistry.create('failureCatChart', {
    type: 'bar',
    data: {
      labels: catKeys,
      datasets: [{
        label: 'Count',
        data: catVals,
        backgroundColor: catKeys[0] === 'No failures' ? 'rgba(34,197,94,0.3)' : 'rgba(239,68,68,0.6)',
        borderRadius: 4,
      }],
    },
    options: {
      indexAxis: 'y',
      responsive: true,
      maintainAspectRatio: false,
      plugins: { legend: { display: false } },
      scales: {
        x: { ticks: { maxTicksLimit: 5, color: '#666' }, grid: { color: 'rgba(255,255,255,0.04)' } },
        y: { ticks: { font: { size: 10 }, color: '#aaa' }, grid: { display: false } },
      },
    },
  });

  // ── Failure Timeline Chart ────────────────────────────────
  const timeline = (() => {
    const counts = {};
    (liveData?.recentEvents || []).forEach(e => {
      const d = (e.date || '').slice(5);
      if (d) counts[d] = (counts[d] || 0) + 1;
    });
    const labels = Object.keys(counts).sort();
    return { labels: labels.length ? labels : ['Today'], vals: labels.length ? labels.map(k => counts[k]) : [0] };
  })();

  ChartRegistry.create('failureTimelineChart', {
    type: 'bar',
    data: {
      labels: timeline.labels,
      datasets: [{
        label: 'Events',
        data: timeline.vals,
        backgroundColor: timeline.labels[0] === 'Today' ? 'rgba(107,114,128,0.3)' : 'rgba(245,158,11,0.6)',
        borderRadius: 3,
      }],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: { legend: { display: false } },
      scales: {
        x: { ticks: { maxTicksLimit: 10, color: '#666' }, grid: { color: 'rgba(255,255,255,0.04)' } },
        y: { ticks: { color: '#666', stepSize: 1 }, grid: { color: 'rgba(255,255,255,0.04)' } },
      },
    },
  });

  // ── Failures Table ────────────────────────────────────────
  const tbody = el('failure-table-body');
  if (tbody) {
    const rows = failures.length ? failures : [];
    const sevColor = { critical: '#ef4444', high: '#f59e0b', medium: '#60a5fa', low: '#6b7280' };
    if (!rows.length) { tbody.innerHTML = '<tr><td colspan="6" style="text-align:center;color:var(--text-muted);padding:20px">No failure records yet</td></tr>'; }
    else tbody.innerHTML = rows.map(f => `
      <tr>
        <td>${f.date || '—'}</td>
        <td><strong>${f.symbol || '—'}</strong></td>
        <td>${(f.category || '—').replace(/_/g, ' ')}</td>
        <td><span style="color:${sevColor[f.severity] || '#fff'}">${f.severity || '—'}</span></td>
        <td style="max-width:260px;white-space:normal;font-size:0.72rem">${(f.rootCause || '—').slice(0, 90)}</td>
        <td>${f.resolved ? '<span class="positive">✓</span>' : '<span class="negative">○</span>'}</td>
      </tr>`).join('');
  }

  // ── Calibration Curve ─────────────────────────────────────
  const calCanvas  = el('lcCalibrationChart');
  const calWrapper = calCanvas && calCanvas.parentElement;
  if (calibration && calibration.buckets && calibration.buckets.some(b => b.accuracy !== null)) {
    if (calCanvas) calCanvas.style.display = '';
    const bkts    = calibration.buckets.filter(b => b.accuracy !== null);
    const avgConfs = bkts.map(b => b.avg_confidence);
    const accs     = bkts.map(b => b.accuracy);
    ChartRegistry.create('lcCalibrationChart', {
      type: 'line',
      data: {
        labels: bkts.map(b => b.bucket),
        datasets: [
          {
            label: 'Stated Confidence',
            data: avgConfs,
            borderColor: '#60a5fa',
            borderWidth: 1.5,
            pointRadius: 4,
            tension: 0.3,
          },
          {
            label: 'Actual Accuracy',
            data: accs,
            borderColor: '#ff8c00',
            borderWidth: 1.5,
            pointRadius: 4,
            borderDash: [4, 3],
            tension: 0.3,
          },
          {
            label: 'Perfect Calibration',
            data: [55, 65, 75, 85, 95],
            borderColor: 'rgba(255,255,255,0.2)',
            borderWidth: 1,
            borderDash: [2, 4],
            pointRadius: 0,
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: { legend: { display: true, labels: { font: { size: 10 }, color: '#aaa' } } },
        scales: {
          y: { min: 0, max: 100, ticks: { callback: v => `${v}%`, color: '#666' }, grid: { color: 'rgba(255,255,255,0.04)' } },
          x: { ticks: { color: '#666' }, grid: { color: 'rgba(255,255,255,0.04)' } },
        },
      },
    });
  } else if (calCanvas) {
    // Show reference "perfect calibration" line even with no evaluated predictions
    if (calCanvas) calCanvas.style.display = '';
    const oldMsg = calWrapper && calWrapper.querySelector('#lc-cal-empty');
    if (oldMsg) oldMsg.remove();
    ChartRegistry.create('lcCalibrationChart', {
      type: 'line',
      data: {
        labels: ['50–60%', '60–70%', '70–80%', '80–90%', '90–100%'],
        datasets: [
          {
            label: 'Perfect Calibration',
            data: [55, 65, 75, 85, 95],
            borderColor: 'rgba(255,255,255,0.25)',
            borderWidth: 1.5,
            borderDash: [4, 4],
            pointRadius: 3,
            fill: false,
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: { legend: { display: true, labels: { font: { size: 10 }, color: '#aaa' } }, tooltip: { enabled: false } },
        scales: {
          y: { min: 40, max: 100, ticks: { callback: v => `${v}%`, color: '#666' }, grid: { color: 'rgba(255,255,255,0.04)' } },
          x: { ticks: { color: '#666' }, grid: { color: 'rgba(255,255,255,0.04)' } },
        },
      },
    });
  }

  // ── Model Drift Panel ─────────────────────────────────────
  const driftBody = el('drift-body');
  if (driftBody && drift) {
    const flagged = drift.flagged_count || 0;
    const models  = Object.entries(drift.by_model || {});
    driftBody.innerHTML = `
      <div style="margin-bottom:0.75rem">
        <span style="color:#ff8c00;font-weight:600">${flagged} model(s) flagged</span>
        <span style="color:rgba(255,255,255,0.4);font-size:0.75rem;margin-left:0.5rem">${drift.total_snapshots || 0} snapshots over ${drift.days}d</span>
      </div>` +
      models.slice(0, 6).map(([key, snaps]) => {
        const latest = snaps[0] || {};
        const dc     = latest.drift_flag ? '#ff3333' : '#00cc66';
        return `<div class="improvement-item">
          <div class="improvement-dot" style="background:${dc}"></div>
          <div>
            <div class="improvement-title">${key}</div>
            <div class="improvement-sub">
              Acc: ${latest.accuracy?.toFixed(1) ?? '—'}%
              IC: ${latest.ic?.toFixed(4) ?? '—'}
              Drift: ${latest.drift_pct?.toFixed(1) ?? '0'}%
              ${latest.drift_flag ? ' <span style="color:#ff3333">DRIFT FLAGGED</span>' : ''}
            </div>
          </div>
        </div>`;
      }).join('') || '<div class="improvement-sub">No drift data yet</div>';
  } else if (driftBody) {
    driftBody.innerHTML = '<div style="color:rgba(255,255,255,0.35);font-size:0.8rem">No drift data — backend offline or no evaluated predictions yet.</div>';
  }

  // ── Feature Intelligence Table ────────────────────────────
  const featureBody = el('feature-intel-body');
  if (featureBody) {
    const features = featIntel?.features || [];
    if (features.length) {
      const decColor = { none: '#00cc66', mild: '#ffcc00', moderate: '#ff8c00', severe: '#ff3333' };
      featureBody.innerHTML = features.slice(0, 10).map((f, i) => {
        const name  = f.featureName  || f.feature_name  || '?';
        const score = f.importanceScore != null ? f.importanceScore.toFixed(3)
                    : f.composite_score != null ? f.composite_score.toFixed(1) : '?';
        const ic    = f.ic_30d != null ? f.ic_30d.toFixed(4) : '?';
        const decay = f.decaySeverity || f.decay_severity || 'none';
        const rec   = (f.recommendation || '?').split(':')[0];
        return `<tr>
          <td style="color:var(--text-muted)">${i + 1}</td>
          <td><strong>${name}</strong></td>
          <td>${score}</td>
          <td>${ic}</td>
          <td><span style="color:${decColor[decay] || '#fff'}">${decay}</span></td>
          <td style="font-size:0.7rem;color:rgba(255,255,255,0.55)">${rec}</td>
        </tr>`;
      }).join('');
    } else {
      featureBody.innerHTML = '<tr><td colspan="6" style="color:rgba(255,255,255,0.3)">No feature data yet</td></tr>';
    }
  }

  // ── Lessons Panel ─────────────────────────────────────────
  const lessonsBody = el('lessons-body');
  if (lessonsBody) {
    if (lessons.length) {
      const sevColor = { critical: '#ef4444', warning: '#f59e0b', info: '#60a5fa' };
      lessonsBody.innerHTML = lessons.slice(0, 8).map(l => `
        <div class="improvement-item">
          <div class="improvement-dot" style="background:${sevColor[l.severity] || '#fff'}"></div>
          <div>
            <div class="improvement-title">${l.title || '—'}</div>
            <div class="improvement-sub">${l.recommendation?.slice(0, 120) || l.description?.slice(0, 120) || '—'}</div>
          </div>
        </div>`).join('');
    } else {
      lessonsBody.innerHTML = '<div style="color:rgba(255,255,255,0.35);font-size:0.8rem">No lessons generated yet — run the learning loop.</div>';
    }
  }

  // ── Recent Events Feed ────────────────────────────────────
  const eventsBody = el('lc-events-body');
  if (eventsBody) {
    const allEvents = liveData?.recentEvents || [];
    if (allEvents.length) {
      const catColor = { strategy: 'var(--accent)', model: '#60a5fa', portfolio: 'var(--positive)', risk: 'var(--negative)', prediction: '#a78bfa' };
      eventsBody.innerHTML = allEvents.slice(0, 40).map(e => {
        const cc = catColor[e.category] || 'var(--text-muted)';
        const desc = (e.description || e.type || '—').replace(/â/g, '—').slice(0, 120);
        return `<tr>
          <td style="color:var(--text-muted);font-size:0.68rem;white-space:nowrap">${e.date || '—'}</td>
          <td><span style="color:${cc};font-size:0.68rem;font-weight:600">${e.category || '—'}</span></td>
          <td style="font-size:0.7rem;color:var(--text-secondary);max-width:400px">${desc}</td>
        </tr>`;
      }).join('');
    } else {
      eventsBody.innerHTML = '<tr><td colspan="3" style="color:var(--text-muted);text-align:center;padding:12px">No events recorded yet. Run pipelines to generate activity.</td></tr>';
    }
  }
}

// -- RISK CENTER (delegates to hydrateRisk)
// ── Learning Centre — live hydration ─────────────────────────
async function hydrateLearnCenter() {
  // renderLearning() is already fully live — re-run it to refresh all data + charts
  await renderLearning();
}
