import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { expect, it, vi } from "vitest";

import { AnnotationLayer } from "@/components/reading/AnnotationLayer";
import type { AnnotationItem } from "@/lib/reading-api";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (value: string) => value }),
}));

it("keeps a highlight's hit area while exposing its note through the shared tooltip", async () => {
  const annotation: AnnotationItem = {
    annotation_id: "a1",
    locator: 1,
    kind: "highlight",
    color: "yellow",
    quote: "A selected passage",
    note: "Review this step",
    rects: [[0.1, 0.2, 0.4, 0.3]],
    source_anchor: "",
    author: "user",
    created_at: 1,
    updated_at: 1,
  };
  const onAnnotationClick = vi.fn();
  render(
    <AnnotationLayer
      annotations={[annotation]}
      onAnnotationClick={onAnnotationClick}
    />,
  );

  const button = screen.getByRole("button", { name: "Review this step" });
  const marker = button.parentElement!.parentElement!;
  expect(button).not.toHaveAttribute("title");
  expect(parseFloat(marker.style.left)).toBeCloseTo(10);
  expect(parseFloat(marker.style.top)).toBeCloseTo(20);
  expect(parseFloat(marker.style.width)).toBeCloseTo(30);
  expect(parseFloat(marker.style.height)).toBeCloseTo(10);
  fireEvent.click(button);
  expect(onAnnotationClick).toHaveBeenCalledWith(annotation);

  fireEvent.focus(button);
  await waitFor(() =>
    expect(document.body.querySelector('[role="tooltip"].fixed')).toHaveTextContent(
      "Review this step",
    ),
  );
});
