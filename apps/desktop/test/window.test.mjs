import test from 'node:test';
import assert from 'node:assert/strict';
import { REPAINT_EVENTS, focusWindow, repaintOnShow } from '../src/window.mjs';

/** Record the calls Electron would make, in order. */
function fakeWindow({ minimized }) {
  const calls = [];
  return {
    calls,
    listeners: {},
    isMinimized: () => minimized,
    restore: () => calls.push('restore'),
    show: () => calls.push('show'),
    focus: () => calls.push('focus'),
    on(event, handler) { (this.listeners[event] ??= []).push(handler); },
    emit(event) { for (const handler of this.listeners[event] ?? []) handler(); },
  };
}

test('a minimized window is restored before it is shown', () => {
  const window = fakeWindow({ minimized: true });
  focusWindow(window);
  assert.deepEqual(window.calls, ['restore', 'show', 'focus']);
});

test('an already visible window is only shown and focused', () => {
  const window = fakeWindow({ minimized: false });
  focusWindow(window);
  assert.deepEqual(window.calls, ['show', 'focus']);
});

test('a second launch before the window exists does nothing', () => {
  assert.doesNotThrow(() => focusWindow(undefined));
});

test('becoming visible again lays the content view out', () => {
  const window = fakeWindow({ minimized: false });
  let layouts = 0;
  repaintOnShow(window, () => { layouts += 1; });
  // restore alone, and maximize, repaint a view that was added while hidden.
  for (const event of REPAINT_EVENTS) window.emit(event);
  assert.equal(layouts, REPAINT_EVENTS.length);
  assert.deepEqual([...REPAINT_EVENTS].sort(), ['focus', 'maximize', 'restore', 'show']);
});

test('a missing window cannot subscribe to repaint events', () => {
  assert.doesNotThrow(() => repaintOnShow(undefined, () => {}));
});
