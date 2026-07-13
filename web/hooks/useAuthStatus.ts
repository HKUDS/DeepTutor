"use client";

import { useEffect, useState } from "react";
import { fetchAuthStatus } from "@/lib/auth";

export interface AuthStatusState {
  /** Whether auth is enabled on the backend. */
  enabled: boolean;
  /** Whether the current session is authenticated. */
  authenticated: boolean;
  /** Whether the authenticated user is an admin. */
  isAdmin: boolean;
  /** True until the first status fetch resolves. */
  loading: boolean;
}

const INITIAL: AuthStatusState = {
  enabled: false,
  authenticated: false,
  isAdmin: false,
  loading: true,
};

/**
 * Resolve auth state at runtime from the backend (`/api/v1/auth/status`).
 *
 * The frontend bundle is URL- and auth-agnostic (see web/lib/api.ts): the auth
 * toggle is a runtime setting read from `data/user/settings/auth.json`, never
 * baked into the build. Components that need to know whether auth is on — to
 * show the Sign-out / Admin affordances — use this hook instead of a build-time
 * constant, so it works identically on Docker (read-only rootfs), the PyPI
 * `deeptutor start` launcher, and source dev.
 */
// Several components (sidebar Admin / Logout / Profile links) mount this hook
// at once. Share a single in-flight request so a page load makes one
// /api/v1/auth/status call instead of one per consumer, and clear it once
// settled so a later mount (e.g. after login/logout) fetches fresh.
let inflight: Promise<AuthStatusState> | null = null;

function loadAuthStatus(): Promise<AuthStatusState> {
  if (!inflight) {
    inflight = fetchAuthStatus()
      .then((status) => ({
        enabled: Boolean(status?.enabled),
        authenticated: Boolean(status?.authenticated),
        isAdmin: status?.role === "admin",
        loading: false,
      }))
      .finally(() => {
        inflight = null;
      });
  }
  return inflight;
}

export function useAuthStatus(): AuthStatusState {
  const [state, setState] = useState<AuthStatusState>(INITIAL);

  useEffect(() => {
    let alive = true;
    loadAuthStatus().then((next) => {
      if (alive) setState(next);
    });
    return () => {
      alive = false;
    };
  }, []);

  return state;
}
