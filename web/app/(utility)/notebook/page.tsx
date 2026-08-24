"use client";

import { Suspense } from "react";
import { useSearchParams } from "next/navigation";
import { Loader2 } from "lucide-react";
import NotebookConsole from "@/components/notebook/NotebookConsole";

// `/notebook` is the Notebooks console. The Question Bank — a separate
// feature that happens to share the word in its API path — lives at
// `/space/questions`.

function NotebookRoute() {
  const searchParams = useSearchParams();
  // Deep links from Memory arrive as `/notebook?notebook=<id>`.
  const requested = searchParams.get("notebook");

  return <NotebookConsole initialNotebookId={requested} />;
}

export default function NotebookPage() {
  return (
    <Suspense
      fallback={
        <div className="flex h-full items-center justify-center">
          <Loader2 className="h-5 w-5 animate-spin text-[var(--muted-foreground)]" />
        </div>
      }
    >
      <NotebookRoute />
    </Suspense>
  );
}
