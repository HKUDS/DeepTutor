"use client";

import { useEffect, useState } from "react";
import { fetchAuthStatus } from "@/lib/auth";

export interface LearningPolicyState {
  /** Surfaces this account may open. Everything else is hidden, not a 403. */
  allowedSurfaces: string[];
}

export interface AuthStatusState {
  /** Whether auth is enabled on the backend. */
  enabled: boolean;
  /** Whether the current session is authenticated. */
  authenticated: boolean;
  /** Whether the authenticated user is an admin. */
  isAdmin: boolean;
  /** Stable account id for account-scoped browser state. */
  userId: string | null;
  /** False when the runtime status endpoint could not be reached. */
  statusAvailable: boolean;
  /** True until the first status fetch resolves. */
  loading: boolean;
  /**
   * Effective learning policy from ``GET /api/auth/status``. Null for accounts
   * without one. The shell reads ``allowedSurfaces`` so denied features are
   * absent instead of offered and then rejected (#1222).
   */
  learningPolicy: LearningPolicyState | null;
}

const INITIAL: AuthStatusState = {
  enabled: false,
  authenticated: false,
  isAdmin: false,
  userId: null,
  statusAvailable: false,
  loading: true,
  learningPolicy: null,
};

function learningPolicyFromStatus(
  status: Awaited<ReturnType<typeof fetchAuthStatus>>,
): LearningPolicyState | null {
  const policy = status?.learning_policy;
  if (!policy) return null;
  const surfaces = (policy.allowed_surfaces ?? ["chat", "reading"]).filter(
    (surface) => surface.trim().length > 0,
  );
  return { allowedSurfaces: surfaces.length ? surfaces : ["chat", "reading"] };
}

/**
 * Resolve auth state at runtime from the backend (`/api/auth/status`).
 *
 * The frontend bundle is URL- and auth-agnostic (see web/lib/api.ts): the auth
 * toggle is a runtime setting read from `data/user/settings/auth.json`, never
 * baked into the build. Components that need to know whether auth is on — to
 * show the Sign-out / Admin affordances — use this hook instead of a build-time
 * constant, so it works identically on Docker (read-only rootfs), the PyPI
 * `deeptutor start` launcher, and source dev.
 */
function loadAuthStatus(): Promise<AuthStatusState> {
  return fetchAuthStatus().then((status) => ({
    enabled: Boolean(status?.enabled),
    authenticated: Boolean(status?.authenticated),
    isAdmin: status?.role === "admin",
    userId:
      typeof status?.user_id === "string" && status.user_id.trim()
        ? status.user_id
        : null,
    statusAvailable: status !== null,
    loading: false,
    learningPolicy: learningPolicyFromStatus(status),
  }));
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
