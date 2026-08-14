"use client";

import { useEffect, useState } from "react";

export type ViewportLayout = "mobile" | "desktop";

const MOBILE_BREAKPOINT = 768;

/**
 * Detects whether the current viewport is mobile or desktop.
 *
 * Uses matchMedia so the browser handles debounce and cross-frame
 * consistency. The coarse-pointer query is an auxiliary signal: a
 * narrow touch device is always mobile, but a wide touch device in a
 * very short viewport (landscape phone) also gets the mobile layout.
 */
export function useResponsiveLayout(): ViewportLayout {
  const [layout, setLayout] = useState<ViewportLayout>("desktop");

  useEffect(() => {
    const mql = window.matchMedia(`(max-width: ${MOBILE_BREAKPOINT - 1}px)`);
    const coarse = window.matchMedia("(pointer: coarse)");

    const update = () => {
      const isNarrow = mql.matches;
      const isCoarse = coarse.matches;
      const isShortViewport = window.innerHeight < 500;
      setLayout(isNarrow || (isCoarse && isShortViewport) ? "mobile" : "desktop");
    };

    update();
    mql.addEventListener("change", update);
    coarse.addEventListener("change", update);
    window.addEventListener("resize", update);
    window.addEventListener("orientationchange", update);

    return () => {
      mql.removeEventListener("change", update);
      coarse.removeEventListener("change", update);
      window.removeEventListener("resize", update);
      window.removeEventListener("orientationchange", update);
    };
  }, []);

  return layout;
}

/**
 * Tracks the iOS Safari dynamic viewport height so bottom-sheets are
 * not obscured by the toolbar. Returns CSS pixels usable for inline styles.
 */
export function useDynamicViewportHeight(): number {
  const [vh, setVh] = useState(0);

  useEffect(() => {
    const update = () => {
      const vv = window.visualViewport;
      setVh(vv ? vv.height : window.innerHeight);
    };
    update();
    window.visualViewport?.addEventListener("resize", update);
    window.visualViewport?.addEventListener("scroll", update);
    window.addEventListener("resize", update);
    return () => {
      window.visualViewport?.removeEventListener("resize", update);
      window.visualViewport?.removeEventListener("scroll", update);
      window.removeEventListener("resize", update);
    };
  }, []);

  return vh;
}
