"use client";

import {
  Lightbulb,
  AlertTriangle,
  BookmarkCheck,
  Sparkles,
} from "lucide-react";
import type { Block } from "@/lib/book-types";

const VARIANT_STYLES: Record<
  string,
  { icon: typeof Lightbulb; rule: string; tint: string; accent: string }
> = {
  key_idea: {
    icon: Lightbulb,
    rule: "border-amber-400/70 dark:border-amber-300/60",
    tint: "bg-amber-50/60 text-amber-950 dark:bg-amber-500/[0.06] dark:text-amber-100",
    accent: "text-amber-700 dark:text-amber-300",
  },
  common_pitfall: {
    icon: AlertTriangle,
    rule: "border-rose-400/70 dark:border-rose-300/60",
    tint: "bg-rose-50/60 text-rose-950 dark:bg-rose-500/[0.06] dark:text-rose-100",
    accent: "text-rose-700 dark:text-rose-300",
  },
  summary: {
    icon: BookmarkCheck,
    rule: "border-sky-400/70 dark:border-sky-300/60",
    tint: "bg-sky-50/60 text-sky-950 dark:bg-sky-500/[0.06] dark:text-sky-100",
    accent: "text-sky-700 dark:text-sky-300",
  },
  tip: {
    icon: Sparkles,
    rule: "border-emerald-400/70 dark:border-emerald-300/60",
    tint: "bg-emerald-50/60 text-emerald-950 dark:bg-emerald-500/[0.06] dark:text-emerald-100",
    accent: "text-emerald-700 dark:text-emerald-300",
  },
};

export interface CalloutBlockProps {
  block: Block;
}

export default function CalloutBlock({ block }: CalloutBlockProps) {
  const variant = String(block.payload?.variant || "key_idea");
  const label = String(block.payload?.label || variant.replace(/_/g, " "));
  const body = String(block.payload?.body || "");
  const style = VARIANT_STYLES[variant] || VARIANT_STYLES.key_idea;
  const Icon = style.icon;
  return (
    <aside
      className={`relative flex gap-3 border-l-[3px] ${style.rule} ${style.tint} py-2 pl-4 pr-3`}
    >
      <Icon className={`mt-[3px] h-4 w-4 shrink-0 ${style.accent}`} />
      <div className="min-w-0 space-y-1">
        <div
          className={`text-[11px] font-semibold uppercase tracking-[0.16em] ${style.accent}`}
        >
          {label}
        </div>
        <div className="text-[14.5px] leading-relaxed">{body}</div>
      </div>
    </aside>
  );
}
