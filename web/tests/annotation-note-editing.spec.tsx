import { act, fireEvent, render, renderHook, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { ReadingProvider, useReading } from "@/context/ReadingContext";
import { AnnotationList } from "@/components/reading/AnnotationList";
import type { AnnotationItem, MaterialDetail } from "@/lib/reading-api";

const api = vi.hoisted(() => ({ fetch: vi.fn() }));
vi.mock("@/lib/api", () => ({ apiFetch: api.fetch, apiUrl: (url: string) => url }));

vi.mock("react-i18next", () => {
  const t = (key: string) => key;
  return { useTranslation: () => ({ t }) };
});

function mark(overrides: Partial<AnnotationItem> = {}): AnnotationItem {
  return {
    annotation_id: "a1",
    locator: 3,
    kind: "highlight",
    color: "yellow",
    quote: "the latency budget",
    note: "original note",
    rects: [[0.1, 0.2, 0.5, 0.24]],
    source_anchor: "",
    author: "user",
    created_at: 1,
    updated_at: 1,
    ...overrides,
  } as AnnotationItem;
}

async function openReader(
  context: { current: ReturnType<typeof useReading> },
  marks: AnnotationItem[],
) {
  api.fetch.mockResolvedValueOnce(new Response(JSON.stringify(marks)));
  await act(async () => {
    await context.current.openMaterial({
      material_id: "doc",
      outline: [],
      revision: 1,
      unit: "page",
    } as unknown as MaterialDetail);
  });
}

describe("editing the note on a saved mark", () => {
  it("sends the note as an update, keeping the mark's anchoring fields", async () => {
    const { result: context } = renderHook(useReading, { wrapper: ReadingProvider });
    await openReader(context, [mark()]);

    const view = render(
      <AnnotationList
        annotations={context.current.annotations}
        unit="page"
        activeId={null}
        onSelect={vi.fn()}
        onDelete={vi.fn()}
        onEditNote={async (annotation, note) =>
          context.current.saveMark(
            {
              annotation_id: annotation.annotation_id,
              locator: annotation.locator,
              kind: annotation.kind,
              color: annotation.color,
              quote: annotation.quote,
              note,
              rects: annotation.rects,
              source_anchor: annotation.source_anchor,
              selectors: annotation.selectors ?? [],
            },
            { ...annotation, note, updated_at: Date.now() / 1000 },
          )
        }
      />,
    );

    await act(async () => {
      fireEvent.click(view.getByLabelText("Edit note"));
    });
    const field = await waitFor(() => {
      const element = view.queryByTestId("annotation-note-input");
      if (!element) throw new Error("note editor has not mounted yet");
      return element;
    });
    expect((field as HTMLTextAreaElement).value).toBe("original note");

    await act(async () => {
      fireEvent.change(field, { target: { value: "revised note" } });
    });
    // The write must carry the id, or the backend would create a second mark
    // instead of updating this one.
    api.fetch.mockImplementationOnce(async (_url: string, init: RequestInit) => {
      const body = JSON.parse(String(init.body));
      expect(body.annotation_id).toBe("a1");
      expect(body.note).toBe("revised note");
      // Everything that anchors the mark is unchanged.
      expect(body.quote).toBe("the latency budget");
      expect(body.rects).toEqual([[0.1, 0.2, 0.5, 0.24]]);
      expect(body.locator).toBe(3);
      return new Response(JSON.stringify({ ...mark(), note: "revised note" }));
    });

    await act(async () => {
      fireEvent.click(view.getByTestId("annotation-note-save"));
    });
    await waitFor(() =>
      expect(context.current.annotations[0].note).toBe("revised note"),
    );
  });

  it("keeps the draft and reports the failure when the write fails", async () => {
    const { result: context } = renderHook(useReading, { wrapper: ReadingProvider });
    await openReader(context, [mark()]);

    const view = render(
      <AnnotationList
        annotations={context.current.annotations}
        unit="page"
        activeId={null}
        onSelect={vi.fn()}
        onDelete={vi.fn()}
        onEditNote={async (annotation, note) =>
          context.current.saveMark(
            {
              annotation_id: annotation.annotation_id,
              locator: annotation.locator,
              kind: annotation.kind,
              color: annotation.color,
              quote: annotation.quote,
              note,
              rects: annotation.rects,
              source_anchor: annotation.source_anchor,
            },
            { ...annotation, note, updated_at: Date.now() / 1000 },
          )
        }
      />,
    );

    await act(async () => {
      fireEvent.click(view.getByLabelText("Edit note"));
    });
    await act(async () => {
      fireEvent.change(view.getByTestId("annotation-note-input"), {
        target: { value: "draft that must survive" },
      });
    });
    api.fetch.mockImplementationOnce(async () => {
      throw new Error("Disconnected");
    });
    await act(async () => {
      fireEvent.click(view.getByTestId("annotation-note-save"));
    });

    // The editor stays open with the reader's text, and the saved mark rolls
    // back to what it was.
    await waitFor(() =>
      expect(view.getByTestId("annotation-note-input")).toBeTruthy(),
    );
    expect(
      (view.getByTestId("annotation-note-input") as HTMLTextAreaElement).value,
    ).toBe("draft that must survive");
    expect(view.getByRole("alert").textContent).toBe(
      "That annotation could not be saved.",
    );
    expect(context.current.annotations[0].note).toBe("original note");
  });

  it("abandons the edit on Escape without touching the stored note", async () => {
    const { result: context } = renderHook(useReading, { wrapper: ReadingProvider });
    await openReader(context, [mark()]);

    const view = render(
      <AnnotationList
        annotations={context.current.annotations}
        unit="page"
        activeId={null}
        onSelect={vi.fn()}
        onDelete={vi.fn()}
        onEditNote={async () => true}
      />,
    );
    await act(async () => {
      fireEvent.click(view.getByLabelText("Edit note"));
    });
    await act(async () => {
      fireEvent.change(view.getByTestId("annotation-note-input"), {
        target: { value: "throwaway" },
      });
      fireEvent.keyDown(view.getByTestId("annotation-note-input"), {
        key: "Escape",
      });
    });
    expect(view.queryByTestId("annotation-note-input")).toBeNull();
    expect(context.current.annotations[0].note).toBe("original note");
  });

  it("saves on the keyboard shortcut as well as the button", async () => {
    const onEditNote = vi.fn(async () => true);
    const view = render(
      <AnnotationList
        annotations={[mark()]}
        unit="page"
        activeId={null}
        onSelect={vi.fn()}
        onDelete={vi.fn()}
        onEditNote={onEditNote}
      />,
    );
    await act(async () => {
      fireEvent.click(view.getByLabelText("Edit note"));
    });
    await act(async () => {
      fireEvent.change(view.getByTestId("annotation-note-input"), {
        target: { value: "via keyboard" },
      });
      fireEvent.keyDown(view.getByTestId("annotation-note-input"), {
        key: "Enter",
        metaKey: true,
      });
    });
    expect(onEditNote).toHaveBeenCalledWith(
      expect.objectContaining({ annotation_id: "a1" }),
      "via keyboard",
    );
  });

  it("will not save an emptied note", async () => {
    const onEditNote = vi.fn(async () => true);
    const view = render(
      <AnnotationList
        annotations={[mark()]}
        unit="page"
        activeId={null}
        onSelect={vi.fn()}
        onDelete={vi.fn()}
        onEditNote={onEditNote}
      />,
    );
    await act(async () => {
      fireEvent.click(view.getByLabelText("Edit note"));
    });
    await act(async () => {
      fireEvent.change(view.getByTestId("annotation-note-input"), {
        target: { value: "   " },
      });
    });
    expect(
      view.getByTestId("annotation-note-save").hasAttribute("disabled"),
    ).toBe(true);
    expect(onEditNote).not.toHaveBeenCalled();
  });
});

describe("finding a mark among many", () => {
  const rows = [
    mark({ annotation_id: "a1", locator: 1, quote: "latency budget", note: "" }),
    mark({ annotation_id: "a2", locator: 2, quote: "cache invalidation", note: "watch the TTL" }),
    mark({ annotation_id: "a3", locator: 5, kind: "citation", quote: "throughput ceiling" }),
  ];

  function list(queryValue = "") {
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

  it("filters by quote and by note text", async () => {
    const view = list();
    const search = view.getByLabelText("Search annotations…");

    await act(async () => {
      fireEvent.change(search, { target: { value: "cache" } });
    });
    expect(view.queryByText("latency budget")).toBeNull();
    expect(view.queryByText("cache invalidation")).not.toBeNull();

    // A match in the note, not the quote, must count too.
    await act(async () => {
      fireEvent.change(search, { target: { value: "TTL" } });
    });
    expect(view.queryByText("cache invalidation")).not.toBeNull();
    expect(view.queryByText("latency budget")).toBeNull();
  });

  it("searches within the active tab only", async () => {
    const view = list();
    const search = view.getByLabelText("Search annotations…");
    await act(async () => {
      fireEvent.change(search, { target: { value: "throughput" } });
    });
    // The citation is filtered out by the Annotations tab even though it
    // matches the query.
    expect(view.queryByText("throughput ceiling")).toBeNull();
  });

  it("says nothing matched instead of pretending nothing was saved", async () => {
    const view = list();
    const search = view.getByLabelText("Search annotations…");
    await act(async () => {
      fireEvent.change(search, { target: { value: "zzzz" } });
    });
    expect(view.queryByText("No matching annotations")).not.toBeNull();
    expect(view.queryByText("No annotations yet")).toBeNull();
  });

  it("hides the search box where the host cannot edit notes", () => {
    const view = render(
      <AnnotationList
        annotations={rows}
        unit="page"
        activeId={null}
        onSelect={vi.fn()}
        onDelete={vi.fn()}
      />,
    );
    expect(view.queryByLabelText("Search annotations…")).toBeNull();
    expect(view.queryByLabelText("Edit note")).toBeNull();
  });
});
