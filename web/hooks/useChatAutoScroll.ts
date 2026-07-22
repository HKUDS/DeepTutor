"use client";

import { useCallback, useEffect, useLayoutEffect, useRef } from "react";

interface AutoScrollOptions {
  hasMessages: boolean;
  isStreaming: boolean;
  composerHeight: number;
  messageCount: number;
  lastMessageContent?: string;
  lastEventCount?: number;
}

/**
 * "Pin to bottom" autoscroll, designed for jitter-free LLM streaming.
 *
 * The implementation deliberately collapses what used to be three
 * separate scroll paths (a throttled timer, a rAF tick, a smooth-vs-
 * instant branch on stream state) into one: a single
 * ``useLayoutEffect`` that assigns ``scrollTop = scrollHeight`` while
 * ``autoFollow`` is true. That is the only writer to ``scrollTop``
 * during streaming, which removes all the races that previously made
 * the viewport visibly stutter — smooth-scroll animation interrupted
 * by the next delta's instant snap, throttle + rAF firing within the
 * same frame, the browser's built-in scroll anchoring tugging back at
 * the manual pin while mid-stream code blocks / KaTeX / dynamic
 * viewers reflow above the cursor, etc.
 *
 * Three companion mechanisms keep behaviour correct in edge cases:
 *
 *  - ``handleScroll`` watches the user's scroll position. The instant
 *    they move more than 80px above the bottom we release the pin so
 *    they can browse history without being yanked back. Scrolling
 *    back near the bottom re-arms it.
 *  - ``composerHeight`` changes (e.g. when the composer grows for a
 *    multi-line draft) re-pin once via a layout effect so the freshly-
 *    revealed content stays on screen.
 *  - A short post-stream window watches for ``childList`` mutations.
 *    Several capability viewers (MathAnimator, Quiz, Visualize) are
 *    loaded via ``next/dynamic({ssr:false})`` and only mount after the
 *    final result event lands; if the user is still pinned we follow
 *    those late-mounting heights downward.
 *
 * The scroll container must also opt into ``overflow-anchor: none``
 * (set globally on ``[data-chat-scroll-root="true"]``). Without it,
 * the browser's default scroll-anchoring tries to keep an in-viewport
 * element fixed in screen space when content above it grows — which
 * fights this hook every time a code block expands.
 */
export function useChatAutoScroll({
  hasMessages,
  isStreaming,
  composerHeight,
  messageCount,
  lastMessageContent,
  lastEventCount,
}: AutoScrollOptions) {
  const containerRef = useRef<HTMLDivElement>(null);
  const endRef = useRef<HTMLDivElement>(null);
  const shouldAutoScrollRef = useRef(true);

  const pinToBottom = useCallback(() => {
    const container = containerRef.current;
    if (!container) return;
    // Direct assignment, not ``scrollTo({behavior})``. The browser
    // applies it synchronously inside the same layout pass which
    // means the user never sees the in-between frame where new
    // content has rendered but the scroll position is still stale.
    container.scrollTop = container.scrollHeight;
  }, []);

  // Primary pin: runs in layout phase after every render that bumps
  // message count / streaming content / events / composer height /
  // mount. ``useLayoutEffect`` (not ``useEffect``) is required so the
  // assignment happens before the browser paints — otherwise the
  // viewer briefly shows the new layout at the old scroll position
  // and we observe a flash.
  useLayoutEffect(() => {
    if (!hasMessages || !shouldAutoScrollRef.current) return;
    pinToBottom();
  }, [
    pinToBottom,
    hasMessages,
    isStreaming,
    messageCount,
    lastMessageContent,
    lastEventCount,
    composerHeight,
  ]);

  // Companion pin: a frame-aligned rAF loop that runs ONLY while the
  // turn is streaming. ``useLayoutEffect`` above already pins on every
  // page-level state change (new delta, new event, new message), but
  // there is a class of height growth that doesn't bubble up to the
  // page:
  //
  //   1. ``useSmoothStreamText`` advances the visible markdown inside
  //      a child component between WebSocket deltas. Those frames
  //      grow the inner content but the page's deps don't change, so
  //      the layout effect above doesn't re-fire on them.
  //   2. KaTeX, code blocks, Mermaid, and the late-mount viewer
  //      ``next/dynamic`` chunks all change the height of the message
  //      area asynchronously when they finish hydrating mid-stream.
  //
  // We can't use ``ResizeObserver`` on the scroll container itself
  // because it observes border-box, not scrollHeight; overflow growth
  // doesn't fire it. A short rAF loop scoped strictly to the
  // streaming window costs ~60 cheap pins per second (each pin is a
  // single attribute write, no React work) and is the simplest way
  // to stay glued to the bottom edge regardless of WHY the inner
  // content height changed.
  useEffect(() => {
    if (!isStreaming || !hasMessages) return;
    let rafId = 0;
    const tick = () => {
      if (shouldAutoScrollRef.current) {
        const container = containerRef.current;
        if (container) container.scrollTop = container.scrollHeight;
      }
      rafId = requestAnimationFrame(tick);
    };
    rafId = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(rafId);
  }, [isStreaming, hasMessages]);

  // After streaming ends, capability viewers loaded via ``next/dynamic``
  // (MathAnimatorViewer, QuizViewer, VisualizationViewer, RichCodeBlock,
  // Mermaid …) finish hydrating and grow the content height. The user
  // expects to land at the bottom so they see the full result.
  //
  // The observer is intentionally short-lived (4s after stream stop):
  // a longer window would mis-classify post-turn user interactions
  // (expanding a trace ``<details>``, clicking a citation) as
  // "streaming-style growth" and rip them back to the bottom.
  const POST_STREAM_AUTOSCROLL_WINDOW_MS = 4000;
  useEffect(() => {
    if (isStreaming) return;
    if (!hasMessages) return;

    const container = containerRef.current;
    if (!container) return;

    let prevHeight = container.scrollHeight;
    let rafId = 0;
    const deadline = performance.now() + POST_STREAM_AUTOSCROLL_WINDOW_MS;

    const check = () => {
      if (rafId) return;
      rafId = requestAnimationFrame(() => {
        rafId = 0;
        if (performance.now() > deadline) return;
        const curHeight = container.scrollHeight;
        if (curHeight > prevHeight && shouldAutoScrollRef.current) {
          pinToBottom();
        }
        prevHeight = curHeight;
      });
    };

    const mo = new MutationObserver(check);
    mo.observe(container, { childList: true, subtree: true });
    const stopTimer = window.setTimeout(() => {
      mo.disconnect();
      if (rafId) cancelAnimationFrame(rafId);
    }, POST_STREAM_AUTOSCROLL_WINDOW_MS);

    return () => {
      window.clearTimeout(stopTimer);
      mo.disconnect();
      if (rafId) cancelAnimationFrame(rafId);
    };
  }, [hasMessages, isStreaming, pinToBottom]);

  const handleScroll = useCallback(() => {
    const container = containerRef.current;
    if (!container) return;
    const distanceFromBottom =
      container.scrollHeight - container.scrollTop - container.clientHeight;
    shouldAutoScrollRef.current = distanceFromBottom < 80;
  }, []);

  // Intent-based release. The streaming rAF above re-pins to
  // ``scrollHeight`` every frame, so the position-only ``handleScroll``
  // check can NEVER observe the user trying to scroll up mid-stream: the
  // pin snaps them back to the bottom before the ``scroll`` event is even
  // handled, so ``distanceFromBottom`` always reads ~0 and the pin never
  // releases — the viewport feels frozen. We therefore release the pin the
  // instant we see an UPWARD scroll *gesture* (wheel up, or a touch drag
  // that pulls earlier content into view), which is unambiguous user intent
  // and independent of where the pin has parked the scroll position. Once
  // released the rAF stops fighting, the user is free to browse, and
  // ``handleScroll`` re-arms the pin when they return near the bottom.
  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    const release = () => {
      shouldAutoScrollRef.current = false;
    };

    const onWheel = (event: WheelEvent) => {
      if (event.deltaY < 0) release();
    };

    let touchY = 0;
    const onTouchStart = (event: TouchEvent) => {
      touchY = event.touches[0]?.clientY ?? 0;
    };
    const onTouchMove = (event: TouchEvent) => {
      const y = event.touches[0]?.clientY ?? 0;
      // Finger dragging downward scrolls the content up (reveals earlier
      // messages) — an explicit "let me read back" gesture.
      if (y - touchY > 4) release();
      touchY = y;
    };

    container.addEventListener("wheel", onWheel, { passive: true });
    container.addEventListener("touchstart", onTouchStart, { passive: true });
    container.addEventListener("touchmove", onTouchMove, { passive: true });
    return () => {
      container.removeEventListener("wheel", onWheel);
      container.removeEventListener("touchstart", onTouchStart);
      container.removeEventListener("touchmove", onTouchMove);
    };
    // Re-attach when the scroll container (re)mounts — it only exists once
    // there are messages to show.
  }, [hasMessages]);

  // ``scrollToBottom`` is preserved as a public escape hatch (e.g. an
  // imperative "jump to latest" button) but kept ``instant`` so it
  // never animates against an active stream.
  const scrollToBottom = useCallback(
    (_behavior: ScrollBehavior) => {
      void _behavior;
      pinToBottom();
    },
    [pinToBottom],
  );

  return {
    containerRef,
    endRef,
    shouldAutoScrollRef,
    scrollToBottom,
    handleScroll,
  };
}
