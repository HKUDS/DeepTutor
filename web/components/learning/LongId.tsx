"use client";

import { useState } from "react";
import { ChevronDown, ChevronUp } from "lucide-react";
import type { TrFn } from "./locale";

/**
 * Long model / profile / snapshot identifier display (§13.3).
 *
 * Truncates the value with CSS and reveals the full value through a native
 * ``title`` tooltip plus an expandable toggle. The workspace never renders
 * API keys / auth headers / private base URLs here — only audit-safe
 * identifiers and fingerprints, so the component deliberately does no
 * redaction of its own (it should not need any).
 */
export function LongId({
  value,
  label,
  maxChars = 18,
  tr,
}: {
  value: string;
  label?: string;
  maxChars?: number;
  tr?: TrFn;
}) {
  const [open, setOpen] = useState(false);
  const needsExpand = value.length > maxChars;
  const shown = open || !needsExpand ? value : value.slice(0, maxChars);
  const expandLabel = tr ? tr("展开完整值", "Show full value") : "Show full value";
  const collapseLabel = tr ? tr("收起", "Collapse") : "Collapse";

  return (
    <span className="fw-long-id" data-testid="long-id">
      {label ? <span className="opacity-80">{label}</span> : null}
      <code
        className="fw-long-id-full min-w-0 font-mono text-[11px] leading-relaxed"
        title={value}
      >
        {shown}
        {needsExpand && !open ? "…" : ""}
      </code>
      {needsExpand ? (
        <button
          type="button"
          className="fw-icon-button h-6 w-6 text-[var(--fw-muted)]"
          aria-expanded={open}
          aria-label={open ? collapseLabel : expandLabel}
          title={open ? collapseLabel : expandLabel}
          onClick={() => setOpen((v) => !v)}
        >
          {open ? (
            <ChevronUp className="h-3.5 w-3.5" />
          ) : (
            <ChevronDown className="h-3.5 w-3.5" />
          )}
        </button>
      ) : null}
    </span>
  );
}
