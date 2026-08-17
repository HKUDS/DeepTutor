"use client";

import { useEffect, useRef, useState } from "react";
import { Check, Loader2, X } from "lucide-react";
import { useTranslation } from "react-i18next";

export interface BlockBodyEditorProps {
  initialValue: string;
  onSave: (value: string) => Promise<void> | void;
  onCancel: () => void;
}

/**
 * Inline prose editor for a single block.
 *
 * Intentionally plain. Fixing a wrong sentence should feel like correcting a
 * document, not like operating a CMS — and anything more ambitious than a
 * touch-up belongs in Co-Writer, not in the reader.
 */
export default function BlockBodyEditor({
  initialValue,
  onSave,
  onCancel,
}: BlockBodyEditorProps) {
  const { t } = useTranslation();
  const [draft, setDraft] = useState(initialValue);
  const [saving, setSaving] = useState(false);
  const textareaRef = useRef<HTMLTextAreaElement | null>(null);

  useEffect(() => {
    const node = textareaRef.current;
    if (!node) return;
    node.focus();
    node.setSelectionRange(node.value.length, node.value.length);
    // Grow to fit so a long section doesn't open as a four-line slot.
    node.style.height = "auto";
    node.style.height = `${Math.min(node.scrollHeight, 640)}px`;
  }, []);

  const commit = async () => {
    if (saving) return;
    setSaving(true);
    try {
      await onSave(draft);
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="space-y-2 rounded-xl border border-[var(--primary)]/40 bg-[var(--card)] p-2">
      <textarea
        ref={textareaRef}
        value={draft}
        onChange={(event) => setDraft(event.target.value)}
        onKeyDown={(event) => {
          if (event.key === "Escape") {
            event.preventDefault();
            onCancel();
          } else if (event.key === "Enter" && (event.metaKey || event.ctrlKey)) {
            event.preventDefault();
            void commit();
          }
        }}
        className="w-full resize-y rounded-md border border-[var(--border)] bg-[var(--background)] px-3 py-2 font-mono text-[13px] leading-relaxed text-[var(--foreground)] outline-none focus:border-[var(--primary)]/50"
      />
      <div className="flex items-center justify-between gap-2">
        <span className="text-[11px] text-[var(--muted-foreground)]">
          {t("Markdown supported. ⌘/Ctrl + Enter to save, Esc to cancel.")}
        </span>
        <div className="flex items-center gap-1.5">
          <button
            type="button"
            onClick={onCancel}
            disabled={saving}
            className="inline-flex items-center gap-1 rounded-md border border-[var(--border)] bg-[var(--card)] px-2 py-1 text-[11px] font-medium text-[var(--muted-foreground)] hover:text-[var(--foreground)] disabled:opacity-50"
          >
            <X className="h-3 w-3" />
            {t("Cancel")}
          </button>
          <button
            type="button"
            onClick={() => void commit()}
            disabled={saving}
            className="inline-flex items-center gap-1 rounded-md bg-[var(--primary)] px-2.5 py-1 text-[11px] font-medium text-[var(--primary-foreground)] hover:opacity-90 disabled:opacity-50"
          >
            {saving ? (
              <Loader2 className="h-3 w-3 animate-spin" />
            ) : (
              <Check className="h-3 w-3" />
            )}
            {t("Save")}
          </button>
        </div>
      </div>
    </div>
  );
}
