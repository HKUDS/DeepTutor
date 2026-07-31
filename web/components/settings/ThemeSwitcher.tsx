"use client";

import { Moon, Sun } from "lucide-react";

import type { Lang } from "@/lib/settings-nav";
import type { Theme } from "@/lib/theme";

type ThemeSwitcherProps = {
  theme: Theme;
  onChange: (theme: Theme) => void;
  tr: (label: Lang) => string;
};

const THEME_OPTIONS = [
  {
    value: "snow",
    label: { zh: "浅色", en: "Light" },
    icon: Sun,
  },
  {
    value: "dark",
    label: { zh: "深色", en: "Dark" },
    icon: Moon,
  },
] as const;

export function ThemeSwitcher({
  theme,
  onChange,
  tr,
}: ThemeSwitcherProps) {
  const selectedMode =
    theme === "dark" || theme === "glass" ? "dark" : "snow";

  return (
    <div
      className="inline-flex min-w-0 items-center gap-1 rounded-lg border border-[var(--border)]/60 bg-[var(--muted)]/40 p-1"
      role="group"
      aria-label={tr({ zh: "界面皮肤", en: "Interface theme" })}
    >
      {THEME_OPTIONS.map((option) => {
        const Icon = option.icon;
        const selected = selectedMode === option.value;
        return (
          <button
            key={option.value}
            type="button"
            aria-pressed={selected}
            onClick={() => onChange(option.value)}
            className={`inline-flex items-center gap-1 rounded-md px-2.5 py-1 text-[12px] transition-colors ${
              selected
                ? "bg-[var(--card)] font-medium text-[var(--foreground)] shadow-sm"
                : "text-[var(--muted-foreground)] hover:text-[var(--foreground)]"
            }`}
          >
            <Icon size={12} aria-hidden="true" />
            {tr(option.label)}
          </button>
        );
      })}
    </div>
  );
}
