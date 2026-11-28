"use client";
import { useTranslation } from "react-i18next";
import { ModelsWorkspace } from "@/components/settings/ModelsWorkspace";
import { ModelSectionGuideBanner } from "@/components/settings/ModelSectionGuideBanner";
import { SettingsPageHeader } from "@/components/settings/shared";
export default function MultimodalSettingsPage() {
  const { t } = useTranslation();
  return (
    <div>
      <SettingsPageHeader
        title={t("Multimodal generation")}
        description={t(
          "Manage image and video generation models using saved providers.",
        )}
      />
      <ModelSectionGuideBanner kind="multimodal" />
      <ModelsWorkspace page="multimodal" />
    </div>
  );
}
