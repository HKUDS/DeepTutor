"use client";

import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";

interface AutoScrollOptions {
  hasMessages: boolean;
  isStreaming: boolean;
  composerHeight: number;
  messageCount: number;
  lastMessageContent?: string;
  lastEventCount?: number;
}

/** Movement smaller than this is layout/rounding noise, not a gesture. */
const SCROLL_INTENT_TOLERANCE_PX = 2;
/** A reader this close to the live end has arrived back at the bottom. */
const BOTTOM_SNAP_PX = 24;

export interface FollowScrollSample {
  /** Scroll offset the browser reports after the event. */
  scrollTop: number;
  /** Offset remembered before the event (last frame / last scroll). */
  previousTop: number;
  /** Content height remembered before the event. */
  previousHeight: number;
  /** Current content height. */
  height: number;
  /** Current scrollport height. */
  viewport: number;
  /** Whether the viewport was pinned to the live end before the event. */
  following: boolean;
}

export type FollowDecision = "detach" | "follow" | "hold";

/**
 * Decide whether a scroll event was the reader leaving or rejoining the live
 * end. Content growth never moves `scrollTop` (the scroll root opts into
 * `overflow-anchor: none`) and a shrink only clamps it down to the new
 * maximum, so `min(previousTop, maxScrollTop)` is where the browser would have
 * left the viewport without the reader. Anything below that is the reader
 * moving up; anything above it is the reader moving down.
 *
 * A shrink clamp can land exactly on the bottom. That is layout, not a
 * gesture, so it must not re-arm follow (#2072).
 */
export function resolveFollowDecision({
  scrollTop,
  previousTop,
  previousHeight,
  height,
  viewport,
  following,
}: FollowScrollSample): FollowDecision {
  const maxScrollTop = Math.max(0, height - viewport);
  const expectedTop = Math.min(previousTop, maxScrollTop);
  if (scrollTop < expectedTop - SCROLL_INTENT_TOLERANCE_PX) return "detach";

  const clampedByShrink =
    height < previousHeight &&
    scrollTop >= maxScrollTop - SCROLL_INTENT_TOLERANCE_PX;
  if (clampedByShrink) return "hold";

  // Already pinned: growth and reflow are not reasons to release.
  if (following) return "hold";

  const distanceFromBottom = Math.max(0, height - scrollTop - viewport);
  const movedDown = scrollTop > expectedTop + SCROLL_INTENT_TOLERANCE_PX;
  if (movedDown && distanceFromBottom <= BOTTOM_SNAP_PX) return "follow";
  return "hold";
}

/**
 * Whether a pointer landed on the scrollport's own scrollbar rather than on
 * its content. Scrollbar drags fire no wheel/key event, so this is the only
 * way to release follow before the next streamed frame pins the view back.
 */
export function isScrollbarPointer(
  container: Pick<HTMLElement, "clientWidth" | "clientHeight" | "clientLeft" | "clientTop">,
  event: Pick<PointerEvent, "offsetX" | "offsetY" | "clientX" | "clientY">,
  rect: Pick<DOMRect, "left" | "top" | "width" | "height">,
): boolean {
  const { clientWidth, clientHeight } = container;
  if (event.offsetX < 0 || event.offsetY < 0 ||
      event.offsetX >= clientWidth || event.offsetY >= clientHeight) {
    return true;
  }
  // `offsetX/offsetY` can be 0 for synthetic or keyboard-triggered pointer
  // events; fall back to the box geometry so a real scrollbar click still
  // releases follow.
  if (rect.width === 0 || rect.height === 0) return false;
  const x = event.clientX - rect.left - container.clientLeft;
  const y = event.clientY - rect.top - container.clientTop;
  return x < 0 || y < 0 || x >= clientWidth || y >= clientHeight;
}

/** Follow layout changes until the reader intentionally leaves the live end.
 * Observe content size, not an arbitrary post-stream timeout: markdown, images
 * and disclosure animations can settle independently of the transport.
 * The scroll root must retain overflow-anchor: none to avoid competing writers.
 */
export function useChatAutoScroll({
  hasMessages, isStreaming, composerHeight, messageCount,
  lastMessageContent, lastEventCount,
}: AutoScrollOptions) {
  const containerRef = useRef<HTMLDivElement>(null);
  const endRef = useRef<HTMLDivElement>(null);
  const followRef = useRef(true);
  const [isFollowing, setIsFollowing] = useState(true);
  const positionRef = useRef({ top: 0, height: 0, viewport: 0 });

  /** Change follow mode and publish it for the "back to latest" affordance. */
  const setFollowing = useCallback((next: boolean) => {
    if (followRef.current === next) return;
    followRef.current = next;
    setIsFollowing(next);
  }, []);

  /* Callers still use the historical mutable ref (`send` re-arms it, turn
   * jumps release it). Route those writes through `setFollowing` so the
   * button appears/disappears without every caller knowing about the state. */
  const shouldAutoScrollRef = useMemo<{ current: boolean }>(() => ({
    get current() { return followRef.current; },
    set current(next: boolean) { setFollowing(next); },
  }), [setFollowing]);

  const rememberPosition = useCallback((container: HTMLDivElement) => {
    positionRef.current = {
      top: container.scrollTop,
      height: container.scrollHeight,
      viewport: container.clientHeight,
    };
  }, []);

  const pinToBottom = useCallback(() => {
    const container = containerRef.current;
    if (!container) return;
    container.scrollTop = container.scrollHeight;
    rememberPosition(container);
  }, [rememberPosition]);

  useLayoutEffect(() => {
    if (hasMessages && followRef.current) pinToBottom();
  }, [pinToBottom, hasMessages, isStreaming, messageCount,
    lastMessageContent, lastEventCount, composerHeight]);

  const handleScroll = useCallback(() => {
    const container = containerRef.current;
    if (!container) return;
    const previous = positionRef.current;
    const decision = resolveFollowDecision({
      scrollTop: container.scrollTop,
      previousTop: previous.top,
      previousHeight: previous.height,
      height: container.scrollHeight,
      viewport: container.clientHeight,
      following: followRef.current,
    });
    if (decision === "detach") setFollowing(false);
    else if (decision === "follow") setFollowing(true);
    rememberPosition(container);
  }, [rememberPosition, setFollowing]);

  useEffect(() => {
    if (!hasMessages) return;
    const container = containerRef.current;
    if (!container) return;
    let rafId = 0;
    const schedule = () => {
      if (rafId) return;
      rafId = requestAnimationFrame(() => {
        rafId = 0;
        if (followRef.current) pinToBottom();
        else rememberPosition(container);
      });
    };
    // A scrollport's own box does not grow with scrollHeight. Observe its
    // content children too: main chat has a wrapper, PartnerChat has rows.
    const observed = new Set<Element>();
    const resize = new ResizeObserver(schedule);
    const observeContent = () => {
      const targets = new Set<Element>([container, ...container.children]);
      for (const target of observed) {
        if (!targets.has(target)) { resize.unobserve(target); observed.delete(target); }
      }
      for (const target of targets) {
        if (!observed.has(target)) { resize.observe(target); observed.add(target); }
      }
      schedule();
    };
    const mutations = new MutationObserver(observeContent);
    mutations.observe(container, { childList: true, subtree: true });
    container.addEventListener("load", schedule, true);
    observeContent();

    const release = () => setFollowing(false);
    const onWheel = (event: WheelEvent) => { if (event.deltaY < 0) release(); };
    let touchY = 0;
    const onTouchStart = (event: TouchEvent) => { touchY = event.touches[0]?.clientY ?? 0; };
    const onTouchMove = (event: TouchEvent) => {
      const y = event.touches[0]?.clientY ?? 0;
      if (y - touchY > 4) release();
      touchY = y;
    };
    const onKeyDown = (event: KeyboardEvent) => {
      const target = event.target;
      if (target instanceof Element && target.closest("input,textarea,[contenteditable='true']")) return;
      if (["ArrowUp", "PageUp", "Home"].includes(event.key) || (event.key === " " && event.shiftKey)) release();
    };
    const onPointerDown = (event: PointerEvent) => {
      // Opening a trace/citation is deliberate browsing, not late model output.
      // Sending/answering re-arms follow at the existing caller-owned boundary.
      const target = event.target;
      if (target instanceof Element && target.closest("button,a,summary,[role='button']")) {
        release();
        return;
      }
      // A scrollbar drag has no wheel/key event. Release on the press itself
      // so a stream delta cannot pin the view before the drag's first scroll
      // event arrives (#2072).
      if (target === container &&
          isScrollbarPointer(container, event, container.getBoundingClientRect())) {
        release();
      }
    };
    container.addEventListener("wheel", onWheel, { passive: true });
    container.addEventListener("touchstart", onTouchStart, { passive: true });
    container.addEventListener("touchmove", onTouchMove, { passive: true });
    container.addEventListener("keydown", onKeyDown);
    container.addEventListener("pointerdown", onPointerDown, true);
    return () => {
      resize.disconnect(); mutations.disconnect();
      container.removeEventListener("load", schedule, true);
      container.removeEventListener("wheel", onWheel);
      container.removeEventListener("touchstart", onTouchStart);
      container.removeEventListener("touchmove", onTouchMove);
      container.removeEventListener("keydown", onKeyDown);
      container.removeEventListener("pointerdown", onPointerDown, true);
      if (rafId) cancelAnimationFrame(rafId);
    };
  }, [hasMessages, pinToBottom, rememberPosition, setFollowing]);

  const scrollToBottom = useCallback((_behavior: ScrollBehavior) => {
    void _behavior;
    setFollowing(true);
    pinToBottom();
  }, [pinToBottom, setFollowing]);

  return {
    containerRef,
    endRef,
    shouldAutoScrollRef,
    isFollowing,
    scrollToBottom,
    handleScroll,
  };
}
