"use client";

import dynamic from "next/dynamic";
import { useMemo } from "react";

import { CategoryScroll } from "@/components/settings/CategoryScroll";
import SettingsOverview from "@/components/settings/SettingsOverview";

import {
  isSettingsCategoryVisible,
  SETTINGS_CATEGORIES,
} from "@/features/settings/navigation/settings-nav";
import { useSettingsAccess } from "@/features/settings/navigation/SettingsAccessProvider";

const sectionLoading = () => <div className="min-h-80" aria-hidden="true" />;

const AppearanceSettingsPage = dynamic(
  () => import("@/features/settings/sections/AppearanceSettingsSection"),
  { loading: sectionLoading },
);
const NetworkSettingsPage = dynamic(
  () => import("@/features/settings/sections/NetworkSettingsSection"),
  { loading: sectionLoading },
);
const WorkspaceSettingsPage = dynamic(
  () => import("@/features/settings/sections/WorkspaceSettingsSection"),
  { loading: sectionLoading },
);
const ModelsSettingsPage = dynamic(
  () => import("@/features/settings/sections/ModelsSettingsSection"),
  { loading: sectionLoading },
);
const DocumentParsingSettingsPage = dynamic(
  () => import("@/features/settings/sections/DocumentParsingSettingsSection"),
  { loading: sectionLoading },
);
const ChatSettingsPage = dynamic(
  () => import("@/features/settings/sections/ChatSettingsSection"),
  { loading: sectionLoading },
);
const AgentsSettingsPage = dynamic(
  () => import("@/features/settings/sections/AgentsSettingsSection"),
  { loading: sectionLoading },
);
const LearnerProfileSettingsPage = dynamic(
  () => import("@/features/settings/sections/LearnerProfileSettingsSection"),
  { loading: sectionLoading },
);
const GuardianSettingsPage = dynamic(
  () => import("@/features/settings/sections/GuardianSettingsSection"),
  { loading: sectionLoading },
);
const MemorySettingsPage = dynamic(
  () => import("@/features/settings/sections/MemorySettingsSection"),
  { loading: sectionLoading },
);
const AboutSettingsPage = dynamic(
  () => import("@/features/settings/sections/AboutSettingsSection"),
  { loading: sectionLoading },
);

const childKeys = (key: string) =>
  SETTINGS_CATEGORIES.find((category) => category.key === key)?.children?.map(
    (child) => child.key,
  ) ?? [];

const SETTINGS_SECTIONS = [
  { key: "overview", Component: SettingsOverview },
  { key: "appearance", Component: AppearanceSettingsPage },
  { key: "network", Component: NetworkSettingsPage },
  { key: "workspace", Component: WorkspaceSettingsPage },
  {
    key: "models",
    Component: ModelsSettingsPage,
    activationKeys: childKeys("models"),
  },
  { key: "knowledge", Component: DocumentParsingSettingsPage },
  {
    key: "chat",
    Component: ChatSettingsPage,
    activationKeys: childKeys("chat"),
  },
  {
    key: "agents",
    Component: AgentsSettingsPage,
    activationKeys: childKeys("agents"),
  },
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

  return <CategoryScroll sections={sections} deferSections />;
}
