"use client";

import { usePathname } from "next/navigation";

import { capabilityForPath } from "@/lib/capability-routes";

import { RequireCapability } from "./RequireCapability";

/**
 * Route-level gate: derives the required model capability from the current
 * pathname and locks the page when the user lacks it. Mounted once per authed
 * layout group, so direct-URL access to a gated feature is covered too.
 */
export default function CapabilityGate({
  children,
}: {
  children: React.ReactNode;
}) {
  const pathname = usePathname() ?? "";
  const capability = capabilityForPath(pathname);
  return (
    <RequireCapability capability={capability}>{children}</RequireCapability>
  );
}
