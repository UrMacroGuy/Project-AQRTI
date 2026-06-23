/**
 * AQRTI Intelligence Terminal — Electron Main Process
 * Entry point for the desktop application.
 */

'use strict';

// ── Ultra-early crash trap ────────────────────────────────────
const _fs = require('fs');
const _os = require('os');
const _cp = require('child_process');
function _boot(msg) {
  const line = '[' + new Date().toISOString() + '] ' + msg + '\n';
  const paths = [
    _os.tmpdir() + '\\aqrti-boot.log',
    _os.homedir() + '\\aqrti-boot.log',
    'C:\\Users\\praty\\aqrti-boot.log',
    'C:\\Users\\praty\\Desktop\\aqrti-boot.log',
    'C:\\Users\\praty\\AppData\\Local\\Temp\\aqrti-boot.log',
  ];
  let written = false;
  for (const p of paths) {
    try { _fs.appendFileSync(p, line); written = true; break; } catch(_) {}
  }
  if (!written) {
    // Last resort: spawn a PowerShell to write the log
    try { _cp.execSync('powershell -NonInteractive -Command "Add-Content \\"C:\\\\Users\\\\praty\\\\aqrti-ps.log\\" \\"' + line.replace(/"/g, '') + '\\""'); } catch(_) {}
  }
}
_boot('=== main.js start === argv=' + JSON.stringify(process.argv) + ' type=' + process.type);
process.on('uncaughtException', function(e) {
  _boot('UNCAUGHT: ' + e.message + '\n' + (e.stack || ''));
  process.exit(1);
});
process.on('unhandledRejection', function(r) {
  _boot('UNHANDLED REJECTION: ' + r);
});
_boot('requiring electron...');
const { app, BrowserWindow, ipcMain, Menu, Tray, nativeImage, shell, dialog, Notification } = require('electron');
_boot('electron required OK, app=' + typeof app);

// Disable GPU before app is ready to prevent GPU process hang on some Windows systems
if (app && app.commandLine) {
  app.commandLine.appendSwitch('disable-gpu');
  app.commandLine.appendSwitch('disable-software-rasterizer');
  app.commandLine.appendSwitch('disable-gpu-sandbox');
  _boot('GPU disabled via commandLine');
} else {
  _boot('WARNING: app or commandLine undefined');
}

const path = require('path');
const { WindowManager } = require('./window_manager');
const { BackendManager } = require('./backend_manager');
const { ProcessManager } = require('./process_manager');
const { setupAutoUpdater } = require('./auto_updater');
const { setupNotifications } = require('./notifications');
const { setupIPC } = require('./ipc_handlers');
const { buildAppMenu } = require('./menu_builder');

// ── Prevent multiple instances ────────────────────────────────
const gotLock = app.requestSingleInstanceLock();
if (!gotLock) {
  app.quit();
  process.exit(0);
}

// ── Global state ──────────────────────────────────────────────
let windowManager = null;
let backendManager = null;
let processManager = null;
let tray = null;
let isQuitting = false;

// ── App metadata ──────────────────────────────────────────────
app.setName('AQRTI Intelligence Terminal');
app.setAppUserModelId('com.aqrti.terminal');

// ── Security: disable remote module ──────────────────────────
app.on('remote-module-required', (event, moduleName) => {
  event.preventDefault();
});

// ── Second instance: focus existing window ────────────────────
app.on('second-instance', () => {
  if (windowManager && windowManager.mainWindow) {
    const win = windowManager.mainWindow;
    if (win.isMinimized()) win.restore();
    win.focus();
  }
});

function startupLog(msg) { _boot(msg); console.log(msg); }

// ── App ready ─────────────────────────────────────────────────
app.whenReady().then(async () => {
  startupLog('app.whenReady fired');
  processManager = new ProcessManager();
  backendManager = new BackendManager(processManager);
  windowManager = new WindowManager();
  startupLog('managers created');

  // Show splash/loading window immediately
  const splashWindow = windowManager.createSplashWindow();

  try {
    // Run startup sequence
    await runStartupSequence(splashWindow);

    // Create main terminal window
    const mainWindow = windowManager.createMainWindow();

    // Setup system tray
    tray = setupSystemTray(mainWindow);

    // Setup native menu
    Menu.setApplicationMenu(buildAppMenu(windowManager, backendManager, processManager));

    // Setup IPC handlers
    setupIPC(ipcMain, { windowManager, backendManager, processManager });

    // Setup notifications
    setupNotifications(backendManager);

    // Setup auto-updater
    setupAutoUpdater(mainWindow);

    // Close splash and show main
    setTimeout(() => {
      splashWindow.close();
      mainWindow.show();
    }, 800);

  } catch (err) {
    startupLog('FATAL: ' + err.message + '\n' + err.stack);
    console.error('[AQRTI] Fatal startup error:', err);
    try { splashWindow.webContents.send('startup-error', err.message); } catch(_) {}
    // Give user time to read the error
    setTimeout(() => {
      dialog.showErrorBox(
        'AQRTI Startup Failed',
        `Failed to start AQRTI Intelligence Terminal.\n\n${err.message}\n\nCheck logs for details.`
      );
      app.quit();
    }, 3000);
  }
});

// ── Startup sequence ──────────────────────────────────────────
async function runStartupSequence(splashWindow) {
  const send = (step, status, msg) => {
    if (splashWindow && !splashWindow.isDestroyed()) {
      splashWindow.webContents.send('startup-progress', { step, status, msg });
    }
  };

  // Step 1: Start FastAPI backend
  startupLog('Step 1: backend.start()');
  send(1, 'running', 'Starting AQRTI Backend...');
  await backendManager.start();
  startupLog('Step 1: done');
  send(1, 'ok', 'Backend started');

  // Step 2: Verify database
  send(2, 'running', 'Verifying database...');
  await backendManager.verifyDatabase();
  send(2, 'ok', 'Database ready');

  // Step 3: Verify vault
  send(3, 'running', 'Verifying Historical Vault...');
  await backendManager.verifyVault();
  send(3, 'ok', 'Vault ready');

  // Step 4: Verify scheduler
  send(4, 'running', 'Verifying Scheduler...');
  await backendManager.verifyScheduler();
  send(4, 'ok', 'Scheduler active');

  // Step 5: Verify model files
  send(5, 'running', 'Verifying Model Registry...');
  await backendManager.verifyModels();
  send(5, 'ok', 'Models ready');

  // Step 6: Verify data directories
  send(6, 'running', 'Verifying Data Directories...');
  await backendManager.verifyDataDirs();
  send(6, 'ok', 'Directories ready');

  // Step 7: Start background services
  send(7, 'running', 'Starting Background Services...');
  await processManager.startAll();
  send(7, 'ok', 'All services running');

  send(8, 'ok', 'AQRTI Intelligence Terminal Ready');
}

// ── System Tray ───────────────────────────────────────────────
function setupSystemTray(mainWindow) {
  const iconPath = path.join(__dirname, '..', 'assets', 'tray-icon.png');
  const icon = nativeImage.createFromPath(iconPath);
  const trayInstance = new Tray(icon.isEmpty() ? nativeImage.createEmpty() : icon);

  trayInstance.setToolTip('AQRTI Intelligence Terminal');

  const updateMenu = () => {
    const isRunning = backendManager.isRunning();
    const contextMenu = Menu.buildFromTemplate([
      {
        label: 'AQRTI Intelligence Terminal',
        enabled: false,
        icon: icon.isEmpty() ? undefined : icon.resize({ width: 16, height: 16 }),
      },
      { type: 'separator' },
      {
        label: 'Show Terminal',
        click: () => {
          mainWindow.show();
          mainWindow.focus();
        },
      },
      { type: 'separator' },
      {
        label: `Backend: ${isRunning ? '● RUNNING' : '○ STOPPED'}`,
        enabled: false,
      },
      {
        label: 'Restart Backend',
        click: async () => {
          await backendManager.restart();
          updateMenu();
        },
      },
      { type: 'separator' },
      {
        label: 'Open Data Directory',
        click: () => {
          shell.openPath(processManager.getDataDir());
        },
      },
      {
        label: 'Open Logs',
        click: () => {
          shell.openPath(processManager.getLogsDir());
        },
      },
      { type: 'separator' },
      {
        label: 'Quit AQRTI',
        click: () => {
          isQuitting = true;
          app.quit();
        },
      },
    ]);

    trayInstance.setContextMenu(contextMenu);
  };

  updateMenu();

  trayInstance.on('double-click', () => {
    mainWindow.show();
    mainWindow.focus();
  });

  // Update tray menu when backend status changes
  backendManager.on('status-change', updateMenu);

  return trayInstance;
}

// ── App window behavior ───────────────────────────────────────
app.on('window-all-closed', () => {
  // On Windows/Linux, keep running in tray
  if (process.platform !== 'darwin') {
    // Don't quit — stay in system tray
  }
});

app.on('activate', () => {
  if (windowManager && windowManager.mainWindow) {
    windowManager.mainWindow.show();
  }
});

app.on('before-quit', async (event) => {
  if (!isQuitting) {
    event.preventDefault();
    isQuitting = true;

    // Graceful shutdown
    try {
      await backendManager.stop();
      await processManager.stopAll();
    } catch (err) {
      console.error('[AQRTI] Shutdown error:', err.message);
    }

    if (tray) {
      tray.destroy();
      tray = null;
    }
    app.quit();
  }
});

// ── Crash recovery ────────────────────────────────────────────
process.on('uncaughtException', (err) => {
  console.error('[AQRTI] Uncaught exception:', err);
  if (backendManager) {
    backendManager.restart().catch(() => {});
  }
});
