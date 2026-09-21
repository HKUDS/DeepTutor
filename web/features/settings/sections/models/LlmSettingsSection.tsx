"use client";
import { useTranslation } from "react-i18next";
import { ModelsWorkspace } from "@/components/settings/ModelsWorkspace";
import { SettingsPageHeader } from "@/components/settings/shared";
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
      <ModelsWorkspace page="llm" />
    </div>
  );
}
