// Engine-level contracts shared by every mode implementation.

import type { ModeOpts } from './profiles';

export type { Dot, Line, OrbFrame, Tint } from './core';

import type { OrbFrame, Tint } from './core';

/**
 * Geometry for one instant: pure math over (size, t, opts), no rendering
 * surface and no theme — `dark` only affects ink at paint time.
 *
 * Deliberately closure-free and `Math`-only so the same function can run
 * inside a Reanimated worklet on the React Native UI thread, and so its
 * output can be compared numerically against the Swift port.
 */
export type ModeFrame = (size: number, t: number, opts: ModeOpts) => OrbFrame;

/**
 * One frame painter: draws a mode into a 2D context at CSS-px `size`.
 *
 * `tint` is a DeepTutor local addition — optional, so every existing caller
 * keeps upstream's greyscale ink.
 */
export type ModeDraw = (
  ctx: CanvasRenderingContext2D,
  size: number,
  t: number,
  dark: boolean,
  opts: ModeOpts,
  tint?: Tint
) => void;
