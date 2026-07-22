"use client";

import { memo, useCallback, useState, type RefObject } from "react";
import { useTranslation } from "react-i18next";
import { shouldSubmitOnEnter } from "@/lib/composer-keyboard";
import { useAutoSizedTextarea } from "@/lib/use-auto-sized-textarea";
import { useImeComposing } from "@/lib/use-ime-composing";

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
  const { isComposingRef, onCompositionStart, onCompositionEnd } =
    useImeComposing();

  useAutoSizedTextarea(textareaRef, input, { min: 42, max: 200 });

  const handleInputChange = useCallback(
    (e: React.ChangeEvent<HTMLTextAreaElement>) => {
      setInput(e.target.value);
    },
    [],
  );

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
      if (shouldSubmitOnEnter(e, isComposingRef.current)) {
        e.preventDefault();
        const content = input.trim();
        if (content && !disabled) {
          onSend(content);
          setInput("");
        }
      }
    },
    [input, onSend, disabled, isComposingRef],
  );

  return (
    <textarea
      ref={textareaRef}
      value={input}
      onChange={handleInputChange}
      onKeyDown={handleKeyDown}
      onCompositionStart={onCompositionStart}
      onCompositionEnd={onCompositionEnd}
      placeholder={t("Type a message...")}
      rows={1}
      // Defensive cap — see ComposerInput for the same guard. Anything beyond
      // this size belongs in an attachment, not in the textarea body.
      maxLength={32000}
      disabled={disabled}
      className="flex-1 resize-none rounded-xl border border-[var(--border)] bg-transparent px-4 py-2.5 text-[14px] text-[var(--foreground)] outline-none transition-colors focus:border-[var(--ring)] disabled:opacity-50 placeholder:text-[var(--muted-foreground)]/40"
      style={{ minHeight: 42 }}
    />
  );
});
