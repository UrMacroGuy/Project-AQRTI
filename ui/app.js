/**
 * AQRTI Intelligence Terminal — app.js
 * Phase 1: Complete UI Shell with Realistic Mock Data
 *
 * Architecture: Module pattern with a central DataStore,
 * page renderers, and a Chart registry to prevent canvas reuse errors.
 */

// ═══════════════════════════════════════════════════════════════
// CHART.JS GLOBAL DEFAULTS — Dark Terminal Theme
// ═══════════════════════════════════════════════════════════════
// Bloomberg black/amber palette
Chart.defaults.color          = '#444444';
Chart.defaults.borderColor    = '#1a1a1a';
Chart.defaults.font.family    = "'JetBrains Mono', monospace";
Chart.defaults.font.size      = 10;
Chart.defaults.plugins.tooltip.backgroundColor = '#0d0d0d';
Chart.defaults.plugins.tooltip.borderColor     = '#2a2a2a';
Chart.defaults.plugins.tooltip.borderWidth     = 1;
Chart.defaults.plugins.tooltip.titleColor      = '#ff8c00';
Chart.defaults.plugins.tooltip.bodyColor       = '#888888';
Chart.defaults.plugins.legend.labels.color     = '#444444';

// ═══════════════════════════════════════════════════════════════
// CHART REGISTRY — prevents "Canvas already in use" errors
// ═══════════════════════════════════════════════════════════════
const ChartRegistry = (() => {
  const instances = {};
  return {
    create(id, config) {
      if (instances[id]) {
        instances[id].destroy();
        delete instances[id];
      }
      const canvas = document.getElementById(id);
      if (!canvas) return null;
      const chart = new Chart(canvas, config);
      instances[id] = chart;
      return chart;
    },
    destroy(id) {
      if (instances[id]) { instances[id].destroy(); delete instances[id]; }
    }
  };
})();

// ═══════════════════════════════════════════════════════════════
// HELPERS
// ═══════════════════════════════════════════════════════════════
function el(id) { return document.getElementById(id); }

function confBarHTML(conf, size = '') {
  const pct = conf;
  const cls = pct >= 80 ? 'high' : pct >= 70 ? 'medium' : 'low';
  return `
    <div class="conf-bar-wrap ${size}">
      <div class="conf-bar-track">
        <div class="conf-bar-fill ${cls}" style="width:${pct}%"></div>
      </div>
      <span class="conf-val">${pct}%</span>
    </div>`;
}

function dirBadge(dir) {
  const map = { Bullish: 'bullish', Bearish: 'bearish', Neutral: 'neutral' };
  return `<span class="badge badge-${map[dir] || 'neutral'}">${dir}</span>`;
}

function riskBadge(risk) {
  const map = { Low: 'low', Medium: 'medium', High: 'high' };
  return `<span class="badge badge-${map[risk] || 'neutral'}">${risk}</span>`;
}

function statusBadge(status) {
  const labels = { institutional: '★ Institutional', production: 'Production', paper: 'Paper', shadow: 'Shadow', retired: 'Retired' };
  return `<span class="badge badge-${status}">${labels[status] || status}</span>`;
}

function sentColor(val) {
  if (val >= 70) return 'positive';
  if (val >= 50) return 'neutral';
  return 'negative';
}

// ═══════════════════════════════════════════════════════════════
// CLOCK
// ═══════════════════════════════════════════════════════════════
function updateClock() {
  const now = new Date();
  const hh = String(now.getHours()).padStart(2,'0');
  const mm = String(now.getMinutes()).padStart(2,'0');
  const ss = String(now.getSeconds()).padStart(2,'0');
  const timeEl = el('market-clock');
  if (timeEl) timeEl.textContent = `${hh}:${mm}:${ss}`;

  const statusEl = el('market-open-status');
  if (statusEl) {
    const h = now.getHours();
    const isOpen = h >= 9 && (h < 15 || (h === 15 && now.getMinutes() <= 30));
    statusEl.textContent  = isOpen ? 'MARKET OPEN' : 'MARKET CLOSED';
    statusEl.style.color  = isOpen ? 'var(--positive)' : 'var(--text-muted)';
  }
}
setInterval(updateClock, 1000);
updateClock();

// ═══════════════════════════════════════════════════════════════
// NAVIGATION
// ═══════════════════════════════════════════════════════════════
const pageSubtitles = {
  overview:            'Command Center',
  market:              'Market Intelligence',
  'live-prices':       'Live Market Prices',
  opportunity:         'Opportunity Rankings',
  news:                'News Intelligence',
  sentiment:           'Sentiment Center',
  strategy:            'Strategy Lab',
  model:               'Model Center',
  learning:            'Learning Center',
  risk:                'Risk Center',
  paper:               'Paper Portfolio',
  agents:              'Research Operations',
  vault:               'Intelligence Vault',
  'intelligence-lab':  'Historical Intelligence',
  'data-intelligence': 'Data Intelligence',
};

function activatePage(pageId) {
  document.querySelectorAll('.nav-item').forEach(item => {
    item.classList.toggle('active', item.dataset.page === pageId);
  });
  document.querySelectorAll('.page').forEach(page => {
    page.classList.toggle('active', page.id === `page-${pageId}`);
  });
  // Bloomberg-style: breadcrumb in uppercase
  const name = pageId.toUpperCase().replace(/-/g, ' ');
  if (el('page-breadcrumb')) el('page-breadcrumb').textContent = name;
  if (el('topbar-subtitle')) el('topbar-subtitle').textContent = pageSubtitles[pageId] || '';

  // Persist current page to session
  _session.save(pageId);
}

// ══════════════════════════════════════════════════════════════
// SESSION PERSISTENCE — survive dev server restarts
// ══════════════════════════════════════════════════════════════
const _session = {
  KEY: 'aqrti_session',

  save(pageId) {
    const filters = {};
    const confF = document.getElementById('opp-conf-filter');
    const dirF  = document.getElementById('opp-dir-filter');
    if (confF) filters.oppConf = confF.value;
    if (dirF)  filters.oppDir  = dirF.value;
    const strF = document.getElementById('str-status-filter');
    if (strF)  filters.strStatus = strF.value;

    try {
      localStorage.setItem(this.KEY, JSON.stringify({
        page:      pageId,
        filters,
        savedAt:   Date.now(),
      }));
    } catch (_) {}
  },

  load() {
    try {
      const raw = localStorage.getItem(this.KEY);
      return raw ? JSON.parse(raw) : null;
    } catch (_) { return null; }
  },

  clear() {
    try { localStorage.removeItem(this.KEY); } catch (_) {}
  },
};

function resumeLastSession() {
  const s = window._pendingSession || _session.load();
  if (!s || !s.page) return;
  activatePage(s.page);
  renderPage(s.page);
  if (s.filters) {
    const cf = document.getElementById('opp-conf-filter');
    const df = document.getElementById('opp-dir-filter');
    const sf = document.getElementById('str-status-filter');
    if (cf && s.filters.oppConf)    cf.value = s.filters.oppConf;
    if (df && s.filters.oppDir)     df.value = s.filters.oppDir;
    if (sf && s.filters.strStatus)  sf.value = s.filters.strStatus;
  }
  const toast = document.getElementById('aqrti-session-toast');
  if (toast) toast.remove();
}

function _updateSidebarSessionBtn(session) {
  const btn  = document.getElementById('sidebar-session-btn');
  const info = document.getElementById('sidebar-session-info');
  if (!btn) return;
  if (!session || !session.page) { btn.style.display = 'none'; return; }
  const age = Math.round((Date.now() - session.savedAt) / 60000);
  const ageStr = age < 1 ? 'just now' : age < 60 ? `${age}m ago` : `${Math.round(age/60)}h ago`;
  const pageName = session.page.toUpperCase().replace(/-/g, ' ');
  if (info) info.textContent = `${pageName} · ${ageStr}`;
  btn.style.display = 'block';
}

function _sessionToast(session) {
  const existing = document.getElementById('aqrti-session-toast');
  if (existing) existing.remove();

  const age = Math.round((Date.now() - session.savedAt) / 60000);
  const ageStr = age < 1 ? 'just now' : age < 60 ? `${age}m ago` : `${Math.round(age/60)}h ago`;
  const pageName = (session.page || 'overview').toUpperCase().replace(/-/g, ' ');

  // Store session data on window so the resume button can access it
  // (localStorage was already overwritten by renderPage('overview'))
  window._pendingSession = session;

  const toast = document.createElement('div');
  toast.id = 'aqrti-session-toast';
  toast.style.cssText = `
    position:fixed; bottom:24px; left:50%; transform:translateX(-50%);
    z-index:9999; background:rgba(10,14,20,0.98);
    border:1px solid rgba(255,140,0,0.6); border-radius:10px;
    padding:16px 22px; display:flex; align-items:center; gap:16px;
    font-family:'JetBrains Mono',monospace; font-size:0.75rem;
    box-shadow:0 8px 40px rgba(0,0,0,0.7),0 0 0 1px rgba(255,140,0,0.15); min-width:380px;
    animation:slideUp 0.3s ease;
  `;
  toast.innerHTML = `
    <style>@keyframes slideUp{from{transform:translateX(-50%) translateY(20px);opacity:0}to{transform:translateX(-50%) translateY(0);opacity:1}}</style>
    <span style="color:var(--accent,#ff8c00);font-size:1.2rem">◈</span>
    <div style="flex:1">
      <div style="color:#f1f5f9;font-weight:700;letter-spacing:0.08em;font-size:0.75rem">SESSION FOUND</div>
      <div style="color:rgba(255,255,255,0.5);margin-top:3px;font-size:0.7rem">
        Last on <span style="color:var(--accent,#ff8c00);font-weight:600">${pageName}</span> · saved ${ageStr}
      </div>
    </div>
    <button id="aqrti-resume-btn"
      style="background:rgba(255,140,0,0.18);border:1px solid rgba(255,140,0,0.6);
             color:var(--accent,#ff8c00);padding:8px 18px;border-radius:6px;
             cursor:pointer;font-family:inherit;font-size:0.72rem;font-weight:700;
             letter-spacing:0.08em;white-space:nowrap;transition:background 0.15s">
      RESUME ›
    </button>
    <button onclick="document.getElementById('aqrti-session-toast').remove()"
      style="background:transparent;border:none;color:rgba(255,255,255,0.35);
             cursor:pointer;font-size:1.1rem;padding:0 4px;line-height:1">✕</button>
  `;
  document.body.appendChild(toast);

  // Wire resume button with captured session (not stale localStorage)
  document.getElementById('aqrti-resume-btn').addEventListener('click', () => {
    const s = window._pendingSession;
    if (s && s.page) {
      activatePage(s.page);
      renderPage(s.page);
      if (s.filters) {
        const cf = document.getElementById('opp-conf-filter');
        const df = document.getElementById('opp-dir-filter');
        const sf = document.getElementById('str-status-filter');
        if (cf && s.filters.oppConf) cf.value = s.filters.oppConf;
        if (df && s.filters.oppDir)  df.value = s.filters.oppDir;
        if (sf && s.filters.strStatus) sf.value = s.filters.strStatus;
      }
    }
    toast.remove();
  });

  // Auto-dismiss after 30s
  setTimeout(() => { if (toast.parentNode) toast.remove(); }, 30000);
}

// ══════════════════════════════════════════════════════════════
// COMMAND PALETTE — Bloomberg-style GO function
// ══════════════════════════════════════════════════════════════
const CMD_PAGES = [
  { icon: '◈', label: 'Overview',              hint: 'Command Center',        page: 'overview' },
  { icon: '◎', label: 'Market Intelligence',   hint: 'Indices · Sectors',     page: 'market' },
  { icon: '◉', label: 'Live Prices',           hint: 'Real-time quotes',      page: 'live-prices' },
  { icon: '◆', label: 'Opportunity Rankings',  hint: 'Signals · Confidence',  page: 'opportunity' },
  { icon: '◉', label: 'News Intelligence',     hint: 'Headlines · Sentiment', page: 'news' },
  { icon: '◐', label: 'Sentiment Center',      hint: 'Fear/Greed · Scores',   page: 'sentiment' },
  { icon: '▣', label: 'Strategy Research',     hint: 'Leaderboard · Replay',  page: 'strategy' },
  { icon: '▦', label: 'Model Center',          hint: 'ML Registry · AUC',     page: 'model' },
  { icon: '▷', label: 'Learning Center',       hint: 'Knowledge · Failures',  page: 'learning' },
  { icon: '◎', label: 'Research Ops',          hint: '7 Agents · Daily Brief',page: 'agents' },
  { icon: '▩', label: 'Intelligence Vault',    hint: 'Replay · Archive',      page: 'vault' },
  { icon: '⬟', label: 'Historical Intelligence',hint: 'Regimes · Meta-Learn', page: 'intelligence-lab' },
  { icon: '◫', label: 'Data Intelligence',     hint: 'FII/DII · Options',     page: 'data-intelligence' },
  { icon: '◈', label: 'Paper Portfolio',       hint: 'Positions · P&L',       page: 'paper' },
  { icon: '⬡', label: 'Risk Center',           hint: 'VaR · Drawdown · CB',   page: 'risk' },
];

let _cmdSelectedIdx = 0;
let _cmdFiltered = [...CMD_PAGES];

function openCmdPalette() {
  const overlay = document.getElementById('cmd-palette-overlay');
  const input   = document.getElementById('cmd-palette-input');
  if (!overlay) return;
  _cmdFiltered = [...CMD_PAGES];
  _cmdSelectedIdx = 0;
  overlay.classList.add('active');
  renderCmdResults('');
  setTimeout(() => input && input.focus(), 50);
}

function closeCmdPalette(e) {
  const overlay = document.getElementById('cmd-palette-overlay');
  if (overlay) overlay.classList.remove('active');
}

function renderCmdResults(query) {
  const container = document.getElementById('cmd-palette-results');
  if (!container) return;
  const q = query.trim().toLowerCase();
  _cmdFiltered = q
    ? CMD_PAGES.filter(p => p.label.toLowerCase().includes(q) || p.hint.toLowerCase().includes(q) || p.page.includes(q))
    : [...CMD_PAGES];
  if (_cmdSelectedIdx >= _cmdFiltered.length) _cmdSelectedIdx = 0;
  container.innerHTML = _cmdFiltered.map((p, i) => `
    <div class="cmd-result-item${i === _cmdSelectedIdx ? ' selected' : ''}" data-idx="${i}" onclick="cmdSelectIdx(${i})">
      <span class="cmd-result-icon">${p.icon}</span>
      <span class="cmd-result-label">${p.label}</span>
      <span class="cmd-result-hint">${p.hint}</span>
    </div>`).join('');
}

function cmdSelectIdx(idx) {
  _cmdSelectedIdx = idx;
  const item = _cmdFiltered[idx];
  if (item) {
    closeCmdPalette();
    renderPage(item.page);
  }
}

// Keyboard wiring for command palette
document.addEventListener('keydown', (e) => {
  const overlay = document.getElementById('cmd-palette-overlay');
  const isOpen  = overlay && overlay.classList.contains('active');

  if ((e.ctrlKey || e.metaKey) && e.key === 'k') {
    e.preventDefault();
    isOpen ? closeCmdPalette() : openCmdPalette();
    return;
  }
  if (!isOpen) return;

  if (e.key === 'Escape') { closeCmdPalette(); return; }
  if (e.key === 'ArrowDown') {
    e.preventDefault();
    _cmdSelectedIdx = Math.min(_cmdSelectedIdx + 1, _cmdFiltered.length - 1);
    renderCmdResults(document.getElementById('cmd-palette-input')?.value || '');
    return;
  }
  if (e.key === 'ArrowUp') {
    e.preventDefault();
    _cmdSelectedIdx = Math.max(_cmdSelectedIdx - 1, 0);
    renderCmdResults(document.getElementById('cmd-palette-input')?.value || '');
    return;
  }
  if (e.key === 'Enter') {
    e.preventDefault();
    cmdSelectIdx(_cmdSelectedIdx);
    return;
  }
});

document.addEventListener('DOMContentLoaded', () => {
  const input = document.getElementById('cmd-palette-input');
  if (input) {
    input.addEventListener('input', (e) => {
      _cmdSelectedIdx = 0;
      renderCmdResults(e.target.value);
    });
  }
});

// ══════════════════════════════════════════════════════════════
// NEWS TICKER STRIP — Bloomberg amber bar hydration
// ══════════════════════════════════════════════════════════════
async function hydrateNewsStrip() {
  const inner = document.getElementById('news-strip-inner');
  if (!inner) return;

  const data = await Api.news({ limit: 20, hours: 48 });
  if (!data || !Array.isArray(data) || !data.length) return;

  // Build items from live news headlines
  const items = data.slice(0, 16).map(n => {
    const sym  = n.symbol || n.entities?.[0] || 'NSE';
    const headline = (n.headline || n.title || '').slice(0, 90);
    const sent = n.sentiment_label || n.sentimentLabel || '';
    const sentIcon = sent === 'positive' ? '▲' : sent === 'negative' ? '▼' : '◆';
    return `<span class="news-strip-item"><span class="strip-sym">${sym}</span><span class="strip-sep">·</span>${sentIcon} ${headline}</span>`;
  });

  // Double for seamless loop
  const html = items.join('') + items.join('');
  inner.innerHTML = html;

  // Adjust animation speed based on content length
  const totalLen = data.slice(0, 16).reduce((a, n) => a + (n.headline || '').length, 0);
  const duration = Math.max(40, Math.min(90, totalLen / 3));
  inner.style.animationDuration = `${duration}s`;
}

// ═══════════════════════════════════════════════════════════════
// PAGE RENDERERS
// ═══════════════════════════════════════════════════════════════

// ── OVERVIEW ──────────────────────────────────────────────────
function renderOverview() {
  // Show loading placeholders — hydrateOverview() fills real data
  const _set = (id, v) => { const e = el(id); if (e) e.textContent = v; };
  _set('kpi-portfolio', '…');
  _set('kpi-daily-pnl', '…');
  _set('kpi-positions', '…');
  _set('kpi-predictions', '…');
  _set('kpi-winrate', '…');
  _set('kpi-knowledge', '…');
  const tbody = el('top-predictions-body');
  if (tbody) tbody.innerHTML = '<tr><td colspan="5" style="color:var(--text-muted);text-align:center;padding:16px">Loading predictions…</td></tr>';
}

// ── MARKET ────────────────────────────────────────────────────
function renderMarket() {
  // Delegate to live hydration — hydrateMarket() renders all charts/tables
  const moversBody = el('top-movers-body');
  if (moversBody) moversBody.innerHTML = '<tr><td colspan="5" style="color:var(--text-muted);text-align:center;padding:16px">Loading market data…</td></tr>';
  const derivBody = el('deriv-body');
  if (derivBody) derivBody.innerHTML = '<tr><td colspan="3" style="color:var(--text-muted);text-align:center;padding:16px">Loading…</td></tr>';
}

// ── OPPORTUNITIES ─────────────────────────────────────────────
function renderOpportunities() {
  // Delegate to hydrateOpportunities() which fetches real predictions
  const tbody = el('opportunity-body');
  if (tbody) tbody.innerHTML = '<tr><td colspan="10" style="color:var(--text-muted);text-align:center;padding:16px">Loading opportunities…</td></tr>';
  // Wire filter listeners once
  const confFilter = el('opp-conf-filter');
  const dirFilter  = el('opp-dir-filter');
  if (confFilter && !confFilter._wired) {
    confFilter._wired = true;
    confFilter.addEventListener('change', () => hydrateOpportunities());
  }
  if (dirFilter && !dirFilter._wired) {
    dirFilter._wired = true;
    dirFilter.addEventListener('change', () => hydrateOpportunities());
  }
}

// ── NEWS ──────────────────────────────────────────────────────
function renderNews() {
  // Delegate to hydrateNews() — all live data from backend
  const hi = el('news-high-impact');
  if (hi) hi.innerHTML = '<div style="padding:24px;text-align:center;color:var(--text-muted);font-size:0.78rem">Loading news…</div>';
  const feed = el('news-feed');
  if (feed) feed.innerHTML = '';
}

// ── SENTIMENT ─────────────────────────────────────────────────
function renderSentiment() {
  // Delegate to hydrateSentiment() — live backend data
  const velBody = el('sentiment-velocity-body');
  if (velBody) velBody.innerHTML = '<div style="padding:16px;text-align:center;color:var(--text-muted);font-size:0.78rem">Loading…</div>';
  const narrativeBody = el('narrative-shifts-body');
  if (narrativeBody) narrativeBody.innerHTML = '';
}

// ── STRATEGY LAB ──────────────────────────────────────────────
function renderStrategy() {
  // Delegate to hydrateStrategyResearch() — live backend data
  const tbody = el('strategy-body');
  if (tbody) tbody.innerHTML = '<tr><td colspan="10" style="color:var(--text-muted);text-align:center;padding:16px">Loading strategies…</td></tr>';
}

// ── MODEL CENTER ──────────────────────────────────────────────
function renderModel() {
  // Delegate to hydrateModelCenter() — live ML registry from backend
  const tbody = el('model-registry-body');
  if (tbody) tbody.innerHTML = '<tr><td colspan="9" style="color:var(--text-muted);text-align:center;padding:16px">Loading model registry…</td></tr>';
}

// ── LEARNING CENTER ───────────────────────────────────────────
async function renderLearning() {
  // Try live data first; fall back to mock
  let liveData = await Api.learningOverview(30).catch(() => null);
  let scoreHistory   = [];
  let failures       = [];
  let lessons        = [];
  let calibration    = null;
  let drift          = null;
  let featIntel      = null;

  if (liveData) {
    scoreHistory  = liveData.scoreHistory || [];
    failures      = liveData.recentFailures || [];
    lessons       = [];
    calibration   = await Api.calibrationCurve(30).catch(() => null);
    drift         = await Api.driftSummary(90).catch(() => null);
    featIntel     = await Api.featureRanking(30).catch(() => null);
    const lessonsData = await Api.lessons({ days: 30 }).catch(() => null);
    if (lessonsData) lessons = lessonsData.lessons || [];

    // KPI updates
    const score = liveData.intelligenceScore || 0;
    const delta = liveData.scoreDelta || 0;
    const setEl = (id, v) => { const e = el(id); if (e) e.textContent = v; };
    setEl('lc-kpi-score', `${score.toFixed(1)} / 100`);
    setEl('lc-kpi-delta', `${delta >= 0 ? '+' : ''}${delta.toFixed(1)} vs yesterday`);
    setEl('lc-kpi-failures', liveData.totalFailures ?? '—');
    setEl('lc-kpi-resolved', `${liveData.resolvedFailures ?? 0} resolved`);
    setEl('lc-kpi-lessons', liveData.totalLessons ?? '—');
    setEl('lc-kpi-applied', `${liveData.appliedLessons ?? 0} applied`);
    setEl('lc-kpi-critical', liveData.failuresBySeverity?.critical ?? 0);
    if (calibration) {
      setEl('lc-kpi-ece', `ECE: ${calibration.ece?.toFixed(4) ?? '—'}`);
    }
    if (featIntel && featIntel.features) {
      const healthy = featIntel.features.filter(f => f.decay_severity === 'none').length;
      setEl('lc-kpi-features-healthy', `${healthy} / ${featIntel.features.length}`);
    }
  } else {
    // Mock fallback — KPIs stay as static HTML defaults
    scoreHistory = [];
  }

  // ── Intelligence Score Growth ─────────────────────────────
  const growthLabels = scoreHistory.map(r => r.date?.slice(5) || '');
  const growthVals   = scoreHistory.map(r => r.overall_score ?? r.score ?? 0);
  ChartRegistry.create('knowledgeGrowthChart', {
    type: 'line',
    data: {
      labels: growthLabels.length ? growthLabels : [],
      datasets: [{
        label: 'Intelligence Score',
        data: growthVals.length ? growthVals : [],
        borderColor: '#ff8c00',
        borderWidth: 2,
        pointRadius: 0,
        tension: 0.4,
        fill: true,
        backgroundColor: 'rgba(255,140,0,0.08)',
      }],
    },
    options: {
      responsive: true,
      maintainAspectRatio: true,
      plugins: { legend: { display: false } },
      scales: {
        y: { min: 0, max: 100, ticks: { maxTicksLimit: 5 } },
        x: { ticks: { maxTicksLimit: 8 } },
      },
    },
  });

  // ── Score Components radar ────────────────────────────────
  const comp = liveData?.components || {};
  ChartRegistry.create('scoreComponentsChart', {
    type: 'radar',
    data: {
      labels: ['Prediction', 'Portfolio', 'Risk', 'Learning', 'Calibration', 'Features'],
      datasets: [{
        label: 'Score',
        data: [
          comp.predictionQuality  ?? 50,
          comp.portfolioQuality   ?? 50,
          comp.riskQuality        ?? 50,
          comp.learningQuality    ?? 50,
          comp.calibrationQuality ?? 50,
          comp.featureQuality     ?? 50,
        ],
        borderColor: '#ff8c00',
        backgroundColor: 'rgba(255,140,0,0.10)',
        pointBackgroundColor: '#ff8c00',
        borderWidth: 1.5,
      }],
    },
    options: {
      responsive: true,
      maintainAspectRatio: true,
      plugins: { legend: { display: false } },
      scales: { r: { min: 0, max: 100, ticks: { stepSize: 25 } } },
    },
  });

  // ── Failure Category Chart ────────────────────────────────
  const byCat    = liveData?.failuresByCategory || {};
  const catKeys  = Object.keys(byCat).length ? Object.keys(byCat) : [];
  const catVals  = Object.keys(byCat).length ? Object.values(byCat) : [];
  ChartRegistry.create('failureCatChart', {
    type: 'bar',
    data: {
      labels: catKeys,
      datasets: [{
        label: 'Count',
        data: catVals,
        backgroundColor: 'rgba(239,68,68,0.6)',
        borderRadius: 4,
      }],
    },
    options: {
      indexAxis: 'y',
      responsive: true,
      maintainAspectRatio: true,
      plugins: { legend: { display: false } },
      scales: {
        x: { ticks: { maxTicksLimit: 5 } },
        y: { ticks: { font: { size: 10 } } },
      },
    },
  });

  // ── Failure Timeline Chart ────────────────────────────────
  const timeline = liveData?.recentEvents
    ? (() => {
        const counts = {};
        (liveData.recentEvents || []).forEach(e => {
          const d = (e.date || '').slice(5);
          counts[d] = (counts[d] || 0) + 1;
        });
        return { labels: Object.keys(counts), vals: Object.values(counts) };
      })()
    : { labels: [], vals: [] };

  if (timeline.labels.length > 0) {
    ChartRegistry.create('failureTimelineChart', {
      type: 'bar',
      data: {
        labels: timeline.labels,
        datasets: [{
          label: 'Events',
          data: timeline.vals,
          backgroundColor: 'rgba(245,158,11,0.6)',
          borderRadius: 3,
        }],
      },
      options: {
        responsive: true,
        maintainAspectRatio: true,
        plugins: { legend: { display: false } },
        scales: { x: { ticks: { maxTicksLimit: 10 } } },
      },
    });
  }

  // ── Failures Table ────────────────────────────────────────
  const tbody = el('failure-table-body');
  if (tbody) {
    const rows = failures.length ? failures : [];
    const sevColor = { critical: '#ef4444', high: '#f59e0b', medium: '#60a5fa', low: '#6b7280' };
    tbody.innerHTML = rows.map(f => `
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
        maintainAspectRatio: true,
        plugins: { legend: { display: true, labels: { font: { size: 10 } } } },
        scales: {
          y: { min: 0, max: 100, ticks: { callback: v => `${v}%` } },
        },
      },
    });
  } else if (calCanvas) {
    calCanvas.style.display = 'none';
    if (calWrapper) {
      const msg = calWrapper.querySelector('#lc-cal-empty') || document.createElement('div');
      msg.id = 'lc-cal-empty';
      msg.style.cssText = 'color:var(--text-muted);font-size:0.72rem;padding:20px;text-align:center';
      msg.textContent = 'No evaluated predictions yet — calibration data builds after the first predictions close.';
      if (!calWrapper.contains(msg)) calWrapper.appendChild(msg);
    }
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
      featureBody.innerHTML = features.slice(0, 10).map(f => {
        const decColor = { none: '#00cc66', mild: '#ffcc00', moderate: '#ff8c00', severe: '#ff3333' };
        return `<tr>
          <td>${f.rank}</td>
          <td><strong>${f.feature_name}</strong></td>
          <td>${f.composite_score?.toFixed(1) ?? '—'}</td>
          <td>${f.ic_30d !== null && f.ic_30d !== undefined ? f.ic_30d.toFixed(4) : '—'}</td>
          <td><span style="color:${decColor[f.decay_severity] || '#fff'}">${f.decay_severity || '—'}</span></td>
          <td style="font-size:0.7rem;color:rgba(255,255,255,0.55)">${(f.recommendation || '').split(':')[0]}</td>
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
function renderRisk() {
  // Delegate entirely to hydrateRisk() -- live backend data only, no mock data
  hydrateRisk();
}

// LAZY RENDER — Render page on first activation
// ═══════════════════════════════════════════════════════════════
const rendered = new Set();

function renderPage(pageId) {
  if (rendered.has(pageId)) return;
  rendered.add(pageId);
  const renderers = {
    overview:    renderOverview,
    market:      renderMarket,
    opportunity: renderOpportunities,
    news:        renderNews,
    sentiment:   renderSentiment,
    strategy:    renderStrategy,
    model:       renderModel,
    learning:    renderLearning,
    risk:        renderRisk,
    paper:       renderPaperPortfolio,
  };
  if (renderers[pageId]) renderers[pageId]();
}

// ═══════════════════════════════════════════════════════════════
// ANIMATED KPI COUNTER
// ═══════════════════════════════════════════════════════════════
function animateCounter(element, target, prefix = '', suffix = '', duration = 800) {
  const start = 0;
  const startTime = performance.now();
  function update(currentTime) {
    const elapsed = currentTime - startTime;
    const progress = Math.min(elapsed / duration, 1);
    const eased = 1 - Math.pow(1 - progress, 3);
    const current = Math.round(start + (target - start) * eased);
    element.textContent = prefix + current.toLocaleString('en-IN') + suffix;
    if (progress < 1) requestAnimationFrame(update);
  }
  requestAnimationFrame(update);
}

// ═══════════════════════════════════════════════════════════════
// INIT
// ═══════════════════════════════════════════════════════════════
// ═══════════════════════════════════════════════════════════════
// LIVE DATA INTEGRATION
// These functions hydrate rendered pages with real backend data.
// They are no-ops when USE_MOCK = true (Api methods return null).
// ═══════════════════════════════════════════════════════════════

// ── News Intelligence — live hydration ───────────────────────
async function hydrateNews() {
  const data = await Api.news({ limit: 50, hours: 168 });
  const _setKpi = (id, val) => { const e = el(id); if (e) e.textContent = val; };

  if (!data || !Array.isArray(data) || !data.length) {
    _setKpi('news-kpi-count', '0');
    _setKpi('news-kpi-high-impact', '0');
    _setKpi('news-kpi-entities', '0');
    const msg = '<div style="padding:32px;text-align:center;color:var(--text-muted);font-size:0.78rem">No news articles in database.<br>Run pipeline from Research Ops → trigger ingestion.</div>';
    const hi = el('news-high-impact'); if (hi) hi.innerHTML = msg;
    const feed = el('news-feed'); if (feed) feed.innerHTML = msg;
    return;
  }

  // KPI cards
  const _set = (id, val) => { const e = el(id); if (e) e.textContent = val; };
  _set('news-kpi-count', data.length);
  const highImpactItems = data.filter(n => (n.impactScore ?? n.impact_score ?? 0) >= 80);
  _set('news-kpi-high-impact', highImpactItems.length);
  const sentScores = data.map(n => n.sentimentScore || 0).filter(s => s !== 0);
  if (sentScores.length) {
    const avg = sentScores.reduce((a, b) => a + b, 0) / sentScores.length;
    const avgEl = el('news-kpi-avg-sentiment');
    if (avgEl) { avgEl.textContent = `${avg >= 0 ? '+' : ''}${avg.toFixed(2)}`; avgEl.className = 'kpi-value ' + (avg >= 0 ? 'positive' : 'negative'); }
    _set('news-kpi-sentiment-sub', avg >= 0.1 ? 'Positive Bias Today' : avg <= -0.1 ? 'Negative Bias Today' : 'Neutral Today');
  }
  const entities = new Set(data.map(n => n.company).filter(Boolean));
  _set('news-kpi-entities', entities.size || '—');

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
          borderColor: '#ff8c00',
          borderWidth: 2,
          pointRadius: 2,
          pointBackgroundColor: '#ff8c00',
          tension: 0.4,
          fill: true,
          backgroundColor: 'rgba(255,140,0,0.06)',
          spanGaps: true,
        }],
      },
      options: {
        responsive: true, maintainAspectRatio: true,
        plugins: { legend: { display: false } },
        scales: {
          y: { min: -1, max: 1, ticks: { stepSize: 0.5, callback: v => v > 0 ? `+${v}` : v } },
          x: { ticks: { maxTicksLimit: 8 } },
        },
      },
    });
  }
}

// ── Sentiment Center — live hydration ────────────────────────
async function hydrateSentiment() {
  const data = await Api.sentiment();
  if (!data) return;

  const { companies = [], sectors = [], market } = data;
  const _set = (id, val) => { const e = el(id); if (e) e.textContent = val; };

  // KPI cards — prefer data.market fields, fall back to deriving from companies
  if (market && market.label) {
    _set('sent-kpi-market', market.label);
    const score = market.score != null ? market.score : '—';
    _set('sent-kpi-market-sub', score !== '—' ? `Score: ${Math.round(score)} / 100` : 'No data yet');
    const fg = market.fearGreed != null ? market.fearGreed : (market.score != null ? Math.round(market.score) : null);
    if (fg != null) {
      const zone = fg >= 75 ? 'Extreme Greed' : fg >= 60 ? 'Greed Zone' : fg >= 40 ? 'Neutral Zone' : fg >= 25 ? 'Fear Zone' : 'Extreme Fear';
      _set('sent-kpi-fear-greed', fg);
      _set('sent-kpi-fear-greed-sub', zone);
    }
  } else if (companies.length) {
    const avgScore = companies.reduce((s, c) => s + (c.score || 0), 0) / companies.length;
    const sentiment = avgScore >= 70 ? 'Optimistic' : avgScore >= 50 ? 'Neutral' : 'Pessimistic';
    _set('sent-kpi-market', sentiment);
    _set('sent-kpi-market-sub', `Score: ${avgScore.toFixed(0)} / 100`);
    const fearGreed = Math.round(avgScore);
    const zone = fearGreed >= 75 ? 'Extreme Greed' : fearGreed >= 60 ? 'Greed Zone' : fearGreed >= 40 ? 'Neutral Zone' : fearGreed >= 25 ? 'Fear Zone' : 'Extreme Fear';
    _set('sent-kpi-fear-greed', fearGreed);
    _set('sent-kpi-fear-greed-sub', zone);
  }

  if (companies.length) {
    const sorted = [...companies].sort((a, b) => (b.score || 0) - (a.score || 0));
    const best = sorted[0];
    const worst = sorted[sorted.length - 1];
    if (best) { _set('sent-kpi-best', best.entity || '—'); _set('sent-kpi-best-score', `Score: ${Math.round(best.score || 0)}`); }
    if (worst) { _set('sent-kpi-worst', worst.entity || '—'); _set('sent-kpi-worst-score', `Score: ${Math.round(worst.score || 0)}`); }
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
        responsive: true, maintainAspectRatio: true,
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
        responsive: true, maintainAspectRatio: true,
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
async function hydrateMarketRegime() {
  const data = await Api.marketRegime();
  if (!data) return;

  const topbarRegime = el('topbar-regime');
  if (topbarRegime) {
    topbarRegime.textContent = data.regime || 'LOADING…';
  }

  const pill = document.getElementById('regime-pill');
  if (pill) {
    pill.className = 'regime-badge badge-' + (data.regime || '').toLowerCase().replace(/\s+/g, '-');
  }

  // Overview page regime card
  const rName = el('overview-regime-name');
  if (rName) rName.textContent = data.regime || '—';
  const rConf = el('overview-regime-conf');
  if (rConf) rConf.textContent = data.confidence != null ? `Confidence: ${(data.confidence * 100).toFixed(0)}%` : 'Confidence: —';
  const rDesc = el('overview-regime-desc');
  if (rDesc) rDesc.textContent = data.description || data.regime_description || '';
}

// ── Add marketRegime endpoint to Api layer ────────────────────
// (Extends api.js Api object — safe to call even if api.js already loaded)
if (typeof Api !== 'undefined' && !Api.marketRegime) {
  Api.marketRegime = async function() {
    if (API_CONFIG.USE_MOCK) return null;
    return apiFetch('/market-regime');
  };
}


window.addEventListener('DOMContentLoaded', () => {
  // Read previous session BEFORE renderPage() overwrites it
  const prevSession = _session.load();

  // Render initial page (mock data first, then live overwrites)
  renderPage('overview');

  // Set date
  const dateEl = el('topbar-date');
  if (dateEl) {
    dateEl.textContent = new Date().toLocaleDateString('en-IN', {
      day: '2-digit', month: 'short', year: 'numeric',
    });
  }

  // Live backend hydration on startup
  hydrateOverview();
  hydrateOverviewPredictions();
  hydratePaperPortfolioStrip();
  hydrateMarket();          // topbar from DB (instant, yesterday's close)
  hydrateMarketRegime();
  startTopbarLivePolling(); // overwrites with real-time yfinance prices, refreshes every 30s
  hydrateNewsStrip();       // amber news ticker bar
  refreshNavBadges();       // update sidebar counts from live data

  // Session restore — sidebar button is always visible, toast appears after 500ms
  _updateSidebarSessionBtn(prevSession);
  if (prevSession && prevSession.page) {
    setTimeout(() => _sessionToast(prevSession), 500);
  }
});

// ── Opportunity Rankings — live prediction hydration ─────────
async function hydrateOpportunities() {
  const rawData = await Api.predictions({ limit: 50 });
  if (!rawData || !rawData.length) return;

  // Only show bullish/buy signals as investable opportunities
  const data = rawData.filter(p => {
    const dir = (p.direction || '').toLowerCase();
    return dir.includes('bull') || dir.includes('buy');
  }).slice(0, 20);

  // Re-rank after filter
  data.forEach((p, i) => { p.rank = i + 1; });

  const _set = (id, val) => { const e = el(id); if (e) e.textContent = val; };

  // Update nav badge
  const oppBadge = el('badge-opp');
  if (oppBadge) oppBadge.textContent = data.length;

  // KPI cards
  const strong = data.filter(p => (p.confidence || 0) >= 80);
  _set('opp-kpi-strong', strong.length);
  const avgConf = data.length ? data.reduce((s, p) => s + (p.confidence || 0), 0) / data.length : 0;
  _set('opp-kpi-avg-conf', data.length ? `${avgConf.toFixed(1)}%` : '—');
  const best = [...data].sort((a, b) => (b.expectedReturn || 0) - (a.expectedReturn || 0))[0];
  if (best) {
    const ret = best.expectedReturn;
    _set('opp-kpi-best-return', ret != null ? (ret >= 0 ? `+${ret.toFixed(2)}%` : `${ret.toFixed(2)}%`) : '—');
    _set('opp-kpi-best-symbol', `${best.symbol || '—'}${best.horizon ? ' (' + best.horizon + ')' : ''}`);
  }
  const riskCounts = { Low: 0, Medium: 0, High: 0 };
  data.forEach(p => { const r = p.risk || 'Medium'; if (riskCounts[r] != null) riskCounts[r]++; });
  const dominantRisk = data.length ? Object.entries(riskCounts).sort((a, b) => b[1] - a[1])[0][0] : '—';
  _set('opp-kpi-risk', dominantRisk);

  const tbody = el('opportunity-body');
  if (tbody) {
    if (!data.length) {
      tbody.innerHTML = '<tr><td colspan="10" style="color:var(--text-muted);text-align:center;padding:20px">No bullish predictions today — model sees no clear long setups.</td></tr>';
    } else tbody.innerHTML = data.map(p => {
      const expRet = p.expectedReturn != null
        ? (p.expectedReturn >= 0 ? `+${p.expectedReturn.toFixed(2)}%` : `${p.expectedReturn.toFixed(2)}%`)
        : '—';
      const sentiment = p.sentimentScore != null ? Math.round(p.sentimentScore) : '—';
      return `
        <tr>
          <td><strong style="color:var(--accent)">#${p.rank}</strong></td>
          <td><strong>${p.symbol}</strong></td>
          <td style="color:var(--text-muted)">${p.sector || '—'}</td>
          <td>${dirBadge(p.direction)}</td>
          <td>${confBarHTML(Math.round(p.confidence || 0))}</td>
          <td class="${(p.expectedReturn || 0) >= 0 ? 'positive' : 'negative'}">${expRet}</td>
          <td>${riskBadge(p.risk || 'Medium')}</td>
          <td style="color:var(--text-secondary)">${p.confidenceDetail ? p.confidenceDetail.category : '—'}</td>
          <td class="${sentColor(typeof sentiment === 'number' ? sentiment : 50)}">${sentiment}</td>
          <td><strong>${p.positionSize || '—'}</strong></td>
        </tr>`;
    }).join('');

    // Re-apply existing filters against live data
    const confFilter = el('opp-conf-filter');
    const dirFilter  = el('opp-dir-filter');
    if (confFilter && dirFilter) {
      const rows = Array.from(tbody.querySelectorAll('tr'));
      rows.forEach((row, i) => {
        const p = data[i]; if (!p) return;
        const conf = p.confidence || 0;
        const confOk = confFilter.value === 'all'
          || (confFilter.value === 'strong' && conf >= 80)
          || (confFilter.value === 'good'   && conf >= 70 && conf < 80);
        const dirOk = dirFilter.value === 'all'
          || (dirFilter.value === 'bullish' && p.direction === 'Bullish')
          || (dirFilter.value === 'bearish' && p.direction === 'Bearish');
        row.style.display = (confOk && dirOk) ? '' : 'none';
      });
    }
  }

  // Rebuild confidence distribution chart from live data
  const confBuckets = [0, 0, 0, 0];
  data.forEach(p => {
    const c = p.confidence || 0;
    if (c >= 80) confBuckets[3]++;
    else if (c >= 70) confBuckets[2]++;
    else if (c >= 60) confBuckets[1]++;
    else confBuckets[0]++;
  });
  ChartRegistry.create('confDistChart', {
    type: 'doughnut',
    data: {
      labels: ['< 60 (Ignore)', '60–69 (Weak)', '70–79 (Good)', '80+ (Strong)'],
      datasets: [{
        data: confBuckets,
        backgroundColor: ['rgba(239,68,68,0.7)','rgba(245,158,11,0.7)','rgba(255,140,0,0.7)','rgba(34,197,94,0.7)'],
        borderWidth: 1, borderColor: 'rgba(255,255,255,0.08)',
      }],
    },
    options: { responsive: true, maintainAspectRatio: true, plugins: { legend: { position: 'bottom' } }, cutout: '60%' },
  });
}


// ── Model Center — live model registry hydration ──────────────
async function hydrateModelCenter() {
  const [models, stats] = await Promise.all([Api.models(), Api.modelStats()]);
  if (!models && !stats) return;

  const _set = (id, val) => { const e = el(id); if (e) e.textContent = val; };

  // Update KPI badges if present
  if (stats && stats.available) {
    if (stats.bestAUC != null) _set('model-ensemble-acc', `${(stats.bestAUC * 100).toFixed(1)}%`);

    _set('model-active-count', stats.activeModels || '0');
    _set('model-active-sub', stats.totalFolds ? `${stats.totalFolds} Walk-Forward Folds` : 'Ensemble Active');

    if (stats.lastTrainedAt) {
      const d = new Date(stats.lastTrainedAt);
      const today = new Date();
      const isToday = d.toDateString() === today.toDateString();
      _set('model-last-retrain', isToday ? 'Today' : d.toLocaleDateString('en-IN'));
      _set('model-last-retrain-sub', d.toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit' }) + ' IST');
    }

    if (stats.bestIC != null) {
      const icEl = el('model-best-ic');
      if (icEl) icEl.textContent = stats.bestIC.toFixed(3);
    }
  }

  // Derive best model name + accuracy from models list
  if (models && models.length) {
    const dirModels = models.filter(m => m.task === 'direction' && m.isActive);
    if (dirModels.length) {
      const best = dirModels.reduce((a, b) => (a.primaryMetric || 0) > (b.primaryMetric || 0) ? a : b);
      _set('model-best-name', best.modelName || '—');
      if (best.primaryMetric != null) _set('model-best-acc', `${(best.primaryMetric * 100).toFixed(1)}% Direction`);
    }
    const featureCount = models.reduce((max, m) => Math.max(max, m.featureCount || m.numFeatures || 0), 0);
    if (featureCount > 0) _set('model-features-count', featureCount);
  }

  // Rebuild model registry table from live data
  const tbody = el('model-registry-body');
  if (tbody && models && models.length) {
    tbody.innerHTML = models.map(m => {
      const primary = m.primaryMetric != null ? (m.primaryMetric * 100).toFixed(1) : '—';
      const statusColor = m.isActive ? 'positive' : 'neutral';
      return `
        <tr>
          <td><strong style="font-family:var(--font-mono);font-size:0.72rem">${m.modelName}-${m.task || 'model'}</strong></td>
          <td style="color:var(--text-muted)">${m.modelName}</td>
          <td style="color:var(--text-secondary)">${m.labelCol}</td>
          <td class="${parseFloat(primary) >= 65 ? 'positive' : parseFloat(primary) >= 55 ? 'neutral' : 'warning'}">${primary}%</td>
          <td>v${m.version}</td>
          <td class="${statusColor}">${m.isActive ? 'Active' : 'Inactive'}</td>
          <td style="color:var(--text-muted)">${m.trainRows ? m.trainRows.toLocaleString('en-IN') : '—'}</td>
          <td style="color:var(--text-muted)">${m.trainedAt ? m.trainedAt.slice(0,10) : '—'}</td>
        </tr>`;
    }).join('');

    // Rebuild model accuracy bar chart from live data
    const active = models.filter(m => m.isActive);
    if (active.length) {
      const labels = active.map(m => `${m.modelName}/${(m.task || 'unk').slice(0,3)}`);
      const values = active.map(m => m.primaryMetric != null ? (m.primaryMetric * 100) : 0);
      ChartRegistry.create('modelAccChart', {
        type: 'bar',
        data: {
          labels,
          datasets: [{
            label: 'Primary Metric %',
            data: values,
            backgroundColor: values.map(v => v >= 65 ? 'rgba(34,197,94,0.7)' : v >= 55 ? 'rgba(255,140,0,0.7)' : 'rgba(245,158,11,0.6)'),
            borderRadius: 4,
          }],
        },
        options: {
          indexAxis: 'y',
          responsive: true,
          maintainAspectRatio: true,
          plugins: { legend: { display: false } },
          scales: { x: { min: 50, max: 100, ticks: { callback: v => `${v}%` } } },
        },
      });
    }
  }
}


// ── Overview — live predictions summary patch ─────────────────
async function hydrateOverviewPredictions() {
  const [regime, summary] = await Promise.all([Api.marketRegime(), Api.predictionSummary()]);

  if (regime) {
    const topbarRegime = el('topbar-regime');
    if (topbarRegime) topbarRegime.textContent = regime.regime || 'LOADING…';
    const pill = document.getElementById('regime-pill');
    if (pill) pill.className = 'regime-badge badge-' + (regime.regime || '').toLowerCase().replace(/\s+/g, '-');
  }

  if (summary && summary.available) {
    const predCountEl = el('kpi-predictions');
    if (predCountEl) predCountEl.textContent = summary.total || '0';

    const confEl = el('kpi-avg-conf');
    if (confEl && summary.avgConfidence != null) confEl.textContent = `Avg Conf: ${summary.avgConfidence}%`;

    // Replace top 3 prediction cards on overview if elements exist
    if (summary.topPredictions && summary.topPredictions.length) {
      summary.topPredictions.forEach((p, i) => {
        const symEl = document.querySelector(`[data-pred-symbol="${i}"]`);
        if (symEl) symEl.textContent = p.symbol;
        const dirEl = document.querySelector(`[data-pred-dir="${i}"]`);
        if (dirEl) {
          dirEl.textContent  = p.direction;
          dirEl.className    = p.direction === 'Bullish' ? 'positive' : p.direction === 'Bearish' ? 'negative' : 'neutral';
        }
        const confEl2 = document.querySelector(`[data-pred-conf="${i}"]`);
        if (confEl2) confEl2.textContent = `${Math.round(p.confidence || 0)}%`;
      });
    }
  }
}

// Extend Api with new Phase 3 endpoints
if (typeof Api !== 'undefined') {
  if (!Api.predictions) {
    Api.predictions = async function(params = {}) {
      if (API_CONFIG.USE_MOCK) return null;
      return apiFetch('/predictions', params);
    };
  }
  if (!Api.predictionSummary) {
    Api.predictionSummary = async function() {
      if (API_CONFIG.USE_MOCK) return null;
      return apiFetch('/predictions/summary');
    };
  }
  if (!Api.models) {
    Api.models = async function(params = {}) {
      if (API_CONFIG.USE_MOCK) return null;
      return apiFetch('/models', params);
    };
  }
  if (!Api.modelStats) {
    Api.modelStats = async function() {
      if (API_CONFIG.USE_MOCK) return null;
      return apiFetch('/models/stats');
    };
  }
  if (!Api.confidence) {
    Api.confidence = async function(params = {}) {
      if (API_CONFIG.USE_MOCK) return null;
      return apiFetch('/confidence', params);
    };
  }
  if (!Api.patterns) {
    Api.patterns = async function(params = {}) {
      if (API_CONFIG.USE_MOCK) return null;
      return apiFetch('/patterns', params);
    };
  }
}


// ═══════════════════════════════════════════════════════════════
// PHASE 4: PAPER PORTFOLIO PAGE RENDERER + HYDRATION
// ═══════════════════════════════════════════════════════════════

// ── Paper Portfolio renderer ─────────────────────────────────
function renderPaperPortfolio() {
  // Delegate entirely to hydratePaperPortfolio() — live backend data
  const pbody = el('pp-full-positions-body');
  if (pbody) pbody.innerHTML = '<tr><td colspan="12" style="color:var(--text-muted);text-align:center;padding:16px">Loading positions…</td></tr>';
  const tbody = el('pp-trades-body');
  if (tbody) tbody.innerHTML = '<tr><td colspan="13" style="color:var(--text-muted);text-align:center;padding:16px">Loading trades…</td></tr>';
}

async function triggerPaperCycle() {
  const statusEl = document.getElementById('pp-cycle-status');
  const btn = document.querySelector('[onclick="triggerPaperCycle()"]');
  if (statusEl) statusEl.textContent = '⟳ Running cycle…';
  if (btn) btn.disabled = true;
  try {
    const res = await fetch(`${API_CONFIG.BASE}/admin/paper-trade`, { method: 'POST' });
    const data = await res.json();
    const opened  = (data.opened || []).length;
    const closed  = (data.closed || []).length;
    const slClosed = (data.stopLossClosed || []).length;
    const tpClosed = (data.takeProfitClosed || []).length;
    const value   = Math.round(data.portfolioValue || 0).toLocaleString('en-IN');
    let msg = `✓ NAV ₹${value}`;
    if (opened)   msg += `  · Opened: ${opened}`;
    if (closed)   msg += `  · Closed: ${closed}`;
    if (slClosed) msg += `  · SL hit: ${slClosed}`;
    if (tpClosed) msg += `  · TP hit: ${tpClosed}`;
    if (data.status === 'no_signals') msg = '⚠ No signals today — NAV marked to market';
    if (statusEl) { statusEl.textContent = msg; statusEl.style.color = 'var(--accent)'; }
    await hydratePaperPortfolio();
  } catch(e) {
    if (statusEl) { statusEl.textContent = '✗ Error: ' + e.message; statusEl.style.color = '#ff4444'; }
  } finally {
    if (btn) btn.disabled = false;
  }
}

// ── Live hydration ────────────────────────────────────────────
async function hydratePaperPortfolio() {
  const [pp, perf, curve, alloc, trades] = await Promise.all([
    Api.paperPortfolio(),
    Api.performance(),
    Api.equityCurve(90),
    Api.paperAllocation(),
    Api.paperTrades(100),
  ]);

  const _set = (id, val) => { const e = el(id); if (e) e.textContent = val; };
  const fmt  = (v, dec = 2) => (v != null && !isNaN(v)) ? Number(v).toFixed(dec) : '—';
  const fmtRs = v => v != null ? `₹${Math.round(v).toLocaleString('en-IN')}` : '—';
  const pnlCls = v => (v || 0) >= 0 ? 'positive' : 'negative';
  const pnlSign = v => (v || 0) >= 0 ? '+' : '';

  // ── KPI row ──
  if (pp && pp.portfolio) {
    const port = pp.portfolio;
    _set('pp-kpi-value',    fmtRs(port.totalValue));
    _set('pp-kpi-cash',     fmtRs(port.currentCash));
    _set('pp-kpi-cash-pct', `${fmt(port.cashPct, 1)}% of Portfolio`);
    _set('pp-kpi-invested', `${fmtRs(port.investedCapital)} Deployed`);
    const retEl = el('pp-kpi-return');
    if (retEl) {
      const ret = port.totalReturnPct || 0;
      retEl.textContent = `${pnlSign(ret)}${fmt(ret)}%`;
      retEl.className = 'kpi-sub ' + pnlCls(ret);
    }
  }

  // Unrealized P&L across open positions
  if (pp && pp.positions && pp.positions.length) {
    const totalUnreal = pp.positions.reduce((s, p) => s + (p.unrealizedPnl || 0), 0);
    const totalInvested = pp.positions.reduce((s, p) => s + (p.capitalDeployed || 0), 0);
    const unrPct = totalInvested > 0 ? totalUnreal / totalInvested * 100 : 0;
    const urEl = el('pp-kpi-unrealized');
    if (urEl) { urEl.textContent = `${pnlSign(totalUnreal)}${fmtRs(totalUnreal)}`; urEl.className = 'kpi-value ' + pnlCls(totalUnreal); }
    _set('pp-kpi-unrealized-pct', `${pnlSign(unrPct)}${fmt(unrPct, 2)}% open`);
    _set('pp-kpi-positions', pp.positions.length);
  }

  if (perf && perf.available) {
    const wr = perf.winRatePct || 0;
    const wrEl = el('pp-kpi-winrate');
    if (wrEl) { wrEl.textContent = `${fmt(wr, 1)}%`; wrEl.className = 'kpi-value ' + (wr >= 50 ? 'positive' : 'negative'); }
    _set('pp-kpi-trades',   `${perf.closedTrades || 0} Closed Trades`);
    _set('pp-kpi-maxdd',    `${fmt(perf.maxDrawdownPct)}%`);
    _set('pp-kpi-sharpe',   `Sharpe: ${fmt(perf.sharpeRatio)}`);

    // Analytics tables
    const sign = v => (v || 0) >= 0 ? '+' : '';
    _set('pp-an-total-ret',  `${sign(perf.totalReturnPct)}${fmt(perf.totalReturnPct)}%`);
    _set('pp-an-cagr',       `${fmt(perf.cagrPct)}%`);
    _set('pp-an-sharpe',     fmt(perf.sharpeRatio));
    _set('pp-an-sortino',    fmt(perf.sortinoRatio));
    _set('pp-an-maxdd',      `${fmt(perf.maxDrawdownPct)}%`);
    _set('pp-an-vol',        `${fmt(perf.volatilityAnn)}%`);
    _set('pp-an-winrate',    `${fmt(perf.winRatePct)}%`);
    _set('pp-an-pf',         fmt(perf.profitFactor));
    _set('pp-an-expectancy', `${fmt(perf.expectancyPct)}%`);
    _set('pp-an-avgwin',     `${fmt(perf.avgWinPct)}%`);
    _set('pp-an-avgloss',    `${fmt(perf.avgLossPct)}%`);
    _set('pp-an-hold',       fmt(perf.avgHoldingDays));
    _set('pp-an-expo',       `${fmt(perf.avgExposurePct)}%`);
    _set('pp-an-turnover',   `${fmt(perf.turnoverPct)}%`);
  }

  // ── Strategy badge — show which strategy is driving trades ──
  const stratBadge = el('pp-strategy-badge');
  if (stratBadge) {
    const pos0 = pp && pp.positions && pp.positions[0];
    const stratName = pos0 && (pos0.strategyName || pos0.strategyId);
    stratBadge.textContent = stratName ? `◈ Strategy: ${stratName}` : `◈ Best Fitness Strategy (auto-selected)`;
  }

  // ── Equity curve chart ──
  const curveCanvas = el('ppEquityCurveChart');
  const curveEmpty  = el('pp-equity-empty');
  if (curve && curve.labels && curve.labels.length > 1) {
    if (curveCanvas) curveCanvas.style.display = '';
    if (curveEmpty)  curveEmpty.style.display  = 'none';
    ChartRegistry.create('ppEquityCurveChart', {
      type: 'line',
      data: {
        labels: curve.labels,
        datasets: [{
          data: curve.values,
          borderColor: '#ff8c00', borderWidth: 2, pointRadius: 0, tension: 0.3, fill: true,
          backgroundColor: (ctx) => {
            const g = ctx.chart.ctx.createLinearGradient(0, 0, 0, ctx.chart.height);
            g.addColorStop(0, 'rgba(255,140,0,0.18)');
            g.addColorStop(1, 'rgba(255,140,0,0.00)');
            return g;
          },
        }],
      },
      options: {
        responsive: true, maintainAspectRatio: false,
        plugins: { legend: { display: false }, tooltip: { callbacks: { label: ctx => ` ₹${Math.round(ctx.parsed.y).toLocaleString('en-IN')}` }}},
        scales: {
          x: { ticks: { maxTicksLimit: 8, maxRotation: 0, color: '#888', font: { size: 9 }}, grid: { color: 'rgba(255,255,255,0.04)' }},
          y: { ticks: { callback: v => `₹${(v/1000).toFixed(0)}K`, maxTicksLimit: 5, color: '#888', font: { size: 9 }}, grid: { color: 'rgba(255,255,255,0.04)' }},
        },
      },
    });
  } else {
    if (curveCanvas) curveCanvas.style.display = 'none';
    if (curveEmpty)  { curveEmpty.style.display = ''; curveEmpty.textContent = 'No equity history yet — run paper cycles to build the curve.'; }
  }

  // ── Allocation doughnut ──
  const allocData = (alloc && alloc.some(a => a.type === 'equity'))
    ? alloc
    : (pp && pp.positions && pp.positions.length)
        ? [...pp.positions.map(p => ({ symbol: p.symbol, weightPct: p.weightPct, type: 'equity' })),
           { symbol: 'CASH', weightPct: pp.portfolio ? pp.portfolio.cashPct : 0, type: 'cash' }]
        : alloc;

  const totalExpo = allocData ? allocData.filter(a => a.type === 'equity').reduce((s, a) => s + (a.weightPct || 0), 0) : 0;
  _set('pp-alloc-exposure', `${fmt(totalExpo, 0)}% Invested`);

  if (allocData && allocData.length) {
    const PALETTE = ['rgba(255,140,0,0.85)','rgba(34,197,94,0.7)','rgba(59,130,246,0.7)',
      'rgba(245,158,11,0.7)','rgba(239,68,68,0.7)','rgba(147,51,234,0.7)',
      'rgba(236,72,153,0.7)','rgba(0,170,255,0.7)','rgba(251,146,60,0.7)',
      'rgba(20,184,166,0.7)','rgba(248,113,113,0.7)','rgba(167,243,208,0.7)',
      'rgba(255,255,255,0.12)'];
    ChartRegistry.create('ppAllocationChart', {
      type: 'doughnut',
      data: {
        labels: allocData.map(a => a.symbol),
        datasets: [{ data: allocData.map(a => a.weightPct), backgroundColor: allocData.map((_, i) => PALETTE[i % 13]), borderWidth: 1, borderColor: 'rgba(255,255,255,0.06)' }],
      },
      options: {
        responsive: true, maintainAspectRatio: false,
        plugins: { legend: { position: 'right', labels: { color: '#aaa', font: { size: 10 }, boxWidth: 10 }}, tooltip: { callbacks: { label: ctx => ` ${ctx.label}: ${ctx.parsed.toFixed(1)}%` }}},
        cutout: '55%',
      },
    });
  }

  // ── Open positions table — full trader view ──
  const pbody = el('pp-full-positions-body');
  if (pbody) {
    const positions = pp && pp.positions || [];
    _set('pp-open-count', `${positions.length} position${positions.length !== 1 ? 's' : ''}`);
    if (positions.length) {
      pbody.innerHTML = positions.map(p => {
        const pc  = pnlCls(p.unrealizedPct);
        const ps  = pnlSign(p.unrealizedPct);
        const slPct = p.entryPrice > 0 ? ((p.stopLoss - p.entryPrice) / p.entryPrice * 100) : 0;
        const tpPct = p.entryPrice > 0 ? ((p.target   - p.entryPrice) / p.entryPrice * 100) : 0;
        return `<tr>
          <td><strong>${p.symbol}</strong></td>
          <td style="color:var(--text-muted);font-size:0.7rem">${p.sector || '—'}</td>
          <td style="color:var(--text-muted)">${p.entryDate || '—'}</td>
          <td>₹${fmt(p.entryPrice)}</td>
          <td><strong>₹${fmt(p.currentPrice)}</strong></td>
          <td style="color:var(--text-muted)">${fmt(p.shares, 2)}</td>
          <td>${fmtRs(p.capitalDeployed)}</td>
          <td class="${pc}"><strong>${ps}₹${Math.round(p.unrealizedPnl || 0).toLocaleString('en-IN')}</strong><br><span style="font-size:0.68rem">${ps}${fmt(p.unrealizedPct)}%</span></td>
          <td class="negative" title="Stop Loss">₹${fmt(p.stopLoss)}<br><span style="font-size:0.65rem">${fmt(slPct)}%</span></td>
          <td class="positive" title="Target">₹${fmt(p.target)}<br><span style="font-size:0.65rem">+${fmt(tpPct)}%</span></td>
          <td style="font-size:0.68rem;color:var(--accent);white-space:nowrap" title="${p.strategyId || ''}">${p.strategyName || p.strategyId || '<span style="color:var(--text-muted)">—</span>'}</td>
          <td>${confBarHTML(Math.round(p.confidence || 0))}</td>
          <td>${dirBadge(p.direction || 'Bullish')}</td>
        </tr>`;
      }).join('');
    } else {
      pbody.innerHTML = `<tr><td colspan="12" style="color:var(--text-muted);text-align:center;padding:20px">No open positions — click ▶ Run Trade Cycle</td></tr>`;
    }
  }

  // ── Trade history table — full detail ──
  const tbody = el('pp-trades-body');
  if (tbody) {
    const tradeList = trades || [];
    _set('pp-trades-count', `${tradeList.length} closed`);
    if (tradeList.length) {
      tbody.innerHTML = tradeList.map(t => {
        const pc = pnlCls(t.grossPnlPct);
        const ps = pnlSign(t.grossPnlPct);
        const reasonColor = t.exitReason === 'stop_loss' ? 'negative' : t.exitReason === 'take_profit' ? 'positive' : '';
        return `<tr>
          <td><strong>${t.symbol}</strong></td>
          <td style="color:var(--text-muted);font-size:0.7rem">${t.sector || '—'}</td>
          <td style="color:var(--text-muted)">${t.entryDate || '—'}</td>
          <td style="color:var(--text-muted)">${t.exitDate || '—'}</td>
          <td style="color:var(--text-muted)">${t.holdingDays || 0}d</td>
          <td>₹${fmt(t.entryPrice)}</td>
          <td>₹${fmt(t.exitPrice)}</td>
          <td style="color:var(--text-muted)">${fmt(t.shares, 2)}</td>
          <td>${fmtRs(t.capitalDeployed)}</td>
          <td class="${pc}"><strong>${ps}${fmtRs(t.grossPnl)}</strong></td>
          <td class="${pc}"><strong>${ps}${fmt(t.grossPnlPct)}%</strong></td>
          <td class="${reasonColor}" style="font-size:0.7rem;letter-spacing:0.03em">${(t.exitReason || '—').replace(/_/g,' ').toUpperCase()}</td>
          <td style="font-size:0.68rem;color:var(--accent);white-space:nowrap" title="${t.strategyId || ''}">${t.strategyName || t.strategyId || '<span style="color:var(--text-muted)">—</span>'}</td>
          <td>${confBarHTML(Math.round(t.confidence || 0))}</td>
        </tr>`;
      }).join('');
    } else {
      tbody.innerHTML = `<tr><td colspan="13" style="color:var(--text-muted);text-align:center;padding:20px">No closed trades yet — run a cycle and let positions close</td></tr>`;
    }
  }
}

// ── Overview strip — portfolio summary + performance ─────────
async function hydratePaperPortfolioStrip() {
  const [pp, perf] = await Promise.all([Api.paperPortfolio(), Api.performance()]);

  if (pp && pp.positions && pp.positions.length) {
    const tbody = el('pp-positions-body');
    if (tbody) {
      tbody.innerHTML = pp.positions.slice(0, 6).map(p => {
        const pnlClass = (p.unrealizedPct || 0) >= 0 ? 'positive' : 'negative';
        const sign     = (p.unrealizedPct || 0) >= 0 ? '+' : '';
        return `
          <tr>
            <td><strong>${p.symbol}</strong></td>
            <td style="color:var(--text-muted)">₹${(p.entryPrice || 0).toFixed(2)}</td>
            <td>₹${(p.currentPrice || 0).toFixed(2)}</td>
            <td>${(p.weightPct || 0).toFixed(1)}%</td>
            <td class="${pnlClass}">${sign}${(p.unrealizedPct || 0).toFixed(2)}%</td>
            <td>${confBarHTML(Math.round(p.confidence || 0))}</td>
          </tr>`;
      }).join('');
      const cnt = el('pp-position-count');
      if (cnt) cnt.textContent = `${pp.positions.length} Open`;
    }
  }

  if (perf && perf.available) {
    const _setEl = (id, val) => { const e = el(id); if (e) e.textContent = val; };
    const ret = perf.totalReturnPct || 0;
    const retEl = el('pp-total-return');
    if (retEl) { retEl.textContent = `${ret >= 0 ? '+' : ''}${ret.toFixed(2)}%`; retEl.className = 'kpi-value ' + (ret >= 0 ? 'positive' : 'negative'); }
    const shrEl = el('pp-sharpe');
    if (shrEl) { shrEl.textContent = (perf.sharpeRatio || 0).toFixed(2); shrEl.className = 'kpi-value ' + ((perf.sharpeRatio || 0) >= 1 ? 'positive' : 'neutral'); }
    const sorEl = el('pp-sortino');
    if (sorEl) sorEl.textContent = (perf.sortinoRatio || 0).toFixed(2);
    const ddEl = el('pp-max-dd');
    if (ddEl) { ddEl.textContent = `${(perf.maxDrawdownPct || 0).toFixed(2)}%`; ddEl.className = 'kpi-value negative'; }
    const wrEl = el('pp-win-rate');
    if (wrEl) { wrEl.textContent = `${(perf.winRatePct || 0).toFixed(1)}%`; wrEl.className = 'kpi-value ' + ((perf.winRatePct || 0) >= 50 ? 'positive' : 'negative'); }
    const pfEl = el('pp-profit-factor');
    if (pfEl) { pfEl.textContent = (perf.profitFactor || 0).toFixed(2); pfEl.className = 'kpi-value ' + ((perf.profitFactor || 0) >= 1 ? 'positive' : 'negative'); }
    const dateEl = el('pp-perf-date');
    if (dateEl) dateEl.textContent = perf.date || '—';
  }
}


// ═══════════════════════════════════════════════════════════════
// STRATEGY RESEARCH CENTER — Phase 6
// ═══════════════════════════════════════════════════════════════

async function hydrateStrategyResearch() {
  const el = id => document.getElementById(id);

  // Try backend, fall back to mock
  let pop      = await Api.strategyPopulation();
  let leaders  = await Api.strategyLeaderboard(15);
  let evoTree  = await Api.evolutionTree(90);
  let affinity = await Api.regimeAffinity();
  let graveD   = await Api.graveyard({ limit: 20 });
  let resurrect = await Api.resurrectionCandidates();
  let research = await Api.latestResearch();



  // ── KPIs ──────────────────────────────────────────────────────
  const stats = pop.stats || {};
  const _kpi = (id, v) => { const e = el(id); if (e) e.textContent = v; };
  _kpi('src-kpi-total', stats.total || '—');
  _kpi('src-kpi-active-sub', `${stats.active_count || 0} Active`);
  _kpi('src-kpi-avg-fitness', stats.avg_fitness != null ? stats.avg_fitness.toFixed(1) : '—');
  _kpi('src-kpi-best-fitness', stats.max_fitness != null ? stats.max_fitness.toFixed(1) : '—');
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
      return `<tr>
        <td style="color:var(--text-muted)">${i + 1}</td>
        <td style="font-family:var(--font-mono);font-size:0.72rem">${r.name || r.strategy_id}</td>
        <td><span class="chip">${r.family || '—'}</span></td>
        <td class="${statusClass}" style="font-size:0.7rem">${(r.status || '').toUpperCase()}</td>
        <td style="font-weight:600">${fitness}</td>
        <td>${wr}</td>
        <td style="font-weight:600;${avgPnlColor}">${avgPnlStr}</td>
        <td style="color:var(--text-muted)">${r.trade_count || 0}</td>
        <td style="white-space:nowrap">
          ${canActivate ? `<button class="panel-action-btn" onclick="activateStrategy('${r.strategy_id}')">Activate</button> ` : ''}
          ${r.trade_count > 0 ? `<button class="panel-action-btn" style="background:rgba(0,170,255,0.12);border-color:rgba(0,170,255,0.35)" onclick="openStrategyTrades('${r.strategy_id}')">Trades</button>` : '—'}
        </td>
      </tr>`;
    }).join('') || `<tr><td colspan="9" style="color:var(--text-muted);text-align:center">No strategies yet</td></tr>`;
  }

  // ── Family Population Chart ───────────────────────────────────
  const familyData = pop.by_family || {};
  const famLabels  = Object.keys(familyData);
  // API returns count/active_count per family; graveyard count not split by family here
  const famAlive   = famLabels.map(f => familyData[f].count || familyData[f].alive || 0);
  const famDead    = famLabels.map(f => familyData[f].dead  || 0);
  ChartRegistry.create('srcFamilyChart', {
    type: 'bar',
    data: {
      labels: famLabels,
      datasets: [
        { label: 'Alive', data: famAlive, backgroundColor: 'rgba(0,170,255,0.7)' },
        { label: 'Graveyard', data: famDead, backgroundColor: 'rgba(239,68,68,0.4)' },
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
  const ops     = evoTree.by_operation || {};
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
          backgroundColor: opDelta.map(v => v >= 0 ? 'rgba(52,211,153,0.6)' : 'rgba(239,68,68,0.5)'),
          yAxisID: 'y',
        },
        {
          label: '% Positive',
          data: opPos,
          type: 'line',
          borderColor: 'rgba(251,191,36,0.8)',
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
  const REGIME_COLORS = ['rgba(52,211,153,0.7)', 'rgba(239,68,68,0.6)', 'rgba(251,191,36,0.6)', 'rgba(167,139,250,0.6)'];
  const affFamilies = Object.keys(affinity);
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
    const stratEvts = evList.filter(e => e.category === 'strategy' || e.type?.startsWith('strategy_'));
    if (stratEvts.length) {
      feedEl.innerHTML = stratEvts.slice(0, 30).map(e => {
        const isPromo  = e.type === 'strategy_promoted';
        const isRetire = e.type === 'strategy_retired';
        const color = isPromo ? 'var(--color-positive)' : isRetire ? 'var(--color-negative)' : 'var(--text-muted)';
        const icon  = isPromo ? '▲' : isRetire ? '▼' : '●';
        return `<div style="display:flex;align-items:flex-start;gap:8px;padding:6px 12px;border-bottom:1px solid var(--border-faint)">
          <span style="color:${color};min-width:12px;margin-top:1px">${icon}</span>
          <div>
            <div style="color:${color};font-size:0.68rem">${e.date}</div>
            <div style="color:var(--text-secondary);font-size:0.7rem;line-height:1.4">${e.description || e.type}</div>
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
        ${rep.recommendations ? `<div style="font-size:0.68rem;color:var(--accent);background:rgba(255,140,0,0.06);padding:6px 10px;border-radius:4px;border-left:2px solid var(--accent)">${rep.recommendations}</div>` : ''}
      </div>
    `).join('');
  }
}

async function activateStrategy(strategyId) {
  if (!confirm(`Activate strategy ${strategyId}?\n\nThis marks it ACTIVE (requires "promoted" status).`)) return;
  try {
    const res = await fetch(`${API_CONFIG.BASE}/strategies/${strategyId}/activate`, { method: 'POST' });
    const result = await res.json();
    if (res.ok && result.status === 'active') {
      alert(`Strategy ${strategyId} is now ACTIVE.`);
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
// RESEARCH OPERATIONS CENTER — Phase 7
// ═══════════════════════════════════════════════════════════════

const MOCK_AGENT_DATA = {
  agents: [
    { agent_id: 'market_research',   name: 'Market Research Agent',   agent_type: 'market',   status: 'idle',    last_run_at: new Date(Date.now()-3600000).toISOString(), last_run_status: 'success', run_count: 14, error_count: 0 },
    { agent_id: 'news_research',     name: 'News Research Agent',     agent_type: 'news',     status: 'idle',    last_run_at: new Date(Date.now()-3600000).toISOString(), last_run_status: 'success', run_count: 14, error_count: 1 },
    { agent_id: 'pattern_research',  name: 'Pattern Research Agent',  agent_type: 'pattern',  status: 'idle',    last_run_at: new Date(Date.now()-3600000).toISOString(), last_run_status: 'success', run_count: 14, error_count: 0 },
    { agent_id: 'model_research',    name: 'Model Research Agent',    agent_type: 'model',    status: 'idle',    last_run_at: new Date(Date.now()-3600000).toISOString(), last_run_status: 'success', run_count: 14, error_count: 0 },
    { agent_id: 'strategy_research', name: 'Strategy Research Agent', agent_type: 'strategy', status: 'idle',    last_run_at: new Date(Date.now()-3600000).toISOString(), last_run_status: 'success', run_count: 14, error_count: 0 },
    { agent_id: 'risk_research',     name: 'Risk Research Agent',     agent_type: 'risk',     status: 'idle',    last_run_at: new Date(Date.now()-3600000).toISOString(), last_run_status: 'success', run_count: 14, error_count: 0 },
    { agent_id: 'cro',               name: 'Chief Research Officer',  agent_type: 'cro',      status: 'idle',    last_run_at: new Date(Date.now()-3600000).toISOString(), last_run_status: 'success', run_count: 14, error_count: 0 },
  ],
  findings: [
    { agent_id: 'market_research',   urgency: 'high',   title: 'Regime Change: SIDEWAYS → BULL',        implication: 'Review strategy allocations.', date: new Date().toISOString().split('T')[0] },
    { agent_id: 'risk_research',     urgency: 'high',   title: 'Sector Concentration: BANKING 48%',     implication: 'Diversify sector exposure.',   date: new Date().toISOString().split('T')[0] },
    { agent_id: 'model_research',    urgency: 'normal', title: 'Model Drift: LightGBM drift=12.4%',     implication: 'Request retraining approval.',  date: new Date().toISOString().split('T')[0] },
    { agent_id: 'strategy_research', urgency: 'normal', title: 'Leading Family: momentum (avg 71.3)',   implication: 'Prioritize in next evolution.',  date: new Date().toISOString().split('T')[0] },
    { agent_id: 'news_research',     urgency: 'normal', title: 'Sentiment Shift: improving (+18.2)',    implication: 'Sentiment-driven signals positive.', date: new Date().toISOString().split('T')[0] },
  ],
  brief: {
    brief_date: new Date().toISOString().split('T')[0],
    regime_at: 'BULL',
    knowledge_score: 67.4,
    market_summary: 'BULL regime (conf=88%). Regime shifted from SIDEWAYS. Sector rotation into BANKING and IT.',
    top_opportunities: ['momentum: MOM_GEN3_001 fitness=84.2', 'Sector leader: BANKING avg_sent=72'],
    major_risks: ['[HIGH] risk_research: Sector Concentration: BANKING 48%', '[HIGH] market_research: Regime Change detected'],
    model_insights: ['LightGBM showing 12.4% drift — retraining recommended', 'Calibration quality: 58/100'],
    strategy_insights: ['86 strategies in population. Avg fitness 51.3', '2 resurrection candidates in BULL regime'],
    action_items: ['🔴 URGENT: Sector Concentration requires human review', '🟡 REVIEW: Model drift LightGBM'],
  },
  messages: [
    { from_agent: 'market_research', to_agent: 'cro',     message_type: 'finding', subject: 'Regime change detected', body: 'Market shifted SIDEWAYS→BULL.', priority: 2, created_at: new Date().toISOString() },
    { from_agent: 'risk_research',   to_agent: 'all',      message_type: 'alert',   subject: 'Sector concentration alert', body: 'BANKING at 48%.', priority: 2, created_at: new Date().toISOString() },
    { from_agent: 'cro',             to_agent: 'all',      message_type: 'broadcast', subject: 'Daily brief issued', body: '2 critical, 3 high findings.', priority: 3, created_at: new Date().toISOString() },
  ],
};

async function hydrateResearchOps() {
  const el = id => document.getElementById(id);
  const _set = (id, v) => { const e = el(id); if (e) e.textContent = v; };

  let agentData    = await Api.agents();
  let briefData    = await Api.todayBrief();
  let findingsData = await Api.findingsSummary(7);
  let msgData      = await Api.agentMessages(2);
  let perfData     = await Api.agentPerformance(30);

  const useMock = !agentData;
  if (useMock) {
    agentData    = { agents: MOCK_AGENT_DATA.agents };
    briefData    = MOCK_AGENT_DATA.brief;
    findingsData = { total: 5, critical: [], high: MOCK_AGENT_DATA.findings.filter(f => f.urgency === 'high'), by_urgency: { high: 2, normal: 3 } };
    msgData      = { messages: MOCK_AGENT_DATA.messages };
    perfData     = MOCK_AGENT_DATA.agents.map(a => ({ agent_id: a.agent_id, total_tasks: a.run_count, completed: a.run_count - a.error_count, failed: a.error_count, success_rate: 100 - (a.error_count / a.run_count * 100) }));
  }

  // ── KPIs ──────────────────────────────────────────────────────
  const agents = agentData?.agents || [];
  const errored = agents.filter(a => a.status === 'error').length;
  _set('roc-kpi-agents', agents.length);
  _set('roc-kpi-agent-status', errored ? `${errored} Errors` : 'All Nominal');
  _set('roc-kpi-findings', findingsData?.total ?? '—');
  _set('roc-kpi-critical', `${(findingsData?.by_urgency?.critical || 0)} Critical`);
  _set('roc-kpi-brief-status', briefData ? 'ISSUED' : 'PENDING');
  _set('roc-kpi-brief-date', briefData?.brief_date || '—');
  _set('roc-kpi-messages', (msgData?.messages || []).length);

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

    const sec = (label, items) => {
      if (!items || !items.length) return '';
      return `<div style="margin-bottom:10px"><div style="font-size:0.65rem;color:var(--text-muted);letter-spacing:0.08em;margin-bottom:4px">${label}</div>`
        + items.map(i => `<div style="padding:3px 0;border-bottom:1px solid var(--border-faint)">${i}</div>`).join('') + '</div>';
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
      ${sec('ACTION ITEMS', briefData.action_items)}
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
    const mockFindings = useMock ? MOCK_AGENT_DATA.findings : [];
    const displayFindings = allFindings.length ? allFindings : mockFindings;
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

  // ── Action Items ──────────────────────────────────────────────
  const actBody = el('roc-actions-body');
  if (actBody && briefData?.action_items) {
    const items = Array.isArray(briefData.action_items) ? briefData.action_items : [];
    actBody.innerHTML = items.map(item => {
      const isUrgent = item.includes('🔴');
      return `<div style="padding:8px 12px;margin-bottom:6px;border-radius:4px;font-size:0.76rem;
        background:${isUrgent ? 'rgba(239,68,68,0.08)' : 'rgba(251,191,36,0.06)'};
        border:1px solid ${isUrgent ? 'rgba(239,68,68,0.2)' : 'rgba(251,191,36,0.15)'}">
        ${item}
      </div>`;
    }).join('') || '<div style="color:var(--text-muted)">No action items</div>';
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
// HISTORICAL INTELLIGENCE VAULT — Phase 7.5
// ═══════════════════════════════════════════════════════════════

const MOCK_VAULT_DATA = {
  summary: {
    market_snapshots: 45, prediction_records: 2340, portfolio_records: 45,
    strategy_records: 1820, knowledge_records: 45, research_records: 312,
    oldest_snapshot: '2026-05-09', newest_snapshot: new Date().toISOString().split('T')[0],
  },
  snapshots: Array.from({ length: 14 }, (_, i) => {
    const d = new Date(); d.setDate(d.getDate() - (13 - i));
    return { snapshot_date: d.toISOString().split('T')[0], regime: i % 7 < 4 ? 'BULL' : 'SIDEWAYS',
      nifty_close: 24000 + i * 30, nifty_return_1d: (i % 3 - 1) * 0.6,
      market_sentiment: 55 + i * 1.2, knowledge_score: 57 + i * 0.5 };
  }),
  knowledge: Array.from({ length: 14 }, (_, i) => {
    const d = new Date(); d.setDate(d.getDate() - (13 - i));
    return { archive_date: d.toISOString().split('T')[0], knowledge_score: 57 + i * 0.5 };
  }),
  portfolio: Array.from({ length: 14 }, (_, i) => {
    const d = new Date(); d.setDate(d.getDate() - (13 - i));
    return { archive_date: d.toISOString().split('T')[0], total_value: 100000 + i * 250, total_pnl: i * 250 };
  }),
  research: [
    { archive_date: new Date().toISOString().split('T')[0], archive_type: 'brief',   agent_id: null,             title: 'Daily Brief — BULL',            urgency: null   },
    { archive_date: new Date().toISOString().split('T')[0], archive_type: 'finding', agent_id: 'risk_research',  title: 'Sector Concentration: 48%',     urgency: 'high' },
    { archive_date: new Date().toISOString().split('T')[0], archive_type: 'finding', agent_id: 'market_research',title: 'Regime shift detected',          urgency: 'high' },
  ],
  backups: [
    { backup_timestamp: '20260623_153000', backup_size_bytes: 2048000, vault_counts: { market_snapshots: 45, prediction_archive: 2340 } },
  ],
};

async function hydrateVault() {
  const _set = (id, v) => { const e = document.getElementById(id); if (e) e.textContent = v; };

  let summary    = await Api.vaultSummary();
  let snapData   = await Api.vaultSnapshots(14);
  let knowData   = await Api.archiveKnowledge(14);
  let portData   = await Api.archivePortfolio(14);
  let resData    = await Api.archiveResearch(30);
  let backupData = await Api.listBackups();
  let briefData  = await Api.vaultBriefs();

  if (!summary) {
    summary    = MOCK_VAULT_DATA.summary;
    snapData   = { snapshots: MOCK_VAULT_DATA.snapshots };
    knowData   = { records: MOCK_VAULT_DATA.knowledge };
    portData   = { records: MOCK_VAULT_DATA.portfolio };
    resData    = { records: MOCK_VAULT_DATA.research };
    backupData = { backups: MOCK_VAULT_DATA.backups };
    briefData  = { briefs: [] };
  }

  _set('vault-kpi-snapshots',   summary.market_snapshots ?? '—');
  _set('vault-kpi-oldest',      `oldest: ${summary.oldest_snapshot ?? '—'}`);
  _set('vault-kpi-predictions', summary.prediction_records ?? '—');
  _set('vault-kpi-strategies',  summary.strategy_records ?? '—');
  _set('vault-kpi-research',    summary.research_records ?? '—');
  _set('vault-kpi-knowledge',   summary.knowledge_records ?? '—');
  _set('vault-kpi-portfolio',   summary.portfolio_records ?? '—');

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


// ══════════════════════════════════════════════════════════
// PHASE 8M — DATA INTELLIGENCE CENTER
// ══════════════════════════════════════════════════════════

const ChartRegistryDI = {};

async function hydrateDataIntelligence() {
  const _set = (id, v) => { const e = document.getElementById(id); if (e) e.textContent = v; };

  // ── Quality Dashboard ──
  const quality = await Api.dataQuality(7);
  if (quality) {
    const avgScore = quality.avg_quality_score;
    _set('di-kpi-quality', avgScore != null ? avgScore.toFixed(0) : '—');
    const alertCount = (quality.alert_datasets || []).length;
    _set('di-kpi-quality-sub', `${alertCount} alert${alertCount !== 1 ? 's' : ''} · ${Object.keys(quality.datasets || {}).length} datasets`);
    // Convert dict to list for table render
    const alertSet = new Set(quality.alert_datasets || []);
    const dsArr = Object.entries(quality.datasets || {}).map(([name, d]) => ({ dataset_name: name, status: alertSet.has(name) ? 'degraded' : 'ok', ...d }));
    _renderQualityTable(dsArr);
  }

  // ── Source Health ──
  const health = await Api.sourceHealth();
  if (health?.sources) {
    const online = health.sources.filter(s => s.status === 'ok').length;
    _set('di-kpi-sources', online);
    _set('di-kpi-sources-sub', `of ${health.sources.length} monitored`);
    _mergeQualityWithHealth(health.sources);
  }

  // ── FII/DII ──
  const fiiData = await Api.fiiDii(30);
  if (fiiData) {
    const fii5d = fiiData.fii_5d_net;
    _set('di-kpi-fii', fii5d != null ? (fii5d >= 0 ? '+' : '') + fii5d.toFixed(0) : '—');
    _set('di-kpi-fii-sub', `Signal: ${fiiData.combined_signal || '—'}`);
    _set('di-fii-signal', fiiData.combined_signal || '—');
    _renderFiiChart(fiiData.fii || [], fiiData.dii || []);
  }

  // ── Market Breadth ──
  const breadth = await Api.marketBreadth();
  if (breadth) {
    const ad = breadth.advance_decline_ratio;
    _set('di-kpi-breadth', ad != null ? ad.toFixed(2) : '—');
    _set('di-kpi-breadth-sub', breadth.breadth_signal || '—');
    _set('di-breadth-signal', breadth.breadth_signal || '—');
  }
  const breadthHist = await Api.marketBreadthHistory(30);
  _renderBreadthChart(breadthHist || []);

  // ── Sector Rotation ──
  const sectors = await Api.sectorRotation();
  const secList = sectors?.sectors || [];
  const leading = secList.filter(s => s.rotation_phase === 'LEADING').length;
  _set('di-kpi-sectors', leading);
  _set('di-kpi-sectors-sub', `LEADING out of ${secList.length}`);
  _renderSectorTable(secList);

  // ── Options ──
  const opts = await Api.optionsSnapshot('NIFTY');
  if (opts) {
    _set('di-opt-pcr', opts.pcr_oi?.toFixed(2) ?? '—');
    _set('di-opt-maxpain', opts.max_pain?.toLocaleString('en-IN') ?? '—');
    _set('di-opt-iv', opts.atm_iv?.toFixed(2) ?? '—');
    _set('di-opt-skew', opts.iv_skew?.toFixed(4) ?? '—');
    _set('di-opt-call-strike', opts.highest_call_oi_strike?.toLocaleString('en-IN') ?? '—');
    _set('di-opt-put-strike', opts.highest_put_oi_strike?.toLocaleString('en-IN') ?? '—');
  }

  // ── Earnings Calendar ──
  const cal = await Api.earningsCalendar(14);
  const calList = cal?.calendar || [];
  _set('di-kpi-earnings', calList.length);
  _renderEarningsTable(calList);

  // ── Corporate Filings ──
  const corp = await Api.corporateFilings({ days: 30, limit: 50 });
  _renderCorpTable(corp?.filings || []);
}

function _renderFiiChart(fii, dii) {
  const canvas = document.getElementById('di-fii-chart');
  if (!canvas) return;
  const labels = fii.map(r => r.flow_date).reverse();
  const fiiNet = fii.map(r => r.net_investment ?? 0).reverse();
  const diiNet = dii.map(r => r.net_investment ?? 0).reverse();
  if (ChartRegistryDI['di-fii-chart']) { ChartRegistryDI['di-fii-chart'].destroy(); }
  ChartRegistryDI['di-fii-chart'] = new Chart(canvas, {
    type: 'bar',
    data: {
      labels,
      datasets: [
        { label: 'FII Net', data: fiiNet, backgroundColor: fiiNet.map(v => v >= 0 ? 'rgba(0,255,127,0.55)' : 'rgba(255,80,80,0.55)') },
        { label: 'DII Net', data: diiNet, backgroundColor: diiNet.map(v => v >= 0 ? 'rgba(100,180,255,0.55)' : 'rgba(255,150,50,0.55)') },
      ],
    },
    options: {
      responsive: true, maintainAspectRatio: false,
      plugins: { legend: { labels: { color: '#aaa', font: { size: 10 } } } },
      scales: {
        x: { ticks: { color: '#888', font: { size: 9 }, maxRotation: 45 }, grid: { color: 'rgba(255,255,255,0.04)' } },
        y: { ticks: { color: '#888', font: { size: 9 } }, grid: { color: 'rgba(255,255,255,0.04)' } },
      },
    },
  });
}

function _renderBreadthChart(history) {
  const canvas = document.getElementById('di-breadth-chart');
  if (!canvas || !history.length) return;
  const labels = history.map(r => r.breadth_date);
  const adRatio = history.map(r => r.advance_decline_ratio ?? null);
  if (ChartRegistryDI['di-breadth-chart']) { ChartRegistryDI['di-breadth-chart'].destroy(); }
  ChartRegistryDI['di-breadth-chart'] = new Chart(canvas, {
    type: 'line',
    data: {
      labels,
      datasets: [{
        label: 'A/D Ratio', data: adRatio, borderColor: '#00e5ff', backgroundColor: 'rgba(0,229,255,0.08)',
        borderWidth: 1.5, pointRadius: 0, fill: true,
      }],
    },
    options: {
      responsive: true, maintainAspectRatio: false,
      plugins: { legend: { display: false } },
      scales: {
        x: { ticks: { color: '#888', font: { size: 9 }, maxRotation: 45 }, grid: { color: 'rgba(255,255,255,0.04)' } },
        y: { ticks: { color: '#888', font: { size: 9 } }, grid: { color: 'rgba(255,255,255,0.04)' } },
      },
    },
  });
}

function _renderSectorTable(sectors) {
  const tbody = document.getElementById('di-sector-tbody');
  if (!tbody) return;
  if (!sectors.length) { tbody.innerHTML = '<tr><td colspan="8" style="text-align:center;color:var(--text-secondary)">No data</td></tr>'; return; }
  const phaseColor = { LEADING: '#00e676', WEAKENING: '#ffd740', LAGGING: '#ff5252', IMPROVING: '#40c4ff', NEUTRAL: '#aaa', UNKNOWN: '#666' };
  tbody.innerHTML = sectors.map(s => `
    <tr>
      <td>${s.sector}</td>
      <td style="color:${phaseColor[s.rotation_phase]??'#aaa'};font-weight:600">${s.rotation_phase || '—'}</td>
      <td>${s.rs_rank ?? '—'}</td>
      <td style="color:${(s.ret_20d??0)>=0?'#00e676':'#ff5252'}">${s.ret_20d!=null?s.ret_20d.toFixed(2)+'%':'—'}</td>
      <td style="color:${(s.ret_60d??0)>=0?'#00e676':'#ff5252'}">${s.ret_60d!=null?s.ret_60d.toFixed(2)+'%':'—'}</td>
      <td>${s.rs_vs_nifty_20d!=null?s.rs_vs_nifty_20d.toFixed(2):'—'}</td>
      <td>${s.avg_sentiment!=null?s.avg_sentiment.toFixed(1):'—'}</td>
      <td style="font-size:0.7rem">${(s.top_stocks||[]).slice(0,3).map(t=>t.symbol).join(', ')||'—'}</td>
    </tr>`).join('');
}

function _renderEarningsTable(calendar) {
  const tbody = document.getElementById('di-earnings-tbody');
  if (!tbody) return;
  if (!calendar.length) { tbody.innerHTML = '<tr><td colspan="5" style="text-align:center;color:var(--text-secondary)">No upcoming earnings</td></tr>'; return; }
  tbody.innerHTML = calendar.map(e => `
    <tr>
      <td>${e.earnings_date}</td>
      <td>${e.symbol}</td>
      <td style="font-size:0.72rem">${e.company_name||'—'}</td>
      <td>${e.period||'—'}</td>
      <td><span class="badge">${e.result_status||'scheduled'}</span></td>
    </tr>`).join('');
}

function _renderCorpTable(filings) {
  const tbody = document.getElementById('di-corp-tbody');
  if (!tbody) return;
  if (!filings.length) { tbody.innerHTML = '<tr><td colspan="5" style="text-align:center;color:var(--text-secondary)">No filings</td></tr>'; return; }
  tbody.innerHTML = filings.map(f => `
    <tr>
      <td>${f.filing_date}</td>
      <td>${f.symbol}</td>
      <td>${f.filing_type||'—'}</td>
      <td style="font-size:0.72rem;max-width:300px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">${f.subject||'—'}</td>
      <td>${f.impact_score!=null?f.impact_score.toFixed(0):'—'}</td>
    </tr>`).join('');
}

function _renderQualityTable(datasets) {
  const tbody = document.getElementById('di-quality-tbody');
  if (!tbody) return;
  if (!datasets.length) { tbody.innerHTML = '<tr><td colspan="7" style="text-align:center;color:var(--text-secondary)">No data</td></tr>'; return; }
  const gradeColor = { A: '#00e676', B: '#69f0ae', C: '#ffd740', D: '#ff9800', F: '#ff5252' };
  tbody.innerHTML = datasets.map(d => `
    <tr>
      <td>${d.dataset_name}</td>
      <td><span class="badge" style="background:${d.status==='ok'?'rgba(0,230,118,0.15)':'rgba(255,82,82,0.15)'};color:${d.status==='ok'?'#00e676':'#ff5252'}">${d.status||'—'}</span></td>
      <td style="color:${gradeColor[d.quality_grade]??'#aaa'};font-weight:700">${d.quality_grade||'—'}</td>
      <td>${d.quality_score!=null?d.quality_score.toFixed(0):'—'}</td>
      <td>${d.total_records!=null?d.total_records.toLocaleString():'—'}</td>
      <td>${d.freshness_hours!=null?d.freshness_hours.toFixed(1):'—'}</td>
      <td style="font-size:0.7rem">${d.last_success||'—'}</td>
    </tr>`).join('');
}

function _mergeQualityWithHealth(sources) {
  const tbody = document.getElementById('di-quality-tbody');
  if (!tbody || !tbody.querySelector('td[colspan]')) return;
  if (!sources.length) return;
  tbody.innerHTML = sources.map(s => `
    <tr>
      <td>${s.source_name}</td>
      <td><span class="badge" style="background:${s.status==='ok'?'rgba(0,230,118,0.15)':'rgba(255,82,82,0.15)'};color:${s.status==='ok'?'#00e676':'#ff5252'}">${s.status}</span></td>
      <td>—</td>
      <td>—</td>
      <td>${s.records_fetched??'—'}</td>
      <td>—</td>
      <td style="font-size:0.7rem">${s.last_success_at||'—'}</td>
    </tr>`).join('');
}

async function runDataSupremacyPipeline(btn) {
  const resEl = document.getElementById('di-pipeline-result');
  if (resEl) resEl.textContent = 'Running pipeline…';
  await _withBtnLoading(btn, async () => {
    const r = await Api.triggerDataSupremacy();
    if (resEl) resEl.textContent = r ? `Pipeline complete — ${r.steps_completed ?? '?'} steps` : 'Pipeline failed or backend offline.';
  });
  _liveHydrated.delete('data-intelligence');
  await hydrateDataIntelligence();
}

function _withBtnLoading(btn, fn) {
  if (!btn) return fn();
  const orig = btn.textContent;
  btn.textContent = 'Running…';
  btn.disabled = true;
  return Promise.resolve(fn()).finally(() => { btn.textContent = orig; btn.disabled = false; });
}

async function scrapeCorpFilings(btn) {
  await _withBtnLoading(btn, () => fetch(`${API_CONFIG.BASE}/corporate/scrape`, { method: 'POST' }));
  _liveHydrated.delete('data-intelligence');
  await hydrateDataIntelligence();
}

async function scrapeFiiDii(btn) {
  await _withBtnLoading(btn, () => fetch(`${API_CONFIG.BASE}/fii-dii/scrape`, { method: 'POST' }));
  _liveHydrated.delete('data-intelligence');
  await hydrateDataIntelligence();
}

async function computeBreadth(btn) {
  await _withBtnLoading(btn, () => fetch(`${API_CONFIG.BASE}/market-breadth/compute`, { method: 'POST' }));
  _liveHydrated.delete('data-intelligence');
  await hydrateDataIntelligence();
}

async function computeSectorRotation(btn) {
  await _withBtnLoading(btn, () => fetch(`${API_CONFIG.BASE}/sector-rotation/compute`, { method: 'POST' }));
  _liveHydrated.delete('data-intelligence');
  await hydrateDataIntelligence();
}

async function runQualityChecks(btn) {
  await _withBtnLoading(btn, () => fetch(`${API_CONFIG.BASE}/data-quality/run-checks`, { method: 'POST' }));
  _liveHydrated.delete('data-intelligence');
  await hydrateDataIntelligence();
}


// Patch nav to trigger live hydration on every page visit
const _originalRenderPage = renderPage;
const _liveHydrated = new Set(); // kept for manual cache-busting by action buttons

function renderPage(pageId) {
  _originalRenderPage(pageId);

  if (pageId === 'news')        hydrateNews();
  if (pageId === 'sentiment')   hydrateSentiment();
  if (pageId === 'market')      hydrateMarket();
  if (pageId === 'opportunity') hydrateOpportunities();
  if (pageId === 'model')       hydrateModelCenter();
  if (pageId === 'paper')       hydratePaperPortfolio();
  if (pageId === 'risk')        hydrateRisk();
  // learning: renderLearning() is fully live. _originalRenderPage calls it on first
  // visit; we only need hydrateLearnCenter (which re-runs renderLearning) on
  // repeat visits when _originalRenderPage is a no-op due to the rendered guard.
  if (pageId === 'learning' && _learningInitDone) hydrateLearnCenter();
  if (pageId === 'learning') _learningInitDone = true;
  if (pageId === 'strategy')    hydrateStrategyResearch();
  if (pageId === 'agents')           hydrateResearchOps();
  if (pageId === 'vault')            hydrateVault();
  if (pageId === 'data-intelligence') hydrateDataIntelligence();
  if (pageId === 'overview') {
    hydrateOverview();
    hydrateMarketRegime();
    hydrateOverviewPredictions();
    hydratePaperPortfolioStrip();
  }
  if (pageId === 'intelligence-lab') hydrateIntelligenceLab();
  if (pageId === 'live-prices')      hydrateLivePrices();
}

// ── Nav Badges — live counts from backend ────────────────────
async function refreshNavBadges() {
  const _b = (id, val) => { const e = el(id); if (e && val != null) e.textContent = val; };
  try {
    const [ov, preds, news, strats, agentData, findings] = await Promise.all([
      Api.overview().catch(() => null),
      Api.predictions({ limit: 50 }).catch(() => null),
      Api.news({ limit: 10 }).catch(() => null),
      Api.strategies().catch(() => null),
      Api.agents().catch(() => null),
      Api.findingsSummary().catch(() => null),
    ]);
    if (ov) {
      _b('badge-overview', ov.openPositions ?? ov.activePredictions ?? '—');
      if (ov.activeStrategies != null) _b('badge-strat', ov.activeStrategies);
      if (ov.knowledgeScore  != null) _b('badge-intel', ov.knowledgeScore.toFixed(1));
    }
    if (preds) {
      const bullish = preds.filter(p => (p.direction || '').toLowerCase().includes('bull')).length;
      _b('badge-opp', bullish || preds.length);
    }
    if (news) {
      _b('badge-news', Array.isArray(news) ? news.length : (news.total ?? news.count ?? '—'));
    }
    if (strats && !ov?.activeStrategies) {
      const count = strats.total ?? (Array.isArray(strats.strategies) ? strats.strategies.length : null) ?? (Array.isArray(strats) ? strats.length : null);
      _b('badge-strat', count ?? '—');
    }
    if (agentData) {
      const arr = agentData.agents || agentData;
      _b('badge-agents', Array.isArray(arr) ? arr.length : '—');
    }
    if (findings) {
      const critical = (findings.by_urgency?.critical || 0);
      const high     = (findings.by_urgency?.high || 0);
      _b('badge-risk', critical + high || findings.total || '—');
    }
  } catch (e) { /* silently skip */ }
}

// ── Topbar Live Ticker — real-time prices every 30s ───────────
let _topbarLiveTimer = null;
let _learningInitDone = false;

async function hydrateTopbarLive() {
  const data = await Api.topbarPrices();
  if (!data || !data.length) return;

  const nifty     = data.find(d => d.key === 'nifty50');
  const banknifty = data.find(d => d.key === 'banknifty');
  const vix       = data.find(d => d.key === 'vix' || d.label?.includes('VIX'));
  const usdinr    = data.find(d => d.key === 'usdinr');

  function applyTicker(valId, chgId, item, fmtFn) {
    if (!item || item.price == null) return;
    const valEl = el(valId);
    const chgEl = el(chgId);
    const fmt = fmtFn ? fmtFn(item.price) : item.price.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    if (valEl) valEl.textContent = fmt;
    if (chgEl) {
      const pct  = item.changePct || 0;
      const isUp = pct >= 0;
      chgEl.textContent = `${isUp ? '+' : ''}${pct.toFixed(2)}%`;
      chgEl.className   = 'ticker-change ' + (isUp ? 'positive' : 'negative');
    }
  }

  applyTicker('nifty-value',    'nifty-change',    nifty);
  applyTicker('banknifty-value','banknifty-change', banknifty);
  applyTicker('vix-value',      'vix-change',      vix,    v => v.toFixed(2));
  applyTicker('usdinr-value',   'usdinr-change',   usdinr, v => v.toFixed(2));

  // Also keep market page KPI cards in sync
  if (nifty && nifty.price != null) {
    const fmt = nifty.price.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    const pct = nifty.changePct || 0;
    const chgText = `${pct >= 0 ? '+' : ''}${pct.toFixed(2)}%`;
    const _s = (id, v) => { const e = el(id); if (e) e.textContent = v; };
    _s('market-nifty-val', fmt);
    const mChg = el('market-nifty-chg');
    if (mChg) { mChg.textContent = chgText; mChg.className = 'kpi-sub ' + (pct >= 0 ? 'positive' : 'negative'); }
  }
  if (banknifty && banknifty.price != null) {
    const fmt = banknifty.price.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    const pct = banknifty.changePct || 0;
    const chgText = `${pct >= 0 ? '+' : ''}${pct.toFixed(2)}%`;
    const _s = (id, v) => { const e = el(id); if (e) e.textContent = v; };
    _s('market-banknifty-val', fmt);
    const mChg = el('market-banknifty-chg');
    if (mChg) { mChg.textContent = chgText; mChg.className = 'kpi-sub ' + (pct >= 0 ? 'positive' : 'negative'); }
  }
}

function startTopbarLivePolling() {
  if (_topbarLiveTimer) clearInterval(_topbarLiveTimer);
  // Show loading state before first fetch resolves
  ['nifty-value','banknifty-value','vix-value','usdinr-value'].forEach(id => {
    const e = el(id); if (e && e.textContent === '—') e.textContent = '···';
  });
  hydrateTopbarLive();  // immediate first fetch
  _topbarLiveTimer = setInterval(hydrateTopbarLive, 5000);  // every 5s
}

// ── Live Prices — real-time index/commodity quotes ────────────
let _livePricesTimer = null;

async function hydrateLivePrices() {
  await refreshLivePrices();
  // Auto-refresh every 5 seconds while the page is visible
  if (_livePricesTimer) clearInterval(_livePricesTimer);
  _livePricesTimer = setInterval(() => {
    const page = document.getElementById('page-live-prices');
    if (page && page.classList.contains('active')) refreshLivePrices();
    else clearInterval(_livePricesTimer);
  }, 5000);
}

async function refreshLivePrices() {
  const grid      = document.getElementById('live-prices-grid');
  const tableBody = document.getElementById('live-prices-table-body');
  const updatedEl = document.getElementById('live-prices-updated');

  const data = await Api.livePrices();

  if (!data || !data.length) {
    if (grid) grid.innerHTML = '<div class="kpi-card" style="grid-column:1/-1;text-align:center;color:var(--text-muted)">Live prices unavailable — backend offline</div>';
    return;
  }

  if (updatedEl) updatedEl.textContent = 'Updated: ' + new Date().toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit', second: '2-digit' });

  // ── KPI grid ────────────────────────────────────────────────
  const ICONS = { nifty50: '◈', sensex: '◎', banknifty: '◉', niftyit: '▦', usdinr: '₹', gold: '◆', crude: '◉' };
  const FMT = {
    nifty50:   v => v.toLocaleString('en-IN', { maximumFractionDigits: 2 }),
    sensex:    v => v.toLocaleString('en-IN', { maximumFractionDigits: 2 }),
    banknifty: v => v.toLocaleString('en-IN', { maximumFractionDigits: 2 }),
    niftyit:   v => v.toLocaleString('en-IN', { maximumFractionDigits: 2 }),
    usdinr:    v => '₹' + v.toFixed(2),
    gold:      v => '$' + v.toLocaleString('en-IN', { maximumFractionDigits: 2 }),
    crude:     v => '$' + v.toFixed(2),
  };

  if (grid) {
    grid.innerHTML = data.map(d => {
      if (d.price == null) return `
        <div class="kpi-card" style="text-align:center">
          <div class="kpi-label">${ICONS[d.key] || '◎'} ${d.label}</div>
          <div class="kpi-value" style="color:var(--text-muted)">—</div>
          <div class="kpi-sub">Unavailable</div>
        </div>`;
      const isUp    = (d.changePct || 0) >= 0;
      const color   = isUp ? 'var(--positive)' : 'var(--negative)';
      const arrow   = isUp ? '▲' : '▼';
      const sign    = isUp ? '+' : '';
      const fmtFn   = FMT[d.key] || (v => v.toLocaleString('en-IN', { maximumFractionDigits: 2 }));
      return `
        <div class="kpi-card" style="text-align:center;border-color:${isUp ? 'rgba(255,140,0,0.2)' : 'rgba(255,51,51,0.2)'}">
          <div class="kpi-label">${ICONS[d.key] || '◎'} ${d.label}</div>
          <div class="kpi-value" style="color:${color};font-size:1.05rem">${fmtFn(d.price)}</div>
          <div class="kpi-sub" style="color:${color}">${arrow} ${sign}${d.change != null ? Math.abs(d.change).toLocaleString('en-IN', {maximumFractionDigits:2}) : '—'} (${sign}${(d.changePct || 0).toFixed(2)}%)</div>
        </div>`;
    }).join('');
  }

  // ── Table ────────────────────────────────────────────────────
  if (tableBody) {
    tableBody.innerHTML = data.map(d => {
      if (d.price == null) return `<tr><td>${d.label}</td><td colspan="4" style="color:var(--text-muted)">Unavailable</td></tr>`;
      const isUp  = (d.changePct || 0) >= 0;
      const cls   = isUp ? 'positive' : 'negative';
      const sign  = isUp ? '+' : '';
      const fmtFn = FMT[d.key] || (v => v.toLocaleString('en-IN', { maximumFractionDigits: 2 }));
      return `
        <tr>
          <td><strong>${d.label}</strong></td>
          <td>${fmtFn(d.price)}</td>
          <td class="${cls}">${sign}${d.change != null ? d.change.toLocaleString('en-IN', {maximumFractionDigits:2}) : '—'}</td>
          <td class="${cls}">${sign}${(d.changePct || 0).toFixed(2)}%</td>
          <td><span style="color:${isUp?'var(--positive)':'var(--negative)'};font-size:1.1rem">${isUp ? '▲' : '▼'}</span></td>
        </tr>`;
    }).join('');
  }

  // ── Charts: Nifty50 + Sensex history from DB ─────────────────
  const [niftyHist, sensexHist] = await Promise.all([
    Api.indexHistory('NIFTY50', 30).catch(() => null),
    Api.indexHistory('BANKNIFTY', 30).catch(() => null),
  ]);

  function buildHistChart(canvasId, histData, label, color) {
    // API returns a flat array directly
    const hist = Array.isArray(histData) ? histData : (histData?.history || []);
    if (!hist.length) return;
    ChartRegistry.create(canvasId, {
      type: 'line',
      data: {
        labels: hist.map(h => h.date?.slice(5)),
        datasets: [{
          label,
          data: hist.map(h => h.close),
          borderColor: color,
          borderWidth: 2,
          pointRadius: 0,
          tension: 0.3,
          fill: true,
          backgroundColor: (ctx) => {
            const g = ctx.chart.ctx.createLinearGradient(0, 0, 0, ctx.chart.height);
            const rgba = (a) => color.startsWith('rgb(') ? color.replace('rgb(', 'rgba(').replace(')', `,${a})`) : color;
            g.addColorStop(0, rgba(0.18));
            g.addColorStop(1, rgba(0.00));
            return g;
          },
        }],
      },
      options: {
        responsive: true, maintainAspectRatio: true,
        plugins: { legend: { display: false }, tooltip: { callbacks: { label: ctx => ` ${ctx.parsed.y.toLocaleString('en-IN', {maximumFractionDigits:2})}` }}},
        scales: {
          x: { ticks: { maxTicksLimit: 8, maxRotation: 0 }, grid: { color: '#0d0d0d' }},
          y: { ticks: { maxTicksLimit: 5, callback: v => v.toLocaleString('en-IN', {maximumFractionDigits:0}) }, grid: { color: '#0d0d0d' }},
        },
      },
    });
  }

  buildHistChart('liveNiftyChart',  niftyHist,  'Nifty 50',  'rgb(255,140,0)');
  buildHistChart('liveSensexChart', sensexHist, 'Bank Nifty', 'rgb(0,170,255)');
}

// ── Risk Center — live hydration ─────────────────────────────
async function hydrateRisk() {
  const data = await Api.risk();
  if (!data) return;

  // Sector exposure doughnut
  if (data.sectorExposure && data.sectorExposure.length) {
    const exp = data.sectorExposure;
    ChartRegistry.create('sectorExposureChart', {
      type: 'doughnut',
      data: {
        labels: exp.map(e => e.sector),
        datasets: [{
          data: exp.map(e => e.weight),
          backgroundColor: exp.map((_, i) => [
            'rgba(255,140,0,0.8)', 'rgba(34,197,94,0.6)', 'rgba(59,130,246,0.6)',
            'rgba(245,158,11,0.6)', 'rgba(239,68,68,0.6)', 'rgba(147,51,234,0.6)',
            'rgba(236,72,153,0.6)', 'rgba(255,255,255,0.1)',
          ][i % 8]),
          borderWidth: 1, borderColor: 'rgba(255,255,255,0.06)',
        }],
      },
      options: {
        responsive: true, maintainAspectRatio: true,
        plugins: {
          legend: { position: 'right', labels: { font: { size: 11 } } },
          tooltip: { callbacks: { label: ctx => ` ${ctx.label}: ${ctx.parsed.toFixed(1)}%` } },
        },
        cutout: '50%',
      },
    });
  }

  // Drawdown history chart
  if (data.drawdownHistory && data.drawdownHistory.length) {
    const hist = data.drawdownHistory;
    ChartRegistry.create('drawdownChart', {
      type: 'line',
      data: {
        labels: hist.map(h => h.date),
        datasets: [{
          label: 'Drawdown %',
          data: hist.map(h => h.drawdown || 0),
          borderColor: '#ef4444', borderWidth: 1.5, pointRadius: 0, tension: 0.3, fill: true,
          backgroundColor: 'rgba(239,68,68,0.12)',
        }],
      },
      options: {
        responsive: true, maintainAspectRatio: true,
        plugins: { legend: { display: false } },
        scales: { y: { ticks: { callback: v => `${v}%` } }, x: { ticks: { maxTicksLimit: 8 } } },
      },
    });
  }

  // Position risk table
  if (data.positions) {
    const tbody = el('risk-position-body');
    if (tbody) {
      if (data.positions.length) {
        tbody.innerHTML = data.positions.map(p => `
          <tr>
            <td><strong>${p.symbol}</strong></td>
            <td>${p.weight}</td>
            <td class="negative">${p.var != null ? `₹${p.var.toFixed(0)}` : '—'}</td>
            <td>${p.volatility != null ? `${p.volatility.toFixed(1)}%` : '—'}</td>
            <td>${riskBadge(p.riskLevel || 'Medium')}</td>
          </tr>`).join('');
      } else {
        tbody.innerHTML = '<tr><td colspan="5" style="color:var(--text-muted);text-align:center">No open positions</td></tr>';
      }
    }
  }

  // Update KPI values
  const _set = (id, val) => { const e = el(id); if (e) e.textContent = val; };
  if (data.exposure != null)       _set('risk-exposure',   `${data.exposure}%`);
  if (data.varDaily != null) {
    _set('risk-var-daily',  `−₹${Math.abs(data.varDaily).toFixed(0)}`);
    const varPctEl = el('risk-var-pct');
    if (varPctEl && data.varPct != null) varPctEl.textContent = `−${Math.abs(data.varPct).toFixed(2)}% of Capital`;
  }
  if (data.maxDrawdown30d != null) _set('risk-max-dd',     `${data.maxDrawdown30d.toFixed(2)}%`);
  if (data.sharpe != null)         _set('risk-sharpe',     data.sharpe.toFixed(2));

  // Largest position (sort by numeric weight descending)
  if (data.positions && data.positions.length) {
    const sorted = [...data.positions].sort((a, b) => {
      const wa = parseFloat(String(a.weight || '0').replace('%', '')) || 0;
      const wb = parseFloat(String(b.weight || '0').replace('%', '')) || 0;
      return wb - wa;
    });
    const largest = sorted[0];
    _set('risk-largest-pos', largest.symbol || '—');
    _set('risk-largest-weight', largest.weight || '—');
  }

  // Circuit breaker status
  if (data.circuitStatus) {
    const statusEl = el('circuit-breaker-status');
    if (statusEl) {
      statusEl.textContent = data.circuitStatus;
      statusEl.className = 'kpi-value ' + (data.circuitStatus === 'TRIGGERED' ? 'negative' : 'positive');
    }
  }

  // Live risk alerts panel — replace mock data
  const alertsBody = el('risk-alerts-body');
  if (alertsBody) {
    const alerts = [];
    if (data.circuitStatus === 'TRIGGERED') alerts.push({ level: 'critical', title: 'Circuit Breaker Triggered', desc: 'One or more drawdown limits breached. Trading paused.' });
    if (data.exposure > 70) alerts.push({ level: 'warning', title: 'High Exposure', desc: `Portfolio exposure at ${data.exposure.toFixed(1)}% — approaching 80% limit.` });
    if (data.maxDrawdown30d && Math.abs(data.maxDrawdown30d) > 5) alerts.push({ level: 'warning', title: 'Drawdown Alert', desc: `Max drawdown at ${Math.abs(data.maxDrawdown30d).toFixed(2)}% over 30 days.` });
    if (data.sharpe < 0.5 && data.sharpe !== 0) alerts.push({ level: 'info', title: 'Low Sharpe Ratio', desc: `Sharpe at ${data.sharpe.toFixed(2)} — risk-adjusted returns below target of 1.0.` });
    if (data.positions && data.positions.some(p => p.riskLevel === 'High')) alerts.push({ level: 'warning', title: 'High-Risk Positions', desc: 'One or more positions flagged as high volatility.' });
    if (!data.positions || data.positions.length === 0) alerts.push({ level: 'info', title: 'No Open Positions', desc: 'Portfolio is fully in cash. Run a paper trade cycle to deploy capital.' });

    if (alerts.length) {
      alertsBody.innerHTML = alerts.map(a => `
        <div class="risk-alert ${a.level}">
          <div class="risk-alert-title">${a.title}</div>
          <div class="risk-alert-sub">${a.desc}</div>
        </div>`).join('');
    } else {
      alertsBody.innerHTML = '<div class="risk-alert info"><div class="risk-alert-title">All Clear</div><div class="risk-alert-sub">No active risk alerts. All metrics within normal ranges.</div></div>';
    }
  }
}

// ── Learning Centre — live hydration ─────────────────────────
async function hydrateLearnCenter() {
  // renderLearning() is already fully live — re-run it to refresh all data + charts
  await renderLearning();
}

// ── Overview — full live hydration ───────────────────────────
async function hydrateOverview() {
  const [ov, curve] = await Promise.all([Api.overview(), Api.equityCurve(30)]);
  if (!ov) return;

  const _set = (id, val) => { const e = el(id); if (e) e.textContent = val; };
  if (ov.portfolioValue != null) {
    const pv = el('kpi-portfolio');
    if (pv) animateCounter(pv, Math.round(ov.portfolioValue), '₹', '', 1200);
  }
  if (ov.dailyPnl != null) {
    const pnlEl = el('kpi-daily-pnl');
    if (pnlEl) {
      pnlEl.textContent = `${ov.dailyPnl >= 0 ? '+' : ''}₹${Math.abs(Math.round(ov.dailyPnl)).toLocaleString('en-IN')}`;
      pnlEl.className = 'kpi-value ' + (ov.dailyPnl >= 0 ? 'positive' : 'negative');
    }
    const pctEl = el('kpi-daily-pct');
    if (pctEl) {
      pctEl.textContent = `${ov.dailyPnlPct >= 0 ? '+' : ''}${(ov.dailyPnlPct || 0).toFixed(2)}%`;
      pctEl.className = 'kpi-sub ' + (ov.dailyPnl >= 0 ? 'positive' : 'negative');
    }
  }
  if (ov.openPositions != null) {
    _set('kpi-positions', ov.openPositions);
    if (ov.deployedCapital != null) _set('kpi-deployed', `₹${Math.round(ov.deployedCapital).toLocaleString('en-IN')} Deployed`);
  }
  if (ov.activePredictions != null) {
    _set('kpi-predictions', ov.activePredictions);
    if (ov.avgConfidence != null) _set('kpi-avg-conf', `Avg Conf: ${(ov.avgConfidence||0).toFixed(0)}%`);
  }
  if (ov.winRate30d != null) {
    _set('kpi-winrate', `${ov.winRate30d.toFixed(1)}%`);
    if (ov.totalTrades30d != null) _set('kpi-trades-30d', `${ov.totalTrades30d} Trades`);
  }
  // Knowledge score: show "Computing" if 0 but system is running
  if (ov.knowledgeScore != null) {
    const ks = ov.knowledgeScore;
    _set('kpi-knowledge', ks > 0 ? `${Math.round(ks)} / 100` : 'Computing…');
    _set('kpi-knowledge-sub', ks > 0 ? `${ov.activeStrategies || 0} Active Strategies` : `${ov.activeStrategies || 0} Strategies Active`);
  }
  // Show strategy count on overview
  if (ov.activeStrategies != null) {
    const stratEl = el('kpi-strategies');
    if (stratEl) { stratEl.textContent = ov.activeStrategies; }
  }
  if (ov.regime) {
    _set('topbar-regime', ov.regime);
    const pill = document.getElementById('regime-pill');
    if (pill) pill.className = 'regime-badge badge-' + ov.regime.toLowerCase().replace(/\s+/g, '-');
  }

  // Nav badge — overview shows open position count
  if (ov.openPositions != null) {
    const ob = el('badge-overview');
    if (ob) ob.textContent = ov.openPositions;
  }

  // Equity curve
  if (curve && curve.labels && curve.labels.length) {
    ChartRegistry.create('equityCurveChart', {
      type: 'line',
      data: {
        labels: curve.labels,
        datasets: [{
          data: curve.values,
          borderColor: '#ff8c00', borderWidth: 2, pointRadius: 0, tension: 0.3, fill: true,
          backgroundColor: (ctx) => {
            const g = ctx.chart.ctx.createLinearGradient(0, 0, 0, ctx.chart.height);
            g.addColorStop(0, 'rgba(255,140,0,0.14)');
            g.addColorStop(1, 'rgba(255,140,0,0.00)');
            return g;
          },
        }],
      },
      options: {
        responsive: true, maintainAspectRatio: true,
        plugins: { legend: { display: false }, tooltip: { callbacks: { label: ctx => ` ₹${ctx.parsed.y.toLocaleString('en-IN')}` } } },
        scales: {
          x: { ticks: { maxTicksLimit: 8, maxRotation: 0 } },
          y: { ticks: { callback: v => `₹${(v / 1000).toFixed(0)}K`, maxTicksLimit: 5 } },
        },
      },
    });
  }

  // Top predictions table
  const preds = await Api.predictions({ limit: 8 });
  if (preds && preds.length) {
    const tbody = el('top-predictions-body');
    if (tbody) {
      tbody.innerHTML = preds.map(p => {
        const expRet = p.expectedReturn != null
          ? (p.expectedReturn >= 0 ? `+${p.expectedReturn.toFixed(2)}%` : `${p.expectedReturn.toFixed(2)}%`)
          : '—';
        return `
          <tr>
            <td><strong>${p.symbol}</strong></td>
            <td>${dirBadge(p.direction)}</td>
            <td>${confBarHTML(Math.round(p.confidence || 0))}</td>
            <td class="${(p.expectedReturn || 0) >= 0 ? 'positive' : 'negative'}">${expRet}</td>
            <td>${riskBadge(p.risk || 'Medium')}</td>
          </tr>`;
      }).join('');
    }
  }
}

// ── Market — full live hydration ──────────────────────────────
async function hydrateMarket() {
  hydrateMarketRegime();  // update regime badge

  const data = await Api.market();
  if (!data) return;

  // NIFTY / BANKNIFTY — topbar ticker + market page KPI cards
  const { indices, sectorStrength, topMovers } = data;
  const _set = (id, val) => { const e = el(id); if (e) e.textContent = val; };
  if (indices) {
    const nifty = indices.nifty50 || {};
    const bank  = indices.banknifty || {};

    if (nifty.value != null) {
      const fmt = nifty.value.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
      const niftyEl = el('nifty-value');
      if (niftyEl) niftyEl.textContent = fmt;
      _set('market-nifty-val', fmt);
      const pct = (nifty.returns || 0) * 100;
      const chgText = `${pct >= 0 ? '+' : ''}${pct.toFixed(2)}%`;
      const chgCls  = pct >= 0 ? 'positive' : 'negative';
      const niftyChg = el('nifty-change');
      if (niftyChg) { niftyChg.textContent = chgText; niftyChg.className = 'ticker-change ' + chgCls; }
      const mNiftyChg = el('market-nifty-chg');
      if (mNiftyChg) { mNiftyChg.textContent = chgText; mNiftyChg.className = 'kpi-sub ' + chgCls; }
    }
    if (bank.value != null) {
      const fmt = bank.value.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
      const bankEl = el('banknifty-value');
      if (bankEl) bankEl.textContent = fmt;
      _set('market-banknifty-val', fmt);
      const pct = (bank.returns || 0) * 100;
      const chgText = `${pct >= 0 ? '+' : ''}${pct.toFixed(2)}%`;
      const chgCls  = pct >= 0 ? 'positive' : 'negative';
      const bankChg = el('banknifty-change');
      if (bankChg) { bankChg.textContent = chgText; bankChg.className = 'ticker-change ' + chgCls; }
      const mBankChg = el('market-banknifty-chg');
      if (mBankChg) { mBankChg.textContent = chgText; mBankChg.className = 'kpi-sub ' + chgCls; }
    }
  }

  // Market breadth — fetch separately
  Api.marketBreadth().then(breadth => {
    if (!breadth) return;
    const adv = breadth.advancing || breadth.advancers || 0;
    const dec = breadth.declining || breadth.decliners || 0;
    const total = adv + dec;
    if (total > 0) {
      const pct = Math.round(adv / total * 100);
      _set('market-breadth-val', `${pct}%`);
      _set('market-breadth-sub', `${adv} Adv / ${dec} Dec`);
      const bEl = el('market-breadth-val');
      if (bEl) bEl.className = 'kpi-value ' + (pct >= 50 ? 'positive' : 'negative');
    }
  });

  // Sector strength bar chart + detail cards
  if (sectorStrength && sectorStrength.length) {
    ChartRegistry.create('sectorStrengthChart', {
      type: 'bar',
      data: {
        labels: sectorStrength.map(s => s.name),
        datasets: [{
          label: 'Strength Score',
          data: sectorStrength.map(s => s.score),
          backgroundColor: sectorStrength.map(s =>
            s.score >= 80 ? 'rgba(34,197,94,0.7)'
            : s.score >= 60 ? 'rgba(255,140,0,0.7)'
            : s.score >= 45 ? 'rgba(245,158,11,0.6)'
            : 'rgba(239,68,68,0.6)'
          ),
          borderRadius: 4, borderSkipped: false,
        }],
      },
      options: {
        indexAxis: 'y', responsive: true, maintainAspectRatio: true,
        plugins: { legend: { display: false } },
        scales: { x: { min: 0, max: 100, ticks: { stepSize: 20 } }, y: { ticks: { font: { size: 11 } } } },
      },
    });

    const sectorDetail = el('sector-detail-body');
    if (sectorDetail) {
      sectorDetail.innerHTML = sectorStrength.map(s => {
        const col = s.score >= 75 ? 'var(--positive)' : s.score >= 50 ? 'var(--accent)' : s.score >= 35 ? 'var(--warning)' : 'var(--negative)';
        return `
          <div class="sector-card">
            <div class="sector-row">
              <span class="sector-name">${s.name}</span>
              <span class="sector-score" style="color:${col}">${s.score}</span>
            </div>
            <div class="score-bar-track">
              <div class="score-bar-fill" style="width:${s.score}%; background:${col}"></div>
            </div>
            <div class="sector-meta">
              <span>RS: ${s.rs || '—'}</span>
              <span>Momentum: ${s.momentum || '—'}</span>
            </div>
          </div>`;
      }).join('');
    }
  }

  // Top movers table
  if (topMovers && topMovers.length) {
    const moversBody = el('top-movers-body');
    if (moversBody) {
      moversBody.innerHTML = topMovers.map(m => {
        const pct = (m.change || 0) * 100;
        return `
          <tr>
            <td><strong>${m.symbol}</strong></td>
            <td style="color:var(--text-muted)">${m.sector || '—'}</td>
            <td>${m.price != null ? m.price.toFixed(2) : '—'}</td>
            <td class="${m.direction === 'up' ? 'positive' : 'negative'}">${pct >= 0 ? '+' : ''}${pct.toFixed(2)}%</td>
            <td style="color:var(--text-muted)">—</td>
          </tr>`;
      }).join('');
    }
  }
}

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
    const data = await API.get('/api/v1/regime-datasets');
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
    const data = await API.get('/api/v1/meta-learning?limit=20');
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
    await API.post('/api/v1/meta-learning/run');
    _liveHydrated.delete('intelligence-lab');
    await loadMetaLearningInsights();
  } catch (e) {
    document.getElementById('il-meta-body').innerHTML = '<tr><td colspan="6" style="color:var(--negative);text-align:center">Error running analysis</td></tr>';
  }
}

async function loadFeatureProposals() {
  const tbody = document.getElementById('il-proposals-body');
  try {
    const data = await API.get('/api/v1/feature-proposals');
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
  try {
    await API.post(`/api/v1/feature-proposals/${pid}/approve`);
    _liveHydrated.delete('intelligence-lab');
    await loadFeatureProposals();
  } catch (e) {
    alert('Failed to approve proposal: ' + e.message);
  }
}

async function runFeatureDiscovery() {
  document.getElementById('il-proposals-body').innerHTML = '<tr><td colspan="5" style="color:var(--accent);text-align:center">Discovering features…</td></tr>';
  try {
    await API.post('/api/v1/feature-proposals/discover');
    _liveHydrated.delete('intelligence-lab');
    await loadFeatureProposals();
  } catch (e) {
    document.getElementById('il-proposals-body').innerHTML = '<tr><td colspan="5" style="color:var(--negative);text-align:center">Error</td></tr>';
  }
}

async function loadModelMemory() {
  const tbody = document.getElementById('il-model-memory-body');
  try {
    const data = await API.get('/api/v1/model-memory');
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
    const data = await API.get('/api/v1/strategy-memory');
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
    const data = await API.get('/api/v1/research-memory/latest');
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
    const data = await API.get('/api/v1/failure-patterns');
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
    const data = await API.get('/api/v1/prediction-patterns');
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
    const res = await API.post('/api/v1/replay', body);
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
    const data = await API.get('/api/v1/replay/history');
    if (!data.length) { el.textContent = 'No replay history yet'; return; }
    el.innerHTML = data.slice(0, 5).map(d =>
      `<div style="padding:2px 0">${d.replay_type} — ${d.scope_label} — ${(d.created_at || '').substring(0, 16)}</div>`
    ).join('');
  } catch (e) {
    el.textContent = 'No history available';
  }
}

async function runIntelligencePipeline() {
  const status = document.getElementById('il-pipeline-status');
  const result = document.getElementById('il-pipeline-result');
  status.textContent = '⟳ Running…';
  status.style.color = 'var(--accent)';
  result.textContent = '';
  try {
    const res = await Api.triggerIntelligence();
    const errors = res.errors || 0;
    status.style.color = errors > 0 ? 'var(--warning)' : 'var(--positive)';
    status.textContent = errors > 0 ? `⚠ ${res.status}` : `✓ ${res.status}`;
    const steps = res.steps || {};
    result.innerHTML = Object.entries(steps).map(([k, v]) =>
      `<div style="display:flex;justify-content:space-between;padding:2px 0">
         <span style="color:var(--text-secondary)">${k.replace(/_/g,' ')}</span>
         <span style="color:${v.status === 'ok' ? 'var(--positive)' : 'var(--negative)'}">${v.status || '—'}</span>
       </div>`
    ).join('');
    _liveHydrated.delete('intelligence-lab');
    setTimeout(() => hydrateIntelligenceLab(), 500);
  } catch (e) {
    status.style.color = 'var(--negative)';
    status.textContent = 'Pipeline failed';
    result.textContent = e.message;
  }
}

// Re-register nav listeners: replace cloned nodes to clear stale listeners,
// then attach a single handler that both activates the page AND hydrates it.
document.querySelectorAll('.nav-item').forEach(item => {
  const clone = item.cloneNode(true);
  item.parentNode.replaceChild(clone, item);
  clone.addEventListener('click', () => {
    const pageId = clone.dataset.page;
    activatePage(pageId);
    renderPage(pageId);
  });
});

// ═══════════════════════════════════════════════════════════════
// STRATEGY TRADE LOG + REPLAY MODAL
// ═══════════════════════════════════════════════════════════════

let _stmChart = null;
let _stmCurrentId = null;

async function openStrategyTrades(strategyId) {
  _stmCurrentId = strategyId;

  // ── Inline inspector panel (strategy tab) ────────────────────
  const inspBody = document.getElementById('src-inspector-body');
  const inspLabel = document.getElementById('src-inspector-label');
  if (inspBody) {
    if (inspLabel) inspLabel.textContent = 'Loading…';
    inspBody.innerHTML = '<div style="padding:1rem;color:var(--text-muted);font-size:0.8rem">Fetching backtest trades…</div>';
  }

  const modal = document.getElementById('strategy-trades-modal');
  if (modal) modal.style.display = 'block';
  const _s = (id, v) => { const e = document.getElementById(id); if (e) e.textContent = v; };
  _s('stm-title', 'Loading…');
  _s('stm-kpi-trades', '…'); _s('stm-kpi-wr', '…'); _s('stm-kpi-sharpe', '…'); _s('stm-kpi-fitness', '…');
  const tradesBody = document.getElementById('stm-trades-body');
  if (tradesBody) tradesBody.innerHTML =
    '<tr><td colspan="9" style="text-align:center;color:var(--text-muted);padding:20px">Fetching trades…</td></tr>';
  const replayStatus = document.getElementById('stm-replay-status');
  if (replayStatus) replayStatus.textContent = '';

  const data = await apiFetch('/strategies/' + strategyId + '/trades');
  if (!data) {
    _s('stm-title', 'Error — backend offline');
    if (inspBody) inspBody.innerHTML = '<div style="padding:1rem;color:var(--negative)">Could not load trades — backend offline.</div>';
    return;
  }

  _s('stm-title', data.name || strategyId);
  const metaEl = document.getElementById('stm-meta');
  if (metaEl) metaEl.innerHTML =
    '<span>Family: ' + (data.family || '—') + '</span>' +
    '<span>Status: ' + (data.status || '').toUpperCase() + '</span>' +
    '<span>ID: ' + strategyId + '</span>';
  _s('stm-kpi-trades', data.trade_count || 0);
  _s('stm-kpi-wr',     data.win_rate  != null ? data.win_rate.toFixed(1)  + '%' : '—');
  _s('stm-kpi-sharpe', data.sharpe    != null ? data.sharpe.toFixed(2)         : '—');
  _s('stm-kpi-fitness',data.fitness   != null ? data.fitness.toFixed(1)        : '—');

  _stmDrawChart(data.equityCurve || [], (data.trades || []).map(t => t.exitDate || ''));

  const tradeRowsHtml = (data.trades && data.trades.length) ? data.trades.map((t, i) => {
    const col  = (t.pnlPct||0) > 0 ? 'var(--positive)' : (t.pnlPct||0) < 0 ? 'var(--negative)' : 'var(--text-muted)';
    const sign = (t.pnlPct||0) > 0 ? '+' : '';
    return '<tr style="border-bottom:1px solid var(--border-faint)">' +
      '<td style="padding:5px 8px;color:var(--text-muted)">' + (i+1) + '</td>' +
      '<td style="padding:5px 8px;font-weight:600">' + t.symbol + '</td>' +
      '<td style="padding:5px 8px;color:var(--text-muted);font-size:0.68rem">' + (t.entryDate||'—') + '</td>' +
      '<td style="padding:5px 8px;color:var(--text-muted);font-size:0.68rem">' + (t.exitDate||'—') + '</td>' +
      '<td style="padding:5px 8px;text-align:right">' + (t.entryPrice!=null?t.entryPrice.toFixed(2):'—') + '</td>' +
      '<td style="padding:5px 8px;text-align:right">' + (t.exitPrice!=null?t.exitPrice.toFixed(2):'—') + '</td>' +
      '<td style="padding:5px 8px;text-align:right;color:' + col + ';font-weight:600">' + (t.pnlPct!=null?sign+t.pnlPct.toFixed(2)+'%':'—') + '</td>' +
      '<td style="padding:5px 8px;text-align:right;color:var(--text-muted)">' + (t.holdingDays||0) + '</td>' +
      '<td style="padding:5px 8px;color:var(--text-muted);font-size:0.68rem">' + (t.exitReason||'—') + '</td>' +
      '</tr>';
  }).join('') : '<tr><td colspan="9" style="text-align:center;color:var(--text-muted);padding:20px">No backtest trades yet. Click Replay Backtest to generate them.</td></tr>';

  const tbody = document.getElementById('stm-trades-body');
  if (tbody) tbody.innerHTML = tradeRowsHtml;

  // ── Update inline inspector panel on strategy tab ─────────────
  if (inspBody) {
    if (inspLabel) inspLabel.textContent = data.name || strategyId;
    const statusColor = { active: 'var(--positive)', promoted: 'var(--accent)', shadow: 'var(--text-muted)' }[data.status] || 'var(--text-muted)';
    const wins  = (data.trades || []).filter(t => (t.pnlPct||0) > 0).length;
    const total = (data.trades || []).length;
    inspBody.innerHTML = `
      <div style="display:grid;grid-template-columns:repeat(4,1fr);gap:8px;padding:10px 0;border-bottom:1px solid var(--border-faint);margin-bottom:8px">
        <div style="text-align:center"><div style="font-size:0.65rem;color:var(--text-muted)">STATUS</div><div style="font-size:0.75rem;font-weight:700;color:${statusColor}">${(data.status||'—').toUpperCase()}</div></div>
        <div style="text-align:center"><div style="font-size:0.65rem;color:var(--text-muted)">FITNESS</div><div style="font-size:0.75rem;font-weight:700;color:var(--accent)">${data.fitness!=null?data.fitness.toFixed(1):'—'}</div></div>
        <div style="text-align:center"><div style="font-size:0.65rem;color:var(--text-muted)">SHARPE</div><div style="font-size:0.75rem;font-weight:700">${data.sharpe!=null?data.sharpe.toFixed(2):'—'}</div></div>
        <div style="text-align:center"><div style="font-size:0.65rem;color:var(--text-muted)">WIN RATE</div><div style="font-size:0.75rem;font-weight:700;color:var(--positive)">${data.win_rate!=null?data.win_rate.toFixed(0)+'%':'—'}</div></div>
      </div>
      <div style="font-size:0.68rem;color:var(--text-muted);padding:0 0 8px;font-family:var(--font-mono)">${data.family||''} — Gen ${data.generation||0} — ${total} trades (${wins}W/${total-wins}L)</div>
      <div style="max-height:200px;overflow-y:auto">
        <table class="data-table compact" style="font-size:0.68rem">
          <thead><tr><th>#</th><th>Symbol</th><th>Entry</th><th>Exit</th><th>P&L%</th><th>Days</th><th>Reason</th></tr></thead>
          <tbody>${total ? (data.trades||[]).slice(0,20).map((t,i) => {
            const c = (t.pnlPct||0)>0?'var(--positive)':(t.pnlPct||0)<0?'var(--negative)':'var(--text-muted)';
            const s = (t.pnlPct||0)>0?'+':'';
            return `<tr><td style="color:var(--text-muted)">${i+1}</td><td><b>${t.symbol}</b></td><td style="color:var(--text-muted)">${t.entryDate||'—'}</td><td style="color:var(--text-muted)">${t.exitDate||'—'}</td><td style="color:${c};font-weight:600">${t.pnlPct!=null?s+t.pnlPct.toFixed(2)+'%':'—'}</td><td style="color:var(--text-muted)">${t.holdingDays||0}d</td><td style="color:var(--text-muted)">${t.exitReason||'—'}</td></tr>`;
          }).join('') : '<tr><td colspan="7" style="color:var(--text-muted);text-align:center;padding:10px">No trades</td></tr>'}</tbody>
        </table>
      </div>`;
  }
}

function _stmDrawChart(values, labels) {
  const canvas = document.getElementById('stm-equity-chart');
  if (!canvas) return;
  if (_stmChart) { _stmChart.destroy(); _stmChart = null; }
  if (!values.length) return;
  _stmChart = new Chart(canvas, {
    type: 'line',
    data: {
      labels: labels,
      datasets: [
        { label: 'Equity', data: values, borderColor: '#ff8c00', borderWidth: 2,
          pointRadius: values.length > 60 ? 0 : 3, tension: 0.3, fill: true,
          backgroundColor: function(ctx){ const g=ctx.chart.ctx.createLinearGradient(0,0,0,ctx.chart.height); g.addColorStop(0,'rgba(255,140,0,0.14)'); g.addColorStop(1,'rgba(255,140,0,0.00)'); return g; } },
        { label: 'Base', data: new Array(values.length).fill(100), borderColor: 'rgba(255,255,255,0.15)', borderWidth: 1, borderDash: [4,4], pointRadius: 0 },
      ],
    },
    options: {
      responsive: true, maintainAspectRatio: true, animation: { duration: 400 },
      plugins: { legend: { display: false } },
      scales: {
        x: { ticks: { maxTicksLimit: 10, maxRotation: 0, font: { size: 9 } }, grid: { color: 'rgba(255,255,255,0.04)' } },
        y: { ticks: { font: { size: 9 } }, grid: { color: 'rgba(255,255,255,0.04)' } },
      },
    },
  });
}

async function runStrategyReplay() {
  if (!_stmCurrentId) return;
  const btn    = document.getElementById('stm-replay-btn');
  const status = document.getElementById('stm-replay-status');
  if (btn) { btn.disabled = true; btn.textContent = 'Replaying…'; }
  if (status) status.textContent = 'Running backtest…';
  try {
    const data = await apiPost('/strategies/' + _stmCurrentId + '/replay');
    if (!data || !data.frames) { if (status) status.textContent = 'Replay failed'; return; }
    if (status) status.textContent = data.trade_count + ' trades · sharpe ' + (data.sharpe||0).toFixed(2) + ' · equity ' + (data.finalEquity||100).toFixed(1);

    const frames = data.frames;
    if (_stmChart) { _stmChart.destroy(); _stmChart = null; }
    const canvas = document.getElementById('stm-equity-chart');
    if (!canvas) return;
    const eqData = new Array(frames.length).fill(null);
    _stmChart = new Chart(canvas, {
      type: 'line',
      data: {
        labels: frames.map(f => f.exitDate || '—'),
        datasets: [
          { label: 'Equity', data: eqData, borderColor: '#ff8c00', borderWidth: 2,
            pointRadius: frames.length > 80 ? 0 : 4,
            pointBackgroundColor: frames.map(f => f.result==='win'?'rgba(34,197,94,0.9)':f.result==='loss'?'rgba(239,68,68,0.9)':'rgba(255,255,255,0.3)'),
            tension: 0.2, fill: true, backgroundColor: 'rgba(255,140,0,0.06)' },
          { label: 'Base', data: new Array(frames.length).fill(100), borderColor: 'rgba(255,255,255,0.12)', borderWidth: 1, borderDash: [4,4], pointRadius: 0 },
        ],
      },
      options: {
        responsive: true, maintainAspectRatio: true, animation: false,
        plugins: { legend: { display: false } },
        scales: {
          x: { ticks: { maxTicksLimit: 10, font: { size: 9 } }, grid: { color: 'rgba(255,255,255,0.04)' } },
          y: { ticks: { font: { size: 9 } }, grid: { color: 'rgba(255,255,255,0.04)' } },
        },
      },
    });

    const tbody = document.getElementById('stm-trades-body');
    if (tbody) {
      tbody.innerHTML = frames.map(function(f, idx) {
        const col  = f.result==='win'?'var(--positive)':f.result==='loss'?'var(--negative)':'var(--text-muted)';
        const sign = (f.pnlPct||0) > 0 ? '+' : '';
        return '<tr id="stm-row-' + idx + '" style="border-bottom:1px solid var(--border-faint)">' +
          '<td style="padding:5px 8px;color:var(--text-muted)">' + (idx+1) + '</td>' +
          '<td style="padding:5px 8px;font-weight:600">' + f.symbol + '</td>' +
          '<td style="padding:5px 8px;color:var(--text-muted);font-size:0.68rem">' + (f.entryDate||'—') + '</td>' +
          '<td style="padding:5px 8px;color:var(--text-muted);font-size:0.68rem">' + (f.exitDate||'—') + '</td>' +
          '<td style="padding:5px 8px;text-align:right">' + (f.entryPrice!=null?f.entryPrice.toFixed(2):'—') + '</td>' +
          '<td style="padding:5px 8px;text-align:right">' + (f.exitPrice!=null?f.exitPrice.toFixed(2):'—') + '</td>' +
          '<td style="padding:5px 8px;text-align:right;color:' + col + ';font-weight:600">' + (f.pnlPct!=null?sign+f.pnlPct.toFixed(2)+'%':'—') + '</td>' +
          '<td style="padding:5px 8px;text-align:right;color:var(--text-muted)">' + (f.holdingDays||0) + '</td>' +
          '<td style="padding:5px 8px;color:var(--text-muted);font-size:0.68rem">' + (f.exitReason||'—') + '</td>' +
          '</tr>';
      }).join('');
    }

    let i = 0;
    const delay = Math.max(10, Math.min(80, 3000 / frames.length));
    (function step() {
      if (i >= frames.length) return;
      eqData[i] = frames[i].equityAfter;
      _stmChart.data.datasets[0].data = eqData.slice();
      _stmChart.update('none');
      const row = document.getElementById('stm-row-' + i);
      if (row) {
        row.style.background = frames[i].result==='win'?'rgba(34,197,94,0.08)':frames[i].result==='loss'?'rgba(239,68,68,0.08)':'';
        row.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
      }
      i++;
      setTimeout(step, delay);
    }());
  } finally {
    if (btn) { btn.disabled = false; btn.textContent = '▶ Replay Backtest'; }
  }
}

function closeStrategyTradesModal() {
  const modal = document.getElementById('strategy-trades-modal');
  if (modal) modal.style.display = 'none';
  if (_stmChart) { _stmChart.destroy(); _stmChart = null; }
  _stmCurrentId = null;
}

document.addEventListener('click', function(e) {
  const modal = document.getElementById('strategy-trades-modal');
  if (modal && e.target === modal) closeStrategyTradesModal();
});
