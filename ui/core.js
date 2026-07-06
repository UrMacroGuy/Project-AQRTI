// ui/core.js - split from app.js (ARCH-5), see CHANGELOG
/**
 * AQRTI Intelligence Terminal — app.js
 * UI shell hydrated entirely from the live backend API — no mock data.
 *
 * Architecture: page renderers plus a Chart registry to prevent canvas
 * reuse errors.
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

function setDataPoint(id, value, source, timestamp) {
  const e = el(id);
  if (!e) return;
  e.textContent = value;
  const ts = timestamp || new Date().toISOString();
  e.title = `Source: ${source || 'live_api'} | ${ts}`;
}

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
  strategy:            'Algo Lab',
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

  // Sync F-key strip active state
  document.querySelectorAll('.fkey-btn').forEach(btn => {
    btn.classList.remove('active-page');
  });
  const fkeyMap = {
    'overview': 'fk-overview', 'market': 'fk-market', 'opportunity': 'fk-opportunity',
    'live-prices': 'fk-live-prices', 'news': 'fk-news', 'strategy': 'fk-strategy',
    'paper': 'fk-paper', 'risk': 'fk-risk', 'model': 'fk-model',
    'learning': 'fk-learning', 'agents': 'fk-agents', 'screener': 'fk-screener',
  };
  const fkActive = el(fkeyMap[pageId]);
  if (fkActive) fkActive.classList.add('active-page');

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
  { icon: '▣', label: 'Algo Research',     hint: 'Leaderboard · Replay',  page: 'strategy' },
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

// ── Bloomberg F-key physical keyboard shortcuts ───────────────
const _fkeyPageMap = {
  F1:  'overview', F2: 'market',     F3: 'opportunity', F4: 'live-prices',
  F5:  'news',     F6: 'strategy',   F7: 'paper',       F8: 'risk',
  F9:  'model',    F10: 'learning',  F11: 'agents',     F12: 'screener',
};
document.addEventListener('keydown', (e) => {
  // Only activate F-keys when not typing in an input
  const tag = (e.target.tagName || '').toUpperCase();
  if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return;
  if (e.altKey || e.ctrlKey || e.metaKey) return;
  const page = _fkeyPageMap[e.key];
  if (page) { e.preventDefault(); activatePage(page); renderPage(page); }
});

// ── Bloomberg GO> command bar ─────────────────────────────────
// Behaves like Bloomberg terminal: type a mnemonic and press Enter
const _bbgCommands = {
  // Page mnemonics
  'GO':    'overview',  'OV':    'overview',  'HP':  'overview',
  'MKT':  'market',    'MRKT':  'market',    'IM':  'market',
  'SIG':  'opportunity','TRADE':'opportunity','OPP': 'opportunity',
  'LIVE': 'live-prices','PX':   'live-prices','GPRT':'live-prices',
  'NI':   'news',       'NEWS': 'news',       'TOP': 'news',
  'SENT': 'sentiment',  'SENT1':'sentiment',
  'ANLT': 'analytics',  'AN':   'analytics',
  'STRAT':'strategy',   'ST':   'strategy',   'EVL': 'strategy',
  'MDL':  'model',      'ML':   'model',
  'LRN':  'learning',   'INTEL':'learning',
  'RSK':  'risk',       'RISK': 'risk',       'VRA': 'risk',
  'PORT': 'paper',      'PPT':  'paper',      'PA':  'paper',
  'AGT':  'agents',     'ROP':  'agents',
  'VLT':  'vault',      'ARCH': 'vault',
  'SCRN': 'screener',   'EQS':  'screener',
  'DI':   'data-intelligence', 'DATA': 'data-intelligence',
  'ARENA':'arena',      'ART':  'arena',
};

document.addEventListener('DOMContentLoaded', () => {
  const bbgInput = document.getElementById('bbg-cmd-input');
  if (!bbgInput) return;

  bbgInput.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') {
      e.preventDefault();
      const cmd = bbgInput.value.trim().toUpperCase();
      bbgInput.value = '';
      if (!cmd) return;

      // Check if it's a page mnemonic
      const page = _bbgCommands[cmd];
      if (page) {
        activatePage(page);
        renderPage(page);
        return;
      }

      // F1-F12 shortcuts: "GO<F1>" style
      const fMatch = cmd.match(/^(?:GO)?F(\d{1,2})$/);
      if (fMatch) {
        const fNum = parseInt(fMatch[1]);
        const fPage = Object.values(_fkeyPageMap)[fNum - 1];
        if (fPage) { activatePage(fPage); renderPage(fPage); }
        return;
      }

      // Treat as symbol search → go to screener with prefilled symbol
      // or fall through to command palette
      openCmdPalette();
      const palette = document.getElementById('cmd-palette-input');
      if (palette) { palette.value = cmd; renderCmdResults(cmd); }
    }
    if (e.key === 'Escape') { bbgInput.value = ''; bbgInput.blur(); }
  });

  // Ctrl+L or `/` focuses the command bar (Bloomberg-like)
  document.addEventListener('keydown', (ev) => {
    if ((ev.ctrlKey && ev.key === 'l') || (ev.key === '/' && document.activeElement.tagName !== 'INPUT' && document.activeElement.tagName !== 'TEXTAREA')) {
      ev.preventDefault();
      bbgInput.focus();
      bbgInput.select();
    }
  });
});

// ══════════════════════════════════════════════════════════════
// NEWS TICKER STRIP — Bloomberg amber bar hydration
// ══════════════════════════════════════════════════════════════
async function hydratePipelineHealthBanner() {
  const banner = el('pipeline-fail-banner');
  const detail = el('pipeline-fail-detail');
  if (!banner) return;
  try {
    const h = await Api.systemHealth();
    if (!h) { banner.style.display = 'none'; return; }
    if (h.overall_ok === false && !h.stale) {
      const msgs = (h.failures || []).join(' · ') || 'unknown failure';
      if (detail) detail.textContent = `Checked ${h.checked_at ? new Date(h.checked_at).toLocaleTimeString('en-IN') : '—'}: ${msgs}`;
      banner.style.display = 'flex';
    } else {
      banner.style.display = 'none';
    }
  } catch (_) {
    banner.style.display = 'none';
  }
}

async function hydrateWatchdogRestartPill() {
  const pill  = el('watchdog-restart-pill');
  const label = el('watchdog-restart-label');
  if (!pill) return;
  try {
    const r = await Api.systemRestartLog();
    if (!r || r.total_restarts === 0 || r.age_minutes == null) {
      pill.style.display = 'none';
      return;
    }
    const ago = r.age_minutes < 60
      ? `${r.age_minutes}m ago`
      : `${Math.round(r.age_minutes / 60)}h ago`;
    if (label) label.textContent = `restarted ${ago}`;
    pill.style.display = 'flex';
    pill.title = `Watchdog auto-restarted backend ${ago} (${r.total_restarts} total). Reason: ${r.last_restart?.reason || '—'}`;
  } catch (_) {
    pill.style.display = 'none';
  }
}

// ══════════════════════════════════════════════════════════════
// GO-1 / GO-7 / GO-8: Go/No-Go Scorecard hydration
// ══════════════════════════════════════════════════════════════

async function hydrateGoNogo() {
  const condEl    = el('gonogo-conditions');
  const quarEl    = el('gonogo-quarantine');
  const sigEl     = el('gonogo-signals');
  const bannerEl  = el('gonogo-overall-banner');
  if (!condEl) return;

  let data = null;
  try { data = await Api.goNogo(); } catch (_) {}

  if (!data) {
    if (condEl) condEl.innerHTML = '<div style="grid-column:1/-1;color:var(--text-muted);padding:24px;text-align:center">Backend unavailable — start the backend server to see scorecard.</div>';
    return;
  }

  // ── Overall banner ───────────────────────────────────────────
  if (bannerEl) {
    const overallColor = data.overall === 'green' ? '#22c55e' : data.overall === 'partial' ? '#f59e0b' : '#ef4444';
    const overallIcon  = data.overall === 'green' ? '✅ ALL CLEAR' : data.overall === 'partial' ? '⚠️ PARTIAL' : '❌ NOT READY';
    bannerEl.style.cssText = `margin-bottom:20px;padding:12px 16px;border-radius:6px;font-size:0.8rem;letter-spacing:0.06em;background:${overallColor}18;border:1px solid ${overallColor}40;color:${overallColor};font-weight:600`;
    bannerEl.textContent = overallIcon + (data.overall === 'green' ? ' — All 5 conditions met. Ready for real capital.' : data.overall === 'partial' ? ' — Some conditions met. Not ready for real capital.' : ' — Conditions not met. Do NOT trade real capital.');
    bannerEl.style.display = 'block';
  }

  // ── Condition cards ──────────────────────────────────────────
  function condCard(c) {
    const color = c.status === 'green' ? '#22c55e' : c.status === 'partial' ? '#f59e0b' : '#ef4444';
    const icon  = c.status === 'green' ? '✅' : c.status === 'partial' ? '⚠️' : '❌';
    return `<div style="background:var(--card-bg);border:1px solid ${color}40;border-left:3px solid ${color};border-radius:6px;padding:14px 16px">
      <div style="font-size:1rem">${icon} <strong style="color:${color}">${c.label}</strong></div>
      <div style="color:var(--text-muted);font-size:0.78rem;margin-top:6px">${c.detail}</div>
    </div>`;
  }
  condEl.innerHTML = (data.conditions || []).map(condCard).join('');

  // ── Quarantine progress ──────────────────────────────────────
  if (quarEl) {
    const algos = data.quarantine_algos || [];
    if (algos.length === 0) {
      quarEl.innerHTML = '<span style="color:var(--text-muted)">No promoted algos yet — quarantine clock hasn\'t started.</span>';
    } else {
      const rows = algos.map(a => {
        const ok = a.quarantine_ok;
        const rowColor = ok ? '#22c55e' : '#f59e0b';
        const gates = a.gates || {};
        const gateHtml = [
          ['>=60d', gates.days_60],
          ['>=20 trades', gates.trades_20],
          ['>=50% WR', gates.wr_50pct],
          ['+P&L', gates.positive_pnl],
        ].map(([lbl, v]) =>
          `<span style="margin-right:8px;color:${v ? '#22c55e' : '#6b7280'}">${v ? '✓' : '○'} ${lbl}</span>`
        ).join('');
        return `<tr style="border-bottom:1px solid var(--border-faint)">
          <td style="padding:8px 6px;color:${rowColor};font-size:0.8rem">${ok ? '✅' : '⏳'} ${a.name}</td>
          <td style="padding:8px 6px;font-size:0.78rem;color:var(--text-muted)">${a.strategy_id}</td>
          <td style="padding:8px 6px;text-align:right;font-size:0.78rem">${a.days_in_quarantine}d</td>
          <td style="padding:8px 6px;text-align:right;font-size:0.78rem">${a.shadow_trades}</td>
          <td style="padding:8px 6px;text-align:right;font-size:0.78rem">${a.shadow_wr}%</td>
          <td style="padding:8px 6px;text-align:right;font-size:0.78rem;color:${a.net_pnl >= 0 ? '#22c55e' : '#ef4444'}">₹${a.net_pnl.toLocaleString('en-IN', {minimumFractionDigits:0, maximumFractionDigits:0})}</td>
          <td style="padding:8px 6px;font-size:0.72rem">${gateHtml}</td>
        </tr>`;
      }).join('');
      quarEl.innerHTML = `<div style="overflow-x:auto"><table style="width:100%;border-collapse:collapse;font-size:0.78rem">
        <thead><tr style="border-bottom:1px solid var(--border-faint)">
          <th style="text-align:left;padding:6px;color:var(--text-muted);font-weight:500">Algo</th>
          <th style="text-align:left;padding:6px;color:var(--text-muted);font-weight:500">ID</th>
          <th style="text-align:right;padding:6px;color:var(--text-muted);font-weight:500">Days</th>
          <th style="text-align:right;padding:6px;color:var(--text-muted);font-weight:500">Trades</th>
          <th style="text-align:right;padding:6px;color:var(--text-muted);font-weight:500">WR</th>
          <th style="text-align:right;padding:6px;color:var(--text-muted);font-weight:500">Net P&L</th>
          <th style="text-align:left;padding:6px;color:var(--text-muted);font-weight:500">Gates</th>
        </tr></thead>
        <tbody>${rows}</tbody>
      </table></div>`;
    }
  }

  // ── Actionable signals ───────────────────────────────────────
  if (sigEl) {
    const sigs = data.actionable_signals || [];
    if (sigs.length === 0) {
      sigEl.innerHTML = '<span style="color:var(--text-muted)">No open positions from promoted algos — nothing actionable today.</span>';
    } else {
      const rows = sigs.map(s => {
        const pnlColor = (s.current_pnl_pct || 0) >= 0 ? '#22c55e' : '#ef4444';
        return `<tr style="border-bottom:1px solid var(--border-faint)">
          <td style="padding:8px 6px;font-weight:600;font-size:0.82rem">${s.symbol}</td>
          <td style="padding:8px 6px;font-size:0.78rem;color:var(--text-muted)">${s.algo_name}</td>
          <td style="padding:8px 6px;font-size:0.78rem">${s.direction || '—'}</td>
          <td style="padding:8px 6px;font-size:0.78rem;color:var(--text-muted)">${s.entry_date || '—'}</td>
          <td style="padding:8px 6px;text-align:right;font-size:0.78rem">₹${(s.entry_price || 0).toLocaleString('en-IN', {minimumFractionDigits:2, maximumFractionDigits:2})}</td>
          <td style="padding:8px 6px;text-align:right;font-size:0.82rem;color:${pnlColor}">${(s.current_pnl_pct || 0) >= 0 ? '+' : ''}${s.current_pnl_pct}%</td>
        </tr>`;
      }).join('');
      sigEl.innerHTML = `<div style="overflow-x:auto"><table style="width:100%;border-collapse:collapse;font-size:0.78rem">
        <thead><tr style="border-bottom:1px solid var(--border-faint)">
          <th style="text-align:left;padding:6px;color:var(--text-muted);font-weight:500">Symbol</th>
          <th style="text-align:left;padding:6px;color:var(--text-muted);font-weight:500">Algo</th>
          <th style="text-align:left;padding:6px;color:var(--text-muted);font-weight:500">Direction</th>
          <th style="text-align:left;padding:6px;color:var(--text-muted);font-weight:500">Entry Date</th>
          <th style="text-align:right;padding:6px;color:var(--text-muted);font-weight:500">Entry Price</th>
          <th style="text-align:right;padding:6px;color:var(--text-muted);font-weight:500">P&L %</th>
        </tr></thead>
        <tbody>${rows}</tbody>
      </table></div>`;
    }
  }
}

async function hydrateGoNogoUptime() {
  const el = id => document.getElementById(id);
  const uptimeEl = el('gonogo-uptime');
  if (!uptimeEl) return;

  let rows = null;
  try { rows = await Api.goNogoUptimeLog(); } catch (_) {}

  if (!rows || !Array.isArray(rows) || rows.length === 0) {
    uptimeEl.innerHTML = '<span style="color:var(--text-muted)">No health check records yet — pipeline watchdog not running.</span>';
    return;
  }

  const greenCount = rows.filter(r => r.overall_ok).length;
  const dots = rows.map(r => {
    const color   = r.overall_ok ? '#22c55e' : '#ef4444';
    const dt      = r.checked_at ? new Date(r.checked_at).toLocaleDateString('en-IN') : '—';
    const tooltip = `${dt}: ${r.overall_ok ? 'OK' : 'FAILED'}${r.failures ? ' — ' + r.failures : ''}`;
    return `<span title="${tooltip}" style="display:inline-block;width:14px;height:14px;border-radius:3px;background:${color};margin:2px;cursor:default"></span>`;
  }).join('');

  uptimeEl.innerHTML = `
    <div style="margin-bottom:8px;font-size:0.78rem;color:var(--text-muted)">${greenCount}/${rows.length} checks green (most recent on right)</div>
    <div style="display:flex;flex-wrap:wrap;gap:2px">${dots}</div>
    <div style="margin-top:6px;font-size:0.72rem;color:var(--text-muted)">
      <span style="display:inline-block;width:10px;height:10px;background:#22c55e;border-radius:2px;margin-right:4px"></span>Green = pipeline OK
      <span style="display:inline-block;width:10px;height:10px;background:#ef4444;border-radius:2px;margin-right:4px;margin-left:12px"></span>Red = check failed
    </div>`;
}

async function hydrateGoNogoMonthlyReview() {
  const el = id => document.getElementById(id);
  const mrEl = el('gonogo-monthly-review');
  if (!mrEl) return;

  let data = null;
  try { data = await Api.goNogoMonthlyReview(); } catch (_) {}

  if (!data) {
    mrEl.innerHTML = '<span style="color:var(--text-muted)">Backend unavailable.</span>';
    return;
  }

  if (data.no_data) {
    mrEl.innerHTML = `<span style="color:var(--text-muted)">${data.empty_reason || 'No data yet.'}</span>`;
    return;
  }

  const uptime = data.uptime || {};
  const algos = data.algo_reviews || [];

  let algoHtml = '';
  if (algos.length > 0) {
    const rows = algos.map(a => {
      const wrDiff = a.wr_vs_backtest_pp;
      const wrColor = wrDiff == null ? '#888' : wrDiff >= 0 ? '#22c55e' : '#ef4444';
      return `<tr style="border-bottom:1px solid var(--border-faint)">
        <td style="padding:7px 6px;font-size:0.8rem;font-weight:500">${a.name}</td>
        <td style="padding:7px 6px;text-align:right;font-size:0.78rem">${a.backtest_win_rate != null ? (a.backtest_win_rate * 100).toFixed(1) + '%' : '—'}</td>
        <td style="padding:7px 6px;text-align:right;font-size:0.78rem">${a.live_30d_win_rate != null ? a.live_30d_win_rate + '%' : '—'}</td>
        <td style="padding:7px 6px;text-align:right;font-size:0.78rem;color:${wrColor}">${wrDiff != null ? (wrDiff >= 0 ? '+' : '') + wrDiff + 'pp' : '—'}</td>
        <td style="padding:7px 6px;text-align:right;font-size:0.78rem">${a.live_30d_trades}</td>
        <td style="padding:7px 6px;text-align:right;font-size:0.78rem;color:${a.live_30d_net_pnl >= 0 ? '#22c55e' : '#ef4444'}">Rs ${a.live_30d_net_pnl.toLocaleString('en-IN', {minimumFractionDigits:0, maximumFractionDigits:0})}</td>
      </tr>`;
    }).join('');
    algoHtml = `<div style="overflow-x:auto;margin-bottom:16px"><table style="width:100%;border-collapse:collapse;font-size:0.78rem">
      <thead><tr style="border-bottom:1px solid var(--border-faint)">
        <th style="text-align:left;padding:5px;color:var(--text-muted);font-weight:500">Algo</th>
        <th style="text-align:right;padding:5px;color:var(--text-muted);font-weight:500">BT WR%</th>
        <th style="text-align:right;padding:5px;color:var(--text-muted);font-weight:500">Live WR%</th>
        <th style="text-align:right;padding:5px;color:var(--text-muted);font-weight:500">Diff</th>
        <th style="text-align:right;padding:5px;color:var(--text-muted);font-weight:500">Trades</th>
        <th style="text-align:right;padding:5px;color:var(--text-muted);font-weight:500">Net P&L</th>
      </tr></thead>
      <tbody>${rows}</tbody>
    </table></div>`;
  }

  const cr = data.cost_reconciliation || {};
  mrEl.innerHTML = `
    <div style="font-size:0.76rem;color:var(--text-muted);margin-bottom:12px">Period: ${data.month_start} to ${data.report_date} &nbsp;|&nbsp; Uptime: ${uptime.checks_green ?? '—'}/${uptime.checks_total ?? '—'} checks (${uptime.uptime_pct ?? '—'}%)</div>
    ${algoHtml}
    <div style="font-size:0.74rem;color:var(--text-muted);padding:8px 12px;background:var(--card-bg);border:1px solid var(--border-faint);border-radius:4px">
      <strong style="color:var(--text-primary)">Cost reconciliation:</strong> ${cr.note || '—'}
      ${cr.real_cost_pct != null ? ` | Real cost: <strong>${cr.real_cost_pct}%</strong> vs modeled ${cr.modeled_cost_pct}%` : ''}
    </div>`;
}

async function hydrateGoNogoRiskRails() {
  const el = id => document.getElementById(id);
  const railsEl = el('gonogo-risk-rails');
  if (!railsEl) return;

  let data = null;
  try { data = await Api.goNogoRiskRails(); } catch (_) {}

  if (!data || !data.rules) {
    railsEl.innerHTML = '<span style="color:var(--text-muted);font-size:0.8rem">Could not load risk rails.</span>';
    return;
  }

  const rows = data.rules.map(r => `
    <div style="border:1px solid var(--border-faint);border-left:3px solid #f59e0b;border-radius:5px;padding:10px 14px;margin-bottom:8px">
      <div style="font-size:0.8rem;font-weight:600;color:#f59e0b">Rule ${r.id}: ${r.rule}</div>
      <div style="font-size:0.76rem;color:var(--text-muted);margin-top:4px">${r.detail}</div>
    </div>`).join('');

  railsEl.innerHTML = rows + `<div style="font-size:0.72rem;color:var(--text-muted);margin-top:8px;padding:8px 12px;background:var(--card-bg);border-radius:4px;border:1px solid var(--border-faint)">${data.note || ''}</div>`;
}

// ══════════════════════════════════════════════════════════════
// GO-7: Morning Decision Screen hydration
// ══════════════════════════════════════════════════════════════

async function hydrateMorningDecision() {
  const panelEl = document.getElementById('morning-decision-panel');
  const logEl   = document.getElementById('morning-act-log');
  if (!panelEl) return;

  let data = null;
  try { data = await Api.morningDecision(); } catch (_) {}

  if (!data) {
    panelEl.innerHTML = '<div style="color:var(--text-muted);font-size:0.78rem;text-align:center;padding:16px">Backend unavailable — start the backend to see today\'s briefing.</div>';
    return;
  }

  const hasNoAction  = data.no_action;
  const noActionText = data.no_action_reason || '';

  // ── NO ACTION banner ────────────────────────────────────────
  let noActionHtml = '';
  if (hasNoAction) {
    noActionHtml = `
      <div style="margin-bottom:14px;padding:12px 16px;background:rgba(239,68,68,0.1);border:1px solid rgba(239,68,68,0.4);border-radius:6px;display:flex;align-items:flex-start;gap:10px">
        <span style="font-size:1.2rem;color:#ef4444;flex-shrink:0">⛔</span>
        <div>
          <div style="color:#ef4444;font-weight:700;font-size:0.82rem;letter-spacing:0.04em;margin-bottom:4px">NO ACTION TODAY</div>
          <div style="color:var(--text-muted);font-size:0.76rem">${noActionText}</div>
        </div>
      </div>`;
  }

  // ── Regime + Risk posture bar ────────────────────────────────
  const regime      = data.regime || '—';
  const regimeDate  = data.regime_date || '';
  const posture     = data.risk_posture || 'normal';
  const cbOk        = data.circuit_breaker_ok;
  const postureIcon = posture === 'high' ? '🔴' : posture === 'elevated' ? '🟡' : '🟢';
  const postureCls  = posture === 'high' ? '#ef4444' : posture === 'elevated' ? '#f59e0b' : '#22c55e';
  const cbIcon      = cbOk === true ? '🟢' : cbOk === false ? '🔴' : '⚪';

  let regimeHtml = `
    <div style="display:flex;flex-wrap:wrap;gap:10px;margin-bottom:14px;font-size:0.76rem">
      <div style="padding:6px 12px;background:var(--card-bg);border:1px solid var(--border-faint);border-radius:4px;display:flex;align-items:center;gap:6px">
        <span style="font-weight:600;color:var(--text-primary)">Regime:</span>
        <span style="color:${regime === 'BULL' ? '#22c55e' : regime === 'BEAR' ? '#ef4444' : '#f59e0b'}">${regime}</span>
        ${regimeDate ? `<span style="color:var(--text-muted);font-size:0.68rem">(${regimeDate})</span>` : ''}
      </div>
      <div style="padding:6px 12px;background:var(--card-bg);border:1px solid var(--border-faint);border-radius:4px;display:flex;align-items:center;gap:6px">
        <span>${postureIcon}</span>
        <span style="font-weight:600;color:var(--text-primary)">Risk Posture:</span>
        <span style="color:${postureCls};text-transform:uppercase">${posture}</span>
      </div>
      <div style="padding:6px 12px;background:var(--card-bg);border:1px solid var(--border-faint);border-radius:4px;display:flex;align-items:center;gap:6px">
        <span>${cbIcon}</span>
        <span style="font-weight:600;color:var(--text-primary)">Circuit Breaker:</span>
        <span style="color:${cbOk === true ? '#22c55e' : cbOk === false ? '#ef4444' : '#888'}">${cbOk === true ? 'OK' : cbOk === false ? 'TRIPPED' : 'No data'}</span>
      </div>
      <div style="padding:6px 12px;background:var(--card-bg);border:1px solid var(--border-faint);border-radius:4px;font-size:0.72rem;color:var(--text-muted)">
        Date: ${data.date || '—'} · ${data.promoted_algo_count || 0} promoted algo(s)
      </div>
    </div>`;

  // ── Signals table ────────────────────────────────────────────
  let signalsHtml = '';
  const sigs = data.signals || [];

  if (!hasNoAction && sigs.length > 0) {
    const rows = sigs.map(s => {
      const dirCls   = (s.direction || '').toLowerCase().includes('bull') ? '#22c55e' : '#ef4444';
      const pnlCls   = (s.current_pnl_pct || 0) >= 0 ? '#22c55e' : '#ef4444';
      const wrColor  = s.shadow_wr != null ? (s.shadow_wr >= 50 ? '#22c55e' : '#ef4444') : '#888';
      return `<tr style="border-bottom:1px solid var(--border-faint)">
        <td style="padding:8px 6px;font-weight:600;font-size:0.82rem">${s.symbol}</td>
        <td style="padding:8px 6px;font-size:0.78rem;color:var(--text-muted)">${s.algo_name}</td>
        <td style="padding:8px 6px;font-size:0.78rem;color:${dirCls}">${s.direction || '—'}</td>
        <td style="padding:8px 6px;text-align:right;font-size:0.78rem;color:${pnlCls}">${(s.current_pnl_pct || 0) >= 0 ? '+' : ''}${s.current_pnl_pct}%</td>
        <td style="padding:8px 6px;text-align:right;font-size:0.78rem;color:var(--text-muted)">₹${(s.position_size_inr || 0).toLocaleString('en-IN')}</td>
        <td style="padding:8px 6px;font-size:0.78rem;color:var(--text-muted)">${s.stop_loss_pct != null ? (s.stop_loss_pct * 100).toFixed(1) + '%' : '—'}</td>
        <td style="padding:8px 6px;font-size:0.78rem;color:var(--text-muted)">${s.take_profit_pct != null ? (s.take_profit_pct * 100).toFixed(1) + '%' : '—'}</td>
        <td style="padding:8px 6px;font-size:0.78rem;color:var(--text-muted)">${s.confidence != null ? s.confidence + '%' : '—'}</td>
        <td style="padding:8px 6px;text-align:right;font-size:0.78rem">${s.quarantine_days}d</td>
        <td style="padding:8px 6px;text-align:right;font-size:0.78rem">${s.shadow_trades}</td>
        <td style="padding:8px 6px;text-align:right;font-size:0.78rem;color:${wrColor}">${s.shadow_wr != null ? s.shadow_wr + '%' : '—'}</td>
      </tr>`;
    }).join('');

    signalsHtml = `
      <div style="overflow-x:auto;margin-bottom:8px">
        <div style="font-size:0.72rem;font-weight:700;letter-spacing:0.08em;color:var(--text-muted);margin-bottom:6px">
          TODAY'S ACTIONABLE SIGNALS — Open paper trades on promoted algos (cap: ₹${(data.position_cap_inr || 1000).toLocaleString('en-IN')}/trade)
        </div>
        <table style="width:100%;border-collapse:collapse;font-size:0.76rem">
          <thead><tr style="border-bottom:1px solid var(--border-faint)">
            <th style="text-align:left;padding:5px;color:var(--text-muted);font-weight:500">Symbol</th>
            <th style="text-align:left;padding:5px;color:var(--text-muted);font-weight:500">Algo</th>
            <th style="text-align:left;padding:5px;color:var(--text-muted);font-weight:500">Dir</th>
            <th style="text-align:right;padding:5px;color:var(--text-muted);font-weight:500">P&L%</th>
            <th style="text-align:right;padding:5px;color:var(--text-muted);font-weight:500">Size ₹</th>
            <th style="text-align:left;padding:5px;color:var(--text-muted);font-weight:500">SL</th>
            <th style="text-align:left;padding:5px;color:var(--text-muted);font-weight:500">TP</th>
            <th style="text-align:left;padding:5px;color:var(--text-muted);font-weight:500">Conf</th>
            <th style="text-align:right;padding:5px;color:var(--text-muted);font-weight:500">Q-Days</th>
            <th style="text-align:right;padding:5px;color:var(--text-muted);font-weight:500">Tr</th>
            <th style="text-align:right;padding:5px;color:var(--text-muted);font-weight:500">WR</th>
          </tr></thead>
          <tbody>${rows}</tbody>
        </table>
      </div>
      <div style="font-size:0.68rem;color:var(--text-muted);padding:6px 0">${data.note || 'Click "Acted" or "Skip" to log compliance — AQRTI never executes real trades.'}</div>`;
  } else if (!hasNoAction) {
    signalsHtml = '<div style="color:var(--text-muted);font-size:0.78rem;padding:8px 0">No open positions from promoted/active algos. All signals flat — no action needed.</div>';
  }

  // ── Act/Skip buttons (only when there are signals and no NO ACTION) ──
  let actHtml = '';
  if (!hasNoAction && sigs.length > 0) {
    const btnRows = sigs.map((s, i) => {
      const actId = `m-act-${i}`;
      const skipId = `m-skip-${i}`;
      return `<div style="display:flex;align-items:center;gap:8px;padding:4px 0;border-bottom:1px solid var(--border-faint);font-size:0.76rem">
        <span style="flex:0 0 100px;font-weight:600">${s.symbol}</span>
        <span style="flex:0 0 120px;color:var(--text-muted);font-size:0.72rem">${s.algo_name}</span>
        <button id="${actId}" class="btn-sm" style="background:rgba(34,197,94,0.15);border:1px solid rgba(34,197,94,0.4);color:#22c55e" onclick="morningAct('${s.strategy_id}','${s.symbol}','acted')">✓ Acted</button>
        <button id="${skipId}" class="btn-sm" style="background:rgba(239,68,68,0.1);border:1px solid rgba(239,68,68,0.3);color:#ef4444" onclick="morningAct('${s.strategy_id}','${s.symbol}','skipped')">✗ Skip</button>
        <span id="m-feedback-${i}" style="font-size:0.68rem;color:var(--text-muted)"></span>
      </div>`;
    }).join('');
    actHtml = `
      <div style="margin-top:12px;padding-top:10px;border-top:1px solid var(--border-faint)">
        <div style="font-size:0.7rem;font-weight:700;letter-spacing:0.08em;color:var(--text-muted);margin-bottom:6px">COMPLIANCE LOG — Did you act or skip this signal?</div>
        ${btnRows}
      </div>`;
  }

  panelEl.innerHTML = noActionHtml + regimeHtml + signalsHtml + actHtml;

  // ── Load act log ──────────────────────────────────────────────
  if (logEl) {
    let logData = null;
    try { logData = await Api.morningActLog(20); } catch (_) {}
    if (logData && Array.isArray(logData) && logData.length > 0) {
      const logRows = logData.map(r => `
        <tr style="border-bottom:1px solid var(--border-faint)">
          <td style="padding:4px 6px;font-size:0.72rem;color:var(--text-muted)">${r.trade_date}</td>
          <td style="padding:4px 6px;font-size:0.72rem;color:var(--text-muted)">${r.symbol}</td>
          <td style="padding:4px 6px;font-size:0.72rem">${r.strategy_id.slice(0, 16)}…</td>
          <td style="padding:4px 6px;font-size:0.72rem;color:${r.action === 'acted' ? '#22c55e' : '#ef4444'}">${r.action}</td>
          <td style="padding:4px 6px;font-size:0.68rem;color:var(--text-muted)">${r.regime || ''}${r.risk_posture ? ' · ' + r.risk_posture : ''}</td>
        </tr>`).join('');
      logEl.style.display = 'block';
      logEl.innerHTML = `
        <div style="background:var(--card-bg);border:1px solid var(--border-faint);border-radius:6px;padding:10px 14px">
          <div style="font-size:0.7rem;font-weight:700;letter-spacing:0.08em;color:var(--text-muted);margin-bottom:6px">RECENT ACT/SKIP LOG</div>
          <div style="overflow-x:auto"><table style="width:100%;border-collapse:collapse;font-size:0.74rem">
            <thead><tr style="border-bottom:1px solid var(--border-faint)">
              <th style="text-align:left;padding:3px 6px;color:var(--text-muted);font-weight:500">Date</th>
              <th style="text-align:left;padding:3px 6px;color:var(--text-muted);font-weight:500">Symbol</th>
              <th style="text-align:left;padding:3px 6px;color:var(--text-muted);font-weight:500">Algo</th>
              <th style="text-align:left;padding:3px 6px;color:var(--text-muted);font-weight:500">Action</th>
              <th style="text-align:left;padding:3px 6px;color:var(--text-muted);font-weight:500">Context</th>
            </tr></thead>
            <tbody>${logRows}</tbody>
          </table></div>
        </div>`;
    }
  }
}

// ── Global function for act/skip buttons ──────────────────────
async function morningAct(strategyId, symbol, action) {
  const result = await Api.morningAct(strategyId, symbol, action);
  if (result && result.logged) {
    // Refresh the morning decision panel to reflect the logged action
    hydrateMorningDecision();
  }
}

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
  setDataPoint('kpi-portfolio', '…', 'overview');
  setDataPoint('kpi-daily-pnl', '…', 'overview');
  setDataPoint('kpi-positions', '…', 'overview');
  setDataPoint('kpi-predictions', '…', 'overview');
  setDataPoint('kpi-winrate', '…', 'overview');
  setDataPoint('kpi-knowledge', '…', 'overview');
  const tbody = el('top-predictions-body');
  if (tbody) tbody.innerHTML = '<tr><td colspan="5" style="color:var(--text-muted);text-align:center;padding:16px">Loading predictions…</td></tr>';
}

// ── MARKET ────────────────────────────────────────────────────
function renderMarket() {
  // Delegate to live hydration — hydrateMarket() renders all charts/tables
  const moversBody = el('top-movers-body');
  if (moversBody) moversBody.innerHTML = '<tr><td colspan="5" style="color:var(--text-muted);text-align:center;padding:16px">Loading market data…</td></tr>';
  const derivBody = el('deriv-body');
  if (derivBody) derivBody.innerHTML = '<tr><td colspan="3" style="color:var(--text-muted);text-align:center;padding:16px">No options data — run Options Intelligence scraper</td></tr>';
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
    risk:       renderRisk,
    paper:      renderPaperPortfolio,
    gonogo:     () => {},  // rendered entirely by hydrate* functions
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

// NOTE: sections below were relocated here from their original position in app.js
// (originally lines 1554-1682, 3823-3971, 4816-4829) because they are core/shared
// plumbing (boot sequence, nav wiring, renderPage patch, topbar polling) rather
// than page-specific code. See ARCH-5 split (plain dashes used to avoid encoding issues).



// ── Boot sequence poller ──────────────────────────────────────────────────────
(function bootPoller() {
  const STEP_LABELS = {
    market_data:       'Pulling market data (OHLCV)…',
    features:          'Computing feature engineering…',
    news:              'Fetching news & classifying…',
    sentiment:         'Running sentiment & regime analysis…',
    predictions:       'Generating ML predictions…',
    paper_trading:     'Running paper trading cycle…',
    agents:            'Dispatching research agents…',
    strategy_research: 'Evolving algo population…',
    learning:          'Running learning & scoring loop…',
  };
  const STEP_ORDER = Object.keys(STEP_LABELS);
  const ICONS = { pending: '⬡', running: '◈', done: '◆', error: '✗' };
  const COLORS = { pending: '#374151', running: '#00d4aa', done: '#22c55e', error: '#ef4444' };

  const overlay  = document.getElementById('boot-overlay');
  const bar      = document.getElementById('boot-progress-bar');
  const stepLbl  = document.getElementById('boot-step-label');
  const elapsed  = document.getElementById('boot-elapsed');
  const startTs  = Date.now();

  if (!overlay) return;   // overlay already removed (unlikely on first load)

  let pollInterval = null;

  function updateOverlay(status) {
    const steps  = status.steps || {};
    const doneN  = Object.values(steps).filter(s => s.status === 'done' || s.status === 'error').length;
    const totalN = STEP_ORDER.length;
    const pct    = totalN > 0 ? Math.min(100, Math.round(doneN / totalN * 100)) : 0;

    if (bar)     bar.style.width = pct + '%';
    if (stepLbl) {
      const cur = status.current_step;
      stepLbl.textContent = cur ? (STEP_LABELS[cur] || cur) : (status.done ? 'All systems ready!' : 'Initialising…');
      stepLbl.style.color = status.done ? '#22c55e' : '#00d4aa';
    }
    if (elapsed && status.started_at) {
      const secs = Math.round((Date.now() / 1000) - status.started_at);
      elapsed.textContent = `${secs}s elapsed`;
    }

    STEP_ORDER.forEach(key => {
      const el = document.getElementById('boot-s-' + key);
      if (!el) return;
      const s = steps[key] || { status: 'pending', msg: '' };
      const icon  = ICONS[s.status] || '⬡';
      const color = COLORS[s.status] || '#374151';
      el.style.color = color;
      el.textContent = icon + ' ' + (STEP_LABELS[key] || key).replace('…', '') + (s.msg ? '  — ' + s.msg : '');
    });
  }

  function dismiss() {
    if (pollInterval) clearInterval(pollInterval);
    overlay.style.transition = 'opacity 0.6s ease';
    overlay.style.opacity    = '0';
    setTimeout(() => { overlay.style.display = 'none'; }, 650);
  }

  async function poll() {
    try {
      const resp = await fetch('http://localhost:8000/api/v1/system/status');
      if (!resp.ok) return;
      const status = await resp.json();
      updateOverlay(status);
      if (status.done) {
        // Show 100% for a moment then dismiss
        if (bar) bar.style.width = '100%';
        setTimeout(dismiss, 800);
      }
    } catch (_) {
      // Backend not yet up — keep showing overlay
    }
  }

  // Poll immediately, then every 2s
  poll();
  pollInterval = setInterval(poll, 2000);

  // Safety fallback: if backend never responds with done=true after 15 min, dismiss anyway
  setTimeout(dismiss, 15 * 60 * 1000);
})();
window.addEventListener('DOMContentLoaded', () => {
  // Read previous session BEFORE renderPage() overwrites it
  const prevSession = _session.load();

  // Render initial page (mock data first, then live overwrites)
  renderPage('overview');

  // Set date — Bloomberg format: 28 JUN 2026
  const dateEl = el('topbar-date');
  if (dateEl) {
    const now = new Date();
    const months = ['JAN','FEB','MAR','APR','MAY','JUN','JUL','AUG','SEP','OCT','NOV','DEC'];
    dateEl.textContent = `${String(now.getDate()).padStart(2,'0')} ${months[now.getMonth()]} ${now.getFullYear()}`;
  }

  // Topbar live dot — pulse while data is fresh
  const liveDot = el('topbar-live-dot');
  if (liveDot) liveDot.classList.remove('off');

  // Live backend hydration on startup
  hydrateOverview();
  hydrateOverviewPredictions();
  hydratePaperPortfolioStrip();
  hydrateMarket();          // topbar from DB (instant, yesterday's close)
  hydrateMarketRegime();
  startTopbarLivePolling(); // overwrites with real-time yfinance prices, refreshes every 30s
  hydrateNewsStrip();       // amber news ticker bar
  refreshNavBadges();       // update sidebar counts from live data
  hydratePipelineHealthBanner(); // GO-3: show red banner if pipeline silently failed
  setInterval(hydratePipelineHealthBanner, 30 * 60 * 1000); // re-check every 30 min
  hydrateWatchdogRestartPill();  // GO-2: amber pill when watchdog restarted backend
  setInterval(hydrateWatchdogRestartPill, 15 * 60 * 1000);

  // Session restore — sidebar button is always visible, toast appears after 500ms
  _updateSidebarSessionBtn(prevSession);
  if (prevSession && prevSession.page) {
    setTimeout(() => _sessionToast(prevSession), 500);
  }
});

// ── TODAY'S TRADES — Top-5 signals with SL/TP/strategy ────────
// Patch nav to trigger live hydration on every page visit
const _originalRenderPage = renderPage;
const _liveHydrated = new Set(); // kept for manual cache-busting by action buttons

function renderPage(pageId) {
  _originalRenderPage(pageId);

  if (pageId === 'news')        hydrateNews();
  if (pageId === 'sentiment')   hydrateSentiment();
  if (pageId === 'market')      { hydrateMarket(); loadUniverseSummary().catch(()=>{}); }
  if (pageId === 'opportunity') { loadTodaySignals(); hydrateOpportunities(); }
  if (pageId === 'model')       hydrateModelCenter();
  if (pageId === 'paper') { hydratePaperPortfolio(); startPaperPolling(); }
  if (pageId !== 'paper') stopPaperPolling();
  if (pageId === 'risk')        hydrateRisk();
  // learning: renderLearning() is fully live. _originalRenderPage calls it on first
  // visit; we only need hydrateLearnCenter (which re-runs renderLearning) on
  // repeat visits when _originalRenderPage is a no-op due to the rendered guard.
  if (pageId === 'learning' && _learningInitDone) hydrateLearnCenter();
  if (pageId === 'learning') _learningInitDone = true;
  if (pageId === 'strategy')    hydrateStrategyResearch();
  if (pageId === 'agents')           { hydrateResearchOps(); startNewsFeedAutoRefresh(); }
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
  if (pageId === 'screener')         hydrateScreener();
  if (pageId === 'analytics')        hydrateAnalytics();
  if (pageId === 'arena')            hydrateArena();
  if (pageId === 'gonogo')           { hydrateMorningDecision(); hydrateGoNogo(); hydrateGoNogoUptime(); hydrateGoNogoRiskRails(); hydrateGoNogoMonthlyReview(); }
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
    setDataPoint('market-nifty-val', fmt, 'topbar');
    const mChg = el('market-nifty-chg');
    if (mChg) { mChg.textContent = chgText; mChg.className = 'kpi-sub ' + (pct >= 0 ? 'positive' : 'negative'); }
  }
  if (banknifty && banknifty.price != null) {
    const fmt = banknifty.price.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    const pct = banknifty.changePct || 0;
    const chgText = `${pct >= 0 ? '+' : ''}${pct.toFixed(2)}%`;
    setDataPoint('market-banknifty-val', fmt, 'topbar');
    const mChg = el('market-banknifty-chg');
    if (mChg) { mChg.textContent = chgText; mChg.className = 'kpi-sub ' + (pct >= 0 ? 'positive' : 'negative'); }
  }
  if (vix && vix.price != null) {
    setDataPoint('market-vix-val', vix.price.toFixed(2), 'topbar');
    const pct = vix.changePct || 0;
    const mChg = el('market-vix-sub');
    if (mChg) { mChg.textContent = `${pct >= 0 ? '+' : ''}${pct.toFixed(2)}% today`; }
    const vEl = el('market-vix-val');
    if (vEl) vEl.className = 'kpi-value ' + (vix.price > 20 ? 'negative' : vix.price < 13 ? 'positive' : '');
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
// Re-register nav listeners: replace cloned nodes to clear stale listeners,
// then attach a single handler that both activates the page AND hydrates it.
document.querySelectorAll('.nav-item').forEach(item => {
  const clone = item.cloneNode(true);
  item.parentNode.replaceChild(clone, item);
  clone.addEventListener('click', () => {
    const pageId = clone.dataset.page;
    activatePage(pageId);
    renderPage(pageId);
    // Always re-hydrate on every visit (renderPage skips after first render)
    if (pageId === 'screener')  hydrateScreener();
    if (pageId === 'analytics') hydrateAnalytics();
  });
});
