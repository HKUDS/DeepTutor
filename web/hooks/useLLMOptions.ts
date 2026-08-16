"use client";

import { useCallback, useEffect, useReducer, useRef, useState } from "react";

import { listLLMOptions } from "@/lib/llm-options";
import {
  INITIAL_LLM_OPTIONS_STATE,
  reduceLLMOptionsState,
} from "@/lib/llm-options-state";
import { createSingleFlight } from "@/lib/single-flight";

interface RefreshOptions {
  force?: boolean;
  /** Keep the last usable catalog visible while synchronizing in the background. */
  background?: boolean;
}

/** Owns model-catalog loading independently from the chat page lifecycle. */
export function useLLMOptions() {
  const [state, dispatch] = useReducer(
    reduceLLMOptionsState,
    INITIAL_LLM_OPTIONS_STATE,
  );
  const latestRequestRef = useRef(0);
  const [loadOptions] = useState(() => createSingleFlight(listLLMOptions));
  const mountedRef = useRef(true);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
    };
  }, []);

  const refresh = useCallback(
    async (options?: RefreshOptions) => {
      const requestId = ++latestRequestRef.current;
      dispatch({
        type: "refresh-started",
        background: options?.background ?? false,
      });

      // Browser lifecycle events commonly arrive as a focus/pageshow/visibility
      // cluster. Coalesce that cluster here, without changing the global cache's
      // force semantics for mutation-sensitive resources such as knowledge bases.
      try {
        const payload = await loadOptions({ force: options?.force });
        if (!mountedRef.current || requestId !== latestRequestRef.current)
          return;
        dispatch({ type: "refresh-succeeded", payload });
      } catch {
        if (!mountedRef.current || requestId !== latestRequestRef.current)
          return;
        dispatch({ type: "refresh-failed" });
      }
    },
    [loadOptions],
  );

  useEffect(() => {
    void refresh();
  }, [refresh]);

  return {
    options: state.options,
    activeDefault: state.activeDefault,
    loading: state.status === "loading",
    error: state.status === "error",
    refresh,
  };
}
