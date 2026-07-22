"use client";

/**
 * Soul markdown editor with an edit/preview toggle, shared by the creation
 * wizard (SoulPicker) and the Configure tab. Styled as a quiet "file card":
 * a SOUL.md chrome strip with an iOS-style sliding segmented control, and a
 * fixed-height body so toggling never shifts the layout.
 */

import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Eye, PencilLine } from "lucide-react";
import MarkdownRenderer from "@/components/common/MarkdownRenderer";

type Mode = "edit" | "preview";

export default function SoulEditor({
  value,
  onChange,
  placeholder,
  heightClass = "h-[320px]",
}: {
  value: string;
  onChange: (next: string) => void;
  placeholder?: string;
  heightClass?: string;
}) {
  const { t } = useTranslation();
  const [mode, setMode] = useState<Mode>("edit");

  const segments: { key: Mode; label: string; icon: typeof PencilLine }[] = [
    { key: "edit", label: t("Edit"), icon: PencilLine },
    { key: "preview", label: t("Preview"), icon: Eye },
  ];

  return (
    <div className="overflow-hidden rounded-xl border border-[var(--border)] bg-[var(--background)] transition-colors focus-within:border-[var(--ring)]">
      <div className="flex items-center justify-between border-b border-[var(--border)] bg-[var(--muted)]/40 py-1.5 pl-4 pr-1.5">
        <span className="font-mono text-[11px] tracking-wide text-[var(--muted-foreground)]">
          SOUL.md
        </span>
        <div className="relative grid grid-cols-2 rounded-lg bg-[var(--muted)] p-0.5">
          <span
            aria-hidden
            className={`pointer-events-none absolute bottom-0.5 left-0.5 top-0.5 w-[calc(50%-2px)] rounded-[6px] bg-[var(--background)] shadow-sm transition-transform duration-200 ease-out ${
              mode === "preview" ? "translate-x-full" : ""
            }`}
          />
          {segments.map(({ key, label, icon: Icon }) => (
            <button
              key={key}
              type="button"
              onClick={() => setMode(key)}
              onMouseDown={(e) => e.preventDefault()}
              aria-pressed={mode === key}
              className={`relative z-[1] inline-flex items-center justify-center gap-1.5 rounded-[6px] px-3 py-1 text-[12px] transition-colors duration-200 ${
                mode === key
                  ? "font-medium text-[var(--foreground)]"
                  : "text-[var(--muted-foreground)] hover:text-[var(--foreground)]"
              }`}
            >
              <Icon className="h-3.5 w-3.5" />
              {label}
            </button>
          ))}
        </div>
      </div>

      {mode === "edit" ? (
        <textarea
          value={value}
          onChange={(e) => onChange(e.target.value)}
          placeholder={
            placeholder ??
            t(
              "# Soul\nDescribe who this partner is, how it speaks, what it values…",
            )
          }
          spellCheck={false}
          className={`block w-full resize-none bg-transparent px-4 py-3.5 font-mono text-[13px] leading-[1.7] text-[var(--foreground)] outline-none placeholder:text-[var(--muted-foreground)]/60 ${heightClass}`}
        />
      ) : (
        <div
          className={`overflow-y-auto px-5 py-4 animate-fade-in ${heightClass}`}
        >
          {value.trim() ? (
            <MarkdownRenderer
              content={value}
              variant="compact"
              className="!font-sans"
            />
          ) : (
            <p className="text-[13px] italic text-[var(--muted-foreground)]">
              {t("Nothing to preview yet.")}
            </p>
          )}
        </div>
      )}
    </div>
  );
}
