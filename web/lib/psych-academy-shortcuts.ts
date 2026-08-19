/**
 * Psych Academy workspace shortcuts — shared between Home empty state and
 * launch-URL builders. Dedicated routes own ask_user / crisis UX; `/home`
 * query params redirect there (see `psychAcademyDedicatedRoute`).
 */

import type { LucideIcon } from "lucide-react";
import {
  ClipboardList,
  Dumbbell,
  FlaskConical,
  GraduationCap,
  HeartHandshake,
} from "lucide-react";

export type PsychAcademySurface =
  | "counsel"
  | "sim"
  | "distill"
  | "train"
  | "intake";

export type PsychAcademyShortcut = {
  id: PsychAcademySurface;
  href: string;
  labelKey: string;
  tooltipKey: string;
  icon: LucideIcon;
};

/** Capability values that should open a dedicated academy page instead of Home chat. */
const DEDICATED_CAPABILITY_ROUTES: Record<string, string> = {
  counsel: "/counsel",
  counsel_sim: "/sim",
  distill: "/distill",
};

export const PSYCH_ACADEMY_SHORTCUTS: PsychAcademyShortcut[] = [
  {
    id: "counsel",
    href: "/counsel",
    labelKey: "Counsel",
    tooltipKey: "Counsel tooltip",
    icon: HeartHandshake,
  },
  {
    id: "sim",
    href: "/sim",
    labelKey: "Sim",
    tooltipKey: "Sim tooltip",
    icon: GraduationCap,
  },
  {
    id: "distill",
    href: "/distill",
    labelKey: "Distill",
    tooltipKey: "Distill tooltip",
    icon: FlaskConical,
  },
  {
    id: "train",
    href: "/train",
    labelKey: "Train",
    tooltipKey: "Train tooltip",
    icon: Dumbbell,
  },
  {
    id: "intake",
    href: "/intake",
    labelKey: "Intake",
    tooltipKey: "Intake tooltip",
    icon: ClipboardList,
  },
];

/** If this capability belongs on a dedicated academy page, return its route. */
export function psychAcademyDedicatedRoute(
  capability: string | null | undefined,
): string | null {
  if (!capability) return null;
  const key = capability.trim();
  return DEDICATED_CAPABILITY_ROUTES[key] ?? null;
}

export function psychAcademyPageHref(surface: PsychAcademySurface): string {
  const row = PSYCH_ACADEMY_SHORTCUTS.find((s) => s.id === surface);
  return row?.href ?? "/home";
}
