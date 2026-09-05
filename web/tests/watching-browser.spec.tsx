import React from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { WatchingBrowser } from "@/components/watching/WatchingBrowser";

const mock = vi.hoisted(() => ({
  account: vi.fn(),
  browse: vi.fn(),
  captions: vi.fn(),
  push: vi.fn(),
}));
vi.mock("next/navigation", () => ({ useRouter: () => ({ push: mock.push }) }));
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
  captionStatus: mock.captions,
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
  mock.captions.mockResolvedValue({});
  mock.account.mockResolvedValue({ connected: true });
  mock.browse.mockResolvedValue({ videos: [video] });
});
describe("Watching account browser", () => {
  it("opens a selected subscription video as a new Watching route", async () => {
    render(<WatchingBrowser canDismiss onDismiss={vi.fn()} />);
    fireEvent.click(
      await screen.findByRole("button", { name: /Neural networks/ }),
    );
    expect(mock.push).toHaveBeenCalledWith(
      `/watching?video=${encodeURIComponent("https://www.youtube.com/watch?v=aircAruvnKk")}`,
    );
    expect(mock.browse.mock.calls[0][0]).toBe("popular");
  });
  it("allows anonymous search and guides account-only browsing", async () => {
    mock.account.mockResolvedValue({ connected: false });
    render(<WatchingBrowser canDismiss={false} onDismiss={vi.fn()} />);
    await waitFor(() => expect(mock.account).toHaveBeenCalled());
    fireEvent.click(screen.getByRole("button", { name: "Subscription feed" }));
    await screen.findByText(
      "Connect your Invidious account to see subscriptions and playlists.",
    );
    expect(mock.browse.mock.calls.every((call) => call[0] === "popular")).toBe(
      true,
    );
    mock.browse.mockClear();
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
    render(<WatchingBrowser canDismiss={false} onDismiss={vi.fn()} />);
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
    render(<WatchingBrowser canDismiss={false} onDismiss={vi.fn()} />);
    await screen.findByRole("alert");
    mock.browse.mockResolvedValue({ videos: [video] });
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    await screen.findByText("Neural networks");
  });
});

it.each(["search", "playlists"])(
  "migrates the old %s view to Popular",
  async (view) => {
    sessionStorage.setItem(
      "watching-browser:owner-a",
      JSON.stringify({ view, query: "" }),
    );
    render(<WatchingBrowser canDismiss={false} onDismiss={vi.fn()} />);
    await screen.findByText("Neural networks");
    expect(mock.browse.mock.calls[0][0]).toBe("popular");
    expect(screen.getByRole("button", { name: "Popular" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
  },
);

it("distinguishes provider CC from saved captions and filters searches", async () => {
  mock.browse.mockResolvedValue({videos: [{...video, hasCaptions: true}]});
  mock.captions.mockResolvedValue({[video.videoId]: {ready: true, language: "en"}});
  render(<WatchingBrowser onDismiss={() => {}} canDismiss={false} />);
  expect(await screen.findByText("Captions ready · en")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("checkbox", {name: "With captions only"}));
  fireEvent.change(screen.getByPlaceholderText("Search videos or paste a video link"), {target: {value: "lesson"}});
  fireEvent.submit(screen.getByPlaceholderText("Search videos or paste a video link").closest("form")!);
  await waitFor(() => expect(mock.browse).toHaveBeenLastCalledWith("search", "lesson features:subtitles", 1, "", expect.any(AbortSignal)));
});
