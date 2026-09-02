/** UI-facing aliases for the validated v2 turn protocol. */
export type {
  ClientCommand,
  ServerEvent,
} from "@/contracts/generated/turn-protocol";

export type StreamEventType =
  | "stage_start"
  | "stage_end"
  | "thinking"
  | "observation"
  | "content"
  | "tool_call"
  | "tool_result"
  | "progress"
  | "sources"
  | "result"
  | "error"
  | "session"
  | "session_meta"
  | "wait_for_input"
  | "done";

export interface StreamEvent {
  type: StreamEventType;
  source: string;
  stage: string;
  content: string;
  metadata: Record<string, unknown>;
  session_id?: string;
  turn_id?: string;
  seq?: number;
  timestamp: number;
}

export interface LLMSelection {
  profile_id: string;
  model_id: string;
}

export interface StartTurnMessage {
  type: "start_turn";
  content: string;
  tools?: string[];
  capability?: string | null;
  workspace_mode?: "immersive_reading" | "mastery_path" | "";
  knowledge_bases?: string[];
  session_id?: string | null;
  attachments?: Array<{
    type: string;
    url?: string;
    base64?: string;
    filename?: string;
    mime_type?: string;
  }>;
  language?: string;
  config?: Record<string, unknown>;
  notebook_references?: Array<{ notebook_id: string; record_ids: string[] }>;
  history_references?: string[];
  question_notebook_references?: number[];
  book_references?: Array<{ book_id: string; page_ids: string[] }>;
  reading_references?: Array<{
    material_id: string;
    revision: number;
    locators: number[];
  }>;
  mastery_path_id?: string;
  reading_workspace_id?: string;
  reading_material_id?: string;
  reading_material_revision?: number;
  reading_viewport?: { locator?: number; selection?: string };
  timed_media_id?: string;
  timed_media_viewport?: { time_seconds: number };
  persona?: string;
  llm_selection?: LLMSelection | null;
  parent_message_id?: number | null;
  [key: string]: unknown;
}

export interface SubscribeTurnMessage {
  type: "subscribe_turn";
  turn_id: string;
  after_seq?: number;
}

export interface SubscribeSessionMessage {
  type: "subscribe_session";
  session_id: string;
  after_seq?: number;
}

export interface ResumeTurnMessage {
  type: "resume_from";
  turn_id: string;
  seq?: number;
}

export interface UnsubscribeMessage {
  type: "unsubscribe";
  turn_id?: string;
  session_id?: string;
}

export interface CancelTurnMessage {
  type: "cancel_turn";
  turn_id: string;
}

export interface RegenerateMessage {
  type: "regenerate";
  session_id: string;
  overrides?: Record<string, unknown>;
}

export interface SubmitUserReplyMessage {
  type: "submit_user_reply";
  turn_id: string;
  text?: string;
  answers?: Array<{ questionId: string; text: string }>;
}

export type ChatMessage =
  | StartTurnMessage
  | SubscribeTurnMessage
  | SubscribeSessionMessage
  | ResumeTurnMessage
  | UnsubscribeMessage
  | CancelTurnMessage
  | RegenerateMessage
  | SubmitUserReplyMessage;
