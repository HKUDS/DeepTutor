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
    <div className="rounded-2xl bg-[rgb(var(--dt-ink,55_53_47)/0.028)] p-4">
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
        className="mt-3 flex h-40 w-full flex-col items-center justify-center gap-2 rounded-xl bg-[var(--background)] px-6 text-center shadow-[var(--dt-shadow-xs,0_0_0_1px_rgba(0,0,0,.06))] transition hover:shadow-[var(--dt-shadow-sm,0_1px_3px_rgba(0,0,0,.1))]"
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
          className="inline-flex items-center gap-1 rounded-md bg-[rgb(var(--dt-ink,55_53_47)/0.05)] px-2 py-1 transition-colors hover:bg-[rgb(var(--dt-ink,55_53_47)/0.085)] text-xs disabled:opacity-30"
        >
          <ChevronLeft className="h-3.5 w-3.5" /> {t("Prev")}
        </button>
        <button
          onClick={() => setShowBack((v) => !v)}
          className="inline-flex items-center gap-1 rounded-md bg-[rgb(var(--dt-ink,55_53_47)/0.05)] px-2 py-1 transition-colors hover:bg-[rgb(var(--dt-ink,55_53_47)/0.085)] text-xs hover:text-[var(--primary)]"
        >
          <RotateCcw className="h-3.5 w-3.5" /> {t("Flip")}
        </button>
        <button
          onClick={() => {
            setShowBack(false);
            setIdx((i) => Math.min(cards.length - 1, i + 1));
          }}
          disabled={idx >= cards.length - 1}
          className="inline-flex items-center gap-1 rounded-md bg-[rgb(var(--dt-ink,55_53_47)/0.05)] px-2 py-1 transition-colors hover:bg-[rgb(var(--dt-ink,55_53_47)/0.085)] text-xs disabled:opacity-30"
        >
          {t("Next")} <ChevronRight className="h-3.5 w-3.5" />
        </button>
      </div>
    </div>
  );
}
