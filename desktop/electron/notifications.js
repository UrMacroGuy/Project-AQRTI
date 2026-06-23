/**
 * AQRTI Notification System (D7)
 * Polls backend for important events and fires native OS notifications.
 */

'use strict';

const { Notification, BrowserWindow } = require('electron');
const http = require('http');
const store = require('./settings_store');

const POLL_INTERVAL_MS = 60_000; // check every minute
let _timer = null;
let _lastRegime = null;
let _lastBriefDate = null;
let _backendManager = null;

function setupNotifications(backendManager) {
  _backendManager = backendManager;

  backendManager.on('critical-failure', (msg) => {
    if (store.get('notifyCriticalFailure')) {
      fireNotification('AQRTI Critical Failure', msg, 'critical-failure');
    }
  });

  // Start polling after backend is running
  backendManager.on('status-change', (status) => {
    if (status === 'running') {
      startPolling();
    } else {
      stopPolling();
    }
  });
}

function startPolling() {
  stopPolling();
  _timer = setInterval(pollEvents, POLL_INTERVAL_MS);
}

function stopPolling() {
  if (_timer) {
    clearInterval(_timer);
    _timer = null;
  }
}

async function pollEvents() {
  if (!_backendManager || !_backendManager.isRunning()) return;

  await Promise.allSettled([
    checkRegimeChange(),
    checkDailyBrief(),
    checkDataSources(),
  ]);
}

async function checkRegimeChange() {
  if (!store.get('notifyRegimeChange')) return;

  const data = await apiGet('/api/v1/market-regime');
  if (!data) return;

  const current = data.regime;
  if (_lastRegime && _lastRegime !== current) {
    fireNotification(
      'Market Regime Change',
      `Regime shifted: ${_lastRegime} → ${current}`,
      'regime-change',
      { from: _lastRegime, to: current }
    );
  }
  _lastRegime = current;
}

async function checkDailyBrief() {
  if (!store.get('notifyDailyBrief')) return;

  const data = await apiGet('/api/v1/research-briefs/today');
  if (!data) return;

  const date = data.date;
  if (date && date !== _lastBriefDate) {
    _lastBriefDate = date;
    fireNotification(
      'AQRTI Daily Brief Ready',
      `Research brief for ${date} is available.`,
      'daily-brief-ready',
      { date }
    );
  }
}

async function checkDataSources() {
  if (!store.get('notifyDataSourceFailure')) return;

  const data = await apiGet('/health');
  if (!data) return;

  if (data.data_source_error) {
    fireNotification(
      'Data Source Failure',
      `Market data feed issue: ${data.data_source_error}`,
      'notification'
    );
  }
}

// ── Fire native notification + send to renderer ───────────────
function fireNotification(title, body, channel, extra = {}) {
  // Native OS notification
  if (Notification.isSupported()) {
    const n = new Notification({ title, body, silent: false });
    n.show();
  }

  // Send to all renderer windows
  BrowserWindow.getAllWindows().forEach((win) => {
    if (!win.isDestroyed()) {
      win.webContents.send(channel, { title, body, ts: Date.now(), ...extra });
      win.webContents.send('notification', { title, body, ts: Date.now(), type: channel, ...extra });
    }
  });
}

// ── HTTP helper ───────────────────────────────────────────────
function apiGet(endpoint) {
  return new Promise((resolve) => {
    http.get(`http://127.0.0.1:8000${endpoint}`, (res) => {
      let body = '';
      res.on('data', (d) => { body += d; });
      res.on('end', () => {
        try { resolve(JSON.parse(body)); }
        catch (_) { resolve(null); }
      });
    }).on('error', () => resolve(null));
  });
}

module.exports = { setupNotifications, fireNotification };
