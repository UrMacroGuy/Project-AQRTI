// ui/pages/model.js - split from app.js (ARCH-5), see CHANGELOG
// ═══════════════════════════════════════════════════════════════
// MODEL CENTER
// ═══════════════════════════════════════════════════════════════

async function hydrateModelCenter() {
  const s  = (id, v) => { const e = document.getElementById(id); if (e) e.textContent = v; };
  const sc = (id, cls) => {
    const e = document.getElementById(id);
    if (e) e.className = e.className.replace(/\bpositive\b|\bnegative\b|\baccent\b/g, '').trim() + ' ' + cls;
  };

  // Show loading state
  s('model-ensemble-acc', 'Loading…');
  s('model-best-name', '…');
  const tbody0 = document.getElementById('model-registry-body');
  if (tbody0) tbody0.innerHTML = '<tr><td colspan="9" style="color:var(--text-muted);text-align:center;padding:16px">Loading model registry…</td></tr>';

  try {
    const [stats, models, metrics, folds] = await Promise.all([
      Api.modelStats().catch(() => null),
      Api.models().catch(() => []),
      Api.modelMetrics().catch(() => []),
      Api.walkForwardFolds().catch(() => []),
    ]);

    // ── KPI Row ──────────────────────────────────────────────
    const metricsArr0 = Array.isArray(metrics) ? metrics : [];
    const eceRow0     = metricsArr0.find(m => m.metricName === 'ece');
    const eceVal0     = eceRow0 ? eceRow0.metricValue : (stats?.avgECE ?? null);
    s('model-calibration-ece', eceVal0 != null ? eceVal0.toFixed(4) : '—');

    if (!stats || !stats.available) {
      s('model-ensemble-acc', 'No data');
      s('model-best-name', '—');
      s('model-best-acc', 'No model metrics in database');
      s('model-active-count', '0');
      s('model-last-retrain', 'Never');
      s('model-last-retrain-sub', 'Run the training pipeline first');
      s('model-features-count', '—');
      sc('model-ensemble-acc', 'negative');
    } else {
      const primary = stats.bestAUC ?? stats.bestAccuracy;
      if (primary != null) {
        s('model-ensemble-acc', `${(primary * 100).toFixed(1)}%`);
        s('model-ensemble-acc-sub', primary >= 0.90 ? 'Excellent (check overfit)' : primary >= 0.65 ? 'Good' : primary >= 0.55 ? 'Acceptable' : 'Poor');
        sc('model-ensemble-acc', primary >= 0.65 ? 'positive' : primary >= 0.55 ? 'accent' : 'negative');
      }
      const modelArr0 = Array.isArray(models) ? models : [];
      const bestDir = modelArr0.find(m => m.task === 'direction') || modelArr0[0];
      if (bestDir) {
        s('model-best-name', bestDir.modelName);
        s('model-best-acc', bestDir.primaryMetric != null ? `${(bestDir.primaryMetric * 100).toFixed(1)}% AUC` : 'See metrics below');
      } else if ((stats.modelTypes || []).length) {
        s('model-best-name', stats.modelTypes[0]);
        s('model-best-acc', primary != null ? `${(primary * 100).toFixed(1)}% best metric` : 'Metrics in table below');
      }
      s('model-active-count', stats.activeModels || (stats.modelTypes || []).length || '0');
      s('model-active-sub', (stats.modelTypes || []).join(' · ') || 'Ensemble Active');
      if (stats.lastTrainedAt) {
        const d = new Date(stats.lastTrainedAt);
        const daysAgo = Math.floor((Date.now() - d.getTime()) / 86400000);
        s('model-last-retrain', daysAgo === 0 ? 'Today' : `${daysAgo}d ago`);
        s('model-last-retrain-sub', d.toLocaleDateString('en-IN', { day: '2-digit', month: 'short', year: 'numeric' }));
        sc('model-last-retrain', daysAgo > 30 ? 'negative' : daysAgo > 14 ? 'accent' : 'positive');
      } else {
        s('model-last-retrain', 'Never'); sc('model-last-retrain', 'negative');
      }
      const featCount = Object.keys(bestDir?.featureImportance || {}).length;
      s('model-features-count', featCount || (metricsArr0.length ? `${metricsArr0.length} metrics` : '—'));
      s('model-features-sub', featCount ? `${featCount} features in active model` : (stats.totalFolds ? `${stats.totalFolds} walk-forward folds` : 'Out of 300+ Target'));
    }

    // ── Accuracy chart ────────────────────────────────────────
    const accCanvas = document.getElementById('modelAccChart');
    if (accCanvas) {
      const foldsArr   = Array.isArray(folds)   ? folds   : [];
      const metricsArr = Array.isArray(metrics)  ? metrics : [];
      const modelArr   = Array.isArray(models)   ? models  : [];

      if (foldsArr.length > 0 && metricsArr.length > 0) {
        const foldNums   = [...new Set(foldsArr.map(f => f.fold))].sort((a, b) => a - b);
        const modelNames = [...new Set(foldsArr.map(f => f.modelName))];
        const byMF = {};
        metricsArr.filter(m => m.metricName === 'accuracy' || m.metricName === 'auc_roc').forEach(m => {
          if (!byMF[m.modelName]) byMF[m.modelName] = {};
          byMF[m.modelName][m.fold] = m.metricValue;
        });
        const pal = ['rgba(255,140,0,0.9)','rgba(34,197,94,0.8)','rgba(59,130,246,0.8)','rgba(245,158,11,0.8)'];
        ChartRegistry.create('modelAccChart', {
          type: 'line',
          data: {
            labels: foldNums.map(f => `Fold ${f}`),
            datasets: modelNames.slice(0, 4).map((name, i) => ({
              label: name,
              data: foldNums.map(f => byMF[name]?.[f] != null ? +(byMF[name][f] * 100).toFixed(2) : null),
              borderColor: pal[i % pal.length],
              backgroundColor: pal[i % pal.length].replace(/[\d.]+\)$/, '0.08)'),
              borderWidth: 2, fill: false, tension: 0.3, spanGaps: true,
            })),
          },
          options: {
            responsive: true, maintainAspectRatio: false,
            plugins: { legend: { labels: { color: '#a0a0a0', font: { size: 11 } } } },
            scales: {
              x: { ticks: { color: '#777', font: { size: 10 } }, grid: { color: 'rgba(255,255,255,0.04)' } },
              y: { ticks: { color: '#777', callback: v => v + '%' }, grid: { color: 'rgba(255,255,255,0.04)' }, min: 40, max: 85 },
            },
          },
        });
      } else {
        const toShow = modelArr.filter(m => m.primaryMetric != null);
        if (toShow.length) {
          ChartRegistry.create('modelAccChart', {
            type: 'bar',
            data: {
              labels: toShow.map(m => `${m.modelName} / ${m.task}`),
              datasets: [{ label: 'Primary Metric', data: toShow.map(m => +(m.primaryMetric * 100).toFixed(2)), backgroundColor: toShow.map(m => m.primaryMetric >= 0.60 ? 'rgba(34,197,94,0.6)' : m.primaryMetric >= 0.55 ? 'rgba(255,140,0,0.6)' : 'rgba(239,68,68,0.6)'), borderRadius: 4 }],
            },
            options: {
              responsive: true, maintainAspectRatio: false,
              plugins: { legend: { display: false }, tooltip: { callbacks: { label: ctx => ` ${ctx.parsed.y.toFixed(1)}%` } } },
              scales: {
                x: { ticks: { color: '#777', font: { size: 10 } }, grid: { color: 'rgba(255,255,255,0.04)' } },
                y: { ticks: { color: '#777', callback: v => v + '%' }, grid: { color: 'rgba(255,255,255,0.04)' }, min: 40, max: 100 },
              },
            },
          });
        } else {
          _modelNoData(accCanvas, '⬡ No trained models yet<br><span style="font-size:11px;opacity:0.6">Use <code>POST /api/v1/admin/train</code> to run the training pipeline</span>');
        }
      }
    }

    // ── Calibration chart ─────────────────────────────────────
    const calCanvas = document.getElementById('calibrationChart');
    if (calCanvas) {
      try {
        const preds    = await Api.predictions({ limit: 500 }).catch(() => null);
        const evaluated = (Array.isArray(preds) ? preds : []).filter(p => p.success != null);
        if (evaluated.length >= 10) {
          const buckets = [{lo:50,hi:60,label:'50–60%'},{lo:60,hi:70,label:'60–70%'},{lo:70,hi:80,label:'70–80%'},{lo:80,hi:90,label:'80–90%'},{lo:90,hi:101,label:'90–100%'}];
          const filled = buckets.map(b => {
            const inB = evaluated.filter(p => (p.confidence||0) >= b.lo && (p.confidence||0) < b.hi);
            if (inB.length < 2) return null;
            return { label: `${b.label} (n=${inB.length})`, actual: +(inB.filter(p=>p.success).length/inB.length*100).toFixed(1), stated: (b.lo+b.hi)/2 };
          }).filter(Boolean);
          if (filled.length >= 2) {
            ChartRegistry.create('calibrationChart', {
              type: 'line',
              data: {
                labels: filled.map(b => b.label),
                datasets: [
                  { label: 'Actual Accuracy', data: filled.map(b => b.actual), borderColor: 'rgba(255,140,0,0.9)', backgroundColor: 'rgba(255,140,0,0.1)', borderWidth: 2, fill: true, tension: 0.3 },
                  { label: 'Perfect Calibration', data: filled.map(b => b.stated), borderColor: 'rgba(255,255,255,0.2)', borderWidth: 1, borderDash: [5,5], pointRadius: 0, fill: false },
                ],
              },
              options: {
                responsive: true, maintainAspectRatio: false,
                plugins: { legend: { labels: { color: '#a0a0a0', font: { size: 11 } } } },
                scales: {
                  x: { ticks: { color: '#777', font: { size: 10 } }, grid: { color: 'rgba(255,255,255,0.04)' } },
                  y: { ticks: { color: '#777', callback: v => v + '%' }, grid: { color: 'rgba(255,255,255,0.04)' }, min: 30, max: 100 },
                },
              },
            });
          } else {
            _modelNoData(calCanvas, `Only ${filled.length} confidence bucket(s) had enough data`);
          }
        } else {
          _modelNoData(calCanvas, `${evaluated.length} evaluated predictions — need 10+ for calibration curve`);
        }
      } catch (_) {
        _modelNoData(calCanvas, 'Calibration data unavailable');
      }
    }

    // ── Registry Table ────────────────────────────────────────
    const tbody = document.getElementById('model-registry-body');
    if (tbody) {
      const modelArr   = Array.isArray(models)  ? models  : [];
      const metricsArr = Array.isArray(metrics) ? metrics : [];

      if (modelArr.length) {
        // Full model list from backend
        const activeCount = modelArr.filter(m => m.isActive).length || 1;
        tbody.innerHTML = modelArr.map(m => {
          const acc      = m.primaryMetric != null ? `${(m.primaryMetric*100).toFixed(1)}%` : '—';
          const accColor = m.primaryMetric >= 0.60 ? 'var(--positive)' : m.primaryMetric >= 0.55 ? 'var(--accent)' : m.primaryMetric ? 'var(--negative)' : 'var(--muted)';
          const trained  = m.trainedAt ? new Date(m.trainedAt).toLocaleDateString('en-IN',{day:'2-digit',month:'short',year:'numeric'}) : '—';
          const featCount = Object.keys(m.featureImportance||{}).length;
          const topFeat   = Object.entries(m.featureImportance||{}).sort((a,b)=>b[1]-a[1]).slice(0,2).map(([f])=>f).join(', ')||'—';
          const eceRow   = metricsArr.find(mm => mm.metricName === 'ece' && mm.modelName === m.modelName);
          const ece      = eceRow ? eceRow.metricValue.toFixed(3) : (m.metrics?.ece != null ? m.metrics.ece.toFixed(3) : '—');
          return `<tr>
            <td style="font-family:monospace;font-size:11px;color:var(--muted)">v${m.version||1}</td>
            <td><span style="color:var(--accent);font-weight:600">${m.modelName||'—'}</span></td>
            <td style="color:var(--muted)">${m.task||'—'}</td>
            <td style="color:${accColor};font-weight:600">${acc}</td>
            <td style="color:var(--muted)">${ece}</td>
            <td style="color:var(--muted);font-size:11px">${m.isActive ? '1/'+activeCount : '—'}</td>
            <td><span style="color:${m.isActive?'var(--positive)':'var(--muted)'};font-size:12px">${m.isActive?'● Active':'○ Inactive'}</span></td>
            <td style="font-size:11px;color:var(--muted)">${trained}</td>
            <td style="font-size:11px;color:var(--muted)" title="${topFeat}">${featCount||'—'}</td>
          </tr>`;
        }).join('');
      } else if (metricsArr.length) {
        // Synthesise rows from raw model_metrics when no model_versions rows exist
        const byModel = {};
        metricsArr.forEach(m => {
          const key = `${m.modelName}::${m.task}`;
          if (!byModel[key]) byModel[key] = { modelName: m.modelName, task: m.task, version: m.version, trainedAt: m.computedAt, metrics: {} };
          byModel[key].metrics[m.metricName] = m.metricValue;
        });
        tbody.innerHTML = Object.values(byModel).map(m => {
          const acc = m.metrics.accuracy != null ? `${(m.metrics.accuracy*100).toFixed(1)}%` : '—';
          const auc = m.metrics.auc_roc   != null ? `${(m.metrics.auc_roc  *100).toFixed(1)}%` : '—';
          const ece = m.metrics.ece       != null ? m.metrics.ece.toFixed(3) : '—';
          const primary = m.metrics.auc_roc ?? m.metrics.accuracy;
          const accColor = primary >= 0.65 ? 'var(--positive)' : primary >= 0.55 ? 'var(--accent)' : primary ? 'var(--negative)' : 'var(--muted)';
          const trained = m.trainedAt ? new Date(m.trainedAt).toLocaleDateString('en-IN',{day:'2-digit',month:'short',year:'numeric'}) : '—';
          return `<tr>
            <td style="font-family:monospace;font-size:11px;color:var(--muted)">v${m.version||1}</td>
            <td><span style="color:var(--accent);font-weight:600">${m.modelName}</span></td>
            <td style="color:var(--muted)">${m.task}</td>
            <td style="color:${accColor};font-weight:600">${auc !== '—' ? auc + ' AUC' : acc}</td>
            <td style="color:var(--muted)">${ece}</td>
            <td style="color:var(--muted);font-size:11px">—</td>
            <td><span style="color:var(--positive);font-size:12px">● Active</span></td>
            <td style="font-size:11px;color:var(--muted)">${trained}</td>
            <td style="font-size:11px;color:var(--muted)">${Object.keys(m.metrics).length} metrics</td>
          </tr>`;
        }).join('');
      } else {
        tbody.innerHTML = `<tr><td colspan="9" style="text-align:center;color:var(--muted);padding:24px">No model data yet — run the training pipeline.</td></tr>`;
      }
    }

  } catch (e) {
    console.error('hydrateModelCenter:', e);
    const tbody = document.getElementById('model-registry-body');
    if (tbody) tbody.innerHTML = `<tr><td colspan="9" style="color:var(--negative);padding:16px">Error loading model data: ${e.message}</td></tr>`;
  }
}

function _modelNoData(canvas, msg) {
  const parent = canvas.parentElement;
  if (parent) parent.innerHTML = `<div style="display:flex;align-items:center;justify-content:center;height:180px;color:var(--muted);font-size:12px;text-align:center;padding:16px">${msg}</div>`;
}

