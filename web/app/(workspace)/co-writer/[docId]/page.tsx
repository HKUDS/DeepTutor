"use client";

import { useParams } from "next/navigation";

import CoWriterWorkspace from "@/features/co-writer/components/CoWriterWorkspace";

export default function CoWriterPage() {
  const params = useParams<{ docId?: string | string[] }>();
  const rawDocId = params?.docId;
  const docId = Array.isArray(rawDocId)
    ? (rawDocId[0] ?? "")
    : (rawDocId ?? "");

  return <CoWriterWorkspace docId={docId} />;
}
