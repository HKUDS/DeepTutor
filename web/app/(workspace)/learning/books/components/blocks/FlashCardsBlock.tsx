"use client";

import { useState } from "react";
import { ChevronLeft, ChevronRight, RotateCcw } from "lucide-react";
import { useTranslation } from "react-i18next";
import type { Block } from "@/lib/book-types";

interface Card {
  front?: string;
  back?: string;
  hint?: string;
}

export interface FlashCardsBlockProps {
  block: Block;
}

export default function FlashCardsBlock({ block }: FlashCardsBlockProps) {
  const { t } = useTranslation();
  const cards = (block.payload?.cards as Card[] | undefined) || [];
  const [idx, setIdx] = useState(0);
  const [showBack, setShowBack] = useState(false);
  if (cards.length === 0) return null;
  const card = cards[Math.min(idx, cards.length - 1)] || {};

  return (
    <div className="rounded-2xl border border-[var(--border)] bg-[var(--card)] p-4 shadow-sm">
      <div className="flex items-center justify-between">
        <span className="text-[11px] font-semibold uppercase tracking-[0.16em] text-[var(--primary)]">
          {t("Flash Cards")}
        </span>
        <span className="text-xs text-[var(--muted-foreground)]">
          {idx + 1} / {cards.length}
        </span>
      </div>
      <button
        onClick={() => setShowBack((v) => !v)}
        className="mt-3 flex h-40 w-full flex-col items-center justify-center gap-2 rounded-xl border border-[var(--border)] bg-[var(--background)] px-6 text-center transition hover:border-[var(--primary)]/40"
      >
        <span className="text-[10px] uppercase tracking-wider text-[var(--muted-foreground)]">
          {showBack ? t("Answer") : t("Question")}
        </span>
        <span className="text-base font-medium text-[var(--foreground)]">
          {showBack ? card.back : card.front}
        </span>
        {!showBack && card.hint && (
          <span className="text-xs italic text-[var(--muted-foreground)]">
            {t("Hint")}: {card.hint}
          </span>
        )}
      </button>
      <div className="mt-3 flex items-center justify-between">
        <button
          onClick={() => {
            setShowBack(false);
            setIdx((i) => Math.max(0, i - 1));
          }}
          disabled={idx === 0}
          className="inline-flex items-center gap-1 rounded-md border border-[var(--border)] px-2 py-1 text-xs disabled:opacity-30"
        >
          <ChevronLeft className="h-3.5 w-3.5" /> {t("Prev")}
        </button>
        <button
          onClick={() => setShowBack((v) => !v)}
          className="inline-flex items-center gap-1 rounded-md border border-[var(--border)] px-2 py-1 text-xs hover:border-[var(--primary)]/40 hover:text-[var(--primary)]"
        >
          <RotateCcw className="h-3.5 w-3.5" /> {t("Flip")}
        </button>
        <button
          onClick={() => {
            setShowBack(false);
            setIdx((i) => Math.min(cards.length - 1, i + 1));
          }}
          disabled={idx >= cards.length - 1}
          className="inline-flex items-center gap-1 rounded-md border border-[var(--border)] px-2 py-1 text-xs disabled:opacity-30"
        >
          {t("Next")} <ChevronRight className="h-3.5 w-3.5" />
        </button>
      </div>
    </div>
  );
}
