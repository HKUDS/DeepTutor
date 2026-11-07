"use client";

/**
 * NotebookCellEditor — edit one cell's content in full.
 *
 * The list view edits a cell inside the card; the graph view edits it in a
 * dialog a double-click opens. Both need the same fields, so the editor lives
 * here: a Markdown cell toggles between source and preview, a code cell picks
 * its language, a board cell edits its script with the board beside it.
 */

import { useState, type ReactNode } from "react";
import dynamic from "next/dynamic";
import { useTranslation } from "react-i18next";

import RichMarkdownRenderer from "@/components/common/RichMarkdownRenderer";
import RichCodeBlock from "@/components/common/RichCodeBlock";
import NotebookTagControl from "@/components/chat/home/NotebookTagControl";
import {
  CODE_LANGUAGE_OPTIONS,
  normalizeCellLanguage,
  type NotebookCell,
} from "@/lib/notebook-cells";
import type { NotebookTag } from "@/lib/notebook-graph";

const Geogebra = dynamic(() => import("@/components/Geogebra"), { ssr: false });

const TEXTAREA =
  "block w-full resize-y rounded-lg border border-[var(--border)] bg-transparent px-2.5 py-2 font-mono text-[12.5px] leading-relaxed text-[var(--foreground)] outline-none placeholder:text-[color-mix(in_srgb,var(--muted-foreground)_60%,transparent)]";

export default function NotebookCellEditor({
  cell,
  onChange,
  tag,
  onTagChange,
}: {
  cell: NotebookCell;
  onChange: (patch: Partial<NotebookCell>) => void;
  tag?: NotebookTag;
  onTagChange?: (tag: NotebookTag | null) => void;
}) {
  const { t } = useTranslation();
  const [preview, setPreview] = useState(false);

  let body: ReactNode;
  if (cell.kind === "code") {
    body = (
      <>
        <div className="flex items-center justify-between gap-2">
          <select
            value={normalizeCellLanguage(cell.language)}
            onChange={(event) =>
              onChange({ language: normalizeCellLanguage(event.target.value) })
            }
            aria-label={t("Language")}
            className="h-7 rounded-md border border-[var(--border)] bg-transparent px-1.5 text-[12px] text-[var(--foreground)] outline-none"
          >
            {CODE_LANGUAGE_OPTIONS.map((option) => (
              <option key={option.value} value={option.value}>
                {t(option.label)}
              </option>
            ))}
          </select>
          <button
            type="button"
            onClick={() => setPreview((value) => !value)}
            className="rounded-md border border-[color-mix(in_srgb,var(--border)_60%,transparent)] px-2 py-1 text-[11px] font-medium text-[var(--muted-foreground)] transition-colors hover:text-[var(--foreground)]"
          >
            {t(preview ? "Edit" : "Preview")}
          </button>
        </div>
        {preview ? (
          <RichCodeBlock
            raw={cell.source}
            lang={normalizeCellLanguage(cell.language)}
          />
        ) : (
          <textarea
            value={cell.source}
            rows={16}
            spellCheck={false}
            onChange={(event) => onChange({ source: event.target.value })}
            placeholder={t("print('hello')")}
            className={TEXTAREA}
          />
        )}
      </>
    );
  } else if (cell.kind === "geogebra") {
    body = (
      <>
        <Geogebra script={cell.source} editable width={520} height={320} />
        <textarea
          value={cell.source}
          rows={6}
          spellCheck={false}
          onChange={(event) => onChange({ source: event.target.value })}
          placeholder={t("GeoGebra commands, one per line.")}
          className={TEXTAREA}
        />
      </>
    );
  } else {
    body = (
      <>
        <div className="flex justify-end">
          <button
            type="button"
            onClick={() => setPreview((value) => !value)}
            className="rounded-md border border-[color-mix(in_srgb,var(--border)_60%,transparent)] px-2 py-1 text-[11px] font-medium text-[var(--muted-foreground)] transition-colors hover:text-[var(--foreground)]"
          >
            {t(preview ? "Edit" : "Preview")}
          </button>
        </div>
        {preview ? (
          <div className="rounded-lg border border-[color-mix(in_srgb,var(--border)_45%,transparent)] px-3 py-2.5 text-[13px]">
            <RichMarkdownRenderer content={cell.source} enableMath enableCode enableMermaid />
          </div>
        ) : (
          <textarea
            value={cell.source}
            rows={16}
            spellCheck={false}
            onChange={(event) => onChange({ source: event.target.value })}
            placeholder={t("Write a note, with $math$ in Markdown.")}
            className={TEXTAREA}
          />
        )}
      </>
    );
  }

  return (
    <div className="space-y-2">
      {onTagChange ? (
        <div className="flex items-center justify-between gap-2">
          <span className="text-[11px] text-[var(--muted-foreground)]">
            {t("Tag")}
          </span>
          <NotebookTagControl tag={tag} onChange={onTagChange} />
        </div>
      ) : null}
      {body}
    </div>
  );
}
