import { redirect } from "next/navigation";

/**
 * The workspace root has one destination; sessions live under `/chat`.
 * `next.config.js` redirects `/` before routing, so this page is only a
 * fallback — it stays so links to `/` still resolve to a real page.
 */
export default function WorkspaceRootPage() {
  redirect("/chat");
}
