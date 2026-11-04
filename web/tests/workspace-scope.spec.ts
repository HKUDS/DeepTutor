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
  const original = window.location;
  const secure = new URL("https://deeptutor.example.org/chat?dt_workspace=ws_c");
  Object.defineProperty(window, "location", { value: secure, writable: true, configurable: true });
  try {
    const socket = wsUrl("/ws/books");
    expect(socket).toMatch(/^wss:\/\//);
    expect(new URL(socket).host).toBe("deeptutor.example.org");
    expect(new URL(socket).pathname).toBe("/ws/books");
    expect(new URL(socket).searchParams.get("dt_workspace")).toBe("ws_c");
  } finally {
    Object.defineProperty(window, "location", { value: original, writable: true, configurable: true });
  }
});

it("leaves an explicitly scoped https URL's origin intact and only swaps the scheme", () => {
  window.history.replaceState(null, "", "/chat?dt_workspace=ws_a");
  const pinned = wsUrl("https://media.example.org/ws?signature=abc");
  expect(pinned).toBe("wss://media.example.org/ws?signature=abc");
});

it("keeps apiUrl relative so fetch() still resolves it against the document", () => {
  window.history.replaceState(null, "", "/chat?dt_workspace=ws_a");
  // Only sockets need the absolute form; getting this wrong would break
  // every proxied fetch.
  expect(apiUrl("/api/books")).toBe("/api/books?dt_workspace=ws_a");
});

it("gives the turn runtime an absolute default socket URL", () => {
  window.history.replaceState(null, "", "/chat?dt_workspace=ws_turn");
  // The runtime builds its own default and does not go through wsUrl, so it
  // needs the same guarantee: a browser-rejectable relative path never
  // reaches new WebSocket() (#2404).
  const client = new TurnRuntimeClient({
    onEvent: () => {},
    socketFactory: () => {
      throw new Error("unused");
    },
  });
  const url = (client as unknown as { options: { url: string } }).options.url;
  expect(url).toMatch(/^wss?:\/\//);
  expect(new URL(url).pathname).toBe("/ws");
  expect(new URL(url).searchParams.get("dt_workspace")).toBe("ws_turn");
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
