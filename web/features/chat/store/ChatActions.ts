import type {
  StartTurnCommand,
  StreamEvent,
  TurnStatus,
} from "@/contracts/generated/turn-protocol";
import {
  buildCancelTurn,
  buildRegenerate,
  buildSubmitUserReply,
} from "@/contracts/parse/turn-command";

import type { ChatMessage, ChatSession } from "../model/types";
import type { StartTurnInput } from "../model/start-turn";
import { buildStartTurnInput } from "../controllers/buildStartTurnInput";
import type { TurnRuntimeClient } from "../transport/TurnRuntimeClient";
import type { ChatStore } from "./createChatStore";
import {
  sessionClient,
  type SessionClient,
  type SessionWireDetail,
} from "../api/session-client";

export type TurnRuntimeFactory = (sessionKey: string) => TurnRuntimeClient;

function status(value: unknown): TurnStatus | "idle" {
  return value === "queued" ||
    value === "running" ||
    value === "waiting_input" ||
    value === "completed" ||
    value === "failed" ||
    value === "cancelled"
    ? value
    : "idle";
}

function toSession(detail: SessionWireDetail, fallbackId: string): ChatSession {
  const id = detail.session_id ?? detail.id ?? fallbackId;
  const normalizedStatus = status(detail.status);
  return {
    key: id,
    id,
    title: detail.title,
    messages: detail.messages.map((message) => ({
      id: message.id,
      role: message.role,
      content: message.content,
      capability: message.capability,
      events: (message.events ?? []) as StreamEvent[],
      parentMessageId: message.parent_message_id ?? null,
    })),
    status: normalizedStatus,
    queryState: normalizedStatus,
    activeTurnId: detail.active_turn_id ?? null,
    lastSeq: 0,
    cancellationRequested: false,
    selectedBranches:
      detail.preferences?.selected_branches &&
      typeof detail.preferences.selected_branches === "object"
        ? (detail.preferences.selected_branches as Record<string, number>)
        : {},
    updatedAt: detail.updated_at ?? Date.now(),
  };
}

export class ChatActions {
  private readonly runtimes = new Map<string, TurnRuntimeClient>();

  constructor(
    private readonly store: ChatStore,
    private readonly runtimeFactory: TurnRuntimeFactory,
    private readonly sessions: SessionClient = sessionClient,
  ) {}

  async loadSession(
    sessionId: string,
    signal?: AbortSignal,
  ): Promise<ChatSession> {
    const session = toSession(
      await this.sessions.get(sessionId, signal),
      sessionId,
    );
    this.store.dispatch({ type: "load_session", session });
    return session;
  }

  async renameSession(sessionId: string, title: string): Promise<void> {
    await this.sessions.rename(sessionId, title);
    this.store.dispatch({ type: "session_meta", key: sessionId, title });
  }

  async deleteSession(sessionId: string): Promise<void> {
    await this.sessions.remove(sessionId);
    this.runtime(sessionId).stop();
    this.runtimes.delete(sessionId);
    this.store.dispatch({ type: "remove_session", key: sessionId });
  }

  startTurn(input: {
    sessionKey: string;
    command: StartTurnCommand;
    user: ChatMessage;
    assistant: ChatMessage;
  }): void {
    this.store.dispatch({ type: "ensure_session", key: input.sessionKey });
    this.store.dispatch({
      type: "add_optimistic_turn",
      key: input.sessionKey,
      user: input.user,
      assistant: input.assistant,
    });
    const runtime = this.runtime(input.sessionKey);
    runtime.connect();
    runtime.send(input.command);
  }

  startTurnInput(input: {
    sessionKey: string;
    turn: StartTurnInput;
    user: ChatMessage;
    assistant: ChatMessage;
  }): void {
    this.startTurn({
      sessionKey: input.sessionKey,
      command: buildStartTurnInput(input.turn),
      user: input.user,
      assistant: input.assistant,
    });
  }

  cancelTurn(sessionKey: string): void {
    const session = this.store.getState().sessions[sessionKey];
    if (!session?.activeTurnId) return;
    this.store.dispatch({ type: "cancel_requested", key: sessionKey });
    this.runtime(sessionKey).cancel(buildCancelTurn(session.activeTurnId));
  }

  submitReply(input: {
    sessionKey: string;
    text?: string;
    answers?: Array<{ questionId: string; text: string }>;
  }): void {
    const turnId =
      this.store.getState().sessions[input.sessionKey]?.activeTurnId;
    if (!turnId) return;
    this.runtime(input.sessionKey).send(
      buildSubmitUserReply({ turnId, ...input }),
    );
  }

  regenerate(sessionId: string, overrides?: Record<string, unknown>): void {
    const runtime = this.runtime(sessionId);
    runtime.connect();
    runtime.send(buildRegenerate({ sessionId, overrides }));
  }

  async selectBranch(
    sessionId: string,
    parentKey: string,
    childId: number,
  ): Promise<void> {
    const current =
      this.store.getState().sessions[sessionId]?.selectedBranches ?? {};
    const next = { ...current, [parentKey]: childId };
    this.store.dispatch({
      type: "set_branch",
      key: sessionId,
      parentKey,
      childId,
    });
    await this.sessions.selectBranch(sessionId, next);
  }

  async deleteMessages(
    sessionId: string,
    messageId: number,
    pairedId?: number,
  ): Promise<void> {
    await this.sessions.removeMessage(sessionId, messageId);
    this.store.dispatch({
      type: "delete_messages",
      key: sessionId,
      ids: pairedId === undefined ? [messageId] : [messageId, pairedId],
    });
  }

  close(): void {
    for (const runtime of this.runtimes.values()) runtime.stop();
    this.runtimes.clear();
  }

  private runtime(key: string): TurnRuntimeClient {
    let runtime = this.runtimes.get(key);
    if (!runtime) {
      runtime = this.runtimeFactory(key);
      this.runtimes.set(key, runtime);
    }
    return runtime;
  }
}
