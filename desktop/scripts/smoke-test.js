#!/usr/bin/env node
/**
 * Runs the Electron smoke test in an isolated profile so it never disturbs the
 * real app config:
 *
 *   npm run smoke                     # default ports 8101/3882
 *   npm run smoke -- --frontend-port=3999
 *
 * Exit code 0 means: window created, UI rendered, preload bridge answered an
 * IPC round-trip, and no 5xx/console errors during boot.
 */

const { spawn } = require('node:child_process');
const fs = require('node:fs');
const path = require('node:path');

const electronPath = require('electron');
const root = path.resolve(__dirname, '..');
const artifacts = path.join(root, 'artifacts');
fs.mkdirSync(artifacts, { recursive: true });

const passthrough = process.argv.slice(2).filter((arg) => arg.startsWith('--'));
const has = (flag) => passthrough.some((arg) => arg === flag || arg.startsWith(`${flag}=`));

const args = [
  root,
  '--smoke',
  `--smoke-out=${path.join(artifacts, 'smoke-report.json')}`,
  `--user-data=${path.join(artifacts, 'userdata')}`,
  '--no-tray',
  '--disable-gpu',
];

if (!has('--backend-port')) args.push('--backend-port=8001');
if (!has('--frontend-port')) args.push('--frontend-port=3882');
// Reuse an already-running backend by default; only the UI is started fresh so
// the test exercises the packaged frontend bundle without fighting the user's
// live DeepTutor instance for the default ports.

args.push(...passthrough);

const child = spawn(electronPath, args, {
  cwd: root,
  env: {
    ...process.env,
    ELECTRON_ENABLE_LOGGING: '1',
    // Some CI/host shells export this to run Electron as plain Node; that would
    // give us a Node process instead of a browser window.
    ELECTRON_RUN_AS_NODE: undefined,
  },
  stdio: 'inherit',
});

child.on('exit', (code, signal) => {
  const reportPath = path.join(artifacts, 'smoke-report.json');
  if (fs.existsSync(reportPath)) {
    const report = JSON.parse(fs.readFileSync(reportPath, 'utf8'));
    process.stdout.write(`\n[smoke] ok=${report.ok} duration=${report.durationMs}ms\n`);
    if (report.checks) {
      for (const [name, value] of Object.entries(report.checks)) {
        process.stdout.write(`[smoke]   ${value ? 'PASS' : 'FAIL'}  ${name}\n`);
      }
    }
    if (report.error) process.stdout.write(`[smoke] error: ${report.error}\n`);
  }
  process.exit(code ?? (signal ? 1 : 0));
});
