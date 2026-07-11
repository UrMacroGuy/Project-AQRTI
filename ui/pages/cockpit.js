// ui/pages/cockpit.js — Portfolio Cockpit, the new default landing page.
// One-glance view of the 9-symbol curated NSE universe plus VOO/QQQ (US,
// monitor-only — price feed pending) — live price, tier badge, latest
// research synthesis snippet with source links, and current algo signal
// (only from promoted-template signals; honestly "No active signal" until
// one exists). The monthly SIP tilt panel shows an honest "not yet
// available" state until the regime_dca_timing template (§4 of the
// re-architecture plan) is built and validated. Suggestions only — never
// advice, never auto-executed. See CLAUDE.md Personal Portfolio module rules.

const COCKPIT_TIER1 = ['BEL', 'HDFCBANK', 'NTPC'];               // owned
const COCKPIT_TIER2 = ['ICICIBANK', 'INFY', 'CDSL', 'DRREDDY', 'LT', 'HAL']; // bench
const COCKPIT_US    = ['VOO', 'QQQ'];                              // tracked, not yet populated
const COCKPIT_UNIVERSE = [...COCKPIT_TIER1, ...COCKPIT_TIER2, ...COCKPIT_US];

function _cockpitEmptyPanel(id, msg) {
  const p = el(id);
  if (p) p.innerHTML = `<div style="grid-column:1/-1;text-align:center;color:var(--text-muted);padding:24px;font-size:0.78rem">${msg}</div>`;
}

async function hydrateCockpit() {
  const grid = el('cockpit-grid');
  if (grid) grid.innerHTML = '<div style="grid-column:1/-1;text-align:center;color:var(--text-muted);padding:24px">Loading…</div>';

  // Note: no ML-prediction fetch here. The retired CatBoost prediction stream
  // is no longer surfaced on the Cockpit (see CLAUDE.md quant bar + §7.0 —
  // signal badges must come only from promoted-template signals, which don't
  // exist yet; the correct empty state is "no active signal", never a stale
  // direction/confidence badge from the old model). Also no /rebalance fetch:
  // the SIP tilt panel below always shows its honest "not yet available"
  // state until regime_dca_timing exists — see the comment further down.
  const [prices, synthesis] = await Promise.all([
    Api.liveStockPrices().catch(() => null),
    Api.researchSynthesisLatest().catch(() => null),
  ]);

  setDataPoint('cockpit-kpi-total', COCKPIT_UNIVERSE.length, 'cockpit');
  setDataPoint('cockpit-kpi-tier1', COCKPIT_TIER1.length, 'cockpit');
  setDataPoint('cockpit-kpi-tier2', COCKPIT_TIER2.length, 'cockpit');
  const updEl = el('cockpit-updated');
  if (updEl) updEl.textContent = `Last refresh: ${new Date().toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit' })}`;

  const priceBySymbol = {};
  (Array.isArray(prices) ? prices : []).forEach(p => { priceBySymbol[p.key || p.symbol] = p; });

  const synthBySymbol = {};
  (synthesis?.synthesis || []).forEach(s => { synthBySymbol[s.symbol] = s; });

  if (!grid) return;

  if (!prices && !synthesis) {
    _cockpitEmptyPanel('cockpit-grid', 'NO DATA — backend offline, could not reach any source for the tracked universe.');
  } else {
    grid.innerHTML = COCKPIT_UNIVERSE.map(sym => {
      const tier = COCKPIT_TIER1.includes(sym) ? 1 : COCKPIT_TIER2.includes(sym) ? 2 : 0;
      const tierBadge = tier === 1
        ? '<span class="badge badge-tier1">TIER 1 · OWNED</span>'
        : tier === 2
          ? '<span class="badge badge-tier2">TIER 2 · BENCH</span>'
          : '<span class="badge badge-monitor">MONITOR-ONLY · PRICE FEED PENDING</span>';

      const px = priceBySymbol[sym];
      // Never show a signal/prediction badge when the price/source state is
      // NO DATA — a confident-looking badge next to an honest "no data" price
      // is misleading (§7.0 item 2). Price and signal render together so
      // that's structurally impossible here.
      const hasPrice = px && px.price != null;
      const priceHTML = hasPrice
        ? `<span style="font-size:1.1rem;font-weight:700">₹${px.price.toLocaleString('en-IN')}</span>
           <span class="${(px.changePct || 0) >= 0 ? 'positive' : 'negative'}" style="font-size:0.75rem;margin-left:6px">${(px.changePct||0) >= 0 ? '+' : ''}${(px.changePct||0).toFixed(2)}%</span>`
        : `<span style="color:var(--text-muted);font-size:0.8rem">NO DATA — source unavailable</span>`;

      const synth = synthBySymbol[sym];
      let synthHTML;
      if (synth) {
        const dirCls = synth.thesis_direction === 'bullish' ? 'positive' : synth.thesis_direction === 'bearish' ? 'negative' : '';
        const catalysts = (synth.key_catalysts || []).slice(0, 2);
        const sources = (synth.source_event_ids || []).length;
        synthHTML = `
          <div style="margin-top:8px;padding-top:8px;border-top:1px solid var(--border)">
            <span class="${dirCls}" style="font-size:0.7rem;font-weight:600;text-transform:uppercase">${synth.thesis_direction}</span>
            <span style="color:var(--text-muted);font-size:0.68rem;margin-left:6px">${synth.synthesis_date}</span>
            ${catalysts.length ? `<div style="font-size:0.72rem;color:var(--text-secondary);margin-top:3px">${catalysts.join(' · ')}</div>` : ''}
            <a href="javascript:void(0)" onclick="showCockpitSources('${sym}')" style="font-size:0.66rem;color:var(--accent)">${sources} cited source${sources !== 1 ? 's' : ''} →</a>
          </div>`;
      } else {
        synthHTML = `<div style="margin-top:8px;padding-top:8px;border-top:1px solid var(--border);color:var(--text-muted);font-size:0.7rem">NO DATA — no research synthesis yet for ${sym}</div>`;
      }

      // Signal badges come only from promoted-template signals (§4/§5). No
      // template has been promoted yet, so the honest state is always
      // "no active signal" — never the retired ML prediction badge.
      const signalHTML = `<div style="margin-top:6px;color:var(--text-muted);font-size:0.7rem">No active signal</div>`;

      return `
        <div class="kpi-card" style="text-align:left;padding:14px">
          <div style="display:flex;justify-content:space-between;align-items:center">
            <strong style="font-size:0.95rem">${sym}</strong>
            ${tierBadge}
          </div>
          <div style="margin-top:6px">${priceHTML}</div>
          ${hasPrice ? signalHTML : ''}
          ${synthHTML}
        </div>`;
    }).join('');
  }

  // ── Monthly SIP tilt — reserved for the regime_dca_timing template (§4 of
  // the re-architecture plan), which has not been built or validated yet.
  // The old /rebalance endpoint returns a "confidence_weighted" table over
  // stale near-coin-flip model confidences across ALL 14 tracked names —
  // degenerate (every name ~7.14%) and not scoped to the 3 owned Tier-1
  // satellites (BEL, HDFCBANK, NTPC) the real ₹700/month SIP actually
  // allocates across. Rendering it would look data-backed but isn't, so we
  // show the honest "not yet available" state instead, regardless of what
  // /rebalance returns, until regime_dca_timing exists and passes its gates.
  const sipBody = el('cockpit-sip-body');
  const sipKpi  = el('cockpit-kpi-sip');
  if (sipKpi) sipKpi.textContent = 'NOT VALIDATED';
  if (sipBody) {
    sipBody.innerHTML = `
      <div style="text-align:center;color:var(--text-muted);padding:20px">
        SIP tilt not yet available — the regime_dca_timing template (Tier 1 only: BEL, HDFCBANK, NTPC)
        has not been built and validated yet. Split this month's ₹700 per the standing 60/40 plan
        until a template clears the walk-forward gates.
      </div>`;
  }
}

function showCockpitSources(symbol) {
  Api.researchSynthesisSymbol(symbol, 1).then(data => {
    const row = (data && data.synthesis && data.synthesis[0]) || null;
    if (!row) { alert(`No research synthesis available for ${symbol}.`); return; }
    const sources = row.source_event_ids || [];
    const lines = sources.map(s => `${s.table || '?'} #${s.id || '?'}`).join('\n');
    alert(`${symbol} — ${row.synthesis_date}\nModel: ${row.model_used}\n\nCited sources:\n${lines || '(none)'}`);
  }).catch(() => alert('Could not load sources — backend offline.'));
}
