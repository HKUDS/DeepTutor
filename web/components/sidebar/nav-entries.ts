import {
  BookOpen,
  BookText,
  Bot,
  Brain,
  HeartHandshake,
  House,
  LayoutGrid,
  Library,
  PenLine,
  Route,
  Settings,
  type LucideIcon,
} from "lucide-react";

import type { Capability } from "@/lib/capability-routes";

export interface NavEntry {
  href: string;
  label: string;
  icon: LucideIcon;
  tooltipKey?: string;
  /** Model capability this feature needs; locked when the user lacks it. */
  requires?: Capability;
}

/**
 * The workspace features, in the order they ship in.
 *
 * This is the *default* arrangement, not the rendered one — a learner can
 * reorder these and fold the ones they don't use into "More"
 * (``lib/sidebar-layout.ts``). Adding an entry here places it for everyone,
 * including people who have already arranged their sidebar: it arrives next to
 * the neighbour it follows below rather than at the bottom of their list.
 */
export const PRIMARY_NAV: NavEntry[] = [
  {
    href: "/chat",
    label: "Home",
    icon: House,
    tooltipKey: "Home tooltip",
    requires: "llm",
  },
  {
    href: "/partners",
    label: "Partners",
    icon: HeartHandshake,
    tooltipKey: "Partners tooltip",
    requires: "llm",
  },
  {
    // My Agents is its own top-level feature (pulled out of the Learning
    // Space): connect a live local Claude Code / Codex to consult in chat,
    // and manage imported agent conversations. Ungated — managing connections
    // and imports needs no per-user model grant.
    href: "/agents",
    label: "My Agents",
    icon: Bot,
    tooltipKey: "Agents tooltip",
  },
  {
    href: "/co-writer",
    label: "Co-Writer",
    icon: PenLine,
    tooltipKey: "Co-Writer tooltip",
    requires: "llm",
  },
  {
    href: "/books",
    label: "Book",
    icon: Library,
    tooltipKey: "Book tooltip",
    requires: "llm",
  },
  // Courses nav entry temporarily hidden pending further product work.
  // The route and its data are untouched — only this entry point is gone.
  {
    href: "/mastery",
    label: "Mastery Path",
    icon: Route,
    tooltipKey: "Learn through a living mastery map",
    requires: "llm",
  },
  {
    href: "/reading",
    label: "Immersive Reading",
    icon: BookText,
    tooltipKey: "Immersive Reading tooltip",
    requires: "llm",
  },
  {
    href: "/space",
    label: "Learning Space",
    icon: LayoutGrid,
    tooltipKey: "Space tooltip",
  },
  {
    // Memory and Knowledge Center are consoles rather than daily workspaces.
    // They ship visible, but a multi-user deployment can fold them into More
    // immediately to leave more room for the conversation list.
    href: "/memory",
    label: "Memory",
    icon: Brain,
    tooltipKey: "Memory tooltip",
  },
  {
    href: "/knowledge-bases",
    label: "Knowledge Center",
    icon: BookOpen,
    tooltipKey: "Knowledge tooltip",
  },
];

/** Consoles that sit under the chat history. Not arrangeable: Settings has to
 *  stay findable, and a console nobody folds away is one less thing to explain. */
export const SECONDARY_NAV: NavEntry[] = [
  { href: "/settings", label: "Settings", icon: Settings },
];

export const PRIMARY_NAV_HREFS = PRIMARY_NAV.map((entry) => entry.href);

/** Fixed consoles that may default into More when auth creates the crowded
 *  multi-user shell, while Settings stays discoverable below the history. */
export const MULTI_USER_DEFAULT_COLLAPSED_NAV_HREFS = [
  "/memory",
  "/knowledge-bases",
] as const;

export const NAV_BY_HREF = new Map(
  [...PRIMARY_NAV, ...SECONDARY_NAV].map((entry) => [entry.href, entry]),
);

export function isNavActive(pathname: string, href: string) {
  if (href === "/space") {
    return (
      (pathname === "/space" || pathname.startsWith("/space/")) &&
      !pathname.startsWith("/mastery")
    );
  }
  return pathname === href || pathname.startsWith(`${href}/`);
}
