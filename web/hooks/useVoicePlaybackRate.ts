"use client";

import { useState } from "react";
import { browserStorage } from "@/shared/storage";

export const VOICE_PLAYBACK_RATES = [0.75, 1, 1.25, 1.5, 2] as const;

function normalizeRate(value: number): number {
  return VOICE_PLAYBACK_RATES.some((rate) => rate === value) ? value : 1;
}

function readRate(scopeKey?: string): number {
  if (!scopeKey) return 1;
  return normalizeRate(Number(browserStorage.readRaw("local", storageKey(scopeKey))));
}

function storageKey(scopeKey: string): string {
  return `deeptutor.voicePlaybackRate:${scopeKey}`;
}

interface VoicePlaybackRatePreference {
  rate: number;
  setRate: (rate: number) => void;
}

/** Persist a conversation's playback rate in this browser. */
export function useVoicePlaybackRate(scopeKey?: string): VoicePlaybackRatePreference {
  const [preference, setPreference] = useState(() => ({
    scopeKey,
    rate: readRate(scopeKey),
  }));

  if (preference.scopeKey !== scopeKey) {
    setPreference({ scopeKey, rate: readRate(scopeKey) });
  }

  function setRate(value: number) {
    const rate = normalizeRate(value);
    if (scopeKey) browserStorage.writeRaw("local", storageKey(scopeKey), String(rate));
    setPreference({ scopeKey, rate });
  }

  return { rate: preference.rate, setRate };
}
