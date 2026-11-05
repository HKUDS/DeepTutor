/**
 * The kinds of artifact create mode can author. A kind is an adapter: the
 * capability, tool, store and router never branch on it (see
 * `deeptutor/services/creations/kinds.py`); this table is the web client's
 * mirror, used by the tray menu, the lead chip, and the draft card.
 */

import { UserRound, Wand2, type LucideIcon } from "lucide-react";

export type CreationKind = "skill" | "persona";

export interface CreationKindDef {
  kind: CreationKind;
  icon: LucideIcon;
  /** i18n key for the kind's own name — reuses the existing "Skill" / "Persona" entries. */
  labelKey: string;
  /** i18n key for the composer placeholder shown while this kind is being authored. */
  placeholderKey: string;
  /** i18n key for the one-line hint shown under the kind in the Create menu. */
  hintKey: string;
  /** i18n key for the draft card's header ("Skill draft" / "Persona draft"). */
  draftHeaderKey: string;
  /** i18n key for the draft card's "manage your X" link label. */
  manageLabelKey: string;
  /** Where an approved draft of this kind can be managed afterwards. */
  href: string;
}

export const CREATE_KINDS: Record<CreationKind, CreationKindDef> = {
  skill: {
    kind: "skill",
    icon: Wand2,
    labelKey: "Skill",
    placeholderKey: "composer.create.placeholder.skill",
    hintKey: "composer.tray.createHintSkill",
    draftHeaderKey: "composer.create.draft.headerSkill",
    manageLabelKey: "composer.create.manageSkills",
    href: "/space/skills",
  },
  persona: {
    kind: "persona",
    icon: UserRound,
    labelKey: "Persona",
    placeholderKey: "composer.create.placeholder.persona",
    hintKey: "composer.tray.createHintPersona",
    draftHeaderKey: "composer.create.draft.headerPersona",
    manageLabelKey: "composer.create.managePersonas",
    href: "/space/personas",
  },
};

export const CREATION_KIND_ORDER: CreationKind[] = ["skill", "persona"];

export function isCreationKind(value: unknown): value is CreationKind {
  return value === "skill" || value === "persona";
}

export function creationKindDef(value: string | null | undefined): CreationKindDef | null {
  return isCreationKind(value) ? CREATE_KINDS[value] : null;
}

/**
 * Lightweight client-side signal for "a draft of this kind was just saved" —
 * same shape as `co-writer-events`/`session-events`: the composer's Skills
 * menu is fetched once per workspace at the shell level, far from wherever a
 * draft card's Approve button fires, so it needs an explicit nudge to refetch
 * rather than reload.
 */
export const CREATIONS_SAVED_EVENT = "deeptutor:creation-saved";

export function notifyCreationSaved(kind: CreationKind): void {
  if (typeof window === "undefined") return;
  window.dispatchEvent(new CustomEvent(CREATIONS_SAVED_EVENT, { detail: { kind } }));
}
