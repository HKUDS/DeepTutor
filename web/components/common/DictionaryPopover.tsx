"use client";

import { useLayoutEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { BookOpen, Languages, Loader2, X } from "lucide-react";
import { useTranslation } from "react-i18next";
import { positionDictionaryPopover, type DictionaryAnchorRect } from "@/lib/dictionary-ui";
import type { DictionaryResult } from "@/lib/immersive-reading-api";

interface DictionaryPopoverProps {
  word: string;
  anchor: DictionaryAnchorRect;
  loading: boolean;
  result: DictionaryResult | null;
  onLookup: () => void;
  onTranslate: () => void;
  onClose: () => void;
}

/**
 * Fixed-position dictionary popover shown above/below a text selection.
 * Portal-rendered to document.body so it floats above any clipping
 * container. Shared by the bilingual reader and the knowledge doc preview.
 */
export default function DictionaryPopover({
  word,
  anchor,
  loading,
  result,
  onLookup,
  onTranslate,
  onClose,
}: DictionaryPopoverProps) {
  const { t } = useTranslation();
  const hasResult = result && (result.definitions.length > 0 || result.context_note);
  const popupRef = useRef<HTMLDivElement>(null);
  const [position, setPosition] = useState<ReturnType<typeof positionDictionaryPopover> | null>(null);

  useLayoutEffect(() => {
    const update = () => {
      const rect = popupRef.current?.getBoundingClientRect();
      if (!rect) return;
      setPosition(
        positionDictionaryPopover(
          anchor,
          { width: rect.width, height: rect.height },
          { width: window.innerWidth, height: window.innerHeight },
        ),
      );
    };
    update();
    window.addEventListener("resize", update);
    window.addEventListener("scroll", update, true);
    return () => {
      window.removeEventListener("resize", update);
      window.removeEventListener("scroll", update, true);
    };
  }, [anchor, loading, result]);

  return createPortal(
    <div
      ref={popupRef}
      className="fixed z-[200] w-[min(360px,calc(100vw-16px))]"
      style={{
        left: position?.left ?? 8,
        top: position?.top ?? 8,
        visibility: position ? "visible" : "hidden",
      }}
    >
      <div className="max-h-[min(70vh,520px)] overflow-y-auto overscroll-contain rounded-xl border border-[var(--border)] bg-[var(--background)] shadow-2xl">
        {/* Header bar */}
        <div className="flex items-center justify-between border-b border-[var(--border)] px-4 py-2">
          <div className="flex items-center gap-2">
            <BookOpen size={14} className="text-[var(--primary)]" />
            <span className="truncate text-sm font-medium">{word}</span>
          </div>
          <button onClick={onClose} className="rounded p-0.5 text-[var(--muted-foreground)] hover:bg-[var(--muted)]">
            <X size={15} />
          </button>
        </div>

        {/* Action buttons (shown when no result yet) */}
        {!hasResult && !loading && (
          <div className="flex gap-1.5 p-3">
            <button
              onClick={onLookup}
              className="flex flex-1 items-center justify-center gap-1.5 rounded-lg bg-[var(--primary)] px-3 py-2 text-xs font-medium text-[var(--primary-foreground)] hover:opacity-90"
            >
              <BookOpen size={14} />
              {t("Dictionary")}
            </button>
            <button
              onClick={onTranslate}
              className="flex flex-1 items-center justify-center gap-1.5 rounded-lg border border-[var(--border)] px-3 py-2 text-xs font-medium text-[var(--foreground)] hover:bg-[var(--muted)]"
            >
              <Languages size={14} />
              {t("Translate")}
            </button>
          </div>
        )}

        {/* Loading */}
        {loading && (
          <div className="flex items-center justify-center py-6">
            <Loader2 className="size-5 animate-spin text-[var(--muted-foreground)]" />
          </div>
        )}

        {/* Dictionary result */}
        {hasResult && !loading && (
          <div className="p-4">
            {result!.definitions.length > 0 ? (
              <>
                {result!.phonetic && (
                  <p className="mb-2 font-mono text-xs text-[var(--muted-foreground)]">/{result!.phonetic}/</p>
                )}
                {result!.context_note && (
                  <div className="mb-3 rounded-lg bg-[var(--primary)]/10 px-3 py-2 text-xs text-[var(--primary)]">
                    {result!.context_note}
                  </div>
                )}
                <div className="space-y-3">
                  {result!.definitions.map((def, i) => (
                    <div key={i} className={def.context_match ? "rounded-lg border border-[var(--primary)]/30 bg-[var(--primary)]/5 p-2.5" : ""}>
                      <div className="mb-0.5 flex items-center gap-2">
                        <span className="text-xs italic text-[var(--muted-foreground)]">{def.part_of_speech}</span>
                        {def.context_match && (
                          <span className="rounded bg-[var(--primary)] px-1.5 py-0.5 text-[10px] font-medium text-[var(--primary-foreground)]">
                            {t("In context")}
                          </span>
                        )}
                      </div>
                      <p className="text-sm leading-relaxed text-[var(--foreground)]">{def.definition}</p>
                      {def.chinese && (
                        <p className="mt-0.5 text-sm text-[var(--muted-foreground)]">{def.chinese}</p>
                      )}
                      {def.example && (
                        <p className="mt-1 text-xs italic text-[var(--muted-foreground)]">&ldquo;{def.example}&rdquo;</p>
                      )}
                      {def.synonyms.length > 0 && (
                        <p className="mt-1 text-xs text-[var(--muted-foreground)]">
                          {t("Synonyms")}: {def.synonyms.join(", ")}
                        </p>
                      )}
                    </div>
                  ))}
                </div>
              </>
            ) : (
              <p className="text-sm leading-relaxed text-[var(--foreground)]">{result!.context_note}</p>
            )}
          </div>
        )}
      </div>
    </div>,
    document.body,
  );
}
