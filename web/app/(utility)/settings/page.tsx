"use client";

import { CategoryScroll } from "@/components/settings/CategoryScroll";
import SettingsOverview from "@/components/settings/SettingsOverview";

import AboutSettingsPage from "./about/page";
import AgentsSettingsPage from "./agents/page";
import AppearanceSettingsPage from "./appearance/page";
import ChatSettingsPage from "./chat/page";
import DocumentParsingSettingsPage from "./document-parsing/page";
import MemorySettingsPage from "./memory/page";
import ModelsSettingsPage from "./models/page";
import NetworkSettingsPage from "./network/page";

/**
 * Settings is one document: users can read it from Overview to About with a
 * normal scroll, while the persistent navigator links to these same anchors.
 * The category pages remain as legacy deep-link targets, but normal Settings
 * navigation no longer remounts the right-hand pane.
 */
export default function SettingsPage() {
  return (
    <CategoryScroll
      sections={[
        { key: "overview", Component: SettingsOverview },
        { key: "appearance", Component: AppearanceSettingsPage },
        { key: "network", Component: NetworkSettingsPage },
        { key: "models", Component: ModelsSettingsPage },
        { key: "knowledge", Component: DocumentParsingSettingsPage },
        { key: "chat", Component: ChatSettingsPage },
        { key: "agents", Component: AgentsSettingsPage },
        { key: "memory", Component: MemorySettingsPage },
        { key: "about", Component: AboutSettingsPage },
      ]}
    />
  );
}
