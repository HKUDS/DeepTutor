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
   * When ``false``, the hook is a pass-through: the smoother is disabled
   * and ``displayContent`` always equals ``content``. Useful so callers
   * can keep the same render path for both streaming and idle messages.
   */
  enabled?: boolean;
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
    enabled = true,
  } = options;

  const [shown, setShown] = useState<string>(content);
  const shownLenRef = useRef<number>(content.length);
  const rafRef = useRef<number>(0);

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

    const step = () => {
      rafRef.current = 0;
      const target = content.length;
      const current = shownLenRef.current;
      if (current >= target) return;
      const backlog = target - current;
      const advance = Math.min(
        maxCharsPerFrame,
        Math.max(minCharsPerFrame, Math.ceil(backlog / catchUpDivisor)),
      );
      const next = Math.min(target, current + advance);
      shownLenRef.current = next;
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
  ]);

  return shown;
}
