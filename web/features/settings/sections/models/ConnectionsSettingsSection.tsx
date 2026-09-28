"use client";

import { useTranslation } from "react-i18next";

import { ProvidersWorkspace } from "@/components/settings/ProvidersWorkspace";
import { SettingsPageHeader } from "@/components/settings/shared";

export default function ConnectionsSettingsPage() {
  const { t } = useTranslation();
  return (
    <div>
      <SettingsPageHeader
        title={t("Providers")}
        description={t(
          "Manage provider names, URLs, and credentials. Configure models on their own pages.",
        )}
      />
      <ProvidersWorkspace />
    </div>
  );
}
