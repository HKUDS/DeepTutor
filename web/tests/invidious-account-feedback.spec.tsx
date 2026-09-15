import React from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { ReadingLibraryPage } from "@/components/reading/library/ReadingLibrary";

const route = vi.hoisted(() => ({ result: "authorization_expired" }));
vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: vi.fn() }),
  useSearchParams: () => new URLSearchParams({ account: route.result }),
}));
const t = (key: string) => key;
vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t, i18n: { language: "en" } }),
}));
vi.mock("@/components/watching/WatchingBrowser", () => ({
  WatchingBrowser: () => <div>Browser</div>,
}));
vi.mock("@/lib/reading-workspace-api", () => ({
  deleteReadingWorkspace: vi.fn(),
  listReadingLibraryMaterials: vi.fn().mockResolvedValue({ materials: [] }),
  listReadingWorkspaces: vi.fn().mockResolvedValue([]),
  retryReadingMaterial: vi.fn(),
}));

describe("Invidious callback feedback", () => {
  it("shows actionable failure and lets the learner dismiss it", () => {
    route.result = "authorization_expired";
    render(<ReadingLibraryPage />);
    expect(screen.getByRole("alert")).toHaveTextContent(
      "Click Connect Invidious to start again",
    );
    fireEvent.click(screen.getByRole("button", { name: "Dismiss" }));
    expect(screen.queryByRole("alert")).toBeNull();
  });
  it("announces success and removes callback parameters", () => {
    route.result = "connected";
    const history = vi.spyOn(window.history, "replaceState");
    render(<ReadingLibraryPage />);
    expect(screen.getByRole("status")).toHaveTextContent(
      "Invidious account connected",
    );
    expect(history).toHaveBeenCalledWith(null, "", "/reading");
    history.mockRestore();
  });
});
