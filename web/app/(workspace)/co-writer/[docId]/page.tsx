"use client";

import dynamic from "next/dynamic";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";

import ChatNotebookTab from "@/components/chat/home/ChatNotebookTab";
import NoteWorkspace from "@/features/notes/components/NoteWorkspace";
import { getNote } from "@/lib/notes-api";

const Companion = dynamic(
  () => import("@/features/notes/components/NoteCompanion"),
  { ssr: false },
);

/**
 * One page under Notes.
 *
 * A "super_note" is a notebook — its Markdown carries fenced code, Mermaid and
 * GeoGebra that the block editor cannot render — so it opens in the notebook
 * editor instead. Everything else opens in the note editor.
 */
export default function CoWriterPage() {
  const params = useParams<{ docId?: string | string[] }>();
  const rawDocId = params?.docId;
  const docId = Array.isArray(rawDocId)
    ? (rawDocId[0] ?? "")
    : (rawDocId ?? "");
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
    return <ChatNotebookTab key={docId} docId={docId} />;
  }
  if (kind === null) {
    return <div className="h-dvh w-full bg-[var(--card)]" aria-hidden="true" />;
  }
  return <NoteWorkspace key={docId} docId={docId} companion={Companion} />;
}
