"use client";

import { useTranslation } from "react-i18next";
import { SettingsPageHeader } from "./shared";
import SettingsStatusPanel from "./SettingsStatusPanel";
import SettingsReadinessPanel from "./SettingsReadinessPanel";
import { useSettings } from "@/features/settings/store/SettingsStore";

export default function SettingsRuntimePage() {
  const { t } = useTranslation();
  const { catalogEditable } = useSettings();
  return (
    <div>
      <SettingsPageHeader
        title={t("Runtime status")}
        description={t(
          "Check configured services and resolve connection problems.",
        )}
      />
      <SettingsStatusPanel />
      <SettingsReadinessPanel enabled={catalogEditable === true} />
    </div>
  );
}
