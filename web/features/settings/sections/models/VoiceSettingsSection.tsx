"use client";
import { useTranslation } from "react-i18next";
import { ModelsWorkspace } from "@/components/settings/ModelsWorkspace";
import { SettingsPageHeader } from "@/components/settings/shared";
export default function VoiceSettingsPage() {
  const { t } = useTranslation();
  return (
    <div>
      <SettingsPageHeader
        title={t("Voice")}
        description={t(
          "Manage speech synthesis and transcription models using saved providers.",
        )}
      />
      <ModelsWorkspace page="voice" />
    </div>
  );
}
