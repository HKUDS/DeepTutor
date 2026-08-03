/// <reference path="./react-syntax-highlighter-prism-themes.d.ts" />

import type { CSSProperties } from "react";

type PrismTheme = {
  [key: string]: CSSProperties;
};

// Individual theme imports - using direct imports, not barrel imports
import oneDark from "react-syntax-highlighter/dist/esm/styles/prism/one-dark";
import a11yDark from "react-syntax-highlighter/dist/esm/styles/prism/a11y-dark";
import a11yOneLight from "react-syntax-highlighter/dist/esm/styles/prism/a11y-one-light";
import atomDark from "react-syntax-highlighter/dist/esm/styles/prism/atom-dark";
import base16AteliersulphurpoolLight from "react-syntax-highlighter/dist/esm/styles/prism/base16-ateliersulphurpool.light";
import cb from "react-syntax-highlighter/dist/esm/styles/prism/cb";
import coldarkCold from "react-syntax-highlighter/dist/esm/styles/prism/coldark-cold";
import coldarkDark from "react-syntax-highlighter/dist/esm/styles/prism/coldark-dark";
import coyWithoutShadows from "react-syntax-highlighter/dist/esm/styles/prism/coy-without-shadows";
import coy from "react-syntax-highlighter/dist/esm/styles/prism/coy";
import darcula from "react-syntax-highlighter/dist/esm/styles/prism/darcula";
import dark from "react-syntax-highlighter/dist/esm/styles/prism/dark";
import dracula from "react-syntax-highlighter/dist/esm/styles/prism/dracula";
import duotoneDark from "react-syntax-highlighter/dist/esm/styles/prism/duotone-dark";
import duotoneEarth from "react-syntax-highlighter/dist/esm/styles/prism/duotone-earth";
import duotoneForest from "react-syntax-highlighter/dist/esm/styles/prism/duotone-forest";
import duotoneLight from "react-syntax-highlighter/dist/esm/styles/prism/duotone-light";
import duotoneSea from "react-syntax-highlighter/dist/esm/styles/prism/duotone-sea";
import duotoneSpace from "react-syntax-highlighter/dist/esm/styles/prism/duotone-space";
import funky from "react-syntax-highlighter/dist/esm/styles/prism/funky";
import ghcolors from "react-syntax-highlighter/dist/esm/styles/prism/ghcolors";
import gruvboxDark from "react-syntax-highlighter/dist/esm/styles/prism/gruvbox-dark";
import gruvboxLight from "react-syntax-highlighter/dist/esm/styles/prism/gruvbox-light";
import holiTheme from "react-syntax-highlighter/dist/esm/styles/prism/holi-theme";
import hopscotch from "react-syntax-highlighter/dist/esm/styles/prism/hopscotch";
import lucario from "react-syntax-highlighter/dist/esm/styles/prism/lucario";
import materialDark from "react-syntax-highlighter/dist/esm/styles/prism/material-dark";
import materialLight from "react-syntax-highlighter/dist/esm/styles/prism/material-light";
import materialOceanic from "react-syntax-highlighter/dist/esm/styles/prism/material-oceanic";
import nightOwl from "react-syntax-highlighter/dist/esm/styles/prism/night-owl";
import nord from "react-syntax-highlighter/dist/esm/styles/prism/nord";
import okaidia from "react-syntax-highlighter/dist/esm/styles/prism/okaidia";
import oneLight from "react-syntax-highlighter/dist/esm/styles/prism/one-light";
import pojoaque from "react-syntax-highlighter/dist/esm/styles/prism/pojoaque";
import prism from "react-syntax-highlighter/dist/esm/styles/prism/prism";
import shadesOfPurple from "react-syntax-highlighter/dist/esm/styles/prism/shades-of-purple";
import solarizedDarkAtom from "react-syntax-highlighter/dist/esm/styles/prism/solarized-dark-atom";
import solarizedlight from "react-syntax-highlighter/dist/esm/styles/prism/solarizedlight";
import synthwave84 from "react-syntax-highlighter/dist/esm/styles/prism/synthwave84";
import tomorrow from "react-syntax-highlighter/dist/esm/styles/prism/tomorrow";
import twilight from "react-syntax-highlighter/dist/esm/styles/prism/twilight";
import vsDark from "react-syntax-highlighter/dist/esm/styles/prism/vs-dark";
import vs from "react-syntax-highlighter/dist/esm/styles/prism/vs";
import vscDarkPlus from "react-syntax-highlighter/dist/esm/styles/prism/vsc-dark-plus";
import xonokai from "react-syntax-highlighter/dist/esm/styles/prism/xonokai";
import zTouch from "react-syntax-highlighter/dist/esm/styles/prism/z-touch";

/** Saved ID for a code block theme. Used in storage and as a stable identifier.
 *
 * These are camelCase versions of the Prism file names (e.g., "one-dark.js" → "oneDark").
 * They remain stable across updates and are safe to persist.
 */
export type CodeBlockThemeId =
  | "oneDark"
  | "a11yDark"
  | "a11yOneLight"
  | "atomDark"
  | "base16AteliersulphurpoolLight"
  | "cb"
  | "coldarkCold"
  | "coldarkDark"
  | "coyWithoutShadows"
  | "coy"
  | "darcula"
  | "dark"
  | "dracula"
  | "duotoneDark"
  | "duotoneEarth"
  | "duotoneForest"
  | "duotoneLight"
  | "duotoneSea"
  | "duotoneSpace"
  | "funky"
  | "ghcolors"
  | "gruvboxDark"
  | "gruvboxLight"
  | "holiTheme"
  | "hopscotch"
  | "lucario"
  | "materialDark"
  | "materialLight"
  | "materialOceanic"
  | "nightOwl"
  | "nord"
  | "okaidia"
  | "oneLight"
  | "pojoaque"
  | "prism"
  | "shadesOfPurple"
  | "solarizedDarkAtom"
  | "solarizedlight"
  | "synthwave84"
  | "tomorrow"
  | "twilight"
  | "vsDark"
  | "vs"
  | "vscDarkPlus"
  | "xonokai"
  | "zTouch";

/** A single Prism theme option with display label and the style object. */
export interface CodeBlockThemeOption {
  /** Stable camelCase ID used for storage and lookup. */
  id: CodeBlockThemeId;
  /** Human-readable label (e.g., "One Dark", "VSC Dark Plus"). */
  label: string;
  /** The Prism style object for syntax highlighting. */
  style: PrismTheme;
}

/** All installed Prism themes available as selectable options. */
export const CODE_BLOCK_THEME_OPTIONS: readonly CodeBlockThemeOption[] = [
  { id: "a11yDark", label: "A11Y Dark", style: a11yDark },
  { id: "a11yOneLight", label: "A11Y One Light", style: a11yOneLight },
  { id: "atomDark", label: "Atom Dark", style: atomDark },
  {
    id: "base16AteliersulphurpoolLight",
    label: "Base16 Atelier Sulphurpool Light",
    style: base16AteliersulphurpoolLight,
  },
  { id: "cb", label: "CB", style: cb },
  { id: "coldarkCold", label: "Coldark Cold", style: coldarkCold },
  { id: "coldarkDark", label: "Coldark Dark", style: coldarkDark },
  {
    id: "coyWithoutShadows",
    label: "Coy Without Shadows",
    style: coyWithoutShadows,
  },
  { id: "coy", label: "Coy", style: coy },
  { id: "darcula", label: "Darcula", style: darcula },
  { id: "dark", label: "Dark", style: dark },
  { id: "dracula", label: "Dracula", style: dracula },
  { id: "duotoneDark", label: "Duotone Dark", style: duotoneDark },
  { id: "duotoneEarth", label: "Duotone Earth", style: duotoneEarth },
  { id: "duotoneForest", label: "Duotone Forest", style: duotoneForest },
  { id: "duotoneLight", label: "Duotone Light", style: duotoneLight },
  { id: "duotoneSea", label: "Duotone Sea", style: duotoneSea },
  { id: "duotoneSpace", label: "Duotone Space", style: duotoneSpace },
  { id: "funky", label: "Funky", style: funky },
  { id: "ghcolors", label: "GH Colors", style: ghcolors },
  { id: "gruvboxDark", label: "Gruvbox Dark", style: gruvboxDark },
  { id: "gruvboxLight", label: "Gruvbox Light", style: gruvboxLight },
  { id: "holiTheme", label: "Holi Theme", style: holiTheme },
  { id: "hopscotch", label: "Hopscotch", style: hopscotch },
  { id: "lucario", label: "Lucario", style: lucario },
  { id: "materialDark", label: "Material Dark", style: materialDark },
  { id: "materialLight", label: "Material Light", style: materialLight },
  { id: "materialOceanic", label: "Material Oceanic", style: materialOceanic },
  { id: "nightOwl", label: "Night Owl", style: nightOwl },
  { id: "nord", label: "Nord", style: nord },
  { id: "okaidia", label: "Okaidia", style: okaidia },
  { id: "oneDark", label: "One Dark", style: oneDark },
  { id: "oneLight", label: "One Light", style: oneLight },
  { id: "pojoaque", label: "Pojoaque", style: pojoaque },
  { id: "prism", label: "Prism", style: prism },
  { id: "shadesOfPurple", label: "Shades of Purple", style: shadesOfPurple },
  {
    id: "solarizedDarkAtom",
    label: "Solarized Dark Atom",
    style: solarizedDarkAtom,
  },
  { id: "solarizedlight", label: "Solarized Light", style: solarizedlight },
  { id: "synthwave84", label: "Synthwave 84", style: synthwave84 },
  { id: "tomorrow", label: "Tomorrow", style: tomorrow },
  { id: "twilight", label: "Twilight", style: twilight },
  { id: "vsDark", label: "VS Dark", style: vsDark },
  { id: "vs", label: "VS", style: vs },
  { id: "vscDarkPlus", label: "VSC Dark Plus", style: vscDarkPlus },
  { id: "xonokai", label: "Xonokai", style: xonokai },
  { id: "zTouch", label: "Z Touch", style: zTouch },
] as const;

/** The default theme ID when no user preference is set. */
export const DEFAULT_CODE_BLOCK_THEME_ID: CodeBlockThemeId = "oneDark";

/** Get a Prism theme style by ID, falling back to oneDark for invalid IDs. */
export function getCodeBlockTheme(id: string): PrismTheme {
  const option = CODE_BLOCK_THEME_OPTIONS.find((opt) => opt.id === id);
  return option?.style ?? oneDark;
}

/** Extract the background color from a Prism style object.
 *
 * Returns the background color if available, or undefined if not.
 * This is used for theme-derived background styling.
 */
export function getCodeBlockThemeBackground(
  style: PrismTheme,
): string | undefined {
  const preStyle = style['pre[class*="language-"]'];
  if (preStyle && typeof preStyle === "object") {
    const backgroundColor = preStyle.backgroundColor;
    if (typeof backgroundColor === "string") {
      return backgroundColor;
    }
    const background = preStyle.background;
    if (typeof background === "string") {
      return background;
    }
  }
  return undefined;
}
