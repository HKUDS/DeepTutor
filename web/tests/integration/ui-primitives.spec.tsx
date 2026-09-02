import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import {
  Button,
  Dialog,
  EmptyState,
  Field,
  IconButton,
  InlineAlert,
  StatusChip,
} from "@/shared/ui";

describe("shared UI primitives", () => {
  it("keeps loading buttons named, busy, and disabled", () => {
    render(<Button loading>Save changes</Button>);
    const button = screen.getByRole("button", { name: "Save changes" });
    expect(button).toBeDisabled();
    expect(button).toHaveAttribute("aria-busy", "true");
  });

  it("gives icon-only actions an accessible name and described tooltip", async () => {
    const user = userEvent.setup();
    render(
      <IconButton label="Open details" icon={<span aria-hidden>+</span>} />,
    );
    const button = screen.getByRole("button", { name: "Open details" });
    await user.tab();
    const tooltip = screen.getByRole("tooltip");
    expect(button).toHaveAttribute("aria-describedby", tooltip.id);
  });

  it("traps focus, closes with Escape, and restores the trigger", async () => {
    const onClose = vi.fn();
    const user = userEvent.setup();
    const { rerender } = render(
      <>
        <button>Trigger</button>
        <Dialog open={false} title="Preferences" onClose={onClose}>
          <button>Inside</button>
        </Dialog>
      </>,
    );
    const trigger = screen.getByRole("button", { name: "Trigger" });
    trigger.focus();
    rerender(
      <>
        <button>Trigger</button>
        <Dialog open title="Preferences" onClose={onClose}>
          <button data-autofocus>Inside</button>
        </Dialog>
      </>,
    );
    expect(
      await screen.findByRole("dialog", { name: "Preferences" }),
    ).toBeVisible();
    await user.keyboard("{Escape}");
    expect(onClose).toHaveBeenCalledOnce();
    rerender(
      <>
        <button>Trigger</button>
        <Dialog open={false} title="Preferences" onClose={onClose}>
          <button>Inside</button>
        </Dialog>
      </>,
    );
    expect(screen.getByRole("button", { name: "Trigger" })).toHaveFocus();
  });

  it("connects fields to hint and error text", () => {
    render(
      <Field
        label="Workspace name"
        hint="Shown to collaborators"
        error="Required"
      >
        <input />
      </Field>,
    );
    const input = screen.getByRole("textbox", { name: "Workspace name" });
    expect(input).toHaveAttribute("aria-invalid", "true");
    expect(input.getAttribute("aria-describedby")?.split(" ")).toHaveLength(2);
  });

  it("renders semantic status, alert, and empty state copy", () => {
    render(
      <>
        <StatusChip tone="success">Connected</StatusChip>
        <InlineAlert tone="warning">Connection is slow</InlineAlert>
        <EmptyState
          title="No sessions yet"
          description="Start with a question."
        />
      </>,
    );
    expect(screen.getByText("Connected")).toHaveClass("bg-success-surface");
    expect(screen.getByRole("status")).toHaveTextContent("Connection is slow");
    expect(
      screen.getByRole("heading", { name: "No sessions yet" }),
    ).toBeVisible();
  });
});
