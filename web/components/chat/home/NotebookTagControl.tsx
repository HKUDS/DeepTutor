"use client";

/**
 * NotebookTagControl — a cell's coloured tag.
 *
 * Shown in the card header and on the graph node. Clicking opens a small editor
 * (name + colour). The tag rides in the notebook's hidden graph block, keyed by
 * the cell id.
 */

import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Tag as TagIcon } from "lucide-react";

import { NOTEBOOK_TAG_COLORS, type NotebookTag } from "@/lib/notebook-graph";

export function NotebookTagChip({
  tag,
  className,
}: {
  tag: NotebookTag;
  className?: string;
}) {
  return (
    <span
      className={`inline-flex max-w-[140px] items-center truncate rounded-full px-2 py-0.5 text-[10.5px] font-medium text-white ${
        className ?? ""
      }`}
      style={{ backgroundColor: tag.color }}
    >
      {tag.label}
    </span>
  );
}

export default function NotebookTagControl({
  tag,
  onChange,
  className,
}: {
  tag?: NotebookTag;
  onChange: (tag: NotebookTag | null) => void;
  className?: string;
}) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const [label, setLabel] = useState(tag?.label ?? "");
  const [color, setColor] = useState(tag?.color ?? NOTEBOOK_TAG_COLORS[0]);

  const openEditor = () => {
    setLabel(tag?.label ?? "");
    setColor(tag?.color ?? NOTEBOOK_TAG_COLORS[0]);
    setOpen((value) => !value);
  };

  const commit = () => {
    const trimmed = label.trim();
    onChange(trimmed ? { label: trimmed, color } : null);
    setOpen(false);
  };

  return (
    <div className={`relative ${className ?? ""}`}>
      <button
        type="button"
        onClick={openEditor}
        aria-label={t("Tag")}
        className="inline-flex items-center gap-1 rounded-md px-1.5 py-0.5 transition-colors hover:bg-[color-mix(in_srgb,var(--muted)_70%,transparent)]"
      >
        {tag ? (
          <NotebookTagChip tag={tag} />
        ) : (
          <span className="inline-flex items-center gap-1 text-[10.5px] text-[var(--muted-foreground)]">
            <TagIcon size={12} strokeWidth={1.9} />
            {t("Tag")}
          </span>
        )}
      </button>

      {open ? (
        <div className="absolute right-0 top-full z-30 mt-1 w-56 rounded-lg border border-[var(--border)] bg-[var(--card)] p-2 shadow-xl">
          <input
            autoFocus
            value={label}
            onChange={(event) => setLabel(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter") commit();
              if (event.key === "Escape") setOpen(false);
            }}
            placeholder={t("Tag name")}
            className="block w-full rounded-md border border-[var(--border)] bg-transparent px-2 py-1 text-[12px] text-[var(--foreground)] outline-none"
          />
          <div className="mt-2 flex flex-wrap gap-1.5">
            {NOTEBOOK_TAG_COLORS.map((value) => (
              <button
                key={value}
                type="button"
                onClick={() => setColor(value)}
                aria-label={value}
                aria-pressed={color === value}
                className={`h-5 w-5 rounded-full border-2 ${
                  color === value ? "border-[var(--foreground)]" : "border-transparent"
                }`}
                style={{ backgroundColor: value }}
              />
            ))}
          </div>
          <div className="mt-2 flex items-center justify-between">
            <button
              type="button"
              onClick={() => {
                onChange(null);
                setOpen(false);
              }}
              className="text-[11.5px] text-[var(--muted-foreground)] underline hover:text-[var(--foreground)]"
            >
              {t("Remove tag")}
            </button>
            <button
              type="button"
              onClick={commit}
              className="rounded-md bg-[var(--primary)] px-2.5 py-1 text-[11.5px] font-medium text-[var(--primary-foreground)]"
            >
              {t("Save")}
            </button>
          </div>
        </div>
      ) : null}
    </div>
  );
}
