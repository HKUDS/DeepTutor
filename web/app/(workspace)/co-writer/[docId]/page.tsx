"use client";

import dynamic from "next/dynamic";
import { useParams } from "next/navigation";

import NoteWorkspace from "@/features/notes/components/NoteWorkspace";

const Companion = dynamic(() => import("@/features/notes/components/NoteCompanion"), { ssr: false });

export default function CoWriterPage() {
  const params = useParams<{ docId?: string | string[] }>();
  const rawDocId = params?.docId;
  const docId = Array.isArray(rawDocId)
    ? (rawDocId[0] ?? "")
    : (rawDocId ?? "");

  return <NoteWorkspace key={docId} docId={docId} companion={Companion} />;
}
