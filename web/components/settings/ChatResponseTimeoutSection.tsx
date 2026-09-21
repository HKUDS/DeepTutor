"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { SettingRow, SettingSection, inputClass } from "./shared";
import { useSettings } from "@/features/settings/store/SettingsStore";
import { apiFetch, apiUrl } from "@/lib/api";
import {
  DEFAULT_CHAT_RESPONSE_TIMEOUT_SECONDS,
  MAX_CHAT_RESPONSE_TIMEOUT_SECONDS,
  MIN_CHAT_RESPONSE_TIMEOUT_SECONDS,
  clampChatResponseTimeout,
  writeStoredChatResponseTimeout,
} from "@/context/app-shell-storage";

/**
 * Per-user chat idle-timeout control. Self-contained (its own fetch + save via
 * the dedicated ``/settings/chat-response-timeout`` endpoint) and renders
 * independently of the admin network settings below, so any user can adjust it.
 * Mirrors the value to localStorage so the chat watchdog picks it up at once.
 */
export default function ChatResponseTimeoutSection() {
  const { t } = useTranslation();
  const { registerExtension, pendingExtensionPayload, draftRevision } =
    useSettings();
  const [seconds, setSeconds] = useState<number>(
    DEFAULT_CHAT_RESPONSE_TIMEOUT_SECONDS,
  );
  const [initial, setInitial] = useState<number>(
    DEFAULT_CHAT_RESPONSE_TIMEOUT_SECONDS,
  );
  const [message, setMessage] = useState("");
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const response = await apiFetch(apiUrl("/api/settings"));
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const data = (await response.json().catch(() => ({}))) as {
          ui?: { chat_response_timeout?: number };
        };
        const value = clampChatResponseTimeout(
          Number(data?.ui?.chat_response_timeout) ||
            DEFAULT_CHAT_RESPONSE_TIMEOUT_SECONDS,
        );
        if (cancelled) return;
        const pending = pendingExtensionPayload("chat-timeout") as
          { chat_response_timeout?: number } | undefined;
        setSeconds(pending?.chat_response_timeout ?? value);
        setInitial(value);
        setLoaded(true);
        writeStoredChatResponseTimeout(value);
      } catch (err) {
        if (!cancelled)
          setMessage(err instanceof Error ? err.message : String(err));
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [draftRevision, pendingExtensionPayload]);

  const dirty = loaded && seconds !== initial;

  // Flush through the global Apply (top toolbar) instead of a local button.
  const secondsRef = useRef(seconds);
  secondsRef.current = seconds;
  const save = useCallback(async () => {
    setMessage("");
    try {
      const value = clampChatResponseTimeout(secondsRef.current);
      const response = await apiFetch(
        apiUrl("/api/settings/chat-response-timeout"),
        {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ chat_response_timeout: value }),
        },
      );
      if (!response.ok) throw new Error(t("Failed to save."));
      setSeconds(value);
      setInitial(value);
      writeStoredChatResponseTimeout(value);
    } catch (err) {
      setMessage(err instanceof Error ? err.message : String(err));
      throw err;
    }
  }, [t]);

  useEffect(() => {
    registerExtension("chat-timeout", {
      dirty,
      save,
      payload: loaded ? { chat_response_timeout: seconds } : null,
    });
    return () => registerExtension("chat-timeout", null);
  }, [dirty, loaded, save, seconds, registerExtension]);

  return (
    <SettingSection
      title={t("Chat response timeout")}
      description={t(
        "How long chat waits for a reply before showing a timeout error. Increase it for slow tools like image or video generation.",
      )}
    >
      <SettingRow
        title={t("Timeout (seconds)")}
        description={t(
          "Between {{min}} and {{max}} seconds. Takes effect immediately — no restart.",
          {
            min: MIN_CHAT_RESPONSE_TIMEOUT_SECONDS,
            max: MAX_CHAT_RESPONSE_TIMEOUT_SECONDS,
          },
        )}
        control={
          <input
            className={`${inputClass} w-28`}
            disabled={!loaded}
            aria-label={t("Timeout (seconds)")}
            type="number"
            min={MIN_CHAT_RESPONSE_TIMEOUT_SECONDS}
            max={MAX_CHAT_RESPONSE_TIMEOUT_SECONDS}
            value={seconds}
            onChange={(event) => setSeconds(Number(event.target.value))}
          />
        }
      />
      {message && (
        <p className="px-1 pb-3 text-[11.5px] text-[var(--muted-foreground)]">
          {message}
        </p>
      )}
    </SettingSection>
  );
}
