"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useTranslation } from "react-i18next";
import { ShieldCheck, Users } from "lucide-react";
import { PRODUCT_NAME_FA } from "@/lib/brand";
import { fetchAuthStatus } from "@/lib/auth";

/**
 * The admin landing page.
 *
 * Phase 1 builds exactly one real admin surface — user management — so this
 * page is a small index that says so, rather than a dashboard of invented
 * metrics. `ROADMAP.md` is explicit that Phase 1 "has no right to present
 * placeholders as completed features", and F-1 says the same: unbuilt things
 * appear as explicit "coming soon", never as a fake API.
 *
 * The panels below are therefore described as *not built*, with the phase that
 * owns them, so an operator reading this knows the difference between "empty"
 * and "not implemented".
 */
export default function AdminHomePage() {
  const { t } = useTranslation();
  const router = useRouter();
  const [ready, setReady] = useState(false);

  // The middleware already refused non-admins; this keeps the page from
  // flashing content on a direct client-side navigation that bypassed it.
  useEffect(() => {
    let alive = true;
    fetchAuthStatus().then((status) => {
      if (!alive) return;
      if (!status?.authenticated) {
        router.replace("/admin/login");
        return;
      }
      if (status.role !== "admin") {
        router.replace("/");
        return;
      }
      setReady(true);
    });
    return () => {
      alive = false;
    };
  }, [router]);

  if (!ready) {
    return (
      <div className="min-h-screen flex items-center justify-center text-sm text-[var(--muted-foreground)]">
        {t("Loading…")}
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-3xl px-6 py-16">
      <div className="flex items-center gap-2.5 mb-2">
        <ShieldCheck size={20} strokeWidth={1.7} className="text-[var(--primary)]" />
        <span className="text-xs font-medium uppercase tracking-wider text-[var(--muted-foreground)]">
          {t("Administration")}
        </span>
      </div>
      <h1 className="font-serif text-3xl font-semibold text-[var(--foreground)] tracking-tight">
        {PRODUCT_NAME_FA}
      </h1>

      <div className="mt-10 space-y-3">
        <Link
          href="/admin/users"
          className="flex items-start gap-4 rounded-2xl border border-[var(--border)] bg-[var(--card)] px-6 py-5 hover:border-[var(--primary)] transition-colors"
        >
          <Users size={20} strokeWidth={1.7} className="mt-0.5 text-[var(--primary)]" />
          <span>
            <span className="block font-medium text-[var(--foreground)]">
              {t("Users")}
            </span>
            <span className="mt-0.5 block text-sm text-[var(--muted-foreground)]">
              {t("Create accounts, assign roles and reset passwords.")}
            </span>
          </span>
        </Link>

        {[
          {
            title: t("Educational catalog"),
            body: t("Courses, books and question banks arrive with Phase 3."),
          },
          {
            title: t("Models and providers"),
            body: t("Provider configuration is part of Phase 4."),
          },
          {
            title: t("Plans and usage"),
            body: t("Billing and quota management are part of Phase 5."),
          },
          {
            title: t("Security and audit"),
            body: t("Audit trails are part of Phase 6."),
          },
        ].map((panel) => (
          <div
            key={panel.title}
            className="flex items-start gap-4 rounded-2xl border border-dashed border-[var(--border)] px-6 py-5"
          >
            <span className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full bg-[var(--muted-foreground)]" />
            <span>
              <span className="flex flex-wrap items-center gap-2">
                <span className="font-medium text-[var(--muted-foreground)]">
                  {panel.title}
                </span>
                {/* The one honest label for an unbuilt feature. */}
                <span className="rounded-full bg-[var(--muted)] px-2 py-0.5 text-[11px] font-medium text-[var(--muted-foreground)]">
                  {t("Coming soon")}
                </span>
              </span>
              <span className="mt-0.5 block text-sm text-[var(--muted-foreground)]">
                {panel.body}
              </span>
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}
