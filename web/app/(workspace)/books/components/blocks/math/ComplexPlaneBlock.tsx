"use client";

import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import type { MathBlockConfig } from "./mathBlockAdapter";

/**
 * YuEdu fork: 复数平面 block（纯 SVG + 滑块，零依赖）。
 * 用 config.re / config.im 作为初始值；学生拖滑块观察模与幅角。
 */
export default function ComplexPlaneBlock({
  config,
}: {
  config: MathBlockConfig;
}) {
  const { t } = useTranslation();
  const [re, setRe] = useState(config.re);
  const [im, setIm] = useState(config.im);

  const W = 320;
  const H = 280;
  const scale = 28; // px per unit
  const ox = W / 2;
  const oy = H / 2;
  const px = ox + re * scale;
  const py = oy - im * scale;

  const modulus = useMemo(() => Math.sqrt(re * re + im * im), [re, im]);
  const argDeg = useMemo(() => (Math.atan2(im, re) * 180) / Math.PI, [re, im]);

  return (
    <div className="my-4 rounded-2xl border border-[var(--border)] bg-[var(--card)] p-4 shadow-sm">
      <h3 className="mb-3 text-base font-bold text-[var(--foreground)]">
        {config.title || t("Complex plane")}
      </h3>
      <div className="grid gap-4 sm:grid-cols-2">
        <div className="rounded-lg border border-[var(--border)] bg-[var(--background)] p-2">
          <svg viewBox={`0 0 ${W} ${H}`} className="w-full">
            {Array.from({ length: 11 }).map((_, i) => (
              <line
                key={`v${i}`}
                x1={(i * W) / 10}
                y1={0}
                x2={(i * W) / 10}
                y2={H}
                stroke="var(--border)"
                strokeWidth={0.5}
              />
            ))}
            {Array.from({ length: 10 }).map((_, i) => (
              <line
                key={`h${i}`}
                x1={0}
                y1={(i * H) / 9}
                x2={W}
                y2={(i * H) / 9}
                stroke="var(--border)"
                strokeWidth={0.5}
              />
            ))}
            <line x1={0} y1={oy} x2={W} y2={oy} stroke="var(--muted-foreground)" strokeWidth={1} />
            <line x1={ox} y1={0} x2={ox} y2={H} stroke="var(--muted-foreground)" strokeWidth={1} />
            <text x={W - 12} y={oy - 6} className="fill-[var(--muted-foreground)] text-[10px]">Re</text>
            <text x={ox + 6} y={12} className="fill-[var(--muted-foreground)] text-[10px]">Im</text>
            <line x1={ox} y1={oy} x2={px} y2={py} stroke="var(--primary)" strokeWidth={2} />
            <circle cx={px} cy={py} r={5} fill="var(--primary)" />
            <text x={px + 8} y={py - 8} className="fill-[var(--foreground)] text-[11px]">
              ({re}, {im})
            </text>
          </svg>
        </div>
        <div className="space-y-3 text-sm">
          <label className="flex items-center justify-between">
            <span>{t("Real (Re)")}</span>
            <span className="tabular-nums text-[var(--primary)]">{re}</span>
          </label>
          <input
            type="range"
            min={-5}
            max={5}
            step={0.5}
            value={re}
            onChange={(e) => setRe(Number(e.target.value))}
            className="w-full accent-[var(--primary)]"
          />
          <label className="flex items-center justify-between">
            <span>{t("Imaginary (Im)")}</span>
            <span className="tabular-nums text-[var(--primary)]">{im}</span>
          </label>
          <input
            type="range"
            min={-5}
            max={5}
            step={0.5}
            value={im}
            onChange={(e) => setIm(Number(e.target.value))}
            className="w-full accent-[var(--primary)]"
          />
          <div className="rounded-md bg-[var(--background)] p-3 text-[var(--foreground)]">
            <div>
              {t("Modulus")} |z| = {modulus.toFixed(2)}
            </div>
            <div>
              {t("Argument")} arg = {argDeg.toFixed(1)}°
            </div>
            <div className="mt-1 text-xs">
              {t("Algebraic form")}: {re} {im >= 0 ? "+" : "−"} {Math.abs(im)}i
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
