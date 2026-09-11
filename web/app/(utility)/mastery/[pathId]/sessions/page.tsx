"use client";

import { useParams, useSearchParams } from "next/navigation";

import { MasteryStudy } from "@/components/space/learning/MasteryStudy";
import { normalizeMasteryMode } from "@/lib/mastery-mode";

export default function MasteryStudyPage() {
  const params = useParams<{ pathId: string }>();
  const search = useSearchParams();
  const courseId = search.get("course")?.trim() ?? "";
  // Only consulted when this route opens a *new* conversation; an existing
  // one carries the kind it was opened with.
  const requestedMode = normalizeMasteryMode(search.get("mode"));

  return (
    <MasteryStudy
      pathId={String(params.pathId || "")}
      courseId={courseId}
      requestedMode={requestedMode}
    />
  );
}
