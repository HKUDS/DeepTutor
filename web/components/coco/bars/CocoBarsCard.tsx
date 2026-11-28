"use client";

import { useMemo, useState } from "react";
import BarsFigure, { PALETTE } from "./BarsFigure";
import { layoutFigure } from "./layout";
import { parseBarsSpec, type BarsSpec } from "./spec";

export interface CocoBarsCardProps {
  /** Raw body of a ```coco-bars fenced block. */
  readonly raw: string;
  readonly className?: string;
}

const buttonClass =
  "rounded-lg border border-[var(--border)] px-3 py-1.5 text-sm text-[var(--foreground)] " +
  "transition-colors hover:bg-[var(--muted)] aria-disabled:cursor-not-allowed aria-disabled:opacity-40";

interface StatusCardProps {
  readonly message: string;
  readonly raw: string;
  readonly className?: string;
}

function StatusCard({ message, raw, className }: StatusCardProps) {
  return (
    <div
      role="note"
      className={`rounded-xl border border-dashed border-[var(--border)] p-3 text-sm text-[var(--muted-foreground)] ${className ?? ""}`}
    >
      <p>{message}</p>
      <details className="mt-1">
        <summary className="cursor-pointer">查看原始数据</summary>
        <pre className="mt-1 max-h-48 overflow-auto whitespace-pre-wrap text-xs">{raw}</pre>
      </details>
    </div>
  );
}

interface StepButtonProps {
  readonly label: string;
  readonly enabled: boolean;
  readonly onPress: () => void;
  readonly className?: string;
}

/** aria-disabled (not `disabled`) keeps keyboard focus on the button at the ends. */
function StepButton({ label, enabled, onPress, className }: StepButtonProps) {
  return (
    <button
      type="button"
      className={`${buttonClass} ${className ?? ""}`}
      aria-disabled={!enabled}
      onClick={() => {
        if (enabled) onPress();
      }}
    >
      {label}
    </button>
  );
}

interface StepperProps {
  readonly spec: BarsSpec;
  readonly className?: string;
}

function BarsStepper({ spec, className }: StepperProps) {
  const [step, setStep] = useState(0);
  const total = spec.steps.length;
  const current = Math.min(step, total - 1);
  const layout = useMemo(() => layoutFigure(spec, current), [spec, current]);
  const title = spec.title ?? "柱形图";
  const atEnd = current === total - 1;

  return (
    <figure
      className={`not-prose overflow-hidden rounded-xl border border-[var(--border)] bg-[var(--card)] ${className ?? ""}`}
      aria-label={title}
    >
      {spec.title && (
        <figcaption className="px-4 pt-3 text-sm font-semibold text-[var(--foreground)]">{spec.title}</figcaption>
      )}
      <div className="px-3 pt-2">
        <BarsFigure layout={layout} title={title} />
      </div>
      <div className="space-y-2 px-4 py-3">
        <p className="text-[15px] leading-relaxed text-[var(--foreground)]" aria-live="polite">
          <span className="me-2 text-xs text-[var(--muted-foreground)]">
            第 {current + 1}/{total} 步
          </span>
          {spec.steps[current].say}
        </p>
        {layout.formulas.length > 0 && (
          <ul className="space-y-0.5 font-mono text-sm" style={{ color: PALETTE.blue }} aria-label="算式">
            {layout.formulas.map((f, i) => (
              <li key={i}>{f}</li>
            ))}
          </ul>
        )}
        {total > 1 && (
          <div className="flex items-center gap-2 pt-1">
            <StepButton label="上一步" enabled={current > 0} onPress={() => setStep(current - 1)} />
            <StepButton label="下一步" enabled={!atEnd} onPress={() => setStep(current + 1)} />
            <StepButton label="全部显示" enabled={!atEnd} onPress={() => setStep(total - 1)} className="ms-auto" />
          </div>
        )}
      </div>
    </figure>
  );
}

export default function CocoBarsCard({ raw, className }: CocoBarsCardProps) {
  const parsed = useMemo(() => parseBarsSpec(raw), [raw]);
  if (!parsed.ok) {
    const message = parsed.incomplete
      ? "正在画图…（回答结束后仍显示这里，说明图的数据不完整）"
      : `柱形图暂时画不出来：${parsed.error}`;
    return <StatusCard message={message} raw={raw} className={className} />;
  }
  // New data (e.g. an edited or regenerated reply) starts again at step 1.
  return <BarsStepper key={raw} spec={parsed.spec} className={className} />;
}
