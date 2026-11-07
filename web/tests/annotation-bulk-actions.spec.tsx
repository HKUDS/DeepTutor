import { act, fireEvent, render } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { AnnotationList } from "@/components/reading/AnnotationList";
import type { AnnotationItem } from "@/lib/reading-api";

vi.mock("react-i18next", () => {
  const t = (key: string, options?: { count?: number }) =>
    options?.count === undefined ? key : `${key.replace("{{count}}", String(options.count))}`;
  return { useTranslation: () => ({ t }) };
});

function mark(overrides: Partial<AnnotationItem> = {}): AnnotationItem {
  return {
    annotation_id: "a1",
    locator: 1,
    kind: "highlight",
    color: "yellow",
    quote: "quote one",
    note: "",
    rects: [],
    source_anchor: "",
    author: "user",
    created_at: 1,
    updated_at: 1,
    ...overrides,
  } as AnnotationItem;
}

const rows = [
  mark({ annotation_id: "a1", locator: 1, quote: "first mark" }),
  mark({ annotation_id: "a2", locator: 2, quote: "second mark" }),
  mark({ annotation_id: "a3", locator: 3, kind: "citation", quote: "a citation" }),
];

/**
 * Bulk removal, and the tab badges that say how much there is.
 *
 * The API deletes one row at a time, so a batch is a walk. What matters is
 * that it removes exactly what was selected — no more (a stray row would be
 * data loss) and no less.
 */
describe("removing several marks at once", () => {
  it("stays out of the way until asked", () => {
    const view = render(
      <AnnotationList
        annotations={rows}
        unit="page"
        activeId={null}
        onSelect={vi.fn()}
        onDelete={vi.fn()}
        onEditNote={async () => true}
      />,
    );
    // A checkbox on every row would make "jump to this mark" the second thing
    // a row is.
    expect(view.container.querySelectorAll('input[type="checkbox"]')).toHaveLength(0);
    expect(view.queryByTestId("annotation-bulk-delete")).toBeNull();
  });

  it("shows a checkbox per row once selection mode is on", () => {
    const view = render(
      <AnnotationList
        annotations={rows}
        unit="page"
        activeId={null}
        onSelect={vi.fn()}
        onDelete={vi.fn()}
        onEditNote={async () => true}
      />,
    );
    act(() => {
      fireEvent.click(view.getByTestId("annotation-select-toggle"));
    });
    // Two annotations + no citation in this view.
    expect(view.container.querySelectorAll('input[type="checkbox"]')).toHaveLength(2);
    expect(view.getByTestId("annotation-bulk-delete")).toBeTruthy();
  });

  it("deletes exactly the selected rows, one call each", async () => {
    const onDelete = vi.fn();
    const onSelect = vi.fn();
    const view = render(
      <AnnotationList
        annotations={rows}
        unit="page"
        activeId={null}
        onSelect={onSelect}
        onDelete={onDelete}
        onEditNote={async () => true}
      />,
    );
    act(() => {
      fireEvent.click(view.getByTestId("annotation-select-toggle"));
    });
    act(() => {
      fireEvent.click(view.getByLabelText(/Select annotations: first mark/));
    });
    // Selecting must not also jump to the mark.
    expect(onSelect).not.toHaveBeenCalled();

    await act(async () => {
      fireEvent.click(view.getByTestId("annotation-bulk-delete"));
    });
    expect(onDelete).toHaveBeenCalledTimes(1);
    expect(onDelete.mock.calls[0][0].annotation_id).toBe("a1");
    // The bar closes once the batch has run.
    expect(view.queryByTestId("annotation-bulk-delete")).toBeNull();
  });

  it("toggles a row from the keyboard instead of jumping to the mark", () => {
    const onSelect = vi.fn();
    const view = render(
      <AnnotationList
        annotations={rows}
        unit="page"
        activeId={null}
        onSelect={onSelect}
        onDelete={vi.fn()}
        onEditNote={async () => true}
      />,
    );
    act(() => {
      fireEvent.click(view.getByTestId("annotation-select-toggle"));
    });
    const row = view.getByRole("button", { name: /first mark/ });
    // The row exposes its selection state, not just the checkbox inside it.
    expect(row.getAttribute("aria-pressed")).toBe("false");
    row.focus();

    act(() => {
      fireEvent.keyDown(row, { key: " " });
    });
    expect(row.getAttribute("aria-pressed")).toBe("true");
    expect(
      (view.getByLabelText(/Select annotations: first mark/) as HTMLInputElement)
        .checked,
    ).toBe(true);

    act(() => {
      fireEvent.keyDown(row, { key: "Enter" });
    });
    expect(row.getAttribute("aria-pressed")).toBe("false");
    // Keyboard selection must not also jump to the mark, exactly as the
    // pointer path does not.
    expect(onSelect).not.toHaveBeenCalled();
  });

  it("selects every visible row, and only those", async () => {
    const onDelete = vi.fn();
    const view = render(
      <AnnotationList
        annotations={rows}
        unit="page"
        activeId={null}
        onSelect={vi.fn()}
        onDelete={onDelete}
        onEditNote={async () => true}
      />,
    );
    act(() => {
      fireEvent.click(view.getByTestId("annotation-select-toggle"));
    });
    act(() => {
      fireEvent.click(view.getByRole("button", { name: "Select all" }));
    });
    await act(async () => {
      fireEvent.click(view.getByTestId("annotation-bulk-delete"));
    });
    // The citation belongs to the other tab, so it is not swept up.
    expect(onDelete).toHaveBeenCalledTimes(2);
    expect(onDelete.mock.calls.map((call) => call[0].annotation_id)).toEqual([
      "a1",
      "a2",
    ]);
  });

  it("will not run a batch with nothing selected", () => {
    const onDelete = vi.fn();
    const view = render(
      <AnnotationList
        annotations={rows}
        unit="page"
        activeId={null}
        onSelect={vi.fn()}
        onDelete={onDelete}
        onEditNote={async () => true}
      />,
    );
    act(() => {
      fireEvent.click(view.getByTestId("annotation-select-toggle"));
    });
    expect(
      view.getByTestId("annotation-bulk-delete").hasAttribute("disabled"),
    ).toBe(true);
  });

  it("leaves selection mode when cancelled", () => {
    const view = render(
      <AnnotationList
        annotations={rows}
        unit="page"
        activeId={null}
        onSelect={vi.fn()}
        onDelete={vi.fn()}
        onEditNote={async () => true}
      />,
    );
    act(() => {
      fireEvent.click(view.getByTestId("annotation-select-toggle"));
    });
    act(() => {
      fireEvent.click(view.getByTestId("annotation-select-toggle"));
    });
    expect(view.container.querySelectorAll('input[type="checkbox"]')).toHaveLength(0);
  });
});

describe("tab badges", () => {
  it("says how many marks each view holds", () => {
    const view = render(
      <AnnotationList
        annotations={rows}
        unit="page"
        activeId={null}
        onSelect={vi.fn()}
        onDelete={vi.fn()}
        onEditNote={async () => true}
      />,
    );
    const tabs = view.getAllByRole("tab");
    expect(tabs[0].textContent).toContain("2");
    expect(tabs[1].textContent).toContain("1");
  });

  it("shows no badge for an empty view", () => {
    const view = render(
      <AnnotationList
        annotations={[mark({ annotation_id: "only", kind: "highlight" })]}
        unit="page"
        activeId={null}
        onSelect={vi.fn()}
        onDelete={vi.fn()}
        onEditNote={async () => true}
      />,
    );
    const tabs = view.getAllByRole("tab");
    // A "0" badge is noise, not information.
    expect(tabs[1].textContent).not.toContain("0");
  });
});
