import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { FocusReadingPanel } from "@/components/reading/FocusReadingPanel";
import {
  startFocusReading,
  submitFocusCheck,
  getFocusState,
  type FocusState,
} from "@/lib/reading-api";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key, i18n: { language: "en" } }),
}));
vi.mock("@/lib/reading-api", () => ({
  startFocusReading: vi.fn(),
  stopFocusReading: vi.fn(),
  submitFocusCheck: vi.fn(),
  getFocusState: vi.fn(),
}));

const checkpoint = {
  checkpoint_id: "one",
  title: "Chapter one",
  start_locator: 1,
  end_locator: 2,
  char_count: 100,
};
const state: FocusState = {
  active: true,
  run_id: "run",
  revision: 1,
  plan_hash: "plan",
  passed_checkpoint_ids: [],
  attempts: [],
  checkpoints: [checkpoint],
  expected_checkpoint: checkpoint,
  completed: false,
  unlocked_through_locator: 2,
  pass_score: 65,
  updated_at: 0,
};
const callbacks = () => ({
  onFocusChange: vi.fn(),
  onNavigate: vi.fn(),
  onClose: vi.fn(),
  onError: vi.fn(),
});

describe("Focus Reading in a workspace", () => {
  it("sends reset to the server and navigates to the returned checkpoint", async () => {
    const props = callbacks();
    vi.mocked(startFocusReading).mockResolvedValue(state);
    render(
      <FocusReadingPanel
        materialId="rm_123456abcdef"
        focus={state}
        {...props}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Start over" }));
    await waitFor(() =>
      expect(props.onFocusChange).toHaveBeenCalledWith(state),
    );
    expect(startFocusReading).toHaveBeenCalledWith("rm_123456abcdef", true);
    expect(props.onNavigate).toHaveBeenCalledWith(1);
  });

  it("reports provider failures without displaying a fabricated zero score", async () => {
    const props = callbacks();
    vi.mocked(submitFocusCheck).mockRejectedValue(
      new Error("Provider unavailable"),
    );
    vi.mocked(getFocusState).mockResolvedValue(state);
    render(
      <FocusReadingPanel
        materialId="rm_123456abcdef"
        focus={state}
        {...props}
      />,
    );
    fireEvent.change(
      screen.getByRole("textbox", {
        name: "What happened or what ideas were developed?",
      }),
      { target: { value: "The chapter describes the traveller's arrival." } },
    );
    fireEvent.change(
      screen.getByRole("textbox", { name: "What affected you most, and why?" }),
      {
        target: { value: "The kindness of strangers mattered to me." },
      },
    );
    fireEvent.click(screen.getByRole("button", { name: "Submit Focus-Check" }));
    await waitFor(() =>
      expect(props.onFocusChange).toHaveBeenCalledWith(state),
    );
    expect(props.onError).toHaveBeenCalledWith("Provider unavailable");
    expect(props.onNavigate).not.toHaveBeenCalled();
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
    expect(submitFocusCheck).toHaveBeenCalledWith(
      "rm_123456abcdef",
      state,
      expect.objectContaining({ checkpoint_id: "one" }),
    );
  });

  it("ignores a late response after the workspace closes or changes material", async () => {
    const props = callbacks();
    let resolve!: (value: FocusState) => void;
    const pending = new Promise<FocusState>((done) => {
      resolve = done;
    });
    vi.mocked(startFocusReading).mockReturnValue(pending);
    const { unmount } = render(
      <FocusReadingPanel
        materialId="rm_123456abcdef"
        focus={null}
        {...props}
      />,
    );
    fireEvent.click(
      screen.getByRole("button", { name: "Start Focus Reading" }),
    );
    unmount();
    await act(async () => {
      resolve(state);
      await pending;
    });
    expect(props.onFocusChange).not.toHaveBeenCalled();
    expect(props.onNavigate).not.toHaveBeenCalled();
  });
});
