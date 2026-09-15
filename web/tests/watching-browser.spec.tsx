import React from "react";
import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { WatchingBrowser } from "@/components/watching/WatchingBrowser";

const mock = vi.hoisted(() => ({
  account: vi.fn(),
  browse: vi.fn(),
  recent: vi.fn(),
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
  listRecentVideoMaterials: mock.recent,
}));
const video = {
  videoId: "aircAruvnKk",
  title: "Neural networks",
  author: "Teacher",
  lengthSeconds: 120,
};
const recentVideo = {
  material_id: "recent-video",
  title: "Recent lesson",
  author: "Teacher",
  duration_seconds: 120,
  thumbnail_url: "",
  provider: "youtube",
  video_id: "dQw4w9WgXcQ",
  source_url: "https://youtu.be/dQw4w9WgXcQ",
  last_position: 37,
  updated_at: "2026-08-31T12:00:00Z",
};

beforeEach(() => {
  vi.clearAllMocks();
  sessionStorage.clear();
  mock.account.mockResolvedValue({ connected: true });
  mock.browse.mockResolvedValue({ videos: [video] });
  mock.recent.mockResolvedValue([recentVideo]);
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
    expect(mock.browse.mock.calls[0][0]).toBe("feed");
  });
  it("resumes a recent video from its saved position", async () => {
    render(<WatchingBrowser canDismiss onDismiss={vi.fn()} />);
    const section = screen.getByRole("region", {
      name: "Continue watching",
    });
    expect(await within(section).findByText("0:37 / 2:00")).toBeVisible();
    fireEvent.click(
      within(section).getByRole("button", {
        name: "Continue watching {{title}}",
      }),
    );
    expect(mock.push).toHaveBeenCalledWith(
      `/watching?video=${encodeURIComponent("https://youtu.be/dQw4w9WgXcQ")}`,
    );
  });
  it("recovers from a recent-videos loading failure", async () => {
    mock.recent.mockRejectedValueOnce(new Error("Recent videos failed"));
    render(<WatchingBrowser canDismiss={false} onDismiss={vi.fn()} />);
    const section = await screen.findByRole("region", {
      name: "Continue watching",
    });
    await within(section).findByText("Recent videos could not be loaded.");
    fireEvent.click(within(section).getByRole("button", { name: "Retry" }));
    await within(section).findByText("Recent lesson");
  });
  it("allows anonymous search and guides account-only browsing", async () => {
    mock.account.mockResolvedValue({ connected: false });
    render(<WatchingBrowser canDismiss={false} onDismiss={vi.fn()} />);
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
