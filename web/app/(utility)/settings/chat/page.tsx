"use client";

import { CategoryScroll } from "@/components/settings/CategoryScroll";

import ToolsSettingsPage from "../tools/page";
import CapabilitiesSettingsPage from "../capabilities/page";
import StarterSettingsPage from "../starters/page";
import AttachmentSettingsPage from "../attachments/page";

/**
 * The Chat category, in full — see `ModelsSettingsPage` for the pattern.
 */
export default function ChatSettingsPage() {
  return (
    <CategoryScroll
      sections={[
        { key: "tools", Component: ToolsSettingsPage },
        { key: "capabilities", Component: CapabilitiesSettingsPage },
        { key: "starters", Component: StarterSettingsPage },
        { key: "attachments", Component: AttachmentSettingsPage },
      ]}
    />
  );
}
