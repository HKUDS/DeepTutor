import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import Button from "@/components/ui/Button";

describe("shared Button", () => {
  it("exposes its accessible name and keyboard focus contract", async () => {
    const user = userEvent.setup();
    render(<Button>Save changes</Button>);

    const button = screen.getByRole("button", { name: "Save changes" });
    expect(button).toBeEnabled();
    expect(button).toHaveClass("focus-visible:ring-2");

    await user.tab();
    expect(button).toHaveFocus();
  });

  it("uses the native disabled state", () => {
    render(<Button disabled>Delete</Button>);

    expect(screen.getByRole("button", { name: "Delete" })).toBeDisabled();
  });

  it("announces and disables its loading state", () => {
    render(<Button loading>Save changes</Button>);

    const button = screen.getByRole("button", { name: "Save changes" });
    expect(button).toBeDisabled();
    expect(button).toHaveAttribute("aria-busy", "true");
  });
});
