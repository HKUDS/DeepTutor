import { redirect } from "next/navigation";

/** The workspace root has one destination; sessions live under `/chat`. */
export default function WorkspaceRootPage() {
  redirect("/chat");
}
