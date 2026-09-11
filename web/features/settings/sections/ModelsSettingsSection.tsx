"use client";

import dynamic from "next/dynamic";

import { CategoryScroll } from "@/components/settings/CategoryScroll";
import { useSettingsAccess } from "@/features/settings/navigation/SettingsAccessProvider";
import { visibleSettingsChildren } from "@/features/settings/navigation/settings-nav";

const loading = () => <div className="min-h-64" aria-hidden="true" />;
const ConnectionsSettingsPage = dynamic(
  () => import("./models/ConnectionsSettingsSection"),
  { loading },
);
const LlmSettingsPage = dynamic(() => import("./models/LlmSettingsSection"), {
  loading,
});
const TaskModelsSettingsPage = dynamic(
  () => import("./models/TaskModelsSettingsSection"),
  { loading },
);
const EmbeddingSettingsPage = dynamic(
  () => import("./models/EmbeddingSettingsSection"),
  { loading },
);
const SearchSettingsPage = dynamic(
  () => import("./models/SearchSettingsSection"),
  { loading },
);
const TtsSettingsPage = dynamic(() => import("./models/TtsSettingsSection"), {
  loading,
});
const SttSettingsPage = dynamic(() => import("./models/SttSettingsSection"), {
  loading,
});
const ImageGenSettingsPage = dynamic(
  () => import("./models/ImageSettingsSection"),
  { loading },
);
const VideoGenSettingsPage = dynamic(
  () => import("./models/VideoSettingsSection"),
  { loading },
);

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
      deferSections
    />
  );
}
