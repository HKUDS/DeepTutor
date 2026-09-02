"use client";

import { CategoryScroll } from "@/components/settings/CategoryScroll";
import { useSettingsAccess } from "@/features/settings/navigation/SettingsAccessProvider";
import { visibleSettingsChildren } from "@/features/settings/navigation/settings-nav";

import ConnectionsSettingsPage from "./models/ConnectionsSettingsSection";
import LlmSettingsPage from "./models/LlmSettingsSection";
import TaskModelsSettingsPage from "./models/TaskModelsSettingsSection";
import EmbeddingSettingsPage from "./models/EmbeddingSettingsSection";
import SearchSettingsPage from "./models/SearchSettingsSection";
import TtsSettingsPage from "./models/TtsSettingsSection";
import SttSettingsPage from "./models/SttSettingsSection";
import ImageGenSettingsPage from "./models/ImageSettingsSection";
import VideoGenSettingsPage from "./models/VideoSettingsSection";

const MODEL_SECTIONS = [
  { key: "connections", Component: ConnectionsSettingsPage },
  { key: "llm", Component: LlmSettingsPage },
  { key: "task-models", Component: TaskModelsSettingsPage },
  { key: "embedding", Component: EmbeddingSettingsPage },
  { key: "search", Component: SearchSettingsPage },
  { key: "tts", Component: TtsSettingsPage },
  { key: "stt", Component: SttSettingsPage },
  { key: "imagegen", Component: ImageGenSettingsPage },
  { key: "videogen", Component: VideoGenSettingsPage },
] as const;

/**
 * The Models category, in full: every service profile page stacked into one
 * scroll instead of nine routes. `SettingsNav` links each leaf here as
 * `#anchor` rather than a route change, so switching services never remounts
 * this page — see `CategoryScroll`.
 */
export default function ModelsSettingsPage() {
  const access = useSettingsAccess();
  const visibleKeys = new Set(
    visibleSettingsChildren("models", access).map((leaf) => leaf.key),
  );
  return (
    <CategoryScroll
      sections={MODEL_SECTIONS.filter(({ key }) => visibleKeys.has(key))}
    />
  );
}
