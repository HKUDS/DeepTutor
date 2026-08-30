"use client";

import { useParams } from "next/navigation";

import { MasteryStudy } from "@/components/space/learning/MasteryStudy";

export default function MasteryStudyPage() {
  const params = useParams<{ pathId: string; sessionId?: string[] }>();
  const routeSessionId = Array.isArray(params.sessionId)
    ? params.sessionId[0]
    : undefined;

  return (
    <MasteryStudy
      pathId={String(params.pathId || "")}
      routeSessionId={routeSessionId}
    />
  );
}
