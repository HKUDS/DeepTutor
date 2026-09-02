import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import {
  ProtocolMismatchNotice,
  TurnStatusBar,
} from "@/features/chat/components/turn";
import type { TurnViewState } from "@/features/chat/model/turn-state";
import { initI18n } from "@/i18n/init";

initI18n("en");

const states: TurnViewState[] = [
  { kind: "idle" },
  { kind: "connecting" },
  { kind: "queued" },
  { kind: "running" },
  { kind: "waiting_input" },
  { kind: "cancelling" },
  { kind: "recovering" },
  { kind: "completed" },
  { kind: "cancelled" },
  {
    kind: "retryable_failure",
    failure: { code: "worker_lost", message: "Worker moved", retryable: true },
  },
  {
    kind: "terminal_failure",
    failure: {
      code: "rejected",
      message: "Request rejected",
      retryable: false,
    },
  },
];

describe("turn lifecycle UI", () => {
  it.each(states)(
    "renders the $kind state without changing the shared layout",
    (state) => {
      const { container } = render(<TurnStatusBar state={state} showSettled />);
      expect(
        container.querySelector(`[data-turn-state="${state.kind}"]`),
      ).toBeVisible();
    },
  );

  it("connects lifecycle actions to their exact semantics", async () => {
    const user = userEvent.setup();
    const onCancel = vi.fn();
    const { rerender } = render(
      <TurnStatusBar state={{ kind: "running" }} onCancel={onCancel} />,
    );
    await user.click(screen.getByRole("button", { name: "Stop" }));
    expect(onCancel).toHaveBeenCalledOnce();

    const onRegenerate = vi.fn();
    rerender(
      <TurnStatusBar
        state={{
          kind: "retryable_failure",
          failure: { code: "worker_lost", message: "Moved", retryable: true },
        }}
        onRegenerate={onRegenerate}
      />,
    );
    await user.click(screen.getByRole("button", { name: "Retry" }));
    expect(onRegenerate).toHaveBeenCalledOnce();
  });

  it("announces lifecycle changes without announcing noisy stage updates", () => {
    const { rerender } = render(
      <TurnStatusBar state={{ kind: "running" }} stage="Searching sources" />,
    );
    const liveRegion = screen.getByRole("status");
    expect(liveRegion).toHaveTextContent("Working");
    expect(liveRegion).not.toHaveTextContent("Searching sources");
    rerender(
      <TurnStatusBar state={{ kind: "recovering" }} stage="Attempt 2" />,
    );
    expect(liveRegion).toHaveTextContent("Reconnecting");
    expect(liveRegion).not.toHaveTextContent("Attempt 2");
  });

  it("shows a safe protocol mismatch notice and reload action", async () => {
    const onReload = vi.fn();
    const user = userEvent.setup();
    render(
      <ProtocolMismatchNotice
        clientVersion="2.0"
        serverVersion="3.0"
        onReload={onReload}
      />,
    );
    expect(screen.getByRole("alert")).toHaveTextContent("2.0");
    expect(screen.getByRole("alert")).toHaveTextContent("3.0");
    await user.click(screen.getByRole("button", { name: "Reload" }));
    expect(onReload).toHaveBeenCalledOnce();
  });
});
