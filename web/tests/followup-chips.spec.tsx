import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";

import FollowupChipsRow from "@/features/chat/messages/FollowupChipsRow";

const api = vi.hoisted(() => ({ fetchSessionFollowups: vi.fn() }));
vi.mock("@/lib/session-api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/session-api")>()),
  fetchSessionFollowups: api.fetchSessionFollowups,
}));
vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key, i18n: { language: "en" } }),
}));

afterEach(() => {
  cleanup();
  api.fetchSessionFollowups.mockReset();
});

it("renders the fetched reactions and sends a pick as the next turn", async () => {
  api.fetchSessionFollowups.mockResolvedValue([
    { id: "simpler", label: "More simply", prompt: "Say it more simply." },
  ]);
  const onFollowup = vi.fn();

  render(
    <FollowupChipsRow
      sessionId="s1"
      isStreaming={false}
      turnKey={1}
      enabled
      onFollowup={onFollowup}
    />,
  );

  const chip = await screen.findByRole("button", { name: "More simply" });
  fireEvent.click(chip);
  expect(onFollowup).toHaveBeenCalledWith("Say it more simply.");
});

it("renders nothing until the turn settles with an answer", () => {
  api.fetchSessionFollowups.mockResolvedValue([
    { id: "simpler", label: "More simply", prompt: "x" },
  ]);
  const { container } = render(
    <FollowupChipsRow
      sessionId="s1"
      isStreaming
      turnKey={1}
      enabled={false}
      onFollowup={vi.fn()}
    />,
  );
  expect(container).toBeEmptyDOMElement();
  expect(api.fetchSessionFollowups).not.toHaveBeenCalled();
});
