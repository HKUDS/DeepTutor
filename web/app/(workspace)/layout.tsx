import WorkspaceSidebar from "@/components/sidebar/WorkspaceSidebar";
import { UnifiedChatProvider } from "@/context/UnifiedChatContext";

export default function WorkspaceLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <UnifiedChatProvider>
      <div className="flex h-[100dvh] overflow-hidden">
        <WorkspaceSidebar />
        <main className="min-w-0 flex-1 overflow-hidden bg-[var(--background)] pb-[calc(72px+env(safe-area-inset-bottom))] md:pb-0">
          {children}
        </main>
      </div>
    </UnifiedChatProvider>
  );
}
