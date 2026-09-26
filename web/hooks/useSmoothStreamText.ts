"use client";

import { useEffect, useRef, useState } from "react";

interface SmoothStreamOptions {
  /**
   * Cap on visible chars revealed per rAF frame.
   * The reveal speed adapts to the current backlog so a long pause that
   * suddenly delivers a 2KB chunk doesn't take 30 seconds to type out:
   * each frame reveals max(MIN_CHARS_PER_FRAME, backlog / catchUpDivisor),
   * up to ``maxCharsPerFrame``.
   */
  maxCharsPerFrame?: number;
  /** Minimum chars revealed per frame so the cursor always advances. */
  minCharsPerFrame?: number;
  /** Larger = slower reveal relative to backlog. ~5 feels natural. */
  catchUpDivisor?: number;
  /**
   * Characters of message per millisecond of enforced gap between reveals.
   *
   * Every reveal re-renders the consumer, and a markdown consumer re-parses
   * the *entire* document when it does — so a turn costs (reveals × length).
   * Revealing on every frame therefore makes a long answer quadratic in its
   * own length, which is the exact shape of "it streams fine at first and
   * gets choppier the longer it runs".
   *
   * The cap cannot be expressed in characters: a model that sends three
   * characters at a time sets the pace, and there is no text to reveal ahead
   * of it. So the gap is in time. At this default a 1KB reply still reveals on
   * every frame, a 5KB one drops to 20fps and a 12KB one to the cap — all of
   * which still read as continuous text arriving, because what the eye follows
   * here is words appearing, not motion.
   */
  revealGapCharsPerMs?: number;
  /** Longest gap the rate cap will impose, however long the message runs. */
  maxRevealGapMs?: number;
  /**
   * When ``false``, the hook is a pass-through: the smoother is disabled
   * and ``displayContent`` always equals ``content``. Useful so callers
   * can keep the same render path for both streaming and idle messages.
   */
  enabled?: boolean;
}

/**
 * How many characters the next reveal advances by.
 *
 * Pure, and exported, because the pacing is the whole behaviour of this hook
 * and is the part worth pinning down without a renderer.
 */
export function revealStep(
  current: number,
  target: number,
  {
    maxCharsPerFrame = 120,
    minCharsPerFrame = 2,
    catchUpDivisor = 5,
  }: SmoothStreamOptions = {},
): number {
  const backlog = target - current;
  if (backlog <= 0) return 0;
  return Math.min(
    maxCharsPerFrame,
    Math.max(minCharsPerFrame, Math.ceil(backlog / catchUpDivisor)),
  );
}

/**
 * The shortest time allowed between two reveals of a message this long.
 *
 * Zero for anything short enough that re-parsing it is free; rising with
 * length so the work per second stays flat instead of growing with the
 * answer. See ``revealGapCharsPerMs``.
 */
export function revealGapMs(
  length: number,
  { revealGapCharsPerMs = 100, maxRevealGapMs = 120 }: SmoothStreamOptions = {},
): number {
  const gap = Math.floor(length / revealGapCharsPerMs);
  // Below a frame it is not a cap at all — rAF is already the floor.
  return gap <= 16 ? 0 : Math.min(maxRevealGapMs, gap);
}

/**
 * Decouples the visible markdown growth rate from the WebSocket delta
 * cadence so the user perceives smooth, "typewriter"-style streaming
 * regardless of how bursty the upstream LLM chunks are.
 *
 * Mechanics:
 *   - While ``isStreaming`` is true and the incoming ``content`` is
 *     longer than what we've shown, a single ``requestAnimationFrame``
 *     loop advances the cursor towards ``content.length``.
 *   - Frames are skipped once the message is long enough that re-rendering it
 *     on every one costs more than it shows — see ``revealGapCharsPerMs``.
 *   - When ``isStreaming`` flips false, we snap to the full ``content``
 *     on the next frame so the finished message lands instantly. This
 *     also handles short messages where the smoother would otherwise
 *     leave a few trailing chars unrevealed at stream end.
 *   - When ``content`` shrinks (regenerate / edit-branch path resets
 *     the streaming bubble) we snap back to the new length. Otherwise
 *     the cursor would briefly display stale tail text.
 *
 * The hook is intentionally generic: it knows nothing about markdown
 * or assistant turns, so it can be reused for any streaming surface
 * (chat, quiz follow-up, book chat, memory workbench, …).
 */
export function useSmoothStreamText(
  content: string,
  isStreaming: boolean,
  options: SmoothStreamOptions = {},
): string {
  const {
    maxCharsPerFrame = 120,
    minCharsPerFrame = 2,
    catchUpDivisor = 5,
    revealGapCharsPerMs = 100,
    maxRevealGapMs = 120,
    enabled = true,
  } = options;

  const [shown, setShown] = useState<string>(content);
  const shownLenRef = useRef<number>(content.length);
  const rafRef = useRef<number>(0);
  // Survives the cancel/re-arm that every delta puts the rAF chain through,
  // so the rate cap is a property of the message rather than of one chain.
  const lastRevealRef = useRef<number>(0);

  useEffect(() => {
    if (!enabled) {
      // Disabled mode: act as a pure pass-through.
      if (shownLenRef.current !== content.length || shown !== content) {
        shownLenRef.current = content.length;
        setShown(content);
      }
      return;
    }

    // Snap to full content the moment streaming stops so the user never
    // sees a half-revealed tail at the end of the turn.
    if (!isStreaming) {
      if (rafRef.current) {
        cancelAnimationFrame(rafRef.current);
        rafRef.current = 0;
      }
      if (shownLenRef.current !== content.length || shown !== content) {
        shownLenRef.current = content.length;
        setShown(content);
      }
      return;
    }

    // Content shrank (regenerate / branch switch): snap back to avoid
    // a phantom tail from the previous stream.
    if (shownLenRef.current > content.length) {
      shownLenRef.current = content.length;
      setShown(content);
      return;
    }

    if (shownLenRef.current >= content.length) {
      // Caught up — wait for the next delta to re-arm the loop.
      return;
    }

    const step = (now: number) => {
      rafRef.current = 0;
      const target = content.length;
      const current = shownLenRef.current;
      if (current >= target) return;
      const gap = revealGapMs(target, { revealGapCharsPerMs, maxRevealGapMs });
      if (gap > 0 && now - lastRevealRef.current < gap) {
        // Too soon to pay for another full re-parse. Keep waiting rather than
        // rendering; the text arriving meanwhile rides on the next reveal.
        rafRef.current = requestAnimationFrame(step);
        return;
      }
      const advance = revealStep(current, target, {
        maxCharsPerFrame,
        minCharsPerFrame,
        catchUpDivisor,
      });
      const next = Math.min(target, current + advance);
      shownLenRef.current = next;
      lastRevealRef.current = now;
      setShown(content.slice(0, next));
      if (next < target) {
        rafRef.current = requestAnimationFrame(step);
      }
    };

    if (!rafRef.current) {
      rafRef.current = requestAnimationFrame(step);
    }

    return () => {
      if (rafRef.current) {
        cancelAnimationFrame(rafRef.current);
        rafRef.current = 0;
      }
    };
    // ``shown`` is intentionally omitted from deps — including it would
    // restart the loop after every advance and we'd lose the rAF chain.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [
    content,
    isStreaming,
    enabled,
    maxCharsPerFrame,
    minCharsPerFrame,
    catchUpDivisor,
    revealGapCharsPerMs,
    maxRevealGapMs,
  ]);

  return shown;
}
