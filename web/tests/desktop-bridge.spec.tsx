import { act, render } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

/**
 * The desktop bridge is the only place web code reacts to shell events. It had
 * no rendered coverage, which is exactly how "clicking the notification does
 * nothing" survived: the shell claims the target before announcing it, so a
 * handler that ignores the payload and drains the (now empty) queue loses the
 * hand-off without any error anywhere.
 */

const hoisted = vi.hoisted(() => ({
  push: vi.fn(),
  handlers: new Map<string, (payload: unknown) => void>(),
  takeOpenRequest: vi.fn(),
  takeNotificationTarget: vi.fn(),
  readLocalFile: vi.fn(),
  fileFromLocalFile: vi.fn(() => new File(["x"], "paper.pdf")),
  shellSettings: vi.fn(),
  updateShellSettings: vi.fn(),
  language: "zh-CN",
  languageHandlers: [] as Array<() => void>,
}));

// The shell's own surfaces are written in the shell's language, so the bridge
// pushes the app's language up; `language` is mutable so a test can flip it.
vi.mock("i18next", () => ({
  default: {
    get language() {
      return hoisted.language;
    },
    on: (event: string, handler: () => void) => {
      if (event === "languageChanged") hoisted.languageHandlers.push(handler);
    },
    off: (event: string, handler: () => void) => {
      hoisted.languageHandlers = hoisted.languageHandlers.filter(
        (candidate) => candidate !== handler,
      );
    },
  },
}));

vi.mock("next/navigation", () => ({
  usePathname: () => "/settings",
  useRouter: () => ({ push: hoisted.push }),
}));

vi.mock("@/lib/desktop-shell", () => ({
  DESKTOP_ATTACH_EVENT: "deeptutor:desktop-attach-files",
  SHELL_EVENTS: {
    openRequest: "deeptutor://open-request",
    notificationTarget: "deeptutor://notification-target",
    shellSettings: "deeptutor://shell-settings",
    updateReport: "deeptutor://update-report",
    downloadStarted: "deeptutor://download-started",
    downloadFinished: "deeptutor://download-finished",
  },
  fileFromLocalFile: hoisted.fileFromLocalFile,
  isDesktopShell: () => true,
  noteUiReady: () => Promise.resolve(),
  onShellEvent: (event: string, handler: (payload: never) => void) => {
    hoisted.handlers.set(event, handler as (payload: unknown) => void);
    return () => hoisted.handlers.delete(event);
  },
  readLocalFile: hoisted.readLocalFile,
  shellLog: () => Promise.resolve(),
  shellSettings: hoisted.shellSettings,
  updateShellSettings: hoisted.updateShellSettings,
  takeNotificationTarget: hoisted.takeNotificationTarget,
  takeOpenRequest: hoisted.takeOpenRequest,
}));

import DesktopBridge from "@/features/desktop/DesktopBridge";
import { safeRoute } from "@/lib/in-app-route";

async function mount() {
  render(<DesktopBridge />);
  await act(async () => {});
}

describe("desktop bridge hand-offs", () => {
  beforeEach(() => {
    hoisted.push.mockClear();
    hoisted.handlers.clear();
    hoisted.takeOpenRequest.mockReset().mockResolvedValue(null);
    hoisted.takeNotificationTarget.mockReset().mockResolvedValue(null);
    hoisted.readLocalFile.mockReset();
    hoisted.shellSettings.mockReset().mockResolvedValue({ locale: "zh-CN" });
    hoisted.updateShellSettings.mockReset().mockResolvedValue({ locale: "zh-CN" });
    hoisted.language = "zh-CN";
    hoisted.languageHandlers = [];
  });

  it("navigates to the session named by the notification payload", async () => {
    await mount();
    const handler = hoisted.handlers.get("deeptutor://notification-target");
    expect(handler).toBeTypeOf("function");
    // The mount drain has already asked the shell once; what matters is that
    // the *event* does not need a second, empty ask.
    hoisted.takeNotificationTarget.mockClear();

    await act(async () => {
      handler?.({
        route: "/chat/s-1",
        session_id: "s-1",
        title: "回合完成",
        age_ms: 12,
      });
    });

    expect(hoisted.push).toHaveBeenCalledWith("/chat/s-1");
    expect(hoisted.takeNotificationTarget).not.toHaveBeenCalled();
  });

  it("still drains the queue when the event carries no route", async () => {
    hoisted.takeNotificationTarget.mockResolvedValue({
      route: "/chat/s-2",
      session_id: "s-2",
      title: "回合完成",
      age_ms: 3,
    });
    await mount();
    hoisted.push.mockClear();

    await act(async () => {
      hoisted.handlers.get("deeptutor://notification-target")?.(null);
    });

    expect(hoisted.push).toHaveBeenCalledWith("/chat/s-2");
  });

  it("refuses a route that is not an in-app path", async () => {
    await mount();
    const handler = hoisted.handlers.get("deeptutor://notification-target");

    await act(async () => {
      handler?.({ route: "//evil.example/steal", age_ms: 1 });
    });
    await act(async () => {
      handler?.({ route: "https://evil.example/steal", age_ms: 1 });
    });

    expect(hoisted.push).not.toHaveBeenCalled();
    expect(safeRoute("//evil.example")).toBeNull();
    expect(safeRoute("https://evil.example")).toBeNull();
    expect(safeRoute("")).toBeNull();
    expect(safeRoute("  /chat/s-3  ")).toBe("/chat/s-3");
  });

  it("pushes the app language to the shell only when they disagree", async () => {
    hoisted.shellSettings.mockResolvedValue({ locale: "en" });
    await mount();
    await act(async () => {});

    expect(hoisted.updateShellSettings).toHaveBeenCalledWith({ locale: "zh-CN" });

    // Same language on both sides: the app must not rewrite the setting (and
    // therefore must not relabel the menu bar) on every launch.
    hoisted.updateShellSettings.mockClear();
    hoisted.shellSettings.mockResolvedValue({ locale: "zh-CN" });
    await mount();
    await act(async () => {});
    expect(hoisted.updateShellSettings).not.toHaveBeenCalled();
  });

  it("reads a handed-over file and offers it to the composer", async () => {
    hoisted.takeOpenRequest
      .mockResolvedValueOnce({
        kind: "file",
        route: null,
        path: "/tmp/paper.pdf",
        source: "file-association",
        raw: "/tmp/paper.pdf",
        age_ms: 1,
      })
      .mockResolvedValue(null);
    hoisted.readLocalFile.mockResolvedValue({
      path: "/tmp/paper.pdf",
      name: "paper.pdf",
      size: 1,
      mime: "application/pdf",
      base64: "eA==",
    });

    const attached: CustomEvent[] = [];
    const onAttach = (event: Event) => attached.push(event as CustomEvent);
    window.addEventListener("deeptutor:desktop-attach-files", onAttach);
    try {
      await mount();
      await act(async () => {});

      expect(hoisted.readLocalFile).toHaveBeenCalledWith("/tmp/paper.pdf");
      expect(attached).toHaveLength(1);
      expect(attached[0].detail.files[0]).toBeInstanceOf(File);
      expect(attached[0].detail.source).toBe("file-association");
    } finally {
      window.removeEventListener("deeptutor:desktop-attach-files", onAttach);
    }
  });
});
