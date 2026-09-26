/**
 * The one place a route coming from the native shell is trusted.
 *
 * The shell's deep-link grammar is strict (`deeplink.rs`), but a notification
 * target's route is built from server data (`/chat/<sessionId>`), and the bridge
 * runs in a window whose `<a href>` targets and `router.push` arguments decide
 * whether the webview stays inside the app. Anything that is not a single
 * `/`-prefixed path — an absolute URL, a `//host` protocol-relative reference,
 * an empty string — is refused rather than navigated to.
 */
export function safeRoute(route: string | null | undefined): string | null {
  const trimmed = route?.trim();
  if (!trimmed || !trimmed.startsWith("/") || trimmed.startsWith("//")) {
    return null;
  }
  return trimmed;
}
