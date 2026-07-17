"use client";

/**
 * MathGraphContext — bridges automatic math-graph detection in chat messages
 * to the SessionViewerPanel's imperative `openMathGraphTab`.
 *
 * Pattern mirrors GeogebraTabContext (same bridge approach):
 *  - Components that detect math call `useMathGraphController().openGraphTab()`
 *  - The chat page wires the viewer panel ref via `setOpenHandler()`
 */

import {
  createContext,
  type ReactNode,
  useCallback,
  useContext,
  useMemo,
  useRef,
} from "react";

/* ------------------------------------------------------------------ */
/*  Types                                                              */
/* ------------------------------------------------------------------ */

export interface MathGraphPayload {
  /** Stable dedup id — typically a hash/slug of the expression set. */
  id: string;
  /** Tab display label. */
  title: string;
  /** Desmos-ready expression strings. */
  expressions: string[];
}

export interface MathGraphController {
  /** Open or focus a math graph tab in the side viewer. */
  openGraphTab(payload: MathGraphPayload): void;
  /** The chat page registers the viewer-panel's openMathGraphTab here. */
  setOpenHandler(
    handler: ((payload: MathGraphPayload) => void) | null,
  ): void;
}

/* ------------------------------------------------------------------ */
/*  Context                                                            */
/* ------------------------------------------------------------------ */

const MathGraphCtx = createContext<MathGraphController | null>(null);

export function MathGraphProvider({ children }: { children: ReactNode }) {
  const handlerRef = useRef<((payload: MathGraphPayload) => void) | null>(
    null,
  );

  const openGraphTab = useCallback((payload: MathGraphPayload) => {
    const handler = handlerRef.current;
    if (handler) {
      handler(payload);
    } else {
      console.warn(
        "[MathGraphContext] No open handler registered; ignoring openGraphTab()",
      );
    }
  }, []);

  const setOpenHandler = useCallback(
    (handler: ((payload: MathGraphPayload) => void) | null) => {
      handlerRef.current = handler;
    },
    [],
  );

  const controller = useMemo<MathGraphController>(
    () => ({ openGraphTab, setOpenHandler }),
    [openGraphTab, setOpenHandler],
  );

  return (
    <MathGraphCtx.Provider value={controller}>
      {children}
    </MathGraphCtx.Provider>
  );
}

/**
 * Hook for descendants that need to open a math-graph tab.
 * Returns null when no provider is mounted — treat as "feature unavailable".
 */
export function useMathGraph(): MathGraphController | null {
  return useContext(MathGraphCtx);
}
