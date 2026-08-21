"use client";

import { useEffect, type ReactNode } from "react";
import { usePathname, useRouter } from "next/navigation";

import { useAuthStatus } from "@/hooks/useAuthStatus";
import { isEncoreAdminOnlyPath } from "@/lib/encore-admin-nav";

export function AdminOnlyRouteGuard({ children }: { children: ReactNode }) {
  const pathname = usePathname() ?? "";
  const router = useRouter();
  const { enabled, isAdmin, loading } = useAuthStatus();
  const blocked = enabled && !isAdmin && isEncoreAdminOnlyPath(pathname);

  useEffect(() => {
    if (loading) return;
    if (blocked) router.replace("/home");
  }, [loading, blocked, router]);

  if (loading && isEncoreAdminOnlyPath(pathname)) return null;
  if (blocked) return null;
  return <>{children}</>;
}
