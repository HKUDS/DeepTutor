import dynamic from "next/dynamic";
import { PageBar } from "@/components/sidebar/PageBar";
import { SidebarShell } from "@/components/sidebar/SidebarShell";
import type { UiLayoutSlots } from "../types";

/** The dt-exp redesign. Its components live where they always have. */
export const modernSlots: UiLayoutSlots = {
  SidebarShell,
  PageBar,
  LearningHome: dynamic(() =>
    import("@/components/learning/LearningDashboard").then((module) => module.LearningDashboard),
  ),
};
