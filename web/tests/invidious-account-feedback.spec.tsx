import React from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import InvidiousAccountFeedback from "@/components/reading/library/InvidiousAccountFeedback";

const route = vi.hoisted(() => ({ result: "authorization_expired" }));
vi.mock("next/navigation", () => ({
  useSearchParams: () => new URLSearchParams({ account: route.result }),
  useParams: () => ({}),
}));
const t = (key: string) => key;
vi.mock("react-i18next", () => ({ useTranslation: () => ({ t }) }));
describe("Invidious callback feedback", () => {
  it("shows actionable failure and lets the learner dismiss it", () => {
    route.result = "authorization_expired";
    render(<InvidiousAccountFeedback />);
    expect(screen.getByRole("alert")).toHaveTextContent(
      "Click Connect Invidious to start again",
    );
    fireEvent.click(screen.getByRole("button", { name: "Dismiss" }));
    expect(screen.queryByRole("alert")).toBeNull();
  });
  it("announces success and removes callback parameters", () => {
    route.result = "connected";
    const history = vi.spyOn(window.history, "replaceState");
    render(<InvidiousAccountFeedback />);
    expect(screen.getByRole("status")).toHaveTextContent(
      "Invidious account connected",
    );
    expect(history).toHaveBeenCalledWith(null, "", "/");
    history.mockRestore();
  });
});
