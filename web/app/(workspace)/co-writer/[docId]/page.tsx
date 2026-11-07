"use client";

import dynamic from "next/dynamic";
import { useParams } from "next/navigation";

import NoteDocumentPage from "@/features/notes/components/NoteDocumentPage";

const Companion = dynamic(() => import("@/features/notes/components/NoteCompanion"), {
  ssr: false,
});

export default function CoWriterPage() {
  const params = useParams<{ docId?: string | string[] }>();
  const raw = params?.docId;
  const docId = Array.isArray(raw) ? (raw[0] ?? "") : (raw ?? "");
  return <NoteDocumentPage key={docId} docId={docId} companion={Companion} />;
}
