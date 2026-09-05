import React from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import { expect, test, vi } from "vitest";
import { ReaderPane } from "@/components/reading/ReaderPane";
import { runReadingExtension } from "@/lib/reading-api";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (s: string) => s, i18n: { language: "en" } }),
}));
vi.mock("@/lib/reading-api", async () => ({
  ...(await vi.importActual("@/lib/reading-api")),
  getReadingPosition: vi.fn().mockResolvedValue({ locator: 1 }),
  saveReadingPosition: vi.fn().mockResolvedValue({}),
  listReadingExtensions: vi.fn().mockResolvedValue([
    {
      id: "vocabulary",
      name: "Vocabulary",
      version: "1",
      protocol_version: "1",
      actions: [
        {
          id: "explain",
          label: "Explain",
          trigger: "toolbar",
          requires: ["selection"],
        },
      ],
      result_types: ["card"],
    },
  ]),
  runReadingExtension: vi.fn().mockResolvedValue({
    type: "card",
    title: "Definition received",
    message: "",
    payload: {},
  }),
}));
vi.mock("@/context/ReadingContext", () => ({
  useReading: () => ({
    material: {
      material_id: "material",
      title: "Test book",
      filename: "book.epub",
      render_mode: "epub",
      unit: "chapter",
      unit_count: 2,
    },
    annotations: [],
    loading: false,
    error: null,
    openMaterial: vi.fn(),
    closeMaterial: vi.fn(),
    saveMark: vi.fn(),
    removeMark: vi.fn(),
    mergeMark: vi.fn(),
    dismissError: vi.fn(),
    setError: vi.fn(),
    reportViewport: vi.fn(),
  }),
}));
vi.mock("@/components/reading/PdfDocumentView", () => ({
  PdfDocumentView: () => null,
}));
vi.mock("@/components/reading/TextUnitView", () => ({
  TextUnitView: () => null,
  unitLabel: (s: string) => s,
}));
vi.mock("@/components/reading/EpubDocumentView", () => ({
  EpubDocumentView: ({
    onSelection,
    onVisibleLocatorChange,
  }: {
    onSelection: (v: unknown) => void;
    onVisibleLocatorChange: (v: number) => void;
  }) => (
    <>
      <button
        onClick={() =>
          onSelection({
            quote: "algorithm",
            locator: 1,
            rects: [],
            anchor: { x: 100, y: 100 },
          })
        }
      >
        Select English word
      </button>
      <button onClick={() => onVisibleLocatorChange(1)}>
        Turn document page
      </button>
    </>
  ),
}));

test("ReaderPane preserves selection through annotation pointerdown and clears it on same-chapter EPUB navigation", async () => {
  render(
    <ReaderPane
      onClose={vi.fn()}
      llmSelection={{ profile_id: "granted", model_id: "chosen" }}
    />,
  );
  const lookup = await screen.findByRole("button", { name: "Look up word" });
  fireEvent.click(screen.getByRole("button", { name: "Select English word" }));
  expect(
    screen.getByRole("dialog", { name: "Annotate selection" }),
  ).toBeVisible();
  fireEvent.pointerDown(lookup);
  fireEvent.mouseDown(lookup);
  fireEvent.pointerUp(lookup);
  fireEvent.mouseUp(lookup);
  fireEvent.click(lookup);
  await screen.findByText("Definition received");
  expect(runReadingExtension).toHaveBeenCalledWith(
    "material",
    "vocabulary",
    "explain",
    expect.objectContaining({
      selection: "algorithm",
      locator: 1,
      llm_selection: { profile_id: "granted", model_id: "chosen" },
    }),
  );
  expect(
    screen.queryByRole("dialog", { name: "Annotate selection" }),
  ).toBeNull();
  vi.mocked(runReadingExtension).mockClear();
  fireEvent.click(screen.getByRole("button", { name: "Turn document page" }));
  fireEvent.click(lookup);
  expect(screen.getByRole("status")).toHaveTextContent(
    "Select a word or passage first.",
  );
  expect(runReadingExtension).not.toHaveBeenCalled();
});
