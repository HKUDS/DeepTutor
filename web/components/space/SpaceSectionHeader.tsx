"use client";

import { type ReactNode } from "react";
import { usePathname } from "next/navigation";
import type { LucideIcon } from "lucide-react";
import { PageHeader } from "@/components/layout/FeaturePage";
import { ALL_ITEMS } from "@/components/space/dashboard-groups";

interface SpaceSectionHeaderProps {
  title: string;
  description: string;
  action?: ReactNode;
  meta?: ReactNode;
  level?: 1 | 2;
  /** Defaults to the icon this section wears on the /space hub. */
  icon?: LucideIcon;
}

export default function SpaceSectionHeader({
  title,
  description,
  action,
  meta,
  level,
  icon,
}: SpaceSectionHeaderProps) {
  // usePathname is null outside the App Router (tests, embeds).
  const pathname = usePathname() ?? "";
  const hubIcon = ALL_ITEMS.find((item) => item.href === pathname)?.icon;
  return (
    <PageHeader title={title} description={description} action={action} meta={meta} level={level} icon={icon ?? hubIcon} />
  );
}
