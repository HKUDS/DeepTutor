"use client";

import { Sparkles } from "lucide-react";
import { useTranslation } from "react-i18next";
import type { Block } from "@/lib/book-types";

export interface PlaceholderBlockProps {
  block: Block;
}

const LABELS: Record<string, string> = {
  figure: "Figure",
  interactive: "Interactive",
  animation: "Animation",
  code: "Code Sandbox",
  timeline: "Timeline",
  flash_cards: "Flash Cards",
  deep_dive: "Deep Dive",
};

export default function PlaceholderBlock({ block }: PlaceholderBlockProps) {
  const { t } = useTranslation();
  const label = LABELS[block.type] || block.type;
  const intended = block.params?.intended_block_type
    ? String(block.params.intended_block_type)
    : block.type;
  return (
    <div className="flex items-center gap-3 rounded-2xl border border-dashed border-[var(--border)] bg-[var(--muted)]/30 px-4 py-3 text-sm text-[var(--muted-foreground)]">
      <Sparkles className="h-4 w-4 text-[var(--primary)]" />
      <div>
        <div className="font-medium text-[var(--foreground)]">{t(label)}</div>
        <div className="text-xs">
          {t(
            "Coming in Phase 2 – {{type}} block will appear here once the generator is wired.",
            { type: t(intended) },
          )}
        </div>
      </div>
    </div>
  );
}
