"use client";

import { useTranslation } from "react-i18next";

import { ServiceConfigEditor } from "@/components/settings/ServiceConfigEditor";
import { SettingsPageHeader } from "@/components/settings/shared";

export default function LlmSettingsPage() {
  const { t } = useTranslation();
  return (
    <div>
      <SettingsPageHeader
        title={t("LLM")}
        description={t(
          "Configure language model profiles. The active model is used for chat and most agent reasoning.",
        )}
      />
      <ServiceConfigEditor service="llm" />
    </div>
  );
}
