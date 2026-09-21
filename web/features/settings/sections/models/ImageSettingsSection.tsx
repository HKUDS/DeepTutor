"use client";
import { useTranslation } from "react-i18next";
import { ModelsWorkspace } from "@/components/settings/ModelsWorkspace";
import { SettingsPageHeader } from "@/components/settings/shared";
export default function ImageSettingsPage() {
  const { t } = useTranslation();
  return (
    <div>
      <SettingsPageHeader
        title={t("Multimodal generation")}
        description={t(
          "Manage image and video generation models using saved providers.",
        )}
      />
      <ModelsWorkspace page="multimodal" initialService="imagegen" />
    </div>
  );
}
