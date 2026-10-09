import { fireEvent, render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";

import SessionViewerPanel from "@/components/chat/home/SessionViewerPanel";
import { initI18n } from "@/i18n/init";
import { buildSessionActivity } from "@/lib/session-activity";

vi.mock("@/components/tasks/TaskPanelSection", () => ({
  default: () => null,
}));

initI18n("en");

it("keeps an explicit return to the conversation inside the Activity view", async () => {
  const onClose = vi.fn();

  render(
    <SessionViewerPanel
      open
      sessionId="session-a"
      activity={buildSessionActivity([])}
      onClose={onClose}
      onAutoOpen={() => {}}
    />,
  );

  const back = await screen.findByRole("button", { name: "Back to conversation" });
  expect(back).toBeVisible();
  expect(back.parentElement).toHaveClass("sticky", "top-0");

  fireEvent.click(back);
  expect(onClose).toHaveBeenCalledTimes(1);
});
