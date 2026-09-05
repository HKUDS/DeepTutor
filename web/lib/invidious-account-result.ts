/** Static translation keys for safe callback outcomes; never render provider input. */
export function invidiousAccountResultMessage(
  result: string | null,
): string | null {
  switch (result) {
    case "connected":
      return "Invidious account connected. Your subscriptions and playlists are ready.";
    case "authorization_expired":
      return "This authorization link expired or was already used. Click Connect Invidious to start again.";
    case "authorization_cancelled":
      return "Authorization was cancelled. You can connect again whenever you are ready.";
    case "authorization_scopes":
      return "Some read permissions were missing. Reconnect and approve all listed permissions.";
    case "authorization_token_invalid":
      return "The instance returned an unsupported token. Start a new connection and try again.";
    case "authorization_token_rejected":
      return "Invidious rejected the token. Reconnect to issue a new one.";
    case "authorization_unavailable":
      return "The Invidious instance could not verify your account. Check the instance and reconnect.";
    case "authorization_login_required":
      return "Your DeepTutor login expired during authorization. Sign in, then start a new Invidious connection.";
    case "authorization_failed":
      return "The account could not be connected. Please start a new connection.";
    default:
      return null;
  }
}
