"use client";

import { useCallback, useEffect, useRef, useState } from "react";

/**
 * Expansion state for the collapse-to-icon toolbar selectors (persona /
 * model). Expands on hover, focus or while the menu is open; on leave or
 * close it LINGERS for ~1.2s before collapsing, so the user can read the
 * (possibly just-changed) selection instead of having it snap shut.
 */
export function useLingerExpand(open: boolean, lingerMs = 1200) {
  const [hovered, setHovered] = useState(false);
  const [lingering, setLingering] = useState(false);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const clearTimer = useCallback(() => {
    if (timerRef.current) clearTimeout(timerRef.current);
    timerRef.current = null;
  }, []);

  /**
   * Hold the expanded state for ``lingerMs`` before collapsing. Fired by
   * mouse-leave automatically; menu owners should also call it wherever
   * they close the menu (selection / outside click) so the just-changed
   * label stays readable for a beat.
   */
  const linger = useCallback(() => {
    clearTimer();
    setLingering(true);
    timerRef.current = setTimeout(() => setLingering(false), lingerMs);
  }, [clearTimer, lingerMs]);

  useEffect(() => clearTimer, [clearTimer]);

  const onMouseEnter = useCallback(() => {
    clearTimer();
    setLingering(false);
    setHovered(true);
  }, [clearTimer]);

  const onMouseLeave = useCallback(() => {
    setHovered(false);
    linger();
  }, [linger]);

  return {
    expanded: hovered || open || lingering,
    linger,
    triggerProps: {
      onMouseEnter,
      onMouseLeave,
      onFocus: onMouseEnter,
      onBlur: onMouseLeave,
    },
  };
}
