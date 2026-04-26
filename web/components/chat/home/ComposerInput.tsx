"use client";

import {
  forwardRef,
  memo,
  useCallback,
  useImperativeHandle,
  useLayoutEffect,
  useRef,
  useState,
  type RefObject,
} from "react";
import { useTranslation } from "react-i18next";
import AtMentionPopup from "@/components/chat/AtMentionPopup";

interface ComposerInputProps {
  textareaRef: RefObject<HTMLTextAreaElement | null>;
  activeCapabilityKey: string;
  isMathAnimatorMode: boolean;
  isVisualizeMode: boolean;
  // When true, parent has attachments/references queued and will accept a
  // send even if the text body is empty. Without this, Enter would silently
  // do nothing for an attachment-only message.
  canSendEmpty: boolean;
  onSend: (content: string) => void;
  onInputChange: (content: string) => void;
  onPaste: (e: React.ClipboardEvent) => void;
  onSelectNotebookPicker: () => void;
  onSelectHistoryPicker: () => void;
  onSelectQuestionBankPicker: () => void;
}

export interface ComposerInputHandle {
  clear: () => void;
  getValue: () => string;
}

export function shouldOpenAtPopup(value: string, cursorPos: number): boolean {
  const prefix = value.slice(0, cursorPos);
  return /(^|\s)@[^\s]*$/.test(prefix);
}

export function stripTrailingAtMention(value: string): string {
  return value.replace(/(^|\s)@[^\s]*$/, "$1").replace(/\s+$/, "");
}

export const ComposerInput = memo(
  forwardRef<ComposerInputHandle, ComposerInputProps>(function ComposerInput(
    {
      textareaRef,
      activeCapabilityKey,
      isMathAnimatorMode,
      isVisualizeMode,
      canSendEmpty,
      onSend,
      onInputChange,
      onPaste,
      onSelectNotebookPicker,
      onSelectHistoryPicker,
      onSelectQuestionBankPicker,
    },
    ref,
  ) {
    const { t } = useTranslation();
    const [input, setInput] = useState("");
    const [showAtPopup, setShowAtPopup] = useState(false);

    // Latest text mirrored into a ref by the change handlers (never updated
    // during render). The select-* handlers and the imperative handle read
    // from this ref so their identities stay stable across keystrokes,
    // letting `memo` on AtMentionPopup actually skip re-renders when
    // `showAtPopup` doesn't change.
    const inputRef = useRef("");
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
      }),
      [setInputBoth, onInputChange],
    );

    useLayoutEffect(() => {
      const el = textareaRef.current;
      if (!el) return;
      el.style.height = "28px";
      const next = Math.max(el.scrollHeight, 28);
      const bounded = Math.min(next, 200);
      el.style.height = `${bounded}px`;
      el.style.overflowY = next > 200 ? "auto" : "hidden";
    }, [input, activeCapabilityKey, textareaRef]);

    const handleInputChange = useCallback(
      (e: React.ChangeEvent<HTMLTextAreaElement>) => {
        const value = e.target.value;
        const cursorPos = e.target.selectionStart ?? value.length;
        setInputBoth(value);
        onInputChange(value);
        setShowAtPopup(shouldOpenAtPopup(value, cursorPos));
      },
      [setInputBoth, onInputChange],
    );

    const handleTextareaClick = useCallback(
      (e: React.MouseEvent<HTMLTextAreaElement>) => {
        const target = e.currentTarget;
        setShowAtPopup(
          shouldOpenAtPopup(
            target.value,
            target.selectionStart ?? target.value.length,
          ),
        );
      },
      [],
    );

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
    }, [canSendEmpty, onSend, setInputBoth, onInputChange]);

    const handleKeyDown = useCallback(
      (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
        if (e.key === "Enter" && !e.shiftKey) {
          e.preventDefault();
          doSend();
        } else if (e.key === "Escape") {
          setShowAtPopup(false);
        }
      },
      [doSend],
    );

    const handleSelectNotebook = useCallback(() => {
      const next = stripTrailingAtMention(inputRef.current);
      setInputBoth(next);
      onInputChange(next);
      setShowAtPopup(false);
      onSelectNotebookPicker();
    }, [setInputBoth, onInputChange, onSelectNotebookPicker]);

    const handleSelectHistory = useCallback(() => {
      const next = stripTrailingAtMention(inputRef.current);
      setInputBoth(next);
      onInputChange(next);
      setShowAtPopup(false);
      onSelectHistoryPicker();
    }, [setInputBoth, onInputChange, onSelectHistoryPicker]);

    const handleSelectQuestionBank = useCallback(() => {
      const next = stripTrailingAtMention(inputRef.current);
      setInputBoth(next);
      onInputChange(next);
      setShowAtPopup(false);
      onSelectQuestionBankPicker();
    }, [setInputBoth, onInputChange, onSelectQuestionBankPicker]);

    return (
      <div className="px-3 pt-3 pb-2 sm:px-4 sm:pt-3.5">
        <AtMentionPopup
          open={showAtPopup}
          onSelectNotebook={handleSelectNotebook}
          onSelectHistory={handleSelectHistory}
          onSelectQuestionBank={handleSelectQuestionBank}
        />
        <textarea
          ref={textareaRef}
          value={input}
          onChange={handleInputChange}
          onKeyDown={handleKeyDown}
          onClick={handleTextareaClick}
          onPaste={onPaste}
          rows={1}
          suppressHydrationWarning
          placeholder={
            isMathAnimatorMode
              ? t("Describe the math animation or storyboard you want...")
              : isVisualizeMode
                ? t("Describe the chart or diagram you want to visualize...")
                : t("How can I help you today?")
          }
          className="w-full resize-none overflow-hidden bg-transparent text-[16px] leading-relaxed text-[var(--foreground)] outline-none placeholder:text-[var(--muted-foreground)] sm:text-[15px]"
          style={{ transition: "height 0.15s ease-out", minHeight: 28 }}
        />
      </div>
    );
  }),
);
