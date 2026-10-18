import { Suspense } from "react";
import { SequencePage } from "@/components/learning/sequence/SequencePage";
import { LearningSkeleton } from "@/components/learning/LearningShell";

export default function Page() {
  return (
    <Suspense fallback={<LearningSkeleton />}>
      <SequencePage />
    </Suspense>
  );
}
