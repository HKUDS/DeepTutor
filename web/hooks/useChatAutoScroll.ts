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
  const shouldAutoScrollRef = useRef(true);
  const positionRef = useRef({ top: 0, height: 0, viewport: 0 });

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
    if (hasMessages && shouldAutoScrollRef.current) pinToBottom();
  }, [pinToBottom, hasMessages, isStreaming, messageCount,
    lastMessageContent, lastEventCount, composerHeight]);

  const handleScroll = useCallback(() => {
    const container = containerRef.current;
    if (!container) return;
    const previous = positionRef.current;
    const sameLayout = previous.height === container.scrollHeight &&
      previous.viewport === container.clientHeight;
    // The browser clamps scrollTop when content shrinks. That is not a user
    // gesture. Neither clamping nor delayed growth may release/re-arm follow.
    if (sameLayout) {
      const remaining = container.scrollHeight - container.scrollTop - container.clientHeight;
      if (remaining < 80 && (shouldAutoScrollRef.current || container.scrollTop > previous.top + 4)) {
        shouldAutoScrollRef.current = true;
      }
      else if (container.scrollTop < previous.top - 4) shouldAutoScrollRef.current = false;
    }
    rememberPosition(container);
  }, [rememberPosition]);

  useEffect(() => {
    if (!hasMessages) return;
    const container = containerRef.current;
    if (!container) return;
    let rafId = 0;
    const schedule = () => {
      if (rafId) return;
      rafId = requestAnimationFrame(() => {
        rafId = 0;
        if (shouldAutoScrollRef.current) pinToBottom();
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

    const release = () => { shouldAutoScrollRef.current = false; };
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
      if (target instanceof Element && target.closest("button,a,summary,[role='button']")) release();
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
  }, [hasMessages, pinToBottom, rememberPosition]);

  const scrollToBottom = useCallback((_behavior: ScrollBehavior) => {
    void _behavior;
    pinToBottom();
  }, [pinToBottom]);

  return { containerRef, endRef, shouldAutoScrollRef, scrollToBottom, handleScroll };
}
