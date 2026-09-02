import type { AuthStatus } from "@/lib/auth";

export interface SettingsAccess {
  /** False until the backend has resolved the runtime auth mode and account. */
  resolved: boolean;
  /** Admin-owned settings stay hidden on auth failures and for ordinary users. */
  hideAdminOnly: boolean;
  /** The self-service learner profile belongs only to learner accounts. */
  showLearnerOnly: boolean;
  /** Ordinary standard/custom accounts may act as authorized guardians. */
  showGuardianOnly: boolean;
}

export const PENDING_SETTINGS_ACCESS: SettingsAccess = {
  resolved: false,
  hideAdminOnly: true,
  showLearnerOnly: false,
  showGuardianOnly: false,
};

/** Convert the backend's account identity into the settings visibility model. */
export function settingsAccessFromAuthStatus(
  authStatus: AuthStatus | null,
): SettingsAccess {
  if (!authStatus) {
    return { ...PENDING_SETTINGS_ACCESS, resolved: true };
  }

  const ordinaryAuthenticatedUser = Boolean(
    authStatus.enabled && authStatus.authenticated && !authStatus.is_admin,
  );
  return {
    resolved: true,
    hideAdminOnly: Boolean(authStatus.enabled) && !authStatus.is_admin,
    showLearnerOnly:
      ordinaryAuthenticatedUser && authStatus.preset === "learner",
    showGuardianOnly:
      ordinaryAuthenticatedUser &&
      (authStatus.preset === "standard" || authStatus.preset === "custom"),
  };
}
