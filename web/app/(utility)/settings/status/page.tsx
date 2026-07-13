import { redirect } from "next/navigation";

// Status was demoted to a resident module on the settings hub. Keep this route
// as a redirect so existing bookmarks/links (and the guided tour fallback)
// still land somewhere sensible.
export default function StatusSettingsPage() {
  redirect("/settings");
}
