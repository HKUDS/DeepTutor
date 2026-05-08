"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useTranslation } from "react-i18next";
import { SPACE_ITEMS } from "@/lib/space-items";

export default function SpaceMiniNav() {
  const pathname = usePathname();
  const { t } = useTranslation();

  return (
    <aside className="flex h-full w-[248px] shrink-0 flex-col border-r border-[var(--border)] bg-[var(--card)]">
      <div className="px-5 pb-4 pt-6">
        <h1 className="text-[19px] font-semibold leading-tight tracking-tight text-[var(--foreground)]">
          {t("Space")}
        </h1>
        <p className="mt-1.5 text-[12.5px] leading-snug text-[var(--muted-foreground)]/80">
          {t("Your personal learning library.")}
        </p>
      </div>

      <div
        aria-hidden
        className="mx-5 h-px bg-gradient-to-r from-transparent via-[var(--border)] to-transparent"
      />

      <nav className="flex-1 px-2.5 py-3">
        {SPACE_ITEMS.map(({ href, label, description, icon: Icon }) => {
          const active = pathname.startsWith(href);
          return (
            <Link
              key={href}
              href={href}
              title={t(description)}
              className={`group relative flex h-11 items-center gap-3 rounded-md px-3 transition-colors ${
                active
                  ? "bg-[var(--muted)]/70 text-[var(--foreground)]"
                  : "text-[var(--muted-foreground)] hover:bg-[var(--muted)]/40 hover:text-[var(--foreground)]"
              }`}
            >
              {active && (
                <span
                  aria-hidden
                  className="absolute left-0 top-1/2 h-5 w-[2.5px] -translate-y-1/2 rounded-r-full bg-[var(--foreground)]"
                />
              )}
              <Icon
                size={17}
                strokeWidth={active ? 2 : 1.7}
                className="shrink-0"
              />
              <span
                className={`min-w-0 flex-1 truncate text-[14px] leading-none tracking-tight ${
                  active ? "font-medium" : "font-normal"
                }`}
              >
                {t(label)}
              </span>
            </Link>
          );
        })}
      </nav>
    </aside>
  );
}
