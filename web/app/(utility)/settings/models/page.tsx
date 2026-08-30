"use client";

import { CategoryScroll } from "@/components/settings/CategoryScroll";

import ConnectionsSettingsPage from "../connections/page";
import LlmSettingsPage from "../llm/page";
import TaskModelsSettingsPage from "../task-models/page";
import EmbeddingSettingsPage from "../embedding/page";
import SearchSettingsPage from "../search/page";
import TtsSettingsPage from "../tts/page";
import SttSettingsPage from "../stt/page";
import ImageGenSettingsPage from "../image/page";
import VideoGenSettingsPage from "../video/page";

/**
 * The Models category, in full: every service profile page stacked into one
 * scroll instead of nine routes. `SettingsNav` links each leaf here as
 * `#anchor` rather than a route change, so switching services never remounts
 * this page — see `CategoryScroll`.
 */
export default function ModelsSettingsPage() {
  return (
    <CategoryScroll
      sections={[
        { key: "connections", Component: ConnectionsSettingsPage },
        { key: "llm", Component: LlmSettingsPage },
        { key: "task-models", Component: TaskModelsSettingsPage },
        { key: "embedding", Component: EmbeddingSettingsPage },
        { key: "search", Component: SearchSettingsPage },
        { key: "tts", Component: TtsSettingsPage },
        { key: "stt", Component: SttSettingsPage },
        { key: "imagegen", Component: ImageGenSettingsPage },
        { key: "videogen", Component: VideoGenSettingsPage },
      ]}
    />
  );
}
