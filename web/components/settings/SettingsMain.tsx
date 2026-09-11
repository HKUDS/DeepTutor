"use client";

import SettingsNav, {
  SettingsNavCompact,
} from "@/components/settings/SettingsNav";
import { SettingsToolbar } from "@/components/settings/SettingsToolbar";
import { SettingsLoadStatusBanner } from "@/components/settings/SettingsLoadStatusBanner";

/**
 * Settings shell: a persistent navigator on the left, one page on the right.
 *
 * This replaces a hub → sub-hub → leaf walk where the only way to reach a
 * second setting was to climb back to the root. The breadcrumb went with it —
 * the column already shows where you are, and a trail repeating the page title
 * directly above the page title was two lines saying one thing.
 */
export default function SettingsMain({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <div className="flex h-full min-w-0 bg-[var(--background)]">
      <div className="hidden h-full shrink-0 border-r border-[var(--border)]/60 py-5 pl-6 pr-3 md:block">
        <SettingsNav />
      </div>
      <div className="flex h-full min-w-0 flex-1 flex-col overflow-hidden">
        <div className="w-full px-5 pt-5 sm:px-8">
          {/* Below `md` the column is hidden, so this is the only way out of
              the page you landed on. */}
          <div className="mb-2">
            <SettingsNavCompact />
          </div>
          <SettingsToolbar />
          <SettingsLoadStatusBanner />
        </div>
        {/* Inner scroll container. Sticky elements inside (e.g. the profile-list
            aside in ServiceConfigEditor) anchor to this ancestor instead of the
            outer flex column, so the left column stays put while the right side
            scrolls. ``min-h-0`` is required for the flex child to constrain to
            remaining space — without it, ``overflow-y-auto`` would never clip. */}
        <div
          data-settings-scroll
          className="min-h-0 flex-1 overflow-y-auto overflow-x-hidden [scrollbar-gutter:stable]"
        >
          <div className="w-full max-w-3xl px-5 pb-16 pt-2 sm:px-8">
            {children}
          </div>
        </div>
      </div>
    </div>
  );
}
