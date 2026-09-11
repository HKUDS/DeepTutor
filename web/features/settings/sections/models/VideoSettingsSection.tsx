"use client";

import { useTranslation } from "react-i18next";

import { ServiceConfigEditor } from "@/components/settings/ServiceConfigEditor";
import { SettingsPageHeader } from "@/components/settings/shared";

export default function VideoGenSettingsPage() {
  const { t } = useTranslation();
  return (
    <div>
      <SettingsPageHeader
        title={t("Video Generation")}
        description={t(
          "Text-to-video model used by the chat 'videogen' tool. Rendering is asynchronous and may take a minute or more. Uses async task providers like Volcengine Seedance.",
        )}
      />
      <ServiceConfigEditor service="videogen" />
    </div>
  );
}
