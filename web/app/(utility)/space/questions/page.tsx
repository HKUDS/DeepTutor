import { Suspense } from "react";
import { PracticePage } from "@/components/learning/practice/PracticePage";
import { LearningSkeleton } from "@/components/learning/LearningShell";

export default function SpaceQuestionsPage() {
  return (
    <Suspense fallback={<LearningSkeleton />}>
      <PracticePage mode="library" />
    </Suspense>
  );
}
