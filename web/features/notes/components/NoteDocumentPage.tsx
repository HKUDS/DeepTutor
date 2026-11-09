"use client";

import { useEffect, useState, type ComponentType } from "react";
import { useRouter } from "next/navigation";

import ChatNotebookTab from "@/components/chat/home/ChatNotebookTab";
import NoteWorkspace from "@/features/notes/components/NoteWorkspace";
import type { NoteCompanionProps } from "@/features/notes/components/note-companion-props";
import { getNote } from "@/lib/notes-api";

/**
 * One page under Notes, opened in the editor its kind calls for.
 *
 * A "super_note" is a notebook — its Markdown carries fenced code, Mermaid and
 * GeoGebra that the block editor cannot render — so it opens in the notebook
 * editor. Everything else opens in the note editor. The route stays a thin
 * composition; this holds the one lookup that decides which.
 */
export default function NoteDocumentPage({
  docId,
  companion,
}: {
  docId: string;
  companion?: ComponentType<NoteCompanionProps>;
}) {
  const router = useRouter();
  const [resolved, setResolved] = useState<{ docId: string; kind: string } | null>(
    null,
  );

  useEffect(() => {
    if (!docId) return;
    let cancelled = false;
    void getNote(docId)
      .then((page) => {
        if (!cancelled) setResolved({ docId, kind: page.kind || "note" });
      })
      .catch(() => {
        // A page that cannot be read renders in the default editor, which
        // surfaces the error itself.
        if (!cancelled) setResolved({ docId, kind: "note" });
      });
    return () => {
      cancelled = true;
    };
  }, [docId]);

  const kind = !docId
    ? "note"
    : resolved?.docId === docId
      ? resolved.kind
      : null;

  if (kind === "super_note") {
    return (
      <ChatNotebookTab
        key={docId}
        docId={docId}
        onExit={() => router.push("/co-writer")}
      />
    );
  }
  if (kind === null) {
    return <div className="h-dvh w-full bg-[var(--card)]" aria-hidden="true" />;
  }
  return <NoteWorkspace key={docId} docId={docId} companion={companion} />;
}
