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
// Guarded: if the Chart.js <script> tag failed to load (blocked/offline CDN,
// network-restricted dev environment), `Chart` is undefined here. Without
// this guard, the line below throws synchronously and aborts the rest of
// this file's execution — including the DOMContentLoaded listener that
// wires up nav clicks and hydrates every page. That failure is invisible
// (no console access needed to notice "the whole app does nothing") and is
// completely independent of backend availability, so it must never be able
// to take down anything past this point.
if (typeof Chart !== 'undefined') {
  Chart.defaults.color          = '#444444';
  Chart.defaults.borderColor    = '#1a1a1a';
  Chart.defaults.font.family    = "'JetBrains Mono', monospace";
  Chart.defaults.font.size      = 10;
  Chart.defaults.plugins.tooltip.backgroundColor = '#0d0d0d';
  Chart.defaults.plugins.tooltip.borderColor     = '#2a2a2a';
  Chart.defaults.plugins.tooltip.borderWidth     = 1;
  Chart.defaults.plugins.tooltip.titleColor      = '#ff9500';
  Chart.defaults.plugins.tooltip.bodyColor       = '#888888';
  Chart.defaults.plugins.legend.labels.color     = '#444444';
} else {
  console.error('[AQRTI] Chart.js failed to load — charts will be unavailable, but the rest of the app will still work.');
}

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
  cockpit:             'Portfolio Cockpit',
  market:              'Market',
  analytics:           'Analytics',
  news:                'Research',
  strategy:            'Algos',
  risk:                'Risk Center',
  paper:               'Paper Portfolio',
  agents:              'Agents',
  arena:               'Algo Arena',
  gonogo:              'Go / No-Go',
  markov:              'Markov Regime',
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
    'cockpit': 'fk-cockpit', 'market': 'fk-market', 'analytics': 'fk-analytics',
    'news': 'fk-news', 'agents': 'fk-agents', 'strategy': 'fk-strategy',
    'arena': 'fk-arena', 'gonogo': 'fk-gonogo', 'markov': 'fk-markov',
    'paper': 'fk-paper', 'risk': 'fk-risk',
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
  const pageName = (session.page || 'cockpit').toUpperCase().replace(/-/g, ' ');

  // Store session data on window so the resume button can access it
  // (localStorage was already overwritten by renderPage('cockpit'))
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
    <span style="color:var(--accent,#ff9500);font-size:1.2rem">◈</span>
    <div style="flex:1">
      <div style="color:#f1f5f9;font-weight:700;letter-spacing:0.08em;font-size:0.75rem">SESSION FOUND</div>
      <div style="color:rgba(255,255,255,0.5);margin-top:3px;font-size:0.7rem">
        Last on <span style="color:var(--accent,#ff9500);font-weight:600">${pageName}</span> · saved ${ageStr}
      </div>
    </div>
    <button id="aqrti-resume-btn"
      style="background:rgba(255,140,0,0.18);border:1px solid rgba(255,140,0,0.6);
             color:var(--accent,#ff9500);padding:8px 18px;border-radius:6px;
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
  { icon: '◈', label: 'Portfolio Cockpit',     hint: '12-symbol overview',    page: 'cockpit' },
  { icon: '◎', label: 'Market',                hint: 'Indices · Sectors',     page: 'market' },
  { icon: '◈', label: 'Analytics',             hint: 'Portfolio performance', page: 'analytics' },
  { icon: '◉', label: 'Research',              hint: 'News · Sentiment · Synthesis', page: 'news' },
  { icon: '◎', label: 'Agents',                hint: 'Research agents · Daily Brief', page: 'agents' },
  { icon: '▣', label: 'Algos',                 hint: 'Leaderboard · Replay',  page: 'strategy' },
  { icon: '⚔', label: 'Arena',                 hint: 'Promotion gates',       page: 'arena' },
  { icon: '✅', label: 'Go / No-Go',            hint: 'Morning decision',      page: 'gonogo' },
  { icon: '◇', label: 'Markov Regime',         hint: 'Bull · Bear · Sideways',page: 'markov' },
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
  F1:  'cockpit',  F2: 'market',   F3: 'analytics', F4: 'news',
  F5:  'agents',   F6: 'strategy', F7: 'arena',      F8: 'gonogo',
  F9:  'markov',   F10: 'paper',   F11: 'risk',
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
  'GO':    'cockpit',   'CKPT': 'cockpit',   'CP':    'cockpit',   'HOME': 'cockpit', 'HP': 'cockpit',
  'MKT':  'market',    'MRKT':  'market',    'IM':  'market',
  'ANLT': 'analytics',  'AN':   'analytics',
  'NI':   'news',       'NEWS': 'news',       'TOP': 'news',
  'SENT': 'news',       'SENT1':'news',        'RSCH':'news',
  'AGT':  'agents',     'ROP':  'agents',
  'STRAT':'strategy',   'ST':   'strategy',   'EVL': 'strategy',
  'ARENA':'arena',      'ART':  'arena',
  'GNG':  'gonogo',     'GONOGO':'gonogo',
  'MKV':  'markov',     'REGIME':'markov',
  'PORT': 'paper',      'PPT':  'paper',      'PA':  'paper',
  'RSK':  'risk',       'RISK': 'risk',       'VRA': 'risk',
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

      // Treat as symbol/command search — fall through to command palette
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
  const scoreEl   = el('gonogo-scorecard-card');
  const quarEl    = el('gonogo-quarantine');
  const sigEl     = el('gonogo-signals');
  if (!scoreEl) return;

  let data = null;
  try {
    data = await Api.goNogo();
  } catch (_) {
    data = null;
  }

  if (!data) {
    scoreEl.innerHTML = '<div class="offline-text">Backend offline — start the backend server to see the readiness scorecard.</div>';
    if (quarEl) quarEl.innerHTML = '<div class="offline-text">Backend offline.</div>';
    if (sigEl) sigEl.innerHTML = '<div class="offline-text">Backend offline.</div>';
    return;
  }

  // -- Readiness Scorecard (summary strip + condition rows) --
  const conditions = data.conditions || [];
  const greenCount = conditions.filter(c => c.status === 'green').length;
  const overallColor = data.overall === 'green' ? 'var(--positive)' : data.overall === 'partial' ? 'var(--warning)' : 'var(--negative)';
  const overallText  = data.overall === 'green'
    ? 'All 5 conditions met — ready for real capital.'
    : data.overall === 'partial'
      ? 'Some conditions met — not ready for real capital.'
      : 'Conditions not met — do NOT trade real capital.';

  function condRow(c) {
    const pillCls = c.status === 'green' ? 'pill-pass' : c.status === 'partial' ? 'pill-pending' : 'pill-fail';
    const pillTxt = c.status === 'green' ? 'PASS' : c.status === 'partial' ? 'PENDING' : 'FAIL';
    return `<div class="scorecard-row">
      <div class="scorecard-cond"><strong>${c.label}</strong><div style="color:var(--text-muted);font-size:0.74rem;margin-top:2px">${c.detail || ''}</div></div>
      <span class="pill ${pillCls}">${pillTxt}</span>
    </div>`;
  }

  if (conditions.length === 0) {
    scoreEl.innerHTML = '<div class="empty-text">No readiness conditions returned yet.</div>';
  } else {
    scoreEl.innerHTML = `
      <div class="scorecard-summary" style="color:${overallColor}">${greenCount} of ${conditions.length} green — ${overallText}</div>
      ${conditions.map(condRow).join('')}
    `;
  }

  // -- Quarantine progress --
  if (quarEl) {
    const algos = data.quarantine_algos || [];
    if (algos.length === 0) {
      quarEl.innerHTML = '<div class="empty-text">No promoted algos yet — quarantine clock hasn\'t started.</div>';
    } else {
      quarEl.innerHTML = algos.map(a => {
        const gates = a.gates || {};
        const daysPct   = Math.max(0, Math.min(100, (a.days_in_quarantine / 60) * 100));
        const tradesPct = Math.max(0, Math.min(100, (a.shadow_trades / 20) * 100));
        const wrPct     = Math.max(0, Math.min(100, a.shadow_wr || 0));
        return `
        <div class="quarantine-card">
          <div class="quarantine-name">${a.quarantine_ok ? '✅' : '⏳'} ${a.name} <span style="color:var(--text-muted);font-weight:400;font-size:0.74rem">${a.strategy_id}</span></div>
          <div class="qbar-row"><span class="qbar-label">Days / 60</span><div class="qbar-track"><div class="qbar-fill ${gates.days_60 ? 'ok' : ''}" style="width:${daysPct}%"></div></div><span class="qbar-val">${a.days_in_quarantine}d</span></div>
          <div class="qbar-row"><span class="qbar-label">Trades / 20</span><div class="qbar-track"><div class="qbar-fill ${gates.trades_20 ? 'ok' : ''}" style="width:${tradesPct}%"></div></div><span class="qbar-val">${a.shadow_trades}</span></div>
          <div class="qbar-row"><span class="qbar-label">WR vs 50%</span><div class="qbar-track"><div class="qbar-fill ${gates.wr_50pct ? 'ok' : 'warn'}" style="width:${wrPct}%"></div></div><span class="qbar-val">${a.shadow_wr}%</span></div>
          <div class="qbar-row"><span class="qbar-label">Net P&amp;L</span><span style="color:${a.net_pnl >= 0 ? 'var(--positive)' : 'var(--negative)'};font-family:var(--font-mono)">₹${a.net_pnl.toLocaleString('en-IN', {minimumFractionDigits:0, maximumFractionDigits:0})}</span></div>
        </div>`;
      }).join('');
    }
  }

  // -- Today's actionable signals --
  if (sigEl) {
    const sigs = data.actionable_signals || [];
    if (sigs.length === 0) {
      sigEl.innerHTML = '<div class="empty-text">No open positions from promoted algos — nothing actionable today.</div>';
    } else {
      const rows = sigs.map(s => {
        const pnlColor = (s.current_pnl_pct || 0) >= 0 ? 'var(--positive)' : 'var(--negative)';
        return `<tr>
          <td style="font-weight:600">${s.symbol}</td>
          <td style="color:var(--text-muted)">${s.algo_name}</td>
          <td>${s.direction || '—'}</td>
          <td style="color:var(--text-muted)">${s.entry_date || '—'}</td>
          <td style="text-align:right">₹${(s.entry_price || 0).toLocaleString('en-IN', {minimumFractionDigits:2, maximumFractionDigits:2})}</td>
          <td style="text-align:right;color:${pnlColor}">${(s.current_pnl_pct || 0) >= 0 ? '+' : ''}${s.current_pnl_pct}%</td>
        </tr>`;
      }).join('');
      sigEl.innerHTML = `<div class="table-container"><table class="data-table compact">
        <thead><tr><th>Symbol</th><th>Algo</th><th>Direction</th><th>Entry Date</th><th style="text-align:right">Entry Price</th><th style="text-align:right">P&amp;L %</th></tr></thead>
        <tbody>${rows}</tbody>
      </table></div>`;
    }
  }
}

async function hydrateGoNogoUptime() {
  const el = id => document.getElementById(id);
  const uptimeEl = el('gonogo-uptime');
  if (!uptimeEl) return;
  uptimeEl.innerHTML = '<div class="loading-text">Loading…</div>';

  let rows = null;
  try {
    rows = await Api.goNogoUptimeLog();
  } catch (_) {
    rows = null;
  }

  if (rows === null) {
    uptimeEl.innerHTML = '<div class="offline-text">Backend offline.</div>';
    return;
  }
  if (!Array.isArray(rows) || rows.length === 0) {
    uptimeEl.innerHTML = '<div class="empty-text">No health check records yet — pipeline watchdog not running.</div>';
    return;
  }

  const greenCount = rows.filter(r => r.overall_ok).length;
  const uptimePct = ((greenCount / rows.length) * 100).toFixed(1);
  const last30 = rows.slice(-30);
  const squares = last30.map(r => {
    const cls = r.overall_ok ? 'green' : 'red';
    const dt = r.checked_at ? new Date(r.checked_at).toLocaleDateString('en-IN') : '—';
    const tooltip = `${dt}: ${r.overall_ok ? 'OK' : 'FAILED'}${r.failures ? ' — ' + r.failures : ''}`;
    return `<span class="uptime-day ${cls}" title="${tooltip}"></span>`;
  }).join('');

  uptimeEl.innerHTML = `
    <div class="uptime-pct">${uptimePct}% uptime <span style="color:var(--text-muted);font-weight:400;font-size:0.74rem">(${greenCount}/${rows.length} checks green, most recent last)</span></div>
    <div class="uptime-strip">${squares}</div>
    <div class="uptime-legend">
      <span><i style="background:var(--positive)"></i>Green = pipeline OK</span>
      <span><i style="background:var(--negative)"></i>Red = check failed</span>
    </div>`;
}

async function hydrateGoNogoMonthlyReview() {
  const el = id => document.getElementById(id);
  const mrEl = el('gonogo-monthly-review');
  if (!mrEl) return;
  mrEl.innerHTML = '<div class="loading-text">Loading…</div>';

  let data = null;
  try {
    data = await Api.goNogoMonthlyReview();
  } catch (_) {
    data = null;
  }

  if (!data) {
    mrEl.innerHTML = '<div class="offline-text">Backend offline.</div>';
    return;
  }

  if (data.no_data) {
    mrEl.innerHTML = `<div class="empty-text">${data.empty_reason || 'No data yet.'}</div>`;
    return;
  }

  const uptime = data.uptime || {};
  const algos = data.algo_reviews || [];

  let algoHtml = '';
  if (algos.length > 0) {
    const rows = algos.map(a => {
      const wrDiff = a.wr_vs_backtest_pp;
      const wrColor = wrDiff == null ? 'var(--text-muted)' : wrDiff >= 0 ? 'var(--positive)' : 'var(--negative)';
      return `<tr>
        <td style="font-weight:500">${a.name}</td>
        <td style="text-align:right">${a.backtest_win_rate != null ? (a.backtest_win_rate * 100).toFixed(1) + '%' : '—'}</td>
        <td style="text-align:right">${a.live_30d_win_rate != null ? a.live_30d_win_rate + '%' : '—'}</td>
        <td style="text-align:right;color:${wrColor}">${wrDiff != null ? (wrDiff >= 0 ? '+' : '') + wrDiff + 'pp' : '—'}</td>
        <td style="text-align:right">${a.live_30d_trades}</td>
        <td style="text-align:right;color:${a.live_30d_net_pnl >= 0 ? 'var(--positive)' : 'var(--negative)'}">₹${a.live_30d_net_pnl.toLocaleString('en-IN', {minimumFractionDigits:0, maximumFractionDigits:0})}</td>
      </tr>`;
    }).join('');
    algoHtml = `<div class="table-container" style="margin-bottom:14px"><table class="data-table compact">
      <thead><tr><th>Algo</th><th style="text-align:right">BT WR%</th><th style="text-align:right">Live WR%</th><th style="text-align:right">Diff</th><th style="text-align:right">Trades</th><th style="text-align:right">Net P&amp;L</th></tr></thead>
      <tbody>${rows}</tbody>
    </table></div>`;
  }

  const cr = data.cost_reconciliation || {};
  mrEl.innerHTML = `
    <div style="font-size:0.78rem;color:var(--text-secondary);margin-bottom:12px">Period: ${data.month_start} to ${data.report_date} &nbsp;·&nbsp; Uptime: ${uptime.checks_green ?? '—'}/${uptime.checks_total ?? '—'} checks (${uptime.uptime_pct ?? '—'}%)</div>
    ${algoHtml}
    <div style="font-size:0.76rem;color:var(--text-muted);padding:10px 12px;background:var(--bg-hover);border:1px solid var(--border-faint);border-radius:var(--radius-md)">
      <strong style="color:var(--text-primary)">Cost reconciliation:</strong> ${cr.note || '—'}
      ${cr.real_cost_pct != null ? ` — real cost <strong>${cr.real_cost_pct}%</strong> vs modeled ${cr.modeled_cost_pct}%` : ''}
    </div>`;
}

async function hydrateGoNogoRiskRails() {
  const el = id => document.getElementById(id);
  const railsEl = el('gonogo-risk-rails');
  if (!railsEl) return;
  railsEl.innerHTML = '<div class="loading-text">Loading…</div>';

  let data = null;
  try {
    data = await Api.goNogoRiskRails();
  } catch (_) {
    data = null;
  }

  if (!data) {
    railsEl.innerHTML = '<div class="offline-text">Backend offline.</div>';
    return;
  }
  if (!data.rules || !data.rules.length) {
    railsEl.innerHTML = '<div class="empty-text">No risk rails configured yet.</div>';
    return;
  }

  const rows = data.rules.map(r => `
    <div class="rail-row">
      <span class="rail-label">Rule ${r.id}: ${r.rule}<div style="color:var(--text-muted);font-size:0.72rem;margin-top:2px">${r.detail || ''}</div></span>
      <span class="rail-value">${r.limit != null ? r.limit : ''}</span>
    </div>`).join('');

  railsEl.innerHTML = `<div class="card-title" style="margin-top:4px">Real-Capital Risk Rails</div>${rows}` +
    (data.note ? `<div style="font-size:0.72rem;color:var(--text-muted);margin-top:10px;padding:8px 12px;background:var(--bg-hover);border-radius:var(--radius-md);border:1px solid var(--border-faint)">${data.note}</div>` : '');
}

// ══════════════════════════════════════════════════════════════════════
// GO-7: Morning Decision Screen hydration
// ══════════════════════════════════════════════════════════════════════

async function hydrateMorningDecision() {
  const panelEl = document.getElementById('morning-decision-panel');
  const logEl   = document.getElementById('morning-act-log');
  if (!panelEl) return;
  panelEl.innerHTML = '<div class="loading-text">Loading morning briefing…</div>';

  let data = null;
  try {
    data = await Api.morningDecision();
  } catch (_) {
    data = null;
  }

  if (!data) {
    panelEl.innerHTML = '<div class="offline-text">Backend offline — start the backend to see today\'s briefing.</div>';
    return;
  }

  const hasNoAction  = data.no_action;
  const noActionText = data.no_action_reason || '';
  const sigs = data.signals || [];

  // ── Row 1 verdict: GO if there's at least one actionable signal and no
  // blocking "no action" condition, NO-GO otherwise. This mirrors the
  // scorecard's overall gate but answers "what should I do today" directly.
  const isGo = !hasNoAction && sigs.length > 0;
  const verdictWhy = hasNoAction
    ? (noActionText || 'Conditions for action are not met today.')
    : (sigs.length > 0
        ? `${sigs.length} actionable signal${sigs.length > 1 ? 's' : ''} from promoted algos in the current ${data.regime || '—'} regime.`
        : 'No open positions from promoted/active algos — nothing actionable today.');

  let verdictHtml = `
    <div class="verdict-banner">
      <span class="verdict-badge ${isGo ? 'go' : 'no-go'}">${isGo ? 'GO' : 'NO-GO'}</span>
      <span class="verdict-line">${isGo ? 'Actionable signals today' : (hasNoAction ? 'No action today' : 'Nothing actionable today')}</span>
    </div>
    <div class="verdict-why">${verdictWhy}</div>`;

  // ── Regime + Risk posture bar ──────────────────────────────────────
  const regime      = data.regime || '—';
  const regimeDate  = data.regime_date || '';
  const posture     = data.risk_posture || 'normal';
  const cbOk        = data.circuit_breaker_ok;
  const postureIcon = posture === 'high' ? '🔴' : posture === 'elevated' ? '🟡' : '🟢';
  const postureCls  = posture === 'high' ? 'var(--negative)' : posture === 'elevated' ? 'var(--warning)' : 'var(--positive)';
  const cbIcon      = cbOk === true ? '🟢' : cbOk === false ? '🔴' : '⚪';

  let regimeHtml = `
    <div style="display:flex;flex-wrap:wrap;gap:10px;margin:14px 0;font-size:0.78rem">
      <div style="padding:6px 12px;background:var(--bg-hover);border:1px solid var(--border-faint);border-radius:var(--radius-md);display:flex;align-items:center;gap:6px">
        <span style="font-weight:600;color:var(--text-primary)">Regime:</span>
        <span style="color:${regime === 'BULL' ? 'var(--positive)' : regime === 'BEAR' ? 'var(--negative)' : 'var(--warning)'}">${regime}</span>
        ${regimeDate ? `<span style="color:var(--text-muted);font-size:0.7rem">(${regimeDate})</span>` : ''}
      </div>
      <div style="padding:6px 12px;background:var(--bg-hover);border:1px solid var(--border-faint);border-radius:var(--radius-md);display:flex;align-items:center;gap:6px">
        <span>${postureIcon}</span>
        <span style="font-weight:600;color:var(--text-primary)">Risk Posture:</span>
        <span style="color:${postureCls};text-transform:uppercase">${posture}</span>
      </div>
      <div style="padding:6px 12px;background:var(--bg-hover);border:1px solid var(--border-faint);border-radius:var(--radius-md);display:flex;align-items:center;gap:6px">
        <span>${cbIcon}</span>
        <span style="font-weight:600;color:var(--text-primary)">Circuit Breaker:</span>
        <span style="color:${cbOk === true ? 'var(--positive)' : cbOk === false ? 'var(--negative)' : 'var(--text-muted)'}">${cbOk === true ? 'OK' : cbOk === false ? 'TRIPPED' : 'No data'}</span>
      </div>
      <div style="padding:6px 12px;background:var(--bg-hover);border:1px solid var(--border-faint);border-radius:var(--radius-md);font-size:0.74rem;color:var(--text-muted)">
        Date: ${data.date || '—'} · ${data.promoted_algo_count || 0} promoted algo(s)
      </div>
    </div>`;

  // ── Signals table ──────────────────────────────────────────────────
  let signalsHtml = '';

  if (!hasNoAction && sigs.length > 0) {
    const rows = sigs.map(s => {
      const dirCls   = (s.direction || '').toLowerCase().includes('bull') ? 'var(--positive)' : 'var(--negative)';
      const pnlCls   = (s.current_pnl_pct || 0) >= 0 ? 'var(--positive)' : 'var(--negative)';
      const wrColor  = s.shadow_wr != null ? (s.shadow_wr >= 50 ? 'var(--positive)' : 'var(--negative)') : 'var(--text-muted)';
      return `<tr>
        <td style="font-weight:600">${s.symbol}</td>
        <td style="color:var(--text-muted)">${s.algo_name}</td>
        <td style="color:${dirCls}">${s.direction || '—'}</td>
        <td style="text-align:right;color:${pnlCls}">${(s.current_pnl_pct || 0) >= 0 ? '+' : ''}${s.current_pnl_pct}%</td>
        <td style="text-align:right;color:var(--text-muted)">₹${(s.position_size_inr || 0).toLocaleString('en-IN')}</td>
        <td style="color:var(--text-muted)">${s.stop_loss_pct != null ? (s.stop_loss_pct * 100).toFixed(1) + '%' : '—'}</td>
        <td style="color:var(--text-muted)">${s.take_profit_pct != null ? (s.take_profit_pct * 100).toFixed(1) + '%' : '—'}</td>
        <td style="color:var(--text-muted)">${s.confidence != null ? s.confidence + '%' : '—'}</td>
        <td style="text-align:right">${s.quarantine_days}d</td>
        <td style="text-align:right">${s.shadow_trades}</td>
        <td style="text-align:right;color:${wrColor}">${s.shadow_wr != null ? s.shadow_wr + '%' : '—'}</td>
      </tr>`;
    }).join('');

    signalsHtml = `
      <div class="table-container" style="margin-bottom:8px">
        <div style="font-size:0.72rem;font-weight:700;letter-spacing:0.08em;color:var(--text-muted);margin-bottom:6px">
          TODAY'S ACTIONABLE SIGNALS — open paper trades on promoted algos (cap: ₹${(data.position_cap_inr || 1000).toLocaleString('en-IN')}/trade)
        </div>
        <table class="data-table compact">
          <thead><tr>
            <th>Symbol</th><th>Algo</th><th>Dir</th><th style="text-align:right">P&amp;L%</th>
            <th style="text-align:right">Size ₹</th><th>SL</th><th>TP</th><th>Conf</th>
            <th style="text-align:right">Q-Days</th><th style="text-align:right">Tr</th><th style="text-align:right">WR</th>
          </tr></thead>
          <tbody>${rows}</tbody>
        </table>
      </div>
      <div style="font-size:0.7rem;color:var(--text-muted);padding:6px 0">${data.note || 'Click "Acted" or "Skip" to log compliance — AQRTI never executes real trades.'}</div>`;
  } else if (!hasNoAction) {
    signalsHtml = '<div class="empty-text" style="padding:8px 0;text-align:left">No open positions from promoted/active algos. All signals flat — no action needed.</div>';
  }

  // ── Act/Skip buttons (only when there are signals and no NO ACTION) ──
  let actHtml = '';
  if (!hasNoAction && sigs.length > 0) {
    const btnRows = sigs.map((s, i) => {
      const actId = `m-act-${i}`;
      const skipId = `m-skip-${i}`;
      return `<div style="display:flex;align-items:center;gap:8px;padding:6px 0;border-bottom:1px solid var(--border-faint);font-size:0.78rem">
        <span style="flex:0 0 100px;font-weight:600">${s.symbol}</span>
        <span style="flex:0 0 120px;color:var(--text-muted);font-size:0.74rem">${s.algo_name}</span>
        <button id="${actId}" class="btn" style="border-color:var(--positive);color:var(--positive)" onclick="morningAct('${s.strategy_id}','${s.symbol}','acted')">Acted</button>
        <button id="${skipId}" class="btn btn-secondary" onclick="morningAct('${s.strategy_id}','${s.symbol}','skipped')">Skip</button>
        <span id="m-feedback-${i}" style="font-size:0.7rem;color:var(--text-muted)"></span>
      </div>`;
    }).join('');
    actHtml = `
      <div style="margin-top:12px;padding-top:10px;border-top:1px solid var(--border-faint)">
        <div class="card-title">Compliance log — did you act or skip this signal?</div>
        ${btnRows}
      </div>`;
  }

  panelEl.innerHTML = verdictHtml + regimeHtml + signalsHtml + actHtml;

  // ── Load act log ────────────────────────────────────────────────────
  if (logEl) {
    let logData = null;
    try { logData = await Api.morningActLog(20); } catch (_) { logData = null; }
    if (logData && Array.isArray(logData) && logData.length > 0) {
      const logRows = logData.map(r => `
        <tr>
          <td style="color:var(--text-muted)">${r.trade_date}</td>
          <td style="color:var(--text-muted)">${r.symbol}</td>
          <td>${r.strategy_id.slice(0, 16)}…</td>
          <td style="color:${r.action === 'acted' ? 'var(--positive)' : 'var(--negative)'}">${r.action}</td>
          <td style="color:var(--text-muted)">${r.regime || ''}${r.risk_posture ? ' · ' + r.risk_posture : ''}</td>
        </tr>`).join('');
      logEl.style.display = 'block';
      logEl.innerHTML = `
        <div class="card">
          <div class="card-title">Recent Act/Skip log</div>
          <div class="table-container"><table class="data-table compact">
            <thead><tr><th>Date</th><th>Symbol</th><th>Algo</th><th>Action</th><th>Context</th></tr></thead>
            <tbody>${logRows}</tbody>
          </table></div>
        </div>`;
    } else {
      logEl.style.display = 'none';
    }
  }
}

async function morningAct(strategyId, symbol, action) {
  const result = await Api.morningAct(strategyId, symbol, action);
  if (result && result.logged) {
    // Refresh the morning decision panel to reflect the logged action
    hydrateMorningDecision();
  }
}

async function hydrateNewsStrip() {
  const strip = document.getElementById('news-strip');
  const inner = document.getElementById('news-strip-inner');
  if (!inner || !strip) return;

  const data = await Api.news({ limit: 20, hours: 48 });
  if (!data || !Array.isArray(data) || !data.length) {
    // Backend offline or no news in the lookback window — there is nothing
    // honest to show, so hide the whole strip rather than leaving a stuck
    // "fetching live data…" placeholder or a noisy offline banner sitting
    // in the layout permanently.
    strip.style.display = 'none';
    document.body.classList.add('news-strip-hidden');
    inner.innerHTML = '';
    inner.style.animationDuration = '';
    return;
  }

  strip.style.display = '';
  document.body.classList.remove('news-strip-hidden');

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

// ── MARKET ────────────────────────────────────────────────────
function renderMarket() {
  // Delegate to live hydration — hydrateMarket() renders all charts/tables
  const moversBody = el('top-movers-body');
  if (moversBody) moversBody.innerHTML = '<tr><td colspan="5" style="color:var(--text-muted);text-align:center;padding:16px">Loading market data…</td></tr>';
  const derivBody = el('deriv-body');
  if (derivBody) derivBody.innerHTML = '<tr><td colspan="3" style="color:var(--text-muted);text-align:center;padding:16px">No options data — run Options Intelligence scraper</td></tr>';
}

// ── RESEARCH (merged News + Sentiment) ───────────────────────
function renderNews() {
  // Delegate to hydrateNews() + hydrateSentiment() + hydrateResearchSynthesis()
  // — all live data from backend. Page id stays "news" for backward
  // compatibility with saved sessions/bookmarks; nav label is "Research".
  const hi = el('news-high-impact');
  if (hi) hi.innerHTML = '<div style="padding:24px;text-align:center;color:var(--text-muted);font-size:0.78rem">Loading news…</div>';
  const feed = el('news-feed');
  if (feed) feed.innerHTML = '';
  const velBody = el('sentiment-velocity-body');
  if (velBody) velBody.innerHTML = '<div style="padding:16px;text-align:center;color:var(--text-muted);font-size:0.78rem">Loading…</div>';
  const narrativeBody = el('narrative-shifts-body');
  if (narrativeBody) narrativeBody.innerHTML = '';
  const synthBody = el('research-synthesis-body');
  if (synthBody) synthBody.innerHTML = '<div style="text-align:center;color:var(--text-muted);padding:20px">Loading…</div>';
}

// ── STRATEGY LAB ──────────────────────────────────────────────
function renderStrategy() {
  // Delegate to hydrateStrategyResearch() — live backend data
  const tbody = el('strategy-body');
  if (tbody) tbody.innerHTML = '<tr><td colspan="10" style="color:var(--text-muted);text-align:center;padding:16px">Loading strategies…</td></tr>';
}

// ── RISK CENTER ───────────────────────────────────────────────
function renderRisk() {
  // Delegate entirely to hydrateRisk() -- live backend data only, no mock data
  hydrateRisk();
}

// LAZY RENDER — Render page on first activation
// ═══════════════════════════════════════════════════════════════
const rendered = new Set();

function _renderPageOnce(pageId) {
  if (rendered.has(pageId)) return;
  rendered.add(pageId);
  const renderers = {
    cockpit:   () => {},  // rendered entirely by hydrateCockpit()
    market:    renderMarket,
    news:      renderNews,
    strategy:  renderStrategy,
    risk:      renderRisk,
    paper:     renderPaperPortfolio,
    arena:     () => {},  // rendered entirely by hydrateArena()
    gonogo:    () => {},  // rendered entirely by hydrate* functions
    markov:    () => {},  // rendered entirely by hydrateMarkov (isolated module)
    analytics: () => {},  // rendered entirely by hydrateAnalytics()
    agents:    () => {},  // rendered entirely by hydrateResearchOps()
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
  const COLORS = { pending: '#3a3a3e', running: '#ff9500', done: '#22c55e', error: '#ef4444' };

  const overlay  = document.getElementById('boot-overlay');
  const bar      = document.getElementById('boot-progress-bar');
  const stepLbl  = document.getElementById('boot-step-label');
  const elapsed  = document.getElementById('boot-elapsed');
  const startTs  = Date.now();

  if (!overlay) return;   // overlay already removed (unlikely on first load)

  let pollInterval = null;
  let consecutiveFailures = 0;
  // Main backend may legitimately be off (e.g. running the Markov module
  // standalone) — don't block the whole UI behind a full-screen overlay for
  // 15 minutes waiting for it. After a handful of failed polls, dismiss and
  // let the app render in a degraded "main backend offline" state instead.
  const MAX_CONSECUTIVE_FAILURES = 5;

  function updateOverlay(status) {
    const steps  = status.steps || {};
    const doneN  = Object.values(steps).filter(s => s.status === 'done' || s.status === 'error').length;
    const totalN = STEP_ORDER.length;
    const pct    = totalN > 0 ? Math.min(100, Math.round(doneN / totalN * 100)) : 0;

    if (bar)     bar.style.width = pct + '%';
    if (stepLbl) {
      const cur = status.current_step;
      stepLbl.textContent = cur ? (STEP_LABELS[cur] || cur) : (status.done ? 'All systems ready!' : 'Initialising…');
      stepLbl.style.color = status.done ? '#22c55e' : '#ff9500';
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
      const color = COLORS[s.status] || '#3a3a3e';
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
      const resp = await fetch('http://localhost:8000/api/v1/system/status', {
        signal: AbortSignal.timeout(3000),
      });
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      const status = await resp.json();
      consecutiveFailures = 0;
      updateOverlay(status);
      if (status.done) {
        // Show 100% for a moment then dismiss
        if (bar) bar.style.width = '100%';
        setTimeout(dismiss, 800);
      }
    } catch (_) {
      // Backend not yet up — keep showing overlay, up to MAX_CONSECUTIVE_FAILURES
      consecutiveFailures++;
      if (consecutiveFailures >= MAX_CONSECUTIVE_FAILURES) {
        if (stepLbl) {
          stepLbl.textContent = 'Main backend offline — showing app in degraded mode';
          stepLbl.style.color = '#ef4444';
        }
        setTimeout(dismiss, 1000);
      }
    }
  }

  // Poll immediately, then every 2s
  poll();
  pollInterval = setInterval(poll, 2000);

  // Safety fallback: if backend never responds with done=true after 15 min, dismiss anyway
  setTimeout(dismiss, 15 * 60 * 1000);
})();
function _initialBoot() {
  // Read previous session BEFORE renderPage() overwrites it
  const prevSession = _session.load();

  // Render initial page — Portfolio Cockpit is the default landing page
  renderPage('cockpit');
  activatePage('cockpit');

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
}

// ── TODAY'S TRADES — Top-5 signals with SL/TP/strategy ────────
// Patch nav to trigger live hydration on every page visit
const _liveHydrated = new Set(); // kept for manual cache-busting by action buttons

function renderPage(pageId) {
  _renderPageOnce(pageId);

  if (pageId === 'news')        { hydrateNews(); hydrateSentiment(); hydrateResearchSynthesis(); }
  if (pageId === 'market')      { hydrateMarket(); loadUniverseSummary().catch(()=>{}); }
  if (pageId === 'paper') { hydratePaperPortfolio(); startPaperPolling(); }
  if (pageId !== 'paper') stopPaperPolling();
  if (pageId === 'risk')        hydrateRisk();
  if (pageId === 'strategy')    hydrateStrategyResearch();
  if (pageId === 'agents')      { hydrateResearchOps(); startNewsFeedAutoRefresh(); }
  if (pageId === 'analytics')   hydrateAnalytics();
  if (pageId === 'arena')       hydrateArena();
  if (pageId === 'gonogo')      { hydrateMorningDecision(); hydrateGoNogo(); hydrateGoNogoUptime(); hydrateGoNogoRiskRails(); hydrateGoNogoMonthlyReview(); }
  if (pageId === 'markov')      hydrateMarkov();
  if (pageId === 'cockpit')     hydrateCockpit();
}

// ── Nav Badges — live counts from backend ────────────────────
async function refreshNavBadges() {
  const _b = (id, val) => { const e = el(id); if (e && val != null) e.textContent = val; };
  try {
    const [ov, news, strats, agentData, findings] = await Promise.all([
      Api.overview().catch(() => null),
      Api.news({ limit: 10 }).catch(() => null),
      Api.strategies().catch(() => null),
      Api.agents().catch(() => null),
      Api.findingsSummary().catch(() => null),
    ]);
    if (ov) {
      if (ov.activeStrategies != null) _b('badge-strat', ov.activeStrategies);
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

async function hydrateTopbarLive() {
  const data = await Api.topbarPrices();
  if (!data || !data.length) {
    // Backend offline / no source — fall back to a single, calm "—" per
    // field rather than verbose "NO DATA" / "Backend offline" text that
    // overflows the tight ticker boxes and reads as glitchy.
    ['nifty-value', 'banknifty-value', 'vix-value', 'usdinr-value'].forEach(id => {
      const e = el(id);
      if (e) e.textContent = '—';
    });
    ['nifty-change', 'banknifty-change', 'vix-change', 'usdinr-change'].forEach(id => {
      const e = el(id);
      if (e) { e.textContent = '—'; e.className = 'ticker-change'; }
    });
    return;
  }

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
    if (pageId === 'analytics') hydrateAnalytics();
  });
});
