// Test ESM dynamic import for electron
const _fs = require('fs');
const _log = (m) => {
  try { _fs.appendFileSync('C:\\Users\\praty\\boot_probe.log', '[' + new Date().toISOString() + '] ' + m + '\n'); } catch(_) {}
};

_log('START');

// Try ESM dynamic import of electron/main
import('electron/main').then(e => {
  _log('ESM import(electron/main) SUCCESS: type=' + typeof e);
  _log('keys: ' + Object.keys(e||{}).slice(0,15).join(','));
}).catch(err => {
  _log('ESM import(electron/main) FAIL: ' + err.message);
});

import('electron').then(e => {
  _log('ESM import(electron) SUCCESS: type=' + typeof e);
  _log('keys: ' + Object.keys(e||{}).slice(0,15).join(','));
}).catch(err => {
  _log('ESM import(electron) FAIL: ' + err.message);
});

setTimeout(() => {
  _log('DONE');
  process.exit(0);
}, 3000);
