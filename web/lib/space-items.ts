"use client";

import {
  Bot,
  ClipboardList,
  History,
  NotebookPen,
  UserRound,
  Wand2,
  type LucideIcon,
} from "lucide-react";

export type SpaceItemKey =
  | "chat_history"
  | "agents"
  | "notebooks"
  | "question_bank"
  | "personas"
  | "skills";

export type SpaceMemoryFile = "summary" | "profile";

export interface SpaceItem {
  key: SpaceItemKey;
  href: string;
  label: string;
  description: string;
  icon: LucideIcon;
}

export const SPACE_ITEMS: SpaceItem[] = [
  {
    key: "chat_history",
    href: "/space/chat-history",
    label: "Chat History",
    description: "Review and reopen previous conversations.",
    icon: History,
  },
  {
    key: "agents",
    href: "/space/agents",
    label: "My Agents",
    description: "Chat with imported Claude Code and Codex agents.",
    icon: Bot,
  },
  {
    key: "notebooks",
    href: "/space/notebooks",
    label: "Notebooks",
    description:
      "Organize saved outputs from chat, research, Co-Writer, and more.",
    icon: NotebookPen,
  },
  {
    key: "question_bank",
    href: "/space/questions",
    label: "Question Bank",
    description: "Review and organize quiz questions across sessions.",
    icon: ClipboardList,
  },
  {
    key: "personas",
    href: "/space/personas",
    label: "Personas",
    description: "Behavior presets you can apply per chat turn.",
    icon: UserRound,
  },
  {
    key: "skills",
    href: "/space/skills",
    label: "Skills",
    description: "Capability playbooks the model reads on demand.",
    icon: Wand2,
  },
];
