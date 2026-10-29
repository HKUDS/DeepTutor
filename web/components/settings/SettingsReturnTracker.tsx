"use client";

import { useEffect } from "react";
import { browserStorage } from "@/shared/storage";
import { usePathname } from "next/navigation";

export const SETTINGS_RETURN_KEY = "deeptutor:settings-return";

/** Session-only navigation state; never touches a user's configuration. */
export default function SettingsReturnTracker() {
  const pathname = usePathname();
  useEffect(() => {
    if (
      !pathname ||
      pathname === "/settings" ||
      pathname.startsWith("/settings/")
    )
      return;
    if (pathname.startsWith("/login") || pathname.startsWith("/register"))
      return;
    // Without the workspace: returning from Settings stays in whichever
    // workspace the tab is in by then, instead of switching back.
    const query = new URLSearchParams(window.location.search);
    query.delete("dt_workspace");
    query.delete("workspace");
    try {
      browserStorage.writeRaw(
        "session",
        SETTINGS_RETURN_KEY,
        pathname + (query.size ? `?${query}` : "") + window.location.hash,
      );
    } catch {
      /* Storage can be disabled. Returning home remains available. */
    }
  }, [pathname]);
  return null;
}
