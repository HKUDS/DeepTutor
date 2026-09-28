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
    try {
      browserStorage.writeRaw(
        "session",
        SETTINGS_RETURN_KEY,
        pathname + window.location.search + window.location.hash,
      );
    } catch {
      /* Storage can be disabled. Returning home remains available. */
    }
  }, [pathname]);
  return null;
}
