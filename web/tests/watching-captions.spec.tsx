import React from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import { beforeAll, describe, expect, it, vi } from "vitest";
import { WatchingCaptions } from "@/components/watching/WatchingCaptions";
vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));
beforeAll(() => {
  vi.stubGlobal(
    "ResizeObserver",
    class {
      observe() {}
      disconnect() {}
    },
  );
  vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue({
    measureText: (s: string) => ({ width: s.length * 8 }),
  } as never);
});
describe("Learning captions", () => {
  it("uses source times for highlighting and seeking, including backward seeks", () => {
    const seek = vi.fn();
    const cues = [
      {
        start: 0,
        end: 3,
        text: "Hello world",
        words: [
          { start: 0, end: 1, text: "Hello " },
          { start: 1, end: 3, text: "world" },
        ],
      },
    ];
    const { rerender } = render(
      <WatchingCaptions cues={cues} time={2} onSeek={seek} />,
    );
    expect(screen.getByRole("button", { name: "world" })).toHaveClass(
      "watching-word-active",
    );
    fireEvent.click(screen.getByRole("button", { name: "world" }));
    expect(seek).toHaveBeenCalledWith(1);
    rerender(<WatchingCaptions cues={cues} time={0.5} onSeek={seek} />);
    expect(screen.getByRole("button", { name: "Hello" })).toHaveClass(
      "watching-word-active",
    );
  });
  it("keeps previous sentence context without inventing word timing", () => {
    const { container } = render(
      <WatchingCaptions
        cues={[
          { start: 0, end: 2, text: "Previous" },
          { start: 2, end: 4, text: "Current" },
        ]}
        time={3}
        onSeek={() => {}}
      />,
    );
    expect(container.querySelectorAll(".watching-caption-line")).toHaveLength(
      2,
    );
    expect(container.querySelector(".watching-word-active")).toBeNull();
    expect(screen.getByText("Sentence timing")).toBeInTheDocument();
  });
  it("clears captions during gaps", () => {
    render(
      <WatchingCaptions
        cues={[{ start: 0, end: 1, text: "Finished" }]}
        time={3}
        onSeek={() => {}}
      />,
    );
    expect(screen.getByText("No caption at this position")).toBeInTheDocument();
  });
});
