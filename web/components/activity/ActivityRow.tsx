"use client";

import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { ChevronDown } from "lucide-react";

import { StatusDot } from "./StatusDot";
import type { ActivityState } from "./types";

/**
 * A scroll box that sticks to the bottom while work streams into it, and
 * stops sticking the moment the reader scrolls up to read something.
 */
function StickyScroll({
  children,
  stick,
  className,
}: {
  children: ReactNode;
  stick?: boolean;
  className?: string;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const stuckRef = useRef(true);

  useEffect(() => {
    if (!stick || !stuckRef.current) return;
    const el = ref.current;
    if (el) el.scrollTop = el.scrollHeight;
  });

  useEffect(() => {
    if (stick) stuckRef.current = true;
  }, [stick]);

  const onScroll = useCallback(() => {
    const el = ref.current;
    if (!el) return;
    stuckRef.current = el.scrollHeight - el.scrollTop - el.clientHeight < 30;
  }, []);

  return (
    <div ref={ref} onScroll={onScroll} className={className}>
      {children}
    </div>
  );
}

/**
 * One line of activity, optionally hiding a second level.
 *
 * This is the shape every activity surface shares: a status dot in a fixed
 * mark column, a title that names the action, an optional dimmer trailing
 * detail, and — folded away until asked for — the specifics.
 *
 * The two levels are the whole contract. Level one is what you see without
 * doing anything: one line per action, never more. Level two is everything
 * else, and nothing opens it on its own except a caller passing `followOpen`
 * for work the reader is meant to watch happen.
 */
export function ActivityRow({
  state,
  title,
  detail,
  detailMono = false,
  breathing = false,
  clampTitle,
  followOpen = false,
  autoScrollDetail = false,
  children,
  className = "",
}: {
  state: ActivityState;
  /** Names the action. Kept on one line unless `clampTitle` says otherwise. */
  title: ReactNode;
  /** The concrete thing this touched — a query, a file, a chapter. */
  detail?: ReactNode;
  /** Render the detail in a mono face (paths, commands, queries). */
  detailMono?: boolean;
  /** Breathe the title while the work is live. */
  breathing?: boolean;
  /** For rows whose title is prose rather than a label. */
  clampTitle?: 2 | 3;
  /**
   * Open the second level while this holds, until the reader decides
   * otherwise — for work worth watching live, which should then fold itself
   * away once it settles. Their click wins from then on.
   */
  followOpen?: boolean;
  /** Keep the second level pinned to its newest line while it streams. */
  autoScrollDetail?: boolean;
  /** The second level. Its presence is what makes the row expandable. */
  children?: ReactNode;
  className?: string;
}) {
  const [userOpen, setUserOpen] = useState<boolean | null>(null);
  const expandable = Boolean(children);
  const open = expandable && (userOpen ?? followOpen);

  return (
    <div className={`group/row ${className}`}>
      <div
        role={expandable ? "button" : undefined}
        aria-expanded={expandable ? open : undefined}
        onClick={expandable ? () => setUserOpen(!open) : undefined}
        className={`flex items-start gap-2.5 py-1 text-[14px] leading-[1.45] text-[var(--muted-foreground)] ${
          expandable
            ? "cursor-pointer transition-colors hover:text-[var(--foreground)]"
            : ""
        }`}
      >
        <StatusDot state={state} className="mt-[3px]" />
        <div className="min-w-0 flex-1">
          {detail ? (
            // Action and artifact share one line: the title anchors (never
            // truncates, always legible) while the dimmer detail trails and
            // ellipsizes. The colour drop is the only separator — no pill.
            <div className="flex items-baseline gap-2">
              {/* The action and the thing it acted on differ in weight, not
                  just in shade. Colour alone was doing all the separating,
                  which at this size read as one continuous string — the eye
                  needs a stroke difference to find where the verb ends. The
                  action never truncates; the content trails and ellipsizes. */}
              <span
                className={`shrink-0 font-medium ${breathing ? "dt-breathing-text" : ""}`}
              >
                {title}
              </span>
              <span
                className={`min-w-0 truncate font-normal text-[var(--muted-foreground)]/50 ${
                  detailMono ? "font-mono text-[12.5px]" : ""
                }`}
              >
                {detail}
              </span>
            </div>
          ) : (
            // Same weight as the two-part case: a row with nothing trailing
            // it is still an action, and the column should not change stroke
            // depending on whether that action happened to have an object.
            <span
              className={`font-medium ${
                clampTitle === 3
                  ? "line-clamp-3"
                  : clampTitle === 2
                    ? "line-clamp-2"
                    : "block"
              } ${breathing ? "dt-breathing-text" : ""}`}
            >
              {title}
            </span>
          )}
        </div>
        {/* No trailing spinner while live — the pulsing dot carries that. A
            faint chevron surfaces on hover so detail is always one click
            away without advertising itself on every row. */}
        {expandable ? (
          <ChevronDown
            size={13}
            className={`mt-1 shrink-0 text-[var(--muted-foreground)]/40 opacity-0 transition-[transform,opacity] duration-150 group-hover/row:opacity-100 ${
              open ? "" : "-rotate-90"
            }`}
          />
        ) : null}
      </div>
      {open ? (
        <StickyScroll
          stick={autoScrollDetail}
          // The rule sits at the dot's own centre (7.5px into the 15px mark
          // column) and the padding brings the body back out to the text
          // column, so the detail visibly hangs from its own row. This is the
          // only rule in the stack — level one needs none, since the dots
          // already form an aligned axis.
          className="dt-detail-in ml-[7px] mr-2 mt-1.5 max-h-[520px] overflow-y-auto border-l border-[var(--border)]/40 pl-[17px] pr-1"
        >
          {children}
        </StickyScroll>
      ) : null}
    </div>
  );
}
