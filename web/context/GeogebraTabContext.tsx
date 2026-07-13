"use client";

/**
 * GeogebraTabContext — bridges in-message "open in viewer" CTAs to the
 * SessionViewerPanel's imperative ``openGeogebraTab``.
 *
 * Pattern mirrors QuizFollowupContext (but much smaller — no persistent
 * thread state). A CTA inside the markdown renderer calls
 * ``useGeogebraTabOpener()`` and dispatches; the chat page wires the
 * controller's open-handler to the viewer panel ref via
 * ``setOpenHandler``.
 */

import {
  createContext,
  type ReactNode,
  useCallback,
  useContext,
  useMemo,
  useRef,
} from "react";

export interface GeogebraTabPayload {
  /** Stable id for tab dedupe — same script + title should map to same tab. */
  id: string;
  /** Display label on the tab strip. */
  title: string;
  /** Raw ggbscript body (GeoGebra commands, one per line, with optional `#` comments). */
  script: string;
}

export interface GeogebraTabController {
  /** Open or focus a GeoGebra tab in the side viewer. */
  openTab(payload: GeogebraTabPayload): void;
  /** The chat page registers the viewer-panel's ``openGeogebraTab`` here. */
  setOpenHandler(handler: ((payload: GeogebraTabPayload) => void) | null): void;
}

const GeogebraTabCtx = createContext<GeogebraTabController | null>(null);

export function GeogebraTabProvider({ children }: { children: ReactNode }) {
  // The handler is mutable — the chat page can swap it via setOpenHandler
  // without forcing every consumer to re-render. Stored in a ref so the
  // controller object itself stays stable across renders.
  const handlerRef = useRef<((payload: GeogebraTabPayload) => void) | null>(
    null,
  );

  const openTab = useCallback((payload: GeogebraTabPayload) => {
    const handler = handlerRef.current;
    if (handler) {
      handler(payload);
    } else {
      // No viewer registered yet (or page hasn't mounted the bridge). The
      // CTA click is a no-op rather than throwing; the user can retry once
      // the viewer is available.
      console.warn(
        "[GeogebraTabContext] No open handler registered; ignoring openTab()",
      );
    }
  }, []);

  const setOpenHandler = useCallback(
    (handler: ((payload: GeogebraTabPayload) => void) | null) => {
      handlerRef.current = handler;
    },
    [],
  );

  const controller = useMemo<GeogebraTabController>(
    () => ({ openTab, setOpenHandler }),
    [openTab, setOpenHandler],
  );

  return (
    <GeogebraTabCtx.Provider value={controller}>
      {children}
    </GeogebraTabCtx.Provider>
  );
}

/**
 * Hook for descendants that need to open a GeoGebra tab. Returns ``null``
 * when no provider is mounted — callers should treat that as "feature
 * unavailable" and degrade gracefully (e.g. don't render the CTA at all).
 */
export function useGeogebraTabOpener(): GeogebraTabController | null {
  return useContext(GeogebraTabCtx);
}
