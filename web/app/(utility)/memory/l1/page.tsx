"use client";

import { useSearchParams } from "next/navigation";
import { Suspense } from "react";

import MemoryL1Workbench from "@/components/memory/MemoryL1Workbench";

type Surface =
  | "chat"
  | "notebook"
  | "quiz"
  | "kb"
  | "book"
  | "partner"
  | "cowriter";

const VALID_SURFACES: ReadonlySet<Surface> = new Set([
  "chat",
  "notebook",
  "quiz",
  "kb",
  "book",
  "partner",
  "cowriter",
]);

function isSurface(s: string | null): s is Surface {
  return s !== null && (VALID_SURFACES as ReadonlySet<string>).has(s);
}

function MemoryL1PageInner() {
  // Deep-link contract — any footnote rendered in a memory doc links here:
  // ``?ref=notebook:3a563e6f`` or ``?surface=notebook&ref=3a563e6f``.
  const params = useSearchParams();
  const rawRef = params.get("ref");
  const rawSurface = params.get("surface");

  let surface: Surface | undefined;
  let focusRef: string | undefined;

  if (rawRef) {
    if (rawRef.includes(":")) {
      const [pfx, rest] = rawRef.split(":", 2);
      if (isSurface(pfx)) {
        surface = pfx;
        focusRef = `${pfx}:${rest}`;
      }
    } else if (isSurface(rawSurface)) {
      surface = rawSurface;
      focusRef = `${rawSurface}:${rawRef}`;
    }
  } else if (isSurface(rawSurface)) {
    surface = rawSurface;
  }

  return (
    <MemoryL1Workbench initialSurface={surface} initialFocusRef={focusRef} />
  );
}

export default function MemoryL1Page() {
  // useSearchParams requires a Suspense boundary in app-router client pages.
  return (
    <Suspense fallback={<MemoryL1Workbench />}>
      <MemoryL1PageInner />
    </Suspense>
  );
}
