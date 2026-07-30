/**
 * Naming a tool call that came from an external provider.
 *
 * The pure half of the activity row's tool vocabulary — the part with actual
 * logic, kept out of the component so it can be tested directly. Icon and verb
 * assembly stays in `TracePanels`, which is where the glyphs live.
 *
 * The provider identity is *read* from trace metadata (`tool_source` /
 * `tool_provider`, stamped by the tool dispatcher from the tool object itself),
 * never recovered by parsing the tool name. `mcp_<server>_<tool>` has no
 * unambiguous split once a server's own name contains an underscore, and
 * guessing wrong renames the tool in front of the reader.
 */

/** Which external provider a tool belongs to. `source` is `"mcp"` or `"cli"`. */
export type ToolProvider = { source: string; id: string };

/**
 * The bare tool name inside an MCP server, e.g. `WolframAlpha`.
 *
 * Stripped with the server id rather than by splitting on underscores. Falls
 * back to the full name when the prefix does not match, so a renamed server or
 * an unexpected shape degrades to something true rather than something mangled.
 */
export function mcpToolLabel(toolName: string, serverId: string): string {
  if (!serverId) return toolName;
  const prefix = `mcp_${serverId}_`;
  return toolName.startsWith(prefix) ? toolName.slice(prefix.length) : toolName;
}

/**
 * A CLI app invocation's arguments, as one display line.
 *
 * They arrive as an array precisely because no shell parses them, so this joins
 * for reading only — nothing downstream splits it again. An argument containing
 * a space is therefore shown as-is: this is a label, not a command to copy.
 */
export function cliArgvLabel(args: unknown): string {
  if (Array.isArray(args)) return args.map((item) => String(item)).join(" ");
  return typeof args === "string" ? args.trim() : "";
}

/**
 * Clip *text* to *max* characters on a word boundary where one is close by.
 *
 * Progress lines and command lines both land in the row's trailing slot, which
 * is one line wide; a mid-word cut reads as corruption rather than truncation.
 */
export function clipLabel(text: string, max: number): string {
  const value = text.trim();
  if (value.length <= max) return value;
  const cut = value.slice(0, max);
  const lastSpace = cut.lastIndexOf(" ");
  return `${lastSpace > max * 0.6 ? cut.slice(0, lastSpace) : cut}…`;
}

/** A provider's own progress line, formatted for the row's trailing slot. */
export function formatProgressLabel(message: string, max = 64): string {
  return clipLabel(message, max);
}

/** Which glyph family a provider row uses. Resolved to a component by the view. */
export type ProviderGlyph = "link" | "command";

/** How one activity row reads: leading glyph, action verb, trailing detail. */
export type ProviderRow = {
  glyph: ProviderGlyph;
  /** Already translated. */
  verb: string;
  /** The trailing detail, or `null` for none. */
  chip: string | null;
  /** Render the chip in a mono face. */
  mono: boolean;
};

/**
 * How to label a tool call that came from an MCP server or a CLI app, or `null`
 * when it is neither.
 *
 * Returned as data — a glyph *name*, not a component — so the whole decision is
 * testable without rendering, while the hand-drawn marks stay in the view.
 *
 * Both cases put the thing the reader recognises in the verb (the service, the
 * app) and the specific action in the trailing detail. Without this the row
 * falls through to title-casing a generated name: `mcp_wolfram_WolframAlpha`
 * becomes "Mcp Wolfram Wolframalpha", which names neither.
 */
export function describeProviderTool(
  toolName: string,
  args: Record<string, unknown> | undefined,
  provider: ToolProvider | null | undefined,
  t: (key: string, opts?: Record<string, unknown>) => string,
): ProviderRow | null {
  if (!provider?.source) return null;
  if (provider.source === "mcp") {
    return {
      glyph: "link",
      verb: t("Using {{service}}", { service: provider.id || toolName }),
      chip: mcpToolLabel(toolName, provider.id) || null,
      mono: true,
    };
  }
  if (provider.source === "cli") {
    return {
      glyph: "command",
      verb: t("Running {{app}}", { app: provider.id || toolName }),
      // The arguments *are* the command. They arrive as an array precisely
      // because no shell parses them, so this is a label and nothing splits it
      // again.
      chip: clipLabel(cliArgvLabel(args?.args), 48) || null,
      mono: true,
    };
  }
  // A provider kind this build does not know about. Better an honest generic row
  // than a confident wrong one.
  return null;
}
