"use client";

import { useTranslation } from "react-i18next";

import { ServiceConfigEditor } from "@/components/settings/ServiceConfigEditor";
import { SettingsPageHeader } from "@/components/settings/shared";

export default function ImageGenSettingsPage() {
  const { t } = useTranslation();
  return (
    <div>
      <SettingsPageHeader
        title={t("Image Generation")}
        description={t(
          "Text-to-image model used by the chat 'imagegen' tool. Works with any OpenAI-compatible /images/generations API — OpenAI, Volcengine Seedream, or compatible gateways.",
        )}
      />
      <ServiceConfigEditor service="imagegen" />
    </div>
  );
}
