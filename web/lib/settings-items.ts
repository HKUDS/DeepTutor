"use client";

import {
  Activity,
  BookMarked,
  Brain,
  Database,
  HeartPulse,
  Network,
  Palette,
  Plug,
  Search,
  SlidersHorizontal,
  Wrench,
  type LucideIcon,
} from "lucide-react";

export type SettingsItemKey =
  | "appearance"
  | "status"
  | "network"
  | "tools"
  | "mcp"
  | "llm"
  | "embedding"
  | "search"
  | "heartbeat"
  | "memory"
  | "capabilities";

export interface SettingsItem {
  key: SettingsItemKey;
  href: string;
  label: string;
  description: string;
  icon: LucideIcon;
}

export const SETTINGS_ITEMS: SettingsItem[] = [
  {
    key: "appearance",
    href: "/settings/appearance",
    label: "Appearance",
    description: "Theme and language preferences.",
    icon: Palette,
  },
  {
    key: "status",
    href: "/settings/status",
    label: "Status",
    description: "Runtime status for backend and configured services.",
    icon: Activity,
  },
  {
    key: "network",
    href: "/settings/network",
    label: "Network",
    description: "Ports, browser API base, and CORS origins.",
    icon: Network,
  },
  {
    key: "llm",
    href: "/settings/llm",
    label: "LLM",
    description: "Language model providers and active profile.",
    icon: Brain,
  },
  {
    key: "embedding",
    href: "/settings/embedding",
    label: "Embedding",
    description: "Embedding model providers and dimensions.",
    icon: Database,
  },
  {
    key: "search",
    href: "/settings/search",
    label: "Search",
    description: "Web search providers.",
    icon: Search,
  },
  {
    key: "heartbeat",
    href: "/settings/heartbeat",
    label: "Heartbeat",
    description: "Heartbeat interval and model configuration.",
    icon: HeartPulse,
  },
  {
    key: "capabilities",
    href: "/settings/capabilities",
    label: "Capabilities",
    description: "Per-capability LLM parameters and runtime knobs.",
    icon: SlidersHorizontal,
  },
  {
    key: "memory",
    href: "/settings/memory",
    label: "Memory",
    description: "Chunking, LLM-budget, dedup, and reference policies.",
    icon: BookMarked,
  },
  {
    key: "mcp",
    href: "/settings/mcp",
    label: "MCP servers",
    description: "External MCP servers (coming soon).",
    icon: Plug,
  },
  {
    key: "tools",
    href: "/settings/tools",
    label: "Tools",
    description: "Built-in tools the chat agent can invoke.",
    icon: Wrench,
  },
];

export const SETTINGS_DEFAULT_HREF = "/settings/appearance";
