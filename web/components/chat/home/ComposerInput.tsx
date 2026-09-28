"use client";

import {
  forwardRef,
  memo,
  useCallback,
  useEffect,
  useId,
  useImperativeHandle,
  useMemo,
  useRef,
  useState,
  type RefObject,
} from "react";
import { useTranslation } from "react-i18next";
import { Bot, Check, Languages, UserRound } from "lucide-react";
import ChatSpaceMenu, {
  type ChatSpaceSelectionCounts,
} from "@/components/chat/space/ChatSpaceMenu";
import { agentGlyph } from "@/components/agents/agent-icons";
import { shouldSubmitOnEnter } from "@/lib/composer-keyboard";
import { useAutoSizedTextarea } from "@/lib/use-auto-sized-textarea";
import { useImeComposing } from "@/lib/use-ime-composing";

interface ComposerInputProps {
  textareaRef: RefObject<HTMLTextAreaElement | null>;
  isVisualizeMode: boolean;
  isStreaming?: boolean;
  // When true, parent has attachments/references queued and will accept a
  // send even if the text body is empty. Without this, Enter would silently
  // do nothing for an attachment-only message.
  canSendEmpty: boolean;
  onSend: (content: string) => void;
  onInputChange: (content: string) => void;
  onPaste: (e: React.ClipboardEvent) => void;
  selectedCounts: ChatSpaceSelectionCounts;
  /**
   * Hide the Knowledge entry in the @ menu. Knowledge now lives in the
   * toolbar KnowledgeSelector chip, so this is currently always false —
   * kept as a prop in case a surface wants the @ entry back.
   */
  knowledgeAvailable: boolean;
  /** Hide the Persona entry (main chat: persona has its own selector). */
  personaAvailable: boolean;
  /**
   * Connected subagents selectable via the ``@`` mention. When provided, ``@``
   * opens an agent picker (the main-chat behavior) instead of the Space menu;
   * surfaces that omit this (e.g. the quiz follow-up) keep the Space menu on @.
   */
  connectedAgents?: { name: string; kind?: string }[];
  selectedAgent?: string | null;
  onSelectAgent?: (name: string | null) => void;
  onSelectAttach: () => void;
  onSelectKnowledge?: () => void;
  onSelectNotebookPicker: () => void;
  onSelectBookPicker: () => void;
  onSelectReadingPicker?: () => void;
  onSelectHistoryPicker: () => void;
  onSelectAgentsPicker?: () => void;
  /** Hide the My Agents entry (e.g. the quiz follow-up surface). */
  agentsAvailable?: boolean;
  onSelectQuestionBankPicker: () => void;
  onSelectPersonaPicker: () => void;
  onSelectMemoryPicker: () => void;
  /**
   * Opens the session persona selector from `/persona`. Surfaces without
   * session personas (e.g. quiz follow-up) omit this command.
   */
  onOpenPersonaSelector?: () => void;
  /** Current conversation's reply-language choice. Null follows the account default. */
  replyLanguageOverride?: string | null;
  replyLanguageOptions?: readonly { value: string; label: string }[];
  replyLanguageDefaultLabel?: string;
  replyLanguageDisabled?: boolean;
  onReplyLanguageChange?: (value: string) => void;
  languagePickerBelow?: boolean;
  /**
   * Override the default placeholder. When unset, falls back to the
   * main chat ("How can I help you today?") / visualize defaults.
   */
  placeholder?: string;
  /**
   * A line Tab accepts into the empty composer.
   *
   * The mastery study screen offers a question the learner could ask; reading
   * it and then retyping it is exactly the work the offer was meant to save,
   * so Tab takes it. Only while the composer is empty — past the first
   * character the learner is writing their own question, and stealing Tab
   * there would break moving focus out of the box.
   */
  placeholderCompletion?: string;
  /**
   * Minimum textarea height in pixels. The auto-sized hook grows the
   * textarea past this as the user types. Bumped on the empty-state
   * composer so the resting box looks inviting rather than crammed.
   */
  minHeight?: number;
}

export interface ComposerInputHandle {
  clear: () => void;
  getValue: () => string;
  /**
   * Programmatically replace the textarea contents (used by the
   * ``AskUserOptions`` chip click handler — picks an option, prefills
   * the composer, leaves it to the user to edit/send rather than
   * auto-firing the message).
   */
  setValue: (value: string) => void;
}

export function shouldOpenAtPopup(value: string, cursorPos: number): boolean {
  const prefix = value.slice(0, cursorPos);
  return /(^|\s)@[^\s]*$/.test(prefix);
}

export function stripTrailingAtMention(value: string): string {
  return value.replace(/(^|\s)@[^\s]*$/, "$1").replace(/\s+$/, "");
}

/** The text typed after a trailing ``@`` (the agent-mention query), or "". */
export function atMentionQuery(value: string, cursorPos: number): string {
  const match = /(^|\s)@([^\s]*)$/.exec(value.slice(0, cursorPos));
  return match ? match[2] : "";
}

type SlashCommand = "persona" | "language";

/** Slash commands only match at the start of the composer. */
export function matchingSlashCommands(
  value: string,
  cursorPos: number,
  enabled: readonly SlashCommand[] = ["persona", "language"],
): SlashCommand[] {
  const match = /^\/([a-z]*)$/i.exec(value.slice(0, cursorPos));
  if (!match) return [];
  const query = match[1].toLowerCase();
  return enabled.filter((command) => command.startsWith(query));
}

export function shouldOpenSlashPopup(
  value: string,
  cursorPos: number,
): boolean {
  return matchingSlashCommands(value, cursorPos).length > 0;
}

export const ComposerInput = memo(
  forwardRef<ComposerInputHandle, ComposerInputProps>(function ComposerInput(
    {
      textareaRef,
      isVisualizeMode,
      isStreaming = false,
      canSendEmpty,
      onSend,
      onInputChange,
      onPaste,
      selectedCounts,
      knowledgeAvailable,
      personaAvailable,
      connectedAgents = [],
      selectedAgent = null,
      onSelectAgent,
      onSelectAttach,
      onSelectKnowledge,
      onSelectNotebookPicker,
      onSelectBookPicker,
      onSelectReadingPicker,
      onSelectHistoryPicker,
      onSelectAgentsPicker,
      agentsAvailable = true,
      onSelectQuestionBankPicker,
      onSelectPersonaPicker,
      onSelectMemoryPicker,
      onOpenPersonaSelector,
      replyLanguageOverride = null,
      replyLanguageOptions = [],
      replyLanguageDefaultLabel = "English",
      replyLanguageDisabled = false,
      onReplyLanguageChange,
      languagePickerBelow = false,
      placeholder,
      placeholderCompletion,
      minHeight = 28,
    },
    ref,
  ) {
    const { t } = useTranslation();
    const [input, setInput] = useState("");
    const [showAtPopup, setShowAtPopup] = useState(false);
    const [showSlashPopup, setShowSlashPopup] = useState(false);
    const [slashCommands, setSlashCommands] = useState<SlashCommand[]>([]);
    const [activeSlashIndex, setActiveSlashIndex] = useState(0);
    const [showLanguagePopup, setShowLanguagePopup] = useState(false);
    const [activeLanguageIndex, setActiveLanguageIndex] = useState(0);
    const [atQuery, setAtQuery] = useState("");
    const slashListId = useId();
    const languageListId = useId();
    const availableSlashCommands = useMemo<SlashCommand[]>(() => [
      ...(onOpenPersonaSelector ? ["persona" as const] : []),
      ...(onReplyLanguageChange && !replyLanguageDisabled ? ["language" as const] : []),
    ], [onOpenPersonaSelector, onReplyLanguageChange, replyLanguageDisabled]);
    const languageChoices = useMemo(() => [
      {
        value: "",
        label: `${t("Account default")} (${replyLanguageDefaultLabel})`,
      },
      ...replyLanguageOptions,
    ], [replyLanguageDefaultLabel, replyLanguageOptions, t]);
    // Main chat passes ``onSelectAgent`` → ``@`` picks a connected agent. Other
    // surfaces (quiz follow-up) omit it and keep the @ Space menu.
    const agentMentionMode = Boolean(onSelectAgent);
    const filteredAgents = useMemo(
      () =>
        agentMentionMode
          ? connectedAgents.filter((agent) =>
              agent.name.toLowerCase().includes(atQuery.toLowerCase()),
            )
          : [],
      [agentMentionMode, atQuery, connectedAgents],
    );

    // Latest text mirrored into a ref by the change handlers (never updated
    // during render). The @space handlers and the imperative handle read
    // from this ref so their identities stay stable across keystrokes,
    // letting `memo` on ChatSpaceMenu actually skip re-renders when
    // `showAtPopup` doesn't change.
    const inputRef = useRef("");
    const { isComposingRef, onCompositionStart, onCompositionEnd } =
      useImeComposing();
    // Helper that always updates state and ref together so they can't drift.
    const setInputBoth = useCallback((value: string) => {
      inputRef.current = value;
      setInput(value);
    }, []);

    useImperativeHandle(
      ref,
      () => ({
        clear: () => {
          setInputBoth("");
          onInputChange("");
        },
        getValue: () => inputRef.current,
        setValue: (value: string) => {
          const text = value ?? "";
          setInputBoth(text);
          onInputChange(text);
          // Focus + move caret to the end so the user can immediately
          // edit or press Enter to send.
          const el = textareaRef.current;
          if (el) {
            requestAnimationFrame(() => {
              el.focus();
              el.setSelectionRange(text.length, text.length);
            });
          }
        },
      }),
      [setInputBoth, onInputChange, textareaRef],
    );

    useAutoSizedTextarea(textareaRef, input, { min: minHeight, max: 200 });

    const updateSlashPopup = useCallback((value: string, cursorPos: number) => {
      const matches = matchingSlashCommands(value, cursorPos, availableSlashCommands);
      setSlashCommands(matches);
      setActiveSlashIndex(0);
      setShowSlashPopup(matches.length > 0);
      setShowLanguagePopup(false);
    }, [availableSlashCommands]);

    const handleInputChange = useCallback(
      (e: React.ChangeEvent<HTMLTextAreaElement>) => {
        const value = e.target.value;
        const cursorPos = e.target.selectionStart ?? value.length;
        setInputBoth(value);
        onInputChange(value);
        const atOpen = shouldOpenAtPopup(value, cursorPos);
        setShowAtPopup(atOpen);
        setAtQuery(atOpen ? atMentionQuery(value, cursorPos) : "");
        updateSlashPopup(value, cursorPos);
      },
      [setInputBoth, onInputChange, updateSlashPopup],
    );

    const handleTextareaClick = useCallback(
      (e: React.MouseEvent<HTMLTextAreaElement>) => {
        const target = e.currentTarget;
        const cursorPos = target.selectionStart ?? target.value.length;
        const atOpen = shouldOpenAtPopup(target.value, cursorPos);
        setShowAtPopup(atOpen);
        setAtQuery(atOpen ? atMentionQuery(target.value, cursorPos) : "");
        updateSlashPopup(target.value, cursorPos);
      },
      [updateSlashPopup],
    );

    const handleSelectSlashCommand = useCallback((command: SlashCommand) => {
      // Command text is never part of the message sent to the model.
      setInputBoth("");
      onInputChange("");
      setShowSlashPopup(false);
      setSlashCommands([]);
      if (command === "persona") {
        onOpenPersonaSelector?.();
        return;
      }
      const selectedIndex = languageChoices.findIndex(
        (choice) => choice.value === (replyLanguageOverride ?? ""),
      );
      setActiveLanguageIndex(Math.max(0, selectedIndex));
      setShowLanguagePopup(true);
      textareaRef.current?.focus();
    }, [setInputBoth, onInputChange, onOpenPersonaSelector, languageChoices, replyLanguageOverride, textareaRef]);

    const handleSelectReplyLanguage = useCallback((value: string) => {
      setShowLanguagePopup(false);
      onReplyLanguageChange?.(value);
      textareaRef.current?.focus();
    }, [onReplyLanguageChange, textareaRef]);

    const doSend = useCallback(() => {
      const content = inputRef.current.trim();
      // Allow sending when text is empty but the parent has attachments or
      // references queued (canSendEmpty). This matches the send-button's
      // own enablement logic in ChatComposer (`canSend`).
      if (!content && !canSendEmpty) return;
      onSend(content);
      setInputBoth("");
      onInputChange("");
      setShowAtPopup(false);
      setShowSlashPopup(false);
      setShowLanguagePopup(false);
    }, [canSendEmpty, onSend, setInputBoth, onInputChange]);

    const clearTrailingMention = useCallback(() => {
      const next = stripTrailingAtMention(inputRef.current);
      setInputBoth(next);
      onInputChange(next);
    }, [setInputBoth, onInputChange]);

    const handleSelectAgentMention = useCallback(
      (name: string) => {
        clearTrailingMention();
        setShowAtPopup(false);
        setAtQuery("");
        onSelectAgent?.(name);
      },
      [clearTrailingMention, onSelectAgent],
    );

    const handleKeyDown = useCallback(
      (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
        if (showLanguagePopup && !isComposingRef.current) {
          if (e.key === "ArrowDown" || e.key === "ArrowUp") {
            e.preventDefault();
            setActiveLanguageIndex((index) =>
              (index + (e.key === "ArrowDown" ? 1 : -1) + languageChoices.length) % languageChoices.length,
            );
            return;
          }
          if (e.key === "Enter" || e.key === "Tab") {
            e.preventDefault();
            handleSelectReplyLanguage(languageChoices[activeLanguageIndex]?.value ?? "");
            return;
          }
          if (e.key === "Escape") {
            e.preventDefault();
            setShowLanguagePopup(false);
            return;
          }
        }
        if (showSlashPopup && !isComposingRef.current) {
          if (e.key === "ArrowDown" || e.key === "ArrowUp") {
            e.preventDefault();
            setActiveSlashIndex((index) =>
              (index + (e.key === "ArrowDown" ? 1 : -1) + slashCommands.length) % slashCommands.length,
            );
            return;
          }
          if (e.key === "Enter" || e.key === "Tab") {
            e.preventDefault();
            const command = slashCommands[activeSlashIndex];
            if (command) handleSelectSlashCommand(command);
            return;
          }
          if (e.key === "Escape") {
            e.preventDefault();
            setShowSlashPopup(false);
            return;
          }
        }
        // With the agent-mention popup open, Enter/Tab confirm the first match.
        if (
          showAtPopup &&
          agentMentionMode &&
          filteredAgents.length > 0 &&
          !isComposingRef.current &&
          (e.key === "Enter" || e.key === "Tab")
        ) {
          e.preventDefault();
          handleSelectAgentMention(filteredAgents[0].name);
          return;
        }
        // Tab takes the offered question — but only into an empty composer, so
        // Tab keeps meaning "leave this box" the moment there is a draft in it.
        if (
          e.key === "Tab" &&
          !e.shiftKey &&
          placeholderCompletion &&
          !inputRef.current.trim()
        ) {
          e.preventDefault();
          setInputBoth(placeholderCompletion);
          onInputChange(placeholderCompletion);
          return;
        }
        if (shouldSubmitOnEnter(e, isComposingRef.current)) {
          e.preventDefault();
          if (!isStreaming) doSend();
        } else if (e.key === "Escape") {
          setShowAtPopup(false);
          setShowSlashPopup(false);
          setShowLanguagePopup(false);
        }
      },
      [
        doSend,
        isStreaming,
        showSlashPopup,
        slashCommands,
        activeSlashIndex,
        handleSelectSlashCommand,
        showLanguagePopup,
        languageChoices,
        activeLanguageIndex,
        handleSelectReplyLanguage,
        showAtPopup,
        agentMentionMode,
        filteredAgents,
        handleSelectAgentMention,
        isComposingRef,
        onInputChange,
        placeholderCompletion,
        setInputBoth,
      ],
    );

    const handleSelectSpaceItem = useCallback(
      (
        key:
          | "attach"
          | "knowledge"
          | "chat_history"
          | "my_agents"
          | "books"
          | "reading"
          | "notebooks"
          | "question_bank"
          | "persona"
          | "memory",
      ) => {
        clearTrailingMention();
        setShowAtPopup(false);
        if (key === "attach") onSelectAttach();
        else if (key === "knowledge") onSelectKnowledge?.();
        else if (key === "chat_history") onSelectHistoryPicker();
        else if (key === "my_agents") onSelectAgentsPicker?.();
        else if (key === "books") onSelectBookPicker();
        else if (key === "reading") onSelectReadingPicker?.();
        else if (key === "notebooks") onSelectNotebookPicker();
        else if (key === "question_bank") onSelectQuestionBankPicker();
        else if (key === "persona") onSelectPersonaPicker();
        else if (key === "memory") onSelectMemoryPicker();
      },
      [
        clearTrailingMention,
        onSelectAttach,
        onSelectKnowledge,
        onSelectHistoryPicker,
        onSelectAgentsPicker,
        onSelectBookPicker,
        onSelectReadingPicker,
        onSelectNotebookPicker,
        onSelectQuestionBankPicker,
        onSelectPersonaPicker,
        onSelectMemoryPicker,
      ],
    );

    // Close the @/slash popups on outside click. Without this, clicking
    // anywhere outside the popup or textarea left the menu hovering
    // indefinitely. We bind on mousedown so the close fires before a
    // synthetic click on a sibling button (e.g. the Tools menu) can
    // re-open something else.
    const popupRef = useRef<HTMLDivElement>(null);
    const slashPopupRef = useRef<HTMLDivElement>(null);
    const languagePopupRef = useRef<HTMLDivElement>(null);
    const languageListRef = useRef<HTMLDivElement>(null);
    useEffect(() => {
      if (!showLanguagePopup) return;
      const option = languageListRef.current?.children[activeLanguageIndex];
      if (option && "scrollIntoView" in option) {
        option.scrollIntoView({ block: "nearest" });
      }
    }, [showLanguagePopup, activeLanguageIndex]);
    useEffect(() => {
      if (!showAtPopup && !showSlashPopup && !showLanguagePopup) return;
      const handler = (e: MouseEvent) => {
        const target = e.target as Node | null;
        if (!target) return;
        if (popupRef.current?.contains(target)) return;
        if (slashPopupRef.current?.contains(target)) return;
        if (languagePopupRef.current?.contains(target)) return;
        if (textareaRef.current?.contains(target)) return;
        setShowAtPopup(false);
        setShowSlashPopup(false);
        setShowLanguagePopup(false);
      };
      document.addEventListener("mousedown", handler);
      return () => document.removeEventListener("mousedown", handler);
    }, [showAtPopup, showSlashPopup, showLanguagePopup, textareaRef]);

    const basePlaceholder =
      placeholder ??
      (isVisualizeMode
        ? t(
            "Describe the chart, diagram, or animation you want to visualize...",
          )
        : t("How can I help you today?"));
    // The Tab hint used to be a separate pill under the textarea — its own
    // block that appeared and disappeared as the offer came and went,
    // nudging the composer's height around it. Rendered as an overlay over
    // the (now empty) native placeholder instead: same muted tone, same
    // line, no layout of its own. Two spans rather than one concatenated
    // string — a hint long enough to fill the line would otherwise wrap the
    // textarea onto a second line and silently clip the very text that
    // explains how to accept it; the hint span truncates with an ellipsis
    // instead, while "→ Tab to complete" stays pinned and fully visible.
    const showHintOverlay = Boolean(placeholderCompletion) && !input.trim();

    return (
      <div className="px-4 pt-3.5 pb-2">
        {showAtPopup && agentMentionMode && (
          <div
            ref={popupRef}
            className="absolute bottom-full left-0 z-[70] mb-2"
          >
            <div
              role="listbox"
              aria-label={t("Talk to an agent")}
              className="w-[300px] overflow-hidden rounded-xl border border-[var(--border)] bg-[var(--popover)] py-1 shadow-lg backdrop-blur-md"
            >
              <div className="px-3 pb-1 pt-1.5 text-[11px] font-medium uppercase tracking-[0.05em] text-[var(--muted-foreground)]">
                {t("Talk to an agent")}
              </div>
              {filteredAgents.length === 0 ? (
                <div className="px-3 py-2 text-[12px] text-[var(--muted-foreground)]">
                  {connectedAgents.length === 0
                    ? t("No connected agents — connect one in My Agents.")
                    : t("No matching agent")}
                </div>
              ) : (
                <div className="max-h-[260px] overflow-y-auto">
                  {filteredAgents.map((agent) => {
                    const Glyph = agentGlyph(agent.kind) ?? Bot;
                    const active = selectedAgent === agent.name;
                    return (
                      <button
                        key={agent.name}
                        type="button"
                        role="option"
                        aria-selected={active}
                        onClick={() => handleSelectAgentMention(agent.name)}
                        className={`flex w-full items-center gap-2.5 px-3 py-1.5 text-left transition-colors active:bg-[var(--muted)]/70 ${
                          active
                            ? "bg-[var(--primary)]/[0.06]"
                            : "hover:bg-[var(--muted)]/45"
                        }`}
                      >
                        <Glyph size={15} className="shrink-0" />
                        <span className="min-w-0 flex-1 truncate text-[12.5px] font-medium text-[var(--foreground)]">
                          {agent.name}
                        </span>
                        {active && (
                          <Check
                            size={14}
                            strokeWidth={2}
                            className="shrink-0 text-[var(--primary)]"
                          />
                        )}
                      </button>
                    );
                  })}
                </div>
              )}
            </div>
          </div>
        )}
        {showAtPopup && !agentMentionMode && (
          <div
            ref={popupRef}
            className="absolute bottom-full left-0 z-[70] mb-2"
          >
            <ChatSpaceMenu
              variant="mention"
              selectedCounts={selectedCounts}
              knowledgeAvailable={knowledgeAvailable}
              personaAvailable={personaAvailable}
              agentsAvailable={agentsAvailable}
              readingAvailable={Boolean(onSelectReadingPicker)}
              onSelectItem={handleSelectSpaceItem}
            />
          </div>
        )}
        {showSlashPopup && (
          <div
            ref={slashPopupRef}
            className="absolute bottom-full left-0 z-[70] mb-2"
          >
            <div
              id={slashListId}
              role="listbox"
              aria-label={t("Commands")}
              className="w-[300px] rounded-xl border border-[var(--border)] bg-[var(--popover)] py-1.5 shadow-lg backdrop-blur-md"
            >
              {slashCommands.map((command, index) => {
                const Icon = command === "persona" ? UserRound : Languages;
                return (
                  <button
                    key={command}
                    id={`${slashListId}-option-${index}`}
                    type="button"
                    role="option"
                    aria-selected={index === activeSlashIndex}
                    onMouseEnter={() => setActiveSlashIndex(index)}
                    onClick={() => handleSelectSlashCommand(command)}
                    className={`flex w-full items-center gap-2.5 px-3 py-2 text-left text-[12.5px] transition-colors ${
                      index === activeSlashIndex
                        ? "bg-[var(--muted)]/60"
                        : "hover:bg-[var(--muted)]/45"
                    }`}
                  >
                    <Icon
                      size={14}
                      strokeWidth={1.7}
                      className="shrink-0 text-[var(--muted-foreground)]"
                    />
                    {/* Command syntax tokens must not be localized. */}
                    <span className="font-medium text-[var(--foreground)]">
                      {command === "persona" ? "/persona" : "/language"}
                    </span>
                    <span className="min-w-0 truncate text-[var(--muted-foreground)]">
                      {command === "persona"
                        ? t("Switch the persona for this chat session")
                        : t("Switch the reply language for this chat session")}
                    </span>
                  </button>
                );
              })}
            </div>
          </div>
        )}
        {showLanguagePopup && (
          <div
            ref={languagePopupRef}
            className={`absolute left-0 z-[70] ${
              languagePickerBelow ? "top-full mt-2" : "bottom-full mb-2"
            }`}
          >
            <div
              id={languageListId}
              role="listbox"
              aria-label={t("Reply language")}
              className="w-[300px] overflow-hidden rounded-xl border border-[var(--border)] bg-[var(--popover)] py-1.5 shadow-lg backdrop-blur-md"
            >
              <div className="px-3 pb-1 pt-1 text-[11px] font-medium uppercase tracking-[0.05em] text-[var(--muted-foreground)]">
                {t("Reply language")}
              </div>
              <div ref={languageListRef} className="max-h-[280px] overflow-y-auto">
                {languageChoices.map((choice, index) => {
                  const selected = choice.value === (replyLanguageOverride ?? "");
                  return (
                    <button
                      key={choice.value}
                      id={`${languageListId}-option-${index}`}
                      type="button"
                      role="option"
                      aria-selected={selected}
                      onMouseEnter={() => setActiveLanguageIndex(index)}
                      onClick={() => handleSelectReplyLanguage(choice.value)}
                      className={`flex w-full items-center gap-2.5 px-3 py-1.5 text-left text-[12.5px] transition-colors ${
                        index === activeLanguageIndex
                          ? "bg-[var(--muted)]/60"
                          : "hover:bg-[var(--muted)]/45"
                      } ${index === 1 ? "border-t border-[var(--border)]" : ""}`}
                    >
                      <span className="min-w-0 flex-1 truncate text-[var(--foreground)]">
                        {choice.label}
                      </span>
                      {selected && <Check size={14} strokeWidth={2} className="shrink-0 text-[var(--primary)]" />}
                    </button>
                  );
                })}
              </div>
            </div>
          </div>
        )}
        <div className="relative">
          <textarea
            ref={textareaRef}
            value={input}
            onChange={handleInputChange}
            onKeyDown={handleKeyDown}
            onCompositionStart={onCompositionStart}
            onCompositionEnd={onCompositionEnd}
            onClick={handleTextareaClick}
            onPaste={onPaste}
            rows={1}
            // Cap input at 32k chars. A bigger paste (e.g. an entire textbook
            // dumped via Cmd+V) would force a layout reflow on every keystroke
            // and lock the page; the cap is a defensive guard, not a real
            // product limit. Users hit by this cap should be using the
            // attachment path, not the composer body.
            maxLength={32000}
            suppressHydrationWarning
            placeholder={placeholderCompletion ? "" : basePlaceholder}
            aria-haspopup={showSlashPopup || showLanguagePopup ? "listbox" : undefined}
            aria-controls={showSlashPopup ? slashListId : showLanguagePopup ? languageListId : undefined}
            aria-activedescendant={showSlashPopup
              ? `${slashListId}-option-${activeSlashIndex}`
              : showLanguagePopup
                ? `${languageListId}-option-${activeLanguageIndex}`
                : undefined}
            // The overlay below replaces the native placeholder visually
            // (so a long hint can truncate instead of wrapping), but an
            // empty placeholder would otherwise leave the field with no
            // accessible name — this restores one that reads the same as
            // what's on screen.
            aria-label={
              placeholderCompletion
                ? `${placeholderCompletion} — ${t("Tab to complete")}`
                : undefined
            }
            className="w-full resize-none overflow-hidden bg-transparent text-[16px] leading-relaxed text-[var(--foreground)] outline-none placeholder:text-[var(--muted-foreground)]"
            style={{ transition: "height 0.15s ease-out" }}
          />
          {showHintOverlay ? (
            <div
              aria-hidden="true"
              className="pointer-events-none absolute inset-0 flex items-start gap-1 overflow-hidden text-[16px] leading-relaxed text-[var(--muted-foreground)]"
            >
              <span className="min-w-0 flex-1 overflow-hidden text-ellipsis whitespace-nowrap">
                {placeholderCompletion}
              </span>
              <span className="shrink-0 whitespace-nowrap">
                → {t("Tab to complete")}
              </span>
            </div>
          ) : null}
        </div>
      </div>
    );
  }),
);
