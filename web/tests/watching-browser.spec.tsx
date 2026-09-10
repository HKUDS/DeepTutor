import React from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { WatchingBrowser } from "@/components/watching/WatchingBrowser";

const mock = vi.hoisted(() => ({
  account: vi.fn(),
  browse: vi.fn(),
}));
const translate = (key: string) => key;
vi.mock("react-i18next", () => ({ useTranslation: () => ({ t: translate }) }));
vi.mock("@/hooks/useAuthStatus", () => ({
  useAuthStatus: () => ({
    loading: false,
    statusAvailable: true,
    userId: "owner-a",
  }),
}));
vi.mock("@/lib/video-learning-api", () => ({
  invidiousAccount: mock.account,
  browseInvidious: mock.browse,
}));
const video = {
  videoId: "aircAruvnKk",
  title: "Neural networks",
  author: "Teacher",
  lengthSeconds: 120,
};

beforeEach(() => {
  vi.clearAllMocks();
  sessionStorage.clear();
  mock.account.mockResolvedValue({ connected: true });
  mock.browse.mockResolvedValue({ videos: [video] });
});
describe("Reading video source browser", () => {
  it("returns a selected subscription video to Reading", async () => {
    const onSelectUrl = vi.fn();
    render(
      <WatchingBrowser
        canDismiss
        onSelectUrl={onSelectUrl}
        onDismiss={vi.fn()}
      />,
    );

    fireEvent.click(
      await screen.findByRole("button", { name: /Neural networks/ }),
    );

    expect(onSelectUrl).toHaveBeenCalledWith(
      "https://www.youtube.com/watch?v=aircAruvnKk",
    );
    expect(mock.browse.mock.calls[0][0]).toBe("feed");
  });
  it("allows anonymous search and guides account-only browsing", async () => {
    mock.account.mockResolvedValue({ connected: false });
    render(
      <WatchingBrowser
        canDismiss={false}
        onDismiss={vi.fn()}
        onSelectUrl={vi.fn()}
      />,
    );
    await waitFor(() => expect(mock.account).toHaveBeenCalled());
    fireEvent.click(screen.getByRole("button", { name: "Subscription feed" }));
    await screen.findByText(
      "Connect your Invidious account to see subscriptions and playlists.",
    );
    expect(mock.browse).not.toHaveBeenCalled();
    const input = screen.getByRole("textbox");
    fireEvent.change(input, { target: { value: "neural" } });
    fireEvent.submit(input.closest("form")!);
    await screen.findByText("Neural networks");
    expect(mock.browse.mock.calls[0].slice(0, 3)).toEqual([
      "search",
      "neural",
      1,
    ]);
  });
  it("clears private rows when disconnected", async () => {
    render(
      <WatchingBrowser
        canDismiss={false}
        onDismiss={vi.fn()}
        onSelectUrl={vi.fn()}
      />,
    );
    await screen.findByText("Neural networks");
    mock.account.mockResolvedValue({ connected: false });
    fireEvent.click(
      screen.getByRole("button", { name: "Disconnect Invidious" }),
    );
    await waitFor(() =>
      expect(screen.queryByText("Neural networks")).toBeNull(),
    );
  });
  it("shows an actionable instance failure", async () => {
    mock.browse.mockRejectedValue(
      new Error(
        "Invidious could not load videos. Please retry or check the instance.",
      ),
    );
    render(
      <WatchingBrowser
        canDismiss={false}
        onDismiss={vi.fn()}
        onSelectUrl={vi.fn()}
      />,
    );
    await screen.findByRole("alert");
    mock.browse.mockResolvedValue({ videos: [video] });
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    await screen.findByText("Neural networks");
  });
});
