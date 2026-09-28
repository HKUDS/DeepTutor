import { CapabilityAccessProvider } from "@/components/access/CapabilityAccessContext";
import CapabilityGate from "@/components/access/CapabilityGate";

/** Settings owns its navigation, independently of the conversation sidebar. */
export default function SettingsRouteLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <CapabilityAccessProvider>
      <CapabilityGate>{children}</CapabilityGate>
    </CapabilityAccessProvider>
  );
}
