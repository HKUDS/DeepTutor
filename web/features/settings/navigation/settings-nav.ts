"use client";

import {
  AudioLines,
  Bot,
  Boxes,
  Brain,
  BrainCircuit,
  Clapperboard,
  Database,
  FileScan,
  FolderOpen,
  Image as ImageIcon,
  Info,
  KeyRound,
  Library,
  ListChecks,
  MessagesSquare,
  Mic,
  Network,
  Palette,
  Paperclip,
  Search,
  ShieldCheck,
  SlidersHorizontal,
  Sparkles,
  UserRound,
  Wrench,
  type LucideIcon,
} from "lucide-react";

import {
  ClaudeGlyph,
  CodexGlyph,
  DeepSeekGlyph,
  GeminiGlyph,
  HermesGlyph,
  KimiGlyph,
  MimoGlyph,
  OpenClawGlyph,
  OpencodeGlyph,
} from "@/components/agents/agent-icons";
import type { ServiceName } from "@/features/settings/store/SettingsStore";
import type { SettingsAccess } from "@/features/settings/navigation/settings-access";

/**
 * Settings information architecture.
 *
 * One document at `/settings`: categories and leaves map to stable fragment
 * identifiers, while this module remains the source for labels, visibility,
 * search metadata, and persistence hints.
 */

export type Lang = { zh: string; en: string };

export interface SettingsLeaf {
  key: string;
  href: string;
  label: Lang;
  blurb: Lang;
  icon: LucideIcon;
  /** Colored icon-tile accent for the sub-hub grid (full class strings). */
  tile: string;
  /** Model-service leaves carry a configured/not chip from the catalog. */
  service?: ServiceName;
  /** Hidden from non-admin users (the backend rejects them anyway). */
  adminOnly?: boolean;
}

export interface SettingsCategory {
  key: string;
  label: Lang;
  /** One-line descriptor shown on the hub block. */
  blurb: Lang;
  icon: LucideIcon;
  /** Canonical in-document category anchor. */
  href: string;
  /** Nested anchors (omitted for direct-section categories). */
  children?: SettingsLeaf[];
  /** Shown only when the backend reports an active learner policy. */
  learnerOnly?: boolean;
  /** Shown only to authenticated standard users who may act as guardians. */
  guardianOnly?: boolean;
}

export function isSettingsLeafVisible(
  leaf: SettingsLeaf,
  access: SettingsAccess,
): boolean {
  return !(leaf.adminOnly && access.hideAdminOnly);
}

export function isSettingsCategoryVisible(
  category: SettingsCategory,
  access: SettingsAccess,
): boolean {
  if (category.learnerOnly && !access.showLearnerOnly) return false;
  if (category.guardianOnly && !access.showGuardianOnly) return false;
  return (
    !category.children ||
    category.children.some((leaf) => isSettingsLeafVisible(leaf, access))
  );
}

export function visibleSettingsChildren(
  categoryKey: string,
  access: SettingsAccess,
): SettingsLeaf[] {
  return (
    SETTINGS_CATEGORIES.find((category) => category.key === categoryKey)
      ?.children ?? []
  ).filter((leaf) => isSettingsLeafVisible(leaf, access));
}

const MODEL_CHILDREN: SettingsLeaf[] = [
  {
    key: "connections",
    href: "/settings#connections",
    label: { zh: "连接", en: "Connections" },
    blurb: {
      zh: "一份凭据供给多个服务。",
      en: "One credential, supplying several services.",
    },
    icon: KeyRound,
    tile: "bg-sky-500/10 text-sky-600 dark:text-sky-400",
  },
  {
    key: "llm",
    href: "/settings#llm",
    label: { zh: "LLM", en: "LLM" },
    blurb: {
      zh: "语言模型供应商与当前档位。",
      en: "Language model providers and active profile.",
    },
    icon: Brain,
    tile: "bg-violet-500/10 text-violet-600 dark:text-violet-400",
    service: "llm",
  },
  {
    key: "task-models",
    href: "/settings#task-models",
    label: { zh: "任务模型", en: "Task models" },
    blurb: {
      zh: "DeepTutor 自己发起的调用使用的模型。",
      en: "The model behind the calls DeepTutor makes on its own.",
    },
    icon: ListChecks,
    tile: "bg-cyan-500/10 text-cyan-600 dark:text-cyan-400",
  },
  {
    key: "embedding",
    href: "/settings#embedding",
    label: { zh: "嵌入模型", en: "Embedding" },
    blurb: {
      zh: "向量模型供应商与维度。",
      en: "Embedding model providers and dimensions.",
    },
    icon: Database,
    tile: "bg-emerald-500/10 text-emerald-600 dark:text-emerald-400",
    service: "embedding",
  },
  {
    key: "search",
    href: "/settings#search",
    label: { zh: "搜索", en: "Search" },
    blurb: { zh: "联网搜索供应商。", en: "Web search providers." },
    icon: Search,
    tile: "bg-amber-500/10 text-amber-600 dark:text-amber-400",
    service: "search",
  },
  {
    key: "tts",
    href: "/settings#tts",
    label: { zh: "语音合成", en: "Text-to-Speech" },
    blurb: {
      zh: "朗读助手回复的 TTS 供应商。",
      en: "Text-to-speech for reading replies aloud.",
    },
    icon: AudioLines,
    tile: "bg-rose-500/10 text-rose-600 dark:text-rose-400",
    service: "tts",
  },
  {
    key: "stt",
    href: "/settings#stt",
    label: { zh: "语音识别", en: "Speech-to-Text" },
    blurb: {
      zh: "转写麦克风录音的 STT 供应商。",
      en: "Speech-to-text for the composer microphone.",
    },
    icon: Mic,
    tile: "bg-pink-500/10 text-pink-600 dark:text-pink-400",
    service: "stt",
  },
  {
    key: "imagegen",
    href: "/settings#imagegen",
    label: { zh: "文生图", en: "Image Generation" },
    blurb: {
      zh: "chat imagegen 工具使用的文生图模型。",
      en: "Text-to-image model for the chat imagegen tool.",
    },
    icon: ImageIcon,
    tile: "bg-fuchsia-500/10 text-fuchsia-600 dark:text-fuchsia-400",
    service: "imagegen",
  },
  {
    key: "videogen",
    href: "/settings#videogen",
    label: { zh: "文生视频", en: "Video Generation" },
    blurb: {
      zh: "chat videogen 工具使用的文生视频模型。",
      en: "Text-to-video model for the chat videogen tool.",
    },
    icon: Clapperboard,
    tile: "bg-indigo-500/10 text-indigo-600 dark:text-indigo-400",
    service: "videogen",
  },
];

const CHAT_CHILDREN: SettingsLeaf[] = [
  {
    key: "video-learning",
    href: "/settings#video-learning",
    label: { zh: "视频学习", en: "Video Learning" },
    blurb: {
      zh: "原生 YouTube 与本地 Invidious 播放供应商。",
      en: "Native YouTube and local Invidious playback providers.",
    },
    icon: Clapperboard,
    tile: "bg-red-500/10 text-red-600 dark:text-red-400",
    adminOnly: true,
  },
  {
    key: "tools",
    href: "/settings#tools",
    label: { zh: "工具", en: "Tools" },
    blurb: {
      zh: "对话智能体可调用的内置工具。",
      en: "Built-in tools the chat agent can invoke.",
    },
    icon: Wrench,
    tile: "bg-orange-500/10 text-orange-600 dark:text-orange-400",
  },
  {
    key: "capabilities",
    href: "/settings#capabilities",
    label: { zh: "能力", en: "Capabilities" },
    blurb: {
      zh: "各能力的 LLM 参数与运行时旋钮。",
      en: "Per-capability LLM parameters and runtime knobs.",
    },
    icon: SlidersHorizontal,
    tile: "bg-lime-500/10 text-lime-600 dark:text-lime-400",
  },
  {
    key: "starters",
    href: "/settings#starters",
    label: { zh: "起始建议", en: "Starting points" },
    blurb: {
      zh: "主页输入框下方那三行引导的素材范围。",
      en: "How much history shapes the three lines under the composer.",
    },
    icon: Sparkles,
    tile: "bg-violet-500/10 text-violet-600 dark:text-violet-400",
  },
  {
    key: "attachments",
    href: "/settings#attachments",
    label: { zh: "附件", en: "Attachments" },
    blurb: {
      zh: "聊天附件的大小上限与文本提取预算。",
      en: "Upload caps and extraction budgets for chat attachments.",
    },
    icon: Paperclip,
    tile: "bg-teal-500/10 text-teal-600 dark:text-teal-400",
    adminOnly: true,
  },
];

const AGENT_CHILDREN: SettingsLeaf[] = [
  {
    key: "agent-claude-code",
    href: "/settings#agent-claude-code",
    label: { zh: "Claude Code", en: "Claude Code" },
    blurb: {
      zh: "DeepTutor 调用本机 Claude Code 时的模型、推理强度与运行参数。",
      en: "Model, reasoning effort, and run params for the local Claude Code.",
    },
    // Brand glyph shares the lucide call signature (size/className).
    icon: ClaudeGlyph as unknown as LucideIcon,
    tile: "bg-orange-500/10 text-orange-600 dark:text-orange-400",
    adminOnly: true,
  },
  {
    key: "agent-codex",
    href: "/settings#agent-codex",
    label: { zh: "Codex", en: "Codex" },
    blurb: {
      zh: "DeepTutor 调用本机 Codex 时的模型、推理强度与运行参数。",
      en: "Model, reasoning effort, and run params for the local Codex.",
    },
    icon: CodexGlyph as unknown as LucideIcon,
    tile: "bg-blue-500/10 text-blue-600 dark:text-blue-400",
    adminOnly: true,
  },
  {
    // Gemini CLI's supported replacement.
    key: "agent-antigravity",
    href: "/settings#agent-antigravity",
    label: { zh: "Antigravity CLI", en: "Antigravity CLI" },
    blurb: {
      zh: "DeepTutor 调用本机 Antigravity CLI 时的模型与运行参数。",
      en: "Model and run params for the local Antigravity CLI.",
    },
    icon: GeminiGlyph as unknown as LucideIcon,
    tile: "bg-sky-500/10 text-sky-600 dark:text-sky-400",
    adminOnly: true,
  },
  {
    key: "agent-kimi",
    href: "/settings#agent-kimi",
    label: { zh: "Kimi CLI", en: "Kimi CLI" },
    blurb: {
      zh: "DeepTutor 调用本机 Kimi CLI 时的模型与运行参数。",
      en: "Model and run params for the local Kimi CLI.",
    },
    icon: KimiGlyph as unknown as LucideIcon,
    tile: "bg-zinc-500/10 text-zinc-700 dark:text-zinc-300",
    adminOnly: true,
  },
  {
    key: "agent-opencode",
    href: "/settings#agent-opencode",
    label: { zh: "opencode", en: "opencode" },
    blurb: {
      zh: "DeepTutor 调用本机 opencode 时的模型、推理强度与运行参数。",
      en: "Model, reasoning effort, and run params for the local opencode.",
    },
    icon: OpencodeGlyph as unknown as LucideIcon,
    tile: "bg-neutral-500/10 text-neutral-700 dark:text-neutral-300",
    adminOnly: true,
  },
  {
    key: "agent-mimo",
    href: "/settings#agent-mimo",
    label: { zh: "MiMo Code", en: "MiMo Code" },
    blurb: {
      zh: "DeepTutor 调用本机 MiMo Code 时的模型、推理强度与运行参数。",
      en: "Model, reasoning effort, and run params for the local MiMo Code.",
    },
    icon: MimoGlyph as unknown as LucideIcon,
    tile: "bg-orange-500/10 text-orange-600 dark:text-orange-400",
    adminOnly: true,
  },
  {
    key: "agent-hermes",
    href: "/settings#agent-hermes",
    label: { zh: "Hermes Agent", en: "Hermes Agent" },
    blurb: {
      zh: "DeepTutor 调用本机 Hermes Agent 时的模型、推理强度与运行参数。",
      en: "Model, reasoning effort, and run params for the local Hermes Agent.",
    },
    icon: HermesGlyph as unknown as LucideIcon,
    tile: "bg-violet-500/10 text-violet-600 dark:text-violet-400",
    adminOnly: true,
  },
  {
    key: "agent-hermes-remote",
    href: "/settings#agent-hermes-remote",
    label: { zh: "Hermes Agent（远程）", en: "Hermes Agent (remote)" },
    blurb: {
      zh: "通过 HTTP 网关调用远程 Hermes Agent，并按会话保持上下文。",
      en: "Call a remote Hermes Agent over HTTP with per-chat session continuity.",
    },
    icon: HermesGlyph as unknown as LucideIcon,
    tile: "bg-violet-500/10 text-violet-600 dark:text-violet-400",
    adminOnly: true,
  },
  {
    key: "agent-openclaw",
    href: "/settings#agent-openclaw",
    label: { zh: "OpenClaw", en: "OpenClaw" },
    blurb: {
      zh: "DeepTutor 通过 Gateway 或本地模式调用 OpenClaw 的运行参数。",
      en: "Gateway or local-mode run params for the local OpenClaw agent.",
    },
    icon: OpenClawGlyph as unknown as LucideIcon,
    tile: "bg-red-500/10 text-red-600 dark:text-red-400",
    adminOnly: true,
  },
  {
    key: "agent-deepseek-harness",
    href: "/settings#agent-deepseek-harness",
    label: { zh: "DeepSeek Harness", en: "DeepSeek Harness" },
    blurb: {
      zh: "DeepTutor 通过 Python SDK 或 headless CLI 调用 DeepSeek Harness。",
      en: "Python SDK or headless CLI settings for DeepSeek Harness.",
    },
    icon: DeepSeekGlyph as unknown as LucideIcon,
    tile: "bg-indigo-500/10 text-indigo-600 dark:text-indigo-400",
    adminOnly: true,
  },
];

export const SETTINGS_CATEGORIES: SettingsCategory[] = [
  {
    key: "appearance",
    label: { zh: "外观", en: "Appearance" },
    blurb: { zh: "视觉主题与代码块", en: "Theme and code blocks" },
    icon: Palette,
    href: "/settings#appearance",
  },
  {
    key: "network",
    label: { zh: "网络", en: "Network" },
    blurb: {
      zh: "端口、浏览器 API 地址与 CORS",
      en: "Ports, browser API base, and CORS",
    },
    icon: Network,
    href: "/settings#network",
  },
  {
    key: "workspace",
    label: { zh: "Workspace", en: "Workspace" },
    blurb: {
      zh: "Agent 可读取的文件与统一输出目录",
      en: "Agent-readable files and the shared output folder",
    },
    icon: FolderOpen,
    href: "/settings#workspace",
  },
  {
    key: "models",
    label: { zh: "模型", en: "Models" },
    blurb: {
      zh: "语言、向量、搜索、语音与生成模型",
      en: "Language, embedding, search, voice, and generation models",
    },
    icon: Boxes,
    href: "/settings#models",
    children: MODEL_CHILDREN,
  },
  {
    key: "knowledge",
    label: { zh: "知识库", en: "Knowledge Base" },
    blurb: { zh: "文档解析引擎", en: "Document parsing engine" },
    icon: Library,
    href: "/settings#document-parsing",
  },
  {
    key: "chat",
    label: { zh: "聊天", en: "Chat" },
    blurb: {
      zh: "工具、能力与附件",
      en: "Tools, capabilities, and attachments",
    },
    icon: MessagesSquare,
    href: "/settings#chat",
    children: CHAT_CHILDREN,
  },
  {
    key: "agents",
    label: { zh: "伙伴和智能体", en: "Partners & Agents" },
    blurb: {
      zh: "配置可在对话中调用的子智能体",
      en: "Configure the subagents you can call on in chat",
    },
    icon: Bot,
    href: "/settings#agents",
    children: AGENT_CHILDREN,
  },
  {
    key: "learner-profile",
    learnerOnly: true,
    label: { zh: "学习档案", en: "Learner profile" },
    blurb: {
      zh: "调整年龄、年级与讲解偏好。",
      en: "Adjust age, grade, and explanation preferences.",
    },
    icon: UserRound,
    href: "/settings#learner-profile",
  },
  {
    key: "guardian",
    guardianOnly: true,
    label: { zh: "监护管理", en: "Guardian" },
    blurb: {
      zh: "查看已授权学习者与学习材料。",
      en: "Review authorized learners and learning materials.",
    },
    icon: ShieldCheck,
    href: "/settings#guardian",
  },
  {
    key: "memory",
    label: { zh: "记忆", en: "Memory" },
    blurb: {
      zh: "分块、预算、去重与引用策略",
      en: "Chunking, budget, dedup, and reference policies",
    },
    icon: BrainCircuit,
    href: "/settings#memory",
  },
  {
    key: "about",
    label: { zh: "关于", en: "About" },
    blurb: {
      zh: "版本、更新与项目资源",
      en: "Version, updates, and project resources",
    },
    icon: Info,
    href: "/settings#about",
  },
];

export const SETTINGS_HUB_HREF = "/settings";

/** The canonical in-document URL used by the persistent settings navigator. */
export function settingsAnchorHref(key: string): string {
  return `${SETTINGS_HUB_HREF}#${key}`;
}

// The on-disk file (under data/user/settings/) each leaf module persists to.
// Surfaced in the toolbar status line so every page says where its parameters
// live, without duplicating the string on each page. Singleton pages (no
// merged category) are keyed by pathname; leaves inside a merged category
// page share one pathname, so those are keyed by `leaf.key` instead and
// looked up via the currently scrolled-to section (see `storagePathFor`).
const STORAGE_PATHS: Record<string, string> = {
  "/settings#appearance": "data/user/settings/interface.json",
  "/settings#network": "data/user/settings/system.json",
  "/settings#workspace": "data/user/settings/content_workspace.json",
  "/settings#llm": "data/user/settings/model_catalog.json",
  "/settings#embedding": "data/user/settings/model_catalog.json",
  "/settings#search": "data/user/settings/model_catalog.json",
  "/settings#tts": "data/user/settings/model_catalog.json",
  "/settings#stt": "data/user/settings/model_catalog.json",
  "/settings#image": "data/user/settings/model_catalog.json",
  "/settings#video": "data/user/settings/model_catalog.json",
  "/settings#video-learning": "data/user/settings/video_learning.json",
  "/settings#document-parsing": "data/user/settings/document_parsing.json",
  "/settings#memory": "data/user/settings/main.yaml",
  appearance: "data/user/settings/interface.json",
  network: "data/user/settings/system.json",
  workspace: "data/user/settings/content_workspace.json",
  connections: "data/user/settings/model_catalog.json",
  "task-models": "data/user/settings/model_catalog.json",
  knowledge: "data/user/settings/document_parsing.json",
  "video-learning": "data/user/settings/video_learning.json",
  starters: "data/user/settings/interface.json",
  memory: "data/user/settings/main.yaml",
  llm: "data/user/settings/model_catalog.json",
  embedding: "data/user/settings/model_catalog.json",
  search: "data/user/settings/model_catalog.json",
  tts: "data/user/settings/model_catalog.json",
  stt: "data/user/settings/model_catalog.json",
  imagegen: "data/user/settings/model_catalog.json",
  videogen: "data/user/settings/model_catalog.json",
  tools: "data/user/settings/interface.json",
  attachments: "data/user/settings/system.json",
  capabilities: "data/user/settings/main.yaml · agents.yaml",
  "agent-claude-code": "data/user/settings/subagent.json",
  "agent-codex": "data/user/settings/subagent.json",
  "agent-antigravity": "data/user/settings/subagent.json",
  "agent-kimi": "data/user/settings/subagent.json",
  "agent-opencode": "data/user/settings/subagent.json",
  "agent-mimo": "data/user/settings/subagent.json",
};

export function storagePathFor(
  pathname: string,
  activeSection?: string | null,
): string | null {
  if (pathname === SETTINGS_HUB_HREF) {
    return activeSection ? (STORAGE_PATHS[activeSection] ?? null) : null;
  }
  return STORAGE_PATHS[pathname] ?? null;
}
