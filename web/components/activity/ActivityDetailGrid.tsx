"use client";

import { Fragment, type ReactNode } from "react";

/** One labelled line of detail: `query`, `result`, an argument name. */
export interface DetailRow {
  key: string;
  value: ReactNode;
  /** Mono face — for queries, paths, commands, raw values. */
  mono?: boolean;
}

/**
 * The second level's layout: a label/value grid on one shared left edge.
 *
 * This is deliberately data-agnostic. Two different trace pipelines feed it
 * (chat's `StreamEvent` groups and the co-writer's own tool records), and
 * before this they each rendered their own version of the same thing —
 * arguments as a pretty-printed JSON block, results in a separately ruled
 * box, both with `→`/`✓` prefixes. Most of that area went to braces, quotes
 * and injected paths rather than to the two values a reader wants.
 *
 * Callers decide *what* the rows are; this decides how they look, so the two
 * pipelines cannot drift apart again.
 */
export function ActivityDetailGrid({
  rows,
  className = "",
}: {
  rows: DetailRow[];
  className?: string;
}) {
  if (!rows.length) return null;

  return (
    <dl
      className={`grid grid-cols-[auto_1fr] gap-x-3 gap-y-1.5 ${className}`}
    >
      {rows.map(({ key, value, mono }) => (
        <Fragment key={key}>
          <dt className="pt-[1px] font-mono text-[10.5px] not-italic leading-[1.7] text-[var(--muted-foreground)]/40">
            {key}
          </dt>
          <dd
            className={`min-w-0 break-words ${
              mono
                ? "font-mono text-[11px] not-italic leading-[1.55] text-[var(--muted-foreground)]/85"
                : "leading-[1.6]"
            }`}
          >
            {value}
          </dd>
        </Fragment>
      ))}
    </dl>
  );
}

/**
 * Is this argument runtime plumbing rather than the caller's intent?
 *
 * The runtime injects workspace locations into most tool calls
 * (`output_dir`, `cwd`, …). They mean nothing to a reader — nobody opens a
 * trace to learn which turn directory a search wrote into — and they are long
 * enough to bury the one argument that does matter. Keyed on the value too,
 * so a `path` argument holding a URL or an id (the user's actual subject)
 * still shows.
 */
export function isPlumbingArg(key: string, value: unknown): boolean {
  if (typeof value !== "string") return false;
  if (!/(^|_)(dir|dest|output|workspace|cwd|root)(_|$)/i.test(key)) {
    return false;
  }
  return value.startsWith("/") || /^[A-Za-z]:[\\/]/.test(value);
}

/** Turn a tool's argument object into detail rows, dropping plumbing. */
export function argumentRows(args: unknown): DetailRow[] {
  if (!args || typeof args !== "object" || Array.isArray(args)) return [];
  return Object.entries(args as Record<string, unknown>)
    .filter(([key, value]) => !isPlumbingArg(key, value))
    .map(([key, value]) => ({
      key,
      value:
        typeof value === "string"
          ? value
          : value == null
            ? String(value)
            : typeof value === "object"
              ? JSON.stringify(value)
              : String(value),
      mono: true,
    }));
}
