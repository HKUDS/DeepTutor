"use client";

import { Suspense } from "react";
import { useParams, useSearchParams } from "next/navigation";
import { Loader2 } from "lucide-react";
import NotebookConsole from "@/components/notebook/NotebookConsole";
import { decodeResourceSegment } from "@/lib/resource-routes";

// `/notebooks` lists the notebooks; `/notebooks/<id>` opens one. The Question Bank — a separate
// feature that happens to share the word in its API path — lives at
// `/space/questions`.

function NotebookRoute() {
  const routeParams = useParams<{ notebookId?: string }>();
  const searchParams = useSearchParams();
  const requested = decodeResourceSegment(routeParams.notebookId);

  return (
    <NotebookConsole
      initialNotebookId={requested}
      initialRecordId={searchParams.get("record")?.trim() || null}
      startCreating={!requested && searchParams.get("create") === "1"}
    />
  );
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
