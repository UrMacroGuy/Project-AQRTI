// ui/pages/agents.js - split from app.js (ARCH-5), see CHANGELOG
// RESEARCH OPERATIONS CENTER — Phase 7
// ═══════════════════════════════════════════════════════════════

async function hydrateResearchOps() {
  const el = id => document.getElementById(id);
  let agentData    = await Api.agents();
  let briefData    = await Api.todayBrief();
  let findingsData = await Api.findingsSummary(7);
  let msgData      = await Api.agentMessages(2);
  let perfData     = await Api.agentPerformance(30);

  if (!agentData) {
    agentData = { agents: [] };
    setDataPoint('roc-kpi-agent-status', 'BACKEND OFFLINE', 'agents');
  }

  // ── KPIs ──────────────────────────────────────────────────────
  const agents = agentData?.agents || [];
  const errored = agents.filter(a => a.status === 'error').length;
  setDataPoint('roc-kpi-agents', agents.length, 'agents');
  setDataPoint('roc-kpi-agent-status', errored ? `${errored} Errors` : 'All Nominal', 'agents');
  setDataPoint('roc-kpi-findings', findingsData?.total ?? '—', 'agents');
  setDataPoint('roc-kpi-critical', `${(findingsData?.by_urgency?.critical || 0)} Critical`, 'agents');
  setDataPoint('roc-kpi-brief-status', briefData ? 'ISSUED' : 'PENDING', 'agents');
  setDataPoint('roc-kpi-brief-date', briefData?.brief_date || '—', 'agents');
  setDataPoint('roc-kpi-messages', (msgData?.messages || []).length, 'agents');

  // ── Daily Brief ───────────────────────────────────────────────
  const briefBody = el('roc-brief-body');
  if (briefBody && briefData) {
    const tag = el('roc-brief-date-tag');
    if (tag) {
      const briefCreated = briefData.created_at || briefData.generated_at || briefData.brief_date;
      let staleLabel = '';
      if (briefCreated) {
        const ageMs  = Date.now() - new Date(briefCreated).getTime();
        const ageH   = ageMs / 3600000;
        if (ageH > 4) staleLabel = ` ⚠ ${ageH >= 24 ? Math.floor(ageH/24) + 'd' : Math.round(ageH) + 'h'} ago`;
      }
      tag.textContent = (briefData.brief_date || '—') + staleLabel;
      if (staleLabel) tag.style.color = 'var(--amber-dim, #cc6600)';
    }

    const _filterStrategyNoise = items => (items || []).filter(i =>
      !i.includes('Critical Decay') && !i.includes('strategy_research:') &&
      !i.includes('cro: Daily Brief') && !i.includes('fitness=')
    );

    const sec = (label, items) => {
      const clean = _filterStrategyNoise(items);
      if (!clean.length) return '';
      return `<div style="margin-bottom:10px"><div style="font-size:0.65rem;color:var(--text-muted);letter-spacing:0.08em;margin-bottom:4px">${label}</div>`
        + clean.map(i => `<div style="padding:3px 0;border-bottom:1px solid var(--border-faint);font-size:0.72rem">${i}</div>`).join('') + '</div>';
    };

    briefBody.innerHTML = `
      <div style="background:var(--bg-raised);border:1px solid var(--border-faint);border-radius:6px;padding:12px;margin-bottom:10px">
        <div style="font-size:0.72rem;color:var(--text-secondary);margin-bottom:6px">${briefData.market_summary || ''}</div>
        <div style="display:flex;gap:12px;font-size:0.65rem">
          <span style="color:var(--accent)">Regime: ${briefData.regime_at}</span>
          <span style="color:var(--text-muted)">Score: ${briefData.knowledge_score?.toFixed(1) ?? '—'}</span>
        </div>
      </div>
      ${sec('TOP OPPORTUNITIES', briefData.top_opportunities)}
      ${sec('MAJOR RISKS', briefData.major_risks)}
    `;
  } else if (briefBody) {
    briefBody.innerHTML = '<div style="color:var(--text-muted)">No brief generated today. Click Generate.</div>';
  }

  // ── Agent Health Table ────────────────────────────────────────
  const agentTableBody = el('roc-agent-table-body');
  if (agentTableBody) {
    const STATUS_COLORS = { idle: 'positive', running: 'accent', error: 'negative', disabled: '' };
    agentTableBody.innerHTML = agents.map(a => {
      const lastRun = a.last_run_at ? new Date(a.last_run_at).toLocaleTimeString() : '—';
      const statusClass = STATUS_COLORS[a.status] || '';
      return `<tr>
        <td style="font-size:0.72rem">${a.name}</td>
        <td><span class="chip">${a.agent_type}</span></td>
        <td class="${statusClass}" style="font-size:0.68rem">${(a.status||'').toUpperCase()}</td>
        <td style="color:var(--text-muted);font-size:0.68rem">${lastRun}</td>
        <td>${a.run_count || 0}</td>
        <td class="${(a.error_count||0) > 0 ? 'negative' : ''}">${a.error_count || 0}</td>
      </tr>`;
    }).join('') || '<tr><td colspan="6" style="color:var(--text-muted);text-align:center">No agents registered</td></tr>';
  }

  // ── Research Findings Table ───────────────────────────────────
  const findingsBody = el('roc-findings-body');
  if (findingsBody) {
    const allFindings = [...(findingsData?.critical || []), ...(findingsData?.high || [])];
    const displayFindings = allFindings;
    const URGENCY_CLASS = { critical: 'negative', high: 'negative', normal: 'neutral', low: '' };
    findingsBody.innerHTML = displayFindings.slice(0, 15).map(f => `<tr>
      <td><span class="chip">${f.agent_id?.replace('_research','') || '—'}</span></td>
      <td class="${URGENCY_CLASS[f.urgency] || ''}" style="font-size:0.68rem">${(f.urgency||'').toUpperCase()}</td>
      <td style="font-size:0.72rem">${f.title || f.description || '—'}</td>
      <td style="font-size:0.68rem;color:var(--text-muted)">${f.implication || '—'}</td>
      <td style="color:var(--text-muted);font-size:0.68rem">${f.finding_date || f.date || '—'}</td>
    </tr>`).join('') || '<tr><td colspan="5" style="color:var(--text-muted);text-align:center">No findings today</td></tr>';
  }

  // ── Messages ──────────────────────────────────────────────────
  const msgBody = el('roc-messages-body');
  if (msgBody) {
    const msgs = (msgData?.messages || []).slice(0, 10);
    const MTYPE_COLOR = { alert: '#ff3333', finding: '#00aaff', broadcast: '#00cc66', request: '#ffcc00', response: '#666666' };
    msgBody.innerHTML = msgs.map(m => `
      <div style="display:flex;gap:8px;align-items:flex-start;padding:6px 0;border-bottom:1px solid var(--border-faint)">
        <span style="color:${MTYPE_COLOR[m.message_type]||'#94a3b8'};font-size:0.65rem;font-family:var(--font-mono);white-space:nowrap;padding-top:1px">${(m.message_type||'').toUpperCase()}</span>
        <div style="flex:1;min-width:0">
          <div style="font-size:0.72rem;font-weight:500">${m.subject || '—'}</div>
          <div style="font-size:0.68rem;color:var(--text-muted)">${m.from_agent} → ${m.to_agent}</div>
        </div>
      </div>
    `).join('') || '<div style="color:var(--text-muted)">No messages</div>';
  }

  // ── Action Items — with actionable Retire buttons ────────────
  const actBody = el('roc-actions-body');
  if (actBody) {
    const rawItems = Array.isArray(briefData?.action_items) ? briefData.action_items : [];

    // Pull decayed strategies directly from leaderboard (fitness < retire threshold)
    let decayedStrategies = [];
    try {
      const lb = await Api.strategyLeaderboard(100);
      decayedStrategies = (lb?.leaderboard || []).filter(s =>
        (s.fitness_score || 0) < 8 && s.status !== 'retired' && s.status !== 'archived'
      );
    } catch (_) {}

    // Show "Retire All Bad" button only when there are decayed strategies
    const retireAllBtn = document.getElementById('btn-retire-all');
    if (retireAllBtn) retireAllBtn.style.display = decayedStrategies.length ? 'inline-block' : 'none';

    // Render decayed strategies as actionable cards first
    const decayedHTML = decayedStrategies.slice(0, 10).map(s => `
      <div data-strategy-card data-strategy-id="${s.strategy_id}"
        style="display:flex;align-items:center;gap:8px;padding:8px 10px;margin-bottom:6px;border-radius:4px;
        background:rgba(239,68,68,0.07);border:1px solid rgba(239,68,68,0.25)">
        <span style="color:#f87171;font-size:0.65rem;font-weight:700;white-space:nowrap">[URGENT]</span>
        <div style="flex:1;min-width:0">
          <div style="font-size:0.73rem;font-weight:600;color:#fca5a5">${s.name || s.strategy_id}</div>
          <div style="font-size:0.62rem;color:var(--accent);opacity:0.7">${s.strategy_id}</div>
          <div style="font-size:0.65rem;color:var(--text-muted)">
            Fitness: <span style="color:#f87171">${(s.fitness_score||0).toFixed(1)}</span>
            &nbsp;|&nbsp; Trades: ${s.trade_count||0}
            &nbsp;|&nbsp; Sharpe: ${(s.sharpe||0).toFixed(2)}
            &nbsp;|&nbsp; ${s.status}
          </div>
        </div>
        <button class="panel-action-btn" style="background:rgba(239,68,68,0.18);border-color:rgba(239,68,68,0.45);color:#f87171;white-space:nowrap;flex-shrink:0"
          onclick="retireSingleStrategy('${s.strategy_id}', this)">Retire</button>
      </div>`).join('');

    // Render non-strategy action items (filter out Critical Decay noise)
    const otherHTML = rawItems
      .filter(item => !item.includes('Critical Decay') && !item.includes('strategy_research:'))
      .slice(0, 6)
      .map(item => {
        const isUrgent = item.includes('URGENT') || item.includes('🔴') || item.includes('[CRITICAL]');
        const isWarn   = item.includes('🟡') || item.includes('REVIEW');
        return `<div style="padding:7px 10px;margin-bottom:5px;border-radius:4px;font-size:0.73rem;
          background:${isUrgent ? 'rgba(239,68,68,0.06)' : isWarn ? 'rgba(251,191,36,0.05)' : 'rgba(255,255,255,0.03)'};
          border:1px solid ${isUrgent ? 'rgba(239,68,68,0.18)' : isWarn ? 'rgba(251,191,36,0.15)' : 'rgba(255,255,255,0.07)'}">
          ${item.replace('[URGENT]:', '').replace('[CRITICAL]:', '').replace('cro: ', '').trim()}
        </div>`;
      }).join('');

    actBody.innerHTML = decayedHTML + otherHTML ||
      '<div style="color:var(--positive);font-size:0.8rem;padding:8px">All clear — no action required</div>';
  }

  // ── Agent Performance Chart ───────────────────────────────────
  if (perfData && perfData.length) {
    ChartRegistry.create('rocAgentPerfChart', {
      type: 'bar',
      data: {
        labels: perfData.map(p => p.agent_id.replace('_research','').replace('_','').toUpperCase()),
        datasets: [
          { label: 'Tasks', data: perfData.map(p => p.total_tasks || 0), backgroundColor: 'rgba(0,170,255,0.6)' },
          { label: 'Success %', data: perfData.map(p => p.success_rate || 0), backgroundColor: 'rgba(52,211,153,0.5)', yAxisID: 'y1' },
        ],
      },
      options: {
        responsive: true, maintainAspectRatio: false,
        plugins: { legend: { labels: { font: { size: 10 } } } },
        scales: {
          x: { grid: { color: 'rgba(255,255,255,0.05)' }, ticks: { font: { size: 9 } } },
          y:  { grid: { color: 'rgba(255,255,255,0.05)' } },
          y1: { position: 'right', min: 0, max: 100, grid: { display: false } },
        },
      },
    });
  }
}

// ═══════════════════════════════════════════════════════════════
// ACTION ITEMS — RETIRE STRATEGIES
// ═══════════════════════════════════════════════════════════════

async function retireSingleStrategy(strategyId, btn) {
  if (btn) { btn.disabled = true; btn.textContent = 'Retiring…'; }
  try {
    const res = await Api.retireStrategy(strategyId, 'low_fitness_manual');
    if (res?.success || res?.status === 'ok' || res?.strategy_id) {
      const card = btn ? btn.closest('[data-strategy-card]') : null;
      if (card) card.remove();
      const remaining = document.querySelectorAll('[data-strategy-card]');
      const allBtn = document.getElementById('btn-retire-all');
      if (allBtn && remaining.length === 0) allBtn.style.display = 'none';
    } else {
      if (btn) { btn.disabled = false; btn.textContent = 'Retire'; }
      alert('Retire failed: ' + (res?.error || 'unknown error'));
    }
  } catch (e) {
    if (btn) { btn.disabled = false; btn.textContent = 'Retire'; }
  }
}

async function retireAllDecayedStrategies() {
  const retireAllBtn = document.getElementById('btn-retire-all');
  const cards = [...document.querySelectorAll('[data-strategy-card]')];
  if (!cards.length) return;
  if (!confirm(`Retire ${cards.length} low-fitness strategies? This cannot be undone.`)) return;
  if (retireAllBtn) { retireAllBtn.disabled = true; retireAllBtn.textContent = `Retiring ${cards.length}…`; }
  for (const card of cards) {
    const sid = card.getAttribute('data-strategy-id');
    const btn = card.querySelector('button');
    if (sid) { await retireSingleStrategy(sid, btn); await new Promise(r => setTimeout(r, 120)); }
  }
  if (retireAllBtn) { retireAllBtn.disabled = false; retireAllBtn.textContent = 'Retire All Bad'; retireAllBtn.style.display = 'none'; }
}

// ═══════════════════════════════════════════════════════════════
// LIVE MARKET NEWS FEED — auto-refreshes every 5 min
// ═══════════════════════════════════════════════════════════════

let _newsRefreshTimer = null;

async function loadLiveNewsFeed() {
  const feed = document.getElementById('live-news-feed');
  const lastUpdate = document.getElementById('news-feed-last-update');
  if (!feed) return;
  try {
    const data = await Api.news({ limit: 30, sort: 'timestamp' });
    const articles = Array.isArray(data) ? data : (data?.articles || data?.news || []);
    if (!articles.length) {
      feed.innerHTML = '<div style="color:var(--text-muted);padding:8px">No news available right now</div>';
      return;
    }
    const SENT_COLOR = { positive: '#34d399', negative: '#f87171', neutral: '#94a3b8' };
    const _age = ts => {
      if (!ts) return '';
      const diff = Date.now() - new Date(ts).getTime();
      const mins = Math.floor(diff / 60000);
      if (mins < 60) return `${mins}m ago`;
      const hrs = Math.floor(mins / 60);
      if (hrs < 24) return `${hrs}h ago`;
      return `${Math.floor(hrs/24)}d ago`;
    };
    feed.innerHTML = articles.map(a => {
      const sent = (a.sentiment || 'neutral').toLowerCase();
      const sentColor = SENT_COLOR[sent] || '#94a3b8';
      const score = a.impactScore || a.importanceScore || 0;
      const source = (a.source || '').replace(/_/g, ' ').toUpperCase();
      const company = a.company ? `<span style="color:var(--accent);font-weight:600">${a.company}</span> · ` : '';
      const sector = a.sector ? `<span style="color:var(--text-muted)">${a.sector}</span> · ` : '';
      const summary = a.summary && a.summary !== a.headline
        ? `<div style="font-size:0.68rem;color:var(--text-muted);line-height:1.4;margin-bottom:4px">${a.summary.slice(0,200)}${a.summary.length>200?'…':''}</div>` : '';
      return `<div style="padding:10px 0;border-bottom:1px solid var(--border-faint);display:flex;gap:10px;align-items:flex-start">
        <div style="flex-shrink:0;width:3px;border-radius:2px;background:${sentColor};align-self:stretch;min-height:36px"></div>
        <div style="flex:1;min-width:0">
          <div style="font-size:0.76rem;font-weight:600;line-height:1.4;margin-bottom:3px">${a.headline || '—'}</div>
          ${summary}
          <div style="display:flex;flex-wrap:wrap;gap:6px;align-items:center;font-size:0.63rem">
            ${company}${sector}<span style="color:${sentColor};text-transform:uppercase;font-weight:700">${sent}</span>
            ${score ? `<span style="color:var(--text-muted)">Impact: ${score.toFixed(0)}</span>` : ''}
            <span style="color:var(--text-muted)">${source}</span>
            <span style="color:var(--text-muted);margin-left:auto">${_age(a.timestamp)}</span>
          </div>
        </div>
      </div>`;
    }).join('');
    if (lastUpdate) {
      const now = new Date();
      lastUpdate.textContent = `Updated ${now.toLocaleTimeString([], {hour:'2-digit',minute:'2-digit'})}`;
    }
  } catch (e) {
    if (feed) feed.innerHTML = '<div style="color:var(--text-muted);padding:8px">Failed to load news</div>';
  }
}

function startNewsFeedAutoRefresh() {
  if (_newsRefreshTimer) clearInterval(_newsRefreshTimer);
  loadLiveNewsFeed();
  _newsRefreshTimer = setInterval(loadLiveNewsFeed, 5 * 60 * 1000);
}

