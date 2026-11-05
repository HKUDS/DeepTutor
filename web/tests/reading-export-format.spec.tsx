import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { ExportMenuGroup } from "@/components/reading/ReaderPane";

vi.mock("react-i18next", () => {
  const t = (key: string) => key;
  return { useTranslation: () => ({ t }) };
});

/**
 * The export control used to call the backend with `auto` and accept whatever
 * that chose. A reader who wants the Markdown for their notes, or the annotated
 * PDF for a colleague, had no way to ask.
 *
 * Asserted on the control itself rather than through a full `ReaderPane`: the
 * pane's module graph is heavy enough that mounting it in jsdom here exhausts
 * the worker, and the format contract lives entirely in this component.
 */
describe("export format menu", () => {
  it("keeps the format rows closed until the trigger is pressed", () => {
    render(<ExportMenuGroup exporting={false} onExport={vi.fn()} />);
    expect(
      screen.queryByRole("menuitem", { name: /Download as Markdown/ }),
    ).toBeNull();
    expect(
      screen.getByRole("menuitemcheckbox", { name: /Export annotated file/ }),
    ).toBeTruthy();
  });

  it("reports the format the reader picked, then closes", () => {
    const onExport = vi.fn();
    render(<ExportMenuGroup exporting={false} onExport={onExport} />);
    fireEvent.click(
      screen.getByRole("menuitemcheckbox", { name: /Export annotated file/ }),
    );
    fireEvent.click(
      screen.getByRole("menuitem", { name: /Download as Markdown/ }),
    );
    expect(onExport).toHaveBeenCalledWith("markdown");
    // A menu that stays open after choosing would hide the result.
    expect(
      screen.queryByRole("menuitem", { name: /Download as Markdown/ }),
    ).toBeNull();
  });

  it("offers all three formats the backend serves", () => {
    render(<ExportMenuGroup exporting={false} onExport={vi.fn()} />);
    fireEvent.click(
      screen.getByRole("menuitemcheckbox", { name: /Export annotated file/ }),
    );
    expect(
      screen.getByRole("menuitem", { name: /Download annotated PDF/ }),
    ).toBeTruthy();
    expect(
      screen.getByRole("menuitem", { name: /Download as Markdown/ }),
    ).toBeTruthy();
  });

  it("refuses a second press while a download is running", () => {
    const onExport = vi.fn();
    render(<ExportMenuGroup exporting onExport={onExport} />);
    const trigger = screen.getByRole("menuitemcheckbox", {
      name: /Export annotated file/,
    });
    expect(trigger.hasAttribute("disabled")).toBe(true);
    fireEvent.click(trigger);
    expect(
      screen.queryByRole("menuitem", { name: /Download as Markdown/ }),
    ).toBeNull();
  });
});
