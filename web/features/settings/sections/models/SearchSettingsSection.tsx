"use client";
import { useTranslation } from "react-i18next";
import { ModelsWorkspace } from "@/components/settings/ModelsWorkspace";
import { SettingsPageHeader } from "@/components/settings/shared";
export default function SearchSettingsPage() {
  const { t } = useTranslation();
  return (
    <div>
      <SettingsPageHeader
        title={t("Search")}
        description={t(
          "Configure and test search engines using saved providers.",
        )}
      />
      <ModelsWorkspace page="search" />
    </div>
  );
}
