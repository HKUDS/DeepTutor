"use client";

import { useTranslation } from "react-i18next";

import { ModelsWorkspace } from "@/components/settings/ModelsWorkspace";
import { SettingsPageHeader } from "@/components/settings/shared";
import { useSettings } from "@/features/settings/store/SettingsStore";

/**
 * The ordered fallback chain (#2693) is configured outside this page for now.
 * Show it read-only so an operator can tell whether a failover path exists —
 * an Apply on this page preserves the chain, it does not create one.
 */
function FallbackChainNotice() {
  const { t } = useTranslation();
  const { catalog } = useSettings();
  const chain = catalog.services.llm.fallbacks ?? [];
  if (chain.length === 0) return null;
  return (
    <div className="mb-6 rounded-xl border border-[var(--border)]/60 bg-[var(--card)] px-4 py-3 text-[12.5px] leading-relaxed">
      <div className="font-medium">
        {t("Fallback chain: {{count}} configured", { count: chain.length })}
      </div>
      <div className="mt-1 text-[var(--muted-foreground)]">
        {t(
          "When the active model fails before any output, DeepTutor tries these in order and returns to the primary once its cooldown ends. Edited in the catalog, not on this page.",
        )}
      </div>
      <ul className="mt-1.5 list-disc pl-5 text-[var(--muted-foreground)]">
        {chain.map((entry) => (
          <li key={`${entry.profile_id}:${entry.model_id}`}>
            {entry.profile_id} / {entry.model_id}
          </li>
        ))}
      </ul>
    </div>
  );
}

export default function LlmSettingsPage() {
  const { t } = useTranslation();

  return (
    <div>
      <SettingsPageHeader
        title={t("Language models")}
        description={t(
          "Manage language models and their context, capabilities, and connection tests.",
        )}
      />
      <FallbackChainNotice />
      <ModelsWorkspace page="llm" />
    </div>
  );
}
