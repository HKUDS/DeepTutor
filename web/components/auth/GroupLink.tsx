"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import { Users } from "lucide-react";
import { useTranslation } from "react-i18next";
import Tooltip from "@/shared/ui/Tooltip";
import { listGroups } from "@/lib/group-api";

// The sidebar mounts on every route; cache the answer so a lead pays for this
// request once per page load rather than once per mount.
let cachedLeadsGroup: boolean | null = null;

interface GroupLinkProps {
  collapsed?: boolean;
}

/**
 * Sidebar entry for people who lead a group.
 *
 * Leads are ordinary users, so this is deliberately not gated on `isAdmin`.
 * A user who leads nothing sees nothing: `listGroups()` returns only the groups
 * the caller leads, which is empty for everyone else.
 */
export function GroupLink({ collapsed = false }: GroupLinkProps) {
  const pathname = usePathname();
  const { t } = useTranslation();
  const [leadsGroup, setLeadsGroup] = useState<boolean>(() => cachedLeadsGroup ?? false);

  useEffect(() => {
    // The initial state already read the cache, so a cached answer needs no
    // extra render here.
    if (cachedLeadsGroup !== null) return;
    let cancelled = false;
    void listGroups()
      .then((groups) => {
        cachedLeadsGroup = groups.length > 0;
        if (!cancelled) setLeadsGroup(cachedLeadsGroup);
      })
      .catch(() => {
        // Someone who cannot be resolved simply gets no link; the page still
        // refuses whatever the server would refuse.
      });
    return () => {
      cancelled = true;
    };
  }, []);

  if (!leadsGroup) return null;

  const active = pathname.startsWith("/groups");

  if (collapsed) {
    return (
      <Tooltip label={t("Groups")} side="right">
        <Link
          href="/groups"
          className={`rounded-lg p-2 transition-colors ${
            active
              ? "bg-[var(--primary)]/10 text-[var(--primary)]"
              : "text-[var(--muted-foreground)] hover:bg-[var(--background)]/50 hover:text-[var(--foreground)]"
          }`}
          aria-label={t("Groups")}
        >
          <Users size={16} strokeWidth={1.5} />
        </Link>
      </Tooltip>
    );
  }

  return (
    <Link
      href="/groups"
      className={`flex w-full items-center gap-2.5 rounded-lg px-3 py-2 text-[13.5px] transition-colors ${
        active
          ? "bg-[var(--primary)]/10 text-[var(--primary)]"
          : "text-[var(--muted-foreground)] hover:bg-[var(--background)]/50 hover:text-[var(--foreground)]"
      }`}
    >
      <Users size={16} strokeWidth={1.5} />
      <span>{t("Groups")}</span>
    </Link>
  );
}
