"use client";

import { useSyncExternalStore } from "react";
import {
  DEFAULT_UI_LAYOUT,
  UI_LAYOUT_EVENT,
  UI_LAYOUT_STORAGE_KEY,
  applyUiLayoutToDocument,
  readStoredUiLayout,
  type UiLayout,
} from "@/lib/ui-layout";

function subscribe(onChange: () => void): () => void {
  const onStorage = (event: StorageEvent) => {
    if (event.key !== UI_LAYOUT_STORAGE_KEY) return;
    // Another tab switched; keep this tab's <html> tokens in step.
    applyUiLayoutToDocument(readStoredUiLayout());
    onChange();
  };
  window.addEventListener(UI_LAYOUT_EVENT, onChange);
  window.addEventListener("storage", onStorage);
  return () => {
    window.removeEventListener(UI_LAYOUT_EVENT, onChange);
    window.removeEventListener("storage", onStorage);
  };
}

/** The active UI layout. SSR and hydration render the default, then adopt. */
export function useUiLayout(): UiLayout {
  return useSyncExternalStore(subscribe, readStoredUiLayout, () => DEFAULT_UI_LAYOUT);
}
