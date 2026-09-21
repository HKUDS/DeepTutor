"use client";

import dynamic from "next/dynamic";
import Link from "next/link";
import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { useTranslation } from "react-i18next";
import { useSettings } from "@/features/settings/store/SettingsStore";
import { useSettingsAccess } from "@/features/settings/navigation/SettingsAccessProvider";
import {
  resolveSettingsKey,
  settingsAnchorHref,
} from "@/features/settings/navigation/settings-nav";
import {
  settingsPageFamily,
  visibleSettingsPages,
} from "@/features/settings/navigation/settings-pages";

const loading = () => (
  <div
    className="min-h-48 animate-pulse rounded-xl bg-[var(--muted)]/30"
    aria-busy="true"
  />
);
const General = dynamic(() => import("./SettingsOverview"), { loading });
const Usage = dynamic(() => import("@/features/settings/sections/UsageSettingsSection"), { loading });
const DataMigration = dynamic(() => import("@/features/settings/sections/DataMigrationSettingsSection"), { loading });
const Status = dynamic(() => import("./SettingsRuntimePage"), { loading });
const Appearance = dynamic(
  () => import("@/features/settings/sections/AppearanceSettingsSection"),
  {
    loading,
  },
);
const Network = dynamic(
  () => import("@/features/settings/sections/NetworkSettingsSection"),
  {
    loading,
  },
);
const Workspace = dynamic(
  () => import("@/features/settings/sections/WorkspaceSettingsSection"),
  {
    loading,
  },
);
const Knowledge = dynamic(
  () => import("@/features/settings/sections/DocumentParsingSettingsSection"),
  { loading },
);
const Memory = dynamic(
  () => import("@/features/settings/sections/MemorySettingsSection"),
  {
    loading,
  },
);
const About = dynamic(
  () => import("@/features/settings/sections/AboutSettingsSection"),
  {
    loading,
  },
);
const Learner = dynamic(
  () => import("@/features/settings/sections/LearnerProfileSettingsSection"),
  { loading },
);
const Guardian = dynamic(
  () => import("@/features/settings/sections/GuardianSettingsSection"),
  {
    loading,
  },
);
const Connections = dynamic(
  () =>
    import("@/features/settings/sections/models/ConnectionsSettingsSection"),
  { loading },
);
const Llm = dynamic(
  () => import("@/features/settings/sections/models/LlmSettingsSection"),
  {
    loading,
  },
);
const Task = dynamic(
  () => import("@/features/settings/sections/models/TaskModelsSettingsSection"),
  { loading },
);
const Embedding = dynamic(
  () => import("@/features/settings/sections/models/EmbeddingSettingsSection"),
  { loading },
);
const Search = dynamic(
  () => import("@/features/settings/sections/models/SearchSettingsSection"),
  {
    loading,
  },
);
const Tts = dynamic(
  () => import("@/features/settings/sections/models/TtsSettingsSection"),
  {
    loading,
  },
);
const Stt = dynamic(
  () => import("@/features/settings/sections/models/SttSettingsSection"),
  {
    loading,
  },
);
const Image = dynamic(
  () => import("@/features/settings/sections/models/ImageSettingsSection"),
  {
    loading,
  },
);
const Video = dynamic(
  () => import("@/features/settings/sections/models/VideoSettingsSection"),
  {
    loading,
  },
);
const VideoLearning = dynamic(
  () => import("@/features/settings/sections/VideoLearningSettingsSection"),
  { loading },
);
const Tools = dynamic(
  () => import("@/features/settings/sections/ToolsSettingsSection"),
  {
    loading,
  },
);
const Capabilities = dynamic(
  () => import("@/features/settings/sections/CapabilitiesSettingsSection"),
  { loading },
);
const Starters = dynamic(
  () => import("@/features/settings/sections/StartersSettingsSection"),
  {
    loading,
  },
);
const Attachments = dynamic(
  () => import("@/features/settings/sections/AttachmentsSettingsSection"),
  { loading },
);
const Agent = dynamic(
  () =>
    import("./SubagentSettingsEditor").then(
      (module) => module.SubagentSettingsEditor,
    ),
  { loading },
);

const Archive = dynamic(
  () => import("@/features/settings/sections/ArchivedChatsSettingsSection"),
  {
    loading,
  },
);

const Voice = dynamic(
  () => import("@/features/settings/sections/models/VoiceSettingsSection"),
  { loading },
);

const Multimodal = dynamic(
  () => import("@/features/settings/sections/models/MultimodalSettingsSection"),
  { loading },
);

const PAGES: Record<string, React.ComponentType> = {
  "data-migration": DataMigration,
  voice: Voice,
  multimodal: Multimodal,
  archive: Archive,
  general: General,
  status: Status,
  usage: Usage,
  appearance: Appearance,
  network: Network,
  workspace: Workspace,
  knowledge: Knowledge,
  memory: Memory,
  about: About,
  "learner-profile": Learner,
  guardian: Guardian,
  connections: Connections,
  llm: Llm,
  "task-models": Task,
  embedding: Embedding,
  search: Search,
  tts: Tts,
  stt: Stt,
  imagegen: Image,
  videogen: Video,
  "video-learning": VideoLearning,
  tools: Tools,
  capabilities: Capabilities,
  starters: Starters,
  attachments: Attachments,
};
const AGENTS = {
  "agent-claude-code": "claude_code",
  "agent-codex": "codex",
  "agent-antigravity": "antigravity",
  "agent-kimi": "kimi",
  "agent-opencode": "opencode",
  "agent-mimo": "mimo",
  "agent-hermes": "hermes",
  "agent-hermes-remote": "hermes_remote",
  "agent-openclaw": "openclaw",
  "agent-deepseek-harness": "deepseek_harness",
} as const;

export default function SettingsPageContent({ section }: { section: string }) {
  const { t, i18n } = useTranslation();
  const router = useRouter();
  const access = useSettingsAccess();
  const { settingsLoading, saving, applying } = useSettings();
  const key = resolveSettingsKey(section);
  const pages = visibleSettingsPages(access);
  const page = pages.find((item) => item.key === key);
  const family = settingsPageFamily(key).flatMap((member) =>
    pages.filter((item) => item.key === member),
  );
  const zh = i18n.language?.toLowerCase().startsWith("zh");
  useEffect(() => {
    if (key !== section)
      router.replace(settingsAnchorHref(key) + window.location.search, {
        scroll: false,
      });
  }, [key, section, router]);
  if (!access.resolved) return loading();
  if (settingsLoading) return loading();
  if (!page)
    return (
      <div className="space-y-4">
        <h1 className="text-xl font-semibold">
          {t("This settings page is unavailable.")}
        </h1>
        <Link href="/settings/general" className="text-sm underline">
          {t("Back to settings")}
        </Link>
      </div>
    );
  const Component = PAGES[key];
  const kind = AGENTS[key as keyof typeof AGENTS];
  return (
    <fieldset disabled={saving || applying} aria-busy={saving || applying} className="min-w-0" data-settings-page={key}>
      {family.length > 1 && (
        <nav
          aria-label={t("Related settings")}
          className="mb-8 flex flex-wrap gap-1 border-b border-[var(--border)]/60 pb-3"
        >
          {family.map((item) => (
            <Link
              key={item.key}
              href={settingsAnchorHref(item.key)}
              scroll={false}
              aria-current={item.key === key ? "page" : undefined}
              className={`rounded-lg px-3 py-2 text-[13px] outline-none focus-visible:ring-2 focus-visible:ring-[var(--ring)] ${item.key === key ? "bg-[var(--accent)] font-medium" : "text-[var(--muted-foreground)] hover:bg-[var(--accent)]/50"}`}
            >
              {zh ? item.label.zh : item.label.en}
            </Link>
          ))}
        </nav>
      )}
      {Component ? (
        <Component key={key} />
      ) : kind ? (
        <Agent key={key} kind={kind} />
      ) : null}
    </fieldset>
  );
}
