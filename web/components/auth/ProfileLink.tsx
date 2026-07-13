"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useTranslation } from "react-i18next";
import { fetchAuthStatus, type AuthStatus } from "@/lib/auth";
import { UserAvatar } from "@/components/UserAvatar";

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
    />
  );

  if (collapsed) {
    return (
      <Link
        href="/profile"
        className={`rounded-lg p-2 transition-colors
          ${
            active
              ? "bg-[var(--primary)]/10 text-[var(--primary)]"
              : "text-[var(--muted-foreground)] hover:bg-[var(--background)]/50 hover:text-[var(--foreground)]"
          }`}
        aria-label={t("My profile")}
        title={`${t("My profile")} — ${status.username}`}
      >
        {avatar}
      </Link>
    );
  }

  return (
    <Link
      href="/profile"
      className={`flex w-full items-center gap-2.5 rounded-lg px-3 py-2 text-[13.5px] transition-colors
        ${
          active
            ? "bg-[var(--primary)]/10 text-[var(--primary)]"
            : "text-[var(--muted-foreground)] hover:bg-[var(--background)]/50 hover:text-[var(--foreground)]"
        }`}
      title={t("My profile")}
    >
      {avatar}
      <span className="truncate">{status.username}</span>
    </Link>
  );
}
