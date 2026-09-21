import { beforeEach, expect, it } from "vitest";
import { activeWorkspaceId, scopedUrl } from "@/lib/workspace-scope";
import { apiUrl, wsUrl } from "@/lib/api";

beforeEach(() => {
  sessionStorage.clear();
  window.history.replaceState(null, "", "/learning");
});

it("uses the default workspace and keeps explicitly scoped URLs immutable", () => {
  expect(activeWorkspaceId()).toBe("");
  expect(apiUrl("/api/reading/materials")).toBe("/api/reading/materials?dt_workspace=");
  const fixed = scopedUrl("/files/attachments/a/b/file.pdf", "ws_a");
  window.history.replaceState(null, "", "/learning?dt_workspace=ws_b");
  expect(scopedUrl(fixed)).toBe(fixed);
});

it("remembers a scope per tab across module navigation and pins sockets", () => {
  window.history.replaceState(null, "", "/learning?dt_workspace=ws_a");
  expect(activeWorkspaceId()).toBe("ws_a");
  const socket = wsUrl("/ws");
  window.history.replaceState(null, "", "/learning/books");
  expect(activeWorkspaceId()).toBe("");
  expect(socket).toBe("/ws?dt_workspace=ws_a");
  window.history.replaceState(null, "", "/learning?dt_workspace=");
  expect(activeWorkspaceId()).toBe("");
  expect(socket).toBe("/ws?dt_workspace=ws_a");
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

it("does not let an earlier tab preference select a new task workspace", () => {
  sessionStorage.setItem('deeptutor:workspace', 'ws_old');
  window.history.replaceState(null, '', '/chat');
  expect(activeWorkspaceId()).toBe('');
});
