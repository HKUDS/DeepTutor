"use client";

import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { AudioLines, BookOpen, Loader2, Volume2, X } from "lucide-react";
import { useTranslation } from "react-i18next";
import {
  positionDictionaryPopover,
  type DictionaryAnchorRect,
} from "@/lib/dictionary-ui";
import type { DictionaryResult } from "@/lib/immersive-reading-api";
import {
  subscribePronunciationState,
  type PronunciationPlaybackState,
  type WordPronunciationAccent,
} from "@/lib/word-pronunciation";

export interface MiniDictionaryTooltipProps {
  word: string;
  anchor: DictionaryAnchorRect;
  loading: boolean;
  result: DictionaryResult | null;
  error?: string | null;
  onOpenFull: () => void;
  onPronounce: (accent: WordPronunciationAccent) => void;
  onClose: () => void;
}

export default function MiniDictionaryTooltip({
  word,
  anchor,
  loading,
  result,
  error,
  onOpenFull,
  onPronounce,
  onClose,
}: MiniDictionaryTooltipProps) {
  const { t } = useTranslation();
  const cardRef = useRef<HTMLDivElement>(null);
  const [position, setPosition] = useState<ReturnType<
    typeof positionDictionaryPopover
  > | null>(null);
  const [audioState, setAudioState] = useState<PronunciationPlaybackState>({
    isPlaying: false,
    word: null,
    accent: null,
  });

  useEffect(() => {
    return subscribePronunciationState(setAudioState);
  }, []);

  const isCurrentWordPlaying =
    audioState.isPlaying &&
    audioState.word?.toLowerCase() === word.trim().toLowerCase();
  const isPlayingUS = isCurrentWordPlaying && audioState.accent === "en-US";
  const isPlayingUK = isCurrentWordPlaying && audioState.accent === "en-GB";

  useLayoutEffect(() => {
    const update = () => {
      const rect = cardRef.current?.getBoundingClientRect();
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
  }, [anchor, loading, result, error]);

  useLayoutEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const primary =
    result?.definitions.find((definition) => definition.context_match) ??
    result?.definitions[0];
  const gloss = primary?.chinese || primary?.definition || result?.chinese;

  return createPortal(
    <div
      ref={cardRef}
      className="fixed z-[210] w-[min(320px,calc(100vw-16px))]"
      style={{
        left: position?.left ?? 8,
        top: position?.top ?? 8,
        visibility: position ? "visible" : "hidden",
        animation: "dt-pop-in 130ms cubic-bezier(0.22,1,0.3,1)",
      }}
      role="dialog"
      aria-label={t("Quick definition")}
    >
      <div className="overflow-hidden rounded-lg border border-[var(--border)] bg-[var(--background)] shadow-xl">
        <div className="flex items-center gap-2 border-b border-[var(--border)] px-3 py-2">
          <span className="min-w-0 flex-1 truncate text-sm font-medium">{word}</span>
          {result?.phonetic && (
            <span className="shrink-0 font-mono text-[11px] text-[var(--muted-foreground)]">
              /{result.phonetic}/
            </span>
          )}
          <button
            type="button"
            onClick={() => onPronounce("en-US")}
            title={t("Play US pronunciation (P)")}
            aria-label={t("Play US pronunciation (P)")}
            className={`rounded p-1 transition ${
              isPlayingUS
                ? "bg-[var(--primary)]/15 text-[var(--primary)] animate-pulse"
                : "text-[var(--muted-foreground)] hover:bg-[var(--muted)]"
            }`}
          >
            {isPlayingUS ? <AudioLines size={14} /> : <Volume2 size={14} />}
          </button>
          <button
            type="button"
            onClick={() => onPronounce("en-GB")}
            title={t("Play UK pronunciation (Shift+P)")}
            aria-label={t("Play UK pronunciation (Shift+P)")}
            className={`rounded px-1 py-0.5 text-[10px] font-semibold transition ${
              isPlayingUK
                ? "bg-[var(--primary)]/15 text-[var(--primary)] animate-pulse"
                : "text-[var(--muted-foreground)] hover:bg-[var(--muted)]"
            }`}
          >
            {isPlayingUK ? <AudioLines size={12} className="inline mr-0.5" /> : null}
            {t("UK")}
          </button>
          <button
            type="button"
            onClick={onClose}
            title={t("Close")}
            aria-label={t("Close")}
            className="rounded p-1 text-[var(--muted-foreground)] hover:bg-[var(--muted)]"
          >
            <X size={14} />
          </button>
        </div>
        <button
          type="button"
          onClick={onOpenFull}
          className="block w-full px-3 py-2.5 text-left hover:bg-[var(--muted)]/50"
        >
          {loading ? (
            <span className="flex items-center gap-2 text-xs text-[var(--muted-foreground)]">
              <Loader2 className="size-3.5 animate-spin" />
              {t("Thinking...")}
            </span>
          ) : error ? (
            <span className="line-clamp-2 text-xs text-red-500">{error}</span>
          ) : gloss ? (
            <span className="line-clamp-3 text-sm leading-relaxed">{gloss}</span>
          ) : (
            <span className="text-xs text-[var(--muted-foreground)]">
              {t("No result")}
            </span>
          )}
          <span className="mt-1.5 flex items-center gap-1 text-[11px] font-medium text-[var(--primary)]">
            <BookOpen size={11} />
            {t("Open dictionary")}
          </span>
        </button>
      </div>
    </div>,
    document.body,
  );
}
