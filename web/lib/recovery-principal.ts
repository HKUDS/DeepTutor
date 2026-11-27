/** Recovery ownership comes only from a resolved server authentication status. */
export const RECOVERY_PRINCIPAL_CHANGED = "deeptutor:recovery-principal-changed";
let principal: string | null = null;

export function recoveryPrincipal(): string | null {
  return principal;
}

export function updateRecoveryPrincipal(status: {
  enabled: boolean; authenticated: boolean; user_id?: string;
} | null): void {
  const next = status?.enabled === false ? "single-user"
    : status?.enabled === true && status.authenticated === true &&
      typeof status.user_id === "string" && status.user_id.trim()
      ? "user:" + status.user_id : null;
  if (next === principal) return;
  principal = next;
  if (typeof window !== "undefined") window.dispatchEvent(new Event(RECOVERY_PRINCIPAL_CHANGED));
}
