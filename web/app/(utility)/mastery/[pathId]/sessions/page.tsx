"use client";

import { useParams, useSearchParams } from "next/navigation";

import { MasteryStudy } from "@/components/space/learning/MasteryStudy";

export default function MasteryStudyPage() {
  const params = useParams<{ pathId: string }>();
  const courseId = useSearchParams().get("course")?.trim() ?? "";

  return (
    <MasteryStudy
      pathId={String(params.pathId || "")}
      courseId={courseId}
    />
  );
}
