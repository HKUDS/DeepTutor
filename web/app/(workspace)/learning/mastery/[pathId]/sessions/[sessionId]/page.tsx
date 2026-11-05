"use client";

import { useParams } from "next/navigation";

import { MasteryStudy } from "@/components/space/learning/MasteryStudy";

export default function MasteryStudySessionPage() {
  const params = useParams<{ pathId: string; sessionId: string }>();

  return (
    <MasteryStudy
      pathId={String(params.pathId || "")}
      routeSessionId={String(params.sessionId || "")}
    />
  );
}
