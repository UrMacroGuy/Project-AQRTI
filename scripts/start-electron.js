const { spawn } = require('child_process');
const path = require('path');

const electronPath = require('../node_modules/electron');
const projectRoot = path.join(__dirname, '..');

const env = Object.assign({}, process.env);
delete env.ELECTRON_RUN_AS_NODE;

const child = spawn(electronPath, ['--disable-gpu', '--disable-software-rasterizer', '--no-sandbox', projectRoot], {
  stdio: 'inherit',
  env: env,
  cwd: projectRoot,
  windowsHide: false
});

child.on('close', (code, signal) => {
  if (code === null) {
    process.exit(1);
  }
  process.exit(code);
});
