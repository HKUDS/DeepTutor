"use client";

import { useEffect, useRef } from "react";

import { wsUrl } from "@/lib/api";
import type { BookWsEvent } from "@/lib/book-ws-operation";

const BOOK_WS_PATH = "/api/v1/book/ws";

// Backs off quickly at first — a dropped socket is usually a transient blip —
// then settles so a backend that is genuinely down isn't hammered.
const RECONNECT_DELAYS_MS = [500, 1_000, 2_000, 5_000, 10_000];

/**
 * Subscribe to a book's live event stream for as long as it is open.
 *
 * Separate from `runBookSocketOperation`, which owns a socket per action and
 * closes it on the result. Compilation outlives any single action, so watching
 * a book needs a connection that outlives them too: this one stays open,
 * reconnects on drop, and re-subscribes on the way back — the backend replays
 * recent history on subscribe, so a reconnect catches up on what it missed.
 *
 * `onEvent` is held in a ref, so callers may pass an inline closure without
 * causing the socket to tear down and reconnect on every render.
 */
export function useBookStream(
  bookId: string | null,
  onEvent: (event: BookWsEvent) => void,
): void {
  const handlerRef = useRef(onEvent);
  useEffect(() => {
    handlerRef.current = onEvent;
  });

  useEffect(() => {
    if (!bookId) return;

    let disposed = false;
    let socket: WebSocket | null = null;
    let retry = 0;
    let reconnectTimer: ReturnType<typeof setTimeout> | undefined;

    const connect = () => {
      if (disposed) return;

      let next: WebSocket;
      try {
        next = new WebSocket(wsUrl(BOOK_WS_PATH));
      } catch {
        scheduleReconnect();
        return;
      }
      socket = next;

      next.onopen = () => {
        retry = 0;
        try {
          next.send(JSON.stringify({ type: "subscribe", book_id: bookId }));
        } catch {
          // The close handler will schedule a reconnect.
        }
      };

      next.onmessage = (message: MessageEvent<string>) => {
        let event: BookWsEvent;
        try {
          event = JSON.parse(message.data) as BookWsEvent;
        } catch {
          return;
        }
        handlerRef.current(event);
      };

      next.onclose = () => {
        socket = null;
        scheduleReconnect();
      };

      // `onclose` always follows `onerror`, so reconnection is handled there.
      next.onerror = () => {};
    };

    const scheduleReconnect = () => {
      if (disposed) return;
      const delay =
        RECONNECT_DELAYS_MS[Math.min(retry, RECONNECT_DELAYS_MS.length - 1)];
      retry += 1;
      reconnectTimer = setTimeout(connect, delay);
    };

    connect();

    return () => {
      disposed = true;
      if (reconnectTimer) clearTimeout(reconnectTimer);
      if (socket) {
        // Drop the handlers first so the teardown close doesn't look like a
        // dropped connection and schedule a reconnect for a book we left.
        socket.onclose = null;
        socket.onerror = null;
        socket.onmessage = null;
        try {
          socket.close();
        } catch {
          // Already closing — nothing to do.
        }
      }
    };
  }, [bookId]);
}

/** Normalized `kind` for a book event, wherever the backend put it. */
export function bookEventKind(event: BookWsEvent): string {
  const metadata =
    (event.metadata as Record<string, unknown> | undefined) || {};
  return String(metadata.kind || event.content || "");
}

/** The page a book event refers to, or `null` for book-level events. */
export function bookEventPageId(event: BookWsEvent): string | null {
  const metadata =
    (event.metadata as Record<string, unknown> | undefined) || {};
  const pageId = metadata.page_id;
  return typeof pageId === "string" && pageId ? pageId : null;
}
