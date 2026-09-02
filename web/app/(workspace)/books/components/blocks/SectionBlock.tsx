"use client";

import { Sparkles } from "lucide-react";
import { useTranslation } from "react-i18next";
import MarkdownRenderer from "@/components/common/MarkdownRenderer";
import type { Block } from "@/lib/book-types";

export interface SectionBlockProps {
  block: Block;
}

interface Subsection {
  heading?: string;
  role?: string;
  focus?: string;
  body?: string;
  target_words?: number;
}

export default function SectionBlock({ block }: SectionBlockProps) {
  const { t } = useTranslation();
  const payload = block.payload || {};
  const intro = String(payload.intro ?? "").trim();
  const keyTakeaway = String(payload.key_takeaway ?? "").trim();
  const focus = String(payload.focus ?? "").trim();
  const rawSubs = Array.isArray(payload.subsections) ? payload.subsections : [];
  const subsections: Subsection[] = rawSubs as Subsection[];

  return (
    <section className="text-[var(--foreground)]">
      {intro && (
        <div className="mb-5 text-[1.02em] leading-relaxed">
          <MarkdownRenderer content={intro} variant="prose" />
        </div>
      )}

      {focus && (
        <div className="mb-4 text-[11px] uppercase tracking-wider text-[var(--muted-foreground)]">
          {t("Section focus")} · {focus}
        </div>
      )}

      <div className="space-y-6">
        {subsections.map((sub, idx) => {
          const body = (sub.body || "").trim();
          if (!body) return null;
          return (
            <div key={idx} className="leading-relaxed">
              <MarkdownRenderer content={body} variant="prose" />
            </div>
          );
        })}
      </div>

      {keyTakeaway && (
        <div className="mt-6 flex items-start gap-2 rounded-xl border border-[var(--border)] bg-[var(--muted)]/30 px-3 py-2 text-sm">
          <Sparkles className="mt-0.5 h-4 w-4 flex-shrink-0 text-[var(--muted-foreground)]" />
          <div className="flex-1">
            <span className="mr-1 font-medium">{t("Key takeaway:")}</span>
            <span className="text-[var(--foreground)]">{keyTakeaway}</span>
          </div>
        </div>
      )}
    </section>
  );
}
