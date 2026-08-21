import UtilitySidebar from "@/components/sidebar/UtilitySidebar";
import AppShell from "@/components/layout/AppShell";
import { AdminOnlyRouteGuard } from "@/components/access/AdminOnlyRouteGuard";
import { CapabilityAccessProvider } from "@/components/access/CapabilityAccessContext";
import CapabilityGate from "@/components/access/CapabilityGate";

export default function UtilityLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <CapabilityAccessProvider>
      <AppShell sidebar={<UtilitySidebar />}>
        <AdminOnlyRouteGuard>
          <CapabilityGate>{children}</CapabilityGate>
        </AdminOnlyRouteGuard>
      </AppShell>
    </CapabilityAccessProvider>
  );
}
