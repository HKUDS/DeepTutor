import React from "react";
import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { beforeEach, expect, test, vi } from "vitest";
import { AnnotationPopover } from "@/components/reading/AnnotationPopover";
import { ReadingExtensionBar } from "@/components/reading/ReadingExtensionBar";
import {
  listReadingExtensions,
  runReadingExtension,
  type ReadingExtensionManifest,
  type ReadingExtensionResult,
} from "@/lib/reading-api";

vi.mock("@/lib/reading-api", async () => ({
  ...(await vi.importActual("@/lib/reading-api")),
  listReadingExtensions: vi.fn(),
  runReadingExtension: vi.fn(),
}));
vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (value: string) => value,
    i18n: { language: "en" },
  }),
}));
const catalog: ReadingExtensionManifest[] = [
  ["quiz", "start", []],
  ["guided_learning", "guide", ["selection"]],
  ["vocabulary", "explain", ["selection"]],
  ["read_aloud", "read", []],
  ["custom", "help", []],
].map(([id, action, requires]) => ({
  id,
  name: id,
  version: "1",
  protocol_version: "1",
  actions: [{ id: action, label: action, trigger: "toolbar", requires }],
  result_types: ["card"],
})) as ReadingExtensionManifest[];
const props = { materialId: "material", locator: 1, onError: vi.fn() };
beforeEach(() => {
  vi.mocked(listReadingExtensions).mockResolvedValue(catalog);
  vi.mocked(runReadingExtension).mockResolvedValue({
    type: "card",
    title: "Word meaning",
    message: "",
    payload: {},
  });
});

test("fixed primary order and secondary disclosure", async () => {
  render(<ReadingExtensionBar {...props} />);
  const toolbar = await screen.findByRole("toolbar");
  expect(
    within(toolbar)
      .getAllByRole("button")
      .map((button) => button.textContent),
  ).toEqual(["Read aloud", "Look up word", "Quiz me", "More"]);
  expect(screen.queryByRole("button", { name: "Guide me" })).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "More" }));
  expect(screen.getByRole("button", { name: "Guide me" })).toBeVisible();
  expect(screen.getByRole("button", { name: "help" })).toBeVisible();
});

test("selection requirement gives a hint without a request, then sends selected context", async () => {
  const view = render(<ReadingExtensionBar {...props} />);
  fireEvent.click(await screen.findByRole("button", { name: "Look up word" }));
  expect(screen.getByRole("status")).toHaveTextContent(
    "Select a word or passage first.",
  );
  expect(runReadingExtension).not.toHaveBeenCalled();
  view.rerender(<ReadingExtensionBar {...props} selection="quantum" />);
  fireEvent.click(screen.getByRole("button", { name: "Look up word" }));
  await screen.findByText("Word meaning");
  expect(runReadingExtension).toHaveBeenCalledWith(
    "material",
    "vocabulary",
    "explain",
    {
      locator: 1,
      selection: "quantum",
      locale: "en",
    },
  );
});

test("failed catalog can be retried", async () => {
  vi.mocked(listReadingExtensions).mockRejectedValueOnce(new Error("offline"));
  render(<ReadingExtensionBar {...props} />);
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "Could not load reading actions.",
  );
  fireEvent.click(screen.getByRole("button", { name: "Retry" }));
  expect(await screen.findByRole("toolbar")).toBeVisible();
});

test("server filtering is respected", async () => {
  vi.mocked(listReadingExtensions).mockResolvedValue(
    catalog.filter((row) => row.id === "quiz"),
  );
  render(<ReadingExtensionBar {...props} />);
  await screen.findByRole("button", { name: "Quiz me" });
  expect(screen.queryByRole("button", { name: "Read aloud" })).toBeNull();
  expect(screen.queryByRole("button", { name: "Look up word" })).toBeNull();
});

test("late speech responses cannot start after navigation", async () => {
  let resolve!: (value: ReadingExtensionResult) => void;
  vi.mocked(runReadingExtension).mockReturnValue(
    new Promise((done) => {
      resolve = done;
    }),
  );
  const speak = vi.fn();
  vi.stubGlobal("speechSynthesis", { cancel: vi.fn(), speak });
  const view = render(<ReadingExtensionBar {...props} />);
  fireEvent.click(await screen.findByRole("button", { name: "Read aloud" }));
  view.rerender(<ReadingExtensionBar {...props} locator={2} />);
  await act(async () =>
    resolve({
      type: "browser_speech",
      title: "",
      message: "",
      payload: { text: "old passage" },
    }),
  );
  expect(speak).not.toHaveBeenCalled();
  vi.unstubAllGlobals();
});

test("a new quiz resets previous answers", async () => {
  vi.mocked(runReadingExtension).mockResolvedValue({
    type: "quiz",
    title: "Quiz",
    message: "",
    payload: {
      questions: [
        {
          id: "q_1",
          prompt: "Choose",
          choices: ["one", "two"],
          correct_choice_index: 0,
        },
      ],
    },
  });
  render(<ReadingExtensionBar {...props} />);
  fireEvent.click(await screen.findByRole("button", { name: "Quiz me" }));
  fireEvent.click(await screen.findByRole("button", { name: "A. one" }));
  expect(screen.getByText("Correct")).toBeVisible();
  fireEvent.click(screen.getByRole("button", { name: "Quiz me" }));
  await act(async () => {});
  expect(screen.queryByText("Correct")).toBeNull();
});

test("speech can be stopped and is cancelled on unmount", async () => {
  const cancel = vi.fn();
  const speak = vi.fn();
  vi.stubGlobal("speechSynthesis", { cancel, speak });
  vi.stubGlobal(
    "SpeechSynthesisUtterance",
    class {
      constructor(public text: string) {}
    },
  );
  vi.mocked(runReadingExtension).mockResolvedValue({
    type: "browser_speech",
    title: "",
    message: "",
    payload: { text: "passage", locale: "en" },
  });
  const view = render(<ReadingExtensionBar {...props} />);
  fireEvent.click(await screen.findByRole("button", { name: "Read aloud" }));
  fireEvent.click(
    await screen.findByRole("button", { name: "Stop reading aloud" }),
  );
  expect(speak).toHaveBeenCalledOnce();
  expect(screen.queryByText("Reading aloud")).toBeNull();
  const previous = cancel.mock.calls.length;
  view.unmount();
  expect(cancel.mock.calls.length).toBeGreaterThan(previous);
  vi.unstubAllGlobals();
});

test("annotation dismissal preserves the selected word for the action click", async () => {
  function ReaderSelection() {
    const [selection, setSelection] = React.useState<string | undefined>(
      "algorithm",
    );
    const [open, setOpen] = React.useState(true);
    return (
      <>
        <ReadingExtensionBar
          materialId="material"
          locator={2}
          selection={selection}
          selectionLocator={1}
          llmSelection={{ profile_id: "granted", model_id: "chosen" }}
          onError={vi.fn()}
        />
        {open && selection ? (
          <AnnotationPopover
            anchor={{ x: 100, y: 100 }}
            quote={selection}
            onHighlight={vi.fn()}
            onUnderline={vi.fn()}
            onNote={vi.fn()}
            onCitation={vi.fn()}
            onAsk={vi.fn()}
            onDismiss={() => setSelection(undefined)}
            onActionFocus={() => setOpen(false)}
          />
        ) : null}
      </>
    );
  }
  render(<ReaderSelection />);
  const button = await screen.findByRole("button", { name: "Look up word" });
  fireEvent.pointerDown(button);
  fireEvent.mouseDown(button);
  fireEvent.pointerUp(button);
  fireEvent.mouseUp(button);
  fireEvent.click(button);
  expect(runReadingExtension).toHaveBeenCalledWith(
    "material",
    "vocabulary",
    "explain",
    expect.objectContaining({
      locator: 1,
      selection: "algorithm",
      llm_selection: { profile_id: "granted", model_id: "chosen" },
    }),
  );
  await screen.findByText("Word meaning");
  expect(
    screen.queryByRole("dialog", { name: "Annotate selection" }),
  ).toBeNull();
});

test("recoverable action errors stay near the toolbar and permit retry", async () => {
  vi.mocked(runReadingExtension).mockRejectedValueOnce(
    Object.assign(new Error("timeout"), { code: "timeout", recoverable: true }),
  );
  render(<ReadingExtensionBar {...props} />);
  const button = await screen.findByRole("button", { name: "Quiz me" });
  fireEvent.click(button);
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "Timed out. Try again.",
  );
  expect(button).toBeEnabled();
  fireEvent.click(button);
  await screen.findByText("Word meaning");
  expect(screen.queryByRole("alert")).toBeNull();
});
