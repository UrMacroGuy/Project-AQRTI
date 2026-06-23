/**
 * AQRTI IPC Handlers
 * Wires up all renderer → main process communication.
 * Called once from main.js after managers are initialized.
 */

'use strict';

const { shell, dialog, app } = require('electron');
const path = require('path');
const fs = require('fs');
const { BackupManager } = require('./backup_manager');
const { RecoverySystem } = require('./recovery_system');
const store = require('./settings_store');

function setupIPC(ipcMain, { windowManager, backendManager, processManager }) {
  const backupManager = new BackupManager(processManager);
  const recoverySystem = new RecoverySystem(processManager, backendManager);

  // ── Backend ──────────────────────────────────────────────
  ipcMain.handle('backend:status', () => ({
    running: backendManager.isRunning(),
    port: backendManager.getPort(),
  }));

  ipcMain.handle('backend:restart', async () => {
    await backendManager.restart();
    return { ok: true };
  });

  ipcMain.handle('backend:port', () => backendManager.getPort());

  ipcMain.handle('backend:logs', (_, lines = 200) => backendManager.getLogs(lines));

  // ── Services ─────────────────────────────────────────────
  ipcMain.handle('services:all', () => processManager.getServiceStatus());

  ipcMain.handle('services:restart', async (_, name) => {
    return processManager.restartService(name);
  });

  ipcMain.handle('services:logs', (_, name, lines = 100) => {
    return backendManager.getLogs(lines);
  });

  // ── Storage ──────────────────────────────────────────────
  ipcMain.handle('storage:stats', async () => {
    return processManager.getStorageStats();
  });

  ipcMain.handle('storage:data-dir', () => processManager.getDataDir());

  ipcMain.handle('storage:open-data-dir', () => {
    shell.openPath(processManager.getDataDir());
  });

  // ── Backup ───────────────────────────────────────────────
  ipcMain.handle('backup:create', async (_, options) => {
    return backupManager.create(options);
  });

  ipcMain.handle('backup:list', async () => {
    return backupManager.list();
  });

  ipcMain.handle('backup:restore', async (_, backupId) => {
    return backupManager.restore(backupId);
  });

  ipcMain.handle('backup:verify', async (_, backupId) => {
    return backupManager.verify(backupId);
  });

  ipcMain.handle('backup:delete', async (_, backupId) => {
    return backupManager.delete(backupId);
  });

  ipcMain.handle('backup:schedule-get', () => store.get('backupSchedule'));

  ipcMain.handle('backup:schedule-set', (_, cron) => {
    store.set('backupSchedule', cron);
    return { ok: true };
  });

  // ── Settings ─────────────────────────────────────────────
  ipcMain.handle('settings:get', (_, key) => store.get(key));

  ipcMain.handle('settings:set', (_, key, value) => {
    store.set(key, value);
    return { ok: true };
  });

  ipcMain.handle('settings:all', () => store.getAll());

  ipcMain.handle('settings:reset', () => {
    store.reset();
    return { ok: true };
  });

  // ── Notifications ─────────────────────────────────────────
  const notifHistory = [];

  ipcMain.handle('notifications:history', () => notifHistory.slice(-100));

  ipcMain.handle('notifications:dismiss', (_, id) => {
    const idx = notifHistory.findIndex((n) => n.id === id);
    if (idx >= 0) notifHistory[idx].dismissed = true;
    return { ok: true };
  });

  ipcMain.handle('notifications:clear', () => {
    notifHistory.length = 0;
    return { ok: true };
  });

  ipcMain.handle('notifications:settings-get', () => ({
    regimeChange: store.get('notifyRegimeChange'),
    dailyBrief: store.get('notifyDailyBrief'),
    criticalFailure: store.get('notifyCriticalFailure'),
    dataSourceFailure: store.get('notifyDataSourceFailure'),
    researchFindings: store.get('notifyResearchFindings'),
    predictionReport: store.get('notifyPredictionReport'),
  }));

  ipcMain.handle('notifications:settings-set', (_, s) => {
    if (s.regimeChange !== undefined) store.set('notifyRegimeChange', s.regimeChange);
    if (s.dailyBrief !== undefined) store.set('notifyDailyBrief', s.dailyBrief);
    if (s.criticalFailure !== undefined) store.set('notifyCriticalFailure', s.criticalFailure);
    if (s.dataSourceFailure !== undefined) store.set('notifyDataSourceFailure', s.dataSourceFailure);
    if (s.researchFindings !== undefined) store.set('notifyResearchFindings', s.researchFindings);
    if (s.predictionReport !== undefined) store.set('notifyPredictionReport', s.predictionReport);
    return { ok: true };
  });

  // ── Recovery ─────────────────────────────────────────────
  ipcMain.handle('recovery:diagnostics', async () => {
    return recoverySystem.runDiagnostics();
  });

  ipcMain.handle('recovery:repair-db', async () => {
    return recoverySystem.repairDatabase();
  });

  ipcMain.handle('recovery:repair-vault', async () => {
    return recoverySystem.repairVault();
  });

  ipcMain.handle('recovery:reset', async () => {
    const { response } = await dialog.showMessageBox({
      type: 'warning',
      buttons: ['Reset', 'Cancel'],
      defaultId: 1,
      title: 'Reset AQRTI',
      message: 'This will reset all settings to defaults. Data files will not be deleted.',
    });
    if (response === 0) {
      store.reset();
      return { ok: true };
    }
    return { ok: false, cancelled: true };
  });

  // ── Window controls ───────────────────────────────────────
  ipcMain.handle('window:minimize', () => {
    windowManager.mainWindow?.minimize();
  });

  ipcMain.handle('window:maximize', () => {
    const win = windowManager.mainWindow;
    if (!win) return;
    win.isMaximized() ? win.unmaximize() : win.maximize();
  });

  ipcMain.handle('window:close', () => {
    const win = windowManager.mainWindow;
    if (win) win.hide();  // hide to tray, don't quit
  });

  ipcMain.handle('window:fullscreen', () => {
    const win = windowManager.mainWindow;
    if (!win) return;
    win.setFullScreen(!win.isFullScreen());
  });

  ipcMain.handle('window:is-maximized', () => {
    return windowManager.mainWindow?.isMaximized() ?? false;
  });

  ipcMain.handle('window:open-settings', () => {
    windowManager.createSettingsWindow();
  });

  ipcMain.handle('window:open-storage', () => {
    windowManager.createStorageWindow();
  });

  ipcMain.handle('window:open-backup', () => {
    windowManager.createBackupWindow();
  });

  // ── Updates ───────────────────────────────────────────────
  ipcMain.handle('updates:version', () => app.getVersion());

  ipcMain.handle('updates:check', () => {
    const { autoUpdater } = require('electron-updater');
    autoUpdater.checkForUpdates();
    return { ok: true };
  });

  ipcMain.handle('updates:download', () => {
    const { autoUpdater } = require('electron-updater');
    autoUpdater.downloadUpdate();
    return { ok: true };
  });

  ipcMain.handle('updates:install', () => {
    const { autoUpdater } = require('electron-updater');
    autoUpdater.quitAndInstall();
  });

  // ── App ───────────────────────────────────────────────────
  ipcMain.handle('app:version', () => app.getVersion());

  ipcMain.handle('app:open-external', async (_, url) => {
    // Only allow http/https URLs
    if (url.startsWith('http://') || url.startsWith('https://')) {
      await shell.openExternal(url);
      return { ok: true };
    }
    return { ok: false, error: 'Blocked non-http URL' };
  });

  ipcMain.handle('app:save-dialog', async (_, opts) => {
    return dialog.showSaveDialog(opts);
  });

  ipcMain.handle('app:open-dialog', async (_, opts) => {
    return dialog.showOpenDialog(opts);
  });

  ipcMain.handle('app:quit', () => {
    app.quit();
  });
}

module.exports = { setupIPC };
