// ui/pages/intelligence-lab.js - split from app.js (ARCH-5), see CHANGELOG
// ═══════════════════════════════════════════════════════════════
// PHASE 8.5: HISTORICAL INTELLIGENCE LAB
// ═══════════════════════════════════════════════════════════════

async function hydrateIntelligenceLab() {
  // Load all sub-sections in parallel
  await Promise.allSettled([
    loadRegimeDatasets(),
    loadMetaLearningInsights(),
    loadFeatureProposals(),
    loadModelMemory(),
    loadStrategyMemory(),
    loadResearchMemory(),
    loadFailurePatterns(),
    loadPredictionPatterns(),
  ]);
}

async function loadRegimeDatasets() {
  const tbody = document.getElementById('il-regime-body');
  try {
    const data = await apiFetch('/regime-datasets');
    document.getElementById('il-kpi-regimes').textContent = data.length;
    if (!data.length) { tbody.innerHTML = '<tr><td colspan="5" style="color:var(--text-muted);text-align:center">No regime datasets yet</td></tr>'; return; }
    tbody.innerHTML = data.map(d => `
      <tr>
        <td><span style="color:var(--accent)">${d.regime_label}</span></td>
        <td>${(d.sample_count || 0).toLocaleString()}</td>
        <td>${(d.metadata && d.metadata.total_dates) || '—'}</td>
        <td style="color:var(--text-muted)">${d.date_range_start || '—'}</td>
        <td style="color:var(--text-muted)">${d.date_range_end || '—'}</td>
      </tr>
    `).join('');
  } catch (e) {
    tbody.innerHTML = '<tr><td colspan="5" style="color:var(--text-muted);text-align:center">No data (run pipeline first)</td></tr>';
  }
}

async function loadMetaLearningInsights() {
  const tbody = document.getElementById('il-meta-body');
  try {
    const data = await apiFetch('/meta-learning', { limit: 20 });
    const hi = data.filter(d => d.severity === 'high' || d.severity === 'critical').length;
    document.getElementById('il-kpi-insights').textContent = data.length;
    document.getElementById('il-kpi-insights-sub').textContent = `High Severity: ${hi}`;
    if (!data.length) { tbody.innerHTML = '<tr><td colspan="6" style="color:var(--text-muted);text-align:center">No insights yet — run meta learning</td></tr>'; return; }
    const sevColor = { low: 'var(--text-muted)', medium: 'var(--accent)', high: '#f59e0b', critical: 'var(--negative)' };
    tbody.innerHTML = data.map(d => `
      <tr>
        <td style="color:var(--accent)">${d.insight_type || '—'}</td>
        <td>${d.title || '—'}</td>
        <td style="color:var(--text-muted);font-size:0.72rem">${(d.condition_text || '—').substring(0, 50)}</td>
        <td>${d.failure_rate != null ? (d.failure_rate * 100).toFixed(1) + '%' : '—'}</td>
        <td>${d.sample_count || '—'}</td>
        <td><span style="color:${sevColor[d.severity] || 'inherit'}">${(d.severity || '—').toUpperCase()}</span></td>
      </tr>
    `).join('');
  } catch (e) {
    tbody.innerHTML = '<tr><td colspan="6" style="color:var(--text-muted);text-align:center">No data</td></tr>';
  }
}

async function runMetaLearning() {
  document.getElementById('il-meta-body').innerHTML = '<tr><td colspan="6" style="color:var(--accent);text-align:center">Running meta-learning analysis…</td></tr>';
  try {
    await apiPost('/meta-learning/run');
    _liveHydrated.delete('intelligence-lab');
    await loadMetaLearningInsights();
  } catch (e) {
    document.getElementById('il-meta-body').innerHTML = '<tr><td colspan="6" style="color:var(--negative);text-align:center">Error running analysis</td></tr>';
  }
}

async function loadFeatureProposals() {
  const tbody = document.getElementById('il-proposals-body');
  try {
    const data = await apiFetch('/feature-proposals');
    const pending = data.filter(d => d.status === 'proposed').length;
    document.getElementById('il-kpi-proposals').textContent = data.length;
    document.getElementById('il-kpi-proposals-sub').textContent = `Pending Approval: ${pending}`;
    if (!data.length) { tbody.innerHTML = '<tr><td colspan="5" style="color:var(--text-muted);text-align:center">No proposals yet</td></tr>'; return; }
    const statusColor = { proposed: 'var(--accent)', approved: 'var(--positive)', rejected: 'var(--negative)', deployed: '#8b5cf6' };
    tbody.innerHTML = data.map(d => `
      <tr>
        <td><span style="color:var(--text-primary);font-weight:500">${d.feature_name}</span></td>
        <td style="color:var(--text-muted)">${d.category || '—'}</td>
        <td style="font-size:0.72rem;color:var(--text-secondary)">${(d.expected_impact || '—').substring(0, 60)}</td>
        <td><span style="color:${statusColor[d.status] || 'inherit'}">${(d.status || '—').toUpperCase()}</span></td>
        <td>
          ${d.status === 'proposed' ? `<button class="btn-sm" onclick="approveProposal('${d.proposal_id}')">✓ Approve</button>` : '—'}
        </td>
      </tr>
    `).join('');
  } catch (e) {
    tbody.innerHTML = '<tr><td colspan="5" style="color:var(--text-muted);text-align:center">No data</td></tr>';
  }
}

async function approveProposal(pid) {
  const btn = document.querySelector(`button[onclick="approveProposal('${pid}')"]`);
  if (btn) { btn.disabled = true; btn.textContent = '⟳'; }
  try {
    const res = await apiPost(`/feature-proposals/${pid}/approve`);
    if (!res) throw new Error('No response — backend may be offline');
    _liveHydrated.delete('intelligence-lab');
    await loadFeatureProposals();
  } catch (e) {
    if (btn) { btn.disabled = false; btn.textContent = '✓ Approve'; }
    alert('Failed to approve: ' + e.message);
  }
}

async function runFeatureDiscovery() {
  document.getElementById('il-proposals-body').innerHTML = '<tr><td colspan="5" style="color:var(--accent);text-align:center">Discovering features…</td></tr>';
  try {
    await apiPost('/feature-proposals/discover');
    _liveHydrated.delete('intelligence-lab');
    await loadFeatureProposals();
  } catch (e) {
    document.getElementById('il-proposals-body').innerHTML = '<tr><td colspan="5" style="color:var(--negative);text-align:center">Error</td></tr>';
  }
}

async function loadModelMemory() {
  const tbody = document.getElementById('il-model-memory-body');
  try {
    const data = await apiFetch('/model-memory');
    document.getElementById('il-kpi-models').textContent = data.length;
    const recColor = { trust: 'var(--positive)', caution: '#f59e0b', retrain: 'var(--accent)', retire: 'var(--negative)' };
    if (!data.length) { tbody.innerHTML = '<tr><td colspan="6" style="color:var(--text-muted);text-align:center">No model memory yet</td></tr>'; return; }
    tbody.innerHTML = data.map(d => `
      <tr>
        <td style="color:var(--text-primary)">${d.model_name}</td>
        <td style="color:var(--text-muted)">${d.task}</td>
        <td>${d.overall_reliability != null ? d.overall_reliability.toFixed(1) + '/100' : '—'}</td>
        <td>${d.drift_score != null ? d.drift_score.toFixed(1) : '—'}</td>
        <td>${d.success_count != null && d.failure_count != null ? ((d.success_count / Math.max(1, d.success_count + d.failure_count)) * 100).toFixed(1) + '%' : '—'}</td>
        <td><span style="color:${recColor[d.recommendation] || 'inherit'}">${(d.recommendation || '—').toUpperCase()}</span></td>
      </tr>
    `).join('');
  } catch (e) {
    tbody.innerHTML = '<tr><td colspan="6" style="color:var(--text-muted);text-align:center">No data</td></tr>';
  }
}

async function loadStrategyMemory() {
  const tbody = document.getElementById('il-strategy-memory-body');
  try {
    const data = await apiFetch('/strategy-memory');
    const decayed = data.filter(d => d.decay_detected).length;
    document.getElementById('il-kpi-strategies').textContent = data.length;
    document.getElementById('il-kpi-strategies-sub').textContent = `Decayed: ${decayed}`;
    if (!data.length) { tbody.innerHTML = '<tr><td colspan="9" style="color:var(--text-muted);text-align:center">No strategy memory yet</td></tr>'; return; }
    const statusColor = { active: 'var(--positive)', retired: 'var(--negative)', shadow: 'var(--accent)', candidate: 'var(--text-muted)' };
    tbody.innerHTML = data.slice(0, 30).map(d => `
      <tr>
        <td style="font-size:0.72rem;color:var(--text-muted)">${(d.strategy_id || '').substring(0, 20)}</td>
        <td>${d.family || '—'}</td>
        <td><span style="color:${statusColor[d.status] || 'inherit'}">${d.status || '—'}</span></td>
        <td>${d.survival_days || 0}</td>
        <td>${d.final_fitness != null ? d.final_fitness.toFixed(2) : '—'}</td>
        <td>${d.peak_fitness != null ? d.peak_fitness.toFixed(2) : '—'}</td>
        <td>${d.decay_detected ? '<span style="color:var(--negative)">YES</span>' : '<span style="color:var(--positive)">NO</span>'}</td>
        <td style="color:var(--accent)">${(d.best_regimes && d.best_regimes[0]) || '—'}</td>
        <td style="color:var(--text-muted);font-size:0.72rem">${d.failure_reason || '—'}</td>
      </tr>
    `).join('');
  } catch (e) {
    tbody.innerHTML = '<tr><td colspan="9" style="color:var(--text-muted);text-align:center">No data</td></tr>';
  }
}

async function loadResearchMemory() {
  const body = document.getElementById('il-research-memory-body');
  try {
    const data = await apiFetch('/research-memory/latest');
    document.getElementById('il-kpi-research').textContent = data.total_records != null ? data.total_records.toLocaleString() : '—';
    if (data.status === 'no_data') { body.innerHTML = '<div style="color:var(--text-muted);font-size:0.8rem">No research memory yet</div>'; return; }
    const themes = (data.themes && data.themes.slice ? data.themes : []).slice(0, 8);
    body.innerHTML = `
      <div style="margin-bottom:10px">
        <div style="color:var(--text-muted);font-size:0.72rem;text-transform:uppercase;letter-spacing:0.08em;margin-bottom:6px">Recurring Themes</div>
        ${themes.map(t => `
          <div style="display:flex;justify-content:space-between;padding:3px 0;border-bottom:1px solid var(--border)">
            <span style="color:var(--text-secondary);font-size:0.76rem">${t.theme}</span>
            <span style="color:var(--accent);font-size:0.76rem">${t.frequency}×</span>
          </div>
        `).join('')}
      </div>
      <div style="color:var(--text-muted);font-size:0.72rem;margin-top:8px">Updated: ${data.memory_date || '—'}</div>
    `;
  } catch (e) {
    body.innerHTML = '<div style="color:var(--text-muted);font-size:0.8rem">No data</div>';
  }
}

async function loadFailurePatterns() {
  const tbody = document.getElementById('il-failure-patterns-body');
  try {
    const data = await apiFetch('/failure-patterns');
    if (!data.length) { tbody.innerHTML = '<tr><td colspan="6" style="color:var(--text-muted);text-align:center">No patterns yet</td></tr>'; return; }
    tbody.innerHTML = data.slice(0, 15).map(d => `
      <tr>
        <td style="color:var(--accent)">${d.pattern_type || '—'}</td>
        <td style="font-size:0.72rem;color:var(--text-secondary)">${(d.description || '—').substring(0, 60)}</td>
        <td>${d.occurrence_count || 0}</td>
        <td>${d.failure_rate != null ? (d.failure_rate * 100).toFixed(1) + '%' : '—'}</td>
        <td style="color:var(--text-muted)">${d.last_seen || '—'}</td>
        <td>${d.resolved ? '<span style="color:var(--positive)">YES</span>' : '<span style="color:var(--negative)">NO</span>'}</td>
      </tr>
    `).join('');
  } catch (e) {
    tbody.innerHTML = '<tr><td colspan="6" style="color:var(--text-muted);text-align:center">No data</td></tr>';
  }
}

async function loadPredictionPatterns() {
  const tbody = document.getElementById('il-pred-patterns-body');
  try {
    const data = await apiFetch('/prediction-patterns');
    if (!data.length) { tbody.innerHTML = '<tr><td colspan="4" style="color:var(--text-muted);text-align:center">No patterns yet</td></tr>'; return; }
    tbody.innerHTML = data.slice(0, 10).map(d => `
      <tr>
        <td style="color:var(--positive)">${d.pattern_type || '—'}</td>
        <td style="font-size:0.72rem;color:var(--text-secondary)">${(d.condition || '—').substring(0, 60)}</td>
        <td>${d.occurrence_count || 0}</td>
        <td style="color:var(--positive)">${d.success_rate != null ? (d.success_rate * 100).toFixed(1) + '%' : '—'}</td>
      </tr>
    `).join('');
  } catch (e) {
    tbody.innerHTML = '<tr><td colspan="4" style="color:var(--text-muted);text-align:center">No data</td></tr>';
  }
}

async function triggerReplay() {
  const scope = document.getElementById('il-replay-scope').value;
  const dateVal = document.getElementById('il-replay-date').value;
  const result = document.getElementById('il-replay-result');
  result.textContent = 'Running replay…';
  result.style.color = 'var(--accent)';
  try {
    const body = { scope };
    if (scope === 'day') body.target_date = dateVal;
    else if (scope === 'week') body.week_start = dateVal;
    else if (scope === 'month') { body.year = new Date(dateVal).getFullYear(); body.month = new Date(dateVal).getMonth() + 1; }
    else if (scope === 'regime') body.regime_name = 'BULL';
    else if (scope === 'event') body.event_date = dateVal;
    const res = await apiPost('/replay', body);
    result.style.color = 'var(--positive)';
    result.textContent = `✓ Replay complete: ${JSON.stringify(res).substring(0, 200)}`;
    await loadReplayHistory();
  } catch (e) {
    result.style.color = 'var(--negative)';
    result.textContent = 'Replay failed: ' + e.message;
  }
}

async function loadReplayHistory() {
  const el = document.getElementById('il-replay-history');
  try {
    const data = await apiFetch('/replay/history');
    if (!data.length) { el.textContent = 'No replay history yet'; return; }
    el.innerHTML = data.slice(0, 5).map(d =>
      `<div style="padding:2px 0">${d.replay_type} — ${d.scope_label} — ${(d.created_at || '').substring(0, 16)}</div>`
    ).join('');
  } catch (e) {
    el.textContent = 'No history available';
  }
}

async function runIntelligencePipeline(btn) {
  const status = document.getElementById('il-pipeline-status');
  const result = document.getElementById('il-pipeline-result');
  if (btn) { btn.disabled = true; btn.textContent = '⟳ Running…'; }
  if (status) { status.textContent = '⟳ Running pipeline…'; status.style.color = 'var(--accent)'; }
  if (result) result.textContent = '';
  try {
    // Intelligence pipeline can take several minutes — bypass the 10s global timeout.
    const _ctrl = new AbortController();
    const _timer = setTimeout(() => _ctrl.abort(), 300000); // 5 min
    let res;
    try {
      const _r = await fetch('http://localhost:8000/admin/intelligence', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({}), signal: _ctrl.signal,
      });
      clearTimeout(_timer);
      if (!_r.ok) throw new Error(`HTTP ${_r.status}`);
      res = await _r.json();
    } catch (fetchErr) {
      clearTimeout(_timer);
      if (fetchErr.name === 'AbortError') throw new Error('Pipeline timed out after 5 minutes');
      throw fetchErr;
    }
    if (!res) throw new Error('No response from server — is the backend running?');
    const errors = res.errors || 0;
    const stepColor = s => {
      if (!s || s === 'error') return 'var(--negative)';
      if (s === 'no_data') return 'var(--text-muted)';
      return 'var(--positive)';
    };
    if (status) {
      status.style.color = errors > 0 ? 'var(--warning)' : 'var(--positive)';
      status.textContent = errors > 0 ? `⚠ ${res.status}` : `✓ ${res.status}`;
    }
    const steps = res.steps || {};
    if (result) {
      result.innerHTML = Object.entries(steps).map(([k, v]) =>
        `<div style="display:flex;justify-content:space-between;padding:2px 0">
           <span style="color:var(--text-secondary)">${k.replace(/_/g,' ')}</span>
           <span style="color:${stepColor(v.status)}">${v.status || '—'}</span>
         </div>`
      ).join('');
    }
    _liveHydrated.delete('intelligence-lab');
    setTimeout(() => hydrateIntelligenceLab(), 500);
  } catch (e) {
    if (status) { status.style.color = 'var(--negative)'; status.textContent = 'Pipeline failed'; }
    if (result) result.textContent = e.message;
  } finally {
    if (btn) { btn.disabled = false; btn.textContent = '▶ Run Full Pipeline'; }
  }
}

