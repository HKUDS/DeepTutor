import type {
  MessageItem,
  MessageAttachment,
} from "@/context/UnifiedChatContext";

function roleHeading(role: MessageItem["role"]): string {
  if (role === "user") return "User";
  if (role === "assistant") return "Assistant";
  return "System";
}

function formatAttachments(attachments?: MessageAttachment[]): string {
  if (!attachments?.length) return "";
  const items = attachments
    .map((a) => {
      const name = a.filename || a.type || "attachment";
      return a.mime_type ? `\`${name}\` (${a.mime_type})` : `\`${name}\``;
    })
    .join(", ");
  return `_Attachments:_ ${items}\n\n`;
}

export interface BuildChatMarkdownOptions {
  title?: string;
  exportedAt?: Date;
}

export function buildChatMarkdown(
  messages: MessageItem[],
  options: BuildChatMarkdownOptions = {},
): string {
  const title = options.title?.trim() || "Chat Session";
  const exportedAt = (options.exportedAt ?? new Date()).toISOString();
  const header = `# ${title}\n\n_Exported: ${exportedAt}_\n\n---\n\n`;
  const body = messages
    .map((msg) => {
      const role = roleHeading(msg.role);
      const cap = msg.capability ? ` _(${msg.capability})_` : "";
      const attachments = formatAttachments(msg.attachments);
      const content = (msg.content ?? "").trim();
      return `## ${role}${cap}\n\n${attachments}${content}`.trimEnd();
    })
    .join("\n\n---\n\n");
  return header + body + "\n";
}

function sanitizeFilename(input: string): string {
  const cleaned = input
    .replace(/[\\/:*?"<>|\n\r\t]/g, "")
    .replace(/\s+/g, "-")
    .slice(0, 60);
  return cleaned || "chat";
}

export function downloadChatMarkdown(
  messages: MessageItem[],
  options: BuildChatMarkdownOptions = {},
): void {
  if (!messages.length) return;
  const markdown = buildChatMarkdown(messages, options);
  const blob = new Blob([markdown], { type: "text/markdown;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  const date = new Date().toISOString().slice(0, 10);
  anchor.download = `${sanitizeFilename(options.title || "chat")}-${date}.md`;
  anchor.click();
  URL.revokeObjectURL(url);
}
