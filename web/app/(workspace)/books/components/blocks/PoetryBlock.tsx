"use client";

import { Loader2, Square, Volume2 } from "lucide-react";
import { useSearchParams } from "next/navigation";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { Block } from "@/lib/book-types";
import { bookApi, type RecitationSummary } from "@/lib/book-api";
import { apiFetch, apiUrl } from "@/lib/api";

import PoetryRecitationPanel from "./PoetryRecitationPanel";

/**
 * YuEdu fork: 诗词 block 渲染组件。
 * 渲染诗词原文（竖排/横排）+ 拼音 + 注解 + 朗读按钮。
 * Payload 形如:
 * {
 *   title: "静夜思",
 *   author: "李白",
 *   dynasty: "唐",
 *   lines: [{ text: "床前明月光", pinyin: "chuáng qián míng yuè guāng" }, ...],
 *   annotations: [{ term: "疑", explanation: "好像" }, ...]
 * }
 */
export default function PoetryBlock({ block }: { block: Block }) {
  const searchParams = useSearchParams();
  const bookId = bookApi.activeBookId() || searchParams?.get("book") || null;
  const params = (block.payload as Record<string, unknown> | undefined) ?? {};
  const title = String(params.title ?? "");
  const author = String(params.author ?? "");
  const dynasty = String(params.dynasty ?? "");
  const lines = Array.isArray(params.lines)
    ? params.lines.filter(
        (line): line is Record<string, unknown> =>
          typeof line === "object" && line !== null && !Array.isArray(line),
      )
    : [];
  const annotations = Array.isArray(params.annotations)
    ? params.annotations.filter(
        (annotation): annotation is Record<string, unknown> =>
          typeof annotation === "object" &&
          annotation !== null &&
          !Array.isArray(annotation),
      )
    : [];
  const speakText = lines.map((line) => String(line.text ?? "")).join("。");
  const recitationLines = lines
    .map((line, index) => ({
      id: `line-${index + 1}`,
      text: String(line.text ?? "").trim(),
    }))
    .filter((line) => line.text.length > 0);
  const initialRecitationSummary = useMemo(
    () => parseRecitationSummary(block.metadata?.recitation),
    [block.metadata?.recitation],
  );
  const [playState, setPlayState] = useState<"idle" | "loading" | "playing">(
    "idle",
  );
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const urlRef = useRef<string | null>(null);
  const utteranceRef = useRef<SpeechSynthesisUtterance | null>(null);

  const cleanup = useCallback(() => {
    if (audioRef.current) {
      audioRef.current.pause();
      audioRef.current = null;
    }
    if (utteranceRef.current && "speechSynthesis" in window) {
      utteranceRef.current = null;
      window.speechSynthesis.cancel();
    }
    if (urlRef.current) {
      URL.revokeObjectURL(urlRef.current);
      urlRef.current = null;
    }
  }, []);

  const fallbackToSpeechSynthesis = useCallback(() => {
    cleanup();
    if (speakText && "speechSynthesis" in window) {
      const utterance = new SpeechSynthesisUtterance(speakText);
      utterance.lang = "zh-CN";
      utterance.rate = 0.8;
      utteranceRef.current = utterance;
      const reset = () => {
        if (utteranceRef.current === utterance) {
          utteranceRef.current = null;
          setPlayState("idle");
        }
      };
      utterance.onend = reset;
      utterance.onerror = reset;
      window.speechSynthesis.speak(utterance);
      setPlayState("playing");
      return;
    }
    setPlayState("idle");
  }, [cleanup, speakText]);

  const play = useCallback(async () => {
    let didFallback = false;
    const fallback = () => {
      if (didFallback) return;
      didFallback = true;
      fallbackToSpeechSynthesis();
    };

    setPlayState("loading");
    try {
      const response = await apiFetch(apiUrl("/api/voice/tts"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text: speakText }),
      });
      if (!response.ok) {
        fallback();
        return;
      }

      const blob = await response.blob();
      cleanup();
      const url = URL.createObjectURL(blob);
      urlRef.current = url;
      const audio = new Audio(url);
      audioRef.current = audio;
      audio.onended = () => {
        setPlayState("idle");
        cleanup();
      };
      audio.onerror = fallback;
      await audio.play();
      setPlayState("playing");
    } catch {
      fallback();
    }
  }, [cleanup, fallbackToSpeechSynthesis, speakText]);

  const handleSpeak = useCallback(() => {
    if (playState === "playing" || playState === "loading") {
      cleanup();
      setPlayState("idle");
      return;
    }
    void play();
  }, [cleanup, play, playState]);

  useEffect(() => cleanup, [cleanup]);

  return (
    <div className="my-4 rounded-2xl border border-[var(--border)] bg-gradient-to-b from-[var(--card)] to-[var(--background)] p-6 shadow-sm">
      {/* 标题区 */}
      <div className="mb-4 text-center">
        {title && (
          <h3 className="text-xl font-bold text-[var(--foreground)]">{title}</h3>
        )}
        {(author || dynasty) && (
          <p className="mt-1 text-sm text-[var(--muted-foreground)]">
            {[dynastyText(dynasty), author].filter(Boolean).join(" · ")}
          </p>
        )}
      </div>

      {/* 诗句 + 拼音 */}
      <div className="mx-auto max-w-md space-y-3">
        {lines.length > 0 ? (
          lines.map((line, i) => {
            const text = String(line.text ?? "");
            const pinyin = String(line.pinyin ?? "");
            return (
              <div key={i} className="text-center">
                {pinyin && (
                  <p className="text-xs text-[var(--muted-foreground)]/70 tracking-wide">
                    {pinyin}
                  </p>
                )}
                <p className="text-lg leading-relaxed text-[var(--foreground)] tracking-wider">
                  {text}
                </p>
              </div>
            );
          })
        ) : (
          <p className="py-6 text-center text-sm text-[var(--muted-foreground)]">
            暂无诗词内容
          </p>
        )}
      </div>

      {/* 示范朗读 */}
      {lines.length > 0 && (
        <div className="mt-4 text-center">
          <button
            type="button"
            onClick={handleSpeak}
            aria-label={playState === "playing" ? "停止示范朗读" : "示范朗读"}
            className="inline-flex items-center gap-1.5 rounded-full border border-[var(--border)] bg-[var(--card)] px-3 py-1 text-xs text-[var(--muted-foreground)] transition hover:bg-[var(--background)] hover:text-[var(--foreground)]"
          >
            {playState === "loading" ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            ) : playState === "playing" ? (
              <Square className="h-3 w-3 fill-current" />
            ) : (
              <Volume2 className="h-3.5 w-3.5" />
            )}
            {playState === "loading"
              ? "加载中"
              : playState === "playing"
                ? "停止"
                : "示范朗读"}
          </button>
        </div>
      )}

      {recitationLines.length > 0 && (
        <PoetryRecitationPanel
          key={initialRecitationSummary?.last_attempt_id || "recitation"}
          bookId={bookId}
          blockId={block.id}
          lines={recitationLines}
          initialSummary={initialRecitationSummary}
        />
      )}

      {/* 注解 */}
      {annotations.length > 0 && (
        <div className="mt-4 border-t border-[var(--border)]/50 pt-3">
          <p className="mb-2 text-xs font-medium text-[var(--muted-foreground)]">注释</p>
          <dl className="space-y-1">
            {annotations.map((ann, i) => (
              <div key={i} className="flex gap-2 text-sm">
                <dt className="font-medium text-[var(--foreground)]">
                  {String(ann.term ?? "")}
                </dt>
                <dd className="text-[var(--muted-foreground)]">
                  {String(ann.explanation ?? "")}
                </dd>
              </div>
            ))}
          </dl>
        </div>
      )}
    </div>
  );
}

function dynastyText(dynasty: string): string {
  if (!dynasty) return "";
  return `${dynasty}代`;
}

function parseRecitationSummary(value: unknown): RecitationSummary | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) return null;
  const summary = value as Record<string, unknown>;
  const dataState = summary.data_state;
  if (dataState !== "" && dataState !== "scored" && dataState !== "stt_failed") {
    return null;
  }
  return {
    last_attempt_id: String(summary.last_attempt_id ?? ""),
    attempt_count: Number(summary.attempt_count ?? 0),
    latest_accuracy:
      typeof summary.latest_accuracy === "number" ? summary.latest_accuracy : null,
    best_accuracy:
      typeof summary.best_accuracy === "number" ? summary.best_accuracy : null,
    data_state: dataState,
    updated_at: Number(summary.updated_at ?? 0),
  };
}
