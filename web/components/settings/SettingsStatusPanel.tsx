"use client";

import { useTranslation } from "react-i18next";

import MemoryUsageItem from "@/components/settings/MemoryUsageItem";
import { useSettings } from "@/features/settings/store/SettingsStore";
import { statusDotClass } from "@/components/settings/shared";
import { RuntimeHealthCard, useRuntimeStatus } from "@/features/runtime-status";

/**
 * Resident status module on the settings hub — the old `/settings#status` page
 * demoted to an always-visible strip.
 *
 * Scope is deliberately narrow: is the backend up, and what is it costing.
 * The LLM / embedding / search items that used to sit here restated what the
 * Models and Chat pages already own, so the strip now carries only the two
 * runtime facts no settings page shows.
 *
 * Compact, left-aligned, hairline-separated items — no stretched grid or
 * uppercase eyebrow (CJK reads badly with letter-spacing).
 */
export default function SettingsStatusPanel() {
  const { t } = useTranslation();
  const { status } = useSettings();
  const runtime = useRuntimeStatus();

  const online = status?.backend.status === "online";

  return (
    <section
      data-tour="tour-status"
      className="flex flex-wrap items-center gap-x-5 gap-y-2.5 border-y border-[var(--border)]/60 py-2.5"
    >
      <div className="flex items-center gap-2.5">
        <span
          className={`h-2 w-2 shrink-0 rounded-full ${statusDotClass(online, false)}`}
        />
        <div className="flex items-baseline gap-2">
          <span className="text-[13px] font-medium leading-none tracking-tight text-[var(--foreground)]">
            {t("Backend")}
          </span>
          <span className="text-[12px] leading-none text-[var(--muted-foreground)]">
            {online ? t("Online") : t("Checking")}
          </span>
        </div>
      </div>
      <RuntimeHealthCard snapshot={runtime} compact />
      <MemoryUsageItem />
    </section>
  );
}
