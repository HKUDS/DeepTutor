"use client";

import { useId } from "react";
import type { ArrowBox, BarBox, BlockBox, BraceBox, FigureLayout, LineBox } from "./layout";
import { VIEW } from "./layout";

/** Same palette as the douYinGZ Remotion lessons (remotion/src/l11/bars.tsx). */
export const PALETTE = {
  paper: "#FBF8F1",
  ink: "#23313F",
  blue: "#1D62AE",
  green: "#17744A",
  orange: "#A2510B",
  cell: "#C9DCEE",
  cellStroke: "#42637E",
  extra: "#5BA1E4",
  missing: "#FFF0DC",
  missingStroke: "#B26723",
  band: "#FFE993",
  muted: "#627990",
} as const;

const FONT = '"PingFang SC","Microsoft YaHei","Noto Sans CJK SC",sans-serif';

function FadeIn({ fresh }: { fresh: boolean }) {
  return fresh ? <animate attributeName="opacity" from="0" to="1" dur="0.45s" fill="freeze" /> : null;
}

function Bar({ bar, base }: { bar: BarBox; base: number }) {
  const height = base - bar.top;
  const mid = bar.x + bar.width / 2;
  return (
    <g data-testid={`bar-${bar.id}`}>
      <rect
        x={bar.x}
        y={bar.top}
        width={bar.width}
        height={height}
        rx={2}
        fill={PALETTE.cell}
        stroke={bar.focus ? PALETTE.orange : PALETTE.cellStroke}
        strokeWidth={bar.focus ? 3.5 : 1.5}
      />
      <text x={mid} y={height > 34 ? bar.top + 22 : bar.top - 8} textAnchor="middle" fontSize={17} fill={PALETTE.ink}>
        {bar.valueText}
      </text>
      <text x={mid} y={base + 24} textAnchor="middle" fontSize={17} fill={PALETTE.ink} fontWeight={600}>
        {bar.name}
      </text>
      <path
        d={`M ${bar.x} ${base + 34} v 8 H ${bar.x + bar.width} v -8`}
        fill="none"
        stroke={bar.focus ? PALETTE.orange : PALETTE.muted}
        strokeWidth={bar.focus ? 3 : 2}
      />
      <text x={mid} y={base + 64} textAnchor="middle" fontSize={16} fill={bar.focus ? PALETTE.orange : PALETTE.ink}>
        {bar.countText}
      </text>
    </g>
  );
}

function Block({ block }: { block: BlockBox }) {
  const style =
    block.kind === "extra"
      ? { fill: PALETTE.extra, stroke: PALETTE.blue, dash: undefined, text: PALETTE.blue }
      : block.kind === "missing"
        ? { fill: PALETTE.missing, stroke: PALETTE.missingStroke, dash: "6 4", text: PALETTE.orange }
        : { fill: PALETTE.band, stroke: PALETTE.orange, dash: "3 3", text: PALETTE.orange };
  const right = block.x + block.width + 8;
  const fitsRight = right + 120 < VIEW.width;
  return (
    <g data-testid={`block-${block.group}-${block.kind}`}>
      <FadeIn fresh={block.fresh} />
      <rect
        x={block.x}
        y={block.y}
        width={block.width}
        height={Math.max(block.height, 3)}
        rx={2}
        fill={style.fill}
        fillOpacity={block.kind === "band" ? 0.75 : 1}
        stroke={style.stroke}
        strokeWidth={block.fresh ? 3 : 2}
        strokeDasharray={style.dash}
      />
      {block.label && (
        <text
          x={fitsRight ? right : block.x - 8}
          y={block.y + block.height / 2 + 6}
          textAnchor={fitsRight ? "start" : "end"}
          fontSize={15}
          fill={style.text}
          fontWeight={600}
        >
          {block.label}
        </text>
      )}
    </g>
  );
}

function AverageLineView({ line }: { line: LineBox }) {
  return (
    <g data-testid="average-line">
      <FadeIn fresh={line.fresh} />
      <line
        x1={line.x1}
        x2={line.x2}
        y1={line.y}
        y2={line.y}
        stroke={PALETTE.green}
        strokeWidth={line.fresh ? 4 : 2.5}
        strokeDasharray="12 8"
      />
      <text x={line.x1 + 4} y={line.y - 7} fontSize={15} fill={PALETTE.green} fontWeight={600}>
        {line.label}
      </text>
    </g>
  );
}

function Arrow({ arrow, marker }: { arrow: ArrowBox; marker: string }) {
  return (
    <g data-testid="move-arrow">
      <FadeIn fresh={arrow.fresh} />
      <path d={arrow.path} fill="none" stroke={PALETTE.blue} strokeWidth={2.5} markerEnd={`url(#${marker})`} />
      {arrow.label && (
        <text x={arrow.labelX} y={arrow.labelY} textAnchor="middle" fontSize={15} fill={PALETTE.blue} fontWeight={600}>
          {arrow.label}
        </text>
      )}
    </g>
  );
}

function Brace({ brace }: { brace: BraceBox }) {
  return (
    <g data-testid="brace">
      <FadeIn fresh={brace.fresh} />
      <path
        d={`M ${brace.x1} ${brace.y + 8} v -8 H ${brace.x2} v 8`}
        fill="none"
        stroke={PALETTE.muted}
        strokeWidth={2}
      />
      <text x={(brace.x1 + brace.x2) / 2} y={brace.y - 6} textAnchor="middle" fontSize={15} fill={PALETTE.ink}>
        {brace.label}
      </text>
    </g>
  );
}

export interface BarsFigureProps {
  readonly layout: FigureLayout;
  readonly title: string;
}

export default function BarsFigure({ layout, title }: BarsFigureProps) {
  const marker = `coco-arrow-${useId().replace(/:/g, "")}`;
  return (
    <svg
      viewBox={`0 0 ${VIEW.width} ${VIEW.height}`}
      role="img"
      aria-label={title}
      style={{ width: "100%", height: "auto", background: PALETTE.paper, borderRadius: 12, fontFamily: FONT }}
    >
      <defs>
        <marker id={marker} viewBox="0 0 10 10" refX="8" refY="5" markerWidth="7" markerHeight="7" orient="auto">
          <path d="M 0 0 L 10 5 L 0 10 z" fill={PALETTE.blue} />
        </marker>
      </defs>
      <line x1={24} x2={VIEW.width - 16} y1={layout.base} y2={layout.base} stroke={PALETTE.ink} strokeWidth={3} />
      {layout.truncated && (
        <path
          data-testid="axis-break"
          d={`M 14 ${layout.base + 8} l 10 -16 M 22 ${layout.base + 8} l 10 -16`}
          stroke={PALETTE.ink}
          strokeWidth={2}
        />
      )}
      {layout.bars.map((bar) => (
        <Bar key={bar.id} bar={bar} base={layout.base} />
      ))}
      {layout.blocks.map((block, i) => (
        <Block key={`b${i}`} block={block} />
      ))}
      {layout.lines.map((line, i) => (
        <AverageLineView key={`l${i}`} line={line} />
      ))}
      {layout.braces.map((brace, i) => (
        <Brace key={`r${i}`} brace={brace} />
      ))}
      {layout.arrows.map((arrow, i) => (
        <Arrow key={`a${i}`} arrow={arrow} marker={marker} />
      ))}
    </svg>
  );
}
