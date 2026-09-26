import { createRef } from "react";
import { fireEvent, render, screen, within } from "@testing-library/react";
import { expect, it, vi } from "vitest";

import { ComposerInput } from "@/components/chat/home/ComposerInput";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

const languageOptions = [
  { value: "zh", label: "简体中文" },
  { value: "fr", label: "Français" },
];

function renderComposer({
  persona = true,
  language = true,
  disabled = false,
  override = null,
}: {
  persona?: boolean;
  language?: boolean;
  disabled?: boolean;
  override?: string | null;
} = {}) {
  const onSend = vi.fn();
  const onInputChange = vi.fn();
  const onOpenPersonaSelector = vi.fn();
  const onReplyLanguageChange = vi.fn();

  render(
    <ComposerInput
      textareaRef={createRef<HTMLTextAreaElement>()}
      isVisualizeMode={false}
      canSendEmpty={false}
      onSend={onSend}
      onInputChange={onInputChange}
      onPaste={vi.fn()}
      selectedCounts={{
        attachments: 0,
        knowledge: 0,
        chatHistory: 0,
        myAgents: 0,
        books: 0,
        reading: 0,
        notebooks: 0,
        questionBank: 0,
        persona: 0,
        memory: 0,
      }}
      knowledgeAvailable={false}
      personaAvailable={false}
      onSelectAttach={vi.fn()}
      onSelectNotebookPicker={vi.fn()}
      onSelectBookPicker={vi.fn()}
      onSelectHistoryPicker={vi.fn()}
      onSelectQuestionBankPicker={vi.fn()}
      onSelectPersonaPicker={vi.fn()}
      onSelectMemoryPicker={vi.fn()}
      onOpenPersonaSelector={persona ? onOpenPersonaSelector : undefined}
      replyLanguageOverride={override}
      replyLanguageOptions={languageOptions}
      replyLanguageDefaultLabel="English"
      replyLanguageDisabled={disabled}
      onReplyLanguageChange={language ? onReplyLanguageChange : undefined}
    />,
  );

  return {
    input: screen.getByRole("textbox") as HTMLTextAreaElement,
    onSend,
    onInputChange,
    onOpenPersonaSelector,
    onReplyLanguageChange,
  };
}

it("lists both slash commands and filters them by prefix", () => {
  const { input } = renderComposer();

  fireEvent.change(input, { target: { value: "/" } });
  expect(within(screen.getByRole("listbox", { name: "Commands" })).getAllByRole("option"))
    .toHaveLength(2);
  expect(screen.getByRole("option", { name: /\/persona/ })).toBeInTheDocument();
  expect(screen.getByRole("option", { name: /\/language/ })).toBeInTheDocument();

  fireEvent.change(input, { target: { value: "/lan" } });
  expect(screen.queryByRole("option", { name: /\/persona/ })).not.toBeInTheDocument();
  expect(screen.getByRole("option", { name: /\/language/ })).toBeInTheDocument();

  fireEvent.change(input, { target: { value: "/per" } });
  expect(screen.getByRole("option", { name: /\/persona/ })).toBeInTheDocument();
  expect(screen.queryByRole("option", { name: /\/language/ })).not.toBeInTheDocument();

  fireEvent.change(input, { target: { value: "Please /language" } });
  expect(screen.queryByRole("listbox", { name: "Commands" })).not.toBeInTheDocument();
});

it("uses arrow keys and Enter to open the language list without sending the command", () => {
  const { input, onSend, onInputChange, onOpenPersonaSelector, onReplyLanguageChange } =
    renderComposer();

  fireEvent.change(input, { target: { value: "/" } });
  fireEvent.keyDown(input, { key: "ArrowDown" });
  expect(screen.getByRole("option", { name: /\/language/ })).toHaveAttribute("aria-selected", "true");
  fireEvent.keyDown(input, { key: "Enter" });

  expect(input).toHaveValue("");
  expect(onInputChange).toHaveBeenLastCalledWith("");
  expect(onSend).not.toHaveBeenCalled();
  expect(onOpenPersonaSelector).not.toHaveBeenCalled();
  const choices = within(screen.getByRole("listbox", { name: "Reply language" }));
  expect(choices.getByRole("option", { name: "Account default (English)" })).toBeInTheDocument();
  expect(choices.getByRole("option", { name: "简体中文" })).toBeInTheDocument();
  expect(choices.getByRole("option", { name: "Français" })).toBeInTheDocument();

  fireEvent.click(choices.getByRole("option", { name: "Français" }));
  expect(onReplyLanguageChange).toHaveBeenCalledExactlyOnceWith("fr");
  expect(screen.queryByRole("listbox", { name: "Reply language" })).not.toBeInTheDocument();
  expect(onSend).not.toHaveBeenCalled();
});

it("selects the account default by keyboard and closes the menus with Escape", () => {
  const { input, onReplyLanguageChange, onSend } = renderComposer({ override: "zh" });

  fireEvent.change(input, { target: { value: "/language" } });
  fireEvent.keyDown(input, { key: "Enter" });
  const choices = within(screen.getByRole("listbox", { name: "Reply language" }));
  expect(choices.getByRole("option", { name: "简体中文" })).toHaveAttribute("aria-selected", "true");
  fireEvent.keyDown(input, { key: "ArrowUp" });
  fireEvent.keyDown(input, { key: "Enter" });
  expect(onReplyLanguageChange).toHaveBeenCalledExactlyOnceWith("");
  expect(onSend).not.toHaveBeenCalled();

  fireEvent.change(input, { target: { value: "/language" } });
  fireEvent.keyDown(input, { key: "Enter" });
  expect(screen.getByRole("listbox", { name: "Reply language" })).toBeInTheDocument();
  fireEvent.keyDown(input, { key: "Escape" });
  expect(screen.queryByRole("listbox", { name: "Reply language" })).not.toBeInTheDocument();
  expect(onReplyLanguageChange).toHaveBeenCalledTimes(1);

  fireEvent.change(input, { target: { value: "/" } });
  fireEvent.keyDown(input, { key: "Escape" });
  expect(screen.queryByRole("listbox", { name: "Commands" })).not.toBeInTheDocument();
});

it("keeps persona available while the reply-language command is disabled", () => {
  const { input, onOpenPersonaSelector, onReplyLanguageChange, onSend } =
    renderComposer({ disabled: true });

  fireEvent.change(input, { target: { value: "/" } });
  expect(screen.getByRole("option", { name: /\/persona/ })).toBeInTheDocument();
  expect(screen.queryByRole("option", { name: /\/language/ })).not.toBeInTheDocument();
  fireEvent.keyDown(input, { key: "Enter" });
  expect(onOpenPersonaSelector).toHaveBeenCalledOnce();
  expect(onReplyLanguageChange).not.toHaveBeenCalled();
  expect(onSend).not.toHaveBeenCalled();

  fireEvent.change(input, { target: { value: "/language" } });
  expect(screen.queryByRole("listbox", { name: "Commands" })).not.toBeInTheDocument();
});
