"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { readReadingAloudAudio } from "@/lib/reading-api";

type Playback = { audio: HTMLAudioElement; url: string; disposed: boolean };

/** Play verified server speech, falling back to browser speech when unavailable. */
export function useReadAloudSpeech() {
  const [speaking, setSpeaking] = useState(false);
  const tokenRef = useRef(0);
  const playbackRef = useRef<Playback | null>(null);

  const disposeAudio = useCallback((playback = playbackRef.current) => {
    if (!playback) return;
    if (!playback.disposed) {
      playback.disposed = true;
      playback.audio.onended = null;
      playback.audio.onerror = null;
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
  }, [disposeAudio]);

  useEffect(() => () => {
    tokenRef.current += 1;
    disposeAudio();
    window.speechSynthesis?.cancel();
  }, [disposeAudio]);

  const speak = useCallback(
    async ({ materialId, locator, locale, fallbackText }: {
      materialId: string;
      locator: number;
      locale: string;
      fallbackText: string;
    }) => {
      const token = ++tokenRef.current;
      disposeAudio();
      window.speechSynthesis?.cancel();
      setSpeaking(false);
      let playback: Playback | null = null;
      try {
        const blob = await readReadingAloudAudio(materialId, { locator });
        if (tokenRef.current !== token || !blob.size) return false;
        const url = URL.createObjectURL(blob);
        const audio = new Audio(url);
        playback = { audio, url, disposed: false };
        playbackRef.current = playback;
        const finished = () => {
          disposeAudio(playback);
          if (tokenRef.current === token) setSpeaking(false);
        };
        audio.onended = finished;
        audio.onerror = finished;
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
      utterance.onend = () => {
        if (tokenRef.current === token) setSpeaking(false);
      };
      utterance.onerror = () => {
        if (tokenRef.current === token) setSpeaking(false);
      };
      window.speechSynthesis.speak(utterance);
      setSpeaking(true);
      return true;
    },
    [disposeAudio],
  );

  return { speak, speaking, stop };
}
