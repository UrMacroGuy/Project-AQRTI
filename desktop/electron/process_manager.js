/**
 * AQRTI Process Manager
 * Manages data directories, background service state, and app paths.
 * All services run inside FastAPI — this manager tracks their virtual state
 * and provides directory management for the desktop environment.
 */

'use strict';

const { EventEmitter } = require('events');
const { app } = require('electron');
const path = require('path');
const fs = require('fs');
const os = require('os');

// ── Service registry ──────────────────────────────────────────
const SERVICES = [
  { id: 'scheduler',      name: 'Scheduler',         description: 'Daily pipeline at 15:30 IST' },
  { id: 'research',       name: 'Research Agents',   description: 'Autonomous research workers' },
  { id: 'learning',       name: 'Learning Engine',   description: 'Model adaptation loop' },
  { id: 'data',           name: 'Data Collection',   description: 'Market data ingestion' },
  { id: 'vault',          name: 'Historical Vault',  description: 'Long-term data store' },
  { id: 'predictions',    name: 'Prediction Engine', description: 'Daily signal generation' },
];

class ProcessManager extends EventEmitter {
  constructor() {
    super();
    this._dataDir = null;
    this._logsDir = null;
    this._serviceStatus = {};
    SERVICES.forEach((s) => {
      this._serviceStatus[s.id] = 'starting';
    });
  }

  // ── Directory resolution ──────────────────────────────────
  getDataDir() {
    if (this._dataDir) return this._dataDir;

    // Prefer user-configured path from settings store
    try {
      const store = require('./settings_store');
      const custom = store.get('dataDir');
      if (custom && fs.existsSync(custom)) {
        this._dataDir = custom;
        return this._dataDir;
      }
    } catch (_) {}

    // Default: %APPDATA%\AQRTI on Windows, ~/Library/Application Support/AQRTI on Mac
    const base = app.getPath('userData');
    this._dataDir = path.join(base, 'data');
    return this._dataDir;
  }

  getLogsDir() {
    if (this._logsDir) return this._logsDir;
    this._logsDir = path.join(this.getDataDir(), 'logs');
    return this._logsDir;
  }

  getBackupsDir() {
    return path.join(this.getDataDir(), 'backups');
  }

  getModelsDir() {
    return path.join(this.getDataDir(), 'models');
  }

  getVaultDir() {
    return path.join(this.getDataDir(), 'vault');
  }

  // ── Ensure all directories exist ─────────────────────────
  async ensureDirs() {
    const dirs = [
      this.getDataDir(),
      this.getLogsDir(),
      this.getBackupsDir(),
      this.getModelsDir(),
      this.getVaultDir(),
      path.join(this.getDataDir(), 'research'),
      path.join(this.getDataDir(), 'predictions'),
      path.join(this.getDataDir(), 'temp'),
    ];

    for (const d of dirs) {
      if (!fs.existsSync(d)) {
        fs.mkdirSync(d, { recursive: true });
      }
    }
  }

  // ── Start all background services ─────────────────────────
  // Services run inside FastAPI; here we just mark them running
  // and optionally trigger initialization via API call.
  async startAll() {
    await this.ensureDirs();

    for (const svc of SERVICES) {
      this._setStatus(svc.id, 'running');
    }

    this.emit('services-ready');
  }

  // ── Stop all services ─────────────────────────────────────
  async stopAll() {
    for (const svc of SERVICES) {
      this._setStatus(svc.id, 'stopped');
    }
  }

  // ── Restart a single service (triggers admin endpoint) ────
  async restartService(serviceId) {
    const http = require('http');
    const endpointMap = {
      scheduler:   null,
      research:    '/admin/agent-pipeline',
      learning:    '/admin/learning',
      data:        '/admin/ingest',
      vault:       null,
      predictions: '/admin/predict',
    };

    const endpoint = endpointMap[serviceId];
    if (endpoint) {
      await this._apiPost(endpoint);
    }

    this._setStatus(serviceId, 'running');
    return this.getServiceStatus();
  }

  // ── Get all service statuses ──────────────────────────────
  getServiceStatus() {
    return SERVICES.map((s) => ({
      ...s,
      status: this._serviceStatus[s.id] || 'unknown',
    }));
  }

  // ── Storage statistics ────────────────────────────────────
  async getStorageStats() {
    const dirs = {
      database:   path.join(this.getDataDir(), 'aqrti.db'),
      vault:      this.getVaultDir(),
      research:   path.join(this.getDataDir(), 'research'),
      predictions: path.join(this.getDataDir(), 'predictions'),
      backups:    this.getBackupsDir(),
      models:     this.getModelsDir(),
      logs:       this.getLogsDir(),
    };

    const stats = {};
    for (const [key, p] of Object.entries(dirs)) {
      stats[key] = {
        path: p,
        size: this._dirSize(p),
        sizeFormatted: this._formatBytes(this._dirSize(p)),
        exists: fs.existsSync(p),
      };
    }

    // Disk free space
    const total = this._getTotalDisk();
    const used = Object.values(stats).reduce((s, v) => s + v.size, 0);

    return {
      items: stats,
      totalAqrti: { size: used, formatted: this._formatBytes(used) },
      diskFree: total,
    };
  }

  // ── System info ───────────────────────────────────────────
  getSystemInfo() {
    return {
      platform: process.platform,
      arch: process.arch,
      nodeVersion: process.version,
      totalMemory: os.totalmem(),
      freeMemory: os.freemem(),
      cpus: os.cpus().length,
      hostname: os.hostname(),
      dataDir: this.getDataDir(),
    };
  }

  // ── Internal ──────────────────────────────────────────────
  _setStatus(id, status) {
    this._serviceStatus[id] = status;
    this.emit('service-status', { id, status });
  }

  _dirSize(p) {
    if (!fs.existsSync(p)) return 0;
    const stat = fs.statSync(p);
    if (stat.isFile()) return stat.size;

    let total = 0;
    try {
      const walk = (dir) => {
        for (const f of fs.readdirSync(dir)) {
          const full = path.join(dir, f);
          try {
            const s = fs.statSync(full);
            if (s.isDirectory()) walk(full);
            else total += s.size;
          } catch (_) {}
        }
      };
      walk(p);
    } catch (_) {}
    return total;
  }

  _formatBytes(bytes) {
    if (bytes === 0) return '0 B';
    const units = ['B', 'KB', 'MB', 'GB', 'TB'];
    const i = Math.floor(Math.log(bytes) / Math.log(1024));
    return `${(bytes / Math.pow(1024, i)).toFixed(1)} ${units[i]}`;
  }

  _getTotalDisk() {
    try {
      const { execSync } = require('child_process');
      if (process.platform === 'win32') {
        const out = execSync('wmic logicaldisk get size,freespace,caption').toString();
        const lines = out.split('\n').filter((l) => l.trim() && !l.includes('Caption'));
        const parts = lines[0]?.trim().split(/\s+/);
        if (parts && parts.length >= 3) {
          return { free: parseInt(parts[1]), total: parseInt(parts[2]) };
        }
      }
    } catch (_) {}
    return { free: 0, total: 0 };
  }

  async _apiPost(endpoint) {
    const http = require('http');
    return new Promise((resolve) => {
      const req = http.request({
        hostname: '127.0.0.1',
        port: 8000,
        path: endpoint,
        method: 'POST',
      }, (res) => {
        res.resume();
        resolve(res.statusCode);
      });
      req.on('error', () => resolve(null));
      req.end();
    });
  }
}

module.exports = { ProcessManager, SERVICES };
