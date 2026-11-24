import { act, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const store = vi.hoisted(() => ({
  current: {
    settingsLoading: true,
    settingsError: null as string | null,
    reloadSettings: async () => {},
  },
}));

vi.mock("@/features/settings/store/SettingsStore", () => ({
  useSettings: () => store.current,
}));
vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

import { SettingsLoadStatusBanner } from "@/components/settings/SettingsLoadStatusBanner";

afterEach(() => {
  vi.useRealTimers();
});

describe("settings load status banner", () => {
  it("holds the loading banner back so a fast settle never flashes it", () => {
    vi.useFakeTimers();
    store.current = {
      settingsLoading: true,
      settingsError: null,
      reloadSettings: async () => {},
    };

    render(<SettingsLoadStatusBanner />);

    expect(screen.queryByText("Loading settings...")).toBeNull();
    act(() => {
      vi.advanceTimersByTime(199);
    });
    expect(screen.queryByText("Loading settings...")).toBeNull();
    act(() => {
      vi.advanceTimersByTime(1);
    });
    expect(screen.getByText("Loading settings...")).toBeInTheDocument();
  });

  it("drops the banner the moment loading settles", () => {
    vi.useFakeTimers();
    store.current = {
      settingsLoading: true,
      settingsError: null,
      reloadSettings: async () => {},
    };

    const { rerender } = render(<SettingsLoadStatusBanner />);
    act(() => {
      vi.advanceTimersByTime(200);
    });
    expect(screen.getByText("Loading settings...")).toBeInTheDocument();

    store.current = {
      settingsLoading: false,
      settingsError: null,
      reloadSettings: async () => {},
    };
    rerender(<SettingsLoadStatusBanner />);

    expect(screen.queryByText("Loading settings...")).toBeNull();
  });
});
