import React from "react";
import { act, render, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import { AppShellProvider } from "@/context/AppShellContext";
import { updateRecoveryPrincipal } from "@/lib/recovery-principal";
import { publishLearningDisplay } from "@/lib/learning-display";
const mocks = vi.hoisted(() => ({ fetch: vi.fn() }));
vi.mock("@/lib/api", () => ({
  apiUrl: (s: string) => s,
  apiFetch: (...args: unknown[]) => mocks.fetch(...args),
}));
vi.mock("@/lib/auth", () => ({ fetchAuthStatus: vi.fn() }));
const principal = (id: string) =>
  updateRecoveryPrincipal({ enabled: true, authenticated: true, user_id: id });
const scale = () =>
  document.documentElement.style.getPropertyValue("--learning-font-scale");
beforeEach(() => {
  updateRecoveryPrincipal(null);
  localStorage.clear();
  mocks.fetch.mockReset();
});
it("loads server preferences and resets across accounts without browser caching", async () => {
  let owner = "alice";
  mocks.fetch.mockImplementation(async (url: string) => ({
    ok: true,
    json: async () =>
      url === "/api/settings/display"
        ? {
            content_font_scale: owner === "alice" ? 150 : 90,
            content_line_spacing: "relaxed",
          }
        : { language: "en" },
  }));
  principal(owner);
  render(
    <AppShellProvider>
      <div />
    </AppShellProvider>,
  );
  await waitFor(() => expect(scale()).toBe("1.5"));
  owner = "bob";
  act(() => principal(owner));
  await waitFor(() => expect(scale()).toBe("0.9"));
  act(() => updateRecoveryPrincipal(null));
  expect(scale()).toBe("1");
  expect(
    Object.keys(localStorage).some((key) =>
      /learning|content_font|content_line/.test(key),
    ),
  ).toBe(false);
});
it("ignores stale account responses and stale Apply publications", async () => {
  let finish!: (data: unknown) => void;
  mocks.fetch.mockImplementation(async (url: string) => ({
    ok: true,
    json: () =>
      url === "/api/settings/display"
        ? new Promise((resolve) => {
            finish = resolve;
          })
        : Promise.resolve({ language: "en" }),
  }));
  principal("alice");
  render(
    <AppShellProvider>
      <div />
    </AppShellProvider>,
  );
  await waitFor(() => expect(finish).toBeDefined());
  act(() => updateRecoveryPrincipal(null));
  await act(async () => {
    finish({ content_font_scale: 150, content_line_spacing: "relaxed" });
  });
  expect(scale()).toBe("1");
  act(() =>
    publishLearningDisplay(
      { content_font_scale: 150, content_line_spacing: "relaxed" },
      "user:alice",
    ),
  );
  expect(scale()).toBe("1");
});
