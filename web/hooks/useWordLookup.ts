"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import type React from "react";
import { useTranslation } from "react-i18next";
import {
  ApiRequestError,
  type DictionaryResult,
  immersiveReadingApi,
} from "@/lib/immersive-reading-api";
import {
  extractDictionaryWord,
  type DictionaryAnchorRect,
} from "@/lib/dictionary-ui";
import {
  getCachedWord,
  setCachedWord,
  getCachedTranslation,
  setCachedTranslation,
} from "@/lib/dictionary-cache";

export interface WordLookupPopover {
  word: string;
  context: string;
  anchor: DictionaryAnchorRect;
}

interface UseWordLookupOptions {
  /** Disable selection detection (e.g. while content is still loading). */
  enabled?: boolean;
  /** Change this value to dismiss any open popover (e.g. a chapter / file key). */
  resetKey?: unknown;
}

/**
 * Word-lookup controller shared by the bilingual reader and the knowledge
 * doc preview. Attach `containerRef` to the readable text container;
 * selecting a single English word pops a dictionary popover and auto-queries
 * the backend for a simple-English definition.
 */
export function useWordLookup(
  containerRef: React.RefObject<HTMLElement | null>,
  { enabled = true, resetKey }: UseWordLookupOptions = {},
) {
  const { t } = useTranslation();
  const [popover, setPopover] = useState<WordLookupPopover | null>(null);
  const [result, setResult] = useState<DictionaryResult | null>(null);
  const [loading, setLoading] = useState(false);
  const reqIdRef = useRef(0);
  const abortRef = useRef<AbortController | null>(null);

  const lookup = useCallback(
    async (word: string, context: string) => {
      abortRef.current?.abort();
      const controller = new AbortController();
      abortRef.current = controller;
      const reqId = ++reqIdRef.current;

      // Client-side cache: instant display for previously looked-up words.
      const cached = getCachedWord(word);
      if (cached) {
        setResult(cached);
        setLoading(false);
        return;
      }

      setLoading(true);
      setResult(null);
      try {
        const res = await immersiveReadingApi.dictionary(
          word,
          context,
          controller.signal,
        );
        if (reqId !== reqIdRef.current) return;
        setCachedWord(word, res);
        setResult(res);
      } catch (err) {
        if (controller.signal.aborted || reqId !== reqIdRef.current) return;
        const msg = err instanceof Error ? err.message : String(err);
        const status = err instanceof ApiRequestError ? err.status : undefined;
        if (status === 503) {
          setResult({
            word,
            phonetic: "",
            definitions: [],
            context_note:
              msg ||
              t(
                "Local dictionary unavailable. Run `ollama serve` then `ollama pull qwen3.5:2b`.",
              ),
          });
        } else if (status === 504) {
          setResult({
            word,
            phonetic: "",
            definitions: [],
            context_note: t(
              "Dictionary lookup timed out. The local model may still be loading.",
            ),
          });
        } else {
          setResult({
            word,
            phonetic: "",
            definitions: [],
            context_note: t("Lookup failed.") + " " + msg,
          });
        }
      } finally {
        if (reqId === reqIdRef.current) setLoading(false);
      }
    },
    [t],
  );

  // Re-query the word currently shown in the popover.
  const onLookup = useCallback(() => {
    if (!popover) return;
    void lookup(popover.word, popover.context);
  }, [lookup, popover]);

  // Translate the word currently shown in the popover.
  const onTranslate = useCallback(async () => {
    if (!popover) return;
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    const reqId = ++reqIdRef.current;
    const targetLang = "Chinese";

    // Client-side cache: instant display for previously translated text.
    const cached = getCachedTranslation(popover.word, targetLang);
    if (cached) {
      setResult({
        word: popover.word,
        phonetic: "",
        definitions: [],
        context_note: cached,
      });
      return;
    }

    setLoading(true);
    try {
      const res = await immersiveReadingApi.translate(popover.word, targetLang);
      if (controller.signal.aborted || reqId !== reqIdRef.current) return;
      setCachedTranslation(popover.word, targetLang, res.translation);
      setResult({
        word: popover.word,
        phonetic: "",
        definitions: [],
        context_note: res.translation,
      });
    } catch (err) {
      if (controller.signal.aborted || reqId !== reqIdRef.current) return;
      const status = err instanceof ApiRequestError ? err.status : undefined;
      const msg = err instanceof Error ? err.message : String(err);
      let errorNote: string;
      if (status === 504) {
        errorNote = t("Translation timed out. The model may still be loading.");
      } else if (status === 503) {
        errorNote = msg || t("Translation service unavailable. Please try again.");
      } else if (status === 429) {
        errorNote = t("Rate limit exceeded. Please wait a moment.");
      } else if (status && status >= 500) {
        errorNote = t("Translation service unavailable. Please try again.");
      } else {
        errorNote = t("Translation failed.") + (msg ? ` ${msg}` : "");
      }
      setResult({
        word: popover.word,
        phonetic: "",
        definitions: [],
        context_note: errorNote,
      });
    } finally {
      if (reqId === reqIdRef.current) setLoading(false);
    }
  }, [popover, t]);

  const close = useCallback(() => {
    abortRef.current?.abort();
    reqIdRef.current++;
    setPopover(null);
    setResult(null);
    setLoading(false);
  }, []);

  // Dismiss the popover whenever the reset key changes (new chapter / file).
  useEffect(() => {
    abortRef.current?.abort();
    reqIdRef.current++;
    setPopover(null);
    setResult(null);
    setLoading(false);
  }, [resetKey]);

  // Abort any in-flight lookup on unmount.
  useEffect(() => () => abortRef.current?.abort(), []);

  const handleSelection = useCallback(() => {
    if (!enabled) return;
    const selection = window.getSelection();
    const text = selection?.toString().trim() || "";
    if (!selection || !text || selection.rangeCount === 0 || !containerRef.current) {
      return;
    }
    const anchorNode = selection.anchorNode;
    if (!anchorNode || !containerRef.current.contains(anchorNode)) return;
    // Sentence around the selection gives the lookup its context.
    const sentence =
      selection.anchorNode.parentElement?.closest("p")?.textContent || "";
    const rect = selection.getRangeAt(0).getBoundingClientRect();
    const word = extractDictionaryWord(text);
    if (!word) return;
    const context = sentence.slice(0, 2000);
    setPopover({
      word,
      context,
      anchor: { left: rect.left, right: rect.right, top: rect.top, bottom: rect.bottom },
    });
    void lookup(word, context);
  }, [containerRef, enabled, lookup]);

  useEffect(() => {
    if (!enabled) return;
    const ref = containerRef.current;
    if (!ref) return;
    let timer: number | null = null;
    const onMouseUp = () => {
      if (timer !== null) window.clearTimeout(timer);
      // Defer a tick so the selection has finalized.
      timer = window.setTimeout(handleSelection, 10);
    };
    ref.addEventListener("mouseup", onMouseUp);
    return () => {
      ref.removeEventListener("mouseup", onMouseUp);
      if (timer !== null) window.clearTimeout(timer);
    };
  }, [containerRef, handleSelection, enabled]);

  return { popover, result, loading, onLookup, onTranslate, close };
}
