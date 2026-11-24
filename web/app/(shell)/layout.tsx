import { Suspense } from "react";
import CalendarRuntime from "@/features/calendar/components/CalendarRuntime";
import WorkspaceSidebar from "@/components/sidebar/WorkspaceSidebar";
import AppShell from "@/components/layout/AppShell";
import { LayoutPageBar } from "@/features/ui-layout/slots";
import { CapabilityAccessProvider } from "@/components/access/CapabilityAccessContext";
import CapabilityGate from "@/components/access/CapabilityGate";
import { ChatRuntimeProvider } from "@/features/chat";
import { ReadingProvider } from "@/context/ReadingContext";
import { WorkspaceRuntimeBoundary } from "@/components/workspaces/WorkspaceRuntimeBoundary";

const ShellFallback = (
  <div data-desktop-shell className="flex h-dvh overflow-hidden">
    <div data-desktop-sidebar className="hidden w-[272px] shrink-0 md:block" />
    <main
      data-desktop-main
      className="flex min-w-0 flex-1 flex-col overflow-hidden bg-[var(--background)]"
    />
  </div>
);

/**
 * Shared persistent shell for both `(workspace)` and `(utility)` route groups.
 * Keeps the sidebar, chat runtime, and reading state mounted across route-group
 * switches so navigating to/from Personalization, Space, or Agents never
 * unmounts the sidebar.
 */
export default function ShellLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <Suspense fallback={ShellFallback}>
      <CapabilityAccessProvider>
        <WorkspaceRuntimeBoundary>
          <CalendarRuntime>
            <ChatRuntimeProvider>
              {/* Above the page on purpose: sending the first message navigates
                  /chat → /chat/<id>, and hopping to Space/Settings keeps live
                  streams and open reading materials intact. */}
              <ReadingProvider>
                <AppShell sidebar={<WorkspaceSidebar />} pageBar={<LayoutPageBar />}>
                  <CapabilityGate>{children}</CapabilityGate>
                </AppShell>
              </ReadingProvider>
            </ChatRuntimeProvider>
          </CalendarRuntime>
        </WorkspaceRuntimeBoundary>
      </CapabilityAccessProvider>
    </Suspense>
  );
}
