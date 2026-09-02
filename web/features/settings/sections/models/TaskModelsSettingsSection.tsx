"use client";

import { useTranslation } from "react-i18next";

import { TaskModelsEditor } from "@/components/settings/TaskModelsEditor";
import { SettingsPageHeader } from "@/components/settings/shared";

export default function TaskModelsSettingsPage() {
  const { t } = useTranslation();
  return (
    <div>
      <SettingsPageHeader
        title={t("Task models")}
        description={t(
          "Conversation titles and home screen starting points. Configured like the LLM — pick a provider, then a model. Left empty, both use the LLM.",
        )}
      />
      <TaskModelsEditor />
    </div>
  );
}
