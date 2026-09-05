import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { ChatMessageList } from "@/features/chat/messages";
import { initI18n } from "@/i18n/init";
import { WatchingProvider } from "@/context/WatchingContext";

initI18n("en");

describe("chat message feature", () => {
  it("renders every planning transcript message when branch filtering is disabled", () => {
    render(
      <WatchingProvider>
        <ChatMessageList
          messages={[
            { id: 1, role: "user", content: "first" },
            { id: 2, role: "assistant", content: "reply" },
            { id: 3, role: "user", content: "follow-up" },
            { id: 4, role: "assistant", content: "answer" },
          ]}
          isStreaming={true}
          disableBranchFiltering
          onCopyAssistantMessage={() => undefined}
          onRegenerateMessage={() => undefined}
        />
      </WatchingProvider>,
    );

    expect(screen.getByText("first")).toBeVisible();
    expect(screen.getByText("reply")).toBeVisible();
    expect(screen.getByText("follow-up")).toBeVisible();
    expect(screen.getByText("answer")).toBeVisible();
  });

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
