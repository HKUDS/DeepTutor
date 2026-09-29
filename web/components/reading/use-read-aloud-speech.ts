"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { readReadingAloudAudio } from "@/lib/reading-api";

/**
 * Play server speech for a verified reading unit, with browser speech as the
 * offline/no-provider fallback. A token keeps late audio responses from
 * starting after the reader has navigated away or pressed stop.
 */
export function useReadAloudSpeech() {
  const [speaking, setSpeaking] = useState(false);
  const tokenRef = useRef(0);
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const audioUrlRef = useRef<string | null>(null);

  const disposeAudio = useCallback(() => {
    audioRef.current?.pause();
    if (audioUrlRef.current) URL.revokeObjectURL(audioUrlRef.current);
    audioRef.current = null;
    audioUrlRef.current = null;
  }, []);

  const stop = useCallback(() => {
    tokenRef.current += 1;
    disposeAudio();
    window.speechSynthesis?.cancel();
    setSpeaking(false);
  }, [disposeAudio]);

  useEffect(() => disposeAudio, [disposeAudio]);

  const speak = useCallback(
    async ({
      materialId,
      locator,
      locale,
      fallbackText,
    }: {
      materialId: string;
      locator: number;
      locale: string;
      fallbackText: string;
    }) => {
      const token = ++tokenRef.current;
      disposeAudio();
      window.speechSynthesis?.cancel();
      try {
        const blob = await readReadingAloudAudio(materialId, { locator });
        if (tokenRef.current !== token || !blob.size) return false;
        const url = URL.createObjectURL(blob);
        const audio = new Audio(url);
        audioUrlRef.current = url;
        audioRef.current = audio;
        audio.onended = () => {
          if (tokenRef.current === token) {
            disposeAudio();
            setSpeaking(false);
          }
        };
        audio.onerror = () => {
          if (tokenRef.current === token) {
            disposeAudio();
            setSpeaking(false);
          }
        };
        await audio.play();
        if (tokenRef.current !== token) {
          disposeAudio();
          return true;
        }
        setSpeaking(true);
        return true;
      } catch {
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
