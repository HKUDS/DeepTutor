import type { ExportableMessage } from "@/lib/chat-export";
import type { PartnerGroupMessage } from "@/lib/partner-groups-api";

/**
 * Adapt a persisted Partner Group transcript to the shared Markdown exporter.
 *
 * Group history calls assistant messages `partner`; the shared exporter calls
 * them `assistant`. Preserve each Partner's visible name so a panel discussion
 * remains attributable after it leaves the app.
 */
export function toPartnerGroupExportMessages(
  messages: PartnerGroupMessage[],
): ExportableMessage[] {
  return messages
    .filter((message) => message.kind !== "round_stopped")
    .map((message) => ({
      role: message.role === "partner" ? "assistant" : "user",
      content: message.content,
      speaker:
        message.role === "partner"
          ? message.author_name.trim() || "Partner"
          : undefined,
    }));
}
