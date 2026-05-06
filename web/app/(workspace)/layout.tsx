"use client";

import { useMemo } from "react";
import WorkspaceSidebar from "@/components/sidebar/WorkspaceSidebar";
import { UnifiedChatProvider } from "@/context/UnifiedChatContext";

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
      <div className={isDesktopClient ? "h-screen" : "h-screen"}>
        <WorkspaceSidebar />
      </div>
    </UnifiedChatProvider>
  );
}
