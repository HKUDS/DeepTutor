import assert from 'node:assert/strict';
import { EventEmitter } from 'node:events';
import { test } from 'node:test';
import { createContentZoom } from '../src/content-zoom.mjs';

class Contents extends EventEmitter {
  factor = 1;
  dead = false;
  getZoomFactor() { return this.factor; }
  setZoomFactor(value) { assert.ok(!this.dead); this.factor = value; }
  isDestroyed() { return this.dead; }
  setZoomMode() {}
}

test('a content zoom step survives reload and a new controller without altering the shell', () => {
  let saved;
  const controller = createContentZoom(undefined, factor => { saved = factor; });
  const page = new Contents();
  controller.attach(page);
  page.emit('did-finish-load');
  controller.step(1);
  assert.equal(page.factor, 1.1);
  assert.equal(saved, 1.1);
  page.factor = 1;
  page.emit('did-finish-load');
  assert.equal(page.factor, 1.1);
  const restarted = createContentZoom(saved, factor => { saved = factor; });
  const next = new Contents();
  restarted.attach(next);
  next.emit('did-finish-load');
  assert.equal(next.factor, 1.1);
  restarted.reset();
  assert.equal(next.factor, 1);
  assert.equal(saved, 1);
});

test('ignores unready or destroyed content, and clamps user input to supported stops', () => {
  const controller = createContentZoom('bad', () => {});
  controller.step(1);
  const page = new Contents();
  controller.attach(page);
  controller.step(1);
  assert.equal(page.factor, 1);
  page.emit('did-finish-load');
  for (let i = 0; i < 15; i++) page.emit('zoom-changed', {}, 'in');
  assert.equal(page.factor, 1.75);
  for (let i = 0; i < 15; i++) controller.step(-1);
  assert.equal(page.factor, 0.75);
  page.dead = true;
  controller.reset();
  assert.equal(controller.factor, 0.75);
});
