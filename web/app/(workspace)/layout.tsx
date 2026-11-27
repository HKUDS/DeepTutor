import { PageCustomizationProvider } from "@/context/PageCustomizationContext";
import CalendarRuntime from "@/features/calendar/components/CalendarRuntime";
import TaskBoardRuntime from "@/components/tasks/TaskBoardRuntime";
import WorkspaceSidebar from "@/components/sidebar/WorkspaceSidebar";
import AppShell from "@/components/layout/AppShell";
import { LayoutPageBar } from "@/features/ui-layout/slots";
import { CapabilityAccessProvider } from "@/components/access/CapabilityAccessContext";
import CapabilityGate from "@/components/access/CapabilityGate";
import { ChatRuntimeProvider } from "@/features/chat";
import { ReadingProvider } from "@/context/ReadingContext";
import { Suspense } from "react";
import { WorkspaceRuntimeBoundary } from "@/components/workspaces/WorkspaceRuntimeBoundary";

export default function WorkspaceLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <CapabilityAccessProvider>
      <PageCustomizationProvider>
      <Suspense>
        <WorkspaceRuntimeBoundary>
          <CalendarRuntime>
          {/* Inside the boundary: each workspace has its own board. */}
          <TaskBoardRuntime>
            <ChatRuntimeProvider>
              {/* Above the page on purpose: sending the first message navigates
            /chat → /chat/<id>, which remounts the page. The open document
            must not die with it. */}
              <ReadingProvider>
                  <AppShell sidebar={<WorkspaceSidebar />} pageBar={<LayoutPageBar />}>
                    <CapabilityGate>{children}</CapabilityGate>
                  </AppShell>
              </ReadingProvider>
            </ChatRuntimeProvider>
          </TaskBoardRuntime>
        </CalendarRuntime>
        </WorkspaceRuntimeBoundary>
      </Suspense>
    </PageCustomizationProvider>
    </CapabilityAccessProvider>
  );
}
