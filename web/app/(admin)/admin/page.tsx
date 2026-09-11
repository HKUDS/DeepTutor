"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { useTranslation } from "react-i18next";
import { fetchAuthStatus } from "@/lib/auth";
import {
  ArrowLeft,
  CreditCard,
  Package,
  Receipt,
  KeyRound,
  Users,
  ShieldCheck,
} from "lucide-react";
import Link from "next/link";

interface AdminCard {
  href: string;
  title: string;
  description: string;
  icon: React.ReactNode;
}

export default function AdminHubPage() {
  const router = useRouter();
  const { t } = useTranslation();
  const [checking, setChecking] = useState(true);

  useEffect(() => {
    fetchAuthStatus().then((status) => {
      if (!status?.authenticated) {
        router.replace("/login");
        return;
      }
      if (status.role !== "admin") {
        router.replace("/");
        return;
      }
      setChecking(false);
    });
  }, [router]);

  if (checking) {
    return (
      <div className="h-screen bg-[var(--background)]" aria-hidden>
        <div className="flex h-full items-center justify-center">
          <div className="h-6 w-6 animate-spin rounded-full border-2 border-[var(--muted)] border-t-[var(--foreground)]" />
        </div>
      </div>
    );
  }

  const cards: AdminCard[] = [
    {
      href: "/admin/users",
      title: t("User Management"),
      description: t("Manage registered accounts and assignments."),
      icon: <Users size={20} />,
    },
    {
      href: "/admin/payment-settings",
      title: t("Payment Settings"),
      description: t("WeChat Pay, EPay gateway and CDK channel configuration."),
      icon: <CreditCard size={20} />,
    },
    {
      href: "/admin/plans",
      title: t("Plan Management"),
      description: t("Pricing plans and the books / KBs / models each unlocks."),
      icon: <Package size={20} />,
    },
    {
      href: "/admin/orders",
      title: t("Order Audit"),
      description: t("All student payments, fulfilment status and refunds."),
      icon: <Receipt size={20} />,
    },
    {
      href: "/admin/cdk",
      title: t("Card Key (CDK) Management"),
      description: t("Batch-generate card keys and export as CSV."),
      icon: <KeyRound size={20} />,
    },
  ];

  return (
    <div className="h-screen overflow-y-auto bg-[var(--background)] px-4 py-10 [scrollbar-gutter:stable]">
      <div className="mx-auto max-w-3xl">
        <div className="mb-8">
          <Link
            href="/"
            className="mb-4 inline-flex items-center gap-1.5 text-sm text-[var(--muted-foreground)] hover:text-[var(--foreground)] transition-colors"
          >
            <ArrowLeft size={16} />
            {t("Back")}
          </Link>
          <div className="flex items-start justify-between gap-4">
            <div>
              <div className="flex items-center gap-2">
                <ShieldCheck size={18} className="text-[var(--muted-foreground)]" />
                <h1 className="font-serif text-xl font-semibold text-[var(--foreground)]">
                  {t("DeepTutor Admin")}
                </h1>
              </div>
              <p className="mt-0.5 text-sm text-[var(--muted-foreground)]">
                {t("Users, payment channels, plans and order ledger.")}
              </p>
            </div>
          </div>
        </div>

        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          {cards.map((card) => (
            <Link
              key={card.href}
              href={card.href}
              className="group flex items-start gap-3 rounded-2xl border border-[var(--border)] bg-[var(--card)] p-5 shadow-sm transition-colors hover:border-[var(--ring)]/50 hover:bg-[var(--background)]/60"
            >
              <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-[var(--muted)]/50 text-[var(--muted-foreground)] group-hover:text-[var(--foreground)]">
                {card.icon}
              </span>
              <div className="min-w-0">
                <p className="text-sm font-semibold text-[var(--foreground)]">
                  {card.title}
                </p>
                <p className="mt-0.5 text-xs leading-relaxed text-[var(--muted-foreground)]">
                  {card.description}
                </p>
              </div>
            </Link>
          ))}
        </div>

        <p className="mt-8 text-center text-xs text-[var(--muted-foreground)]">
          {t("DeepTutor Admin")}
        </p>
      </div>
    </div>
  );
}