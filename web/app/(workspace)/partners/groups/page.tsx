import { redirect } from "next/navigation";

/**
 * Groups are listed alongside Partners on /partners, so this former index page
 * only keeps existing links and bookmarks working.
 */
export default function PartnerGroupsPage() {
  redirect("/partners");
}
