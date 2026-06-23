/**
 * AQRTI Settings Store
 * Persistent key-value store backed by a JSON file in userData.
 * Replaces electron-store to avoid extra dependency complexity.
 */

'use strict';

const { app } = require('electron');
const path = require('path');
const fs = require('fs');

const DEFAULTS = {
  // Directories
  dataDir: null,               // null = use default userData/data
  backupDir: null,             // null = use dataDir/backups
  modelDir: null,              // null = use dataDir/models
  vaultDir: null,              // null = use dataDir/vault

  // Data retention (days)
  retainNewsdays: 90,
  retainPredictionDays: 365,
  retainLogDays: 30,
  retainBackupCount: 10,

  // Backup schedule (cron string)
  backupSchedule: '0 18 * * 1-5',   // weekdays at 18:00

  // Notifications
  notifyRegimeChange: true,
  notifyDailyBrief: true,
  notifyCriticalFailure: true,
  notifyDataSourceFailure: true,
  notifyResearchFindings: true,
  notifyPredictionReport: true,

  // Auto-update
  autoUpdate: true,
  updateChannel: 'stable',

  // UI
  windowBounds: null,
  theme: 'terminal-dark',

  // Backend
  backendPort: 8000,
  logLevel: 'INFO',
};

class SettingsStore {
  constructor() {
    this._filePath = null;
    this._data = null;
  }

  _getFilePath() {
    if (this._filePath) return this._filePath;
    this._filePath = path.join(app.getPath('userData'), 'aqrti-settings.json');
    return this._filePath;
  }

  _load() {
    if (this._data) return;
    const fp = this._getFilePath();
    try {
      if (fs.existsSync(fp)) {
        this._data = { ...DEFAULTS, ...JSON.parse(fs.readFileSync(fp, 'utf8')) };
      } else {
        this._data = { ...DEFAULTS };
      }
    } catch (_) {
      this._data = { ...DEFAULTS };
    }
  }

  _save() {
    const fp = this._getFilePath();
    const dir = path.dirname(fp);
    if (!fs.existsSync(dir)) fs.mkdirSync(dir, { recursive: true });
    fs.writeFileSync(fp, JSON.stringify(this._data, null, 2), 'utf8');
  }

  get(key) {
    this._load();
    return key ? this._data[key] : undefined;
  }

  set(key, value) {
    this._load();
    this._data[key] = value;
    this._save();
  }

  getAll() {
    this._load();
    return { ...this._data };
  }

  reset() {
    this._data = { ...DEFAULTS };
    this._save();
  }
}

// Singleton
let _store = null;

function getStore() {
  if (!_store) _store = new SettingsStore();
  return _store;
}

module.exports = getStore();
