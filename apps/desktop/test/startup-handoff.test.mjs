import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';
import { runInNewContext } from 'node:vm';

const renderer = readFileSync(new URL('../src/renderer.js', import.meta.url), 'utf8');

// Run the shipped private-shell renderer against status events from its preload.
function openShell() {
  const root = { dataset: {} };
  const elements = new Map();
  function element(id) {
    if (!elements.has(id)) elements.set(id, {
      hidden: id === 'slow-hint', classList: { add() {}, remove() {} },
      style: { setProperty() {} }, setAttribute() {}, addEventListener() {},
    });
    return elements.get(id);
  }
  let send;
  let slowTimer;
  const initial = { phase: 'starting', language: 'zh', theme: 'dark', step: 'opening' };
  runInNewContext(renderer, {
    document: { documentElement: root, getElementById: element },
    window: { desktop: { platform: 'win32', onStatus(fn) { send = fn; },
      initialStatus: () => initial, status: async () => initial } },
    requestAnimationFrame: fn => fn(),
    setTimeout(fn, ms) { if (ms === 15000) slowTimer = fn; return fn; },
    clearTimeout(id) { if (id === slowTimer) slowTimer = undefined; },
  });
  return { root, element, send, fireSlowTimer() { slowTimer?.(); } };
}

test('localizes the first frame and keeps startup visible until the web view is visible', () => {
  const shell = openShell();
  assert.equal(shell.root.lang, 'zh');
  assert.equal(shell.root.dataset.theme, 'dark');
  shell.send({ phase: 'ready', contentVisible: false });
  assert.equal(shell.root.dataset.content, 'hidden');
  shell.send({ phase: 'ready', contentVisible: true });
  assert.equal(shell.root.dataset.content, 'visible');
  shell.send({ phase: 'error', detail: 'load failed' });
  assert.equal(shell.root.dataset.content, 'hidden');
  assert.equal(shell.element('problem').hidden, false);
  assert.equal(shell.element('problem-detail').textContent, 'load failed');
});

test('shows logs for a slow start and clears the hint on handoff', () => {
  const shell = openShell();
  shell.fireSlowTimer();
  assert.equal(shell.element('slow-hint').hidden, false);
  shell.send({ phase: 'ready', contentVisible: true });
  assert.equal(shell.element('slow-hint').hidden, true);
});
