import { redirect } from "next/navigation";

// MCP moved out of Settings: servers are now per-account, managed in the Learning
// Space store at /space/mcp — which also hosts the deployment-wide registry this
// page used to be, behind an admin check. Kept as a redirect so shipped links and
// bookmarks still land somewhere real.
export default function McpSettingsRedirect() {
  redirect("/space/mcp");
}
