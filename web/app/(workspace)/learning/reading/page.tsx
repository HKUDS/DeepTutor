import { Suspense } from "react";

import { ReadingLibraryPage } from "@/components/reading/library/ReadingLibrary";

export default function ImmersiveReadingLibraryRoute() {
  return (
    <Suspense fallback={null}>
      <ReadingLibraryPage />
    </Suspense>
  );
}
