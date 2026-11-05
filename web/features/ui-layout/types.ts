import type { ComponentType } from "react";
import type { SidebarShellProps } from "./classic/ClassicSidebarShell";

export type { SidebarShellProps };

/*
 * Everything that differs between the two product UIs, in three layers:
 *
 * - Slots  (`slots.tsx`)  — components that differ wholesale.
 * - Tokens (`tokens.ts`)  — copy that differs; a leaf, safe to import anywhere.
 * - CSS    (`<variant>/*.css`) — custom properties on <html data-ui-layout>.
 *
 * Shared code renders a slot or reads a token and never asks which layout is
 * active. A difference that is not expressed here does not exist: to change
 * something for one UI only, add a slot or token, or fork the component into
 * that variant's folder — never branch on the layout inside a shared component.
 */

export interface UiLayoutSlots {
  /** Workspace + utility sidebar. Receives what both route groups pass. */
  SidebarShell: ComponentType<SidebarShellProps>;
  /** `/learning` page body. */
  LearningHome: ComponentType;
  /** Location bar above section index pages, or none. */
  PageBar: ComponentType | null;
}

export interface UiLayoutTokens {
  /** i18n keys for copy the two UIs name differently. */
  labels: {
    /** The /space hub and its back links. */
    space: string;
    /** The /learning hub and its back links. */
    learning: string;
    /** The default chat capability in the mode picker. */
    defaultCapability: string;
  };
}
