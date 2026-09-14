"use client";

/**
 * Page-level student guard (review round 3: F7).
 *
 * T039 hid the engineer consoles from the student dashboard, but the four
 * pages themselves stayed reachable by typing the URL. This wrapper renders
 * a friendly placeholder instead — a redirect would bounce students around
 * with no explanation.
 */

import { ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { useAuthStatus } from "@/hooks/useAuthStatus";

export default function StudentGuard({ children }: { children: ReactNode }) {
  const { i18n } = useTranslation();
  const zh = i18n.language?.toLowerCase().startsWith("zh");
  const { role, loading } = useAuthStatus();

  if (loading) {
    return (
      <div className="flex min-h-[40vh] items-center justify-center">
        <div className="h-6 w-6 animate-spin rounded-full border-2 border-[var(--border)] border-t-transparent" />
      </div>
    );
  }

  if (role === "student") {
    return (
      <div className="flex min-h-[40vh] flex-col items-center justify-center gap-2 px-6 text-center">
        <p className="text-[15px] font-medium text-[var(--foreground)]">
          {zh ? "此页面为教师端功能" : "This page is for teachers"}
        </p>
        <p className="text-[13px] text-[var(--muted-foreground)]">
          {zh
            ? "回到主页继续你的学习吧"
            : "Head back home to continue learning"}
        </p>
      </div>
    );
  }

  return <>{children}</>;
}
