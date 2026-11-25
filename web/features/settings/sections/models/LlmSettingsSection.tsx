"use client";

import { useTranslation } from "react-i18next";

import { ModelsWorkspace } from "@/components/settings/ModelsWorkspace";
import { SettingsPageHeader } from "@/components/settings/shared";

import { FallbackChainEditor } from "./FallbackChainEditor";

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
      <FallbackChainEditor />
      <ModelsWorkspace page="llm" />
    </div>
  );
}
