"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useState,
  type ReactNode,
} from "react";

import type { Capability } from "@/lib/capability-routes";
import { apiFetch, apiUrl } from "@/lib/api";
import { listLLMOptions } from "@/lib/llm-options";

type CapabilityAccessValue = {
  /** True until the first access probe resolves. */
  loading: boolean;
  /** Admins manage the catalog directly and are never gated. */
  isAdmin: boolean;
  /** Whether the current user has at least one usable LLM model. */
  hasLlm: boolean;
  /** Whether the current user may use a gated capability. */
  has: (capability: Capability) => boolean;
  /** Re-probe access (used on tab focus to pick up mid-session grant changes). */
  refresh: () => Promise<void>;
};

// Default value keeps the hook safe outside a provider (e.g. shared components
// rendered in the admin tree): everything reads as available, and the backend
// remains the real enforcement boundary.
const DEFAULT_VALUE: CapabilityAccessValue = {
  loading: false,
  isAdmin: true,
  hasLlm: true,
  has: () => true,
  refresh: async () => {},
};

const CapabilityAccessContext =
  createContext<CapabilityAccessValue>(DEFAULT_VALUE);

export function useCapabilityAccess(): CapabilityAccessValue {
  return useContext(CapabilityAccessContext);
}

export function CapabilityAccessProvider({
  children,
}: {
  children: ReactNode;
}) {
  // Optimistic until the first probe resolves so we never flash a locked UI
  // (admins and users-with-access stay unlocked; the backend enforces anyway).
  const [isAdmin, setIsAdmin] = useState(true);
  const [hasLlm, setHasLlm] = useState(true);
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async () => {
    try {
      // The settings payload only exposes the catalog to admins, so its
      // presence is our admin signal — admins are never gated.
      const res = await apiFetch(apiUrl("/api/v1/settings"));
      if (!res.ok) return;
      const payload = (await res.json()) as { catalog?: unknown };
      if (payload.catalog) {
        setIsAdmin(true);
        setHasLlm(true);
        return;
      }
      setIsAdmin(false);
      // Non-admins: their grant-filtered LLM options decide access.
      const { options } = await listLLMOptions();
      setHasLlm(options.length > 0);
    } catch {
      // Keep last known state; the backend still enforces access on every call.
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  // Re-check when the user returns to the tab. This is what surfaces a
  // mid-session revocation (admin removed the grant while the tab was open)
  // without any polling — the next focus re-reads access and locks the UI.
  useEffect(() => {
    const onFocus = () => void refresh();
    const onVisible = () => {
      if (document.visibilityState === "visible") void refresh();
    };
    window.addEventListener("focus", onFocus);
    document.addEventListener("visibilitychange", onVisible);
    return () => {
      window.removeEventListener("focus", onFocus);
      document.removeEventListener("visibilitychange", onVisible);
    };
  }, [refresh]);

  const has = useCallback(
    (_capability: Capability): boolean => {
      // Only LLM is gated today. Admins and the pre-load window are never gated.
      if (isAdmin || loading) return true;
      return hasLlm;
    },
    [isAdmin, loading, hasLlm],
  );

  return (
    <CapabilityAccessContext.Provider
      value={{ loading, isAdmin, hasLlm, has, refresh }}
    >
      {children}
    </CapabilityAccessContext.Provider>
  );
}
