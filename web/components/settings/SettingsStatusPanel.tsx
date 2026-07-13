"use client";

import { Fragment } from "react";
import { useTranslation } from "react-i18next";

import { useSettings } from "@/components/settings/SettingsContext";
import { statusDotClass } from "@/components/settings/shared";

/**
 * Resident status module on the settings hub — the old `/settings/status` page
 * demoted to an always-visible strip. Reads the runtime `/system/status`
 * snapshot (available to every user, unlike the editable catalog), so it
 * reflects what is actually running rather than the draft.
 *
 * Compact, left-aligned, hairline-separated items — no stretched grid or
 * uppercase eyebrow (CJK reads badly with letter-spacing).
 */
export default function SettingsStatusPanel() {
  const { t } = useTranslation();
  const { status } = useSettings();

  const items = [
    {
      key: "backend",
      name: t("Backend"),
      configured: status?.backend.status === "online",
      hasError: false,
      value: status
        ? status.backend.status === "online"
          ? t("Online")
          : t("Checking")
        : t("Checking"),
    },
    {
      key: "llm",
      name: t("LLM"),
      configured: Boolean(status?.llm.model),
      hasError: Boolean(status?.llm.error),
      value: status?.llm.model || t("Not set"),
    },
    {
      key: "embedding",
      name: t("Embedding"),
      configured: Boolean(status?.embeddings.model),
      hasError: Boolean(status?.embeddings.error),
      value: status?.embeddings.model || t("Not set"),
    },
    {
      key: "search",
      name: t("Search"),
      configured: Boolean(status?.search.provider),
      hasError: Boolean(status?.search.error),
      value: status?.search.provider || t("Not set"),
    },
  ];

  return (
    <section
      data-tour="tour-status"
      className="flex flex-wrap items-center gap-x-5 gap-y-2.5 rounded-2xl border border-[var(--border)]/70 bg-[var(--card)]/50 px-5 py-3.5"
    >
      {items.map((item, i) => (
        <Fragment key={item.key}>
          {i > 0 && (
            <span
              aria-hidden
              className="hidden h-7 w-px shrink-0 bg-[var(--border)]/70 sm:block"
            />
          )}
          <div className="flex items-center gap-2.5">
            <span
              className={`h-2 w-2 shrink-0 rounded-full ${statusDotClass(
                item.configured,
                item.hasError,
              )}`}
            />
            <div className="flex items-baseline gap-2">
              <span className="text-[13px] font-medium leading-none tracking-tight text-[var(--foreground)]">
                {item.name}
              </span>
              <span
                className="max-w-[220px] truncate text-[12px] leading-none text-[var(--muted-foreground)]"
                title={item.value}
              >
                {item.value}
              </span>
            </div>
          </div>
        </Fragment>
      ))}
    </section>
  );
}
