import { act, fireEvent, render } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { AnnotationList } from "@/components/reading/AnnotationList";
import type { AnnotationItem } from "@/lib/reading-api";

vi.mock("react-i18next", () => {
  const t = (key: string) => key;
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

/**
 * Three orders, cycled by one button.
 *
 * Document order is the default and must stay byte-identical to what the list
 * has always shown: grouped under page headings, pages ascending. The two
 * time orders are flat, because page headings make no sense once the list is
 * no longer ordered by page.
 */
describe("ordering the saved marks", () => {
  const rows = [
    mark({ annotation_id: "b", locator: 5, quote: "written second", created_at: 20 }),
    mark({ annotation_id: "a", locator: 2, quote: "written first", created_at: 10 }),
    mark({ annotation_id: "c", locator: 9, quote: "written third", created_at: 30 }),
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

  function order(view: ReturnType<typeof render>): string[] {
    return view.container.querySelectorAll<HTMLElement>("li").length
      ? [...view.container.querySelectorAll<HTMLElement>("li")].map(
          (row) => row.textContent ?? "",
        )
      : [];
  }

  it("opens in document order, grouped by page", () => {
    const view = list();
    const headings = [...view.container.querySelectorAll("h4")].map(
      (node) => node.textContent,
    );
    // Page headings, ascending, and no repeats.
    expect(headings).toEqual(["Page 2", "Page 5", "Page 9"]);
  });

  it("cycles document order to newest, then oldest, then back", () => {
    const view = list();
    const button = view.getByTestId("annotation-sort");
    expect(button.getAttribute("aria-label")).toBe("Document order");

    act(() => {
      fireEvent.click(button);
    });
    expect(button.getAttribute("aria-label")).toBe("Newest first");

    act(() => {
      fireEvent.click(button);
    });
    expect(button.getAttribute("aria-label")).toBe("Oldest first");

    act(() => {
      fireEvent.click(button);
    });
    expect(button.getAttribute("aria-label")).toBe("Document order");
  });

  it("lists the newest mark first, ignoring page order", () => {
    const view = list();
    act(() => {
      fireEvent.click(view.getByTestId("annotation-sort"));
    });
    const text = order(view).join("|");
    expect(text.indexOf("written third")).toBeLessThan(
      text.indexOf("written second"),
    );
    expect(text.indexOf("written second")).toBeLessThan(
      text.indexOf("written first"),
    );
  });

  it("lists the oldest mark first when asked", () => {
    const view = list();
    const button = view.getByTestId("annotation-sort");
    act(() => {
      fireEvent.click(button);
    });
    act(() => {
      fireEvent.click(button);
    });
    const text = order(view).join("|");
    expect(text.indexOf("written first")).toBeLessThan(
      text.indexOf("written second"),
    );
    expect(text.indexOf("written second")).toBeLessThan(
      text.indexOf("written third"),
    );
  });

  it("drops the page headings once the order is no longer by page", () => {
    const view = list();
    act(() => {
      fireEvent.click(view.getByTestId("annotation-sort"));
    });
    // A time order with page headings would claim a grouping it does not have.
    expect(view.container.querySelectorAll("h4").length).toBe(0);
  });

  it("advances one stop per press even when two land in one frame", () => {
    const view = list();
    const button = view.getByTestId("annotation-sort");
    act(() => {
      // Both presses dispatched before React commits: a state read in the
      // handler would see "document" twice and lose a stop.
      fireEvent.click(button);
      fireEvent.click(button);
    });
    expect(button.getAttribute("aria-label")).toBe("Oldest first");
  });

  it("sorts what the search left, not the whole list", () => {
    const view = list();
    act(() => {
      fireEvent.change(view.getByLabelText("Search annotations…"), {
        target: { value: "written" },
      });
    });
    act(() => {
      fireEvent.click(view.getByTestId("annotation-sort"));
    });
    expect(order(view)).toHaveLength(3);
  });
});
