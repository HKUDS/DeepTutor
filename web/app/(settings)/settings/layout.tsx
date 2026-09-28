import SettingsMain from "@/components/settings/SettingsMain";
import {
  ModelCatalogProvider,
  SettingsDraftProvider,
  SettingsProvider,
  UiSettingsProvider,
} from "@/features/settings/store";
import { SettingsAccessProvider } from "@/features/settings/navigation/SettingsAccessProvider";
import { SettingsTourOverlay } from "@/components/settings/SettingsTourOverlay";

export default function SettingsLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <SettingsProvider>
      <SettingsAccessProvider>
        <UiSettingsProvider>
          <ModelCatalogProvider>
            <SettingsDraftProvider>
              <SettingsMain>{children}</SettingsMain>
              {/* Mounted once at the layout level so the cross-route guided tour
                  survives navigation between the hub and its sub-pages. */}
              <SettingsTourOverlay />
            </SettingsDraftProvider>
          </ModelCatalogProvider>
        </UiSettingsProvider>
      </SettingsAccessProvider>
    </SettingsProvider>
  );
}
