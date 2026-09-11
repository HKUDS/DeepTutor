import { apiFetch, apiUrl, setRuntimeAuthEnabled } from "@/lib/api";

// Auth state is resolved at runtime from the backend (`/api/auth/status`),
// not from a build-time/env constant: the browser bundle never sees
// `DEEPTUTOR_AUTH_ENABLED` (not a `NEXT_PUBLIC_` var), and auth is runtime
// config that must not be baked into the bundle. Components observe it via the
// `useAuthStatus` hook (web/hooks/useAuthStatus.ts); `apiFetch`'s redirect gate
// is driven by `setRuntimeAuthEnabled`, which `fetchAuthStatus` calls below.

export interface AuthStatus {
  enabled: boolean;
  authenticated: boolean;
  user_id?: string;
  username?: string;
  role?: string;
  is_admin?: boolean;
  /** Server-side account preset; null for identities without a local account. */
  preset?: "standard" | "learner" | "custom" | null;
  /** Avatar marker: "", "icon:<name>:<color>", or "img:<version>". */
  avatar?: string;
  learning_policy?: {
    age_band: string;
    locked_persona: string;
    allowed_capabilities: string[];
    default_capability: string;
    allowed_surfaces?: string[];
    reading?: {
      allow_upload: boolean;
      material_ids: string[];
      extensions: string[];
    };
  } | null;
}

const AUTH_STATUS_CACHE_MS = 5_000;
let authStatusRequest: Promise<AuthStatus | null> | null = null;
let cachedAuthStatus: { value: AuthStatus | null; expiresAt: number } | null =
  null;

export function invalidateAuthStatusCache(): void {
  authStatusRequest = null;
  cachedAuthStatus = null;
}

/**
 * Call the backend to check whether the current session is authenticated.
 * Returns null on network error so callers can decide how to handle it.
 */
export function fetchAuthStatus(): Promise<AuthStatus | null> {
  if (cachedAuthStatus && cachedAuthStatus.expiresAt > Date.now()) {
    return Promise.resolve(cachedAuthStatus.value);
  }
  if (!authStatusRequest) {
    authStatusRequest = (async () => {
      try {
        const res = await apiFetch(apiUrl("/api/auth/status"));
        if (!res.ok) return null;
        const status: AuthStatus = await res.json();
        // Record the real auth state so apiFetch's in-session 401 → /login redirect
        // fires only when auth is actually enabled.
        setRuntimeAuthEnabled(Boolean(status.enabled));
        return status;
      } catch {
        return null;
      }
    })()
      .then((status) => {
        cachedAuthStatus = {
          value: status,
          // Retry unavailable backends quickly; stable answers can be shared
          // across the shell and Settings providers for one navigation.
          expiresAt: Date.now() + (status === null ? 1_000 : AUTH_STATUS_CACHE_MS),
        };
        return status;
      })
      .finally(() => {
        authStatusRequest = null;
      });
  }
  return authStatusRequest;
}

/**
 * POST credentials to the backend. Returns true on success.
 */
export async function login(
  username: string,
  password: string,
): Promise<{ ok: boolean; error?: string }> {
  try {
    const res = await apiFetch(apiUrl("/api/auth/login"), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username, password }),
      // A 401 here means "wrong credentials", not an expired session — handle it
      // inline as a form error instead of triggering the global login redirect.
      skipAuthRedirect: true,
    });

    if (res.ok) {
      invalidateAuthStatusCache();
      return { ok: true };
    }

    const data = await res.json().catch(() => ({}));
    return { ok: false, error: extractDetail(data.detail) ?? "Login failed" };
  } catch {
    return { ok: false, error: "Could not reach the server" };
  }
}

/**
 * Normalise a FastAPI error detail to a plain string.
 * FastAPI can return detail as a string (HTTPException) or as an array of
 * validation error objects (422 Unprocessable Entity).
 */
function extractDetail(detail: unknown): string {
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail) && detail.length > 0) {
    const first = detail[0];
    if (typeof first === "object" && first !== null && "msg" in first)
      return String((first as { msg: unknown }).msg);
  }
  return "Request failed";
}

/**
 * Register a new account. The first user to register becomes admin.
 */
export async function register(
  username: string,
  password: string,
): Promise<{
  ok: boolean;
  role?: string;
  is_first_user?: boolean;
  error?: string;
}> {
  try {
    const res = await apiFetch(apiUrl("/api/auth/register"), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username, password }),
      // Registration validation failures (e.g. 400/401) should surface inline
      // rather than bounce the user through the global login redirect.
      skipAuthRedirect: true,
    });

    const data = await res.json().catch(() => ({}));
    if (res.ok) {
      invalidateAuthStatusCache();
      return { ok: true, role: data.role, is_first_user: data.is_first_user };
    }
    return { ok: false, error: extractDetail(data.detail) };
  } catch {
    return { ok: false, error: "Could not reach the server" };
  }
}

/**
 * Check whether the user store is empty (first user will become admin).
 */
export async function checkIsFirstUser(): Promise<boolean> {
  try {
    const res = await apiFetch(apiUrl("/api/auth/is_first_user"));
    if (!res.ok) return false;
    const data = await res.json();
    return Boolean(data.is_first_user);
  } catch {
    return false;
  }
}

/**
 * POST to the logout endpoint to clear the session cookie.
 */
export async function logout(): Promise<void> {
  try {
    await apiFetch(apiUrl("/api/auth/logout"), {
      method: "POST",
    });
  } catch {
    // Ignore — we'll redirect regardless
  } finally {
    invalidateAuthStatusCache();
  }
}
