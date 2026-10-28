/**
 * The /space hub's sections: what each resource is called, where it lives,
 * its icon and live count. Shared by the hub, the sidebar shelf, the ⌘K
 * palette and the page bar, so it carries no component code.
 */
import {
  BookOpen,
  Bookmark,
  Bot,
  Brain,
  ClipboardList,
  Ear,
  History,
  NotebookPen,
  Plug,
  Terminal,
  UserRound,
  Wand2,
  type LucideIcon,
} from "lucide-react";

import { SPACE_MCP_SURFACE, loadMcpSurface } from "@/components/mcp/surface";
import { getCliApps } from "@/lib/cli-apps-api";
import { listSessions } from "@/lib/session-api";
import { listNotebooks, listNotebookEntries } from "@/lib/notebook-api";
import { listPersonas } from "@/lib/personas-api";
import { listKnowledgeBases } from "@/features/knowledge/api/catalog";
import { listSkills } from "@/lib/skills-api";
import { listSubagentConnections } from "@/lib/subagents-api";

export type Lang = { zh: string; en: string };

export type DashKey =
  | "agents"
  | "knowledge"
  | "memory"
  | "chat_history"
  | "notebooks"
  | "journal"
  | "question_bank"
  | "personas"
  | "skills"
  | "mcp"
  | "cli_apps"
  | "whisper";

export interface DashboardItem {
  key: DashKey;
  href: string;
  icon: LucideIcon;
  title: Lang;
  blurb: Lang;
  /**
   * Unit shown after the live count, e.g. "168 conversations". Omitted
   * together with ``load`` for a tile that has nothing to count.
   */
  unit?: Lang;
  /** Icon-tile accent — full class strings so Tailwind keeps them. */
  tile: string;
  /**
   * Live count for the tile. Optional: a surface with no countable rows (an
   * ephemeral room, say) renders as title + blurb instead of showing a
   * permanently-loading number.
   */
  load?: () => Promise<number>;
  /** GitHub handle of the contributor this surface came from. */
  credit?: string;
  /**
   * Turn capability this surface needs, when it is not served by this
   * repository. The tile is withheld unless the backend registry actually
   * holds the name, so a stock install never offers a room whose capability
   * was never installed (#963).
   */
  requiresCapability?: string;
}

export interface DashboardGroup {
  label: Lang;
  items: DashboardItem[];
}

export const DASHBOARD_GROUPS: DashboardGroup[] = [
  {
    label: { zh: "对话与资料", en: "Conversations & Materials" },
    items: [
      {
        key: "chat_history",
        href: "/space/chat-history",
        icon: History,
        title: { zh: "聊天历史", en: "Chat History" },
        blurb: {
          zh: "回顾并继续此前的对话。",
          en: "Review and reopen previous conversations.",
        },
        unit: { zh: "段对话", en: "conversations" },
        tile: "bg-sky-500/10 text-sky-600 dark:text-sky-400",
        load: async () => (await listSessions(200, 0, { force: true })).length,
      },
      {
        key: "notebooks",
        href: "/notebooks",
        icon: Bookmark,
        title: { zh: "收藏夹", en: "Favorites" },
        blurb: {
          zh: "收藏对话和资料的原文，随时引用到笔记本。",
          en: "Keep original conversations and sources, ready to use in your notes.",
        },
        unit: { zh: "个收藏夹", en: "collections" },
        tile: "bg-amber-500/10 text-amber-600 dark:text-amber-400",
        load: async () => (await listNotebooks()).length,
      },
      {
        key: "journal",
        href: "/space/journal",
        icon: NotebookPen,
        title: { zh: "学习日志", en: "Learning journal" },
        blurb: {
          zh: "查看当前目标、上次会话交接和已确认的学习记录。",
          en: "Inspect your mission, session handoff and confirmed records.",
        },
        tile: "bg-teal-500/10 text-teal-600 dark:text-teal-400",
      },
      {
        key: "question_bank",
        href: "/space/questions",
        icon: ClipboardList,
        title: { zh: "题库", en: "Question Bank" },
        blurb: {
          zh: "跨会话回顾和整理测验题目。",
          en: "Review and organize quiz questions across sessions.",
        },
        unit: { zh: "道题", en: "questions" },
        tile: "bg-emerald-500/10 text-emerald-600 dark:text-emerald-400",
        load: async () => (await listNotebookEntries({ limit: 1 })).total,
      },
      {
        key: "knowledge",
        href: "/knowledge-bases",
        icon: BookOpen,
        title: { zh: "知识中心", en: "Knowledge Center" },
        blurb: {
          zh: "管理知识库与检索引擎。",
          en: "Manage knowledge bases and retrieval engines.",
        },
        unit: { zh: "个知识库", en: "knowledge bases" },
        tile: "bg-blue-500/10 text-blue-600 dark:text-blue-400",
        load: async () => (await listKnowledgeBases({ library: true })).length,
      },
    ],
  },
  {
    label: { zh: "更多项目", en: "More Projects" },
    items: [
      {
        key: "whisper",
        href: "/whisper",
        icon: Ear,
        title: { zh: "密语", en: "Whisper" },
        blurb: {
          zh: "双席位咨询练习房间：督导只对受训者耳语。",
          en: "Dual-seat practice room — the supervisor whispers to the trainee only.",
        },
        tile: "bg-fuchsia-500/10 text-fuchsia-600 dark:text-fuchsia-400",
        credit: "alanguan73",
        // Served by the out-of-tree psych-academy plugin, not by this repo.
        requiresCapability: "whisper_visitor",
      },
    ],
  },
];

/**
 * Account-level: the agents, presets, playbooks, connectors and memory that
 * travel with the learner into every workspace. The sidebar gives these their
 * own shelf, apart from the workspace's materials above.
 */
export const PERSONALIZATION_GROUPS: DashboardGroup[] = [
  {
    label: { zh: "个性化", en: "Personalization" },
    items: [
      {
        key: "agents",
        href: "/agents",
        icon: Bot,
        title: { zh: "子智能体", en: "My Agents" },
        blurb: {
          zh: "连接本机或远程的智能体，在对话中随时请教。",
          en: "Connect local or remote agents and consult them from any chat.",
        },
        unit: { zh: "个智能体", en: "agents" },
        tile: "bg-slate-500/10 text-slate-600 dark:text-slate-300",
        load: async () => (await listSubagentConnections()).length,
      },
      {
        key: "personas",
        href: "/space/personas",
        icon: UserRound,
        title: { zh: "Personas", en: "Personas" },
        blurb: {
          zh: "可在每轮对话中套用的行为预设。",
          en: "Behavior presets you can apply per chat turn.",
        },
        unit: { zh: "个预设", en: "personas" },
        tile: "bg-rose-500/10 text-rose-600 dark:text-rose-400",
        load: async () => (await listPersonas()).length,
      },
      {
        key: "skills",
        href: "/space/skills",
        icon: Wand2,
        title: { zh: "技能", en: "Skills" },
        blurb: {
          zh: "模型按需读取的能力手册。",
          en: "Capability playbooks the model reads on demand.",
        },
        unit: { zh: "个技能", en: "skills" },
        tile: "bg-indigo-500/10 text-indigo-600 dark:text-indigo-400",
        load: async () => (await listSkills()).length,
      },
      {
        key: "mcp",
        href: "/space/mcp",
        icon: Plug,
        title: { zh: "MCP 服务", en: "MCP Services" },
        blurb: {
          zh: "连接托管 MCP 服务，把它们的工具带进对话。",
          en: "Connect hosted MCP services and bring their tools into chat.",
        },
        unit: { zh: "个服务", en: "services" },
        tile: "bg-blue-500/10 text-blue-600 dark:text-blue-400",
        // The account's own servers only: the deployment's are shown on the page
        // but are not this reader's to count.
        load: async () =>
          Object.keys((await loadMcpSurface(SPACE_MCP_SURFACE)).servers).length,
      },
      {
        key: "cli_apps",
        href: "/space/cli-apps",
        icon: Terminal,
        title: { zh: "CLI 应用", en: "CLI Apps" },
        blurb: {
          zh: "来自 CLI-Anything 目录的命令行工具，启用后对话可直接调用。",
          en: "Command-line tools from the CLI-Anything catalog, callable from chat.",
        },
        unit: { zh: "个应用", en: "apps" },
        tile: "bg-violet-500/10 text-violet-600 dark:text-violet-400",
        // What this reader can actually use, not what the deployment installed:
        // an app they were not granted is visible on the page but is not theirs.
        load: async () =>
          (await getCliApps()).apps.filter((app) => app.granted && app.enabled)
            .length,
      },
      {
        key: "memory",
        href: "/memory",
        icon: Brain,
        title: { zh: "记忆", en: "Memory" },
        blurb: {
          zh: "查看与整理导师记住的偏好和学习经历。",
          en: "Review what your tutor remembers about you.",
        },
        tile: "bg-rose-500/10 text-rose-600 dark:text-rose-400",
      },
    ],
  },
];

export const ALL_ITEMS = [
  ...DASHBOARD_GROUPS,
  ...PERSONALIZATION_GROUPS,
].flatMap((g) => g.items);

/**
 * The groups to render, given what the backend can actually serve.
 *
 * `isAvailable` is null while the probe is in flight: gated tiles stay hidden
 * until then, so a surface whose capability was never installed does not flash
 * into view and out again — an ungated tile is never affected. A group left
 * with no tiles is dropped along with its heading, or "More Projects" would
 * render as a title over nothing (#963).
 */
export function visibleGroups(
  groups: DashboardGroup[],
  isAvailable: ((name: string) => boolean) | null,
): DashboardGroup[] {
  return groups
    .map((group) => ({
      ...group,
      items: group.items.filter(
        (item) =>
          !item.requiresCapability ||
          (isAvailable?.(item.requiresCapability) ?? false),
      ),
    }))
    .filter((group) => group.items.length > 0);
}
