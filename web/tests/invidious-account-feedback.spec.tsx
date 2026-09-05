import React from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { WatchingSurface } from "@/components/watching/WatchingWorkspace";

const route = vi.hoisted(() => ({ result: "authorization_expired" }));
vi.mock("next/navigation", () => ({
  useSearchParams: () => new URLSearchParams({ account: route.result }),
  useParams: () => ({}),
}));
const t = (key: string) => key;
vi.mock("react-i18next", () => ({ useTranslation: () => ({ t }) }));
vi.mock("@/context/WatchingContext", () => ({
  useWatching: () => ({ material: null }),
}));
vi.mock("@/components/watching/WatchingBrowser", () => ({
  WatchingBrowser: () => <div>Browser</div>,
}));
vi.mock("@/components/watching/WatchingPane", () => ({
  WatchingPane: () => null,
  WATCHING_ASK_EVENT: "dt:watching-ask",
}));

describe("Invidious callback feedback", () => {
  it("shows actionable failure and lets the learner dismiss it", () => {
    route.result = "authorization_expired";
    render(<WatchingSurface activePanel="chat" onPanelChange={vi.fn()} />);
    expect(screen.getByRole("alert")).toHaveTextContent(
      "Click Connect Invidious to start again",
    );
    fireEvent.click(screen.getByRole("button", { name: "Dismiss" }));
    expect(screen.queryByRole("alert")).toBeNull();
  });
  it("announces success and removes callback parameters", () => {
    route.result = "connected";
    const history = vi.spyOn(window.history, "replaceState");
    render(<WatchingSurface activePanel="chat" onPanelChange={vi.fn()} />);
    expect(screen.getByRole("status")).toHaveTextContent(
      "Invidious account connected",
    );
    expect(history).toHaveBeenCalledWith(null, "", "/watching");
    history.mockRestore();
  });
});
