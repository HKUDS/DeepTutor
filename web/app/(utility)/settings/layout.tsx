import SettingsMain from "@/components/settings/SettingsMain";
import { SettingsProvider } from "@/components/settings/SettingsContext";
import { SettingsTourOverlay } from "@/components/settings/SettingsTourOverlay";

export default function SettingsLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <SettingsProvider>
      <SettingsMain>{children}</SettingsMain>
      {/* Mounted once at the layout level so the cross-route guided tour
          survives navigation between the hub and its sub-pages. */}
      <SettingsTourOverlay />
    </SettingsProvider>
  );
}
