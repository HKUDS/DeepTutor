"use client";

/**
 * Whether a text-to-speech provider is configured on this deployment.
 *
 * Read-aloud surfaces need to know before they offer anything: without a
 * provider the backend answers ``400`` and the learner just sees an error.
 * The answer is fetched once per page and shared, so a chat full of replies
 * does not ask the readiness endpoint per message.
 *
 * ``null`` means "still unknown" — callers should stay quiet until it
 * resolves rather than guess.
 */

import { useEffect, useState } from "react";

import { fetchSettingsReadiness, type SettingsReadinessSnapshot } from "@/lib/settings-readiness";

let cached: boolean | null = null;
let inflight: Promise<boolean> | null = null;

function ttsConfigured(snapshot: SettingsReadinessSnapshot): boolean {
  const row = snapshot.rows?.find((entry) => entry.id === "catalog.tts");
  if (!row) return false;
  return Boolean(row.configured && row.available);
}

export function useTtsReadiness(): boolean | null {
  const [ready, setReady] = useState<boolean | null>(cached);

  useEffect(() => {
    if (cached !== null) return;
    let cancelled = false;
    if (!inflight) {
      inflight = fetchSettingsReadiness()
        .then((snapshot) => {
          cached = ttsConfigured(snapshot);
          return cached;
        })
        .catch(() => {
          cached = false;
          return false;
        });
    }
    void inflight.then((value) => {
      if (!cancelled) setReady(value);
    });
    return () => {
      cancelled = true;
    };
  }, []);

  return ready;
}
