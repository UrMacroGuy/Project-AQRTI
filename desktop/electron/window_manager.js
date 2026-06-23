/**
 * AQRTI Window Manager
 * Creates and manages all application windows.
 */

'use strict';

const { BrowserWindow, screen } = require('electron');
const path = require('path');

class WindowManager {
  constructor() {
    this.mainWindow = null;
    this.splashWindow = null;
    this.settingsWindow = null;
    this.storageWindow = null;
    this.backupWindow = null;
    this.windows = new Map();
  }

  // ── Splash / Loading Window ───────────────────────────────
  createSplashWindow() {
    this.splashWindow = new BrowserWindow({
      width: 600,
      height: 400,
      frame: false,
      transparent: true,
      alwaysOnTop: true,
      resizable: false,
      center: true,
      skipTaskbar: true,
      webPreferences: {
        preload: path.join(__dirname, 'preload.js'),
        contextIsolation: true,
        nodeIntegration: false,
        sandbox: true,
      },
    });

    this.splashWindow.loadFile(path.join(__dirname, '..', 'splash', 'splash.html'));
    this.splashWindow.on('closed', () => {
      this.splashWindow = null;
    });

    return this.splashWindow;
  }

  // ── Main Terminal Window ──────────────────────────────────
  createMainWindow() {
    const { width, height } = screen.getPrimaryDisplay().workAreaSize;

    this.mainWindow = new BrowserWindow({
      width: Math.min(1600, width),
      height: Math.min(960, height),
      minWidth: 1280,
      minHeight: 720,
      frame: false,           // custom titlebar
      transparent: false,
      backgroundColor: '#0a0a0f',
      show: false,            // show after startup completes
      title: 'AQRTI Intelligence Terminal',
      icon: path.join(__dirname, '..', 'assets', 'icon.png'),
      webPreferences: {
        preload: path.join(__dirname, 'preload.js'),
        contextIsolation: true,
        nodeIntegration: false,
        sandbox: false,       // sandbox=false needed for preload IPC
        webSecurity: true,
        allowRunningInsecureContent: false,
      },
    });

    this.mainWindow.loadFile(path.join(__dirname, '..', '..', 'ui', 'index.html'));

    // Persist window size/position
    this.mainWindow.on('close', (event) => {
      if (!this.mainWindow.isDestroyed()) {
        const bounds = this.mainWindow.getBounds();
        // Store bounds for next launch
        try {
          const store = require('./settings_store');
          store.set('windowBounds', bounds);
        } catch (_) {}
      }
    });

    this.mainWindow.on('closed', () => {
      this.mainWindow = null;
    });

    // Restore saved bounds if available
    try {
      const store = require('./settings_store');
      const saved = store.get('windowBounds');
      if (saved) this.mainWindow.setBounds(saved);
    } catch (_) {}

    // Open DevTools in development
    if (process.env.AQRTI_DEV === '1') {
      this.mainWindow.webContents.openDevTools({ mode: 'detach' });
    }

    // Block navigation to external URLs — keep app contained
    this.mainWindow.webContents.on('will-navigate', (event, url) => {
      const { shell } = require('electron');
      if (!url.startsWith('file://')) {
        event.preventDefault();
        shell.openExternal(url);
      }
    });

    this.mainWindow.webContents.setWindowOpenHandler(({ url }) => {
      const { shell } = require('electron');
      shell.openExternal(url);
      return { action: 'deny' };
    });

    return this.mainWindow;
  }

  // ── Settings Window ───────────────────────────────────────
  createSettingsWindow() {
    if (this.settingsWindow && !this.settingsWindow.isDestroyed()) {
      this.settingsWindow.focus();
      return this.settingsWindow;
    }

    this.settingsWindow = new BrowserWindow({
      width: 900,
      height: 650,
      parent: this.mainWindow,
      modal: false,
      frame: false,
      backgroundColor: '#0a0a0f',
      resizable: true,
      title: 'AQRTI Settings',
      icon: path.join(__dirname, '..', 'assets', 'icon.png'),
      webPreferences: {
        preload: path.join(__dirname, 'preload.js'),
        contextIsolation: true,
        nodeIntegration: false,
        sandbox: false,
      },
    });

    this.settingsWindow.loadFile(path.join(__dirname, '..', 'panels', 'settings.html'));
    this.settingsWindow.on('closed', () => {
      this.settingsWindow = null;
    });

    return this.settingsWindow;
  }

  // ── Storage Dashboard Window ──────────────────────────────
  createStorageWindow() {
    if (this.storageWindow && !this.storageWindow.isDestroyed()) {
      this.storageWindow.focus();
      return this.storageWindow;
    }

    this.storageWindow = new BrowserWindow({
      width: 800,
      height: 600,
      parent: this.mainWindow,
      modal: false,
      frame: false,
      backgroundColor: '#0a0a0f',
      resizable: true,
      title: 'AQRTI Storage',
      webPreferences: {
        preload: path.join(__dirname, 'preload.js'),
        contextIsolation: true,
        nodeIntegration: false,
        sandbox: false,
      },
    });

    this.storageWindow.loadFile(path.join(__dirname, '..', 'panels', 'storage.html'));
    this.storageWindow.on('closed', () => {
      this.storageWindow = null;
    });

    return this.storageWindow;
  }

  // ── Backup Center Window ──────────────────────────────────
  createBackupWindow() {
    if (this.backupWindow && !this.backupWindow.isDestroyed()) {
      this.backupWindow.focus();
      return this.backupWindow;
    }

    this.backupWindow = new BrowserWindow({
      width: 850,
      height: 620,
      parent: this.mainWindow,
      modal: false,
      frame: false,
      backgroundColor: '#0a0a0f',
      resizable: true,
      title: 'AQRTI Backup Center',
      webPreferences: {
        preload: path.join(__dirname, 'preload.js'),
        contextIsolation: true,
        nodeIntegration: false,
        sandbox: false,
      },
    });

    this.backupWindow.loadFile(path.join(__dirname, '..', 'panels', 'backup.html'));
    this.backupWindow.on('closed', () => {
      this.backupWindow = null;
    });

    return this.backupWindow;
  }

  // ── Broadcast to all windows ──────────────────────────────
  broadcast(channel, data) {
    const wins = BrowserWindow.getAllWindows();
    wins.forEach((win) => {
      if (!win.isDestroyed()) {
        win.webContents.send(channel, data);
      }
    });
  }

  closeAll() {
    BrowserWindow.getAllWindows().forEach((win) => {
      if (!win.isDestroyed()) win.destroy();
    });
  }
}

module.exports = { WindowManager };
