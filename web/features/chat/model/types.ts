import type {
  StreamEvent,
  TurnQueryState,
  TurnStatus,
} from "@/contracts/generated/turn-protocol";

export interface ChatAttachment {
  id?: string;
  type: string;
  filename?: string;
  mimeType?: string;
  url?: string;
  base64?: string;
  generated?: boolean;
  sizeBytes?: number;
}

export interface ChatRequestSnapshot {
  content: string;
  capability?: string | null;
  tools: string[];
  knowledgeBases: string[];
  language: string;
  attachments?: ChatAttachment[];
  config?: Record<string, unknown>;
}

export interface ChatMessage {
  id: number;
  role: "user" | "assistant" | "system";
  content: string;
  parentMessageId: number | null;
  capability?: string;
  events?: StreamEvent[];
  attachments?: ChatAttachment[];
  requestSnapshot?: ChatRequestSnapshot;
}

export interface ChatSession {
  key: string;
  id: string | null;
  title: string;
  messages: ChatMessage[];
  status: TurnStatus | "idle";
  queryState: TurnQueryState | "idle";
  activeTurnId: string | null;
  lastSeq: number;
  cancellationRequested: boolean;
  selectedBranches: Record<string, number>;
  updatedAt: number;
}

export interface SidebarSessionSummary {
  key: string;
  id: string | null;
  title: string;
  status: TurnStatus | "idle";
  updatedAt: number;
}

export interface ChatSidebarSnapshot {
  revision: number;
  sessions: SidebarSessionSummary[];
}

export interface ChatStoreState {
  activeKey: string | null;
  sessions: Record<string, ChatSession>;
  sidebar: ChatSidebarSnapshot;
}

export type ChatStoreAction =
  | { type: "ensure_session"; key: string }
  | { type: "select_session"; key: string }
  | { type: "remove_session"; key: string }
  | { type: "load_session"; session: ChatSession }
  | {
      type: "add_optimistic_turn";
      key: string;
      user: ChatMessage;
      assistant: ChatMessage;
    }
  | { type: "stream_event"; key: string; event: StreamEvent }
  | {
      type: "turn_status";
      key: string;
      status: TurnStatus;
      queryState?: TurnQueryState;
      turnId?: string | null;
    }
  | { type: "cancel_requested"; key: string }
  | { type: "session_meta"; key: string; title: string }
  | { type: "set_branch"; key: string; parentKey: string; childId: number }
  | { type: "delete_messages"; key: string; ids: number[] }
  | { type: "regenerate_rollback"; key: string; assistant: ChatMessage };
