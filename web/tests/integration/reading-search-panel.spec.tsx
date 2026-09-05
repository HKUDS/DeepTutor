import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ReadingSearchPanel } from "@/components/reading/ReadingSearchPanel";
import {
  getDescriptionIndexStatus,
  getDescriptionSearchCapabilities,
  searchReadingMaterial,
} from "@/lib/reading-api";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));
vi.mock("@/components/reading/TextUnitView", () => ({
  unitLabel: () => "Chapter",
}));
vi.mock("@/lib/reading-api", () => ({
  getDescriptionIndexStatus: vi.fn(),
  getDescriptionSearchCapabilities: vi.fn(),
  rebuildDescriptionIndex: vi.fn(),
  searchReadingMaterial: vi.fn(),
}));

beforeEach(() => {
  vi.mocked(getDescriptionSearchCapabilities).mockResolvedValue({
    model: "test",
    binding: "openai",
    enabled: true,
    context_window: 100_000,
    minimum_context_window: 50_000,
  });
  vi.mocked(getDescriptionIndexStatus).mockResolvedValue({
    status: "ready",
    total_groups: 2,
    completed_groups: 2,
    failed_groups: 0,
    model: "test",
    binding: "openai",
    prompt_version: "1",
    updated_at: 0,
    needs_build: false,
    errors: {},
  });
});

describe("Reading search in the official workspace", () => {
  it("keeps the selected mode and sends the source quote when a result is clicked", async () => {
    const onJump = vi.fn();
    vi.mocked(searchReadingMaterial).mockResolvedValue({
      hits: [
        {
          locator: 2,
          quote: "Her wallet was stolen in Athens.",
          snippet: "Her wallet was stolen in Athens.",
          score: 0.9,
          reason: "Matching event",
          group_title: "Athens",
          start_offset: 10,
          end_offset: 43,
        },
      ],
      requested_mode: "description_fast",
      resolved_mode: "description_fine",
      fallback_used: true,
      truncated: false,
    });
    render(
      <ReadingSearchPanel
        materialId="rm_123456abcdef"
        unit="chapter"
        onJump={onJump}
        onClose={vi.fn()}
        onError={vi.fn()}
      />,
    );
    const mode = screen.getByRole("button", { name: "Description · Fast" });
    await waitFor(() => expect(mode).toBeEnabled());
    fireEvent.click(mode);
    fireEvent.change(
      screen.getByPlaceholderText("Search words, events, people, or ideas…"),
      {
        target: { value: "stolen wallet in Greece" },
      },
    );
    fireEvent.click(screen.getByRole("button", { name: "Search" }));
    const result = await screen.findByRole("button", {
      name: /Her wallet was stolen/,
    });
    expect(searchReadingMaterial).toHaveBeenCalledWith(
      "rm_123456abcdef",
      "stolen wallet in Greece",
      "description_fast",
    );
    expect(
      screen.getByText(
        "Fast search had low confidence, so Fine search was used automatically.",
      ),
    ).toBeVisible();
    fireEvent.click(result);
    expect(onJump).toHaveBeenCalledWith(2, "Her wallet was stolen in Athens.");
  });

  it("disables description modes for a small context but keeps exact search available", async () => {
    vi.mocked(getDescriptionSearchCapabilities).mockResolvedValue({
      model: "small",
      binding: "openai",
      enabled: false,
      context_window: 32_000,
      minimum_context_window: 50_000,
    });
    render(
      <ReadingSearchPanel
        materialId="rm_123456abcdef"
        unit="chapter"
        onJump={vi.fn()}
        onClose={vi.fn()}
        onError={vi.fn()}
      />,
    );
    await screen.findByText(/Description search is unavailable/);
    expect(
      screen.getByRole("button", { name: "Description · Fast" }),
    ).toBeDisabled();
    expect(
      screen.getByRole("button", { name: "Description · Fine" }),
    ).toBeDisabled();
    expect(screen.getByRole("button", { name: "Exact" })).toBeEnabled();
  });
});
