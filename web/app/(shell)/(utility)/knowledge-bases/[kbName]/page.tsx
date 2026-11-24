"use client";

import { Suspense } from "react";
import { Loader2 } from "lucide-react";
import KnowledgePage from "@/components/knowledge/KnowledgePage";

export default function Page() {
  return (
    <Suspense
      fallback={
        <div className="flex min-h-[50vh] items-center justify-center text-[13px] text-[var(--muted-foreground)]">
          <Loader2 className="h-5 w-5 animate-spin" />
        </div>
      }
    >
      <KnowledgePage />
    </Suspense>
  );
}
