import { deriveTitle } from "./shared";
import {
  ImportScanError,
  type NormalizedMessage,
  type NormalizedSession,
} from "./types";

type UnknownRecord = Record<string, unknown>;

interface ChatGptNode {
  id: string;
  parent: string | null;
  children: string[];
  message: UnknownRecord | null;
}

interface ChatGptConversation {
  id: string;
  title: string;
  createTime: number;
  updateTime: number;
  currentNode: string;
  mapping: Map<string, ChatGptNode>;
}

const HIDDEN_CONTENT_TYPES = new Set([
  "computer_initialize_state",
  "model_editable_context",
  "thoughts",
  "tether_browsing_display",
  "user_editable_context",
]);

function record(value: unknown): UnknownRecord | null {
  return value !== null && typeof value === "object" && !Array.isArray(value)
    ? (value as UnknownRecord)
    : null;
}

function text(value: unknown): string {
  return typeof value === "string" ? value.trim() : "";
}

function epochSeconds(value: unknown, fallback = 0): number {
  if (typeof value !== "number" || !Number.isFinite(value) || value <= 0) {
    return fallback;
  }
  // Official exports use seconds, but accepting milliseconds makes copied or
  // transformed exports deterministic too.
  return value > 10_000_000_000 ? value / 1000 : value;
}

function stringArray(value: unknown): string[] {
  return Array.isArray(value)
    ? value.filter((item): item is string => typeof item === "string")
    : [];
}

function normalizeNode(id: string, value: unknown): ChatGptNode | null {
  const row = record(value);
  if (!row) return null;
  return {
    // Parent/child pointers reference the mapping key. Prefer it over the
    // embedded message node id so transformed exports cannot break lineage.
    id,
    parent: text(row.parent) || null,
    children: stringArray(row.children),
    message: record(row.message),
  };
}

function normalizeConversation(
  value: unknown,
  fallbackTimestamp: number,
): ChatGptConversation | null {
  const row = record(value);
  if (!row) return null;
  const id = text(row.id) || text(row.conversation_id);
  const rawMapping = record(row.mapping);
  if (!id || !rawMapping) return null;

  const mapping = new Map<string, ChatGptNode>();
  for (const [key, candidate] of Object.entries(rawMapping)) {
    const node = normalizeNode(key, candidate);
    if (node) mapping.set(node.id, node);
  }
  if (!mapping.size) return null;

  const createTime = epochSeconds(row.create_time, fallbackTimestamp);
  const updateTime = epochSeconds(row.update_time, createTime);
  return {
    id: id.slice(0, 256),
    title: text(row.title),
    createTime,
    updateTime,
    currentNode: text(row.current_node),
    mapping,
  };
}

function messageTimestamp(node: ChatGptNode): number {
  return epochSeconds(node.message?.create_time, 0);
}

function terminalNode(conversation: ChatGptConversation): string {
  if (
    conversation.currentNode &&
    conversation.mapping.has(conversation.currentNode)
  ) {
    return conversation.currentNode;
  }

  // Some redacted exports omit current_node. Choose the newest leaf so we
  // still recover one coherent branch instead of interleaving siblings.
  const leaves = [...conversation.mapping.values()].filter(
    (node) => !node.children.some((child) => conversation.mapping.has(child)),
  );
  const candidates = leaves.length
    ? leaves
    : [...conversation.mapping.values()];
  candidates.sort(
    (a, b) =>
      messageTimestamp(b) - messageTimestamp(a) || b.id.localeCompare(a.id),
  );
  return candidates[0]?.id ?? "";
}

function activePath(conversation: ChatGptConversation): ChatGptNode[] {
  const path: ChatGptNode[] = [];
  const seen = new Set<string>();
  let cursor = terminalNode(conversation);
  while (
    cursor &&
    !seen.has(cursor) &&
    path.length <= conversation.mapping.size
  ) {
    seen.add(cursor);
    const node = conversation.mapping.get(cursor);
    if (!node) break;
    path.push(node);
    cursor = node.parent ?? "";
  }
  return path.reverse();
}

function partText(value: unknown): string {
  if (typeof value === "string") return value.trim();
  const item = record(value);
  if (!item) return "";
  return text(item.text) || text(item.content);
}

function messageContent(message: UnknownRecord): string {
  const content = record(message.content);
  if (!content) return "";
  const contentType = text(content.content_type).toLowerCase();
  if (HIDDEN_CONTENT_TYPES.has(contentType)) return "";

  const parts = Array.isArray(content.parts) ? content.parts : [];
  const rendered = parts.map(partText).filter(Boolean).join("\n\n").trim();
  return rendered || text(content.text);
}

function normalizeMessage(node: ChatGptNode): NormalizedMessage | null {
  const message = node.message;
  if (!message) return null;
  const author = record(message.author);
  const role = text(author?.role).toLowerCase();
  if (role !== "user" && role !== "assistant") return null;
  const metadata = record(message.metadata);
  if (metadata?.is_visually_hidden_from_conversation === true) return null;
  const content = messageContent(message);
  if (!content) return null;
  const createdAt = epochSeconds(message.create_time, 0);
  return {
    role,
    content,
    ...(createdAt ? { created_at: createdAt } : {}),
  };
}

function exportedConversations(payload: unknown): unknown[] {
  if (Array.isArray(payload)) return payload;
  const wrapper = record(payload);
  return Array.isArray(wrapper?.conversations) ? wrapper.conversations : [];
}

export function parseChatGptExport(
  payload: unknown,
  fallbackTimestamp = 0,
  onProgress?: (done: number, total: number) => void,
): NormalizedSession[] {
  const rows = exportedConversations(payload);
  if (!rows.length) {
    throw new ImportScanError(
      "invalid_export",
      "The selected file has no ChatGPT conversations",
    );
  }

  const sessions: NormalizedSession[] = [];
  const seenIds = new Set<string>();
  rows.forEach((row, index) => {
    const conversation = normalizeConversation(row, fallbackTimestamp);
    if (conversation && !seenIds.has(conversation.id)) {
      const messages = activePath(conversation)
        .map(normalizeMessage)
        .filter((message): message is NormalizedMessage => message !== null);
      if (messages.length) {
        const firstUser = messages.find((message) => message.role === "user");
        const createdAt =
          conversation.createTime ||
          messages[0]?.created_at ||
          fallbackTimestamp;
        const updatedAt =
          conversation.updateTime || messages.at(-1)?.created_at || createdAt;
        sessions.push({
          external_id: conversation.id,
          title:
            conversation.title.slice(0, 256) ||
            deriveTitle(firstUser?.content ?? "") ||
            "Imported conversation",
          source_cwd: "",
          created_at: createdAt,
          updated_at: Math.max(createdAt, updatedAt),
          messages,
        });
        seenIds.add(conversation.id);
      }
    }
    onProgress?.(index + 1, rows.length);
  });

  if (!sessions.length) {
    throw new ImportScanError(
      "invalid_export",
      "The selected file has no readable ChatGPT conversations",
    );
  }
  return sessions.sort((a, b) => b.updated_at - a.updated_at);
}

export async function parseChatGptExportFile(
  file: File,
  onProgress?: (done: number, total: number) => void,
): Promise<NormalizedSession[]> {
  let payload: unknown;
  try {
    payload = JSON.parse(await file.text()) as unknown;
  } catch {
    throw new ImportScanError(
      "invalid_export",
      "The selected file is not valid JSON",
    );
  }
  return parseChatGptExport(payload, file.lastModified / 1000, onProgress);
}
