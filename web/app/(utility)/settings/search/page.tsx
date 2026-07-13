"use client";

import { useTranslation } from "react-i18next";

import { ServiceConfigEditor } from "@/components/settings/ServiceConfigEditor";
import { SettingsPageHeader } from "@/components/settings/shared";

export default function SearchSettingsPage() {
  const { t } = useTranslation();
  return (
    <div>
      <SettingsPageHeader
        title={t("Search")}
        description={t(
          "Configure web search providers. Used by the web_search tool and any agent step that hits the open web.",
        )}
      />
      <ServiceConfigEditor service="search" />
    </div>
  );
}
