import { redirect } from "next/navigation";

// Notebooks moved out of the Space document layout to their own full-height
// console at /notebook. This route stays behind so existing links and
// bookmarks keep working; it forwards the `?notebook=<id>` deep link too.
export default async function SpaceNotebooksPage({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const params = await searchParams;
  const requested = params.notebook;
  const notebookId = Array.isArray(requested) ? requested[0] : requested;
  const requestedCourse = params.course;
  const courseId = Array.isArray(requestedCourse)
    ? requestedCourse[0]
    : requestedCourse;

  // Both deep links are forwarded: dropping `?course=` here would silently
  // widen a course-scoped hand-off back to the whole library.
  const query = new URLSearchParams();
  if (notebookId) query.set("notebook", notebookId);
  if (courseId) query.set("course", courseId);
  const search = query.toString();

  redirect(search ? `/notebook?${search}` : "/notebook");
}
