import { act, fireEvent, render } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { AnnotationList } from "@/components/reading/AnnotationList";
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
 * Filtering by the colour a mark was drawn in.
 *
 * A reader who marks in five colours and wants only the yellow ones should
 * not have to type their own notes to get there. The palette shown is the
 * one the material actually uses, because a swatch for a colour that does
 * not exist is a filter for zero results.
 */
describe("filtering the marks by colour", () => {
  const rows = [
    mark({ annotation_id: "y1", locator: 1, color: "yellow", quote: "yellow one" }),
    mark({ annotation_id: "g1", locator: 2, color: "green", quote: "green one" }),
    mark({ annotation_id: "y2", locator: 3, color: "yellow", quote: "yellow two" }),
    mark({ annotation_id: "c1", locator: 4, kind: "citation", color: "blue", quote: "a citation" }),
  ];

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

  it("offers only the colours the material actually uses", () => {
    const view = list();
    // Yellow and green are in play; blue belongs to the citation, which the
    // annotations tab does not show.
    expect(view.queryByTestId("annotation-color-filter-yellow")).not.toBeNull();
    expect(view.queryByTestId("annotation-color-filter-green")).not.toBeNull();
    expect(view.queryByTestId("annotation-color-filter-blue")).toBeNull();
    expect(view.queryByTestId("annotation-color-filter-pink")).toBeNull();
  });

  it("shows only the chosen colour", () => {
    const view = list();
    act(() => {
      fireEvent.click(view.getByTestId("annotation-color-filter-yellow"));
    });
    expect(view.queryByText("yellow one")).not.toBeNull();
    expect(view.queryByText("yellow two")).not.toBeNull();
    expect(view.queryByText("green one")).toBeNull();
  });

  it("clears when the same swatch is pressed again", () => {
    const view = list();
    const yellow = view.getByTestId("annotation-color-filter-yellow");
    act(() => {
      fireEvent.click(yellow);
    });
    expect(yellow.getAttribute("aria-pressed")).toBe("true");
    act(() => {
      fireEvent.click(yellow);
    });
    expect(yellow.getAttribute("aria-pressed")).toBe("false");
    expect(view.queryByText("green one")).not.toBeNull();
  });

  it("combines with the text search rather than replacing it", () => {
    const view = list();
    act(() => {
      fireEvent.change(view.getByLabelText("Search annotations…"), {
        target: { value: "two" },
      });
    });
    act(() => {
      fireEvent.click(view.getByTestId("annotation-color-filter-yellow"));
    });
    // Only the yellow mark that also matches the query survives both filters.
    expect(view.queryByText("yellow two")).not.toBeNull();
    expect(view.queryByText("yellow one")).toBeNull();
    expect(view.queryByText("green one")).toBeNull();
  });

  it("hides the palette when only one colour is in use", () => {
    const single = render(
      <AnnotationList
        annotations={[mark({ annotation_id: "only", color: "yellow" })]}
        unit="page"
        activeId={null}
        onSelect={vi.fn()}
        onDelete={vi.fn()}
        onEditNote={async () => true}
      />,
    );
    // A one-colour palette filters nothing.
    expect(single.queryByRole("group", { name: "Filter by colour" })).toBeNull();
  });

  it("says nothing matched when a colour filter empties the list", () => {
    const view = render(
      <AnnotationList
        annotations={[
          mark({ annotation_id: "y", color: "yellow", quote: "yellow one" }),
          mark({ annotation_id: "g", color: "green", quote: "green one" }),
        ]}
        unit="page"
        activeId={null}
        onSelect={vi.fn()}
        onDelete={vi.fn()}
        onEditNote={async () => true}
      />,
    );
    act(() => {
      fireEvent.click(view.getByTestId("annotation-color-filter-green"));
    });
    act(() => {
      fireEvent.change(view.getByLabelText("Search annotations…"), {
        target: { value: "zzz" },
      });
    });
    expect(view.queryByText("No matching annotations")).not.toBeNull();
  });
});
