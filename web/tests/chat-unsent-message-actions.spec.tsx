import { act, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";

import { ChatMessageList } from "@/features/chat/messages";
import { initI18n } from "@/i18n/init";

const supported = vi.hoisted(() => vi.fn(async () => true));
vi.mock("@/lib/session-api", async importOriginal => ({
  ...await importOriginal<typeof import("@/lib/session-api")>(),
  supportsSubmissionReplacement: supported,
}));
beforeEach(() => supported.mockResolvedValue(true));

initI18n("en");

const messages = [
  { id: 1, role: "assistant" as const, content: "Earlier response", parentMessageId: null },
  { id: -2, role: "user" as const, content: "First unsent draft", parentMessageId: 1,
    failedSubmission: true, failedSubmissionId: "draft-one" },
  { id: -3, role: "user" as const, content: "Second unsent draft", parentMessageId: -2,
    failedSubmission: true, failedSubmissionId: "draft-two" },
];

it("offers per-draft local discard, without requiring an assistant placeholder", async () => {
  const user = userEvent.setup();
  const discard = vi.fn(() => true);
  const { container } = render(<ChatMessageList messages={messages} isStreaming={false}
    onCopyAssistantMessage={async () => undefined} onRegenerateMessage={() => undefined}
    {...{ onDiscardFailedSubmission: discard }} />);
  const first = within(container.querySelector('[data-chat-message-id="-2"]') as HTMLElement);
  const second = within(container.querySelector('[data-chat-message-id="-3"]') as HTMLElement);
  await user.click(first.getByRole("button", { name: "Discard unsent draft" }));
  expect(discard).toHaveBeenCalledExactlyOnceWith(-2);
  await user.click(second.getByRole("button", { name: "Discard unsent draft" }));
  expect(discard.mock.calls).toEqual([[-2], [-3]]);
});

it("offers editing for unsent local drafts through the recovery handler", async () => {
  render(<ChatMessageList messages={messages.slice(0, 2)} isStreaming={false}
    onCopyAssistantMessage={async () => undefined} onRegenerateMessage={() => undefined}
    onEditMessage={() => undefined} />);
  expect(await screen.findByRole("button", { name: "Edit" })).toBeInTheDocument();
  expect(screen.getByText("First unsent draft")).toBeInTheDocument();
});

it("retains the editor text until the asynchronous edit succeeds", async () => {
  const user = userEvent.setup();
  let complete!: (value: boolean) => void;
  const edit = vi.fn(() => new Promise<boolean>((resolve) => { complete = resolve; }));
  render(<ChatMessageList messages={messages.slice(0, 2)} isStreaming={false}
    onCopyAssistantMessage={async () => undefined} onRegenerateMessage={() => undefined} onEditMessage={edit} />);
  await user.click(await screen.findByRole("button", { name: "Edit" }));
  await user.clear(screen.getByRole("textbox"));
  await user.type(screen.getByRole("textbox"), "Corrected draft");
  await user.click(screen.getByRole("button", { name: "Send" }));
  expect(screen.getByRole("textbox")).toHaveValue("Corrected draft");
  expect(screen.getByRole("button", { name: "Send" })).toBeDisabled();
  await act(async () => { complete(false); });
  await vi.waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("edit could not be sent"));
  expect(screen.getByRole("textbox")).toHaveValue("Corrected draft");
  expect(screen.getByRole("button", { name: "Send" })).toBeEnabled();
});

it("retries the selected unsent row rather than the tail", async () => {
  const user = userEvent.setup();
  const retry = vi.fn(async () => true);
  const { container } = render(<ChatMessageList messages={messages} isStreaming={false}
    onCopyAssistantMessage={async () => undefined} onRegenerateMessage={() => undefined} onRetryFailedSubmission={retry} />);
  const first = within(container.querySelector('[data-chat-message-id="-2"]') as HTMLElement);
  await user.click(first.getByRole("button", { name: "Retry" }));
  expect(retry).toHaveBeenCalledExactlyOnceWith(-2);
});

it("retains the visible copy and reports a failed discard", async () => {
  const user = userEvent.setup();
  const discard = vi.fn(async () => false);
  render(<ChatMessageList messages={messages.slice(0, 2)} isStreaming={false}
    onCopyAssistantMessage={async () => undefined} onRegenerateMessage={() => undefined}
    {...{ onDiscardFailedSubmission: discard }} />);
  await user.click(screen.getByRole("button", { name: "Discard unsent draft" }));
  await vi.waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("could not be discarded"));
  expect(screen.getByText("First unsent draft")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Discard unsent draft" })).toBeEnabled();
});

it("leaves ordinary persisted edit available and does not offer local discard for it", () => {
  render(<ChatMessageList messages={[{ id: 2, role: "user", content: "Sent message", parentMessageId: null }]}
    isStreaming={false} onCopyAssistantMessage={async () => undefined} onRegenerateMessage={() => undefined}
    onEditMessage={() => undefined} {...{ onDiscardFailedSubmission: () => true }} />);
  expect(screen.getByRole("button", { name: "Edit" })).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Discard unsent draft" })).toBeNull();
});

it("does not discard while a turn is being submitted", () => {
  render(<ChatMessageList messages={messages.slice(0, 2)} isStreaming
    onCopyAssistantMessage={async () => undefined} onRegenerateMessage={() => undefined}
    {...{ onDiscardFailedSubmission: () => true }} />);
  expect(screen.getByRole("button", { name: "Discard unsent draft" })).toBeDisabled();
});


it("keeps retry and discard but hides draft editing on unsupported backends", async () => {
  supported.mockResolvedValue(false);
  render(<ChatMessageList messages={messages.slice(0, 2)} isStreaming={false}
    onCopyAssistantMessage={async () => undefined} onRegenerateMessage={() => undefined}
    onEditMessage={() => undefined} onRetryFailedSubmission={async () => true}
    onDiscardFailedSubmission={() => true} />);
  await act(async () => {});
  expect(screen.queryByRole("button", { name: "Edit" })).toBeNull();
  expect(screen.getByRole("button", { name: "Retry" })).toBeEnabled();
  expect(screen.getByRole("button", { name: "Discard unsent draft" })).toBeEnabled();
});
