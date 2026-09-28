"use client";
import { useTranslation } from "react-i18next";
import { TaskModelsWorkspace } from "@/components/settings/TaskModelsWorkspace";
import { SettingsPageHeader } from "@/components/settings/shared";
export default function TaskModelsSettingsPage() {
  const { t } = useTranslation();
  return (
    <div>
      <SettingsPageHeader
        title={t("Task models")}
        description={t(
          "The model behind the calls DeepTutor makes on its own — titles, suggestions, lookups. Set one for all of them, or give a task its own.",
        )}
      />
      <TaskModelsWorkspace />
    </div>
  );
}
