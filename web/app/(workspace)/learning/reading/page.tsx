import { Suspense } from "react";

import { ReadingLibraryPage } from "@/components/reading/library/ReadingLibrary";

// The library reads `?course=` to scope itself, and `useSearchParams` needs a
// Suspense boundary above it or the whole route opts out of static rendering.
export default function ImmersiveReadingLibraryRoute() {
  return (
    <Suspense fallback={null}>
      <ReadingLibraryPage />
    </Suspense>
  );
}
