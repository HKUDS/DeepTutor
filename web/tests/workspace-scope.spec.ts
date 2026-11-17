import { beforeEach, expect, it, vi } from "vitest";
import { activeWorkspaceId, navigateTask, rememberWorkspaceId, scopedUrl } from "@/lib/workspace-scope";
import { apiUrl, wsUrl } from "@/lib/api";
import { TurnRuntimeClient } from "@/features/chat/transport/TurnRuntimeClient";

beforeEach(() => {
  sessionStorage.clear();
  localStorage.clear();
  window.history.replaceState(null, "", "/learning?dt_workspace=");
  activeWorkspaceId();
});

/** The absolute origin a socket should be pinned to, in socket scheme. */
function socketOrigin(): string {
  return window.location.origin.replace(/^http:/, "ws:").replace(/^https:/, "wss:");
}

it("uses the default workspace and keeps explicitly scoped URLs immutable", () => {
  expect(activeWorkspaceId()).toBe("");
  expect(apiUrl("/api/reading/materials")).toBe("/api/reading/materials?dt_workspace=");
  const fixed = scopedUrl("/files/attachments/a/b/file.pdf", "ws_a");
  window.history.replaceState(null, "", "/learning?dt_workspace=ws_b");
  expect(scopedUrl(fixed)).toBe(fixed);
});

it("stays in the tab's workspace when a URL names none, and pins sockets", () => {
  window.history.replaceState(null, "", "/learning?dt_workspace=ws_a");
  expect(activeWorkspaceId()).toBe("ws_a");
  const socket = wsUrl("/ws");
  window.history.replaceState(null, "", "/learning/books");
  expect(activeWorkspaceId()).toBe("ws_a");
  expect(apiUrl("/api/books")).toBe("/api/books?dt_workspace=ws_a");
  // Only an explicit scope leaves it, General included.
  window.history.replaceState(null, "", "/learning?dt_workspace=");
  expect(activeWorkspaceId()).toBe("");
  window.history.replaceState(null, "", "/chat");
  expect(activeWorkspaceId()).toBe("");
  expect(socket).toBe(`${socketOrigin()}/ws?dt_workspace=ws_a`);
});

it("gives sockets an absolute ws: URL that WebSocket accepts", () => {
  window.history.replaceState(null, "", "/chat?dt_workspace=ws_a");
  // The constructor rejects a relative path outright (#2404).
  expect(() => new WebSocket(wsUrl("/ws"))).not.toThrow();
  expect(wsUrl("/ws")).toMatch(/^ws:\/\//);
  expect(new URL(wsUrl("/ws")).pathname).toBe("/ws");
});

it("maps an https page to wss: and keeps the scoped query", () => {
  const descriptor = Object.getOwnPropertyDescriptor(window, "location")!;
  const secure = new URL("https://deeptutor.example.org/chat?dt_workspace=ws_c");
  Object.defineProperty(window, "location", { value: secure, writable: true, configurable: true });
  try {
    const socket = wsUrl("/ws/books");
    expect(socket).toMatch(/^wss:\/\//);
    expect(new URL(socket).host).toBe("deeptutor.example.org");
    expect(new URL(socket).pathname).toBe("/ws/books");
    expect(new URL(socket).searchParams.get("dt_workspace")).toBe("ws_c");
  } finally {
    // Restore the accessor, not a data slot: assigning `{ value: original }`
    // turns `window.location` into a writable property and a later
    // `window.location = "/x"` in another test would silently replace it.
    Object.defineProperty(window, "location", descriptor);
  }
});

it("leaves an explicitly scoped https URL's origin intact and only swaps the scheme", () => {
  window.history.replaceState(null, "", "/chat?dt_workspace=ws_a");
  const pinned = wsUrl("https://media.example.org/ws?signature=abc");
  expect(pinned).toBe("wss://media.example.org/ws?signature=abc");
});

it("keeps apiUrl relative so the browser resolves it against the document", () => {
  window.history.replaceState(null, "", "/chat?dt_workspace=ws_a");
  // Only sockets need the absolute form; getting this wrong would break
  // every proxied request.
  expect(apiUrl("/api/books")).toBe("/api/books?dt_workspace=ws_a");
});

it("gives the turn runtime an absolute default socket URL", () => {
  window.history.replaceState(null, "", "/chat?dt_workspace=ws_turn");
  // The runtime builds its own default and does not go through wsUrl, so it
  // needs the same guarantee. Assert through the factory rather than the
  // private options object: the path that matters is the one `connect()`
  // hands to `new WebSocket()`, so a later change that relativises at the
  // call site has to fail here (#2404).
  let seen: string | undefined;
  const client = new TurnRuntimeClient({
    onEvent: () => {},
    socketFactory: (url) => {
      seen = url;
      throw new Error("stop after capture");
    },
  });
  client.connect();
  expect(seen).toBeDefined();
  expect(seen).toMatch(/^wss?:\/\//);
  const parsed = new URL(seen!);
  expect(parsed.pathname).toBe("/ws");
  expect(parsed.searchParams.get("dt_workspace")).toBe("ws_turn");
});

it("drops a fragment, which the WebSocket constructor rejects", () => {
  window.history.replaceState(null, "", "/chat?dt_workspace=ws_a");
  // Verified in Chromium 156: a URL with a fragment throws rather than
  // connecting, so it must not survive into the socket URL.
  const socket = wsUrl("/ws#lobby");
  expect(socket).toBe(`${socketOrigin()}/ws?dt_workspace=ws_a`);
  expect(socket).not.toContain("#");
  expect(() => new WebSocket(socket)).not.toThrow();
});

it("leaves an already absolute ws: URL alone and keeps it on wss:", () => {
  // A caller that already names a secure endpoint must not be downgraded to
  // cleartext: that is the regression this whole change exists to prevent.
  expect(wsUrl("wss://media.example.org/ws")).toBe("wss://media.example.org/ws");
  expect(wsUrl("ws://media.example.org/ws")).toBe("ws://media.example.org/ws");
  // The fragment is stripped here too, or the constructor rejects the URL.
  expect(wsUrl("wss://media.example.org/ws#top")).toBe("wss://media.example.org/ws");
});

it("does not append workspace identity to external or signed URLs", () => {
  expect(scopedUrl("https://example.org/video?signature=abc", "ws_a")).toBe("https://example.org/video?signature=abc");
  expect(scopedUrl("//example.org/video", "ws_a")).toBe("//example.org/video");
});

it("pins same-origin absolute URLs and honors legacy workspace links", () => {
  expect(scopedUrl(`${window.location.origin}/api/books`, "ws_a"))
    .toBe(`${window.location.origin}/api/books?dt_workspace=ws_a`);
  expect(scopedUrl("/chat?workspace=ws_b", "ws_a"))
    .toBe("/chat?workspace=ws_b&dt_workspace=ws_b");
});

it("keeps bare task navigation in the current workspace", () => {
  window.history.replaceState(null, "", "/chat?dt_workspace=ws_a");
  const push = vi.fn();
  navigateTask("/kanban", push);
  expect(push).toHaveBeenCalledWith("/kanban?dt_workspace=ws_a");
});

it("records the last workspace for the next fresh tab", () => {
  rememberWorkspaceId("ws_last");
  expect(localStorage.getItem("deeptutor:workspace")).toBe("ws_last");
  expect(sessionStorage.getItem("deeptutor:workspace")).toBe("ws_last");
});
