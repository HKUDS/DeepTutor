"use client";

import { useCallback, useEffect, useRef } from "react";

interface AutoScrollOptions {
  hasMessages: boolean;
  isStreaming: boolean;
  composerHeight: number;
  messageCount: number;
  lastMessageContent?: string;
  lastEventCount?: number;
}

const THROTTLE_MS = 80;

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
  const lastScrollTimeRef = useRef(0);
  const pendingRafRef = useRef(0);

  const scrollToBottom = useCallback((behavior: ScrollBehavior) => {
    const container = containerRef.current;
    if (!container) return;
    container.scrollTo({
      top: container.scrollHeight,
      behavior,
    });
  }, []);

  useEffect(() => {
    if (!shouldAutoScrollRef.current) return;

    const now = performance.now();
    const elapsed = now - lastScrollTimeRef.current;

    if (isStreaming && elapsed < THROTTLE_MS) {
      if (pendingRafRef.current) return;
      pendingRafRef.current = window.setTimeout(() => {
        pendingRafRef.current = 0;
        if (shouldAutoScrollRef.current) {
          scrollToBottom("instant");
          lastScrollTimeRef.current = performance.now();
        }
      }, THROTTLE_MS - elapsed);
      return;
    }

    const raf = window.requestAnimationFrame(() => {
      scrollToBottom(isStreaming ? "instant" : "smooth");
      lastScrollTimeRef.current = performance.now();
    });

    return () => {
      window.cancelAnimationFrame(raf);
      if (pendingRafRef.current) {
        clearTimeout(pendingRafRef.current);
        pendingRafRef.current = 0;
      }
    };
  }, [isStreaming, lastEventCount, lastMessageContent, messageCount, scrollToBottom]);

  useEffect(() => {
    if (!hasMessages || !shouldAutoScrollRef.current) return;
    const raf = window.requestAnimationFrame(() => {
      scrollToBottom("instant");
    });
    return () => window.cancelAnimationFrame(raf);
  }, [composerHeight, hasMessages, scrollToBottom]);

  // After streaming ends, dynamically-loaded components (e.g. MathAnimatorViewer
  // via next/dynamic) may render and grow the content height. Detect that and
  // scroll to bottom so the user can see the full result.
  useEffect(() => {
    if (isStreaming) return;

    const container = containerRef.current;
    if (!container) return;

    let prevHeight = container.scrollHeight;
    let rafId = 0;

    const check = () => {
      if (rafId) return;
      rafId = requestAnimationFrame(() => {
        rafId = 0;
        const curHeight = container.scrollHeight;
        if (curHeight > prevHeight && shouldAutoScrollRef.current) {
          scrollToBottom("instant");
        }
        prevHeight = curHeight;
      });
    };

    const mo = new MutationObserver(check);
    mo.observe(container, { childList: true, subtree: true });

    return () => {
      mo.disconnect();
      if (rafId) cancelAnimationFrame(rafId);
    };
  }, [isStreaming, scrollToBottom]);

  const handleScroll = useCallback(() => {
    const container = containerRef.current;
    if (!container) return;
    const distanceFromBottom =
      container.scrollHeight - container.scrollTop - container.clientHeight;
    shouldAutoScrollRef.current = distanceFromBottom < 80;
  }, []);

  return {
    containerRef,
    endRef,
    shouldAutoScrollRef,
    scrollToBottom,
    handleScroll,
  };
}
