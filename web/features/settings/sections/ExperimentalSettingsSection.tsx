"use client";

import { useTranslation } from "react-i18next";

import { Toggle } from "@/components/settings/Toggle";
import {
  SettingRow,
  SettingSection,
  SettingsPageHeader,
} from "@/components/settings/shared";
import { useUiSettings } from "@/features/settings/store";

export default function ExperimentalSettingsSection() {
  const { t } = useTranslation();
  const {
    experimentalMasteryPlanning,
    updateExperimentalMasteryPlanning,
  } = useUiSettings();

  return (
    <div>
      <SettingsPageHeader
        title={t("Experimental")}
        description={t("Try opt-in features that are still being refined.")}
      />
      <SettingRow
        title={t("New mastery planning flow")}
        description={t(
          "Enable the new Planning Workspace and Route Draft creation flow.",
        )}
        control={
          <Toggle
            checked={experimentalMasteryPlanning}
            onChange={(next) => void updateExperimentalMasteryPlanning(next)}
          />
        }
      />
    </div>
  );
}
