import { browserStorage } from "@/shared/storage";

/**
 * Which product UI the app renders.
 *
 * - `classic` — the UI as it ships on dev, kept as a frozen snapshot.
 * - `modern`  — the dt-exp redesign, free to keep evolving.
 *
 * A browser-local preference: it picks a presentation, never data, so it does
 * not belong in the account's interface.json. `ThemeScript` mirrors it onto
 * `<html data-ui-layout>` before hydration so variant CSS tokens paint right.
 */
export type UiLayout = "classic" | "modern";

export const UI_LAYOUTS: readonly UiLayout[] = ["classic", "modern"];
export const DEFAULT_UI_LAYOUT: UiLayout = "modern";
export const UI_LAYOUT_STORAGE_KEY = "deeptutor.ui-layout";
export const UI_LAYOUT_EVENT = "deeptutor:ui-layout";
export const UI_LAYOUT_ATTRIBUTE = "data-ui-layout";

export function isUiLayout(value: unknown): value is UiLayout {
  return value === "classic" || value === "modern";
}

export function readStoredUiLayout(): UiLayout {
  if (typeof window === "undefined") return DEFAULT_UI_LAYOUT;
  const stored = browserStorage.readRaw("local", UI_LAYOUT_STORAGE_KEY);
  return isUiLayout(stored) ? stored : DEFAULT_UI_LAYOUT;
}

export function applyUiLayoutToDocument(layout: UiLayout): void {
  if (typeof document === "undefined") return;
  document.documentElement.setAttribute(UI_LAYOUT_ATTRIBUTE, layout);
}

export function writeStoredUiLayout(layout: UiLayout): void {
  if (typeof window === "undefined") return;
  browserStorage.writeRaw("local", UI_LAYOUT_STORAGE_KEY, layout);
  applyUiLayoutToDocument(layout);
  window.dispatchEvent(new CustomEvent(UI_LAYOUT_EVENT, { detail: { layout } }));
}
