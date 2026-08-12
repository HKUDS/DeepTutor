import type { LLMOption, LLMOptionsResponse } from "@/lib/llm-options";
import type { LLMSelection } from "@/lib/unified-ws";

export type LLMOptionsStatus = "loading" | "ready" | "error";

export interface LLMOptionsState {
  options: LLMOption[];
  activeDefault: LLMSelection | null;
  status: LLMOptionsStatus;
}

export type LLMOptionsAction =
  | { type: "refresh-started"; background: boolean }
  | { type: "refresh-succeeded"; payload: LLMOptionsResponse }
  | { type: "refresh-failed" };

export const INITIAL_LLM_OPTIONS_STATE: LLMOptionsState = {
  options: [],
  activeDefault: null,
  status: "loading",
};

/**
 * State transitions for the model selector's stale-while-revalidate behavior.
 *
 * A page-return refresh is a catalog synchronization, not a model startup. It
 * therefore keeps the last usable catalog visible and only replaces it after a
 * successful response. Initial loading still has an explicit loading/error
 * state because there is no usable catalog to fall back to yet.
 */
export function reduceLLMOptionsState(
  state: LLMOptionsState,
  action: LLMOptionsAction,
): LLMOptionsState {
  switch (action.type) {
    case "refresh-started":
      return action.background ? state : { ...state, status: "loading" };
    case "refresh-succeeded":
      return {
        options: action.payload.options,
        activeDefault: action.payload.active,
        status: "ready",
      };
    case "refresh-failed":
      return state.options.length > 0
        ? { ...state, status: "ready" }
        : { ...state, status: "error" };
  }
}
