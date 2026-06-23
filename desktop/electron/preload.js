/**
 * AQRTI Preload Script
 * Exposes a safe, typed bridge between renderer (UI) and main process.
 * contextIsolation: true — renderer cannot access Node.js directly.
 */

'use strict';

const { contextBridge, ipcRenderer } = require('electron');

// ── Safe IPC bridge ───────────────────────────────────────────
contextBridge.exposeInMainWorld('aqrti', {

  // ── Backend status ────────────────────────────────────────
  backend: {
    getStatus: () => ipcRenderer.invoke('backend:status'),
    restart: () => ipcRenderer.invoke('backend:restart'),
    getPort: () => ipcRenderer.invoke('backend:port'),
    getLogs: (lines) => ipcRenderer.invoke('backend:logs', lines),
  },

  // ── Services ──────────────────────────────────────────────
  services: {
    getAll: () => ipcRenderer.invoke('services:all'),
    restart: (name) => ipcRenderer.invoke('services:restart', name),
    getLogs: (name, lines) => ipcRenderer.invoke('services:logs', name, lines),
  },

  // ── Storage ───────────────────────────────────────────────
  storage: {
    getStats: () => ipcRenderer.invoke('storage:stats'),
    getDataDir: () => ipcRenderer.invoke('storage:data-dir'),
    openDataDir: () => ipcRenderer.invoke('storage:open-data-dir'),
  },

  // ── Backup ────────────────────────────────────────────────
  backup: {
    create: (options) => ipcRenderer.invoke('backup:create', options),
    list: () => ipcRenderer.invoke('backup:list'),
    restore: (backupId) => ipcRenderer.invoke('backup:restore', backupId),
    verify: (backupId) => ipcRenderer.invoke('backup:verify', backupId),
    delete: (backupId) => ipcRenderer.invoke('backup:delete', backupId),
    getSchedule: () => ipcRenderer.invoke('backup:schedule-get'),
    setSchedule: (cron) => ipcRenderer.invoke('backup:schedule-set', cron),
  },

  // ── Settings ──────────────────────────────────────────────
  settings: {
    get: (key) => ipcRenderer.invoke('settings:get', key),
    set: (key, value) => ipcRenderer.invoke('settings:set', key, value),
    getAll: () => ipcRenderer.invoke('settings:all'),
    reset: () => ipcRenderer.invoke('settings:reset'),
  },

  // ── Notifications ─────────────────────────────────────────
  notifications: {
    getHistory: () => ipcRenderer.invoke('notifications:history'),
    dismiss: (id) => ipcRenderer.invoke('notifications:dismiss', id),
    clearAll: () => ipcRenderer.invoke('notifications:clear'),
    getSettings: () => ipcRenderer.invoke('notifications:settings-get'),
    setSettings: (s) => ipcRenderer.invoke('notifications:settings-set', s),
  },

  // ── Recovery ─────────────────────────────────────────────
  recovery: {
    runDiagnostics: () => ipcRenderer.invoke('recovery:diagnostics'),
    repairDatabase: () => ipcRenderer.invoke('recovery:repair-db'),
    repairVault: () => ipcRenderer.invoke('recovery:repair-vault'),
    resetToDefault: () => ipcRenderer.invoke('recovery:reset'),
  },

  // ── Window controls ───────────────────────────────────────
  window: {
    minimize: () => ipcRenderer.invoke('window:minimize'),
    maximize: () => ipcRenderer.invoke('window:maximize'),
    close: () => ipcRenderer.invoke('window:close'),
    toggleFullscreen: () => ipcRenderer.invoke('window:fullscreen'),
    isMaximized: () => ipcRenderer.invoke('window:is-maximized'),
    openSettings: () => ipcRenderer.invoke('window:open-settings'),
    openStorage: () => ipcRenderer.invoke('window:open-storage'),
    openBackup: () => ipcRenderer.invoke('window:open-backup'),
  },

  // ── Updates ───────────────────────────────────────────────
  updates: {
    check: () => ipcRenderer.invoke('updates:check'),
    download: () => ipcRenderer.invoke('updates:download'),
    install: () => ipcRenderer.invoke('updates:install'),
    getVersion: () => ipcRenderer.invoke('updates:version'),
  },

  // ── App ───────────────────────────────────────────────────
  app: {
    getVersion: () => ipcRenderer.invoke('app:version'),
    openExternal: (url) => ipcRenderer.invoke('app:open-external', url),
    showSaveDialog: (opts) => ipcRenderer.invoke('app:save-dialog', opts),
    showOpenDialog: (opts) => ipcRenderer.invoke('app:open-dialog', opts),
    quit: () => ipcRenderer.invoke('app:quit'),
  },

  // ── Event listeners (renderer subscribes to main events) ──
  on: (channel, callback) => {
    const ALLOWED_CHANNELS = [
      'startup-progress',
      'startup-error',
      'backend-status-change',
      'service-status-change',
      'notification',
      'update-available',
      'update-downloaded',
      'update-progress',
      'backup-complete',
      'recovery-result',
      'regime-change',
      'daily-brief-ready',
      'critical-failure',
    ];

    if (ALLOWED_CHANNELS.includes(channel)) {
      ipcRenderer.on(channel, (event, ...args) => callback(...args));
    }
  },

  removeListener: (channel, callback) => {
    ipcRenderer.removeListener(channel, callback);
  },

  removeAllListeners: (channel) => {
    ipcRenderer.removeAllListeners(channel);
  },
});

// ── Platform info ─────────────────────────────────────────────
contextBridge.exposeInMainWorld('platform', {
  isWindows: process.platform === 'win32',
  isMac: process.platform === 'darwin',
  isLinux: process.platform === 'linux',
  arch: process.arch,
});
