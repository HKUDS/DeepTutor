import { afterEach, describe, expect, it, vi } from "vitest";

import {
  clipText,
  notifyDesktopRoundComplete,
} from "@/features/desktop/round-notification";
import { fileFromLocalFile, isDesktopShell } from "@/lib/desktop-shell";

/**
 * The desktop bridge is the one place where web code talks to the Tauri shell.
 * Two things matter for Web mode staying untouched: `isDesktopShell()` must be
 * false in a browser, and every helper that posts a notification must be a
 * no-op there instead of a thrown error.
 */

type Invoke = (command: string, args?: unknown) => Promise<unknown>;

function installShell(invoke: Invoke) {
  (window as unknown as { __TAURI__?: unknown }).__TAURI__ = {
    core: { invoke },
  };
}

afterEach(() => {
  delete (window as unknown as { __TAURI__?: unknown }).__TAURI__;
});

describe("desktop shell detection", () => {
  it("reports a browser as not desktop", () => {
    expect(isDesktopShell()).toBe(false);
  });

  it("reports the shell when the Tauri bridge is injected", () => {
    installShell(async () => null);
    expect(isDesktopShell()).toBe(true);
  });

  it("does not treat an unrelated global as the shell", () => {
    (window as unknown as { __TAURI__?: unknown }).__TAURI__ = { core: {} };
    expect(isDesktopShell()).toBe(false);
  });
});

describe("notification copy", () => {
  it("collapses whitespace and keeps short text intact", () => {
    expect(clipText("  hello   world\n", 40)).toBe("hello world");
  });

  it("marks where a long answer was cut", () => {
    const clipped = clipText("a".repeat(200), 20);
    expect(clipped.length).toBeLessThanOrEqual(20);
    expect(clipped.endsWith("…")).toBe(true);
  });
});

describe("round-complete notifications", () => {
  it("stays silent in a browser", () => {
    const invoke = vi.fn(async () => ({ delivered: true }));
    installShell(invoke);
    delete (window as unknown as { __TAURI__?: unknown }).__TAURI__;
    notifyDesktopRoundComplete({
      sessionId: "s-1",
      content: "done",
      backgrounded: true,
    });
    expect(invoke).not.toHaveBeenCalled();
  });

  it("stays silent while the user is watching the turn finish", () => {
    const invoke = vi.fn(async () => ({ delivered: true }));
    installShell(invoke);
    notifyDesktopRoundComplete({
      sessionId: "s-1",
      content: "done",
      backgrounded: false,
    });
    expect(invoke).not.toHaveBeenCalled();
  });

  it("stays silent when the turn has no session to return to", () => {
    const invoke = vi.fn(async () => ({ delivered: true }));
    installShell(invoke);
    notifyDesktopRoundComplete({
      sessionId: null,
      content: "done",
      backgrounded: true,
    });
    expect(invoke).not.toHaveBeenCalled();
  });

  it("posts through the shell with the session as the notification target", async () => {
    const invoke = vi.fn(async () => ({ delivered: true, permission: "granted", detail: null }));
    installShell(invoke);
    notifyDesktopRoundComplete({
      sessionId: "s-42",
      sessionTitle: "  傅里叶变换  ",
      content: "  A  long\nanswer  ",
      backgrounded: true,
    });
    expect(invoke).toHaveBeenCalledTimes(1);
    const [command, args] = invoke.mock.calls[0] as unknown as [
      string,
      { request: Record<string, unknown> },
    ];
    expect(command).toBe("plugin:deeptutor|notify_round_complete");
    expect(args.request).toMatchObject({
      title: "傅里叶变换",
      body: "A long answer",
      route: "/chat/s-42",
      session_id: "s-42",
      kind: "round_complete",
    });
  });
});

describe("file hand-off payloads", () => {
  it("rebuilds a File with the shell's bytes and name", async () => {
    const file = fileFromLocalFile({
      path: "/tmp/paper.pdf",
      name: "paper.pdf",
      size: 4,
      mime: "application/pdf",
      base64: btoa("PDF!"),
    });
    expect(file.name).toBe("paper.pdf");
    expect(file.type).toBe("application/pdf");
    expect(await file.text()).toBe("PDF!");
  });

  it("falls back to a generic type when the shell cannot name one", () => {
    const file = fileFromLocalFile({
      path: "/tmp/mystery",
      name: "mystery",
      size: 0,
      mime: null,
      base64: "",
    });
    expect(file.type).toBe("application/octet-stream");
  });
});

describe("update checks", () => {
  it("checks without installing unless the caller asks to install", async () => {
    const calls: Array<unknown> = [];
    installShell(async (command, args) => {
      calls.push({ command, args });
      return { runtime: {}, shell: {} };
    });

    const { checkUpdates } = await import("@/lib/desktop-shell");
    await checkUpdates();
    await checkUpdates({ install: true });

    expect(calls).toEqual([
      { command: "plugin:deeptutor|check_updates", args: { install: false } },
      { command: "plugin:deeptutor|check_updates", args: { install: true } },
    ]);
  });
});
