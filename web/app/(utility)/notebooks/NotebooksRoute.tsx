"use client";

import { Suspense, useCallback, useEffect, useState } from "react";
import { useParams, useSearchParams } from "next/navigation";
import { Loader2 } from "lucide-react";
import NotebookConsole, {
  type NotebookCourseScope,
} from "@/components/notebook/NotebookConsole";
import { listCourses } from "@/lib/courses-api";

// `/notebooks` is the Notebooks console. The Question Bank — a separate
// feature that happens to share the word in its API path — lives at
// `/space/questions`.

function NotebookRoute() {
  const routeParams = useParams<{ notebookId?: string }>();
  const searchParams = useSearchParams();
  const requested = routeParams.notebookId?.trim() || null;
  // A course scope arrives as `/notebooks?course=<id>`, from the course page or
  // a Course Study hand-off. Resolved here rather than in the console so the
  // console stays a pure view over whatever list it is handed.
  const courseId = searchParams.get("course")?.trim() ?? "";
  const [courseScope, setCourseScope] = useState<NotebookCourseScope | null>(
    null,
  );

  // Bumped after the console attaches something, so the scope re-reads and the
  // notebook just created stops looking like it is outside the course.
  const [scopeVersion, setScopeVersion] = useState(0);
  const handleScopeChanged = useCallback(
    () => setScopeVersion((version) => version + 1),
    [],
  );

  useEffect(() => {
    if (!courseId) {
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setCourseScope(null);
      return;
    }
    let cancelled = false;
    void listCourses()
      .then((courses) => {
        if (cancelled) return;
        const course = courses.find((item) => item.id === courseId);
        setCourseScope({
          id: courseId,
          name: course?.name ?? "",
          // A course that references no notebook scopes the list to nothing,
          // which is the honest answer — not "here is everything instead".
          notebookIds: (course?.resources ?? [])
            .filter((resource) => resource.kind === "notebook")
            .map((resource) => resource.ref_id),
        });
      })
      .catch(() => {
        // Scope unknown: show the whole library rather than an empty console.
        if (!cancelled) setCourseScope(null);
      });
    return () => {
      cancelled = true;
    };
  }, [courseId, scopeVersion]);

  return (
    <NotebookConsole
      initialNotebookId={requested}
      courseScope={courseScope}
      onScopeChanged={handleScopeChanged}
    />
  );
}

export default function NotebookPage() {
  return (
    <Suspense
      fallback={
        <div className="flex h-full items-center justify-center">
          <Loader2 className="h-5 w-5 animate-spin text-[var(--muted-foreground)]" />
        </div>
      }
    >
      <NotebookRoute />
    </Suspense>
  );
}
