/**
 * AQRTI Native Menu Builder (D12)
 * Builds the application menu with keyboard shortcuts.
 */

'use strict';

const { Menu, app, shell, dialog } = require('electron');

function buildAppMenu(windowManager, backendManager, processManager) {
  const isMac = process.platform === 'darwin';

  const template = [
    // ── App menu (macOS only) ──────────────────────────────
    ...(isMac ? [{
      label: 'AQRTI',
      submenu: [
        { role: 'about' },
        { type: 'separator' },
        { role: 'services' },
        { type: 'separator' },
        { role: 'hide' },
        { role: 'hideOthers' },
        { role: 'unhide' },
        { type: 'separator' },
        { role: 'quit' },
      ],
    }] : []),

    // ── Terminal ──────────────────────────────────────────
    {
      label: 'Terminal',
      submenu: [
        {
          label: 'Overview',
          accelerator: 'CmdOrCtrl+1',
          click: () => windowManager.mainWindow?.webContents.send('nav', 'overview'),
        },
        {
          label: 'Market Intelligence',
          accelerator: 'CmdOrCtrl+2',
          click: () => windowManager.mainWindow?.webContents.send('nav', 'market'),
        },
        {
          label: 'Opportunity Rankings',
          accelerator: 'CmdOrCtrl+3',
          click: () => windowManager.mainWindow?.webContents.send('nav', 'opportunities'),
        },
        {
          label: 'News Intelligence',
          accelerator: 'CmdOrCtrl+4',
          click: () => windowManager.mainWindow?.webContents.send('nav', 'news'),
        },
        {
          label: 'Sentiment Engine',
          accelerator: 'CmdOrCtrl+5',
          click: () => windowManager.mainWindow?.webContents.send('nav', 'sentiment'),
        },
        {
          label: 'Strategy Lab',
          accelerator: 'CmdOrCtrl+6',
          click: () => windowManager.mainWindow?.webContents.send('nav', 'strategy'),
        },
        {
          label: 'Model Center',
          accelerator: 'CmdOrCtrl+7',
          click: () => windowManager.mainWindow?.webContents.send('nav', 'models'),
        },
        {
          label: 'Learning Center',
          accelerator: 'CmdOrCtrl+8',
          click: () => windowManager.mainWindow?.webContents.send('nav', 'learning'),
        },
        {
          label: 'Risk Center',
          accelerator: 'CmdOrCtrl+9',
          click: () => windowManager.mainWindow?.webContents.send('nav', 'risk'),
        },
        { type: 'separator' },
        {
          label: 'Toggle Full Screen',
          accelerator: isMac ? 'Ctrl+Command+F' : 'F11',
          click: () => {
            const win = windowManager.mainWindow;
            if (win) win.setFullScreen(!win.isFullScreen());
          },
        },
        { type: 'separator' },
        {
          label: 'Minimize to Tray',
          accelerator: 'CmdOrCtrl+M',
          click: () => windowManager.mainWindow?.hide(),
        },
        ...(!isMac ? [{
          label: 'Quit AQRTI',
          accelerator: 'Alt+F4',
          click: () => app.quit(),
        }] : []),
      ],
    },

    // ── Backend ───────────────────────────────────────────
    {
      label: 'Backend',
      submenu: [
        {
          label: 'Restart Backend',
          accelerator: 'CmdOrCtrl+Shift+R',
          click: async () => {
            await backendManager.restart();
          },
        },
        {
          label: 'View Backend Logs',
          click: () => {
            windowManager.mainWindow?.webContents.send('show-logs');
          },
        },
        { type: 'separator' },
        {
          label: 'Run Diagnostics',
          click: () => {
            windowManager.mainWindow?.webContents.send('run-diagnostics');
          },
        },
        {
          label: 'Open Data Directory',
          click: () => {
            shell.openPath(processManager.getDataDir());
          },
        },
        {
          label: 'Open Logs Directory',
          click: () => {
            shell.openPath(processManager.getLogsDir());
          },
        },
      ],
    },

    // ── Data ──────────────────────────────────────────────
    {
      label: 'Data',
      submenu: [
        {
          label: 'Force Data Ingest',
          click: () => windowManager.mainWindow?.webContents.send('admin-action', 'ingest'),
        },
        {
          label: 'Run Feature Pipeline',
          click: () => windowManager.mainWindow?.webContents.send('admin-action', 'features'),
        },
        {
          label: 'Run News Pipeline',
          click: () => windowManager.mainWindow?.webContents.send('admin-action', 'news'),
        },
        {
          label: 'Run Sentiment Pipeline',
          click: () => windowManager.mainWindow?.webContents.send('admin-action', 'sentiment'),
        },
        { type: 'separator' },
        {
          label: 'Run Prediction Pipeline',
          click: () => windowManager.mainWindow?.webContents.send('admin-action', 'predict'),
        },
        {
          label: 'Run Paper Trading Cycle',
          click: () => windowManager.mainWindow?.webContents.send('admin-action', 'paper-trade'),
        },
      ],
    },

    // ── Tools ─────────────────────────────────────────────
    {
      label: 'Tools',
      submenu: [
        {
          label: 'Settings',
          accelerator: 'CmdOrCtrl+,',
          click: () => windowManager.createSettingsWindow(),
        },
        {
          label: 'Storage Dashboard',
          click: () => windowManager.createStorageWindow(),
        },
        {
          label: 'Backup Center',
          click: () => windowManager.createBackupWindow(),
        },
        { type: 'separator' },
        {
          label: 'Create Backup Now',
          accelerator: 'CmdOrCtrl+B',
          click: () => windowManager.mainWindow?.webContents.send('create-backup'),
        },
        { type: 'separator' },
        {
          label: 'Check for Updates',
          click: () => {
            try {
              const { autoUpdater } = require('electron-updater');
              autoUpdater.checkForUpdates();
            } catch (_) {
              dialog.showMessageBox({ message: 'Auto-update not configured in development mode.' });
            }
          },
        },
      ],
    },

    // ── View ──────────────────────────────────────────────
    {
      label: 'View',
      submenu: [
        { role: 'reload', accelerator: 'CmdOrCtrl+Shift+F5' },
        { type: 'separator' },
        { role: 'resetZoom' },
        { role: 'zoomIn', accelerator: 'CmdOrCtrl+=' },
        { role: 'zoomOut' },
        { type: 'separator' },
        { role: 'togglefullscreen', accelerator: 'F11' },
        { type: 'separator' },
        {
          label: 'Toggle DevTools',
          accelerator: 'F12',
          click: (_, win) => { if (win) win.webContents.toggleDevTools(); },
        },
      ],
    },

    // ── Help ──────────────────────────────────────────────
    {
      role: 'help',
      submenu: [
        {
          label: `AQRTI v${app.getVersion()}`,
          enabled: false,
        },
        { type: 'separator' },
        {
          label: 'Open Logs Folder',
          click: () => shell.openPath(processManager.getLogsDir()),
        },
        {
          label: 'About AQRTI',
          click: () => {
            dialog.showMessageBox({
              type: 'info',
              title: 'About AQRTI',
              message: 'AQRTI Intelligence Terminal',
              detail: [
                `Version: ${app.getVersion()}`,
                'Autonomous Quantitative Research & Trading Intelligence',
                '',
                'NSE India · AI-Powered · Paper Trading',
              ].join('\n'),
              buttons: ['Close'],
            });
          },
        },
      ],
    },
  ];

  return Menu.buildFromTemplate(template);
}

module.exports = { buildAppMenu };
