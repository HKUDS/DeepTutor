import { useRef, useState } from "react";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  within,
  waitFor,
} from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { Wand2 } from "lucide-react";
import ComposerResources from "@/components/chat/home/ComposerResources";
import ResourceSelector from "@/components/chat/home/ResourceSelector";
import AgentSelector from "@/components/chat/home/AgentSelector";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));
afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});
function Harness({ answerKind }: { answerKind?: "persona" | "agent" } = {}) {
  const [open, setOpen] = useState(false);
  const [picked, setPicked] = useState(false);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const panelRef = useRef<HTMLDivElement>(null);
  return (
    <>
      <button>Outside</button>
      <ComposerResources
        open={open}
        onOpenChange={setOpen}
        onBack={() => {}}
        triggerRef={triggerRef}
        panelRef={panelRef}
        materials={() => <button>Books</button>}
        items={[
          {
            key: answerKind || "skills",
            label:
              answerKind === "persona"
                ? "Answer style"
                : answerKind === "agent"
                  ? "Collaborating agent"
                  : "Skills",
            group: answerKind ? "Answer preferences" : "Tools",
            icon: Wand2,
            count: picked ? 1 : 0,
            summary: picked ? "Tutor" : "Workspace default",
            node: (
              <button onClick={() => setPicked(!picked)} aria-pressed={picked}>
                Tutor
              </button>
            ),
          },
        ]}
      />
    </>
  );
}
it("opens a dialog and keeps the category list out of the composer until opened", () => {
  render(<Harness />);
  expect(screen.queryByText("Books")).not.toBeInTheDocument();
  expect(
    screen.queryByRole("button", { name: "Done" }),
  ).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Resources" }));
  expect(screen.getByRole("dialog", { name: "Resources" })).toBeInTheDocument();
  expect(
    screen.getByRole("textbox", { name: "Search resource types" }),
  ).toHaveFocus();
});
it("keeps selection in one panel and preserves it after back and reopen", () => {
  render(<Harness />);
  fireEvent.click(screen.getByRole("button", { name: "Resources" }));
  fireEvent.click(
    screen.getByRole("button", { name: /Skills.*Workspace default/ }),
  );
  fireEvent.click(screen.getByRole("button", { name: "Tutor" }));
  expect(screen.getAllByRole("dialog")).toHaveLength(1);
  expect(screen.getByRole("button", { name: "Tutor" })).toHaveAttribute(
    "aria-pressed",
    "true",
  );
  fireEvent.keyDown(screen.getByRole("button", { name: "Tutor" }), {
    key: "Escape",
  });
  expect(
    screen.getByRole("button", { name: /Skills.*Tutor/ }),
  ).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Close" }));
  expect(screen.getByRole("button", { name: /Resources/ })).toHaveFocus();
  fireEvent.click(screen.getByRole("button", { name: /Resources/ }));
  expect(
    screen.getByRole("button", { name: /Skills.*Tutor/ }),
  ).toBeInTheDocument();
});
it("closes on outside click and traps tab within the panel", async () => {
  render(<Harness />);
  fireEvent.click(screen.getByRole("button", { name: "Resources" }));
  screen.getByRole("button", { name: /Skills.*Workspace default/ }).focus();
  fireEvent.keyDown(
    screen.getByRole("button", { name: /Skills.*Workspace default/ }),
    {
      key: "Tab",
    },
  );
  expect(screen.getByRole("button", { name: "Close" })).toHaveFocus();
  fireEvent.mouseDown(screen.getByRole("button", { name: "Outside" }));
  await waitFor(() =>
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument(),
  );
});
it("embedded skill picker supports search and multi-selection without another popup", () => {
  const toggle = vi.fn();
  render(
    <ResourceSelector
      embedded
      kind="skills"
      options={[
        {
          id: "tutor",
          name: "Tutor",
          description: "Learning helper",
          source: "account",
          available: true,
        },
      ]}
      selected={[]}
      onToggle={toggle}
    />,
  );
  expect(
    screen.queryByRole("button", { name: "Select skills" }),
  ).not.toBeInTheDocument();
  fireEvent.change(screen.getByPlaceholderText("Search"), {
    target: { value: "Learning" },
  });
  fireEvent.click(screen.getByRole("button", { name: /Tutor/ }));
  expect(toggle).toHaveBeenCalledWith("tutor");
});
it("embedded agent selection keeps the round controls available", () => {
  const select = vi.fn();
  const budget = vi.fn();
  const { container } = render(
    <AgentSelector
      embedded
      agents={[{ name: "Helper" }]}
      selected={null}
      onSelect={select}
      budget={5}
      onBudgetChange={budget}
    />,
  );
  fireEvent.click(screen.getByRole("button", { name: "Helper" }));
  expect(select).toHaveBeenCalledWith("Helper");
  fireEvent.click(
    within(container).getByRole("button", { name: "More rounds" }),
  );
  expect(budget).toHaveBeenCalledWith(6);
});

it("keeps the measured anchor when a smaller submenu replaces the overview", () => {
  vi.spyOn(HTMLElement.prototype, "getBoundingClientRect").mockImplementation(
    function (this: HTMLElement) {
      return this.tagName === "BUTTON" &&
        this.getAttribute("aria-label") === "Resources"
        ? new DOMRect(400, 700, 32, 32)
        : new DOMRect();
    },
  );
  const contentHeight = vi
    .spyOn(HTMLElement.prototype, "scrollHeight", "get")
    .mockReturnValue(500);
  render(<Harness />);
  fireEvent.click(screen.getByRole("button", { name: "Resources" }));
  const panel = screen.getByRole("dialog", { name: "Resources" });
  expect(panel.style.left).toBe("400px");
  const top = panel.style.top;
  expect(top).not.toBe("64px");
  contentHeight.mockReturnValue(150);
  fireEvent.click(
    screen.getByRole("button", { name: /Skills.*Workspace default/ }),
  );
  fireEvent.scroll(screen.getByRole("button", { name: "Tutor" }));
  expect(panel.style.top).toBe(top);
  expect(panel.style.left).toBe("400px");
  fireEvent.click(screen.getByRole("button", { name: "Back" }));
  expect(panel.style.top).toBe(top);
  expect(panel.style.transform).toBe("none");
});

it.each(["persona", "agent"] as const)(
  "preserves %s selection and the anchor after animated Back",
  async (answerKind) => {
    vi.spyOn(HTMLElement.prototype, "getBoundingClientRect").mockImplementation(
      function (this: HTMLElement) {
        if (this.getAttribute("role") === "dialog")
          return new DOMRect(400, 120, 336, 400);
        if (this.getAttribute("aria-label") === "Resources")
          return new DOMRect(400, 700, 32, 32);
        return new DOMRect(401, 440, 334, 36);
      },
    );
    render(<Harness answerKind={answerKind} />);
    fireEvent.click(screen.getByRole("button", { name: "Resources" }));
    const panel = screen.getByRole("dialog");
    const anchor = { top: panel.style.top, left: panel.style.left };
    fireEvent.click(screen.getByRole("button", { name: /Workspace default/ }));
    fireEvent.click(screen.getByRole("button", { name: "Tutor" }));
    fireEvent.click(screen.getByRole("button", { name: "Back" }));
    await waitFor(() =>
      expect(
        screen.queryByRole("button", { name: "Back" }),
      ).not.toBeInTheDocument(),
    );
    expect(screen.getByRole("button", { name: /Tutor/ })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    expect(panel.style.top).toBe(anchor.top);
    expect(panel.style.left).toBe(anchor.left);
  },
);

it("does not reopen a submenu when Close interrupts animated Back", async () => {
  vi.spyOn(HTMLElement.prototype, "getBoundingClientRect").mockReturnValue(
    new DOMRect(400, 120, 336, 36),
  );
  render(<Harness answerKind="persona" />);
  fireEvent.click(screen.getByRole("button", { name: "Resources" }));
  fireEvent.click(screen.getByRole("button", { name: /Workspace default/ }));
  fireEvent.click(screen.getByRole("button", { name: "Back" }));
  fireEvent.click(screen.getByRole("button", { name: "Close" }));
  await waitFor(() =>
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument(),
  );
  fireEvent.click(screen.getByRole("button", { name: "Resources" }));
  expect(
    screen.getByRole("button", { name: /Answer style.*Workspace default/ }),
  ).toBeInTheDocument();
  expect(
    screen.queryByRole("button", { name: "Back" }),
  ).not.toBeInTheDocument();
});
