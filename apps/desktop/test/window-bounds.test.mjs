import assert from 'node:assert/strict';
import { test } from 'node:test';
import { minWindowSize, restoreWindowBounds } from '../src/window-bounds.mjs';

test('restores a window on the display that held most of it', () => {
  const saved = { x: 1350, y: 100, width: 850, height: 600 };
  const primary = { workArea: { x: 0, y: 0, width: 1500, height: 800 } };
  const secondary = { workArea: { x: 1500, y: 0, width: 900, height: 700 } };
  const expected = { x: 1500, y: 100, width: 850, height: 600 };

  assert.deepEqual(restoreWindowBounds(saved, [primary, secondary]), expected);
  assert.deepEqual(restoreWindowBounds(saved, [secondary, primary]), expected);
});

test('fits a high-DPI work area smaller than the normal window minimum', () => {
  const workArea = { x: 0, y: 0, width: 420, height: 320 };
  const saved = { x: 10, y: 10, width: 1050, height: 720 };

  assert.deepEqual(minWindowSize(workArea), { minWidth: 420, minHeight: 320 });
  assert.deepEqual(restoreWindowBounds(saved, [{ workArea }]), workArea);
});

test('lets the caller pick default bounds when the saved title bar is offscreen', () => {
  const saved = { x: -2000, y: 200, width: 950, height: 640 };
  const display = { workArea: { x: 0, y: 0, width: 1500, height: 800 } };

  assert.equal(restoreWindowBounds(saved, [display]), null);
});
