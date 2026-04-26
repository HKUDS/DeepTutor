"use client";

import {
  memo,
  useCallback,
  useLayoutEffect,
  useState,
  type RefObject,
} from "react";
import { useTranslation } from "react-i18next";

interface SimpleComposerInputProps {
  textareaRef: RefObject<HTMLTextAreaElement | null>;
  onSend: (content: string) => void;
  disabled?: boolean;
}

export const SimpleComposerInput = memo(function SimpleComposerInput({
  textareaRef,
  onSend,
  disabled,
}: SimpleComposerInputProps) {
  const { t } = useTranslation();
  const [input, setInput] = useState("");

  useLayoutEffect(() => {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = "auto";
    const next = Math.max(el.scrollHeight, 42);
    el.style.height = `${Math.min(next, 200)}px`;
  }, [input, textareaRef]);

  const handleInputChange = useCallback(
    (e: React.ChangeEvent<HTMLTextAreaElement>) => {
      setInput(e.target.value);
    },
    [],
  );

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        const content = input.trim();
        if (content && !disabled) {
          onSend(content);
          setInput("");
        }
      }
    },
    [input, onSend, disabled],
  );

  return (
    <textarea
      ref={textareaRef}
      value={input}
      onChange={handleInputChange}
      onKeyDown={handleKeyDown}
      placeholder={t("Type a message...")}
      rows={1}
      disabled={disabled}
      className="flex-1 resize-none rounded-xl border border-[var(--border)] bg-transparent px-4 py-2.5 text-[16px] text-[var(--foreground)] outline-none transition-colors focus:border-[var(--ring)] disabled:opacity-50 placeholder:text-[var(--muted-foreground)]/40 sm:text-[14px]"
      style={{ minHeight: 42 }}
    />
  );
});
