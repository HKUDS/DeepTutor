"use client";

import { CategoryScroll } from "@/components/settings/CategoryScroll";
import { useSettingsAccess } from "@/features/settings/navigation/SettingsAccessProvider";
import { visibleSettingsChildren } from "@/features/settings/navigation/settings-nav";

import VideoLearningSettingsPage from "./VideoLearningSettingsSection";
import ToolsSettingsPage from "./ToolsSettingsSection";
import CapabilitiesSettingsPage from "./CapabilitiesSettingsSection";
import StarterSettingsPage from "./StartersSettingsSection";
import AttachmentSettingsPage from "./AttachmentsSettingsSection";

const CHAT_SECTIONS = [
  { key: "video-learning", Component: VideoLearningSettingsPage },
  { key: "tools", Component: ToolsSettingsPage },
  { key: "capabilities", Component: CapabilitiesSettingsPage },
  { key: "starters", Component: StarterSettingsPage },
  { key: "attachments", Component: AttachmentSettingsPage },
] as const;

/**
 * The Chat category, in full — see `ModelsSettingsPage` for the pattern.
 */
export default function ChatSettingsPage() {
  const access = useSettingsAccess();
  const visibleKeys = new Set(
    visibleSettingsChildren("chat", access).map((leaf) => leaf.key),
  );
  return (
    <CategoryScroll
      sections={CHAT_SECTIONS.filter(({ key }) => visibleKeys.has(key))}
    />
  );
}
