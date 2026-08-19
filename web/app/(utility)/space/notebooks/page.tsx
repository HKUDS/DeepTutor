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

  redirect(
    notebookId
      ? `/notebook?notebook=${encodeURIComponent(notebookId)}`
      : "/notebook",
  );
}
