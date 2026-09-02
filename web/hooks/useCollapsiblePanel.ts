"use client";

import { useCallback, useEffect, useState } from "react";
import { browserStorage } from "@/shared/storage";

/**
 * Persisted, per-key collapsed/expanded state for side panels.
 *
 * Initial state is always `defaultCollapsed` so SSR and the first client
 * render match. After mount we hydrate from localStorage.
 */
export function useCollapsiblePanel(
  storageKey: string,
  defaultCollapsed = false,
) {
  const [collapsed, setCollapsedState] = useState(defaultCollapsed);

  useEffect(() => {
    if (typeof window === "undefined") return;
    try {
      const stored = browserStorage.readRaw(
        "local",
        `panel:${storageKey}:collapsed`,
      );
      if (stored != null) {
        // eslint-disable-next-line react-hooks/set-state-in-effect
        setCollapsedState(stored === "1");
      }
    } catch {
      // localStorage unavailable; keep default
    }
  }, [storageKey]);

  const setCollapsed = useCallback(
    (value: boolean | ((prev: boolean) => boolean)) => {
      setCollapsedState((prev) => {
        const next = typeof value === "function" ? value(prev) : value;
        try {
          if (typeof window !== "undefined") {
            browserStorage.writeRaw(
              "local",
              `panel:${storageKey}:collapsed`,
              next ? "1" : "0",
            );
          }
        } catch {
          // quota / privacy mode; ignore
        }
        return next;
      });
    },
    [storageKey],
  );

  const toggle = useCallback(() => {
    setCollapsed((prev) => !prev);
  }, [setCollapsed]);

  return { collapsed, setCollapsed, toggle };
}
