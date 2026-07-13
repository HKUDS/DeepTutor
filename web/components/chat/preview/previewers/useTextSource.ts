"use client";

import { useEffect, useRef, useState } from "react";
import { apiFetch } from "@/lib/api";

const MAX_TEXT_BYTES = 8 * 1024 * 1024; // 8 MB — preview, not a download

export type TextSourceState =
  | { kind: "loading" }
  | { kind: "ready"; text: string }
  | { kind: "error"; message: string };

/**
 * Fetch the text content at *url* (HEAD-checked for size to avoid pulling
 * a 50 MB log into memory). Aborts on unmount.
 *
 * If *fallbackText* is provided and the URL is empty/missing, we render
 * that text instead of fetching. This handles the office-doc case where
 * the backend already extracted plain text.
 */
export function useTextSource(
  url: string | null,
  fallbackText?: string,
): TextSourceState {
  const [state, setState] = useState<TextSourceState>(() =>
    !url && fallbackText !== undefined
      ? { kind: "ready", text: fallbackText }
      : { kind: "loading" },
  );
  const reqIdRef = useRef(0);

  useEffect(() => {
    // Inline fallback (no URL): nothing to fetch.
    if (!url) {
      if (fallbackText !== undefined) {
        setState({ kind: "ready", text: fallbackText });
      } else {
        setState({
          kind: "error",
          message: "Preview source is not available.",
        });
      }
      return;
    }

    const reqId = ++reqIdRef.current;
    const controller = new AbortController();
    setState({ kind: "loading" });

    (async () => {
      try {
        const res = await apiFetch(url, { signal: controller.signal });
        if (!res.ok) {
          throw new Error(`HTTP ${res.status}`);
        }
        const lengthHeader = res.headers.get("content-length");
        if (lengthHeader && Number(lengthHeader) > MAX_TEXT_BYTES) {
          throw new Error(
            "File is too large to preview as text. Use the Download button.",
          );
        }
        const text = await res.text();
        if (reqIdRef.current !== reqId) return; // superseded
        setState({ kind: "ready", text });
      } catch (err) {
        if (controller.signal.aborted) return;
        if (reqIdRef.current !== reqId) return;
        const message =
          err instanceof Error ? err.message : "Failed to load preview";
        setState({ kind: "error", message });
      }
    })();

    return () => {
      controller.abort();
    };
  }, [url, fallbackText]);

  return state;
}
