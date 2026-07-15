// ui/pages/strategy.js - split from app.js (ARCH-5), see CHANGELOG
// ═══════════════════════════════════════════════════════════════
// STRATEGY RESEARCH CENTER — Phase 6
// ═══════════════════════════════════════════════════════════════

async function hydrateStrategyResearch() {
  const el = id => document.getElementById(id);
  const statusEl = el('src-status-label');
  if (statusEl) statusEl.textContent = 'Loading…';

  // Fetch all in parallel for speed
  let pop, leaders, evoTree, affinity, graveD, resurrect, research;
  try {
    [pop, leaders, evoTree, affinity, graveD, resurrect, research] = await Promise.all([
      Api.strategyPopulation(),
      Api.strategyLeaderboard(15),
      Api.evolutionTree(90),
      Api.regimeAffinity(),
      Api.graveyard({ limit: 20 }),
      Api.resurrectionCandidates(),
      Api.latestResearch(),
    ]);
  } catch (err) {
    console.error('[Strategy Research] Data fetch failed:', err);
    if (statusEl) statusEl.textContent = 'Backend offline';
    return;
  }

  const serverOnline = !!(pop || leaders);
  if (statusEl) {
    const now = new Date().toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit' });
    statusEl.textContent = serverOnline ? `Updated ${now}` : 'Backend offline — start server';
    statusEl.style.color = serverOnline ? 'var(--positive)' : 'var(--negative)';
  }



  // ── KPIs ──────────────────────────────────────────────────────
  const stats = (pop && pop.stats) || {};
  const _kpi = (id, v) => { const e = el(id); if (e) e.textContent = v; };
  _kpi('src-kpi-total', stats.total || '—');
  _kpi('src-kpi-active-sub', `${stats.active_count || 0} Active`);
  _kpi('src-kpi-avg-fitness', stats.avg_fitness != null ? stats.avg_fitness.toFixed(1) : '—');
  _kpi('src-kpi-best-fitness', stats.max_fitness != null ? stats.max_fitness.toFixed(1) : '—');
  const bestRow = (leaders && leaders.leaderboard && leaders.leaderboard.length) ? leaders.leaderboard[0] : null;
  _kpi('src-kpi-best-name', bestRow ? (bestRow.name || bestRow.strategy_id || '—') : '—');
  _kpi('src-kpi-generation', stats.max_generation || '—');
  _kpi('src-kpi-graveyard', stats.graveyard_count || '—');
  _kpi('src-kpi-promoted', stats.promoted || '—');

  // ── Leaderboard ───────────────────────────────────────────────
  const lbBody = el('src-leaderboard-body');
  if (lbBody) {
    const rows = (leaders && leaders.leaderboard) ? leaders.leaderboard : [];
    lbBody.innerHTML = rows.slice(0, 15).map((r, i) => {
      const statusClass = { active: 'positive', promoted: 'accent', shadow: 'neutral', candidate: '' }[r.status] || '';
      const fitness  = r.fitness_score != null ? r.fitness_score.toFixed(1) : '—';
      const wr       = r.win_rate != null ? `${r.win_rate.toFixed(1)}%` : '—';
      const avgPnl   = r.avg_pnl_pct != null ? r.avg_pnl_pct : null;
      const avgPnlStr = avgPnl != null ? (avgPnl >= 0 ? '+' : '') + avgPnl.toFixed(2) + '%' : '—';
      const avgPnlColor = avgPnl == null ? '' : avgPnl > 0 ? 'color:var(--positive)' : avgPnl < 0 ? 'color:var(--negative)' : '';
      const canActivate = r.status === 'promoted';
      // 'promoted' means it passed backtest+OOS gates but has NOT yet been
      // forward-proven in paper trading (the quarantine). 'active' means a
      // human approved it after quarantine (or forced). Make that distinction
      // visible — otherwise an unproven strategy looks identical to a proven one.
      const quarantineBadge = r.status === 'promoted'
        ? ' <span style="font-size:0.6rem;color:var(--warning);border:1px solid rgba(200,200,204,0.4);border-radius:3px;padding:0 4px" title="Backtest-proven only — not yet forward-tested in paper trading">UNPROVEN</span>'
        : r.status === 'active'
          ? ' <span style="font-size:0.6rem;color:var(--positive);border:1px solid rgba(240,240,242,0.4);border-radius:3px;padding:0 4px" title="Human-approved after forward paper-trading quarantine">PROVEN</span>'
          : '';
      const maxDd = r.max_drawdown != null ? r.max_drawdown : null;
      const ddWarn = maxDd != null && maxDd < -30;
      const ddStr  = maxDd != null ? `${maxDd.toFixed(1)}%` : '—';
      const ddColor = maxDd == null ? '' : maxDd < -50 ? 'color:var(--negative);font-weight:700' : maxDd < -30 ? 'color:var(--warning);font-weight:600' : 'color:var(--text-muted)';
      return `<tr${ddWarn ? ' title="⚠ High drawdown — use caution"' : ''}>
        <td style="color:var(--text-muted)">${i + 1}</td>
        <td style="font-family:var(--font-mono);font-size:0.72rem">
          <div>${r.name || '—'}${ddWarn ? ' <span style="color:var(--warning);font-size:0.65rem">⚠</span>' : ''}</div>
          <div onclick="loadStrategyDna('${r.strategy_id}');document.getElementById('panel-dna-viewer').scrollIntoView({behavior:'smooth'})" style="font-size:0.62rem;color:var(--accent);letter-spacing:0.02em;cursor:pointer;text-decoration:underline dotted" title="Click to open DNA viewer">${r.strategy_id}</div>
        </td>
        <td><span class="chip">${r.family || '—'}</span></td>
        <td class="${statusClass}" style="font-size:0.7rem">${(r.status || '').toUpperCase()}${quarantineBadge}</td>
        <td style="font-weight:600">${fitness}</td>
        <td>${wr}</td>
        <td style="font-weight:600;${avgPnlColor}">${avgPnlStr}</td>
        <td style="${ddColor}">${ddStr}</td>
        <td style="color:var(--text-muted)">${r.trade_count || 0}</td>
        <td style="white-space:nowrap">
          ${canActivate ? `<button class="panel-action-btn" onclick="activateStrategy('${r.strategy_id}')">Activate</button> ` : ''}
          ${r.trade_count > 0 ? `<button class="panel-action-btn" style="background:rgba(232,232,234,0.12);border-color:rgba(232,232,234,0.35)" onclick="openStrategyTrades('${r.strategy_id}')">Trades</button> ` : ''}
          <button class="panel-action-btn" style="background:rgba(196,196,200,0.1);border-color:rgba(196,196,200,0.35);color:rgba(196,196,200,0.9)" onclick="loadStrategyDna('${r.strategy_id}');document.getElementById('panel-dna-viewer').scrollIntoView({behavior:'smooth'})">DNA</button>
        </td>
      </tr>`;
    }).join('') || `<tr><td colspan="10" style="color:var(--text-muted);text-align:center">${serverOnline ? 'No strategies yet' : 'Backend offline — click Refresh after starting server'}</td></tr>`;
  }

  // ── Family Population Chart ───────────────────────────────────
  const familyData = (pop && pop.by_family) || {};
  const famLabels  = Object.keys(familyData);
  // API returns count/active_count per family; graveyard count not split by family here
  const famAlive   = famLabels.map(f => familyData[f].count || familyData[f].alive || 0);
  const famDead    = famLabels.map(f => familyData[f].dead  || 0);
  ChartRegistry.create('srcFamilyChart', {
    type: 'bar',
    data: {
      labels: famLabels,
      datasets: [
        { label: 'Alive', data: famAlive, backgroundColor: 'rgba(232,232,234,0.7)' },
        { label: 'Graveyard', data: famDead, backgroundColor: 'rgba(154,154,159,0.4)' },
      ],
    },
    options: {
      responsive: true, maintainAspectRatio: false,
      plugins: { legend: { labels: { font: { size: 10 } } } },
      scales: {
        x: { stacked: true, grid: { color: 'rgba(255,255,255,0.05)' }, ticks: { font: { size: 9 } } },
        y: { stacked: true, grid: { color: 'rgba(255,255,255,0.05)' } },
      },
    },
  });

  // ── Evolution Operations Chart ────────────────────────────────
  const ops     = (evoTree && evoTree.by_operation) || {};
  const opKeys  = Object.keys(ops);
  const opDelta = opKeys.map(k => ops[k].avg_fitness_delta || 0);
  const opPos   = opKeys.map(k => ops[k].positive_pct || 0);
  ChartRegistry.create('srcEvoChart', {
    type: 'bar',
    data: {
      labels: opKeys,
      datasets: [
        {
          label: 'Avg Fitness Δ',
          data: opDelta,
          backgroundColor: opDelta.map(v => v >= 0 ? 'rgba(240,240,242,0.6)' : 'rgba(154,154,159,0.5)'),
          yAxisID: 'y',
        },
        {
          label: '% Positive',
          data: opPos,
          type: 'line',
          borderColor: 'rgba(200,200,204,0.8)',
          backgroundColor: 'transparent',
          pointRadius: 3,
          yAxisID: 'y1',
        },
      ],
    },
    options: {
      responsive: true, maintainAspectRatio: false,
      plugins: { legend: { labels: { font: { size: 10 } } } },
      scales: {
        x: { grid: { color: 'rgba(255,255,255,0.05)' }, ticks: { font: { size: 9 } } },
        y:  { grid: { color: 'rgba(255,255,255,0.05)' }, title: { display: true, text: 'Avg Δ Fitness' } },
        y1: { position: 'right', min: 0, max: 100, grid: { display: false }, title: { display: true, text: '% Positive' } },
      },
    },
  });

  // ── Regime Affinity Chart ─────────────────────────────────────
  const REGIMES = ['BULL', 'BEAR', 'SIDEWAYS', 'VOLATILE'];
  const REGIME_COLORS = ['rgba(240,240,242,0.7)', 'rgba(154,154,159,0.6)', 'rgba(200,200,204,0.6)', 'rgba(196,196,200,0.6)'];
  const affFamilies = affinity ? Object.keys(affinity) : [];
  ChartRegistry.create('srcRegimeChart', {
    type: 'bar',
    data: {
      labels: affFamilies,
      datasets: REGIMES.map((reg, i) => ({
        label: reg,
        data: affFamilies.map(f => (affinity[f]?.regime_sharpe?.[reg] || 0)),
        backgroundColor: REGIME_COLORS[i],
      })),
    },
    options: {
      responsive: true, maintainAspectRatio: false,
      plugins: { legend: { labels: { font: { size: 10 } } } },
      scales: {
        x: { grid: { color: 'rgba(255,255,255,0.05)' }, ticks: { font: { size: 9 } } },
        y: { grid: { color: 'rgba(255,255,255,0.05)' }, title: { display: true, text: 'Avg Sharpe' } },
      },
    },
  });

  // ── Graveyard Table ───────────────────────────────────────────
  const graveyardBody = el('src-graveyard-body');
  if (graveyardBody) {
    const rows = (graveD && graveD.graveyard) ? graveD.graveyard : [];
    graveyardBody.innerHTML = rows.map(r => `<tr>
      <td style="font-family:var(--font-mono);font-size:0.72rem">${r.name || r.strategy_id}</td>
      <td><span class="chip">${r.family || '—'}</span></td>
      <td class="negative">${r.final_fitness != null ? r.final_fitness.toFixed(1) : '—'}</td>
      <td style="font-size:0.72rem;color:var(--text-muted)">${r.failure_reason || '—'}</td>
      <td><span class="chip">${r.regime_at_death || '—'}</span></td>
      <td style="color:var(--text-muted)">${r.lifespan_days != null ? `${r.lifespan_days}d` : '—'}</td>
    </tr>`).join('') || `<tr><td colspan="6" style="color:var(--text-muted);text-align:center">No buried strategies yet</td></tr>`;
  }

  // ── Resurrection Candidates ───────────────────────────────────
  const resurrBody = el('src-resurrection-body');
  if (resurrBody) {
    const rows = (resurrect && resurrect.candidates) ? resurrect.candidates : [];
    resurrBody.innerHTML = rows.map(r => `<tr>
      <td style="font-family:var(--font-mono);font-size:0.72rem">${r.name || r.strategy_id}</td>
      <td><span class="chip">${r.family || '—'}</span></td>
      <td class="accent">${r.final_fitness != null ? r.final_fitness.toFixed(1) : '—'}</td>
      <td class="negative">${r.died_in_regime || '—'}</td>
      <td class="positive">${r.current_regime || '—'}</td>
    </tr>`).join('') || `<tr><td colspan="5" style="color:var(--text-muted);text-align:center">No resurrection candidates</td></tr>`;
  }

  // ── Strategy Activity Feed ────────────────────────────────────
  const feedEl = el('src-activity-feed');
  if (feedEl) {
    // Pull recent knowledge events filtered to strategy category
    const events = await apiFetch('/knowledge?days=7').catch(() => null);
    const evList = events ? (events.recentEvents || []) : [];
    const stratEvts = evList.filter(e => e.category === 'strategy' || (e.eventType || e.type || '').startsWith('strategy_'));
    if (stratEvts.length) {
      feedEl.innerHTML = stratEvts.slice(0, 30).map(e => {
        const evType   = e.eventType || e.type || '';
        const isPromo  = evType === 'strategy_promoted';
        const isRetire = evType === 'strategy_retired';
        const color = isPromo ? 'var(--positive)' : isRetire ? 'var(--negative)' : 'var(--text-muted)';
        const icon  = isPromo ? '▲' : isRetire ? '▼' : '●';
        return `<div style="display:flex;align-items:flex-start;gap:8px;padding:6px 12px;border-bottom:1px solid var(--border-faint)">
          <span style="color:${color};min-width:12px;margin-top:1px">${icon}</span>
          <div>
            <div style="color:${color};font-size:0.68rem">${e.date || e.event_date || ''}</div>
            <div style="color:var(--text-secondary);font-size:0.7rem;line-height:1.4">${e.description || evType}</div>
          </div>
        </div>`;
      }).join('');
    } else {
      // Fall back to showing leaderboard changes if no events
      const lbRows = (leaders && leaders.leaderboard) ? leaders.leaderboard.slice(0, 10) : [];
      feedEl.innerHTML = lbRows.map(r => `
        <div style="display:flex;align-items:flex-start;gap:8px;padding:6px 12px;border-bottom:1px solid var(--border-faint)">
          <span style="color:var(--accent);min-width:12px;margin-top:1px">▲</span>
          <div>
            <div style="color:var(--text-muted);font-size:0.68rem">TODAY</div>
            <div style="color:var(--text-secondary);font-size:0.7rem;line-height:1.4">[${r.strategy_id}] ${r.status?.toUpperCase()} — Fitness=${r.fitness_score?.toFixed(1) ?? '—'} Sharpe=${r.sharpe?.toFixed(2) ?? '—'}</div>
          </div>
        </div>`).join('') || '<div style="padding:1rem;color:var(--text-muted)">No recent activity</div>';
    }
  }

  // ── Research Report Cards ─────────────────────────────────────
  const researchCards = el('src-research-cards');
  if (researchCards && research) {
    const CATEGORY_ICONS = {
      feature_analysis:  '◆',
      regime_analysis:   '◈',
      family_survival:   '◉',
      evolution_summary: '▷',
      resurrection:      '↑',
      population_health: '▣',
    };
    researchCards.innerHTML = Object.entries(research).map(([cat, rep]) => `
      <div style="background:var(--bg-raised);border:1px solid var(--border-faint);border-radius:8px;padding:14px">
        <div style="display:flex;align-items:center;gap:8px;margin-bottom:8px">
          <span style="color:var(--accent);font-size:1rem">${CATEGORY_ICONS[cat] || '◦'}</span>
          <span style="font-size:0.75rem;font-weight:600;color:var(--text-primary)">${rep.title || cat}</span>
        </div>
        <div style="font-size:0.72rem;color:var(--text-secondary);margin-bottom:8px;line-height:1.5">${rep.summary || '—'}</div>
        ${rep.recommendations ? `<div style="font-size:0.68rem;color:var(--accent);background:rgba(232,232,234,0.06);padding:6px 10px;border-radius:4px;border-left:2px solid var(--accent)">${rep.recommendations}</div>` : ''}
      </div>
    `).join('');
  }

  // Load trade recommendations and top strategy DNA viewer
  loadTradeRecommendations().catch(() => {});

  // Load meta-learning state
  loadMetaLearningState().catch(() => {});
}

async function activateStrategy(strategyId) {
  if (!confirm(`Activate algo ${strategyId}?\n\nThis marks it ACTIVE (requires "promoted" status).`)) return;
  try {
    const res = await fetch(`${API_CONFIG.BASE}/strategies/${strategyId}/activate`, { method: 'POST' });
    const result = await res.json();
    if (res.ok && result.status === 'active') {
      alert(`Algo ${strategyId} is now ACTIVE.`);
      _liveHydrated.delete('strategy');
      hydrateStrategyResearch();
    } else {
      const msg = result.detail || result.message || JSON.stringify(result);
      alert(`Cannot activate: ${msg}`);
    }
  } catch (e) {
    alert(`Error: ${e.message}`);
  }
}

async function bulkActivateTop5() {
  try {
    const data = await apiFetch('/strategies/leaderboard?top_n=10&status=promoted');
    if (!data || !data.leaderboard) { alert('No promoted strategies to activate.'); return; }
    const top5 = data.leaderboard.filter(r => r.status === 'promoted').slice(0, 5);
    if (!top5.length) { alert('No promoted strategies found in top 10.'); return; }
    if (!confirm(`Activate top ${top5.length} promoted strategies?\n\n${top5.map(r => `  ${r.name} (fitness ${r.fitness_score?.toFixed(1)})`).join('\n')}`)) return;
    let activated = 0, errors = 0;
    for (const r of top5) {
      try {
        const res = await fetch(`${API_CONFIG.BASE}/strategies/${r.strategy_id}/activate`, { method: 'POST' });
        if (res.ok) activated++;
        else errors++;
      } catch { errors++; }
    }
    alert(`Activated ${activated} strategies.${errors ? ` (${errors} failed)` : ''}`);
    _liveHydrated.delete('strategy');
    await hydrateStrategyResearch();
  } catch (e) {
    alert(`Error: ${e.message}`);
  }
}

async function triggerStrategyResearch() {
  const btn = document.getElementById('src-run-research-btn');
  if (btn) { btn.textContent = 'Running…'; btn.disabled = true; }
  try {
    await Api.triggerStrategyResearch();
    _liveHydrated.delete('strategy');
    await hydrateStrategyResearch();
  } finally {
    if (btn) { btn.textContent = 'Run Research'; btn.disabled = false; }
  }
}


// ═══════════════════════════════════════════════════════════════
// STRATEGY DNA VIEWER
// ═══════════════════════════════════════════════════════════════

async function loadStrategyDna(strategyId) {
  if (!strategyId) return;
  const container = document.getElementById('dna-content');
  if (!container) return;
  container.innerHTML = `<div style="color:var(--text-muted);font-size:0.8rem;padding:1rem">Loading DNA for <b>${strategyId}</b>…</div>`;
  const searchInput = document.getElementById('dna-search-input');
  if (searchInput) searchInput.value = strategyId;

  let dna;
  try {
    dna = await Api.strategyDna(strategyId);
  } catch (e) {
    container.innerHTML = `<div style="color:var(--negative);padding:1rem">Error loading DNA: ${e.message}</div>`;
    return;
  }
  if (!dna || dna.detail) {
    container.innerHTML = `<div style="color:var(--negative);padding:1rem">Algo not found: <code>${strategyId}</code><br><span style="color:var(--text-muted);font-size:0.75rem">Backend may be offline or the ID is invalid.</span></div>`;
    return;
  }

  try {
  const statusColor = { active:'var(--positive)', promoted:'var(--accent)', shadow:'var(--text-muted)', retired:'var(--negative)', candidate:'' }[dna.status] || '';
  const rr = (dna.stop_loss_pct && dna.take_profit_pct)
    ? (Math.abs(dna.take_profit_pct) / Math.abs(dna.stop_loss_pct)).toFixed(2)
    : '—';

  // Live validation — backend returns flat keys, not nested bt/lv objects
  const fv = dna.live_validation || {};

  // Trade sample rows
  const trades = (dna.recent_trades || []).slice(0, 8);
  const tradeTbody = trades.map(t => {
    const c = (t.pnl_pct || 0) >= 0 ? 'var(--positive)' : 'var(--negative)';
    return `<tr>
      <td style="font-family:var(--font-mono);font-size:0.72rem">${t.symbol || '—'}</td>
      <td style="font-size:0.7rem;color:var(--text-muted)">${t.entry_date || '—'}</td>
      <td style="font-size:0.7rem;color:var(--text-muted)">${t.exit_date || '—'}</td>
      <td style="font-size:0.7rem">${t.holding_days ?? '—'}d</td>
      <td style="font-weight:600;color:${c}">${t.pnl_pct >= 0 ? '+' : ''}${(t.pnl_pct || 0).toFixed(2)}%</td>
      <td style="font-size:0.7rem;color:var(--text-muted)">${t.exit_reason || '—'}</td>
      <td style="font-size:0.7rem;color:var(--text-muted)">${t.regime || '—'}</td>
    </tr>`;
  }).join('') || `<tr><td colspan="7" style="color:var(--text-muted);text-align:center">No backtest trades recorded</td></tr>`;

  // Entry/exit rules
  const entryRules = (dna.entry_rules || []).map(r => `<li style="margin:2px 0;color:var(--text-secondary)">${r}</li>`).join('') || '<li style="color:var(--text-muted)">No decoded rules (DSL may use ML signals)</li>';
  const exitRules  = (dna.exit_rules  || []).map(r => `<li style="margin:2px 0;color:var(--text-secondary)">${r}</li>`).join('') || `<li style="color:var(--text-muted)">Stop ${dna.stop_loss_pct ?? '?'}% · Target ${dna.take_profit_pct ?? '?'}% · Max ${dna.max_holding_days ?? '?'} days</li>`;

  // Parents
  const parents = (dna.parents || []).map(p =>
    `<span onclick="loadStrategyDna('${p.strategy_id}')" style="cursor:pointer;background:rgba(255,255,255,0.05);border:1px solid var(--border);border-radius:4px;padding:2px 8px;font-size:0.7rem;font-family:var(--font-mono);color:var(--accent);margin:2px"
      title="fitness ${p.fitness}">${p.name || p.strategy_id} (${p.family})</span>`
  ).join('') || '<span style="color:var(--text-muted);font-size:0.72rem">Genesis — no parent (original)</span>';

  // Children
  const children = (dna.children || []).slice(0, 5).map(c =>
    `<span onclick="loadStrategyDna('${c.strategy_id}')" style="cursor:pointer;background:rgba(240,240,242,0.06);border:1px solid rgba(240,240,242,0.2);border-radius:4px;padding:2px 8px;font-size:0.7rem;font-family:var(--font-mono);color:var(--positive);margin:2px"
      title="${c.operation}">${c.name || c.strategy_id}</span>`
  ).join('') || '<span style="color:var(--text-muted);font-size:0.72rem">No offspring yet</span>';

  // Version/mutation history
  const versions = (dna.version_history || []).slice(-5).reverse().map(v =>
    `<div style="padding:4px 0;border-bottom:1px solid rgba(255,255,255,0.04);font-size:0.7rem">
      <span style="color:var(--text-muted)">v${v.version}</span>
      <span style="color:var(--accent);margin:0 8px">${v.change_type || '—'}</span>
      <span style="color:var(--text-secondary)">${v.change_desc || ''}</span>
      ${v.fitness_score != null ? `<span style="float:right;color:var(--positive)">fitness ${v.fitness_score.toFixed(1)}</span>` : ''}
    </div>`
  ).join('') || '<div style="color:var(--text-muted);font-size:0.72rem">No version history</div>';

  // Live validation — use actual flat key names from get_live_validation_summary()
  // Keys: live_sharpe, live_winrate, backtest_sharpe, backtest_winrate, divergence, live_trades
  let validHtml = '<span style="color:var(--text-muted);font-size:0.72rem">No live trade data yet (paper trade to generate)</span>';
  if (fv.available !== false && fv.live_sharpe != null) {
    const btSharpe = fv.backtest_sharpe || 0;
    const btWr     = fv.backtest_winrate || 0;
    const lvSharpe = fv.live_sharpe || 0;
    const lvWr     = fv.live_winrate || 0;
    const shDelta  = lvSharpe - btSharpe;
    const wrDelta  = lvWr - btWr;
    const shColor  = shDelta >= -0.3 ? 'var(--positive)' : 'var(--negative)';
    const wrColor  = wrDelta >= -5 ? 'var(--positive)' : 'var(--negative)';
    const divStatus = fv.divergence || 'ok';
    validHtml = `<div style="display:grid;grid-template-columns:repeat(4,1fr);gap:8px;font-size:0.72rem;font-family:var(--font-mono)">
      <div><div style="color:var(--text-muted)">Backtest Sharpe</div><div style="font-size:1.1rem;font-weight:600">${btSharpe.toFixed(2)}</div></div>
      <div><div style="color:var(--text-muted)">Live Sharpe</div><div style="font-size:1.1rem;font-weight:600;color:${shColor}">${lvSharpe.toFixed(2)} (${shDelta>=0?'+':''}${shDelta.toFixed(2)})</div></div>
      <div><div style="color:var(--text-muted)">Backtest Win%</div><div style="font-size:1.1rem;font-weight:600">${btWr.toFixed(1)}%</div></div>
      <div><div style="color:var(--text-muted)">Live Win%</div><div style="font-size:1.1rem;font-weight:600;color:${wrColor}">${lvWr.toFixed(1)}% (${wrDelta>=0?'+':''}${wrDelta.toFixed(1)}pp)</div></div>
    </div>
    <div style="margin-top:6px;font-size:0.68rem;color:var(--text-muted);font-family:var(--font-mono)">Live trades: ${fv.live_trades || 0} · Total P&amp;L: ${fv.live_total_pnl != null ? (fv.live_total_pnl >= 0 ? '+' : '') + fv.live_total_pnl.toFixed(2) + '%' : '—'}</div>
    <div style="margin-top:6px;padding:4px 8px;border-radius:4px;font-size:0.7rem;background:${divStatus==='ok'?'rgba(240,240,242,0.1)':divStatus==='warning'?'rgba(200,200,204,0.1)':'rgba(154,154,159,0.1)'};color:${divStatus==='ok'?'var(--positive)':divStatus==='warning'?'rgba(200,200,204,0.9)':'var(--negative)'}">
      ${divStatus === 'ok' ? '✓ Live performance tracking backtest — strategy is validated' : `⚠ Divergence: ${divStatus} — sharpe gap ${fv.sharpe_gap != null ? fv.sharpe_gap.toFixed(2) : '?'}, win-rate gap ${fv.winrate_gap != null ? fv.winrate_gap.toFixed(1) : '?'}pp`}
    </div>`;
  }

  container.innerHTML = `
    <div style="display:grid;grid-template-columns:1fr 1fr;gap:16px;padding-bottom:16px">

      <!-- LEFT: Identity + Rules -->
      <div>
        <div style="display:flex;align-items:baseline;gap:10px;margin-bottom:12px;flex-wrap:wrap">
          <span style="font-family:var(--font-mono);font-size:1rem;font-weight:700;color:var(--text-primary)">${dna.name}</span>
          <span class="chip">${dna.family}</span>
          <span style="color:${statusColor};font-size:0.72rem;font-weight:700">${(dna.status||'').toUpperCase()}</span>
          <span style="color:var(--text-muted);font-size:0.7rem">Gen ${dna.generation || 1}</span>
        </div>

        <!-- KPIs -->
        <div style="display:grid;grid-template-columns:repeat(4,1fr);gap:8px;margin-bottom:14px">
          ${[
            ['Fitness', dna.fitness_score != null ? dna.fitness_score.toFixed(1) : '—', 'var(--accent)'],
            ['Sharpe',  dna.sharpe != null ? dna.sharpe.toFixed(2) : '—', ''],
            ['Win%',    dna.win_rate != null ? dna.win_rate.toFixed(1)+'%' : '—', 'var(--positive)'],
            ['P/F',     dna.profit_factor != null ? dna.profit_factor.toFixed(2) : '—', ''],
            ['Max DD',  dna.max_drawdown != null ? dna.max_drawdown.toFixed(1)+'%' : '—', 'var(--negative)'],
            ['Trades',  dna.trade_count ?? '—', ''],
            ['Avg Hold',dna.avg_holding_days != null ? dna.avg_holding_days.toFixed(1)+'d' : '—', ''],
            ['Net Exp', dna.net_expectancy != null ? (dna.net_expectancy >= 0 ? '+' : '')+dna.net_expectancy.toFixed(2)+'%' : '—', dna.net_expectancy != null ? (dna.net_expectancy >= 0 ? 'var(--positive)' : 'var(--negative)') : ''],
          ].map(([l,v,c]) => `<div style="background:rgba(255,255,255,0.03);border:1px solid var(--border);border-radius:6px;padding:8px 10px">
            <div style="font-size:0.62rem;color:var(--text-muted);font-family:var(--font-mono);margin-bottom:2px">${l}</div>
            <div style="font-size:0.95rem;font-weight:700;${c?'color:'+c:''}">${v}</div>
          </div>`).join('')}
        </div>

        <!-- Entry Rules -->
        <div style="margin-bottom:12px">
          <div style="font-size:0.72rem;color:var(--text-muted);font-family:var(--font-mono);margin-bottom:6px;letter-spacing:0.08em">ENTRY CONDITIONS</div>
          <ul style="margin:0;padding-left:16px;font-family:var(--font-mono);font-size:0.72rem">${entryRules}</ul>
        </div>

        <!-- Exit Rules -->
        <div style="margin-bottom:12px">
          <div style="font-size:0.72rem;color:var(--text-muted);font-family:var(--font-mono);margin-bottom:6px;letter-spacing:0.08em">EXIT RULES</div>
          <ul style="margin:0;padding-left:16px;font-family:var(--font-mono);font-size:0.72rem">${exitRules}</ul>
          <div style="margin-top:6px;font-size:0.7rem;color:var(--text-muted);font-family:var(--font-mono)">
            Stop ${dna.stop_loss_pct ?? '?'}% · Target ${dna.take_profit_pct ?? '?'}% · Reward:Risk ${rr} · Min Confidence ${dna.min_confidence ?? '?'}%
          </div>
        </div>

        <!-- Allowed Regimes -->
        <div style="margin-bottom:12px">
          <div style="font-size:0.72rem;color:var(--text-muted);font-family:var(--font-mono);margin-bottom:6px;letter-spacing:0.08em">REGIME PERMISSIONS</div>
          <div style="display:flex;gap:6px;flex-wrap:wrap">
            ${['BULL','BEAR','SIDEWAYS','VOLATILE'].map(r => {
              const allowed = !dna.allowed_regimes || dna.allowed_regimes.includes(r);
              const colors = {BULL:'var(--positive)',BEAR:'var(--negative)',SIDEWAYS:'rgba(200,200,204,0.9)',VOLATILE:'rgba(196,196,200,0.9)'};
              return `<span style="padding:3px 10px;border-radius:4px;font-size:0.7rem;font-family:var(--font-mono);border:1px solid;${allowed?`color:${colors[r]};border-color:${colors[r]};background:${colors[r]}1a`:'color:var(--text-muted);border-color:rgba(255,255,255,0.08);opacity:0.4'}">${r}</span>`;
            }).join('')}
          </div>
        </div>

        <!-- Regime Sharpes -->
        <div>
          <div style="font-size:0.72rem;color:var(--text-muted);font-family:var(--font-mono);margin-bottom:6px;letter-spacing:0.08em">REGIME SHARPE</div>
          <div style="display:grid;grid-template-columns:repeat(4,1fr);gap:6px">
            ${[['BULL',dna.bull_sharpe],['BEAR',dna.bear_sharpe],['SIDE',dna.sideways_sharpe],['VOLA',dna.volatile_sharpe]].map(([l,v]) => {
              const val = v ?? 0;
              const c = val > 0.5 ? 'var(--positive)' : val < 0 ? 'var(--negative)' : 'var(--text-muted)';
              return `<div style="text-align:center;background:rgba(255,255,255,0.03);border:1px solid var(--border);border-radius:4px;padding:6px 4px">
                <div style="font-size:0.62rem;color:var(--text-muted)">${l}</div>
                <div style="font-weight:700;color:${c}">${val.toFixed(2)}</div>
              </div>`;
            }).join('')}
          </div>
        </div>
      </div>

      <!-- RIGHT: Lineage + Validation -->
      <div>
        <!-- Parents -->
        <div style="margin-bottom:14px">
          <div style="font-size:0.72rem;color:var(--text-muted);font-family:var(--font-mono);margin-bottom:6px;letter-spacing:0.08em">PARENT STRATEGIES (click to explore)</div>
          <div style="display:flex;flex-wrap:wrap;gap:4px">${parents}</div>
        </div>

        <!-- Children -->
        <div style="margin-bottom:14px">
          <div style="font-size:0.72rem;color:var(--text-muted);font-family:var(--font-mono);margin-bottom:6px;letter-spacing:0.08em">OFFSPRING (${(dna.children||[]).length} total)</div>
          <div style="display:flex;flex-wrap:wrap;gap:4px">${children}</div>
        </div>

        <!-- Version history -->
        <div style="margin-bottom:14px">
          <div style="font-size:0.72rem;color:var(--text-muted);font-family:var(--font-mono);margin-bottom:6px;letter-spacing:0.08em">MUTATION HISTORY</div>
          <div style="background:rgba(255,255,255,0.02);border:1px solid var(--border);border-radius:6px;padding:8px 12px;max-height:150px;overflow-y:auto">${versions}</div>
        </div>

        <!-- Live validation -->
        <div style="margin-bottom:14px">
          <div style="font-size:0.72rem;color:var(--text-muted);font-family:var(--font-mono);margin-bottom:6px;letter-spacing:0.08em">LIVE vs BACKTEST VALIDATION</div>
          <div style="background:rgba(255,255,255,0.02);border:1px solid var(--border);border-radius:6px;padding:10px 12px">${validHtml}</div>
        </div>

        <!-- Backtest start/end -->
        <div style="font-size:0.7rem;color:var(--text-muted);font-family:var(--font-mono)">
          Backtest: ${dna.backtest_start || '—'} → ${dna.backtest_end || '—'} · Created: ${(dna.created_at||'').slice(0,10) || '—'} · Promoted: ${(dna.promoted_at||'').slice(0,10) || '—'}
        </div>
      </div>
    </div>

    <!-- Sample Trades -->
    <div>
      <div style="font-size:0.72rem;color:var(--text-muted);font-family:var(--font-mono);margin-bottom:6px;letter-spacing:0.08em;padding-top:12px;border-top:1px solid var(--border)">RECENT BACKTEST TRADES (last 8)</div>
      <table class="data-table compact">
        <thead><tr><th>Symbol</th><th>Entry</th><th>Exit</th><th>Hold</th><th>P&amp;L%</th><th>Reason</th><th>Regime</th></tr></thead>
        <tbody>${tradeTbody}</tbody>
      </table>
    </div>
  `;
  } catch (renderErr) {
    container.innerHTML = `<div style="color:var(--negative);padding:1rem">Render error: ${renderErr.message}<br><span style="color:var(--text-muted);font-size:0.72rem">Algo data loaded but failed to display. Check browser console.</span></div>`;
  }
}


// ═══════════════════════════════════════════════════════════════
// TRADE RECOMMENDATIONS
// ═══════════════════════════════════════════════════════════════

async function loadTradeRecommendations() {
  const body = document.getElementById('recs-body');
  const regimeLabel = document.getElementById('recs-regime-label');
  const stratBar    = document.getElementById('recs-strategy-bar');
  if (!body) return;
  body.innerHTML = `<div style="color:var(--text-muted);font-size:0.8rem;padding:1rem">Loading…</div>`;

  const data = await Api.tradeRecommendations();
  if (!data || !data.recommendations) {
    body.innerHTML = `<div style="color:var(--text-muted);padding:1rem">No recommendations available — run predictions first.</div>`;
    return;
  }

  const regime = data.currentRegime || 'UNKNOWN';
  const regimeColors = { BULL:'var(--positive)', BEAR:'var(--negative)', SIDEWAYS:'rgba(200,200,204,0.9)', VOLATILE:'rgba(196,196,200,0.9)' };
  if (regimeLabel) {
    regimeLabel.textContent = `${regime} REGIME`;
    regimeLabel.style.color = regimeColors[regime] || '';
  }

  if (data.topStrategy && stratBar) {
    const ts = data.topStrategy;
    stratBar.innerHTML = `Algo: <b style="color:var(--accent)">${ts.name}</b> · Fitness <b>${(ts.fitness||0).toFixed(1)}</b> · Sharpe <b>${(ts.sharpe||0).toFixed(2)}</b> · Win% <b>${(ts.winRate||0).toFixed(1)}%</b> · 5% position size · max 8 trades`;
  }

  const recs = data.recommendations;
  if (!recs.length) {
    body.innerHTML = `<div style="color:var(--text-muted);padding:1rem">No high-confidence predictions today (confidence ≥ 55%). Run the prediction pipeline and try again.</div>`;
    return;
  }

  body.innerHTML = `
    <div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(320px,1fr));gap:12px;padding:8px">
      ${recs.map((r, i) => {
        const upside   = r.entryPrice ? ((r.target - r.entryPrice) / r.entryPrice * 100).toFixed(1) : '—';
        const downside = r.entryPrice ? ((r.entryPrice - r.stopLoss) / r.entryPrice * 100).toFixed(1) : '—';
        const confColor = r.confidence >= 70 ? 'var(--positive)' : r.confidence >= 60 ? 'var(--accent)' : 'var(--text-muted)';
        const fmtPrice = v => v != null ? `₹${Number(v).toLocaleString('en-IN', {minimumFractionDigits:2, maximumFractionDigits:2})}` : '—';
        return `<div style="background:rgba(255,255,255,0.03);border:1px solid var(--border);border-radius:8px;padding:14px;position:relative">
          <div style="display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:10px">
            <div>
              <span style="font-family:var(--font-mono);font-size:1rem;font-weight:700;color:var(--text-primary)">${r.symbol}</span>
              <span class="chip" style="margin-left:8px;font-size:0.65rem">${r.sector || '—'}</span>
            </div>
            <span style="background:rgba(240,240,242,0.12);border:1px solid rgba(240,240,242,0.3);color:var(--positive);padding:2px 8px;border-radius:4px;font-size:0.68rem;font-family:var(--font-mono)">TRADE #${i+1}</span>
          </div>

          <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:8px;margin-bottom:10px;font-family:var(--font-mono)">
            <div style="text-align:center;background:rgba(255,255,255,0.04);border-radius:6px;padding:8px">
              <div style="font-size:0.6rem;color:var(--text-muted);margin-bottom:2px">ENTRY</div>
              <div style="font-size:0.95rem;font-weight:700">${fmtPrice(r.entryPrice)}</div>
              <div style="font-size:0.65rem;color:var(--text-muted)">${r.priceDate || 'latest'}</div>
            </div>
            <div style="text-align:center;background:rgba(154,154,159,0.08);border:1px solid rgba(154,154,159,0.2);border-radius:6px;padding:8px">
              <div style="font-size:0.6rem;color:var(--negative);margin-bottom:2px">STOP LOSS</div>
              <div style="font-size:0.95rem;font-weight:700;color:var(--negative)">${fmtPrice(r.stopLoss)}</div>
              <div style="font-size:0.65rem;color:var(--negative)">−${downside}%</div>
            </div>
            <div style="text-align:center;background:rgba(240,240,242,0.08);border:1px solid rgba(240,240,242,0.2);border-radius:6px;padding:8px">
              <div style="font-size:0.6rem;color:var(--positive);margin-bottom:2px">TARGET</div>
              <div style="font-size:0.95rem;font-weight:700;color:var(--positive)">${fmtPrice(r.target)}</div>
              <div style="font-size:0.65rem;color:var(--positive)">+${upside}%</div>
            </div>
          </div>

          <div style="display:flex;justify-content:space-between;font-size:0.7rem;font-family:var(--font-mono);padding:6px 0;border-top:1px solid rgba(255,255,255,0.06)">
            <span>Confidence <b style="color:${confColor}">${r.confidence.toFixed(0)}%</b></span>
            <span>R:R <b style="color:${r.rrRatio >= 1.5 ? 'var(--positive)' : 'var(--negative)'}">${r.rrRatio.toFixed(1)}x</b></span>
            <span>Position <b style="color:var(--accent)">${r.positionSizePct}%</b></span>
            <span>Exp return <b style="color:var(--positive)">+${r.expectedReturn.toFixed(1)}%</b></span>
          </div>

          ${r.strategyName ? `<div style="margin-top:6px;font-size:0.65rem;color:var(--text-muted);font-family:var(--font-mono)">Algo: ${r.strategyName}</div>` : ''}
        </div>`;
      }).join('')}
    </div>
    <div style="padding:8px 16px;font-size:0.68rem;color:var(--text-muted);font-family:var(--font-mono);border-top:1px solid var(--border)">
      ⚠ These are ML predictions for paper trading reference only. Entry/stop/target calculated from backtest strategy DSL. Prices as of ${recs[0]?.priceDate || 'last close'}. Always verify with current market data before placing real trades.
    </div>
  `;
}


// ═══════════════════════════════════════════════════════════════
// ═══════════════════════════════════════════════════════════════
// META-LEARNING CONTROL CENTER
// ═══════════════════════════════════════════════════════════════

async function loadMetaLearningState() {
  const content = document.getElementById('meta-content');
  if (!content) return;
  content.innerHTML = '<div style="color:var(--muted);font-size:13px;padding:8px">Loading meta-learning state…</div>';

  try {
    const [metaResp, retrainResp] = await Promise.all([
      Api.metaState().catch(() => null),
      Api.modelRetrainStatus().catch(() => null),
    ]);

    const ms = metaResp?.meta_state || null;
    const rt = retrainResp || null;

    content.innerHTML = renderMetaLearningPanel(ms, rt);
  } catch (e) {
    content.innerHTML = `<div style="color:var(--negative);padding:8px">Error: ${e.message}</div>`;
  }
}

function renderMetaLearningPanel(ms, rt) {
  const fmtPct = v => v != null ? `${(v * 100).toFixed(1)}%` : '—';
  const fmtN   = v => v != null ? v.toFixed(2) : '—';
  const badge  = (label, color) =>
    `<span style="background:${color};color:#fff;padding:2px 8px;border-radius:4px;font-size:11px;margin-left:4px">${label}</span>`;

  let html = '<div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:16px;padding:4px">';

  // ── Panel 1: Family Weight Adjustments ──────────────────────
  html += '<div>';
  html += '<div style="font-weight:600;font-size:13px;color:var(--accent);margin-bottom:10px">◆ Family Weight Adjustments</div>';
  if (ms?.family_weights) {
    // Must mirror backend/strategies/strategy_generator.py::_FAMILY_WEIGHTS —
    // update both together if family weights change.
    // LOCKSTEP (pitfall C16): must mirror strategy_generator._FAMILY_WEIGHTS
    // and meta_learner._RAW_DEFAULT_FAMILY_WEIGHTS — update all three together.
    // 2026-07-14 evidence rebalance: MR families floored, week52_high_momentum
    // (expectancy-gated) + turn_of_month added; 2026-07-14c: vol_managed_momentum
    // + tstat_trend added.
    const defaults = {
      post_earnings_drift: 0.07, momentum_trend: 0.07, mean_reversion_quality: 0.02,
      event_catalyst: 0.06, regime_dca_timing: 0.04, rotation_monitor: 0.06,
      regime_pullback_v2: 0.02,
      quality_momentum: 0.08, institutional_flow: 0.04, rl_momentum: 0.06,
      relative_strength: 0.08, breadth_momentum: 0.06, long_hold_momentum: 0.09,
      week52_high_momentum: 0.10, turn_of_month: 0.04,
      vol_managed_momentum: 0.06, tstat_trend: 0.05,
      // 2026-07-15c: 5 evidence-based additions
      breakout_volume_confirmed: 0.05, dual_momentum: 0.05, fii_flow_momentum: 0.04,
      adx_trend_vol_filtered: 0.05, accumulation_momentum: 0.04,
    };
    html += '<table style="width:100%;font-size:12px;border-collapse:collapse">';
    html += '<tr><th style="text-align:left;color:var(--muted);padding:2px 4px">Family</th><th style="color:var(--muted);padding:2px 4px">Default</th><th style="color:var(--muted);padding:2px 4px">Current</th><th style="color:var(--muted);padding:2px 4px">Δ</th></tr>';
    Object.entries(ms.family_weights)
      .sort((a, b) => b[1] - a[1])
      .forEach(([fam, w]) => {
        const def = defaults[fam] || 0.05;
        const delta = w - def;
        const color = Math.abs(delta) < 0.01 ? 'var(--text)' : delta > 0 ? 'var(--positive)' : 'var(--negative)';
        const arrow = Math.abs(delta) < 0.005 ? '' : delta > 0 ? ' ▲' : ' ▼';
        html += `<tr>
          <td style="padding:2px 4px;color:var(--text)">${fam}</td>
          <td style="padding:2px 4px;text-align:center;color:var(--muted)">${fmtPct(def)}</td>
          <td style="padding:2px 4px;text-align:center;font-weight:600">${fmtPct(w)}</td>
          <td style="padding:2px 4px;text-align:center;color:${color}">${delta > 0 ? '+' : ''}${(delta * 100).toFixed(1)}%${arrow}</td>
        </tr>`;
      });
    html += '</table>';
  } else {
    html += '<div style="color:var(--muted);font-size:12px">No meta-state available. Click "Run Meta-Learn".</div>';
  }
  html += '</div>';

  // ── Panel 2: Signal Summary ──────────────────────────────────
  html += '<div>';
  html += '<div style="font-weight:600;font-size:13px;color:var(--accent);margin-bottom:10px">◈ Learning Signals</div>';

  if (ms) {
    const items = [
      ['Regime', ms.current_regime || '—', 'var(--text)'],
      ['Confidence Floor', ms.current_conf_floor != null ? `${ms.current_conf_floor}%` : '—', ms.current_conf_floor > 60 ? 'var(--warning)' : 'var(--positive)'],
      ['Graveyard Algos', ms.graveyard_total != null ? ms.graveyard_total : '—', 'var(--muted)'],
      ['Short-Hold Deaths', ms.short_hold_deaths != null ? ms.short_hold_deaths : '—', ms.short_hold_deaths > 10 ? 'var(--negative)' : 'var(--muted)'],
      ['Top Alive Algos', ms.top_alive_count != null ? ms.top_alive_count : '—', 'var(--positive)'],
      ['Top Mutation Op', ms.ranked_mutation_ops?.[0] || '—', 'var(--accent)'],
    ];
    items.forEach(([label, val, color]) => {
      html += `<div style="display:flex;justify-content:space-between;padding:4px 0;border-bottom:1px solid rgba(255,255,255,0.04)">
        <span style="color:var(--muted);font-size:12px">${label}</span>
        <span style="font-size:12px;font-weight:600;color:${color}">${val}</span>
      </div>`;
    });

    // Bad features
    if (ms.bad_features?.length) {
      html += `<div style="margin-top:10px">
        <div style="color:var(--muted);font-size:11px;margin-bottom:4px">Bad Features (avoided in generation)</div>
        <div style="display:flex;flex-wrap:wrap;gap:4px">
          ${ms.bad_features.map(f =>
            `<span style="background:rgba(154,154,159,0.15);color:var(--negative);border:1px solid rgba(154,154,159,0.3);border-radius:3px;padding:1px 6px;font-size:11px">${f}</span>`
          ).join('')}
        </div>
      </div>`;
    }

    // Prediction accuracy by regime
    if (ms.prediction_regime_acc && Object.keys(ms.prediction_regime_acc).length) {
      html += `<div style="margin-top:10px">
        <div style="color:var(--muted);font-size:11px;margin-bottom:4px">Prediction Win Rate by Regime</div>`;
      Object.entries(ms.prediction_regime_acc).forEach(([reg, wr]) => {
        const barColor = wr >= 60 ? 'var(--positive)' : wr >= 50 ? 'var(--warning)' : 'var(--negative)';
        html += `<div style="display:flex;align-items:center;gap:8px;padding:2px 0">
          <span style="width:70px;font-size:11px;color:var(--muted)">${reg}</span>
          <div style="flex:1;background:rgba(255,255,255,0.06);border-radius:2px;height:6px">
            <div style="width:${Math.min(wr, 100)}%;background:${barColor};height:6px;border-radius:2px"></div>
          </div>
          <span style="font-size:11px;color:${barColor};width:35px;text-align:right">${wr}%</span>
        </div>`;
      });
      html += '</div>';
    }
  } else {
    html += '<div style="color:var(--muted);font-size:12px">No data yet.</div>';
  }
  html += '</div>';

  // ── Panel 3: Model Self-Improvement ─────────────────────────
  html += '<div>';
  html += '<div style="font-weight:600;font-size:13px;color:var(--accent);margin-bottom:10px">⬡ Model Self-Improvement</div>';
  if (rt) {
    const needsRetrain = rt.needs_retraining;
    const acc  = rt.accuracy_check || {};
    const stal = rt.staleness_check || {};

    html += `<div style="background:${needsRetrain ? 'rgba(154,154,159,0.1)' : 'rgba(240,240,242,0.08)'};border:1px solid ${needsRetrain ? 'rgba(154,154,159,0.3)' : 'rgba(240,240,242,0.2)'};border-radius:6px;padding:10px;margin-bottom:12px">
      <div style="font-size:13px;font-weight:600;color:${needsRetrain ? 'var(--negative)' : 'var(--positive)'}">
        ${needsRetrain ? '⚠ Retraining Recommended' : '✓ Model Healthy'}
      </div>
      <div style="font-size:11px;color:var(--muted);margin-top:4px">${acc.reason || 'No data'}</div>
    </div>`;

    const mItems = [
      ['Win Rate (30d)', acc.win_rate != null ? `${acc.win_rate.toFixed(1)}%` : '—', acc.win_rate != null ? (acc.win_rate >= 55 ? 'var(--positive)' : acc.win_rate >= 50 ? 'var(--warning)' : 'var(--negative)') : 'var(--muted)'],
      ['Predictions Evaluated', acc.evaluated != null ? acc.evaluated : '—', 'var(--text)'],
      ['Model Age', stal.age_days != null ? `${stal.age_days} days` : '—', stal.stale ? 'var(--negative)' : 'var(--muted)'],
      ['Model Name', stal.model_name || '—', 'var(--accent)'],
      ['Last Retrained', rt.last_retrained_at ? rt.last_retrained_at.split('.')[0] : 'Never', 'var(--muted)'],
    ];
    mItems.forEach(([label, val, color]) => {
      html += `<div style="display:flex;justify-content:space-between;padding:3px 0;border-bottom:1px solid rgba(255,255,255,0.04)">
        <span style="color:var(--muted);font-size:12px">${label}</span>
        <span style="font-size:12px;font-weight:600;color:${color}">${val}</span>
      </div>`;
    });

    // Per-regime win rate breakdown
    if (acc.regime_win_rates && Object.keys(acc.regime_win_rates).length) {
      html += `<div style="margin-top:10px">
        <div style="color:var(--muted);font-size:11px;margin-bottom:4px">Win Rate by Regime (30d)</div>`;
      Object.entries(acc.regime_win_rates).forEach(([reg, wr]) => {
        const c = wr >= 55 ? 'var(--positive)' : wr >= 50 ? 'var(--warning)' : 'var(--negative)';
        html += `<div style="display:flex;justify-content:space-between;font-size:11px;padding:2px 0">
          <span style="color:var(--muted)">${reg}</span>
          <span style="color:${c};font-weight:600">${wr}%</span>
        </div>`;
      });
      html += '</div>';
    }
  } else {
    html += '<div style="color:var(--muted);font-size:12px">Click "Check Model" to run accuracy check.</div>';
  }
  html += '</div>';

  html += '</div>'; // end grid

  // Mutation op stats table
  if (ms?.mutation_op_stats && Object.keys(ms.mutation_op_stats).length) {
    const ranked = ms.ranked_mutation_ops || Object.keys(ms.mutation_op_stats);
    html += `<div style="margin-top:16px">
      <div style="font-weight:600;font-size:13px;color:var(--accent);margin-bottom:8px">Mutation Operation Performance (60 days)</div>
      <table style="width:100%;font-size:12px;border-collapse:collapse">
        <tr>
          <th style="text-align:left;color:var(--muted);padding:3px 8px">Operation</th>
          <th style="color:var(--muted);padding:3px 8px">Total</th>
          <th style="color:var(--muted);padding:3px 8px">Positive %</th>
          <th style="color:var(--muted);padding:3px 8px">Avg Δ Fitness</th>
          <th style="color:var(--muted);padding:3px 8px">Rank</th>
        </tr>`;
    ranked.forEach((op, idx) => {
      const s = ms.mutation_op_stats[op] || {};
      const deltaColor = (s.avg_delta || 0) > 0 ? 'var(--positive)' : (s.avg_delta || 0) < 0 ? 'var(--negative)' : 'var(--muted)';
      const rankLabel = idx === 0 ? '🥇' : idx === 1 ? '🥈' : idx === 2 ? '🥉' : `#${idx + 1}`;
      html += `<tr style="border-top:1px solid rgba(255,255,255,0.04)">
        <td style="padding:4px 8px;color:var(--text);font-family:monospace">${op}</td>
        <td style="padding:4px 8px;text-align:center;color:var(--muted)">${s.total || 0}</td>
        <td style="padding:4px 8px;text-align:center">${s.positive_pct != null ? s.positive_pct + '%' : '—'}</td>
        <td style="padding:4px 8px;text-align:center;color:${deltaColor};font-weight:600">${s.avg_delta != null ? (s.avg_delta >= 0 ? '+' : '') + s.avg_delta.toFixed(3) : '—'}</td>
        <td style="padding:4px 8px;text-align:center">${rankLabel}</td>
      </tr>`;
    });
    html += '</table></div>';
  }

  html += `<div style="margin-top:12px;font-size:11px;color:var(--muted)">Last computed: ${ms?.computed_at || 'never'} · Regime: ${ms?.current_regime || '—'}</div>`;
  return html;
}

async function triggerMetaLearning() {
  const content = document.getElementById('meta-content');
  if (content) content.innerHTML = '<div style="color:var(--muted);padding:8px">Running meta-learning cycle… this analyses graveyard failures, evolution history, live trades, and model accuracy.</div>';

  try {
    const result = await Api.runMetaLearning();
    if (result?.status === 'error') {
      if (content) content.innerHTML = `<div style="color:var(--negative);padding:8px">Error: ${result.error}</div>`;
      return;
    }

    const summary = [
      `Insights written: ${result.insights_written ?? '—'}`,
      `Confidence floor: ${result.conf_floor ?? '—'}%`,
      `Top mutation op: ${result.top_mutation_op ?? '—'}`,
      `Bad features: ${result.bad_features?.length ?? 0}`,
      `Regime: ${result.regime ?? '—'}`,
    ].join(' · ');

    if (content) content.innerHTML = `<div style="color:var(--positive);padding:8px 0;margin-bottom:8px">✓ Meta-learning complete — ${summary}</div>`;
    // Reload full state
    await loadMetaLearningState();
  } catch (e) {
    if (content) content.innerHTML = `<div style="color:var(--negative);padding:8px">Error: ${e.message}</div>`;
  }
}

async function checkModelRetrain() {
  const content = document.getElementById('meta-content');
  if (content) content.innerHTML = '<div style="color:var(--muted);padding:8px">Checking model accuracy and staleness…</div>';

  try {
    const [metaResp, retrainResp] = await Promise.all([
      Api.metaState().catch(() => null),
      Api.modelRetrainStatus().catch(() => null),
    ]);
    const ms = metaResp?.meta_state || null;
    const rt = retrainResp || null;

    if (content) content.innerHTML = renderMetaLearningPanel(ms, rt);
  } catch (e) {
    if (content) content.innerHTML = `<div style="color:var(--negative);padding:8px">Error: ${e.message}</div>`;
  }
}

async function forceModelRetrain() {
  if (!confirm('Force full model retraining? This will retrain LightGBM, XGBoost, and CatBoost on all historical data. It may take several minutes.')) return;

  const content = document.getElementById('meta-content');
  if (content) content.innerHTML = '<div style="color:var(--warning);padding:8px">Retraining models… this may take several minutes. Do not close the app.</div>';

  try {
    const result = await Api.triggerModelRetrain(true);
    if (result?.result?.status === 'ok' || result?.retrained) {
      const r = result.result || {};
      if (content) content.innerHTML = `
        <div style="color:var(--positive);padding:8px 0;margin-bottom:12px">
          ✓ Model retrained: ${r.model || 'N/A'} v${r.version || '?'} — accuracy=${r.accuracy?.toFixed(3) || '—'} — elapsed ${r.elapsed_sec || '?'}s
        </div>`;
    } else if (result?.result?.status === 'unavailable') {
      if (content) content.innerHTML = `
        <div style="color:var(--warning);padding:8px">
          ⚠ Training pipeline unavailable: ${result.result.reason || 'ML dependencies may not be installed or training data is insufficient.'}
        </div>`;
    } else {
      const reason = result?.result?.reason || result?.result?.status || JSON.stringify(result);
      if (content) content.innerHTML = `<div style="color:var(--negative);padding:8px">Retraining failed: ${reason}</div>`;
    }
    // Reload full state after
    await loadMetaLearningState();
  } catch (e) {
    if (content) content.innerHTML = `<div style="color:var(--negative);padding:8px">Error: ${e.message}</div>`;
  }
}

// ═══════════════════════════════════════════════════════════════
// EQUITY SCREENER
// ═══════════════════════════════════════════════════════════════

// ══════════════════════════════════════════════════════════════
