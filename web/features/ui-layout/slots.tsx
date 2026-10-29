"use client";

import { useUiLayout } from "@/hooks/useUiLayout";
import type { UiLayout } from "@/lib/ui-layout";
import { classicSlots } from "./classic";
import { modernSlots } from "./modern";
import type { SidebarShellProps, UiLayoutSlots } from "./types";

const UI_LAYOUT_SLOTS: Record<UiLayout, UiLayoutSlots> = {
  classic: classicSlots,
  modern: modernSlots,
};

function useSlots(): UiLayoutSlots {
  return UI_LAYOUT_SLOTS[useUiLayout()];
}

// Shared code renders these and never the variants' components directly.

export function LayoutSidebarShell(props: SidebarShellProps) {
  const { SidebarShell } = useSlots();
  return <SidebarShell {...props} />;
}

export function LayoutPageBar() {
  const { PageBar } = useSlots();
  return PageBar ? <PageBar /> : null;
}

export function LayoutLearningHome() {
  const { LearningHome } = useSlots();
  return <LearningHome />;
}
