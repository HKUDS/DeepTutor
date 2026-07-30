"use client";

import { Languages } from "lucide-react";

import type { Lang } from "@/lib/settings-nav";

type LanguageSwitcherProps = {
  language: "en" | "zh";
  onChange: (language: "en" | "zh") => void;
  tr: (label: Lang) => string;
};

const LANGUAGE_OPTIONS = [
  { value: "en", label: "English", lang: "en" },
  { value: "zh", label: "简体中文", lang: "zh-CN" },
] as const;

export function LanguageSwitcher({
  language,
  onChange,
  tr,
}: LanguageSwitcherProps) {
  return (
    <div
      className="inline-flex min-w-0 items-center gap-1 rounded-lg border border-[var(--border)]/60 bg-[var(--muted)]/40 p-1"
      role="group"
      aria-label={tr({ zh: "界面语言", en: "Interface language" })}
    >
      <span className="hidden items-center gap-1.5 px-1.5 text-[12px] font-medium text-[var(--muted-foreground)] lg:inline-flex">
        <Languages size={13} aria-hidden="true" />
        {tr({ zh: "语言", en: "Language" })}
      </span>
      {LANGUAGE_OPTIONS.map((option) => {
        const selected = language === option.value;
        return (
          <button
            key={option.value}
            type="button"
            lang={option.lang}
            aria-pressed={selected}
            onClick={() => onChange(option.value)}
            className={`rounded-md px-2.5 py-1 text-[12px] transition-colors ${
              selected
                ? "bg-[var(--card)] font-medium text-[var(--foreground)] shadow-sm"
                : "text-[var(--muted-foreground)] hover:text-[var(--foreground)]"
            }`}
          >
            {option.label}
          </button>
        );
      })}
    </div>
  );
}
