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
 * Two defects found by reviewing the code rather than by testing it.
 *
 * Both had passing tests before this file existed, which is the point: the
 * earlier tests asserted the happy path only.
 */
describe("time-ordered list keys", () => {
  it("gives each mark its own section, even when two share a page", () => {
    // The time orders flatten the list into one row per section, but the
    // section was keyed by locator — so two marks on page 3 shared a React key
    // and React reused the wrong row's DOM.
    const view = render(
      <AnnotationList
        annotations={[
          mark({ annotation_id: "a", locator: 3, created_at: 10 }),
          mark({ annotation_id: "b", locator: 3, created_at: 20 }),
        ]}
        unit="page"
        activeId={null}
        onSelect={vi.fn()}
        onDelete={vi.fn()}
        onEditNote={async () => true}
      />,
    );
    // Section count alone cannot catch this: React still renders two nodes
    // when two children share a key, it just reuses the wrong one. The
    // duplicate-key warning is the signal, so capture it.
    const errors: string[] = [];
    const spy = vi.spyOn(console, "error").mockImplementation((...args) => {
      errors.push(String(args[0]));
    });
    act(() => {
      fireEvent.click(view.getByTestId("annotation-sort"));
    });
    spy.mockRestore();
    expect(errors.filter((line) => line.includes("same key")).join("\n")).toBe("");
    expect(view.container.querySelectorAll("section")).toHaveLength(2);
    expect(view.container.querySelectorAll("li")).toHaveLength(2);
  });

  it("still groups by page in document order", () => {
    const view = render(
      <AnnotationList
        annotations={[
          mark({ annotation_id: "a", locator: 3 }),
          mark({ annotation_id: "b", locator: 3 }),
        ]}
        unit="page"
        activeId={null}
        onSelect={vi.fn()}
        onDelete={vi.fn()}
        onEditNote={async () => true}
      />,
    );
    // Document order groups: one heading, two rows.
    expect(view.container.querySelectorAll("section")).toHaveLength(1);
    expect(view.container.querySelectorAll("h4")).toHaveLength(1);
    expect(view.container.querySelectorAll("li")).toHaveLength(2);
  });
});

describe("bulk removal", () => {
  const rows = [mark({ annotation_id: "a", locator: 1 }), mark({ annotation_id: "b", locator: 2 })];

  function list(onDelete: (annotation: AnnotationItem) => void | Promise<void>) {
    return render(
      <AnnotationList
        annotations={rows}
        unit="page"
        activeId={null}
        onSelect={vi.fn()}
        onDelete={onDelete}
        onEditNote={async () => true}
      />,
    );
  }

  function selectAll(view: ReturnType<typeof render>) {
    act(() => {
      fireEvent.click(view.getByTestId("annotation-select-toggle"));
    });
    act(() => {
      fireEvent.click(view.getByRole("button", { name: "Select all" }));
    });
  }

  it("waits for each delete before starting the next", async () => {
    // The hosts pass a function that starts a delete and returns at once, so a
    // bare loop fired every DELETE simultaneously and a mid-batch failure was
    // indistinguishable from success.
    const order: string[] = [];
    const view = list(async (annotation) => {
      order.push(`start:${annotation.annotation_id}`);
      await new Promise((resolve) => setTimeout(resolve, 10));
      order.push(`end:${annotation.annotation_id}`);
    });
    selectAll(view);
    await act(async () => {
      fireEvent.click(view.getByTestId("annotation-bulk-delete"));
      await new Promise((resolve) => setTimeout(resolve, 60));
    });
    expect(order).toEqual(["start:a", "end:a", "start:b", "end:b"]);
  });

  it("says so when every delete failed, instead of failing silently", async () => {
    const view = list(async () => {
      throw new Error("offline");
    });
    selectAll(view);
    await act(async () => {
      fireEvent.click(view.getByTestId("annotation-bulk-delete"));
      await new Promise((resolve) => setTimeout(resolve, 40));
    });
    // The host has already rolled the rows back into the list; without this
    // notice the reader sees them reappear with no explanation.
    expect(view.getByRole("alert").textContent).toBe(
      "That annotation could not be removed.",
    );
  });

  it("distinguishes a partial failure from a total one", async () => {
    let calls = 0;
    const view = list(async () => {
      calls += 1;
      if (calls === 2) throw new Error("offline");
    });
    selectAll(view);
    await act(async () => {
      fireEvent.click(view.getByTestId("annotation-bulk-delete"));
      await new Promise((resolve) => setTimeout(resolve, 40));
    });
    expect(view.getByRole("alert").textContent).toBe(
      "Some annotations could not be removed.",
    );
  });

  it("stays quiet when the batch succeeded", async () => {
    const view = list(async () => undefined);
    selectAll(view);
    await act(async () => {
      fireEvent.click(view.getByTestId("annotation-bulk-delete"));
      await new Promise((resolve) => setTimeout(resolve, 40));
    });
    expect(view.queryByRole("alert")).toBeNull();
  });
});

describe("per-mark busy state", () => {
  it("does not swallow a second press on a different mark", async () => {
    // A single global flag meant recolouring mark A blocked mark B until A
    // settled, silently dropping the press.
    let release!: () => void;
    const onChangeMark = vi.fn(
      (annotation: AnnotationItem) =>
        new Promise<boolean>((resolve) => {
          release = () => resolve(true);
        }),
    );
    const view = render(
      <AnnotationList
        annotations={[
          mark({ annotation_id: "a", locator: 1 }),
          mark({ annotation_id: "b", locator: 2 }),
        ]}
        unit="page"
        activeId={null}
        onSelect={vi.fn()}
        onDelete={vi.fn()}
        onChangeMark={onChangeMark}
      />,
    );
    const swatches = view.getAllByLabelText("Green");
    await act(async () => {
      fireEvent.click(swatches[0]);
    });
    await act(async () => {
      fireEvent.click(swatches[1]);
    });
    // Both marks were asked to change, not just the first.
    expect(onChangeMark).toHaveBeenCalledTimes(2);
    await act(async () => {
      release();
    });
  });

  it("still refuses a second press on the same mark while it is saving", async () => {
    const onChangeMark = vi.fn(
      () => new Promise<boolean>((resolve) => setTimeout(() => resolve(true), 20)),
    );
    const view = render(
      <AnnotationList
        annotations={[mark({ annotation_id: "a" })]}
        unit="page"
        activeId={null}
        onSelect={vi.fn()}
        onDelete={vi.fn()}
        onChangeMark={onChangeMark}
      />,
    );
    await act(async () => {
      fireEvent.click(view.getByLabelText("Green"));
    });
    await act(async () => {
      fireEvent.click(view.getByLabelText("Blue"));
    });
    expect(onChangeMark).toHaveBeenCalledTimes(1);
  });
});

describe("colour filter across tabs", () => {
  const rows = [
    mark({ annotation_id: "h1", locator: 1, color: "yellow" }),
    mark({ annotation_id: "h2", locator: 2, color: "green" }),
    mark({ annotation_id: "c1", locator: 3, kind: "citation", color: "blue" }),
  ];

  it("does not let one tab's colour empty the other tab", () => {
    // The palette was built from the annotations tab alone, so filtering to
    // yellow and then opening Citations — whose only row is blue — produced an
    // empty list blamed on the reader's search.
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
      fireEvent.click(view.getByTestId("annotation-color-filter-yellow"));
    });
    act(() => {
      fireEvent.click(view.getByRole("tab", { name: /Citations/ }));
    });
    // The citation is still listed: a filter the tab cannot honour does not
    // apply to it.
    expect(view.container.querySelectorAll("li")).toHaveLength(1);
    expect(view.queryByText("No matching annotations")).toBeNull();
  });

  it("restores the reader's choice when they switch back", () => {
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
      fireEvent.click(view.getByTestId("annotation-color-filter-yellow"));
    });
    act(() => {
      fireEvent.click(view.getByRole("tab", { name: /Citations/ }));
    });
    act(() => {
      fireEvent.click(view.getByRole("tab", { name: /Annotations/ }));
    });
    expect(view.getByTestId("annotation-color-filter-yellow").getAttribute("aria-pressed")).toBe("true");
  });
});
