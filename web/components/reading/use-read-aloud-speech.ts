"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { readReadingAloudAudio, readReadingAloudTimed } from "@/lib/reading-api";

type Playback = { audio: HTMLAudioElement; url: string; disposed: boolean };

/** One entry of the read-along timeline, in the audio element's own clock. */
export interface SpokenWord {
  word: string;
  start: number;
  duration: number;
}

/**
 * Estimate a word timeline when the voice reports no boundaries.
 *
 * Spreads the words evenly across the decoded duration, weighted by length so
 * long words hold the highlight a little longer. Approximate, but it keeps the
 * read-along cursor moving for providers that cannot report timings.
 */
function estimateTimeline(text: string, duration: number): SpokenWord[] {
  const tokens = text.split(/\s+/).filter(Boolean);
  if (!tokens.length || !Number.isFinite(duration) || duration <= 0) return [];
  const weights = tokens.map((token) => Math.max(1, token.replace(/[^\w']/g, "").length));
  const total = weights.reduce((sum, weight) => sum + weight, 0);
  let cursor = 0;
  return tokens.map((word, index) => {
    const share = (weights[index] / total) * duration;
    const entry = { word, start: cursor, duration: share };
    cursor += share;
    return entry;
  });
}

/**
 * Play verified server speech, falling back to browser speech when unavailable.
 *
 * `speak` now also builds a **word timeline** so the reader can highlight the
 * word being spoken (NaturalReader-style read-along). Pass `timed: true` to
 * request per-word timings from the server; when the active voice cannot report
 * them the timeline is estimated from the audio duration, and `timed` in the
 * result says which happened. The existing call shape keeps working unchanged.
 */
export function useReadAloudSpeech() {
  const [speaking, setSpeaking] = useState(false);
  const [activeWord, setActiveWord] = useState(-1);
  const [timeline, setTimeline] = useState<SpokenWord[]>([]);
  const tokenRef = useRef(0);
  const playbackRef = useRef<Playback | null>(null);

  const disposeAudio = useCallback((playback = playbackRef.current) => {
    if (!playback) return;
    if (!playback.disposed) {
      playback.disposed = true;
      playback.audio.onended = null;
      playback.audio.onerror = null;
      playback.audio.ontimeupdate = null;
      playback.audio.onloadedmetadata = null;
      playback.audio.pause();
      URL.revokeObjectURL(playback.url);
    }
    if (playbackRef.current === playback) playbackRef.current = null;
  }, []);

  const stop = useCallback(() => {
    tokenRef.current += 1;
    disposeAudio();
    window.speechSynthesis?.cancel();
    setSpeaking(false);
    setActiveWord(-1);
    setTimeline([]);
  }, [disposeAudio]);

  useEffect(() => () => {
    tokenRef.current += 1;
    disposeAudio();
    window.speechSynthesis?.cancel();
  }, [disposeAudio]);

  /** Resolve the timeline once metadata is known, then drive `activeWord`. */
  const attachTimeline = useCallback(
    (audio: HTMLAudioElement, words: SpokenWord[], fallbackText: string, token: number) => {
      const apply = (resolved: SpokenWord[]) => {
        if (tokenRef.current !== token || playbackRef.current?.audio !== audio) return;
        setTimeline(resolved);
        setActiveWord(resolved.length ? 0 : -1);
      };

      if (words.length) {
        apply(words);
      } else if (audio.readyState >= 1) {
        apply(estimateTimeline(fallbackText, audio.duration));
      } else {
        audio.onloadedmetadata = () => {
          audio.onloadedmetadata = null;
          apply(estimateTimeline(fallbackText, audio.duration));
        };
      }

      let lastIndex = -2;
      audio.ontimeupdate = () => {
        if (tokenRef.current !== token || playbackRef.current?.audio !== audio) return;
        const t = audio.currentTime;
        // Binary search for the last word that starts at or before `t`.
        let lo = 0;
        let hi = words.length - 1;
        let found = -1;
        while (lo <= hi) {
          const mid = (lo + hi) >> 1;
          if (words[mid].start <= t) {
            found = mid;
            lo = mid + 1;
          } else {
            hi = mid - 1;
          }
        }
        if (found !== lastIndex) {
          lastIndex = found;
          setActiveWord(found);
        }
      };
    },
    [],
  );

  const speak = useCallback(
    async ({
      materialId,
      locator,
      locale,
      fallbackText,
      timed = false,
    }: {
      materialId: string;
      locator: number;
      locale: string;
      fallbackText: string;
      /** Request server word timings for read-along highlighting. */
      timed?: boolean;
    }) => {
      const token = ++tokenRef.current;
      disposeAudio();
      window.speechSynthesis?.cancel();
      setSpeaking(false);
      setActiveWord(-1);
      setTimeline([]);
      let playback: Playback | null = null;
      try {
        let blob: Blob;
        let words: SpokenWord[] = [];
        let wasTimed = false;
        if (timed) {
          const result = await readReadingAloudTimed(materialId, { locator });
          blob = result.audio;
          words = result.words;
          wasTimed = result.timed;
        } else {
          blob = await readReadingAloudAudio(materialId, { locator });
        }
        if (tokenRef.current !== token || !blob.size) return false;
        const url = URL.createObjectURL(blob);
        const audio = new Audio(url);
        playback = { audio, url, disposed: false };
        playbackRef.current = playback;
        const finished = () => {
          disposeAudio(playback);
          if (tokenRef.current === token) {
            setSpeaking(false);
            setActiveWord(-1);
          }
        };
        audio.onended = finished;
        audio.onerror = finished;
        if (timed) attachTimeline(audio, wasTimed ? words : [], fallbackText, token);
        await audio.play();
        if (tokenRef.current !== token) {
          disposeAudio(playback);
          return true;
        }
        if (!playback.disposed) setSpeaking(true);
        return true;
      } catch {
        disposeAudio(playback);
        if (tokenRef.current !== token) return true;
      }

      if (!("speechSynthesis" in window) || !fallbackText) return false;
      const utterance = new SpeechSynthesisUtterance(fallbackText);
      utterance.lang = locale;
      // Browser speech reports its own word boundary, so read-along still works.
      if (timed) {
        const words = estimatedWordsFor(fallbackText);
        setTimeline(words);
        utterance.onboundary = (event) => {
          if (tokenRef.current !== token) return;
          if (typeof event.charIndex !== "number") return;
          setActiveWord(indexAtChar(words, fallbackText, event.charIndex));
        };
      }
      utterance.onend = () => {
        if (tokenRef.current === token) {
          setSpeaking(false);
          setActiveWord(-1);
        }
      };
      utterance.onerror = () => {
        if (tokenRef.current === token) {
          setSpeaking(false);
          setActiveWord(-1);
        }
      };
      window.speechSynthesis.speak(utterance);
      setSpeaking(true);
      return true;
    },
    [attachTimeline, disposeAudio],
  );

  return { speak, speaking, stop, activeWord, timeline };
}

function estimatedWordsFor(text: string): SpokenWord[] {
  const tokens = text.split(/\s+/).filter(Boolean);
  return tokens.map((word) => ({ word, start: 0, duration: 0 }));
}

/** Map a character index from `onboundary` onto the matching word slot. */
function indexAtChar(words: SpokenWord[], text: string, charIndex: number): number {
  const tokens = [...text.matchAll(/\S+/g)];
  for (let i = 0; i < tokens.length; i += 1) {
    const start = tokens[i].index ?? 0;
    const end = start + tokens[i][0].length;
    if (charIndex >= start && charIndex < end) return Math.min(i, words.length - 1);
  }
  return -1;
}
