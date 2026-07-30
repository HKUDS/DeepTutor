"use client";

import { AnimatePresence, motion } from "framer-motion";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import { getModeBadgeLabel } from "@/components/chat/home/ChatMessages";
import type { ChatOutlineEntry } from "@/lib/chat-outline";

/**
 * A rail of ticks in the transcript's left gutter — one per question the
 * user asked — for jumping back through a long conversation.
 *
 * Placement. The rail is an absolutely-positioned sibling of the scroll
 * container, NOT a child of it: the scrollport carries a mask-image that
 * fades its top 32 px and bottom 40 px, which would eat a sticky rail's
 * ends. It therefore expects to be rendered inside a positioned wrapper
 * that spans exactly the scrollport, and it measures its own left offset
 * from the transcript column (``[data-chat-column]``) so it hugs the
 * text at any width instead of floating in the middle of the gutter.
 *
 * Two resting states, not one. At rest the rail is deliberately almost
 * absent — short ticks, tight rows, pulled toward the window edge — so a
 * reader who is just reading never registers a widget in their
 * periphery. Bringing the pointer near it shifts the whole rail a few px
 * inward and lets the rows breathe apart, which both acknowledges the
 * hover and makes a 2 px target comfortable to hit. Everything that
 * moves does so via ``transform`` / ``height`` transitions on the ticks
 * themselves, so no reflow reaches the transcript.
 *
 * Visibility. When the gutter is narrower than the rail needs (narrow
 * window, preview drawer open, phone) the ticks are not rendered at all
 * — squeezing them over the text would be worse than not having them.
 * The component stays mounted in that case so ``Alt`` + ``↑`` / ``↓``
 * keeps working; that shortcut is the keyboard half of the same feature
 * and must not depend on how wide the window happens to be.
 *
 * Active state lives here rather than in the page so that scrolling a
 * long transcript re-renders one small rail instead of the whole chat.
 */

/** Gutter needed before the rail is worth showing (tick + breathing room). */
const MIN_GUTTER_PX = 52;
/** Resting distance from the scrollport's left edge. */
const EDGE_PAD_PX = 14;
/**
 * Cap on how far in from that edge the rail may sit. The rail belongs to
 * the window, not to the paragraph: on a wide monitor "hug the text"
 * parks it right beside the prose where it competes with the reading
 * column, so it stays pinned near the edge and the extra gutter is left
 * as empty margin.
 */
const EDGE_MAX_PX = 40;
/** Clearance kept between the rail and the transcript column. */
const RAIL_INSET_PX = 30;
/** Extra px the rail hides itself by while idle, and reveals on hover. */
const IDLE_RETREAT_PX = 7;
/** A bubble is "current" once its top passes this line in the scrollport. */
const ACTIVE_LINE_PX = 140;
/** Vertical padding inside the tick track (``py-2``). */
const TRACK_PAD_PX = 8;
/** Fraction of the viewport the track may occupy before it scrolls. */
const TRACK_MAX_VH = 0.62;
/** Half the preview card's height, used to keep it inside the rail. */
const CARD_HALF_PX = 62;

/**
 * Row height per tick, idle and hovered. Both shrink as the conversation
 * grows so the rail keeps reading as one glanceable object; past ~40
 * questions they stop shrinking and the track scrolls instead
 * (illegible 4 px rows are not a better answer than scrolling).
 */
function rowHeight(count: number, hot: boolean): number {
  if (count > 40) return hot ? 11 : 7;
  if (count > 24) return hot ? 14 : 9;
  return hot ? 18 : 11;
}

/** Tick length: idle reads as a hairline, hover as a legible bar. */
function tickWidth(weight: number, hot: boolean, emphasised: boolean): number {
  const base = hot ? 9 + weight * 14 : 5 + weight * 7;
  return Math.round(base + (emphasised ? (hot ? 5 : 3) : 0));
}

export function TurnNavigator({
  entries,
  scrollRootRef,
  onJump,
  onJumpToBottom,
}: {
  entries: ChatOutlineEntry[];
  scrollRootRef: React.RefObject<HTMLDivElement | null>;
  /** Scroll the bubble carrying ``key`` into view and flash it. */
  onJump: (key: string) => void;
  onJumpToBottom: () => void;
}) {
  const { t } = useTranslation();
  const railRef = useRef<HTMLDivElement>(null);
  const trackRef = useRef<HTMLDivElement>(null);
  const [left, setLeft] = useState<number | null>(null);
  const [activeKey, setActiveKey] = useState<string | null>(null);
  const [hoveredKey, setHoveredKey] = useState<string | null>(null);
  const [pointerInside, setPointerInside] = useState(false);
  const [cardY, setCardY] = useState<number | null>(null);

  // Effects below depend on the key list rather than on ``entries`` so a
  // streamed content delta (which rebuilds entries but not their keys)
  // doesn't re-subscribe the scroll and keyboard listeners.
  const keys = useMemo(
    () => entries.map((entry) => entry.key).join("\n"),
    [entries],
  );
  const keyList = useMemo(() => (keys ? keys.split("\n") : []), [keys]);

  // Keyboard focus counts as "reaching for the rail" too, so a tabbing
  // user gets the same expanded target the pointer gets.
  const hot = pointerInside || hoveredKey !== null;

  // ─── Where does the rail sit? ───
  // Re-measured whenever the wrapper resizes: window resize, sidebar
  // collapse, and the preview/activity drawer sliding in all change the
  // gutter, and the drawer animates so a one-shot measure would land on
  // a stale width.
  useEffect(() => {
    const rail = railRef.current;
    const wrapper = rail?.parentElement;
    if (!rail || !wrapper) return;

    const measure = () => {
      const column =
        scrollRootRef.current?.querySelector<HTMLElement>("[data-chat-column]");
      if (!column) return;
      const gutter =
        column.getBoundingClientRect().left -
        wrapper.getBoundingClientRect().left;
      if (gutter < MIN_GUTTER_PX) {
        setLeft(null);
        return;
      }
      setLeft(
        Math.min(Math.max(gutter - RAIL_INSET_PX, EDGE_PAD_PX), EDGE_MAX_PX),
      );
    };

    measure();
    const ro = new ResizeObserver(measure);
    ro.observe(wrapper);
    return () => ro.disconnect();
  }, [scrollRootRef, entries.length]);

  // ─── Which tick is current? ───
  // Rect-based and coalesced to one pass per animation frame. Reading n
  // rects costs a single layout (they are read back-to-back with no
  // interleaved writes), which is cheaper and far less fragile than
  // caching offsets that every mid-stream reflow would invalidate.
  useEffect(() => {
    const container = scrollRootRef.current;
    if (!container) return;
    let rafId = 0;

    const recompute = () => {
      rafId = 0;
      const containerTop = container.getBoundingClientRect().top;
      let current: string | null = null;
      for (const key of keyList) {
        const el = container.querySelector<HTMLElement>(
          `[data-turn-key="${key}"]`,
        );
        if (!el) continue;
        if (el.getBoundingClientRect().top - containerTop <= ACTIVE_LINE_PX) {
          current = key;
        } else break;
      }
      setActiveKey(current ?? keyList[0] ?? null);
    };
    const schedule = () => {
      if (!rafId) rafId = requestAnimationFrame(recompute);
    };

    schedule();
    container.addEventListener("scroll", schedule, { passive: true });
    return () => {
      container.removeEventListener("scroll", schedule);
      if (rafId) cancelAnimationFrame(rafId);
    };
  }, [scrollRootRef, keyList]);

  // Keep the current tick in view when the track itself has to scroll.
  useEffect(() => {
    if (!activeKey) return;
    trackRef.current
      ?.querySelector<HTMLElement>(`[data-tick="${activeKey}"]`)
      ?.scrollIntoView({ block: "nearest" });
  }, [activeKey]);

  // ─── Keyboard ───
  // Alt/Option + arrows walk the user's own questions; from the last one
  // Alt+↓ returns to the live end of the conversation. Editable targets
  // are skipped so the composer keeps its native word-wise navigation.
  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (!event.altKey || event.metaKey || event.ctrlKey) return;
      if (event.key !== "ArrowUp" && event.key !== "ArrowDown") return;
      const target = event.target as HTMLElement | null;
      if (
        target?.isContentEditable ||
        target?.tagName === "INPUT" ||
        target?.tagName === "TEXTAREA"
      )
        return;
      if (!keyList.length) return;
      const at = activeKey ? keyList.indexOf(activeKey) : -1;
      event.preventDefault();
      if (event.key === "ArrowUp") {
        onJump(keyList[Math.max(0, (at === -1 ? keyList.length : at) - 1)]);
        return;
      }
      if (at === -1 || at >= keyList.length - 1) onJumpToBottom();
      else onJump(keyList[at + 1]);
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [activeKey, keyList, onJump, onJumpToBottom]);

  // The card is parked beside the tick it describes, computed from the
  // rail's own geometry rather than measured: the row heights are still
  // mid-transition when the hover fires, so a ``getBoundingClientRect``
  // here would anchor to the collapsed layout and then look misplaced.
  // Clamped so the card can never hang off the ends of a long rail.
  const parkCardAt = useCallback(
    (index: number, count: number) => {
      const row = rowHeight(count, true);
      const trackHeight = Math.min(
        count * row + TRACK_PAD_PX * 2,
        (typeof window === "undefined" ? 800 : window.innerHeight) *
          TRACK_MAX_VH,
      );
      const raw =
        TRACK_PAD_PX +
        index * row +
        row / 2 -
        (trackRef.current?.scrollTop ?? 0);
      setCardY(
        Math.min(
          Math.max(raw, CARD_HALF_PX),
          Math.max(trackHeight - CARD_HALF_PX, CARD_HALF_PX),
        ),
      );
    },
    [],
  );

  // Below three questions the rail is noise: everything is one flick away.
  if (entries.length < 3) return null;

  const row = rowHeight(entries.length, hot);
  const hovered = hoveredKey
    ? (entries.find((entry) => entry.key === hoveredKey) ?? null)
    : null;

  return (
    <div
      ref={railRef}
      aria-hidden={left === null}
      className="absolute top-1/2 z-20 -translate-y-1/2"
      style={{
        left: left ?? 0,
        visibility: left === null ? "hidden" : "visible",
      }}
    >
      <nav
        aria-label={t("Jump to one of your questions")}
        // Negative margins turn the padding into an invisible grab area:
        // the ticks are hairlines, so the pointer must be able to claim
        // the rail from a few px away in the empty gutter around them.
        className="relative -my-2 -ml-2 py-2 pl-2 pr-4 transition-transform duration-300 ease-out motion-reduce:transition-none"
        style={{
          transform: `translateX(${hot ? 0 : -IDLE_RETREAT_PX}px)`,
        }}
        onMouseEnter={() => setPointerInside(true)}
        onMouseLeave={() => {
          setPointerInside(false);
          setHoveredKey(null);
        }}
      >
        <div
          ref={trackRef}
          className="hide-scrollbar flex flex-col overflow-y-auto overscroll-contain"
          style={{ maxHeight: `${TRACK_MAX_VH * 100}vh` }}
        >
          {entries.map((entry, index) => {
            const isActive = entry.key === activeKey;
            const isHovered = entry.key === hoveredKey;
            const focus = () => {
              setHoveredKey(entry.key);
              parkCardAt(index, entries.length);
            };
            return (
              <button
                key={entry.key}
                type="button"
                data-tick={entry.key}
                onMouseEnter={focus}
                onFocus={focus}
                onBlur={() => setHoveredKey(null)}
                onClick={() => onJump(entry.key)}
                aria-current={isActive ? "true" : undefined}
                aria-label={`${entry.ordinal}. ${entry.title}`}
                className="flex shrink-0 items-center outline-none transition-[height] duration-[240ms] ease-out motion-reduce:transition-none"
                style={{
                  height: row,
                  transitionDelay: hot
                    ? `${Math.min(index, 14) * 6}ms`
                    : undefined,
                }}
              >
                <span
                  className={`h-[2px] rounded-full transition-[width,opacity,background-color] duration-[240ms] ease-out motion-reduce:transition-none ${
                    isHovered
                      ? "bg-[var(--foreground)] opacity-100"
                      : isActive
                        ? "bg-[var(--foreground)] opacity-80"
                        : hot
                          ? "bg-[var(--muted-foreground)] opacity-55"
                          : "bg-[var(--muted-foreground)] opacity-25"
                  }`}
                  style={{
                    width: tickWidth(entry.weight, hot, isActive || isHovered),
                  }}
                />
              </button>
            );
          })}
        </div>

        {/* Preview flies out over the transcript. Deliberately
            pointer-transparent so it can never swallow a click meant for
            the message underneath it, and painted on --popover rather
            than a blur: every theme publishes a near-opaque popover
            colour, so the text on top stays crisp instead of picking up
            the paragraph it covers. */}
        <AnimatePresence>
          {hovered ? (
            <motion.div
              key={hovered.key}
              initial={{ opacity: 0, x: -6 }}
              animate={{ opacity: 1, x: 0 }}
              exit={{ opacity: 0, x: -4 }}
              transition={{ duration: 0.14, ease: "easeOut" }}
              style={{ top: cardY ?? "50%" }}
              className="pointer-events-none absolute left-full z-10 ml-2 w-[290px] -translate-y-1/2 rounded-2xl border border-[var(--border)] bg-[var(--popover)] px-3.5 py-3 text-[var(--popover-foreground)] shadow-[0_16px_44px_-18px_var(--overlay)]"
            >
              <div className="flex items-baseline gap-2 text-[10px] font-medium uppercase tracking-[0.08em] text-[var(--muted-foreground)]">
                <span className="tabular-nums">
                  {hovered.ordinal}/{entries.length}
                </span>
                {hovered.capability && hovered.capability !== "chat" ? (
                  <span className="truncate normal-case tracking-normal opacity-80">
                    {t(getModeBadgeLabel(hovered.capability))}
                  </span>
                ) : null}
              </div>
              <div className="mt-1.5 line-clamp-3 text-[12.5px] font-medium leading-[1.5]">
                {hovered.title}
              </div>
              {hovered.reply ? (
                <div className="mt-1.5 line-clamp-2 text-[11.5px] leading-[1.55] text-[var(--muted-foreground)]">
                  {hovered.reply}
                </div>
              ) : null}
            </motion.div>
          ) : null}
        </AnimatePresence>
      </nav>
    </div>
  );
}
