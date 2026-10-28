import dynamic from "next/dynamic";
import type { UiLayoutSlots } from "../types";
import { ClassicSidebarShell } from "./ClassicSidebarShell";

/**
 * The UI as it ships on dev, frozen. Every file in this folder is a snapshot;
 * fixes that must reach classic users go into the shared code it renders.
 */
export const classicSlots: UiLayoutSlots = {
  SidebarShell: ClassicSidebarShell,
  PageBar: null,
  LearningHome: dynamic(() =>
    import("./ClassicLearningDashboard").then((module) => module.ClassicLearningDashboard),
  ),
};
