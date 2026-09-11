"use client";

import { useTranslation } from "react-i18next";

import { ConnectionsEditor } from "@/components/settings/ConnectionsEditor";
import { SettingsPageHeader } from "@/components/settings/shared";

export default function ConnectionsSettingsPage() {
  const { t } = useTranslation();
  return (
    <div>
      <SettingsPageHeader
        title={t("Connections")}
        description={t(
          "One vendor credential, supplying every model service that can use it. Services can still hold their own key instead.",
        )}
      />
      <ConnectionsEditor />
    </div>
  );
}
