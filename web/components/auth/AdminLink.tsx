"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { ShieldCheck } from "lucide-react";
import { fetchAuthStatus, AUTH_ENABLED } from "@/lib/auth";

interface AdminLinkProps {
  collapsed?: boolean;
}

export function AdminLink({ collapsed = false }: AdminLinkProps) {
  const pathname = usePathname();
  const [isAdmin, setIsAdmin] = useState(false);

  useEffect(() => {
    if (!AUTH_ENABLED) return;
    fetchAuthStatus().then((status) => {
      setIsAdmin(status?.role === "admin");
    });
  }, []);

  if (!AUTH_ENABLED || !isAdmin) return null;

  const active = pathname.startsWith("/admin");

  if (collapsed) {
    return (
      <Link
        href="/admin/users"
        className={`rounded-lg p-2 transition-colors
          ${
            active
              ? "bg-[var(--primary)]/10 text-[var(--primary)]"
              : "text-[var(--muted-foreground)] hover:bg-[var(--background)]/50 hover:text-[var(--foreground)]"
          }`}
        aria-label="Admin"
        title="Admin — User Management"
      >
        <ShieldCheck size={16} strokeWidth={1.5} />
      </Link>
    );
  }

  return (
    <Link
      href="/admin/users"
      className={`flex w-full items-center gap-2.5 rounded-lg px-3 py-2 text-[13.5px] transition-colors
        ${
          active
            ? "bg-[var(--primary)]/10 text-[var(--primary)]"
            : "text-[var(--muted-foreground)] hover:bg-[var(--background)]/50 hover:text-[var(--foreground)]"
        }`}
    >
      <ShieldCheck size={16} strokeWidth={1.5} />
      <span>Admin</span>
    </Link>
  );
}
