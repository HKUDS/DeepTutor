"use client";

import { useCallback, useEffect, useState } from "react";

import { apiFetch, apiUrl } from "@/lib/api";

// Three-state autoplay model:
//   • global default — persisted per-user (Settings › Voice → ui.voice_autoplay)
//   • session override — sessionStorage, wins over the global default
//   • first-play prompt — when the global default is off and the user manually
//     plays one reply, we offer to auto-play the rest of the session.
const SESSION_KEY_PREFIX = "deeptutor.voiceAutoplay.session"; // "on" | "off"
const PROMPTED_KEY_PREFIX = "deeptutor.voiceAutoplay.prompted"; // "1"
const GLOBAL_EVENT = "deeptutor:voice-autoplay-global";
const SESSION_EVENT = "deeptutor:voice-autoplay-session";

let cachedGlobal: boolean | null = null;
let inflight: Promise<boolean> | null = null;

function fetchGlobalDefault(): Promise<boolean> {
  if (cachedGlobal !== null) return Promise.resolve(cachedGlobal);
  if (!inflight) {
    inflight = apiFetch(apiUrl("/api/v1/settings"))
      .then((r) => (r.ok ? r.json() : null))
      .then((payload) => {
        cachedGlobal = Boolean(payload?.ui?.voice_autoplay);
        return cachedGlobal;
      })
      .catch(() => {
        cachedGlobal = false;
        return false;
      })
      .finally(() => {
        inflight = null;
      });
  }
  return inflight;
}

function scopedKey(prefix: string, scopeKey?: string): string {
  return `${prefix}:${scopeKey || "default"}`;
}

function readSession(scopeKey?: string): boolean | null {
  if (typeof window === "undefined") return null;
  try {
    const v = window.sessionStorage.getItem(
      scopedKey(SESSION_KEY_PREFIX, scopeKey),
    );
    return v === "on" ? true : v === "off" ? false : null;
  } catch {
    return null;
  }
}

function writeSession(value: boolean, scopeKey?: string): void {
  if (typeof window === "undefined") return;
  try {
    window.sessionStorage.setItem(
      scopedKey(SESSION_KEY_PREFIX, scopeKey),
      value ? "on" : "off",
    );
    window.dispatchEvent(
      new CustomEvent(SESSION_EVENT, { detail: { scopeKey, value } }),
    );
  } catch {
    // sessionStorage may be unavailable
  }
}

/**
 * Settings-page hook: read/write the persisted global default.
 */
export function useVoiceAutoplayPreference() {
  const [value, setVal] = useState<boolean>(cachedGlobal ?? false);
  const [loading, setLoading] = useState<boolean>(cachedGlobal === null);

  useEffect(() => {
    let active = true;
    fetchGlobalDefault().then((v) => {
      if (active) {
        setVal(v);
        setLoading(false);
      }
    });
    return () => {
      active = false;
    };
  }, []);

  const setValue = useCallback(async (next: boolean) => {
    setVal(next);
    cachedGlobal = next;
    if (typeof window !== "undefined") {
      window.dispatchEvent(
        new CustomEvent(GLOBAL_EVENT, { detail: { value: next } }),
      );
    }
    await apiFetch(apiUrl("/api/v1/settings/voice-autoplay"), {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ voice_autoplay: next }),
    });
  }, []);

  return { value, setValue, loading };
}

/**
 * Chat-surface hook: the effective autoplay flag plus the session controls
 * and the first-play prompt gate.
 */
export function useVoiceAutoplay(scopeKey?: string) {
  const normalizedScopeKey = scopeKey || undefined;
  const [globalDefault, setGlobalDefault] = useState<boolean>(
    cachedGlobal ?? false,
  );
  const [stateScopeKey, setStateScopeKey] = useState<string | undefined>(
    normalizedScopeKey,
  );
  const [sessionOverride, setSessionOverride] = useState<boolean | null>(() =>
    readSession(normalizedScopeKey),
  );
  if (stateScopeKey !== normalizedScopeKey) {
    setStateScopeKey(normalizedScopeKey);
    setSessionOverride(readSession(normalizedScopeKey));
  }

  useEffect(() => {
    let active = true;
    fetchGlobalDefault().then((v) => active && setGlobalDefault(v));
    const onGlobal = (e: Event) =>
      setGlobalDefault(Boolean((e as CustomEvent).detail?.value));
    const onSession = (e: Event) => {
      const detail = (e as CustomEvent).detail as
        | { scopeKey?: string; value?: boolean }
        | undefined;
      if ((detail?.scopeKey || undefined) !== normalizedScopeKey) return;
      setSessionOverride(Boolean(detail?.value));
    };
    window.addEventListener(GLOBAL_EVENT, onGlobal);
    window.addEventListener(SESSION_EVENT, onSession);
    return () => {
      active = false;
      window.removeEventListener(GLOBAL_EVENT, onGlobal);
      window.removeEventListener(SESSION_EVENT, onSession);
    };
  }, [normalizedScopeKey]);

  const autoplayEnabled = sessionOverride ?? globalDefault;

  const enableForSession = useCallback(() => {
    writeSession(true, normalizedScopeKey);
    setSessionOverride(true);
  }, [normalizedScopeKey]);

  const disableForSession = useCallback(() => {
    writeSession(false, normalizedScopeKey);
    setSessionOverride(false);
  }, [normalizedScopeKey]);

  const markPrompted = useCallback(() => {
    if (typeof window === "undefined") return;
    try {
      window.sessionStorage.setItem(
        scopedKey(PROMPTED_KEY_PREFIX, normalizedScopeKey),
        "1",
      );
    } catch {
      // ignore
    }
  }, [normalizedScopeKey]);

  // Offer the "auto-play this session?" prompt only when autoplay isn't already
  // on and we haven't asked yet this session.
  const shouldPromptOnFirstPlay = useCallback((): boolean => {
    if (autoplayEnabled) return false;
    if (sessionOverride !== null) return false;
    if (typeof window === "undefined") return false;
    try {
      return (
        window.sessionStorage.getItem(
          scopedKey(PROMPTED_KEY_PREFIX, normalizedScopeKey),
        ) !== "1"
      );
    } catch {
      return false;
    }
  }, [autoplayEnabled, normalizedScopeKey, sessionOverride]);

  return {
    autoplayEnabled,
    enableForSession,
    disableForSession,
    markPrompted,
    shouldPromptOnFirstPlay,
  };
}
