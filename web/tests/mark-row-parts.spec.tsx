import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { MarkBadges } from "@/components/reading/MarkBadges";
import { MarkRow } from "@/components/reading/MarkRow";
import { MarkPalette } from "@/components/reading/MarkPalette";
import type { AnnotationItem } from "@/lib/reading-api";

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
 * The two blocks split out of the row. Each badge is an independent predicate,
 * so each is checked on its own rather than through the row's whole output.
 */
describe("MarkBadges", () => {
  it("says nothing about a plain user highlight", () => {
    const view = render(<MarkBadges annotation={mark()} />);
    expect(view.container.textContent).toBe("");
  });

  it("marks an assistant's mark", () => {
    render(<MarkBadges annotation={mark({ author: "assistant" })} />);
    expect(screen.getByText("AI")).toBeTruthy();
  });

  it("names an underline", () => {
    render(<MarkBadges annotation={mark({ kind: "underline" })} />);
    expect(screen.getByText("Underline")).toBeTruthy();
  });

  it("names a citation", () => {
    render(<MarkBadges annotation={mark({ kind: "citation" })} />);
    expect(screen.getByText("Citation")).toBeTruthy();
  });

  it("warns when the quote no longer resolves", () => {
    render(<MarkBadges annotation={mark({ resolution: "unresolved" })} />);
    expect(screen.getByText("Not found")).toBeTruthy();
  });

  it("warns when the quote resolves to more than one passage", () => {
    render(<MarkBadges annotation={mark({ resolution: "ambiguous" })} />);
    expect(screen.getByText("Ambiguous")).toBeTruthy();
  });

  it("shows a resolved mark without a warning", () => {
    const view = render(<MarkBadges annotation={mark({ resolution: "resolved" })} />);
    expect(view.container.textContent).not.toContain("Not found");
    expect(view.container.textContent).not.toContain("Ambiguous");
  });
});

describe("MarkPalette", () => {
  const onRecolour = vi.fn();
  const onChangeKind = vi.fn();

  function palette(annotation = mark(), busy = false) {
    return render(
      <MarkPalette
        annotation={annotation}
        busy={busy}
        onRecolour={onRecolour}
        onChangeKind={onChangeKind}
      />,
    );
  }

  it("offers every palette colour and marks the current one", () => {
    const view = palette();
    for (const label of ["Yellow", "Green", "Blue", "Pink", "Purple"]) {
      expect(view.getByLabelText(label)).toBeTruthy();
    }
    expect(view.getByLabelText("Yellow").getAttribute("aria-pressed")).toBe("true");
    expect(view.getByLabelText("Green").getAttribute("aria-pressed")).toBe("false");
  });

  it("reports the colour that was pressed", () => {
    const view = palette();
    view.getByLabelText("Green").click();
    expect(onRecolour).toHaveBeenCalledWith(expect.objectContaining({ annotation_id: "a1" }), "green");
  });

  it("offers the other kind, and flips it", () => {
    const view = palette(mark({ kind: "highlight" }));
    view.getByRole("button", { name: "Underline" }).click();
    expect(onChangeKind).toHaveBeenCalledWith(expect.anything(), "underline");
  });

  it("offers to go back to a highlight from an underline", () => {
    const view = palette(mark({ kind: "underline" }));
    view.getByRole("button", { name: "Highlight" }).click();
    expect(onChangeKind).toHaveBeenCalledWith(expect.anything(), "highlight");
  });

  it("does not offer a kind toggle on a citation", () => {
    const view = palette(mark({ kind: "citation" }));
    expect(view.queryByRole("button", { name: "Underline" })).toBeNull();
    expect(view.queryByRole("button", { name: "Highlight" })).toBeNull();
  });

  it("disables every control while the mark is saving", () => {
    const view = palette(mark(), true);
    expect(view.getByLabelText("Green").hasAttribute("disabled")).toBe(true);
    expect(
      view.getByRole("button", { name: "Underline" }).hasAttribute("disabled"),
    ).toBe(true);
  });
});

/**
 * The row's own interactions. These had no test at all — the mutation run
 * reported every site in the click and keydown handlers as uncovered, which is
 * the definition of behaviour nothing would notice breaking.
 */
describe("MarkRow interactions", () => {
  const onSelect = vi.fn();
  const onToggle = vi.fn();
  const onDelete = vi.fn();
  const onStartEditing = vi.fn();

  function row(overrides: { selecting?: boolean; canEdit?: boolean } = {}) {
    return render(
      <MarkRow
        annotation={mark({ note: "a note" })}
        active={false}
        selecting={overrides.selecting ?? false}
        selected={false}
        editing={false}
        savingNote={false}
        noteError=""
        busy={false}
        canEdit={overrides.canEdit ?? true}
        canChange
        onSelect={onSelect}
        onToggle={onToggle}
        onDelete={onDelete}
        onStartEditing={onStartEditing}
        onCancelEditing={vi.fn()}
        onSaveNote={async () => undefined}
        onRecolour={vi.fn()}
        onChangeKind={vi.fn()}
      />,
    );
  }

  it("jumps to the mark when the row is clicked", () => {
    const view = row();
    fireEvent.click(view.getByRole("button", { name: /a note|quote/ }));
    expect(onSelect).toHaveBeenCalledTimes(1);
  });

  it("toggles selection instead of jumping while selecting", () => {
    const view = row({ selecting: true });
    fireEvent.click(view.getByRole("button", { name: /a note|quote/ }));
    expect(onToggle).toHaveBeenCalledTimes(1);
    expect(onSelect).not.toHaveBeenCalled();
  });

  it("activates on Enter", () => {
    const view = row();
    fireEvent.keyDown(view.getByRole("button", { name: /a note|quote/ }), { key: "Enter" });
    expect(onSelect).toHaveBeenCalledTimes(1);
  });

  it("activates on Space", () => {
    const view = row();
    fireEvent.keyDown(view.getByRole("button", { name: /a note|quote/ }), { key: " " });
    expect(onSelect).toHaveBeenCalledTimes(1);
  });

  it("ignores other keys", () => {
    const view = row();
    fireEvent.keyDown(view.getByRole("button", { name: /a note|quote/ }), { key: "a" });
    expect(onSelect).not.toHaveBeenCalled();
  });

  it("deletes from the row action without also jumping", () => {
    const view = row();
    fireEvent.click(view.getByLabelText("Delete annotation"));
    expect(onDelete).toHaveBeenCalledTimes(1);
    // The click must not bubble into the row's own select handler.
    expect(onSelect).not.toHaveBeenCalled();
  });

  it("opens the editor from the row action without also jumping", () => {
    const view = row();
    fireEvent.click(view.getByLabelText("Edit note"));
    expect(onStartEditing).toHaveBeenCalledTimes(1);
    expect(onSelect).not.toHaveBeenCalled();
  });

  it("hides the edit action where the host cannot edit", () => {
    const view = row({ canEdit: false });
    expect(view.queryByLabelText("Edit note")).toBeNull();
    // Deleting is always available.
    expect(view.getByLabelText("Delete annotation")).toBeTruthy();
  });
});
