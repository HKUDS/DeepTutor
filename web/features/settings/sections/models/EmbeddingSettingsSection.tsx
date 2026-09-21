"use client";
import { useTranslation } from "react-i18next";
import { ModelsWorkspace } from "@/components/settings/ModelsWorkspace";
import { SettingsPageHeader } from "@/components/settings/shared";
export default function EmbeddingSettingsPage() {
  const { t } = useTranslation();
  return (
    <div>
      <SettingsPageHeader
        title={t("Embedding models")}
        description={t(
          "Manage embedding models for retrieval and knowledge bases.",
        )}
      />
      <ModelsWorkspace page="embedding" />
    </div>
  );
}
