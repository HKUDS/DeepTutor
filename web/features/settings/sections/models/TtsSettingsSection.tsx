"use client";
import { useTranslation } from "react-i18next";
import { ModelsWorkspace } from "@/components/settings/ModelsWorkspace";
import { SettingsPageHeader } from "@/components/settings/shared";
import { VoicePlaybackPrefs } from "./VoicePlaybackPrefs";
export default function TtsSettingsPage() {
  const { t } = useTranslation();
  return (
    <div>
      <SettingsPageHeader
        title={t("Voice")}
        description={t(
          "Manage speech synthesis and transcription models using saved providers.",
        )}
      />
      <VoicePlaybackPrefs />
      <ModelsWorkspace page="voice" initialService="tts" />
    </div>
  );
}
