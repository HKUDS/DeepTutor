"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { legacySettingsDestination } from "@/features/settings/navigation/settings-pages";
import { SETTINGS_ANCHOR_EVENT } from "@/features/settings/navigation/settings-scroll";

/** Resolve pre-upgrade bookmarks on the client: fragments never reach the server. */
export default function SettingsEntry() {
  const router = useRouter();
  useEffect(() => {
    const navigate = () =>
      router.replace(
        legacySettingsDestination(window.location.hash, window.location.search),
        {
          scroll: false,
        },
      );
    navigate();
    window.addEventListener("hashchange", navigate);
    window.addEventListener(SETTINGS_ANCHOR_EVENT, navigate);
    return () => {
      window.removeEventListener("hashchange", navigate);
      window.removeEventListener(SETTINGS_ANCHOR_EVENT, navigate);
    };
  }, [router]);
  return <div className="min-h-48" aria-busy="true" />;
}
