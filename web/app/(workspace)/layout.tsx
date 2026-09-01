import WorkspaceSidebar from "@/components/sidebar/WorkspaceSidebar";
import AppShell from "@/components/layout/AppShell";
import { CapabilityAccessProvider } from "@/components/access/CapabilityAccessContext";
import CapabilityGate from "@/components/access/CapabilityGate";
import { UnifiedChatProvider } from "@/context/UnifiedChatContext";
import { ReadingProvider } from "@/context/ReadingContext";
import { WatchingProvider } from "@/context/WatchingContext";

export default function WorkspaceLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <CapabilityAccessProvider>
      <UnifiedChatProvider>
        {/* Above the page on purpose: sending the first message navigates
            /home → /home/<id>, which remounts the page. The open document
            must not die with it. */}
        <ReadingProvider>
          <WatchingProvider>
            <AppShell sidebar={<WorkspaceSidebar />}>
              <CapabilityGate>{children}</CapabilityGate>
            </AppShell>
          </WatchingProvider>
        </ReadingProvider>
      </UnifiedChatProvider>
    </CapabilityAccessProvider>
  );
}
