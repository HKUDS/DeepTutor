"use client";

import { useEffect, useRef, useState } from "react";
import { apiFetch } from "@/lib/api";

// Ceiling for an in-browser office render. docx-preview / exceljs both hold
// the whole document in memory and lay it out synchronously, so a huge file
// would freeze the tab — past this we steer the user to Download instead.
const MAX_BYTES = 25 * 1024 * 1024; // 25 MB

export type BinarySourceState =
  | { kind: "loading" }
  | { kind: "ready"; buffer: ArrayBuffer; objectUrl?: string }
  | { kind: "error"; message: string };

/**
 * Fetch the bytes at *url* as an ArrayBuffer for a client-side office
 * renderer (docx-preview / exceljs). Size-guards via the content-length
 * header and aborts on unmount / url change. Mirrors {@link useTextSource}
 * but yields raw bytes instead of decoded text.
 */
export function useBinarySource(url: string | null, objectMimeType?: string): BinarySourceState {
  const [state, setState] = useState<BinarySourceState>({ kind: "loading" });
  const reqIdRef = useRef(0);

  useEffect(() => {
    if (!url) {
      setState({ kind: "error", message: "Preview source is not available." });
      return;
    }

    const reqId = ++reqIdRef.current;
    const controller = new AbortController();
    let objectUrl: string | undefined;
    setState({ kind: "loading" });

    (async () => {
      try {
        const res = await apiFetch(url, { signal: controller.signal });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const lengthHeader = res.headers.get("content-length");
        if (lengthHeader && Number(lengthHeader) > MAX_BYTES) {
          throw new Error(
            "File is too large to preview. Use the Download button.",
          );
        }
        const buffer = await res.arrayBuffer();
        if (controller.signal.aborted || reqIdRef.current !== reqId) return; // superseded
        if (objectMimeType) objectUrl = URL.createObjectURL(new Blob([buffer], { type: objectMimeType }));
        setState({ kind: "ready", buffer, ...(objectUrl ? { objectUrl } : {}) });
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
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [url, objectMimeType]);

  return state;
}
