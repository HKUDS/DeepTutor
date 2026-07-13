"use client";

import { useTranslation } from "react-i18next";

import { ServiceConfigEditor } from "@/components/settings/ServiceConfigEditor";
import { SettingsPageHeader } from "@/components/settings/shared";

export default function SttSettingsPage() {
  const { t } = useTranslation();
  return (
    <div>
      <SettingsPageHeader
        title={t("Speech-to-Text")}
        description={t(
          "Transcribe the chat composer's microphone recordings. Works with any OpenAI-compatible audio API — OpenAI, Groq, SiliconFlow, Azure, or a local server.",
        )}
      />
      <ServiceConfigEditor service="stt" />
    </div>
  );
}
