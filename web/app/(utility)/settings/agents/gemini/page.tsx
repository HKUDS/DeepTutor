import { redirect } from "next/navigation";

/** Preserve old bookmarks after the Gemini CLI harness was retired. */
export default function RetiredGeminiAgentSettingsPage() {
  redirect("/settings/agents#agent-antigravity");
}
