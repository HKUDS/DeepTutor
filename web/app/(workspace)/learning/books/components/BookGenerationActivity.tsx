"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Loader2, Pause, Play, RefreshCcw } from "lucide-react";
import { useTranslation } from "react-i18next";

import {
  ActivityDivider,
  ActivityHeader,
  ActivityRow,
  ActivityStack,
  StatusDot,
} from "@/components/activity";
import { buildBookActivity, formatElapsed } from "@/lib/book-activity";
import type { BookProgress } from "@/lib/book-progress";
import type { Book, GenerationSummary, Page, Spine } from "@/lib/book-types";

export interface BookGenerationActivityProps {
  book: Book | null;
  pages: Page[];
  spine?: Spine | null;
  generation?: GenerationSummary | null;
  progress: BookProgress;
  onOpenPage?: (pageId: string) => void;
  onPause?: () => void;
  onResume?: () => void;
  pausing?: boolean;
  resuming?: boolean;
  className?: string;
}

/** The strip is one line, at one height, in every view and every phase. */
const STRIP_HEIGHT = 46;

/**
 * What the book is doing, on one line, with its history one click away.
 *
 * Replaces `BookProgressTimeline`, which showed the same run twice at once: a
 * gradient card spliced into the creator's scrolling content, and a floating
 * chip in the corner repeating its percentage. Both were built from six
 * aggregate stage chips and an invented `stages_done / 6` number — while the
 * engine was emitting per-chapter, per-block events that nothing rendered.
 *
 * Four rules:
 *
 * - **Exactly one line, always.** A fixed height, so the strip cannot reflow
 *   the page when work starts or finishes. That reflow was the whole problem
 *   with its predecessor.
 * - **The rest is a layer, not a section.** Clicking opens a popover *over*
 *   the content, holding what is already finished. The running item stays on
 *   the line, so the two never say the same thing twice.
 * - **Rows are real actions**, named after what they touched — the reader's
 *   own chapters, not internal stage names.
 * - **A manual way out is always on the line.** Pause while it runs, Resume
 *   when it stopped.
 */
export default function BookGenerationActivity({
  book,
  pages,
  spine,
  generation,
  progress,
  onOpenPage,
  onPause,
  onResume,
  pausing = false,
  resuming = false,
  className = "",
}: BookGenerationActivityProps) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const wrapRef = useRef<HTMLDivElement>(null);

  const activity = useMemo(
    () =>
      buildBookActivity({
        book,
        pages,
        spine,
        generation,
        progress,
        t: (key, options) => t(key, options) as string,
      }),
    [book, pages, spine, generation, progress, t],
  );

  // One clock for the strip. `now` is state rather than a bare re-render
  // trigger so the elapsed time is derived *here*, outside the memo above:
  // computing it inside meant it only moved when an event happened to land,
  // which is exactly the stall — the number sat still for a whole stage and
  // then jumped.
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!activity.live) return;
    // The interval is the only writer. Setting `now` synchronously here as
    // well would be a cascading render (the React Compiler rules forbid it),
    // and buys nothing: the first tick lands within a second and the display
    // is in whole seconds.
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, [activity.live]);

  // A layer over the page closes the way layers do: click away, or Escape.
  const close = useCallback(() => setOpen(false), []);
  useEffect(() => {
    if (!open) return;
    const onPointerDown = (event: MouseEvent) => {
      if (!wrapRef.current?.contains(event.target as Node)) close();
    };
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") close();
    };
    document.addEventListener("mousedown", onPointerDown);
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("mousedown", onPointerDown);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [open, close]);

  const settled = !activity.live;

  // What the layer holds: work that is finished. The line already names what
  // is running, and a chapter still in the queue has nothing to report yet.
  const history = useMemo(() => {
    const preparation = activity.preparation.filter(
      (row) => row.state !== "running" && Boolean(row.detail),
    );
    const chapters = activity.chapters.filter(
      (row) => row.state !== "running" && !row.queued,
    );
    return {
      preparation,
      chapters,
      size: preparation.length + chapters.length,
    };
  }, [activity]);

  /**
   * The strip exists to report work. If none is happening it goes away.
   *
   * Three states earn it: something is running, generation is paused, or a
   * compile was lost and needs restarting — the last two because they are the
   * only way back. Everything else (a finished book, a book sitting at the
   * spine waiting to be confirmed) got a strip that said "Preparing your
   * book" with a turning orb over a page where nothing was happening at all.
   */
  if (activity.empty) return null;
  if (
    !activity.live &&
    activity.phase !== "paused" &&
    activity.phase !== "interrupted"
  ) {
    return null;
  }

  const duration =
    activity.runStartedAt != null
      ? formatElapsed(
          Math.max(0, Math.round((now - activity.runStartedAt) / 1000)),
        )
      : null;

  return (
    <div
      ref={wrapRef}
      // `relative` anchors the layer; `shrink-0` keeps the strip out of the
      // view's height negotiation, so the reader below owns whatever is left.
      className={`relative shrink-0 border-b border-[var(--border)] ${className}`}
    >
      <div
        className="mx-auto flex w-full max-w-[78ch] items-center gap-3 px-6"
        style={{ height: STRIP_HEIGHT }}
      >
        <ActivityHeader
          orb={activity.orb}
          orbSpeed={activity.orbSpeed}
          label={activity.label}
          duration={duration}
          settled={settled}
          expandable={history.size > 0}
          expanded={open}
          onToggle={() => setOpen((current) => !current)}
          className="min-w-0 flex-1"
        />
        {activity.chaptersTotal > 0 && (
          <span className="shrink-0 text-[12px] font-medium tabular-nums text-[var(--muted-foreground)] opacity-60">
            {t("{{done}}/{{total}} chapters", {
              done: activity.chaptersReady,
              total: activity.chaptersTotal,
            })}
          </span>
        )}
        {activity.live && onPause && (
          <ControlButton
            onClick={onPause}
            busy={pausing}
            icon={<Pause className="h-3 w-3" />}
            label={t("Pause generation")}
            busyLabel={t("Pausing…")}
          />
        )}
        {!activity.live &&
          onResume &&
          (activity.phase === "paused" || activity.phase === "interrupted") && (
            <ControlButton
              onClick={onResume}
              busy={resuming}
              icon={
                activity.phase === "interrupted" ? (
                  <RefreshCcw className="h-3 w-3" />
                ) : (
                  <Play className="h-3 w-3" />
                )
              }
              label={
                activity.phase === "interrupted"
                  ? t("Continue generating")
                  : t("Resume generation")
              }
              busyLabel={t("Resuming…")}
            />
          )}
      </div>

      {open && history.size > 0 && (
        // Two elements on purpose. Centring with `-translate-x-1/2` and
        // animating with `dt-detail-in` both want `transform`, and the
        // keyframes win — they end on `transform: none`, so the layer came up
        // with its left edge on the centre line (visibly off to the right)
        // and snapped into place when the animation finished. The outer box
        // owns the position, using flex rather than a transform; the inner
        // one owns the motion.
        <div className="absolute inset-x-0 top-full z-40 flex justify-center px-6">
          <div
            role="dialog"
            aria-label={t("Finished so far")}
            // A layer gets a layer's surface: staying readable over arbitrary
            // content is the one case where a border, a radius and a shadow
            // are doing work rather than decorating.
            className="dt-detail-in mt-1 max-h-[min(60vh,460px)] w-full max-w-[32rem] overflow-y-auto rounded-xl border border-[var(--border)] bg-[var(--card)] p-3 shadow-lg"
          >
            <ActivityStack alignUnderOrb={false}>
              {history.preparation.map((row) => (
                <ActivityRow
                  key={row.id}
                  state={row.state}
                  title={row.title}
                  detail={row.detail}
                />
              ))}
              {history.chapters.length > 0 && (
                <ActivityDivider label={t("Chapters")} />
              )}
              {history.chapters.map((row) => (
                <ActivityRow
                  key={row.id}
                  state={row.state}
                  title={
                    onOpenPage && row.pageId ? (
                      <span
                        role="link"
                        tabIndex={0}
                        onClick={(event) => {
                          // The row owns the fold; the title owns navigation.
                          event.stopPropagation();
                          close();
                          onOpenPage(row.pageId!);
                        }}
                        onKeyDown={(event) => {
                          if (event.key !== "Enter" && event.key !== " ")
                            return;
                          event.stopPropagation();
                          event.preventDefault();
                          close();
                          onOpenPage(row.pageId!);
                        }}
                        className="cursor-pointer decoration-[var(--muted-foreground)] underline-offset-2 hover:underline"
                      >
                        {row.title}
                      </span>
                    ) : (
                      row.title
                    )
                  }
                  detail={row.detail}
                >
                  {row.blocks?.length ? (
                    <ul className="space-y-px py-0.5">
                      {row.blocks.map((block) => (
                        <li
                          key={block.key}
                          className="flex items-center gap-2 text-[13px] text-[var(--muted-foreground)]"
                        >
                          <StatusDot state={block.state} />
                          <span>{block.label}</span>
                        </li>
                      ))}
                    </ul>
                  ) : null}
                </ActivityRow>
              ))}
            </ActivityStack>
          </div>
        </div>
      )}
    </div>
  );
}

/** A small text control on the strip — same weight as the status beside it. */
function ControlButton({
  onClick,
  busy,
  icon,
  label,
  busyLabel,
}: {
  onClick: () => void;
  busy: boolean;
  icon: React.ReactNode;
  label: string;
  busyLabel: string;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={busy}
      className="inline-flex shrink-0 items-center gap-1.5 rounded-md px-2 py-1 text-[12px] font-medium text-[var(--muted-foreground)] transition-colors hover:bg-[var(--muted)] hover:text-[var(--foreground)] disabled:cursor-not-allowed disabled:opacity-50"
    >
      {busy ? <Loader2 className="h-3 w-3 animate-spin" /> : icon}
      {busy ? busyLabel : label}
    </button>
  );
}
