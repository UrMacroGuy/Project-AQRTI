/**
 * AQRTI Auto-Update System (D8)
 * GitHub Releases compatible via electron-updater.
 * Safe: downloads in background, installs only on user confirmation.
 */

'use strict';

const store = require('./settings_store');

function setupAutoUpdater(mainWindow) {
  // Skip in development
  if (process.env.AQRTI_DEV === '1' || !mainWindow) return;

  let autoUpdater;
  try {
    ({ autoUpdater } = require('electron-updater'));
  } catch (_) {
    // electron-updater not installed yet — skip gracefully
    console.log('[AutoUpdater] electron-updater not available, skipping.');
    return;
  }

  if (!store.get('autoUpdate')) return;

  autoUpdater.autoDownload = false;       // ask user before downloading
  autoUpdater.autoInstallOnAppQuit = false;

  const send = (channel, data) => {
    if (mainWindow && !mainWindow.isDestroyed()) {
      mainWindow.webContents.send(channel, data);
    }
  };

  autoUpdater.on('checking-for-update', () => {
    console.log('[AutoUpdater] Checking for updates...');
  });

  autoUpdater.on('update-available', (info) => {
    console.log(`[AutoUpdater] Update available: v${info.version}`);
    send('update-available', {
      version: info.version,
      releaseDate: info.releaseDate,
      releaseNotes: info.releaseNotes,
    });
  });

  autoUpdater.on('update-not-available', () => {
    console.log('[AutoUpdater] Up to date.');
  });

  autoUpdater.on('download-progress', (progress) => {
    send('update-progress', {
      percent: Math.round(progress.percent),
      transferred: progress.transferred,
      total: progress.total,
      bytesPerSecond: progress.bytesPerSecond,
    });
  });

  autoUpdater.on('update-downloaded', (info) => {
    console.log(`[AutoUpdater] Downloaded v${info.version}`);
    send('update-downloaded', {
      version: info.version,
      releaseNotes: info.releaseNotes,
    });
  });

  autoUpdater.on('error', (err) => {
    console.error('[AutoUpdater] Error:', err.message);
  });

  // Check on startup, then every 4 hours
  autoUpdater.checkForUpdates().catch(() => {});
  setInterval(() => {
    autoUpdater.checkForUpdates().catch(() => {});
  }, 4 * 60 * 60 * 1000);
}

module.exports = { setupAutoUpdater };
