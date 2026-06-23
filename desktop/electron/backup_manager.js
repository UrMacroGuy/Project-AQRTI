/**
 * AQRTI Backup Manager (D6)
 * Handles manual backups, scheduled backups, verification, and restore.
 */

'use strict';

const path = require('path');
const fs = require('fs');
const { createGzip } = require('zlib');
const { pipeline } = require('stream');
const { promisify } = require('util');
const crypto = require('crypto');

const pipe = promisify(pipeline);

class BackupManager {
  constructor(processManager) {
    this.pm = processManager;
  }

  // ── Create backup ─────────────────────────────────────────
  async create(options = {}) {
    const { label = 'manual', compress = true } = options;
    const dataDir = this.pm.getDataDir();
    const backupsDir = this.pm.getBackupsDir();

    if (!fs.existsSync(backupsDir)) {
      fs.mkdirSync(backupsDir, { recursive: true });
    }

    const ts = new Date().toISOString().replace(/[:.]/g, '-').substring(0, 19);
    const name = `aqrti-backup-${label}-${ts}`;
    const targetDir = path.join(backupsDir, name);

    fs.mkdirSync(targetDir, { recursive: true });

    // Items to back up
    const items = [
      { src: path.join(dataDir, 'aqrti.db'), dst: path.join(targetDir, 'aqrti.db') },
      { src: path.join(dataDir, 'vault'),    dst: path.join(targetDir, 'vault') },
      { src: path.join(dataDir, 'models'),   dst: path.join(targetDir, 'models') },
    ];

    const copied = [];
    for (const { src, dst } of items) {
      if (fs.existsSync(src)) {
        this._copyRecursive(src, dst);
        copied.push(path.basename(src));
      }
    }

    // Generate manifest
    const manifest = {
      id: name,
      label,
      createdAt: new Date().toISOString(),
      items: copied,
      checksum: this._checksumDir(targetDir),
    };
    fs.writeFileSync(
      path.join(targetDir, 'manifest.json'),
      JSON.stringify(manifest, null, 2),
      'utf8'
    );

    // Compress if requested
    if (compress) {
      // Simple: rename folder to .tar marker (actual tar requires external tool)
      // For cross-platform safety we keep it as a directory backup
    }

    // Enforce retention limit
    await this._enforceRetention();

    return { ok: true, id: name, items: copied };
  }

  // ── List backups ──────────────────────────────────────────
  list() {
    const backupsDir = this.pm.getBackupsDir();
    if (!fs.existsSync(backupsDir)) return [];

    const entries = fs.readdirSync(backupsDir);
    const backups = [];

    for (const entry of entries) {
      const manifestPath = path.join(backupsDir, entry, 'manifest.json');
      if (fs.existsSync(manifestPath)) {
        try {
          const manifest = JSON.parse(fs.readFileSync(manifestPath, 'utf8'));
          const size = this._dirSize(path.join(backupsDir, entry));
          backups.push({ ...manifest, size, sizeFormatted: this._formatBytes(size) });
        } catch (_) {}
      }
    }

    return backups.sort((a, b) => new Date(b.createdAt) - new Date(a.createdAt));
  }

  // ── Verify backup integrity ───────────────────────────────
  verify(backupId) {
    const backupsDir = this.pm.getBackupsDir();
    const targetDir = path.join(backupsDir, backupId);
    const manifestPath = path.join(targetDir, 'manifest.json');

    if (!fs.existsSync(manifestPath)) {
      return { ok: false, error: 'Manifest not found' };
    }

    const manifest = JSON.parse(fs.readFileSync(manifestPath, 'utf8'));
    const currentChecksum = this._checksumDir(targetDir);

    const matches = currentChecksum === manifest.checksum;
    return { ok: matches, stored: manifest.checksum, current: currentChecksum };
  }

  // ── Restore backup ────────────────────────────────────────
  async restore(backupId) {
    const backupsDir = this.pm.getBackupsDir();
    const dataDir = this.pm.getDataDir();
    const backupDir = path.join(backupsDir, backupId);

    if (!fs.existsSync(backupDir)) {
      return { ok: false, error: 'Backup not found' };
    }

    const verification = this.verify(backupId);
    if (!verification.ok) {
      return { ok: false, error: 'Backup integrity check failed — not restoring.' };
    }

    // Create a safety backup of current state first
    await this.create({ label: 'pre-restore' });

    const items = [
      { src: path.join(backupDir, 'aqrti.db'), dst: path.join(dataDir, 'aqrti.db') },
      { src: path.join(backupDir, 'vault'),    dst: path.join(dataDir, 'vault') },
      { src: path.join(backupDir, 'models'),   dst: path.join(dataDir, 'models') },
    ];

    for (const { src, dst } of items) {
      if (fs.existsSync(src)) {
        this._copyRecursive(src, dst);
      }
    }

    return { ok: true, restoredFrom: backupId };
  }

  // ── Delete backup ─────────────────────────────────────────
  delete(backupId) {
    const backupsDir = this.pm.getBackupsDir();
    const targetDir = path.join(backupsDir, backupId);
    if (fs.existsSync(targetDir)) {
      fs.rmSync(targetDir, { recursive: true, force: true });
      return { ok: true };
    }
    return { ok: false, error: 'Not found' };
  }

  // ── Internal helpers ──────────────────────────────────────
  _copyRecursive(src, dst) {
    const stat = fs.statSync(src);
    if (stat.isDirectory()) {
      if (!fs.existsSync(dst)) fs.mkdirSync(dst, { recursive: true });
      for (const f of fs.readdirSync(src)) {
        this._copyRecursive(path.join(src, f), path.join(dst, f));
      }
    } else {
      fs.copyFileSync(src, dst);
    }
  }

  _checksumDir(dir) {
    const hash = crypto.createHash('sha256');
    const walk = (d) => {
      if (!fs.existsSync(d)) return;
      const stat = fs.statSync(d);
      if (stat.isFile()) {
        hash.update(fs.readFileSync(d));
      } else if (stat.isDirectory()) {
        for (const f of fs.readdirSync(d).sort()) {
          if (f === 'manifest.json') continue;
          walk(path.join(d, f));
        }
      }
    };
    walk(dir);
    return hash.digest('hex').substring(0, 16);
  }

  async _enforceRetention() {
    const store = require('./settings_store');
    const maxCount = store.get('retainBackupCount') || 10;
    const backups = this.list();
    if (backups.length > maxCount) {
      const toDelete = backups.slice(maxCount);
      for (const b of toDelete) {
        this.delete(b.id);
      }
    }
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
            s.isDirectory() ? walk(full) : total += s.size;
          } catch (_) {}
        }
      };
      walk(p);
    } catch (_) {}
    return total;
  }

  _formatBytes(bytes) {
    if (!bytes) return '0 B';
    const units = ['B', 'KB', 'MB', 'GB'];
    const i = Math.floor(Math.log(bytes) / Math.log(1024));
    return `${(bytes / Math.pow(1024, i)).toFixed(1)} ${units[i]}`;
  }
}

module.exports = { BackupManager };
