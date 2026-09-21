"use client";

import {
  useCallback,
  useEffect,
  type Dispatch,
  type SetStateAction,
} from "react";
import { useSettings } from "./SettingsStore";
import { applyExtensionPayload } from "@/lib/settings-extensions";

/** Keep edits in the layout's draft, including while this editor is unmounted. */
export function useStagedSettings<T>(
  key: string,
  live: T,
  setLive: Dispatch<SetStateAction<T>>,
): [T, Dispatch<SetStateAction<T>>] {
  const { pendingExtensionPayload, registerExtension, draftRevision } =
    useSettings();
  const value = (pendingExtensionPayload(key) as T | undefined) ?? live;
  const edit = useCallback<Dispatch<SetStateAction<T>>>(
    (action) => {
      const current = (pendingExtensionPayload(key) as T | undefined) ?? live;
      const next =
        typeof action === "function"
          ? (action as (value: T) => T)(current)
          : action;
      registerExtension(key, {
        dirty: JSON.stringify(next) !== JSON.stringify(live),
        payload: next,
        save: async () => {
          await applyExtensionPayload(key, next);
          setLive(next);
        },
      });
    },
    [key, live, pendingExtensionPayload, registerExtension, setLive],
  );
  useEffect(() => {
    const pending = pendingExtensionPayload(key) as T | undefined;
    // A fetched baseline may not have arrived yet. Restoring a pending value
    // must never compare it with a placeholder and silently discard the edit.
    if (pending !== undefined)
      registerExtension(key, {
        dirty: true,
        payload: pending,
        save: async () => {
          await applyExtensionPayload(key, pending);
          setLive(pending);
        },
      });
  }, [
    key,
    live,
    draftRevision,
    pendingExtensionPayload,
    registerExtension,
    setLive,
  ]);
  useEffect(
    () => () => registerExtension(key, null),
    [key, registerExtension],
  );
  return [value, edit];
}
