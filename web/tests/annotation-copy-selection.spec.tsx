import { act, fireEvent, render } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { AnnotationList } from "@/components/reading/AnnotationList";
import { marksToMarkdown } from "@/lib/reading-mark-list";
import type { AnnotationItem } from "@/lib/reading-api";

vi.mock("react-i18next", () => {
  const t = (key: string, options?: { count?: number }) =>
    options?.count === undefined ? key : key.replace("{{count}}", String(options.count));
  return { useTranslation: () => ({ t }) };
});

function mark(overrides: Partial<AnnotationItem> = {}): AnnotationItem {
  return {
    annotation_id: "a1",
    locator: 1,
    kind: "highlight",
    color: "yellow",
    quote: "quote",
    note: "",
    rects: [],
    source_anchor: "",
    author: "user",
    created_at: 1,
    updated_at: 1,
    ...overrides,
  } as AnnotationItem;
}

/**
 * Copying the chosen marks as Markdown.
 *
 * The backend's export always covers the whole material, so a reader who wants
 * three quotes in their notes has no way to get just those. Copying is the
 * local answer, and it is what a reader actually does with the text.
 */
describe("marksToMarkdown", () => {
  it("puts the quote, the note and the page in reading order", () => {
    const text = marksToMarkdown(
      [
        mark({ locator: 4, quote: "the latency budget", note: "worth re-reading" }),
      ],
      { unit: "Page", note: "Note: " },
    );
    expect(text).toContain("**Page 4**");
    expect(text).toContain("> the latency budget");
    expect(text).toContain("Note: worth re-reading");
  });

  it("omits an absent note instead of printing an empty label", () => {
    const text = marksToMarkdown([mark({ quote: "only a quote" })], {
      unit: "Page",
      note: "Note: ",
    });
    expect(text).not.toContain("Note:");
    expect(text).toContain("> only a quote");
  });

  it("separates several marks with a blank line", () => {
    const text = marksToMarkdown(
      [
        mark({ annotation_id: "a", locator: 1, quote: "one" }),
        mark({ annotation_id: "b", locator: 2, quote: "two" }),
      ],
      { unit: "Page", note: "Note: " },
    );
    expect(text).toContain("\n\n");
    expect(text.split("**Page").length - 1).toBe(2);
  });
});

describe("copying the selection", () => {
  const rows = [
    mark({ annotation_id: "a1", locator: 2, quote: "first quote", note: "a note" }),
    mark({ annotation_id: "a2", locator: 5, quote: "second quote" }),
  ];

  beforeEach(() => {
    Object.defineProperty(navigator, "clipboard", {
      configurable: true,
      value: { writeText: vi.fn(async () => undefined) },
    });
  });
  afterEach(() => {
    vi.restoreAllMocks();
  });

  function list() {
    return render(
      <AnnotationList
        annotations={rows}
        unit="page"
        activeId={null}
        onSelect={vi.fn()}
        onDelete={vi.fn()}
        onEditNote={async () => true}
      />,
    );
  }

  it("copies only the rows that were selected", async () => {
    const view = list();
    act(() => {
      fireEvent.click(view.getByTestId("annotation-select-toggle"));
    });
    act(() => {
      fireEvent.click(view.getByLabelText(/Select annotations: first quote/));
    });
    await act(async () => {
      fireEvent.click(view.getByTestId("annotation-bulk-copy"));
    });
    const written = (navigator.clipboard.writeText as ReturnType<typeof vi.fn>).mock
      .calls[0][0] as string;
    expect(written).toContain("first quote");
    expect(written).not.toContain("second quote");
  });

  it("confirms the copy in the button, then goes back", async () => {
    const view = list();
    act(() => {
      fireEvent.click(view.getByTestId("annotation-select-toggle"));
    });
    act(() => {
      fireEvent.click(view.getByTestId("annotation-bulk-copy"));
    });
    // Nothing selected: the button is disabled, so this is a no-op.
    expect(
      view.getByTestId("annotation-bulk-copy").hasAttribute("disabled"),
    ).toBe(true);

    act(() => {
      fireEvent.click(view.getByLabelText(/Select annotations: first quote/));
    });
    await act(async () => {
      fireEvent.click(view.getByTestId("annotation-bulk-copy"));
    });
    expect(view.getByTestId("annotation-bulk-copy").textContent).toContain("Copied");
  });

  it("reports a clipboard refusal instead of silently doing nothing", async () => {
    (navigator.clipboard.writeText as ReturnType<typeof vi.fn>).mockRejectedValueOnce(
      new Error("denied"),
    );
    const view = list();
    act(() => {
      fireEvent.click(view.getByTestId("annotation-select-toggle"));
    });
    act(() => {
      fireEvent.click(view.getByLabelText(/Select annotations: second quote/));
    });
    await act(async () => {
      fireEvent.click(view.getByTestId("annotation-bulk-copy"));
    });
    expect(view.getByRole("alert").textContent).toBe(
      "Could not copy to the clipboard.",
    );
  });
});
