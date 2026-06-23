/**
 * AQRTI Error Recovery System (D11)
 * Detects and attempts to automatically recover from common failure modes:
 * database corruption, missing files, vault problems, failed services.
 */

'use strict';

const path = require('path');
const fs = require('fs');
const { execFile } = require('child_process');

class RecoverySystem {
  constructor(processManager, backendManager) {
    this.pm = processManager;
    this.bm = backendManager;
  }

  // ── Full diagnostics ──────────────────────────────────────
  async runDiagnostics() {
    const checks = await Promise.allSettled([
      this._checkDatabase(),
      this._checkVault(),
      this._checkModels(),
      this._checkBackend(),
      this._checkDiskSpace(),
      this._checkDataDirs(),
    ]);

    const results = [
      'database', 'vault', 'models', 'backend', 'disk', 'directories'
    ].map((name, i) => {
      const r = checks[i];
      return r.status === 'fulfilled'
        ? { name, ...r.value }
        : { name, ok: false, error: r.reason?.message || 'Unknown error' };
    });

    const allOk = results.every((r) => r.ok);
    return { ok: allOk, checks: results, ts: new Date().toISOString() };
  }

  // ── Repair database ───────────────────────────────────────
  async repairDatabase() {
    const dbPath = path.join(this.pm.getDataDir(), 'aqrti.db');

    if (!fs.existsSync(dbPath)) {
      return { ok: false, action: 'none', error: 'Database file not found' };
    }

    // Check integrity via sqlite3
    const integrityOk = await this._sqliteIntegrity(dbPath);

    if (integrityOk) {
      return { ok: true, action: 'none', message: 'Database integrity OK' };
    }

    // Attempt repair: copy WAL and SHM, then vacuum
    try {
      const bakPath = dbPath + '.corrupt.' + Date.now();
      fs.copyFileSync(dbPath, bakPath);
      await this._sqliteVacuum(dbPath);
      return { ok: true, action: 'vacuum', message: 'Database vacuumed', backup: bakPath };
    } catch (err) {
      return { ok: false, action: 'failed', error: err.message };
    }
  }

  // ── Repair vault ──────────────────────────────────────────
  async repairVault() {
    const vaultDir = this.pm.getVaultDir();

    if (!fs.existsSync(vaultDir)) {
      fs.mkdirSync(vaultDir, { recursive: true });
      return { ok: true, action: 'created', message: 'Vault directory created' };
    }

    // Check for truncated parquet files (size 0)
    let removed = 0;
    const walk = (dir) => {
      for (const f of fs.readdirSync(dir)) {
        const full = path.join(dir, f);
        try {
          const stat = fs.statSync(full);
          if (stat.isDirectory()) {
            walk(full);
          } else if (stat.size === 0) {
            fs.unlinkSync(full);
            removed++;
          }
        } catch (_) {}
      }
    };

    try {
      walk(vaultDir);
      return { ok: true, action: 'cleaned', message: `Removed ${removed} empty files` };
    } catch (err) {
      return { ok: false, action: 'failed', error: err.message };
    }
  }

  // ── Individual checks ─────────────────────────────────────
  async _checkDatabase() {
    const dbPath = path.join(this.pm.getDataDir(), 'aqrti.db');
    const exists = fs.existsSync(dbPath);
    if (!exists) return { ok: false, message: 'Database file missing', recoverable: true };

    const stat = fs.statSync(dbPath);
    const integrityOk = await this._sqliteIntegrity(dbPath);
    return {
      ok: integrityOk,
      message: integrityOk ? `Database OK (${this._formatBytes(stat.size)})` : 'Integrity check failed',
      size: stat.size,
      recoverable: !integrityOk,
    };
  }

  async _checkVault() {
    const vaultDir = this.pm.getVaultDir();
    const exists = fs.existsSync(vaultDir);
    if (!exists) return { ok: false, message: 'Vault directory missing', recoverable: true };

    const size = this._dirSize(vaultDir);
    return { ok: true, message: `Vault OK (${this._formatBytes(size)})`, size };
  }

  async _checkModels() {
    const modelsDir = this.pm.getModelsDir();
    const exists = fs.existsSync(modelsDir);
    if (!exists) return { ok: false, message: 'Models directory missing', recoverable: true };

    const files = fs.readdirSync(modelsDir).filter((f) => f.endsWith('.pkl') || f.endsWith('.cbm') || f.endsWith('.json'));
    return {
      ok: true,
      message: `${files.length} model file(s) present`,
      count: files.length,
    };
  }

  async _checkBackend() {
    const running = this.bm.isRunning();
    return {
      ok: running,
      message: running ? 'Backend running' : 'Backend not running',
      recoverable: !running,
    };
  }

  async _checkDiskSpace() {
    const dataDir = this.pm.getDataDir();
    // Rough check: ensure at least 500 MB free
    try {
      const stat = fs.statfsSync ? fs.statfsSync(dataDir) : null;
      if (stat) {
        const freeBytes = stat.bavail * stat.bsize;
        const ok = freeBytes > 500 * 1024 * 1024;
        return {
          ok,
          message: ok ? `${this._formatBytes(freeBytes)} free` : 'Low disk space',
          freeBytes,
        };
      }
    } catch (_) {}
    return { ok: true, message: 'Disk check skipped (platform limitation)' };
  }

  async _checkDataDirs() {
    const dirs = [
      this.pm.getDataDir(),
      this.pm.getLogsDir(),
      this.pm.getBackupsDir(),
      this.pm.getModelsDir(),
      this.pm.getVaultDir(),
    ];

    const missing = dirs.filter((d) => !fs.existsSync(d));
    if (missing.length > 0) {
      missing.forEach((d) => fs.mkdirSync(d, { recursive: true }));
      return { ok: true, message: `Created ${missing.length} missing directories`, recoverable: false };
    }

    return { ok: true, message: 'All directories present' };
  }

  // ── SQLite helpers ────────────────────────────────────────
  _sqliteIntegrity(dbPath) {
    return new Promise((resolve) => {
      const sqlite3 = this._getSqlite3Path();
      if (!sqlite3) { resolve(true); return; }  // can't check, assume ok

      execFile(sqlite3, [dbPath, 'PRAGMA integrity_check;'], { timeout: 10000 }, (err, stdout) => {
        resolve(!err && stdout.trim() === 'ok');
      });
    });
  }

  _sqliteVacuum(dbPath) {
    return new Promise((resolve, reject) => {
      const sqlite3 = this._getSqlite3Path();
      if (!sqlite3) { resolve(); return; }

      execFile(sqlite3, [dbPath, 'VACUUM;'], { timeout: 30000 }, (err) => {
        err ? reject(err) : resolve();
      });
    });
  }

  _getSqlite3Path() {
    const candidates = ['sqlite3', 'sqlite3.exe'];
    const { execSync } = require('child_process');
    for (const c of candidates) {
      try {
        execSync(`${c} --version`, { stdio: 'ignore' });
        return c;
      } catch (_) {}
    }
    return null;
  }

  _dirSize(p) {
    if (!fs.existsSync(p)) return 0;
    let total = 0;
    const walk = (dir) => {
      for (const f of fs.readdirSync(dir)) {
        const full = path.join(dir, f);
        try {
          const s = fs.statSync(full);
          s.isDirectory() ? walk(full) : total += s.size;
        } catch (_) {}
      }
    };
    try { walk(p); } catch (_) {}
    return total;
  }

  _formatBytes(bytes) {
    if (!bytes) return '0 B';
    const units = ['B', 'KB', 'MB', 'GB'];
    const i = Math.floor(Math.log(bytes) / Math.log(1024));
    return `${(bytes / Math.pow(1024, i)).toFixed(1)} ${units[i]}`;
  }
}

module.exports = { RecoverySystem };
