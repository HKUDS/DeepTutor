"use client";

import { useTranslation } from "react-i18next";
import { QuickModelSetupWorkspace } from "@/components/settings/QuickModelSetupWorkspace";
import { SettingsPageHeader } from "@/components/settings/shared";

export default function QuickSetupSettingsSection() {
  const { t } = useTranslation();
  return (
    <div>
      <SettingsPageHeader
        title={t("Quick setup")}
        description={t("quickSetup.header.description")}
      />
      <QuickModelSetupWorkspace />
    </div>
  );
}
