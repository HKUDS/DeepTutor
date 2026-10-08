"use client";

import { type ReactNode } from "react";
import { PageHeader } from "@/components/layout/FeaturePage";

interface SpaceSectionHeaderProps {
  title: string;
  description: string;
  action?: ReactNode;
  meta?: ReactNode;
  level?: 1 | 2;
}

export default function SpaceSectionHeader({
  title,
  description,
  action,
  meta,
  level,
}: SpaceSectionHeaderProps) {
  return (
    <PageHeader title={title} description={description} action={action} meta={meta} level={level} />
  );
}
