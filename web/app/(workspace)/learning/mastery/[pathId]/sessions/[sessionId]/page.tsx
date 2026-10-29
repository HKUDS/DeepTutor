"use client";

import { useParams, useSearchParams } from "next/navigation";

import { MasteryStudy } from "@/components/space/learning/MasteryStudy";

export default function MasteryStudySessionPage() {
  const params = useParams<{ pathId: string; sessionId: string }>();
  const search = useSearchParams();
  const hintedPointId = search.get("point")?.trim() ?? "";

  return (
    <MasteryStudy
      pathId={String(params.pathId || "")}
      routeSessionId={String(params.sessionId || "")}
      hintedPointId={hintedPointId}
    />
  );
}
