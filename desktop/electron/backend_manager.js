/**
 * AQRTI Backend Manager
 * Spawns, monitors, and manages the embedded FastAPI backend process.
 * Supports both dev (python main.py) and production (bundled .exe) modes.
 */

'use strict';

const { EventEmitter } = require('events');
const { spawn, execFile } = require('child_process');
const path = require('path');
const fs = require('fs');
const http = require('http');
const { app } = require('electron');

const BACKEND_PORT = 8000;
const HEALTH_URL = `http://127.0.0.1:${BACKEND_PORT}/health`;
const STARTUP_TIMEOUT_MS = 60_000;
const HEALTH_POLL_INTERVAL_MS = 500;
const MAX_RESTART_ATTEMPTS = 3;

class BackendManager extends EventEmitter {
  constructor(processManager) {
    super();
    this.processManager = processManager;
    this.process = null;
    this.port = BACKEND_PORT;
    this.running = false;
    this.restartAttempts = 0;
    this.logs = [];
    this.maxLogLines = 2000;
  }

  // ── Determine backend executable path ─────────────────────
  _getBackendPath() {
    const isPackaged = app.isPackaged;

    if (isPackaged) {
      // Production: bundled Python executable via PyInstaller
      const exeName = process.platform === 'win32' ? 'aqrti_backend.exe' : 'aqrti_backend';
      return path.join(process.resourcesPath, 'backend', exeName);
    } else {
      // Development: run Python directly
      return null; // signals dev mode
    }
  }

  _getBackendDir() {
    const isPackaged = app.isPackaged;
    if (isPackaged) {
      return path.join(process.resourcesPath, 'backend');
    }
    // Dev: backend/ sibling of desktop/
    return path.join(__dirname, '..', '..', 'backend');
  }

  _buildEnv() {
    const dataDir = this.processManager.getDataDir();
    return {
      ...process.env,
      AQRTI_HOST: '127.0.0.1',
      AQRTI_PORT: String(this.port),
      AQRTI_RELOAD: 'false',
      AQRTI_LOG_LEVEL: 'INFO',
      AQRTI_DB_PATH: path.join(dataDir, 'aqrti.db'),
      AQRTI_VAULT_PATH: path.join(dataDir, 'vault'),
      AQRTI_MODELS_PATH: path.join(dataDir, 'models'),
      AQRTI_DATA_PATH: dataDir,
      PYTHONUNBUFFERED: '1',
      PYTHONDONTWRITEBYTECODE: '1',
    };
  }

  // ── Start backend ─────────────────────────────────────────
  async start() {
    if (this.running) return;

    // If backend is already running (e.g. started externally), adopt it
    const alreadyAlive = await this._pingHealth();
    if (alreadyAlive) {
      this._log('[BackendManager] Backend already running — adopting existing process.');
      this.running = true;
      this.emit('status-change', 'running');
      return;
    }

    const backendExe = this._getBackendPath();
    const backendDir = this._getBackendDir();
    const env = this._buildEnv();

    this._log('[BackendManager] Starting FastAPI backend...');

    if (backendExe && fs.existsSync(backendExe)) {
      // Production: bundled exe
      this.process = spawn(backendExe, [], {
        cwd: backendDir,
        env,
        detached: false,
        stdio: ['ignore', 'pipe', 'pipe'],
      });
    } else {
      // Development: find Python interpreter
      const pythonCmd = await this._findPython();
      const mainPy = path.join(backendDir, 'main.py');

      this._log(`[BackendManager] Dev mode — python: ${pythonCmd}, main: ${mainPy}`);

      this.process = spawn(pythonCmd, [mainPy], {
        cwd: backendDir,
        env,
        detached: false,
        stdio: ['ignore', 'pipe', 'pipe'],
      });
    }

    this._attachProcessHandlers();
    await this._waitForHealthy();
    this.running = true;
    this.restartAttempts = 0;
    this.emit('status-change', 'running');
    this._log('[BackendManager] Backend is healthy and ready.');
  }

  // ── Attach stdout/stderr handlers ─────────────────────────
  _attachProcessHandlers() {
    this.process.stdout.on('data', (data) => {
      this._log(data.toString().trim());
    });

    this.process.stderr.on('data', (data) => {
      this._log('[ERR] ' + data.toString().trim());
    });

    this.process.on('exit', (code, signal) => {
      this.running = false;
      this._log(`[BackendManager] Process exited — code=${code} signal=${signal}`);
      this.emit('status-change', 'stopped');

      if (code !== 0 && code !== null) {
        this._attemptAutoRestart();
      }
    });

    this.process.on('error', (err) => {
      this._log(`[BackendManager] Spawn error: ${err.message}`);
      this.emit('status-change', 'error');
    });
  }

  // ── Single /health ping — true if already alive ───────────
  _pingHealth() {
    return new Promise((resolve) => {
      http.get(HEALTH_URL, (res) => {
        resolve(res.statusCode === 200);
        res.resume();
      }).on('error', () => resolve(false));
    });
  }

  // ── Poll /health until ready ──────────────────────────────
  _waitForHealthy() {
    return new Promise((resolve, reject) => {
      const deadline = Date.now() + STARTUP_TIMEOUT_MS;

      const poll = () => {
        if (Date.now() > deadline) {
          reject(new Error('Backend health check timed out after 60s'));
          return;
        }

        http.get(HEALTH_URL, (res) => {
          if (res.statusCode === 200) {
            resolve();
          } else {
            setTimeout(poll, HEALTH_POLL_INTERVAL_MS);
          }
          res.resume();
        }).on('error', () => {
          setTimeout(poll, HEALTH_POLL_INTERVAL_MS);
        });
      };

      poll();
    });
  }

  // ── Auto-restart on unexpected exit ──────────────────────
  async _attemptAutoRestart() {
    if (this.restartAttempts >= MAX_RESTART_ATTEMPTS) {
      this._log('[BackendManager] Max restart attempts reached. Emitting critical-failure.');
      this.emit('critical-failure', 'Backend process failed to stay running.');
      return;
    }

    this.restartAttempts++;
    this._log(`[BackendManager] Auto-restart attempt ${this.restartAttempts}/${MAX_RESTART_ATTEMPTS}...`);

    setTimeout(async () => {
      try {
        await this.start();
      } catch (err) {
        this._log(`[BackendManager] Restart failed: ${err.message}`);
        this._attemptAutoRestart();
      }
    }, 2000 * this.restartAttempts);
  }

  // ── Verification steps ────────────────────────────────────
  async verifyDatabase() {
    const data = await this._apiGet('/health');
    if (!data || data.status !== 'ok') {
      throw new Error('Database verification failed — backend health check failed');
    }
  }

  async verifyVault() {
    const dataDir = this.processManager.getDataDir();
    const vaultDir = path.join(dataDir, 'vault');
    if (!fs.existsSync(vaultDir)) {
      fs.mkdirSync(vaultDir, { recursive: true });
    }
  }

  async verifyScheduler() {
    const data = await this._apiGet('/health');
    // Scheduler is embedded in FastAPI startup; just verify backend responded
    return !!data;
  }

  async verifyModels() {
    const dataDir = this.processManager.getDataDir();
    const modelsDir = path.join(dataDir, 'models');
    if (!fs.existsSync(modelsDir)) {
      fs.mkdirSync(modelsDir, { recursive: true });
    }
  }

  async verifyDataDirs() {
    const dataDir = this.processManager.getDataDir();
    const subdirs = ['vault', 'models', 'backups', 'logs', 'research', 'predictions'];
    for (const sub of subdirs) {
      const d = path.join(dataDir, sub);
      if (!fs.existsSync(d)) {
        fs.mkdirSync(d, { recursive: true });
      }
    }
  }

  // ── Control ───────────────────────────────────────────────
  async stop() {
    if (!this.process) return;
    this._log('[BackendManager] Stopping backend...');
    this.process.kill('SIGTERM');
    await new Promise((resolve) => setTimeout(resolve, 1500));
    if (this.process && !this.process.killed) {
      this.process.kill('SIGKILL');
    }
    this.running = false;
    this.process = null;
  }

  async restart() {
    await this.stop();
    await this.start();
  }

  isRunning() {
    return this.running;
  }

  getPort() {
    return this.port;
  }

  getLogs(lines = 200) {
    return this.logs.slice(-lines).join('\n');
  }

  // ── Internal helpers ──────────────────────────────────────
  _log(msg) {
    const ts = new Date().toISOString().substring(11, 19);
    const line = `[${ts}] ${msg}`;
    this.logs.push(line);
    if (this.logs.length > this.maxLogLines) {
      this.logs = this.logs.slice(-this.maxLogLines);
    }
    console.log(line);
  }

  async _apiGet(endpoint) {
    return new Promise((resolve) => {
      http.get(`http://127.0.0.1:${this.port}${endpoint}`, (res) => {
        let body = '';
        res.on('data', (d) => { body += d; });
        res.on('end', () => {
          try { resolve(JSON.parse(body)); }
          catch (_) { resolve(null); }
        });
      }).on('error', () => resolve(null));
    });
  }

  async _findPython() {
    const os = require('os');
    const candidates = [
      // Well-known uv-managed location on Windows
      path.join(os.homedir(), '.local', 'bin', 'python3.11.exe'),
      path.join(os.homedir(), '.local', 'bin', 'python3.exe'),
      // Standard PATH lookups
      'python3.11', 'python3.12', 'python3.10', 'python3', 'python',
      // Windows launcher
      'py',
    ];
    for (const cmd of candidates) {
      try {
        await new Promise((resolve, reject) => {
          execFile(cmd, ['--version'], { timeout: 5000 }, (err) => err ? reject(err) : resolve());
        });
        this._log(`[BackendManager] Python found: ${cmd}`);
        return cmd;
      } catch (_) {}
    }
    throw new Error(
      'Python not found. Install Python 3.10+ and ensure it is in PATH, or place aqrti_backend.exe in resources/backend/.'
    );
  }
}

module.exports = { BackendManager, BACKEND_PORT };
