// The `thinking-orbs/engine` entry point: pure geometry, zero React, zero
// DOM. Import this to drive your own renderer — a Skia canvas in React
// Native, an offscreen canvas in a worker, a server-side rasteriser.
//
// The contract is deliberately small: resolve a (state, size) pair to its
// draw options once, then call the mode's frame function per instant. What
// comes back is a finished, z-sorted list of circles (and, for `connecting`,
// line segments) with every value final — draw them in order and you have
// the same picture the React component paints.
//
//   import { resolvePreset } from 'thinking-orbs/engine';
//   import { MODE_FRAMES } from 'thinking-orbs/engine';
//
//   const { mode, speed, opts } = resolvePreset('searching', 64);
//   const { dots, lines } = MODE_FRAMES[mode](64, elapsedSeconds * speed, opts);
//
// Ink convention: `white` is the paper-theme ink value in [0,1]; on a dark
// substrate a renderer mirrors it (`1 - white`) so near dots read bright.

export { MODE_FRAMES, MODE_DRAWS } from './registry';
export { resolvePreset, STATE_TO_MODE, type ModeKey, type Resolved } from '../presets';
export type { Dot, Line, OrbFrame, ModeFrame, ModeDraw } from './types';
export type { ModeOpts } from './profiles';
export type { OrbState, OrbSize } from '../types';

// Escape hatches for renderers that want the primitives themselves.
export { finalizeFrame, paintFrame, paint, paintLines, radiusScale, makeProj } from './core';
