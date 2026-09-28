"use client";

import { useCallback, useEffect, useState } from "react";

import { apiFetch, apiUrl } from "@/lib/api";

const GLOBAL_EVENT = "deeptutor:voice-math-speak";

let cached: boolean | null = null;
let inflight: Promise<boolean> | null = null;

function fetchPreference(): Promise<boolean> {
  if (cached !== null) return Promise.resolve(cached);
  if (!inflight) {
    inflight = apiFetch(apiUrl("/api/settings"))
      .then((r) => (r.ok ? r.json() : null))
      .then((payload) => {
        const next = payload?.ui?.voice_math_speak !== false;
        cached = next;
        return next;
      })
      .catch(() => {
        cached = true;
        return true;
      })
      .finally(() => {
        inflight = null;
      });
  }
  return inflight;
}

/**
 * Settings-page hook: read/write whether TTS verbalizes LaTeX as spoken math.
 * Default is on. The server applies this on every /tts call.
 */
export function useVoiceMathSpeakPreference() {
  const [value, setVal] = useState<boolean>(cached ?? true);
  const [loading, setLoading] = useState<boolean>(cached === null);

  useEffect(() => {
    let active = true;
    fetchPreference().then((v) => {
      if (active) {
        setVal(v);
        setLoading(false);
      }
    });
    const onGlobal = (e: Event) =>
      setVal(Boolean((e as CustomEvent).detail?.value));
    window.addEventListener(GLOBAL_EVENT, onGlobal);
    return () => {
      active = false;
      window.removeEventListener(GLOBAL_EVENT, onGlobal);
    };
  }, []);

  const setValue = useCallback(async (next: boolean) => {
    setVal(next);
    cached = next;
    if (typeof window !== "undefined") {
      window.dispatchEvent(
        new CustomEvent(GLOBAL_EVENT, { detail: { value: next } }),
      );
    }
    await apiFetch(apiUrl("/api/settings/voice-math-speak"), {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ voice_math_speak: next }),
    });
  }, []);

  return { value, setValue, loading };
}
