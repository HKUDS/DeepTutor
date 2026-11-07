import { act, fireEvent, render, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { AnnotationList } from "@/components/reading/AnnotationList";
import type { AnnotationItem } from "@/lib/reading-api";

type ChangeMark = (
  annotation: AnnotationItem,
  changes: { color?: string; kind?: AnnotationItem["kind"] },
) => Promise<boolean>;

vi.mock("react-i18next", () => {
  const t = (key: string) => key;
  return { useTranslation: () => ({ t }) };
});

function mark(overrides: Partial<AnnotationItem> = {}): AnnotationItem {
  return {
    annotation_id: "a1",
    locator: 2,
    kind: "highlight",
    color: "yellow",
    quote: "the latency budget",
    note: "a note",
    rects: [[0.1, 0.2, 0.5, 0.24]],
    source_anchor: "",
    author: "user",
    created_at: 1,
    updated_at: 1,
    ...overrides,
  } as AnnotationItem;
}

/**
 * Recolouring and re-kinding a saved mark.
 *
 * Both are updates of an existing row, so what matters is that they carry the
 * `annotation_id` (otherwise the backend creates a second mark) and leave the
 * anchoring fields alone (otherwise the highlight moves).
 */
describe("changing a mark's colour", () => {
  it("offers every palette colour, marking the current one", () => {
    const view = render(
      <AnnotationList
        annotations={[mark()]}
        unit="page"
        activeId={null}
        onSelect={vi.fn()}
        onDelete={vi.fn()}
        onChangeMark={async () => true}
      />,
    );
    for (const label of ["Yellow", "Green", "Blue", "Pink", "Purple"]) {
      expect(view.getByLabelText(label)).toBeTruthy();
    }
    expect(view.getByLabelText("Yellow").getAttribute("aria-pressed")).toBe(
      "true",
    );
    expect(view.getByLabelText("Green").getAttribute("aria-pressed")).toBe(
      "false",
    );
  });

  it("sends only the colour, keeping quote and rects untouched", async () => {
    const onChangeMark = vi.fn<ChangeMark>(async () => true);
    const view = render(
      <AnnotationList
        annotations={[mark()]}
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
    expect(onChangeMark).toHaveBeenCalledTimes(1);
    const [annotation, changes] = onChangeMark.mock.calls[0];
    expect(annotation.annotation_id).toBe("a1");
    expect(changes).toEqual({ color: "green" });
  });

  it("does not re-open the mark's jump when a swatch is pressed", async () => {
    const onSelect = vi.fn();
    const view = render(
      <AnnotationList
        annotations={[mark()]}
        unit="page"
        activeId={null}
        onSelect={onSelect}
        onDelete={vi.fn()}
        onChangeMark={async () => true}
      />,
    );
    await act(async () => {
      fireEvent.click(view.getByLabelText("Blue"));
    });
    // The row itself is the select target; a swatch inside it is not.
    expect(onSelect).not.toHaveBeenCalled();
  });
});

describe("changing what kind of mark it is", () => {
  it("flips a highlight to an underline and back", async () => {
    const onChangeMark = vi.fn<ChangeMark>(async () => true);
    const view = render(
      <AnnotationList
        annotations={[mark({ kind: "highlight" })]}
        unit="page"
        activeId={null}
        onSelect={vi.fn()}
        onDelete={vi.fn()}
        onChangeMark={onChangeMark}
      />,
    );
    // A highlight offers "Underline" as the next state.
    await act(async () => {
      fireEvent.click(view.getByRole("button", { name: "Underline" }));
    });
    expect(onChangeMark.mock.calls[0][1]).toEqual({ kind: "underline" });

    const flipped = render(
      <AnnotationList
        annotations={[mark({ kind: "underline" })]}
        unit="page"
        activeId={null}
        onSelect={vi.fn()}
        onDelete={vi.fn()}
        onChangeMark={onChangeMark}
      />,
    );
    await act(async () => {
      fireEvent.click(flipped.getByRole("button", { name: "Highlight" }));
    });
    expect(onChangeMark.mock.calls[1][1]).toEqual({ kind: "highlight" });
  });

  it("does not offer a kind toggle on a citation", () => {
    const view = render(
      <AnnotationList
        annotations={[mark({ kind: "citation" })]}
        unit="page"
        activeId={null}
        onSelect={vi.fn()}
        onDelete={vi.fn()}
        onChangeMark={async () => true}
      />,
    );
    // A citation is a saved reference, not a drawing style.
    expect(view.queryByRole("button", { name: "Underline" })).toBeNull();
  });

  it("hides the whole control where the host cannot update marks", () => {
    const view = render(
      <AnnotationList
        annotations={[mark()]}
        unit="page"
        activeId={null}
        onSelect={vi.fn()}
        onDelete={vi.fn()}
      />,
    );
    expect(view.queryByLabelText("Green")).toBeNull();
  });

  it("reports a failed change instead of silently keeping the old colour", async () => {
    const onChangeMark = vi.fn<ChangeMark>(async () => false);
    const view = render(
      <AnnotationList
        annotations={[mark()]}
        unit="page"
        activeId={null}
        onSelect={vi.fn()}
        onDelete={vi.fn()}
        onChangeMark={onChangeMark}
      />,
    );
    await act(async () => {
      fireEvent.click(view.getByLabelText("Purple"));
    });
    await waitFor(() =>
      expect(view.getByRole("alert").textContent).toBe(
        "That annotation could not be saved.",
      ),
    );
  });
});
