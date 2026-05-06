"use client";

import { useMemo } from "react";
import WorkspaceSidebar from "@/components/sidebar/WorkspaceSidebar";
import { UnifiedChatProvider } from "@/context/UnifiedChatContext";
import clsx from "clsx";

export default function WorkspaceLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  // Detect if running in Electron desktop client
  const isDesktopClient = useMemo(
    () =>
      typeof navigator !== "undefined" &&
      navigator.userAgent.includes("Electron"),
    []
  );

  return (
    <UnifiedChatProvider>
      <div className={clsx(
        "flex h-screen overflow-hidden",
        isDesktopClient && "bg-transparent"
      )}>
        <WorkspaceSidebar />
        <main
          className={clsx(
            "flex-1 overflow-hidden",
            isDesktopClient
              ? "bg-[var(--background)] rounded-l-xl"
              : "bg-[var(--background)]"
          )}
        >
          {children}
        </main>
      </div>
    </UnifiedChatProvider>
  );
}
