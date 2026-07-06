// ui/pages/vault.js - split from app.js (ARCH-5), see CHANGELOG
// ═══════════════════════════════════════════════════════════════
// HISTORICAL INTELLIGENCE VAULT — Phase 7.5
// ═══════════════════════════════════════════════════════════════

async function hydrateVault() {
  let summary    = await Api.vaultSummary();
  let snapData   = await Api.vaultSnapshots(14);
  let knowData   = await Api.archiveKnowledge(14);
  let portData   = await Api.archivePortfolio(14);
  let resData    = await Api.archiveResearch(30);
  let backupData = await Api.listBackups();
  let briefData  = await Api.vaultBriefs();

  if (!summary) {
    summary    = {};
    snapData   = { snapshots: [] };
    knowData   = { records: [] };
    portData   = { records: [] };
    resData    = { records: [] };
    backupData = { backups: [] };
    briefData  = { briefs: [] };
  }

  setDataPoint('vault-kpi-snapshots',   summary.market_snapshots ?? '—', 'vault');
  setDataPoint('vault-kpi-oldest',      `oldest: ${summary.oldest_snapshot ?? '—'}`, 'vault');
  setDataPoint('vault-kpi-predictions', summary.prediction_records ?? '—', 'vault');
  setDataPoint('vault-kpi-strategies',  summary.strategy_records ?? '—', 'vault');
  setDataPoint('vault-kpi-research',    summary.research_records ?? '—', 'vault');
  setDataPoint('vault-kpi-knowledge',   summary.knowledge_records ?? '—', 'vault');
  setDataPoint('vault-kpi-portfolio',   summary.portfolio_records ?? '—', 'vault');

  const snaps = (snapData?.snapshots || []).slice(-14).reverse();
  const snapTbl = document.getElementById('vault-snapshot-table');
  if (snapTbl) {
    snapTbl.innerHTML = snaps.slice(0, 10).map(s => `<tr>
      <td style="font-size:0.68rem;color:var(--text-muted)">${s.snapshot_date}</td>
      <td><span class="chip">${s.regime || '?'}</span></td>
      <td>${s.nifty_close ? s.nifty_close.toFixed(1) : '—'}</td>
      <td class="${(s.nifty_return_1d||0) >= 0 ? 'positive' : 'negative'}">${s.nifty_return_1d != null ? ((s.nifty_return_1d>0?'+':'')+s.nifty_return_1d.toFixed(2)+'%') : '—'}</td>
      <td>${s.market_sentiment ? s.market_sentiment.toFixed(1) : '—'}</td>
      <td>${s.knowledge_score ? s.knowledge_score.toFixed(1) : '—'}</td>
    </tr>`).join('') || '<tr><td colspan="6" style="color:var(--text-muted);text-align:center">No snapshots yet</td></tr>';
  }

  const chartSnaps = (snapData?.snapshots || []).slice(-14);
  ChartRegistry.create('vaultSnapshotChart', {
    type: 'line',
    data: { labels: chartSnaps.map(s => s.snapshot_date?.slice(5)),
      datasets: [{ label: 'Nifty', data: chartSnaps.map(s => s.nifty_close),
        borderColor: '#00aaff', backgroundColor: 'rgba(0,170,255,0.08)', fill: true, tension: 0.4, pointRadius: 2 }] },
    options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { display: false } },
      scales: { x: { grid: { color: 'rgba(255,255,255,0.05)' }, ticks: { font: { size: 9 } } }, y: { grid: { color: 'rgba(255,255,255,0.05)' } } } },
  });

  const knowRecs = (knowData?.records || []).slice(-14);
  ChartRegistry.create('vaultKnowledgeChart', {
    type: 'line',
    data: { labels: knowRecs.map(r => r.archive_date?.slice(5)),
      datasets: [{ label: 'Knowledge', data: knowRecs.map(r => r.knowledge_score),
        borderColor: '#34d399', backgroundColor: 'rgba(52,211,153,0.1)', fill: true, tension: 0.4, pointRadius: 2 }] },
    options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { display: false } },
      scales: { x: { grid: { color: 'rgba(255,255,255,0.05)' }, ticks: { font: { size: 9 } } }, y: { min: 0, max: 100, grid: { color: 'rgba(255,255,255,0.05)' } } } },
  });

  const portRecs = (portData?.records || []).slice(-14);
  ChartRegistry.create('vaultPortfolioChart', {
    type: 'line',
    data: { labels: portRecs.map(r => r.archive_date?.slice(5)),
      datasets: [{ label: 'Portfolio', data: portRecs.map(r => r.total_value),
        borderColor: '#fbbf24', backgroundColor: 'rgba(251,191,36,0.1)', fill: true, tension: 0.4, pointRadius: 2 }] },
    options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { display: false } },
      scales: { x: { grid: { color: 'rgba(255,255,255,0.05)' }, ticks: { font: { size: 9 } } }, y: { grid: { color: 'rgba(255,255,255,0.05)' } } } },
  });

  const resTbl = document.getElementById('vault-research-table');
  if (resTbl) {
    const UCLASS = { high: 'negative', critical: 'negative' };
    resTbl.innerHTML = (resData?.records || []).slice(0, 20).map(r => `<tr>
      <td style="font-size:0.68rem;color:var(--text-muted)">${r.archive_date}</td>
      <td><span class="chip">${r.archive_type || '—'}</span></td>
      <td style="font-size:0.68rem;color:var(--text-muted)">${(r.agent_id||'').replace('_research','')||'—'}</td>
      <td style="font-size:0.72rem">${(r.title||'').slice(0,50)}</td>
      <td class="${UCLASS[r.urgency]||''}" style="font-size:0.68rem">${r.urgency?r.urgency.toUpperCase():'—'}</td>
    </tr>`).join('') || '<tr><td colspan="5" style="color:var(--text-muted);text-align:center">No records</td></tr>';
  }

  const bkpTbl = document.getElementById('vault-backups-table');
  if (bkpTbl) {
    bkpTbl.innerHTML = (backupData?.backups || []).slice(0, 10).map(b => `<tr>
      <td style="font-size:0.68rem;color:var(--text-muted)">${b.backup_timestamp || '—'}</td>
      <td>${b.backup_size_bytes ? (b.backup_size_bytes/1024/1024).toFixed(1)+' MB' : '—'}</td>
      <td>${b.vault_counts?.market_snapshots ?? '—'}</td>
      <td>${b.vault_counts?.prediction_archive ?? '—'}</td>
    </tr>`).join('') || '<tr><td colspan="4" style="color:var(--text-muted);text-align:center">No backups yet</td></tr>';
  }

  const briefsEl = document.getElementById('vault-briefs-list');
  if (briefsEl) {
    const briefs = (briefData?.briefs || []).slice(0, 15);
    briefsEl.innerHTML = briefs.map(b => `
      <div style="display:flex;justify-content:space-between;align-items:center;padding:5px 0;border-bottom:1px solid var(--border-faint)">
        <span style="font-family:var(--font-mono);font-size:0.72rem">${b.date}</span>
        <span style="font-size:0.65rem;color:var(--text-muted)">${b.size_bytes?(b.size_bytes/1024).toFixed(1)+' KB':''}</span>
        <a href="http://localhost:8000/api/v1/vault-briefs/${b.date}" target="_blank" style="color:var(--accent);font-size:0.65rem;font-family:var(--font-mono)">VIEW</a>
      </div>
    `).join('') || '<div style="color:var(--text-muted);font-size:0.72rem;padding:8px 0">No briefs stored. Generated daily.</div>';
  }
}

async function triggerVaultArchive() {
  await Api.triggerVault();
  _liveHydrated.delete('vault');
  await hydrateVault();
}

async function runVaultBackup() {
  const r = await Api.runBackup();
  alert(r ? `Backup complete: ${r.timestamp || '(done)'}` : 'Backup failed or backend offline.');
  _liveHydrated.delete('vault');
  await hydrateVault();
}

async function loadVaultReplay() {
  const dateInput  = document.getElementById('vault-replay-date');
  const replayBody = document.getElementById('vault-replay-body');
  const label      = document.getElementById('vault-replay-label');
  if (!dateInput?.value) {
    if (replayBody) replayBody.innerHTML = '<div style="color:var(--text-muted)">Select a date first.</div>';
    return;
  }
  const d = dateInput.value;
  if (label) label.textContent = `Replaying ${d}…`;
  if (replayBody) replayBody.innerHTML = '<div style="color:var(--text-muted)">Loading…</div>';

  const state = await Api.replayDate(d);
  if (!state || !state.data_available) {
    if (replayBody) replayBody.innerHTML = `<div style="color:var(--text-muted)">No archived data for ${d}. Vault starts archiving from first pipeline run.</div>`;
    if (label) label.textContent = `No data for ${d}`;
    return;
  }

  if (label) label.textContent = `AQRTI State at ${d}`;
  const m = state.market_state || {};
  const p = state.portfolio    || {};

  if (replayBody) replayBody.innerHTML = `
    <div style="display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-bottom:10px">
      <div style="background:var(--bg-raised);border:1px solid var(--border-faint);border-radius:6px;padding:10px">
        <div style="font-size:0.65rem;color:var(--text-muted);margin-bottom:6px">MARKET</div>
        <div style="font-size:0.72rem">Regime: <strong>${m.regime||'—'}</strong> ${m.regime_conf!=null?'('+((m.regime_conf||0)*100).toFixed(0)+'%)':''}</div>
        <div style="font-size:0.72rem">Nifty: ${m.nifty_close?m.nifty_close.toFixed(1):'—'}</div>
        <div style="font-size:0.72rem">Ret 1D: ${m.nifty_return_1d!=null?((m.nifty_return_1d>0?'+':'')+m.nifty_return_1d.toFixed(2)+'%'):'—'}</div>
        <div style="font-size:0.72rem">Sentiment: ${m.market_sentiment?m.market_sentiment.toFixed(1):'—'}</div>
        <div style="font-size:0.72rem">Knowledge: ${m.knowledge_score?m.knowledge_score.toFixed(1):'—'}</div>
      </div>
      <div style="background:var(--bg-raised);border:1px solid var(--border-faint);border-radius:6px;padding:10px">
        <div style="font-size:0.65rem;color:var(--text-muted);margin-bottom:6px">PORTFOLIO</div>
        <div style="font-size:0.72rem">Value: ${p.total_value?'₹'+p.total_value.toLocaleString('en-IN',{maximumFractionDigits:0}):'—'}</div>
        <div style="font-size:0.72rem">P&L: ${p.total_pnl!=null?((p.total_pnl>=0?'+':'')+'₹'+p.total_pnl.toFixed(0)):'—'}</div>
        <div style="font-size:0.72rem">Sharpe: ${p.sharpe!=null?p.sharpe.toFixed(2):'—'}</div>
        <div style="font-size:0.72rem">Win Rate: ${p.win_rate!=null?(p.win_rate*100).toFixed(1)+'%':'—'}</div>
      </div>
    </div>
    <div style="background:var(--bg-raised);border:1px solid var(--border-faint);border-radius:6px;padding:10px">
      <div style="font-size:0.65rem;color:var(--text-muted);margin-bottom:4px">STRATEGIES — ${(state.strategies||[]).length} archived</div>
      ${(state.strategies||[]).slice(0,5).map(s=>`<div style="font-size:0.7rem;padding:2px 0">${s.name||s.strategy_id} — fitness ${s.fitness_score?.toFixed(1)??'—'} — ${s.status}</div>`).join('')||'<div style="color:var(--text-muted);font-size:0.7rem">None</div>'}
    </div>
  `;
}


async function generateBrief() {
  const btn = document.getElementById('roc-brief-body');
  if (btn) btn.innerHTML = '<div style="color:var(--text-muted)">Generating brief…</div>';
  await Api.generateBrief();
  _liveHydrated.delete('agents');
  await hydrateResearchOps();
}

async function runAgentPipeline() {
  if (!confirm('Run full agent pipeline? This will execute all 7 research agents sequentially.')) return;
  const btn = document.getElementById('roc-kpi-pipeline');
  if (btn) btn.textContent = 'RUNNING…';
  await Api.agentPipeline();
  _liveHydrated.delete('agents');
  await hydrateResearchOps();
}


