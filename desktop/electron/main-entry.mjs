// ESM entry point for Electron 31+
// Imports electron APIs via ESM (which works in browser_init context)
// then patches the CJS module system so main.js can require('electron')

import * as electronMain from 'electron/main';
import * as electronCommon from 'electron/common';
import { createRequire } from 'module';
import { fileURLToPath } from 'url';
import { dirname, join } from 'path';

// Patch CJS Module._cache and _resolveFilename so that
// require('electron') from main.js returns the real API
const require = createRequire(import.meta.url);
const Module = require('module');

// Build the combined electron API object
const electronAPI = { ...electronCommon, ...electronMain };

// Create a fake module entry in the cache
const fakeElectronModule = new Module('electron', null);
fakeElectronModule.id = 'electron';
fakeElectronModule.loaded = true;
fakeElectronModule.filename = 'electron';
fakeElectronModule.exports = electronAPI;
Module._cache['electron'] = fakeElectronModule;

// Patch _resolveFilename to return 'electron' for all electron requires
const origResolveFilename = Module._resolveFilename;
const electronIds = new Set(['electron', 'electron/main', 'electron/renderer', 'electron/common']);
Module._resolveFilename = function(request, parent, isMain, options) {
  if (electronIds.has(request)) return 'electron';
  return origResolveFilename.call(this, request, parent, isMain, options);
};

// Now load main.js via CJS require — it will find 'electron' in the cache
const __dirname = dirname(fileURLToPath(import.meta.url));
require(join(__dirname, 'main.js'));
