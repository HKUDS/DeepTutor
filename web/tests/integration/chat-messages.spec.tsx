import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { ChatMessageList } from "@/features/chat/messages";
import { initI18n } from "@/i18n/init";

initI18n("en");

describe("chat message feature", () => {
  it("renders a user row with keyboard-accessible message actions", async () => {
    const copy = vi.fn();
    const user = userEvent.setup();
    render(
      <ChatMessageList
        messages={[
          {
            id: 1,
            role: "user",
            content: "Explain eigenvectors",
            parentMessageId: null,
          },
        ]}
        isStreaming={false}
        onCopyAssistantMessage={copy}
        onRegenerateMessage={() => undefined}
      />,
    );
    expect(screen.getByText("Explain eigenvectors")).toBeVisible();
    await user.click(screen.getByRole("button", { name: "Copy" }));
    expect(copy).toHaveBeenCalledWith("Explain eigenvectors");
  });
});
