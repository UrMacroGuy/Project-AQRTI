const fs = require('fs');
const lines = [];
lines.push('type=' + process.type);
lines.push('versions=' + JSON.stringify(process.versions));

// Try all known Electron binding methods
try { const b = process._linkedBinding('electron_browser_app'); lines.push('_linkedBinding(electron_browser_app)=' + JSON.stringify(Object.keys(b))); } catch(e) { lines.push('_linkedBinding(electron_browser_app) FAIL: ' + e.message); }
try { const b = process._linkedBinding('electron_common_application'); lines.push('_linkedBinding(electron_common_application)=' + JSON.stringify(Object.keys(b))); } catch(e) { lines.push('_linkedBinding fail: ' + e.message); }
try { const b = process.binding('electron_common_asar'); lines.push('process.binding(electron_common_asar) keys=' + Object.keys(b)); } catch(e) { lines.push('process.binding fail: ' + e.message); }

// Check process._linkedBinding keys
try { lines.push('typeof process._linkedBinding=' + typeof process._linkedBinding); } catch(e) {}

// Check what's available at module load time
lines.push('Module cache keys with electron: ' + Object.keys(require.cache).filter(k => k.includes('electron')).join(', '));

fs.writeFileSync('C:\\Users\\praty\\aqrti-probe.log', lines.join('\n'));
setTimeout(() => process.exit(0), 1000);
