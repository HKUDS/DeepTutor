// Lesson kit: the only building blocks a video lesson may use. DeepTutor's cream/terracotta palette,
// Lora + Geist type, and restrained motion live here, so the model composes content instead of
// inventing styling. Every component reads the frame from its enclosing <Sequence>.
import React, {createContext, useContext} from "react";
import {AbsoluteFill, Easing, Html5Audio, Sequence, Series, interpolate, useCurrentFrame} from "remotion";
import outline from "./china_outline.json";
import {VOICE} from "./voice";

export const T = {
  paper: "#fdfcf9", paper2: "#f5f2ea", ink: "#1c1816", soft: "#3b3430", muted: "#6d645a",
  rule: "#e6decc", accent: "#b0501e", blue: "#2f5d8a", green: "#3d6b4f",
  serif: "Lora, 'Noto Serif SC', 'Songti SC', 'SimSun', serif",
  sans: "Geist, 'PingFang SC', 'Microsoft YaHei', 'Noto Sans SC', sans-serif",
  mono: "'Geist Mono', ui-monospace, monospace",
};
export const W = 1920, H = 1080;
type Tone = "ink" | "soft" | "accent" | "muted" | "blue" | "green";
const tone = (t: Tone = "ink") => ({ink: T.ink, soft: T.soft, accent: T.accent, muted: T.muted, blue: T.blue, green: T.green}[t]);

const ease = Easing.bezier(0.2, 0.8, 0.2, 1);
/** 0→1 progress that starts `delay` frames into the current Sequence and lasts `dur` frames. */
export function useProgress(delay = 0, dur = 18): number {
  const f = useCurrentFrame();
  return interpolate(f, [delay, delay + Math.max(1, dur)], [0, 1],
    {extrapolateLeft: "clamp", extrapolateRight: "clamp", easing: ease});
}

// ------------------------------------------------------------------ page and text

/** Full-frame paper page. `eyebrow` is the small section label in the top-left corner. */
export const Stage: React.FC<{eyebrow?: string; page?: string; children?: React.ReactNode}> = ({eyebrow, page, children}) => (
  <AbsoluteFill style={{background: T.paper, color: T.ink, fontFamily: T.sans}}>
    {eyebrow && <div style={{position: "absolute", left: 120, top: 70, font: `500 26px ${T.sans}`, color: T.muted,
      letterSpacing: "0.06em"}}>{eyebrow}</div>}
    {page && <div style={{position: "absolute", right: 120, top: 70, font: `500 24px ${T.mono}`, color: T.muted}}>{page}</div>}
    {children}
  </AbsoluteFill>
);

/** Fades in and rises 14px; wrap any absolutely placed content in it. */
export const Reveal: React.FC<{delay?: number; dur?: number; x?: number; y?: number; w?: number;
  style?: React.CSSProperties; children?: React.ReactNode}> = ({delay = 0, dur = 16, x, y, w, style, children}) => {
  const p = useProgress(delay, dur);
  const placed: React.CSSProperties = x !== undefined || y !== undefined
    ? {position: "absolute", left: x ?? 0, top: y ?? 0, width: w} : {};
  return <div style={{...placed, ...style, opacity: p, transform: `translateY(${(1 - p) * 14}px)`}}>{children}</div>;
};

/** Serif headline with an optional small kicker above it. */
export const Title: React.FC<{kicker?: string; x?: number; y?: number; w?: number; size?: number; delay?: number;
  children?: React.ReactNode}> = ({kicker, x = 120, y = 150, w = 1500, size = 76, delay = 0, children}) => (
  <Reveal x={x} y={y} w={w} delay={delay}>
    {kicker && <div style={{font: `600 28px ${T.sans}`, color: T.accent, marginBottom: 18, letterSpacing: "0.04em"}}>{kicker}</div>}
    <div style={{font: `500 ${size}px/1.22 ${T.serif}`, color: T.ink}}>{children}</div>
  </Reveal>
);

/** Body paragraph. */
export const Body: React.FC<{x: number; y: number; w?: number; size?: number; delay?: number; color?: Tone;
  children?: React.ReactNode}> = ({x, y, w = 760, size = 36, delay = 0, color = "soft", children}) => (
  <Reveal x={x} y={y} w={w} delay={delay}>
    <div style={{font: `400 ${size}px/1.65 ${T.sans}`, color: tone(color)}}>{children}</div>
  </Reveal>
);

/** Inline emphasis inside Body/Title text. */
export const Em: React.FC<{tone?: Tone; children?: React.ReactNode}> = ({tone: t = "accent", children}) => (
  <span style={{color: tone(t), fontWeight: 600}}>{children}</span>
);

/** Inline math in serif italic; use <Frac> for fractions. */
export const Formula: React.FC<{size?: number; children?: React.ReactNode}> = ({size, children}) => (
  <span style={{fontFamily: T.serif, fontStyle: "italic", fontSize: size, whiteSpace: "nowrap"}}>{children}</span>
);
export const Frac: React.FC<{num: React.ReactNode; den: React.ReactNode}> = ({num, den}) => (
  <span style={{display: "inline-flex", flexDirection: "column", alignItems: "center", verticalAlign: "middle",
    fontSize: "0.82em", lineHeight: 1.1, margin: "0 0.15em"}}>
    <span style={{padding: "0 0.2em"}}>{num}</span>
    <span style={{borderTop: "2px solid currentColor", padding: "0 0.2em"}}>{den}</span>
  </span>
);

/** Teacher's spoken line at the bottom of the frame. `lines[i].at` is the frame (inside the Sequence) it starts. */
export const Narration: React.FC<{lines: {at: number; text: React.ReactNode}[]}> = ({lines}) => {
  const f = useCurrentFrame();
  const i = lines.reduce((k, l, j) => (f >= l.at ? j : k), -1);
  if (i < 0) return null;
  const local = f - lines[i].at;
  const p = interpolate(local, [0, 10], [0, 1], {extrapolateRight: "clamp"});
  return (
    <div style={{position: "absolute", left: 120, right: 120, bottom: 64, borderTop: `2px solid ${T.rule}`, paddingTop: 22}}>
      <div style={{font: `400 38px/1.55 ${T.sans}`, color: T.ink, opacity: p, maxWidth: 1500}}>{lines[i].text}</div>
    </div>
  );
};

/** A note card with a left rule; good for a definition, a treaty, or one key fact. */
export const Card: React.FC<{x: number; y: number; w?: number; title?: string; tone?: Tone; delay?: number;
  children?: React.ReactNode}> = ({x, y, w = 560, title, tone: t = "accent", delay = 0, children}) => (
  <Reveal x={x} y={y} w={w} delay={delay}>
    <div style={{background: "#fff", border: `1.5px solid ${T.rule}`, borderLeft: `6px solid ${tone(t)}`, borderRadius: 8,
      padding: "22px 28px"}}>
      {title && <div style={{font: `600 32px ${T.sans}`, color: T.ink, marginBottom: 8}}>{title}</div>}
      <div style={{font: `400 30px/1.6 ${T.sans}`, color: T.soft}}>{children}</div>
    </div>
  </Reveal>
);

/** A number that counts from `from` to `to`. */
export const Count: React.FC<{from: number; to: number; delay?: number; dur?: number; digits?: number;
  style?: React.CSSProperties}> = ({from, to, delay = 0, dur = 30, digits = 0, style}) => {
  const p = useProgress(delay, dur);
  return <span style={{fontVariantNumeric: "tabular-nums", ...style}}>{(from + (to - from) * p).toFixed(digits)}</span>;
};

// ------------------------------------------------------------------ hand-drawn marks

function wobble(points: [number, number][], seed: number, amp: number): string {
  let s = seed;
  const rnd = () => ((s = (s * 9301 + 49297) % 233280) / 233280 - 0.5) * amp;
  return points.map(([x, y], i) => `${i ? "L" : "M"}${(x + rnd()).toFixed(1)} ${(y + rnd()).toFixed(1)}`).join(" ");
}

/** Draws an underline, circle, or box around a frame region, as if by pen. Coordinates are frame pixels. */
export const Mark: React.FC<{x: number; y: number; w: number; h: number; kind?: "underline" | "circle" | "box";
  delay?: number; dur?: number; tone?: Tone}> = ({x, y, w, h, kind = "underline", delay = 0, dur = 16, tone: t = "accent"}) => {
  const p = useProgress(delay, dur);
  let pts: [number, number][];
  if (kind === "underline") pts = Array.from({length: 9}, (_, i) => [x + (w * i) / 8, y + h + 6 + Math.sin(i) * 2]);
  else if (kind === "box") pts = [[x - 8, y - 8], [x + w + 8, y - 6], [x + w + 6, y + h + 8], [x - 6, y + h + 6], [x - 8, y - 4]];
  else pts = Array.from({length: 34}, (_, i) => {
    const a = (i / 30) * 2 * Math.PI - 0.6;
    return [x + w / 2 + (w / 2 + 18) * Math.cos(a), y + h / 2 + (h / 2 + 14) * Math.sin(a)];
  });
  return (
    <svg width={W} height={H} style={{position: "absolute", left: 0, top: 0, pointerEvents: "none"}}>
      <path d={wobble(pts, x * 7 + y, kind === "underline" ? 2 : 4)} pathLength={1} fill="none"
        stroke={tone(t)} strokeWidth={4} strokeLinecap="round" strokeLinejoin="round"
        strokeDasharray={1} strokeDashoffset={1 - p} />
    </svg>
  );
};

/** A gently curved arrow between two frame points, drawn over `dur` frames. */
export const Arrow: React.FC<{from: [number, number]; to: [number, number]; bend?: number; delay?: number; dur?: number;
  tone?: Tone; label?: string}> = ({from, to, bend = 0.18, delay = 0, dur = 18, tone: t = "muted", label}) => {
  const p = useProgress(delay, dur);
  const [x1, y1] = from, [x2, y2] = to;
  const mx = (x1 + x2) / 2 - (y2 - y1) * bend, my = (y1 + y2) / 2 + (x2 - x1) * bend;
  const ang = Math.atan2(y2 - my, x2 - mx);
  const head = (d: number) => `${x2 - 18 * Math.cos(ang + d)},${y2 - 18 * Math.sin(ang + d)}`;
  return (
    <svg width={W} height={H} style={{position: "absolute", left: 0, top: 0, pointerEvents: "none"}}>
      <path d={`M${x1} ${y1} Q${mx} ${my} ${x2} ${y2}`} pathLength={1} fill="none" stroke={tone(t)} strokeWidth={3}
        strokeDasharray={1} strokeDashoffset={1 - p} strokeLinecap="round" />
      <polyline points={`${head(0.45)} ${x2},${y2} ${head(-0.45)}`} fill="none" stroke={tone(t)} strokeWidth={3}
        opacity={p > 0.95 ? 1 : 0} strokeLinejoin="round" />
      {label && <text x={mx} y={my - 12} textAnchor="middle" fill={T.muted} opacity={p}
        style={{font: `500 26px ${T.sans}`}}>{label}</text>}
    </svg>
  );
};

// ------------------------------------------------------------------ plots

type PlotCtx = {sx: (x: number) => number; sy: (y: number) => number; x: number; y: number; w: number; h: number;
  xDomain: [number, number]; yDomain: [number, number]};
const PlotContext = createContext<PlotCtx | null>(null);
const usePlot = () => {
  const c = useContext(PlotContext);
  if (!c) throw new Error("Curve/Dots/Cobweb/HLine/VLine/PlotLabel must be inside <Plot>");
  return c;
};

/** Axes in a frame rectangle; children draw in data coordinates. */
export const Plot: React.FC<{x: number; y: number; w: number; h: number; xDomain: [number, number];
  yDomain: [number, number]; xTicks?: number[]; yTicks?: number[]; xLabel?: string; yLabel?: string; delay?: number;
  tickFormat?: (v: number) => string; children?: React.ReactNode}> = (props) => {
  const {x, y, w, h, xDomain, yDomain, xTicks = [], yTicks = [], xLabel, yLabel, delay = 0, children} = props;
  const fmt = props.tickFormat || ((v: number) => String(v));
  const p = useProgress(delay, 20);
  const sx = (v: number) => x + ((v - xDomain[0]) / (xDomain[1] - xDomain[0])) * w;
  const sy = (v: number) => y + h - ((v - yDomain[0]) / (yDomain[1] - yDomain[0])) * h;
  return (
    <PlotContext.Provider value={{sx, sy, x, y, w, h, xDomain, yDomain}}>
      <svg width={W} height={H} style={{position: "absolute", left: 0, top: 0, overflow: "visible"}}>
        <g opacity={p}>
          {yTicks.map((v) => <g key={"y" + v}>
            <line x1={x} x2={x + w} y1={sy(v)} y2={sy(v)} stroke={T.rule} strokeWidth={1.5} />
            <text x={x - 16} y={sy(v) + 9} textAnchor="end" fill={T.muted} style={{font: `400 26px ${T.mono}`}}>{fmt(v)}</text>
          </g>)}
          {xTicks.map((v) => <text key={"x" + v} x={sx(v)} y={y + h + 42} textAnchor="middle" fill={T.muted}
            style={{font: `400 26px ${T.mono}`}}>{fmt(v)}</text>)}
          <line x1={x} x2={x + w} y1={y + h} y2={y + h} stroke={T.ink} strokeWidth={2} />
          <line x1={x} x2={x} y1={y} y2={y + h} stroke={T.ink} strokeWidth={2} />
          {xLabel && <text x={x + w} y={y + h + 84} textAnchor="end" fill={T.soft} style={{font: `500 28px ${T.sans}`}}>{xLabel}</text>}
          {yLabel && <text x={x} y={y - 24} fill={T.soft} style={{font: `500 28px ${T.sans}`}}>{yLabel}</text>}
        </g>
        {children}
      </svg>
    </PlotContext.Provider>
  );
};

/** y = fn(x), drawn left to right. */
export const Curve: React.FC<{fn: (x: number) => number; domain?: [number, number]; delay?: number; dur?: number;
  tone?: Tone; width?: number; dashed?: boolean; label?: string; labelAt?: number}> = (props) => {
  const c = usePlot();
  const {fn, delay = 0, dur = 36, tone: t = "ink", width = 4, dashed, label} = props;
  const [a, b] = props.domain || c.xDomain;
  const p = useProgress(delay, dur);
  const pts: string[] = [];
  for (let i = 0; i <= 160; i++) {
    const xv = a + ((b - a) * i) / 160, yv = fn(xv);
    if (Number.isFinite(yv) && yv >= c.yDomain[0] - 1e-9 && yv <= c.yDomain[1] + 1e-9) pts.push(`${c.sx(xv).toFixed(1)},${c.sy(yv).toFixed(1)}`);
  }
  const lx = props.labelAt ?? b;
  return <g>
    <polyline points={pts.join(" ")} pathLength={1} fill="none" stroke={tone(t)} strokeWidth={width}
      strokeDasharray={dashed ? undefined : 1} strokeDashoffset={dashed ? undefined : 1 - p}
      opacity={dashed ? p : 1} strokeLinejoin="round" style={dashed ? {strokeDasharray: "10 8"} : undefined} />
    {label && <text x={c.sx(lx) + 12} y={c.sy(fn(lx)) - 14} fill={tone(t)} opacity={p}
      style={{font: `italic 500 30px ${T.serif}`}}>{label}</text>}
  </g>;
};

/** Points that appear one by one, `every` frames apart, optionally joined and labelled. */
export const Dots: React.FC<{data: [number, number][]; delay?: number; every?: number; tone?: Tone; join?: boolean;
  labels?: (string | null)[]; r?: number}> = ({data, delay = 0, every = 10, tone: t = "accent", join, labels, r = 8}) => {
  const c = usePlot();
  const f = useCurrentFrame();
  const shown = data.filter((_, i) => f >= delay + i * every);
  return <g>
    {join && shown.length > 1 && <polyline points={shown.map(([a, b]) => `${c.sx(a)},${c.sy(b)}`).join(" ")}
      fill="none" stroke={tone(t)} strokeWidth={2.5} opacity={0.55} />}
    {shown.map(([a, b], i) => {
      const k = interpolate(f - (delay + i * every), [0, 8], [0, 1], {extrapolateRight: "clamp"});
      return <g key={i} opacity={k}>
        <circle cx={c.sx(a)} cy={c.sy(b)} r={r * (0.6 + 0.4 * k)} fill={tone(t)} />
        {labels && labels[i] && <text x={c.sx(a)} y={c.sy(b) - 20} textAnchor="middle" fill={T.soft}
          style={{font: `500 24px ${T.mono}`}}>{labels[i]}</text>}
      </g>;
    })}
  </g>;
};

/** Cobweb diagram for x_{n+1} = f(x_n): the staircase between y = f(x) and y = x. */
export const Cobweb: React.FC<{f: (x: number) => number; x0: number; steps: number; delay?: number; every?: number;
  tone?: Tone}> = ({f: fn, x0, steps, delay = 0, every = 14, tone: t = "accent"}) => {
  const c = usePlot();
  const frame = useCurrentFrame();
  const segs: [number, number, number, number][] = [];
  let xv = x0;
  segs.push([xv, c.yDomain[0], xv, fn(xv)]);
  for (let i = 0; i < steps; i++) {
    const yv = fn(xv);
    segs.push([xv, yv, yv, yv]);
    segs.push([yv, yv, yv, fn(yv)]);
    xv = yv;
  }
  return <g>{segs.map(([a, b, cc, d], i) => {
    const k = interpolate(frame - (delay + i * every), [0, every * 0.8], [0, 1],
      {extrapolateLeft: "clamp", extrapolateRight: "clamp"});
    if (k <= 0) return null;
    return <line key={i} x1={c.sx(a)} y1={c.sy(b)} x2={c.sx(a + (cc - a) * k)} y2={c.sy(b + (d - b) * k)}
      stroke={tone(t)} strokeWidth={3} opacity={i === 0 ? 0.6 : 1} strokeDasharray={i === 0 ? "6 6" : undefined} />;
  })}</g>;
};

/** Horizontal / vertical reference line with a label at its end. */
export const HLine: React.FC<{y: number; label?: string; delay?: number; tone?: Tone}> = ({y, label, delay = 0, tone: t = "blue"}) => {
  const c = usePlot();
  const p = useProgress(delay, 18);
  return <g opacity={p}>
    <line x1={c.x} x2={c.x + c.w} y1={c.sy(y)} y2={c.sy(y)} stroke={tone(t)} strokeWidth={2.5} strokeDasharray="10 8" />
    {label && <text x={c.x + c.w - 6} y={c.sy(y) - 14} textAnchor="end" fill={tone(t)} style={{font: `500 28px ${T.sans}`}}>{label}</text>}
  </g>;
};
export const VLine: React.FC<{x: number; label?: string; delay?: number; tone?: Tone}> = ({x, label, delay = 0, tone: t = "blue"}) => {
  const c = usePlot();
  const p = useProgress(delay, 18);
  return <g opacity={p}>
    <line x1={c.sx(x)} x2={c.sx(x)} y1={c.y} y2={c.y + c.h} stroke={tone(t)} strokeWidth={2.5} strokeDasharray="10 8" />
    {label && <text x={c.sx(x) + 10} y={c.y + 30} fill={tone(t)} style={{font: `500 28px ${T.sans}`}}>{label}</text>}
  </g>;
};
/** Text at a data coordinate. */
export const PlotLabel: React.FC<{x: number; y: number; text: string; delay?: number; tone?: Tone; anchor?: "start" | "middle" | "end"}> =
  ({x, y, text, delay = 0, tone: t = "soft", anchor = "start"}) => {
    const c = usePlot();
    const p = useProgress(delay, 14);
    return <text x={c.sx(x)} y={c.sy(y)} textAnchor={anchor} opacity={p} fill={tone(t)}
      style={{font: `500 28px ${T.sans}`}}>{text}</text>;
  };

// ------------------------------------------------------------------ timeline

/** Honest-scale timeline. Events appear one by one; labels alternate above/below the axis. */
export const Timeline: React.FC<{start: number; end: number; x?: number; y?: number; w?: number;
  events: {year: number; label: string; tone?: Tone}[]; eras?: {from: number; to: number; label: string}[];
  delay?: number; every?: number; focus?: number}> = (props) => {
  const {start, end, x = 140, y = 560, w = 1640, events, eras = [], delay = 0, every = 12, focus} = props;
  const f = useCurrentFrame();
  const p = useProgress(delay, 24);
  const sx = (v: number) => x + ((v - start) / (end - start)) * w;
  const step = (end - start) > 60 ? 10 : 5;
  const ticks: number[] = [];
  for (let v = Math.ceil(start / step) * step; v <= end; v += step) ticks.push(v);
  return (
    <svg width={W} height={H} style={{position: "absolute", left: 0, top: 0, overflow: "visible"}}>
      {eras.map((e, i) => <g key={"e" + i} opacity={p}>
        <rect x={sx(e.from)} y={y - 250} width={sx(e.to) - sx(e.from)} height={8} rx={4}
          fill={i % 2 ? T.muted : T.accent} opacity={0.35} />
        <text x={sx(e.from)} y={y - 266} fill={T.muted} style={{font: `500 24px ${T.sans}`}}>{e.label}</text>
      </g>)}
      <line x1={x} x2={x + w * p} y1={y} y2={y} stroke={T.ink} strokeWidth={2.5} />
      {ticks.map((v) => <g key={v} opacity={p}>
        <line x1={sx(v)} x2={sx(v)} y1={y} y2={y + 12} stroke={T.muted} strokeWidth={2} />
        <text x={sx(v)} y={y + 46} textAnchor="middle" fill={T.muted} style={{font: `400 24px ${T.mono}`}}>{v}</text>
      </g>)}
      {events.map((e, i) => {
        const k = interpolate(f - (delay + 20 + i * every), [0, 12], [0, 1], {extrapolateLeft: "clamp", extrapolateRight: "clamp"});
        if (k <= 0) return null;
        const up = i % 2 === 0, lift = up ? -(70 + (i % 4 === 0 ? 0 : 60)) : 90 + (i % 4 === 1 ? 0 : 60);
        const hot = focus === e.year || e.tone === "accent";
        const col = hot ? T.accent : tone(e.tone || "ink");
        return <g key={i} opacity={focus !== undefined && !hot ? 0.45 * k : k}>
          <line x1={sx(e.year)} x2={sx(e.year)} y1={y} y2={y + (lift + (up ? 12 : -30)) * k} stroke={col} strokeWidth={1.5} />
          <circle cx={sx(e.year)} cy={y} r={hot ? 10 : 7} fill={col} />
          <text x={sx(e.year)} y={y + lift - (up ? 34 : -8)} textAnchor="middle" fill={col}
            style={{font: `500 24px ${T.mono}`}}>{e.year}</text>
          <text x={sx(e.year)} y={y + lift + (up ? -2 : 40)} textAnchor="middle" fill={hot ? T.accent : T.ink}
            style={{font: `${hot ? 600 : 500} 28px ${T.sans}`}}>{e.label}</text>
        </g>;
      })}
    </svg>
  );
};

// ------------------------------------------------------------------ map

/** Place names the map understands, as [longitude, latitude]. */
export const PLACES: Record<string, [number, number]> = {
  北京: [116.4, 39.9], 天津: [117.2, 39.13], 上海: [121.47, 31.23], 南京: [118.8, 32.06], 广州: [113.26, 23.13],
  香港: [114.17, 22.3], 澳门: [113.54, 22.19], 武昌: [114.31, 30.55], 武汉: [114.31, 30.59], 长沙: [112.94, 28.23],
  南昌: [115.86, 28.68], 瑞金: [116.03, 25.89], 井冈山: [114.17, 26.57], 遵义: [106.93, 27.73], 延安: [109.49, 36.59],
  重庆: [106.55, 29.56], 西安: [108.94, 34.34], 沈阳: [123.43, 41.8], 旅顺: [121.26, 38.81], 大连: [121.61, 38.91],
  威海: [122.12, 37.51], 青岛: [120.38, 36.07], 台北: [121.56, 25.04], 台湾: [120.96, 23.7], 福州: [119.3, 26.08],
  厦门: [118.09, 24.48], 宁波: [121.55, 29.87], 杭州: [120.16, 30.27], 金田: [110.08, 23.39], 桂林: [110.29, 25.27],
  成都: [104.07, 30.57], 昆明: [102.83, 24.88], 贵阳: [106.63, 26.65], 济南: [117.0, 36.65], 太原: [112.55, 37.87],
  哈尔滨: [126.63, 45.75], 长春: [125.32, 43.82], 西柏坡: [114.0, 38.35], 卢沟桥: [116.21, 39.85], 徐州: [117.28, 34.2],
  锦州: [121.13, 41.1], 拉萨: [91.13, 29.65], 乌鲁木齐: [87.62, 43.83], 兰州: [103.83, 36.06], 海口: [110.35, 20.02],
  汕头: [116.68, 23.35], 大渡河: [102.25, 29.25], 赤水: [105.7, 28.58], 吴淞口: [121.5, 31.4], 虎门: [113.67, 22.8],
};
type Where = string | [number, number];

/** China outline with places and routes. `places`/`routes` take names from PLACES or [lon, lat]. */
export const ChinaMap: React.FC<{x?: number; y?: number; h?: number; delay?: number;
  places?: {at: Where; label?: string; delay?: number; tone?: Tone}[];
  routes?: {via: Where[]; delay?: number; dur?: number; tone?: Tone; label?: string}[]}> = (props) => {
  const {x = 880, y = 140, h = 700, delay = 0, places = [], routes = []} = props;
  const f = useCurrentFrame();
  const p = useProgress(delay, 24);
  const [lo0, lo1, la0, la1] = [73, 135.5, 17.5, 54];
  const kx = Math.cos((36 * Math.PI) / 180);
  const s = h / (la1 - la0);
  const pr = ([lon, lat]: [number, number]): [number, number] => [x + (lon - lo0) * kx * s, y + (la1 - lat) * s];
  const at = (w: Where): [number, number] => {
    const ll = typeof w === "string" ? PLACES[w] : w;
    if (!ll) throw new Error(`ChinaMap: unknown place "${w}" (use a PLACES name or [lon, lat])`);
    return pr(ll);
  };
  void lo1;
  return (
    <svg width={W} height={H} style={{position: "absolute", left: 0, top: 0, overflow: "visible"}}>
      <g opacity={p}>
        {(outline as number[][][]).map((ring, i) => <polygon key={i} points={ring.map((ll) => pr(ll as [number, number]).join(",")).join(" ")}
          fill={T.paper2} stroke={T.muted} strokeWidth={2} strokeLinejoin="round" />)}
      </g>
      {routes.map((r, i) => {
        const pts = r.via.map(at);
        const k = interpolate(f, [(r.delay ?? delay + 20), (r.delay ?? delay + 20) + (r.dur ?? 40)], [0, 1],
          {extrapolateLeft: "clamp", extrapolateRight: "clamp", easing: ease});
        if (k <= 0) return null;
        const d = pts.map(([a, b], j) => `${j ? "L" : "M"}${a} ${b}`).join(" ");
        const [lx, ly] = pts[Math.floor(pts.length / 2)];
        return <g key={"r" + i}>
          <path d={d} pathLength={1} fill="none" stroke={tone(r.tone || "accent")} strokeWidth={4}
            strokeDasharray={1} strokeDashoffset={1 - k} strokeLinecap="round" strokeLinejoin="round" />
          {r.label && <text x={lx + 14} y={ly - 14} fill={tone(r.tone || "accent")} opacity={k}
            style={{font: `500 26px ${T.sans}`}}>{r.label}</text>}
        </g>;
      })}
      {places.map((pl, i) => {
        const k = interpolate(f, [(pl.delay ?? delay + 20 + i * 8), (pl.delay ?? delay + 20 + i * 8) + 12], [0, 1],
          {extrapolateLeft: "clamp", extrapolateRight: "clamp"});
        if (k <= 0) return null;
        const [a, b] = at(pl.at);
        const col = tone(pl.tone || "ink");
        return <g key={"p" + i} opacity={k}>
          <circle cx={a} cy={b} r={8 + 8 * (1 - k)} fill={col} />
          <text x={a + 16} y={b + 9} fill={col} style={{font: `600 28px ${T.sans}`}}>{pl.label ?? (typeof pl.at === "string" ? pl.at : "")}</text>
        </g>;
      })}
    </svg>
  );
};

// ------------------------------------------------------------------ narrated scenes

/** One scene: `voice` names its narration in the json block, `frames` is the planned length. */
export type Scene = {voice: string; frames: number; content: React.ReactNode};
type Clip = {text: string; frames: number; src?: string; captions: {at: number; text: string}[]};
const LEAD = 10; // frames of picture before the voice starts

const clip = (id: string): Clip => {
  const c = (VOICE as Record<string, Clip>)[id];
  if (!c) throw new Error(`scene voice "${id}" has no narration entry in the json block`);
  return c;
};
// A scene lasts as long as planned, or longer when its narration needs the time.
const sceneLength = (s: Scene) => Math.max(s.frames, LEAD + clip(s.voice).frames + 20);

/** Total length of a lesson built from `scenes`; use it for LESSON.durationInFrames. */
export const lessonLength = (scenes: Scene[]) => scenes.reduce((n, s) => n + sceneLength(s), 0);

/** Plays the scenes back to back, each with its voice-over and captions timed to the voice. */
export const Scenes: React.FC<{scenes: Scene[]}> = ({scenes}) => (
  <Series>
    {scenes.map((s, i) => {
      const c = clip(s.voice);
      return (
        <Series.Sequence key={i} durationInFrames={sceneLength(s)}>
          {s.content}
          {c.src ? <Sequence from={LEAD} layout="none"><Html5Audio src={c.src} /></Sequence> : null}
          <Narration lines={c.captions.map((l) => ({at: LEAD + l.at, text: l.text}))} />
        </Series.Sequence>
      );
    })}
  </Series>
);
