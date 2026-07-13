import { redirect } from "next/navigation";

// The MinerU settings page was generalized into the multi-engine Document
// Parsing page. Keep this route as a redirect so existing bookmarks/links work.
export default function MinerUSettingsRedirect() {
  redirect("/settings/document-parsing");
}
