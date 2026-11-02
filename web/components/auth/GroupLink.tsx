"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import { Users } from "lucide-react";
import { useTranslation } from "react-i18next";
import { apiUrl } from "@/shared/api/client";
import Tooltip from "@/shared/ui/Tooltip";

// The sidebar mounts on every route; cache the answer for the page load.
let cachedLeadsGroup: boolean | null = null;

/**
 * Sidebar entry for people who lead a group.
 *
 * Leads are ordinary users, so this is deliberately not gated on `isAdmin`.
 * A user who leads nothing sees nothing: the endpoint returns only the groups
 * the caller leads.
 */
export function GroupLink({ collapsed = false }: { collapsed?: boolean }) {
  const pathname = usePathname();
  const { t } = useTranslation();
  const [leadsGroup, setLeadsGroup] = useState<boolean>(() => cachedLeadsGroup ?? false);

  useEffect(() => {
    // A cached answer already reached the initial state, so nothing to do.
    if (cachedLeadsGroup !== null) return;
    let cancelled = false;
    // Bare fetch on purpose: importing the group client would pull it into the
    // app shell, which every route pays for and the route budgets measure.
    void fetch(apiUrl("/api/multi-user/groups"))
      .then((response) => (response.ok ? response.json() : null))
      .then((body: { groups?: unknown } | null) => {
        cachedLeadsGroup = Array.isArray(body?.groups) && body.groups.length > 0;
        if (!cancelled) setLeadsGroup(cachedLeadsGroup);
      })
      .catch(() => {
        // Unresolvable: no link. The page still enforces everything server-side.
      });
    return () => {
      cancelled = true;
    };
  }, []);

  if (!leadsGroup) return null;

  const active = pathname.startsWith("/groups");
  const tone = active
    ? "bg-[var(--primary)]/10 text-[var(--primary)]"
    : "text-[var(--muted-foreground)] hover:bg-[var(--background)]/50 hover:text-[var(--foreground)]";

  const link = (
    <Link
      href="/groups"
      aria-label={t("Groups")}
      className={`rounded-lg ${tone} ${
        collapsed
          ? "p-2 transition-colors"
          : "flex w-full items-center gap-2.5 px-3 py-2 text-[13.5px] transition-colors"
      }`}
    >
      <Users size={16} strokeWidth={1.5} />
      {!collapsed && <span>{t("Groups")}</span>}
    </Link>
  );

  if (!collapsed) return link;
  return (
    <Tooltip label={t("Groups")} side="right">
      {link}
    </Tooltip>
  );
}
