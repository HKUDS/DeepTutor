"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useTranslation } from "react-i18next";
import { fetchAuthStatus, type AuthStatus } from "@/lib/auth";
import { UserAvatar } from "@/components/UserAvatar";
import Tooltip from "@/shared/ui/Tooltip";

interface ProfileLinkProps {
  collapsed?: boolean;
}

export function ProfileLink({ collapsed = false }: ProfileLinkProps) {
  const pathname = usePathname();
  const { t } = useTranslation();
  const [status, setStatus] = useState<AuthStatus | null>(null);

  useEffect(() => {
    fetchAuthStatus().then((next) => {
      // Only surface the link when auth is on AND the user is signed in.
      if (next?.enabled && next?.authenticated) setStatus(next);
    });
  }, []);

  if (!status?.username) return null;

  const active = pathname.startsWith("/profile");
  const avatar = (
    <UserAvatar
      username={status.username}
      userId={status.user_id}
      avatar={status.avatar}
      role={status.role}
      size={collapsed ? 18 : 16}
      suppressTitle
    />
  );

  if (collapsed) {
    return (
      <Tooltip label={`${t("My profile")} — ${status.username}`} side="right">
        <Link
          href="/profile"
          className={`rounded-lg p-2 transition-colors
            ${
              active
                ? "bg-[var(--primary)]/10 text-[var(--primary)]"
                : "text-[var(--muted-foreground)] hover:bg-[var(--background)]/50 hover:text-[var(--foreground)]"
            }`}
          aria-label={t("My profile")}
        >
          {avatar}
        </Link>
      </Tooltip>
    );
  }

  return (
    <Tooltip label={t("My profile")} as="div" className="w-full" side="right">
      <Link
        href="/profile"
        className={`flex w-full items-center gap-2.5 rounded-lg px-3 py-2 text-[13.5px] transition-colors
          ${
            active
              ? "bg-[var(--primary)]/10 text-[var(--primary)]"
              : "text-[var(--muted-foreground)] hover:bg-[var(--background)]/50 hover:text-[var(--foreground)]"
          }`}
      >
        {avatar}
        <span className="truncate">{status.username}</span>
      </Link>
    </Tooltip>
  );
}
