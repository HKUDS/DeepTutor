"use client";

import { notFound, useParams, useSearchParams } from "next/navigation";
import { Suspense } from "react";

import MemoryWorkbench from "@/components/memory/MemoryWorkbench";

const SURFACES = [
  "chat",
  "notebook",
  "quiz",
  "kb",
  "book",
  "partner",
  "cowriter",
];

function L2WorkbenchInner() {
  // ``?focus=m_xxx`` is the deep-link contract used by the resolver
  // page when the user clicks an L3 footnote — scroll the matching
  // bullet into view + flash it.
  const params = useParams<{ surface: string }>();
  const search = useSearchParams();
  const surface = params?.surface;
  if (!surface || !SURFACES.includes(surface)) {
    notFound();
  }
  const focus = search.get("focus") || undefined;
  return (
    <MemoryWorkbench layer="L2" initialKey={surface} initialFocus={focus} />
  );
}

export default function MemoryL2WorkbenchPage() {
  return (
    <Suspense fallback={null}>
      <L2WorkbenchInner />
    </Suspense>
  );
}
