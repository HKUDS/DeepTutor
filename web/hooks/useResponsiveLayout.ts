"use client";

import { useEffect, useState } from "react";

export type ViewportLayout = "mobile" | "desktop";

const MOBILE_BREAKPOINT = 768;

/** Detect whether the current viewport should use the mobile or desktop layout. */
export function useResponsiveLayout(): ViewportLayout {
  const [layout, setLayout] = useState<ViewportLayout>("desktop");

  useEffect(() => {
    const narrowQuery = window.matchMedia(`(max-width: ${MOBILE_BREAKPOINT - 1}px)`);
    const coarseQuery = window.matchMedia("(pointer: coarse)");

    const update = () => {
      const isNarrow = narrowQuery.matches;
      const isCoarse = coarseQuery.matches;
      const isShortViewport = window.innerHeight < 500;
      setLayout(isNarrow || (isCoarse && isShortViewport) ? "mobile" : "desktop");
    };

    update();
    narrowQuery.addEventListener("change", update);
    coarseQuery.addEventListener("change", update);
    window.addEventListener("resize", update);
    window.addEventListener("orientationchange", update);

    return () => {
      narrowQuery.removeEventListener("change", update);
      coarseQuery.removeEventListener("change", update);
      window.removeEventListener("resize", update);
      window.removeEventListener("orientationchange", update);
    };
  }, []);

  return layout;
}

/** Track the iOS Safari dynamic viewport height for bottom sheets. */
export function useDynamicViewportHeight(): number {
  const [viewportHeight, setViewportHeight] = useState(0);

  useEffect(() => {
    const update = () => {
      const visualViewport = window.visualViewport;
      setViewportHeight(visualViewport ? visualViewport.height : window.innerHeight);
    };

    update();
    visualViewport?.addEventListener("resize", update);
    visualViewport?.addEventListener("scroll", update);
    window.addEventListener("resize", update);
    return () => {
      visualViewport?.removeEventListener("resize", update);
      visualViewport?.removeEventListener("scroll", update);
      window.removeEventListener("resize", update);
    };
  }, []);

  return viewportHeight;
}
