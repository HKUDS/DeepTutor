import CalendarRuntime from "@/features/calendar/components/CalendarRuntime";
import UtilitySidebar from "@/components/sidebar/UtilitySidebar";
import AppShell from "@/components/layout/AppShell";
import { LayoutPageBar } from "@/features/ui-layout/slots";
import { CapabilityAccessProvider } from "@/components/access/CapabilityAccessContext";
import CapabilityGate from "@/components/access/CapabilityGate";
import { WorkspaceRuntimeBoundary } from "@/components/workspaces/WorkspaceRuntimeBoundary";
import { Suspense } from "react";

export default function UtilityLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <CapabilityAccessProvider>
      {/* Utility pages read the workspace's own stores too; a switch remounts them. */}
      <Suspense>
        <WorkspaceRuntimeBoundary>
          <CalendarRuntime>
          <AppShell sidebar={<UtilitySidebar />} pageBar={<LayoutPageBar />}>
            <CapabilityGate>{children}</CapabilityGate>
          </AppShell>
        </CalendarRuntime>
        </WorkspaceRuntimeBoundary>
      </Suspense>
    </CapabilityAccessProvider>
  );
}
