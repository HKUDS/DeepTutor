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
        description={t(
          "Pick a provider, paste your API key, and start chatting in seconds.",
        )}
      />
      <QuickModelSetupWorkspace />
    </div>
  );
}
