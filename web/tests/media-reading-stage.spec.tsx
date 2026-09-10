import React from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { MediaReadingStage } from "@/components/reading/workspace/MediaReadingStage";
import type { ReadingLibraryMaterial } from "@/lib/reading-workspace-api";
import type { TranscriptRow } from "@/components/reading/workspace/types";

const mock = vi.hoisted(() => ({
  currentTime: 0,
  seeks: [] as number[],
  getPosition: vi.fn(),
  savePosition: vi.fn(),
  select: vi.fn(),
}));

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

vi.mock("@/lib/reading-api", () => ({
  getReadingPosition: mock.getPosition,
  saveReadingPosition: mock.savePosition,
  rawMaterialUrl: (id: string) => `/materials/${id}/raw`,
}));

vi.mock("@/components/reading/workspace/YouTubeReadingPlayer", () => ({
  YouTubeReadingPlayer(props: {
    onController(controller: unknown): void;
    onTime(seconds: number, duration: number): void;
  }) {
    React.useEffect(() => {
      props.onController({
        currentTime: () => mock.currentTime,
        duration: () => 180,
        seek: (seconds: number) => mock.seeks.push(seconds),
        tracksPosition: true,
      });
      props.onTime(mock.currentTime, 180);
    }, [props]);
    return (
      <button
        type="button"
        onClick={() => {
          mock.currentTime = 65;
          props.onTime(mock.currentTime, 180);
        }}
      >
        emit playback
      </button>
    );
  },
}));

const material: ReadingLibraryMaterial = {
  material_id: "media-1",
  content_id: "content-1",
  filename: "lecture.mp4",
  title: "Lecture",
  source_kind: "youtube",
  source_url: "https://www.youtube.com/watch?v=abc123xyz00",
  mime: "video/youtube",
  render_mode: "video",
  cover_url: "",
  duration_seconds: 180,
  status: "ready",
  progress: 1,
  error_code: "",
  error_detail: "",
  created_at: 1,
  updated_at: 1,
  last_opened_at: 1,
};

const refs = [0, 30, 65].map((seconds, index) => ({
  locator: index + 1,
  title: `0:${String(seconds).padStart(2, "0")}`,
  source_href: `#t=${seconds}`,
}));

const transcript: TranscriptRow[] = [
  { locator: 1, title: "0:00", text: "Opening sentence", sourceHref: "#t=0" },
  { locator: 2, title: "0:30", text: "Middle passage", sourceHref: "#t=30" },
  { locator: 3, title: "1:05", text: "Later passage", sourceHref: "#t=65" },
];

function renderStage(activeLocator = 1) {
  const onLocatorChange = vi.fn();
  const view = render(
    <MediaReadingStage
      material={material}
      title="Lecture"
      refs={refs}
      transcript={transcript}
      transcriptUnavailable={false}
      chaptersOnly={false}
      activeLocator={activeLocator}
      onLocatorChange={onLocatorChange}
    />,
  );
  return { onLocatorChange, view };
}

beforeEach(() => {
  vi.clearAllMocks();
  mock.currentTime = 0;
  mock.seeks = [];
  mock.getPosition.mockResolvedValue({ locator: 1, source_anchor: "#t=0" });
  mock.savePosition.mockResolvedValue(undefined);
});

describe("MediaReadingStage", () => {
  it("shows the current and next caption and seeks from either line", () => {
    renderStage();
    expect(screen.getByTestId("media-caption-current")).toHaveTextContent(
      "Opening sentence",
    );
    expect(screen.getByTestId("media-caption-next")).toHaveTextContent(
      "Middle passage",
    );

    fireEvent.click(screen.getByTestId("media-caption-next"));
    expect(mock.seeks).toContain(30);
  });

  it("searches the transcript and advances wrapping matches", () => {
    const { onLocatorChange } = renderStage();
    const input = screen.getByLabelText("Search transcript");

    fireEvent.change(input, { target: { value: "missing" } });
    expect(screen.getByText("No transcript matches.")).toBeVisible();
    expect(screen.getByLabelText("Next transcript match")).toBeDisabled();

    fireEvent.change(input, { target: { value: "later" } });
    fireEvent.click(screen.getByLabelText("Next transcript match"));

    expect(mock.seeks).toContain(65);
    expect(onLocatorChange).toHaveBeenCalledWith(3);
  });

  it("follows playback, pauses on reader scroll, and resumes on request", async () => {
    const { onLocatorChange, view } = renderStage();
    const list = await screen.findByTestId("reading-media-transcript-list");
    list.scrollTo = vi.fn();
    Object.defineProperty(list, "clientHeight", { value: 200 });
    Object.defineProperty(list, "scrollHeight", { value: 900 });
    list.getBoundingClientRect = () =>
      ({ top: 0, height: 200 }) as DOMRect;

    list
      .querySelectorAll("button")
      .forEach(
        (row) => {
          row.getBoundingClientRect = () =>
            ({ top: 150, height: 20 }) as DOMRect;
          Object.defineProperty(row, "clientHeight", { value: 20 });
        },
      );
    fireEvent.click(screen.getByRole("button", { name: "emit playback" }));
    view.rerender(
      <MediaReadingStage
        material={material}
        title="Lecture"
        refs={refs}
        transcript={transcript}
        transcriptUnavailable={false}
        chaptersOnly={false}
        activeLocator={3}
        onLocatorChange={onLocatorChange}
      />,
    );

    await waitFor(() => expect(list.scrollTo).toHaveBeenCalled());
    fireEvent.wheel(list);
    expect(
      screen.getByRole("button", { name: "Follow playback" }),
    ).toHaveAttribute("aria-pressed", "false");

    fireEvent.click(screen.getByRole("button", { name: "Follow playback" }));
    expect(
      screen.getByRole("button", { name: "Follow playback" }),
    ).toHaveAttribute("aria-pressed", "true");
  });

  it("opens the media stage in fullscreen", () => {
    const requestFullscreen = vi.fn().mockResolvedValue(undefined);
    HTMLElement.prototype.requestFullscreen = requestFullscreen;
    renderStage();

    fireEvent.click(screen.getByLabelText("Enter fullscreen"));
    expect(requestFullscreen).toHaveBeenCalled();
  });
});
