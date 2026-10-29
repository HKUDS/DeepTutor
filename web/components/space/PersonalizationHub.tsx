"use client";

import { useTranslation } from "react-i18next";
import { FeaturePage } from "@/components/layout/FeaturePage";
import SpaceDashboard from "@/components/space/SpaceDashboard";
import { PERSONALIZATION_GROUPS } from "@/components/space/dashboard-groups";
import { PersonalizationShelfIcon } from "@/components/sidebar/ShelfIcons";

/** The account's own shelf: the same in every workspace. */
export function PersonalizationHub() {
  const { t } = useTranslation();
  return (
    <FeaturePage>
      <SpaceDashboard
        icon={PersonalizationShelfIcon}
        title={t("navigation.personalization")}
        description={t("navigation.personalizationIntro")}
        groups={PERSONALIZATION_GROUPS}
      />
    </FeaturePage>
  );
}
