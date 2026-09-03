// Shared primitives for the dotted 3D thought-orbs. Ported from inkform
// (PlotterLab's HalftoneSphere lineage): honestly 3D — rotated,
// depth-shaded, z-sorted. Depth is carried by dot size and ink weight
// alone. Plain 2D canvas fills only: no ctx.filter, no SVG filters, so
// every mode renders identically in Chrome, Safari and Firefox.

export interface Dot {
  x: number;
  y: number;
  z: number;
  r: number;
  /** Ink value: 0 = darkest ink on paper. Mirrored on dark themes. */
  white: number;
  a?: number;
}

/** A stroked edge between two projected points (the `connecting` web). */
export interface Line {
  x1: number;
  y1: number;
  x2: number;
  y2: number;
  /** Ink value, same convention as `Dot.white`. */
  white: number;
  a?: number;
  w: number;
}

/**
 * One rendered instant: a complete, final set of draw instructions.
 * `dots` is already z-sorted into draw order and radius-clamped; `lines`
 * are drawn first. Nothing here needs further interpretation, which is what
 * makes a frame portable to any 2D renderer.
 */
export interface OrbFrame {
  dots: Dot[];
  lines: Line[];
}

export type Projector = (x: number, y: number, z: number) => [number, number, number];

export function lerp(a: number, b: number, f: number): number {
  return a + (b - a) * f;
}

export function frac(x: number): number {
  return x - Math.floor(x);
}

/** Value noise on a 2D lattice — smooth, deterministic, cheap. */
export function vnoise(x: number, y: number): number {
  const xi = Math.floor(x);
  const yi = Math.floor(y);
  let fx = x - xi;
  let fy = y - yi;
  fx = fx * fx * (3 - 2 * fx);
  fy = fy * fy * (3 - 2 * fy);
  const a = hashD(xi, yi);
  const b = hashD(xi + 1, yi);
  const c = hashD(xi, yi + 1);
  const d = hashD(xi + 1, yi + 1);
  return a + (b - a) * fx + (c - a) * fy + (a - b - c + d) * fx * fy;
}

/** Deterministic hash in [0, 1). */
export function hashD(a: number, b: number): number {
  const h = Math.sin(a * 12.9898 + b * 78.233) * 43758.5453;
  return h - Math.floor(h);
}

/** Stable directions on a unit sphere (Fibonacci lattice). */
export function fibDir(i: number, n: number): [number, number, number] {
  const golden = Math.PI * (3 - Math.sqrt(5));
  const y = 1 - (2 * (i + 0.5)) / n;
  const rad = Math.sqrt(1 - y * y);
  const a = i * golden;
  return [rad * Math.cos(a), y, rad * Math.sin(a)];
}

/** Shortest signed angular distance, wrapped to (-π, π]. */
export function angleDelta(a: number, b: number): number {
  return Math.atan2(Math.sin(a - b), Math.cos(a - b));
}

/** Shared spin + tilt + orthographic projection. */
export function makeProj(yaw: number, tilt: number, cx: number, cy: number, scale: number): Projector {
  const st = Math.sin(tilt);
  const ct = Math.cos(tilt);
  const sy = Math.sin(yaw);
  const cyw = Math.cos(yaw);
  return (x, y, z) => {
    const x1 = x * cyw + z * sy;
    const z1 = -x * sy + z * cyw;
    const y1 = y * ct - z1 * st;
    const z2 = y * st + z1 * ct;
    return [cx + x1 * scale, cy - y1 * scale, z2];
  };
}

/**
 * DeepTutor local change: the ink a frame is painted in.
 *
 * Upstream paints pure greyscale, which would drop the brand colour the
 * status header has always carried. A tint replaces the grey ramp with the
 * same ramp run along a hue — see `inkStyle`.
 */
export interface Tint {
  r: number;
  g: number;
  b: number;
}

/**
 * Resolve one mark's fill/stroke colour.
 *
 * `white` is a depth term, not a colour: 0 is full-strength ink and 1 has
 * faded into the substrate. Untinted, that ramp runs grey (mirrored on dark
 * grounds so near marks read bright). Tinted, it runs from the tint toward
 * the substrate — black on dark, white on light — so depth still reads
 * exactly as before, just in colour.
 */
/**
 * How much of the depth ramp a tinted mark actually spends.
 *
 * DeepTutor local change. Upstream runs `white` the whole way to 1, so the
 * farthest dots land exactly on the paper colour. That is right for a 64px
 * orb carrying hundreds of dots — the ones that vanish read as depth. At
 * inline size there are only 30-120 dots in an 18px mark, and the same ramp
 * leaves the whole orb washed out beside the type.
 *
 * This scales the ramp rather than clipping it. A ceiling was tried first and
 * did nothing measurable: the modes used inline never emit `white` near 1
 * anyway — the strongest dot in `ring` measured around 0.32 — so any ceiling
 * above that is never reached. Scaling compresses the whole gradient toward
 * the ink, darkening every dot while keeping their relative depth intact.
 */
const TINT_FADE_SCALE = 0.45;

function inkStyle(white: number, alpha: number, dark: boolean, tint?: Tint): string {
  if (!tint) {
    const g = Math.round((dark ? 1 - white : white) * 255);
    return `rgba(${g},${g},${g},${alpha})`;
  }
  const fade = white * TINT_FADE_SCALE;
  const substrate = dark ? 0 : 255;
  const r = Math.round(tint.r + (substrate - tint.r) * fade);
  const g = Math.round(tint.g + (substrate - tint.g) * fade);
  const b = Math.round(tint.b + (substrate - tint.b) * fade);
  return `rgba(${r},${g},${b},${alpha})`;
}

/**
 * Painter: z-sort far→near, matte dots. On dark substrates the ink value is
 * mirrored (1 - white) so near dots read bright — the same depth language on
 * an inverted substrate.
 */
export function paint(
  ctx: CanvasRenderingContext2D,
  dots: Dot[],
  dark: boolean,
  rMin = 0.3,
  tint?: Tint
): void {
  for (const d of dots) {
    const alpha = d.a ?? 1;
    const w = Math.min(1, Math.max(0, d.white));
    ctx.fillStyle = inkStyle(w, alpha, dark, tint);
    ctx.beginPath();
    ctx.arc(d.x, d.y, d.r, 0, Math.PI * 2);
    ctx.fill();
  }
}

/** Stroke pass for edge-based modes. Runs before `paint` so nodes sit on top. */
export function paintLines(
  ctx: CanvasRenderingContext2D,
  lines: Line[],
  dark: boolean,
  tint?: Tint
): void {
  for (const l of lines) {
    const alpha = l.a ?? 1;
    const w = Math.min(1, Math.max(0, l.white));
    ctx.strokeStyle = inkStyle(w, alpha, dark, tint);
    ctx.lineWidth = l.w;
    ctx.beginPath();
    ctx.moveTo(l.x1, l.y1);
    ctx.lineTo(l.x2, l.y2);
    ctx.stroke();
  }
}

/**
 * Turn raw mode output into a finished frame: drop invisible marks, clamp
 * radii to the mode's floor, and z-sort far→near into draw order.
 *
 * This runs in the GEOMETRY step, not the painter, so a frame is a complete
 * set of draw instructions: every value is final and the array order is the
 * order to draw in. That is what lets the RN and SwiftUI ports share this
 * output verbatim — a port draws the list, it never re-derives anything —
 * and what lets the golden-vector tests compare numbers instead of pixels.
 */
export function finalizeFrame(dots: Dot[], lines: Line[], rMin = 0.3): OrbFrame {
  const visible: Dot[] = [];
  for (const d of dots) {
    if ((d.a ?? 1) < 0.02) continue;
    d.r = Math.max(rMin, d.r);
    visible.push(d);
  }
  visible.sort((a, b) => a.z - b.z);
  return { dots: visible, lines: lines.filter((l) => (l.a ?? 1) >= 0.02) };
}

/** Paint a finished frame. Lines first, so nodes sit on top of their edges. */
export function paintFrame(
  ctx: CanvasRenderingContext2D,
  frame: OrbFrame,
  dark: boolean,
  tint?: Tint
): void {
  if (frame.lines.length) paintLines(ctx, frame.lines, dark, tint);
  paint(ctx, frame.dots, dark, 0.3, tint);
}

/**
 * Dot radii were tuned for a 300pt frame; sub-linear scaling keeps small
 * spinners legible. Lower pow = radii shrink less with size.
 */
export function radiusScale(size: number, pow: number): number {
  return (size / 300) ** pow;
}
