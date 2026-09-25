"use client";

import {
  ALargeSmall,
  Columns2,
  Minus,
  Plus,
  RotateCcw,
  Rows3,
  SunMoon,
  type LucideIcon,
} from "lucide-react";
import { useTranslation } from "react-i18next";

import {
  DEFAULT_READER_DISPLAY_PREFERENCES,
  MAX_FONT_SIZE,
  MIN_FONT_SIZE,
  MIN_LINE_WIDTH,
  type ReaderDisplayPreferences,
} from "@/lib/reading-display-preferences";

const LINE_WIDTH_STEPS = [48, 64, 84, 104];

export function PreferenceButton({
  label,
  icon: Icon,
  active = false,
  disabled = false,
  onClick,
}: {
  label: string;
  icon: LucideIcon;
  active?: boolean;
  disabled?: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      title={label}
      aria-label={label}
      aria-pressed={active}
      disabled={disabled}
      onClick={onClick}
      className={`inline-flex h-7 w-7 items-center justify-center rounded-lg text-inherit transition hover:bg-[color-mix(in_srgb,currentColor_10%,transparent)] disabled:opacity-35 disabled:hover:bg-transparent ${
        active ? "opacity-100" : "opacity-70 hover:opacity-100"
      }`}
    >
      <Icon size={15} />
    </button>
  );
}

/** The text and native EPUB readers share one display preference contract. */
export function ReaderDisplayControls({
  preferences,
  onChange,
  showSpread = false,
}: {
  preferences: ReaderDisplayPreferences;
  onChange: (next: Partial<ReaderDisplayPreferences>) => void;
  showSpread?: boolean;
}) {
  const { t } = useTranslation();
  const { fontSize, lineWidth, serif, readerTheme, spreadMode } = preferences;

  return (
    <div className="flex shrink-0 items-center gap-0.5">
      <PreferenceButton
        label={t("Smaller text ({{percent}}%)", {
          percent: Math.round((fontSize / 16) * 100),
        })}
        icon={Minus}
        disabled={fontSize <= MIN_FONT_SIZE}
        onClick={() => onChange({ fontSize: Math.max(MIN_FONT_SIZE, fontSize - 1) })}
      />
      <PreferenceButton
        label={t("Larger text ({{percent}}%)", {
          percent: Math.round((fontSize / 16) * 100),
        })}
        icon={Plus}
        disabled={fontSize >= MAX_FONT_SIZE}
        onClick={() => onChange({ fontSize: Math.min(MAX_FONT_SIZE, fontSize + 1) })}
      />
      <PreferenceButton
        label={serif ? t("Use sans-serif font") : t("Use serif font")}
        icon={ALargeSmall}
        active={!serif}
        onClick={() => onChange({ serif: !serif })}
      />
      <PreferenceButton
        label={t("Change line width ({{width}} characters)", { width: lineWidth })}
        icon={Rows3}
        onClick={() =>
          onChange({
            lineWidth:
              LINE_WIDTH_STEPS.find((width) => width > lineWidth) ??
              MIN_LINE_WIDTH,
          })
        }
      />
      <PreferenceButton
        label={t("Change reading theme")}
        icon={SunMoon}
        active={readerTheme !== "auto"}
        onClick={() =>
          onChange({
            readerTheme:
              readerTheme === "auto"
                ? "sepia"
                : readerTheme === "sepia"
                  ? "night"
                  : "auto",
          })
        }
      />
      {showSpread && (
        <PreferenceButton
          label={
            spreadMode === "none"
              ? t("Switch to two-page spread")
              : t("Switch to single-page view")
          }
          icon={Columns2}
          active={spreadMode === "auto"}
          onClick={() =>
            onChange({ spreadMode: spreadMode === "none" ? "auto" : "none" })
          }
        />
      )}
      <PreferenceButton
        label={t("Reset reading display")}
        icon={RotateCcw}
        onClick={() => onChange(DEFAULT_READER_DISPLAY_PREFERENCES)}
      />
    </div>
  );
}
