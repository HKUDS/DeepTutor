"use client";

import { useTranslation } from "react-i18next";
import type { MathBlockConfig, VennSet } from "./mathBlockAdapter";

const DEFAULT_SETS: VennSet[] = [{ label: "集合 A" }, { label: "集合 B" }];

const FILL_COLORS = ["var(--primary)", "var(--accent)", "#a78bfa"];

/**
 * YuEdu fork: 维恩图 block（纯 SVG，零依赖）。
 * 用 config.sets 绘制 2~3 圆交集；为空时用默认两集合 A/B。
 */
export default function VennDiagramBlock({
  config,
}: {
  config: MathBlockConfig;
}) {
  const { t } = useTranslation();
  const sets = config.sets.length > 0 ? config.sets.slice(0, 3) : DEFAULT_SETS;
  const count = sets.length;

  // 视布局：2 圆左右排，3 圆三角排
  const R = 78;
  const circles =
    count === 3
      ? [
          { cx: 120, cy: 95, label: sets[0]?.label ?? "A" },
          { cx: 220, cy: 95, label: sets[1]?.label ?? "B" },
          { cx: 170, cy: 175, label: sets[2]?.label ?? "C" },
        ]
      : [
          { cx: 120, cy: 130, label: sets[0]?.label ?? "A" },
          { cx: 220, cy: 130, label: sets[1]?.label ?? "B" },
        ];

  const center =
    config.center ||
    (count === 3 ? "A ∩ B ∩ C" : "A ∩ B");
  const centerX = circles.reduce((a, c) => a + c.cx, 0) / circles.length;
  const centerY = count === 3 ? 145 : 130;

  return (
    <div className="my-4 rounded-2xl border border-[var(--border)] bg-[var(--card)] p-4 shadow-sm">
      <h3 className="mb-3 text-base font-bold text-[var(--foreground)]">
        {config.title || t("Venn diagram")}
      </h3>
      {config.description && (
        <p className="mb-3 text-sm text-[var(--muted-foreground)]">
          {config.description}
        </p>
      )}
      <div className="rounded-lg border border-[var(--border)] bg-[var(--background)] p-3">
        <svg viewBox="0 0 340 240" className="mx-auto h-56 w-full max-w-md">
          {circles.map((c, i) => (
            <circle
              key={`c${i}`}
              cx={c.cx}
              cy={c.cy}
              r={R}
              fill={FILL_COLORS[i % FILL_COLORS.length]}
              fillOpacity={0.22}
              stroke={FILL_COLORS[i % FILL_COLORS.length]}
              strokeWidth={2}
            />
          ))}
          {circles.map((c, i) => (
            <text
              key={`l${i}`}
              x={c.cx + (i === 0 ? -50 : 50)}
              y={count === 3 ? 60 : 60}
              textAnchor="middle"
              className="fill-[var(--foreground)] text-sm font-semibold"
            >
              {c.label}
            </text>
          ))}
          <text
            x={centerX}
            y={centerY}
            textAnchor="middle"
            className="fill-[var(--foreground)] text-xs"
          >
            {center}
          </text>
        </svg>
      </div>
      <p className="mt-3 text-sm text-[var(--muted-foreground)]">
        {config.caption ||
          t("Overlapping region is the intersection; union is all covered area.")}
      </p>
    </div>
  );
}
