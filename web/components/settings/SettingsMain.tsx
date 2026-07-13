"use client";

import { usePathname } from "next/navigation";

import SettingsBreadcrumb from "@/components/settings/SettingsBreadcrumb";
import { SettingsToolbar } from "@/components/settings/SettingsToolbar";
import { SettingsLoadStatusBanner } from "@/components/settings/SettingsLoadStatusBanner";
import { SETTINGS_HUB_HREF, isNavOnlyRoute } from "@/lib/settings-nav";

// Two-level hub: the dashboard at `/settings` is the entry; categories with
// several settings open a sub-hub, the rest go straight to a leaf. Every page
// below the hub carries a breadcrumb top-left so the user knows where they
// are. The sticky Save Draft / Apply toolbar rides above the scroll area on
// leaf pages only — nav-only pages (hub, sub-hubs) have nothing to save.

export default function SettingsMain({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  const pathname = usePathname() ?? "";
  const isHub = pathname === SETTINGS_HUB_HREF;

  if (isHub) {
    return (
      <div className="h-full overflow-y-auto bg-[var(--background)] [scrollbar-gutter:stable]">
        <div className="mx-auto w-full max-w-5xl px-8 py-8 pb-12">
          {children}
        </div>
      </div>
    );
  }

  const showToolbar = !isNavOnlyRoute(pathname);

  return (
    <div className="flex h-full min-w-0 flex-col overflow-hidden bg-[var(--background)]">
      <div className="mx-auto w-full max-w-5xl px-10 pt-5">
        <SettingsBreadcrumb />
        {showToolbar && (
          <div className="mt-2">
            <SettingsToolbar />
          </div>
        )}
        <SettingsLoadStatusBanner />
      </div>
      {/* Inner scroll container. Sticky elements inside (e.g. the profile-list
          aside in ServiceConfigEditor) anchor to this ancestor instead of the
          outer flex column, so the left column stays put while the right side
          scrolls. ``min-h-0`` is required for the flex child to constrain to
          remaining space — without it, ``overflow-y-auto`` would never clip. */}
      <div className="min-h-0 flex-1 overflow-y-auto overflow-x-hidden [scrollbar-gutter:stable]">
        <div className="mx-auto w-full max-w-5xl px-10 pb-16">
          <div className="mt-4">{children}</div>
        </div>
      </div>
    </div>
  );
}
