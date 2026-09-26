"use client";

import type { LucideIcon } from "lucide-react";
import { createContext, useContext, useEffect } from "react";

/**
 * One entry in the workspace's single ⋯ menu.
 *
 * The reader, the companion and the collection each had a ⋯ of their own —
 * three identical icons a hand's width apart, and a learner looking for
 * "export" had to open all three. The panels still own their actions; they
 * hand them up here, and the top bar lists them in one place.
 */
export interface WorkspaceMenuItem {
  key: string;
  icon: LucideIcon;
  label: string;
  hint?: string;
  /** A setting that is on (shown with a check), not an action. */
  active?: boolean;
  disabled?: boolean;
  spinning?: boolean;
  onSelect: () => void;
}

export type WorkspaceMenuSection = "material" | "conversation";

export interface WorkspaceMenuHost {
  register: (
    section: WorkspaceMenuSection,
    items: WorkspaceMenuItem[] | null,
  ) => void;
}

export const WorkspaceMenuContext = createContext<WorkspaceMenuHost | null>(
  null,
);

/**
 * Publish a panel's menu items to the workspace's ⋯ menu.
 *
 * Returns whether a workspace is listening: a panel rendered on its own keeps
 * its own ⋯, since nothing else would show these actions. `items` must be
 * memoised, or every render re-registers and re-renders the workspace.
 */
export function useWorkspaceMenuSection(
  section: WorkspaceMenuSection,
  items: WorkspaceMenuItem[] | null,
): boolean {
  const host = useContext(WorkspaceMenuContext);
  useEffect(() => {
    if (!host) return;
    host.register(section, items);
  }, [host, items, section]);
  useEffect(() => {
    if (!host) return;
    return () => host.register(section, null);
  }, [host, section]);
  return host !== null;
}
