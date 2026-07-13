"use client";

import { notFound, useParams, useSearchParams } from "next/navigation";
import { Suspense } from "react";

import MemoryWorkbench from "@/components/memory/MemoryWorkbench";

const SLOTS = ["recent", "profile", "scope"];

function L3WorkbenchInner() {
  const params = useParams<{ slot: string }>();
  const search = useSearchParams();
  const slot = params?.slot;
  if (!slot || !SLOTS.includes(slot)) {
    notFound();
  }
  // L3 docs don't currently surface ?focus targets directly — but keep
  // the param plumbed for symmetry (and so future resolver hops to L3
  // entries work without another patch).
  const focus = search.get("focus") || undefined;
  return <MemoryWorkbench layer="L3" initialKey={slot} initialFocus={focus} />;
}

export default function MemoryL3WorkbenchPage() {
  return (
    <Suspense fallback={null}>
      <L3WorkbenchInner />
    </Suspense>
  );
}
