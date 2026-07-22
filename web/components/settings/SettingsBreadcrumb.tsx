"use client";

import { Fragment } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { ChevronRight } from "lucide-react";
import { useTranslation } from "react-i18next";

import { breadcrumbFor, type Lang } from "@/lib/settings-nav";

// Top-left location trail, e.g. 设置 / 模型 / LLM. Earlier crumbs are links;
// the current page is plain text. Replaces the old single "back" link so the
// user always knows where they are inside Settings and can jump up a level.
export default function SettingsBreadcrumb() {
  const pathname = usePathname() ?? "";
  const { t, i18n } = useTranslation();
  const zh = i18n.language?.toLowerCase().startsWith("zh");
  const tr = (l: Lang) => (zh ? l.zh : l.en);

  const crumbs = breadcrumbFor(pathname);

  return (
    <nav
      aria-label={t("Breadcrumb")}
      className="flex items-center gap-1 text-[12.5px] text-[var(--muted-foreground)]"
    >
      {crumbs.map((crumb, i) => {
        const last = i === crumbs.length - 1;
        return (
          <Fragment key={`${crumb.label.en}-${i}`}>
            {i > 0 && (
              <ChevronRight
                size={13}
                strokeWidth={1.8}
                className="shrink-0 text-[var(--muted-foreground)]/40"
              />
            )}
            {crumb.href && !last ? (
              <Link
                href={crumb.href}
                className="rounded px-0.5 transition-colors hover:text-[var(--foreground)]"
              >
                {tr(crumb.label)}
              </Link>
            ) : (
              <span
                className={
                  last
                    ? "px-0.5 font-medium text-[var(--foreground)]"
                    : "px-0.5"
                }
              >
                {tr(crumb.label)}
              </span>
            )}
          </Fragment>
        );
      })}
    </nav>
  );
}
