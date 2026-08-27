import type { FocusState } from "@/lib/reading-api";

/** UI guidance only; durable progression is enforced by the server. */
export function focusAllowsLocator(
  focus: FocusState | null,
  locator: number,
): boolean {
  return !focus?.active || locator <= focus.unlocked_through_locator;
}

export function focusProgress(focus: FocusState | null): {
  passed: number;
  total: number;
} {
  if (!focus) return { passed: 0, total: 0 };
  return {
    passed: focus.passed_checkpoint_ids.length,
    total: focus.checkpoints.length,
  };
}
