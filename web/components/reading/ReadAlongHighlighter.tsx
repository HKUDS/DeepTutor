"use client";

import { useEffect } from "react";

import { useReadingActions } from "@/components/reading/reading-actions-context";
import {
  collectSpeakableText,
  rangeForWordIndex,
} from "@/lib/reading-speakable-text";

const HIGHLIGHT_NAME = "reading-readalong";

/**
 * Read-along highlight: tints the word currently being spoken.
 *
 * Uses the **CSS Custom Highlight API** rather than wrapping words in spans.
 * That matters here: the reader anchors annotations to quotes and character
 * offsets inside the article, so adding thousands of `span` nodes mid-passage
 * would invalidate stored anchors and fight React over the DOM it owns.
 * `CSS.highlights` paints a `Range` without mutating the document at all, and
 * the whole effect disappears with a single `delete`.
 *
 * The timeline comes from `useReadAloudSpeech`: real server word boundaries when
 * the voice reports them, otherwise a duration-based estimate.
 */
export function ReadAlongHighlighter({
  containerRef,
}: {
  containerRef: React.RefObject<HTMLElement | null>;
}) {
  const shared = useReadingActions();
  const activeWord = shared?.activeWord ?? -1;
  const words = shared?.readAlongWords;

  useEffect(() => {
    const registry = getHighlightRegistry();
    const root = containerRef.current;
    if (!registry || !root || activeWord < 0 || !words?.length) {
      registry?.delete(HIGHLIGHT_NAME);
      return;
    }

    const HighlightCtor = getHighlightCtor();
    // Same enumeration the click handler used to pick the start word, so
    // index N means the same word in both directions.
    const range = rangeForWordIndex(collectSpeakableText(root), activeWord);
    if (!HighlightCtor || !range) {
      registry.delete(HIGHLIGHT_NAME);
      return;
    }

    registry.set(HIGHLIGHT_NAME, new HighlightCtor(range));

    return () => {
      registry.delete(HIGHLIGHT_NAME);
    };
  }, [activeWord, containerRef, words]);

  // Never leave a stale highlight behind when the reader closes or speech stops.
  useEffect(() => {
    const registry = getHighlightRegistry();
    return () => {
      registry?.delete(HIGHLIGHT_NAME);
    };
  }, []);

  return null;
}

type HighlightCtor = new (...ranges: Range[]) => unknown;

interface HighlightRegistry {
  set: (name: string, highlight: unknown) => void;
  delete: (name: string) => void;
}

function getHighlightCtor(): HighlightCtor | null {
  if (typeof window === "undefined") return null;
  const ctor = (window as unknown as { Highlight?: HighlightCtor }).Highlight;
  return typeof ctor === "function" ? ctor : null;
}

function getHighlightRegistry(): HighlightRegistry | null {
  if (typeof CSS === "undefined") return null;
  const registry = (CSS as unknown as { highlights?: Map<string, unknown> }).highlights;
  if (!registry || typeof registry.set !== "function") return null;
  return registry as unknown as HighlightRegistry;
}
