/**
 * AQRTI Desktop Bridge
 * Loaded only when running inside Electron.
 * Wires the custom titlebar, IPC events, and switches API to live mode.
 */

(function () {
  'use strict';

  // Not in Electron — bail out silently
  if (!window.aqrti) return;

  // ── Show custom titlebar + shift layout ──────────────────
  const titlebar = document.getElementById('aqrti-titlebar');
  if (titlebar) titlebar.style.display = 'flex';
  document.body.classList.add('electron-desktop');

  // ── Titlebar button handlers ──────────────────────────────
  document.getElementById('tb-min')?.addEventListener('click', () => window.aqrti.window.minimize());
  document.getElementById('tb-close')?.addEventListener('click', () => window.aqrti.window.close());
  document.getElementById('tb-settings')?.addEventListener('click', () => window.aqrti.window.openSettings());

  const maxBtn = document.getElementById('tb-max');
  maxBtn?.addEventListener('click', async () => {
    await window.aqrti.window.maximize();
    const isMax = await window.aqrti.window.isMaximized();
    maxBtn.textContent = isMax ? '❐' : '□';
  });

  // ── Switch API to live backend ────────────────────────────
  if (typeof API_CONFIG !== 'undefined') {
    API_CONFIG.USE_MOCK = false;
  }

  // ── Backend status in sidebar ─────────────────────────────
  async function refreshBackendStatus() {
    try {
      const status = await window.aqrti.backend.getStatus();
      const label = document.getElementById('sys-status-label');
      const dot = document.querySelector('.status-dot');
      if (label) label.textContent = status.running ? 'BACKEND LIVE' : 'BACKEND OFFLINE';
      if (dot) {
        dot.classList.toggle('active', status.running);
        dot.classList.toggle('error', !status.running);
      }
    } catch (_) {}
  }

  refreshBackendStatus();
  setInterval(refreshBackendStatus, 30_000);

  // ── Desktop notifications overlay ────────────────────────
  window.aqrti.on('notification', ({ title, body, type }) => {
    showDesktopToast(title, body, type);
  });

  function showDesktopToast(title, body, type = 'info') {
    const colours = {
      'critical-failure': { bg: 'rgba(239,68,68,0.15)', border: 'rgba(239,68,68,0.4)', text: '#ef4444' },
      'regime-change':    { bg: 'rgba(245,158,11,0.15)', border: 'rgba(245,158,11,0.4)', text: '#f59e0b' },
      'daily-brief-ready':{ bg: 'rgba(34,197,94,0.15)', border: 'rgba(34,197,94,0.4)',  text: '#22c55e' },
    };
    const c = colours[type] || { bg: 'rgba(99,102,241,0.15)', border: 'rgba(99,102,241,0.4)', text: '#6366f1' };

    const toast = document.createElement('div');
    toast.style.cssText = `
      position:fixed;bottom:20px;right:20px;z-index:99999;
      background:${c.bg};border:1px solid ${c.border};color:${c.text};
      font-family:'JetBrains Mono',monospace;font-size:0.68rem;
      padding:10px 16px;border-radius:7px;max-width:320px;
      animation:fadeIn 0.25s ease;
    `;
    toast.innerHTML = `<div style="font-weight:500;margin-bottom:2px">${title}</div><div style="opacity:0.8;font-size:0.62rem">${body}</div>`;
    document.body.appendChild(toast);
    setTimeout(() => toast.remove(), 5000);
  }

  // ── Update banner ─────────────────────────────────────────
  window.aqrti.on('update-available', ({ version }) => {
    showDesktopToast(
      'Update Available',
      `AQRTI v${version} is ready to download.`,
      'info'
    );
  });

  // ── Menu navigation events ────────────────────────────────
  window.aqrti.on('nav', (page) => {
    const item = document.querySelector(`.nav-item[data-page="${page}"]`);
    if (item) item.click();
  });

  // ── Admin action triggers from menu ──────────────────────
  window.aqrti.on('admin-action', async (action) => {
    const map = {
      'ingest':      () => Api.triggerIngestion?.(),
      'features':    () => fetch('http://localhost:8000/admin/features', { method: 'POST' }),
      'news':        () => fetch('http://localhost:8000/admin/news', { method: 'POST' }),
      'sentiment':   () => fetch('http://localhost:8000/admin/sentiment', { method: 'POST' }),
      'predict':     () => Api.triggerPredictions?.(),
      'paper-trade': () => Api.triggerPaperTrade?.(),
    };
    if (map[action]) {
      try { await map[action](); } catch (_) {}
      showDesktopToast('Pipeline triggered', action, 'info');
    }
  });

  // ── Backup shortcut from menu ─────────────────────────────
  window.aqrti.on('create-backup', async () => {
    const r = await window.aqrti.backup.create({ label: 'menu' });
    showDesktopToast(
      r.ok ? 'Backup Created' : 'Backup Failed',
      r.ok ? r.id : (r.error || ''),
      r.ok ? 'daily-brief-ready' : 'critical-failure'
    );
  });

  // ── Keyboard shortcuts ────────────────────────────────────
  document.addEventListener('keydown', (e) => {
    if (e.key === 'F11') window.aqrti.window.toggleFullscreen();
    if ((e.ctrlKey || e.metaKey) && e.key === ',') window.aqrti.window.openSettings();
    if ((e.ctrlKey || e.metaKey) && e.key === 'b') {
      window.aqrti.backup.create({ label: 'hotkey' });
    }
  });

  console.log('[AQRTI Desktop] Bridge active.');
})();
