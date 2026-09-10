import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { ChatMessageList } from "@/features/chat/messages";
import { initI18n } from "@/i18n/init";

initI18n("en");

describe("chat message feature", () => {
  it("renders a user row with keyboard-accessible message actions", async () => {
    const copy = vi.fn(async () => undefined);
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
    expect(await screen.findByRole("button", { name: "Copied" })).toBeVisible();
  });

  // The button used to infer success from the handler's promise *resolving*,
  // so a swallowed clipboard error rendered 已复制 — and, because the label is
  // the aria-label on an aria-live element, announced it to screen readers.
  it("reports a failed copy instead of claiming success", async () => {
    const copy = vi.fn(async () => {
      throw new Error("clipboard unavailable");
    });
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
    await user.click(screen.getByRole("button", { name: "Copy" }));
    expect(
      await screen.findByRole("button", { name: "Could not copy" }),
    ).toBeVisible();
    expect(screen.queryByRole("button", { name: "Copied" })).toBeNull();
  });

  // A synchronous throw is what reading `navigator.clipboard.writeText` does
  // on an insecure origin, and `Promise.resolve(onCopy(content))` ran the
  // handler outside the chain, so that throw escaped the button entirely.
  it("catches a handler that throws synchronously", async () => {
    const copy = vi.fn(() => {
      throw new Error("navigator.clipboard is undefined");
    }) as unknown as (content: string) => Promise<void>;
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
    await user.click(screen.getByRole("button", { name: "Copy" }));
    expect(
      await screen.findByRole("button", { name: "Could not copy" }),
    ).toBeVisible();
  });
});
