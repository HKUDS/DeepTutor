"use client";

import { useMemo } from "react";

import { CategoryScroll } from "@/components/settings/CategoryScroll";
import SettingsOverview from "@/components/settings/SettingsOverview";

import AboutSettingsPage from "@/features/settings/sections/AboutSettingsSection";
import AgentsSettingsPage from "@/features/settings/sections/AgentsSettingsSection";
import AppearanceSettingsPage from "@/features/settings/sections/AppearanceSettingsSection";
import ChatSettingsPage from "@/features/settings/sections/ChatSettingsSection";
import DocumentParsingSettingsPage from "@/features/settings/sections/DocumentParsingSettingsSection";
import GuardianSettingsPage from "@/features/settings/sections/GuardianSettingsSection";
import LearnerProfileSettingsPage from "@/features/settings/sections/LearnerProfileSettingsSection";
import MemorySettingsPage from "@/features/settings/sections/MemorySettingsSection";
import ModelsSettingsPage from "@/features/settings/sections/ModelsSettingsSection";
import NetworkSettingsPage from "@/features/settings/sections/NetworkSettingsSection";
import {
  isSettingsCategoryVisible,
  SETTINGS_CATEGORIES,
} from "@/features/settings/navigation/settings-nav";
import { useSettingsAccess } from "@/features/settings/navigation/SettingsAccessProvider";

const SETTINGS_SECTIONS = [
  { key: "overview", Component: SettingsOverview },
  { key: "appearance", Component: AppearanceSettingsPage },
  { key: "network", Component: NetworkSettingsPage },
  { key: "models", Component: ModelsSettingsPage },
  { key: "knowledge", Component: DocumentParsingSettingsPage },
  { key: "chat", Component: ChatSettingsPage },
  { key: "agents", Component: AgentsSettingsPage },
  { key: "learner-profile", Component: LearnerProfileSettingsPage },
  { key: "guardian", Component: GuardianSettingsPage },
  { key: "memory", Component: MemorySettingsPage },
  { key: "about", Component: AboutSettingsPage },
] as const;

/**
 * Settings is one document: users can read it from Overview to About with a
 * normal scroll, while the persistent navigator links to these same anchors.
 * Every navigator target is an anchor in this document; no duplicate leaf
 * routes or redirect aliases remain.
 */
export default function SettingsPage() {
  const access = useSettingsAccess();
  const sections = useMemo(
    () =>
      SETTINGS_SECTIONS.filter(({ key }) => {
        if (key === "overview") return true;
        const category = SETTINGS_CATEGORIES.find((item) => item.key === key);
        return category ? isSettingsCategoryVisible(category, access) : false;
      }),
    [access],
  );

  // Waiting prevents a protected deep link from mounting an unauthorized
  // section and firing its API request before runtime auth has resolved.
  if (!access.resolved) {
    return <div className="h-48" aria-busy="true" />;
  }

  return <CategoryScroll sections={sections} />;
}
