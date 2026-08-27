export function invidiousFallbackUrl(publicBaseUrl?: string | null): string {
  const base = String(publicBaseUrl || "").trim().replace(/\/$/, "");
  return base ? `${base}/feed/popular` : "";
}

export function shouldOpenInvidiousInCurrentTab(
  preferSameTab: boolean,
  popupAvailable: boolean,
): boolean {
  return preferSameTab || !popupAvailable;
}
