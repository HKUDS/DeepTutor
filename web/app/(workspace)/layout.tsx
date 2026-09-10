import WorkspaceSidebar from "@/components/sidebar/WorkspaceSidebar";
import AppShell from "@/components/layout/AppShell";
import { CapabilityAccessProvider } from "@/components/access/CapabilityAccessContext";
import CapabilityGate from "@/components/access/CapabilityGate";
import { ChatRuntimeProvider } from "@/features/chat";
import { ReadingProvider } from "@/context/ReadingContext";

export default function WorkspaceLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <CapabilityAccessProvider>
      <ChatRuntimeProvider>
        {/* Above the page on purpose: sending the first message navigates
            /chat → /chat/<id>, which remounts the page. The open document
            must not die with it. */}
        <ReadingProvider>
          <AppShell sidebar={<WorkspaceSidebar />}>
            <CapabilityGate>{children}</CapabilityGate>
          </AppShell>
        </ReadingProvider>
      </ChatRuntimeProvider>
    </CapabilityAccessProvider>
  );
}
