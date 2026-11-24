import type { ServerEvent } from '@/contracts/generated/turn-protocol';
import {
  buildCancelTurn,
  buildStartTurn,
  buildSubmitUserReply,
  buildUnsubscribe,
  newCommandId,
} from '@/contracts/parse/turn-command';
import { parseTurnEvent } from '@/contracts/parse/turn-event';
import { NO_LLM_ACCESS } from '@/features/chat/model/protocol';
import {
  TurnRuntimeClient,
  type RuntimeConnectionState,
} from '@/features/chat/transport/TurnRuntimeClient';
import {
  browserSocketFactory,
  type SocketMessageEvent,
  type TurnSocketFactory,
} from '@/features/chat/transport/socket';
import { shouldAppendEventContent } from '@/lib/stream';

type ChatPhase = 'ready' | 'running' | 'waiting' | 'stopping';
type ChatMessage = { id: string; question: string; answer: string };
type ChatState = {
  connection: RuntimeConnectionState;
  messages: ChatMessage[];
  phase: ChatPhase;
  waitingPrompt: string | null;
  canLeaveTurn: boolean;
  error: string | null;
};
type ChatOptions = {
  origin: string;
  socketFactory?: TurnSocketFactory;
  onAuthExpired?: () => void;
  refreshAuth?: () => Promise<boolean>;
};
type ActiveTurn = {
  messageId: string;
  turnId: string | null;
  replying: boolean;
  cancelRequested: boolean;
  cancelSent: boolean;
  replayRetries: number;
  terminal?: { error?: string };
  idleRecovery?: boolean;
};
type Timer = ReturnType<typeof setTimeout>;

const ACK_TIMEOUT_MS = 30_000;
const MAX_REPLAY_RETRIES = 3;
const START_TIMEOUT_MS = 30_000;
const SOCKET_OPEN_TIMEOUT_MS = 12_000;
const TURN_IDLE_TIMEOUT_MS = 60_000;
const TURN_RECOVERY_TIMEOUT_MS = 30_000;
const AUTH_PROBE_INTERVAL_MS = 5_000;
const START_ERRORS = new Set([
  'start_turn_rejected',
  NO_LLM_ACCESS,
  'invalid_command',
  'invalid_json',
  'unsupported_protocol_version',
  'unknown_message_type',
  'internal_error',
]);

function initialState(): ChatState {
  return {
    connection: 'idle',
    messages: [],
    phase: 'ready',
    waitingPrompt: null,
    canLeaveTurn: false,
    error: null,
  };
}

export class MobileChatRuntime {
  private state = initialState();
  private readonly listeners = new Set<() => void>();
  private readonly retiredTurnIds = new Set<string>();
  private client: TurnRuntimeClient | null = null;
  private active: ActiveTurn | null = null;
  private sessionId: string | undefined;
  private timer: Timer | undefined;
  private replayTimer: Timer | undefined;
  private idleTimer: Timer | undefined;
  private visible = true;
  private authProbe: Promise<boolean> | undefined;
  private nextAuthProbeAt = 0;

  constructor(private readonly options: ChatOptions) {}

  getSnapshot = () => this.state;

  subscribe = (listener: () => void) => {
    this.listeners.add(listener);
    return () => {
      this.listeners.delete(listener);
    };
  };

  start(visible = true) {
    this.visible = visible;
    if (!this.client) this.openTransport();
  }

  stop() {
    this.clearStartTimeout();
    this.clearReplayRetry();
    this.clearIdleTimer();
    this.active = null;
    this.sessionId = undefined;
    this.retiredTurnIds.clear();
    this.closeTransport();
    this.update({ ...initialState(), connection: 'stopped' });
  }

  setVisible(visible: boolean) {
    const resumed = visible && !this.visible;
    this.visible = visible;
    if (!visible) this.clearIdleTimer();
    const client = this.client;
    if (!client) return;
    // A socket can still report OPEN after Android/iOS has suspended the app
    // and the route has changed. Reopen it and replay from the live cursor.
    if (resumed && client.state === 'connected') client.manualRetry();
    client.setPageVisible(visible);
    if (resumed && this.active) this.watchTurn(this.active);
  }

  retryConnection = () => {
    if (!this.visible) return;
    this.clearReplayRetry();
    if (this.active) {
      this.active.replayRetries = 0;
      this.active.idleRecovery = false;
      this.watchTurn(this.active);
    }
    this.update({ error: null });
    this.client?.manualRetry();
  };

  reset = () => {
    if (this.active && !this.state.canLeaveTurn) return;
    this.active = null;
    this.clearIdleTimer();
    this.clearStartTimeout();
    this.clearReplayRetry();
    this.sessionId = undefined;
    this.closeTransport();
    // Keep previously seen turn IDs fenced off until the old socket is gone.
    this.retiredTurnIds.clear();
    this.update(initialState());
    this.openTransport();
  };

  send = (text: string): boolean => {
    const question = text.trim();
    if (!question || this.active || this.client?.state !== 'connected') {
      return false;
    }
    const messageId = newCommandId();
    const active: ActiveTurn = {
      messageId,
      turnId: null,
      replying: false,
      cancelRequested: false,
      cancelSent: false,
      replayRetries: 0,
    };
    this.active = active;
    this.update({
      messages: [
        ...this.state.messages,
        { id: messageId, question, answer: '' },
      ],
      phase: 'running',
      canLeaveTurn: false,
      error: null,
    });
    this.timer = setTimeout(() => {
      if (this.active !== active || active.turnId) return;
      this.finishTurn(
        'The server did not confirm the request. Check your connection and try again.',
      );
      // The transport can replay this durable command until it is admitted.
      // Dispose that queue so the timed-out request cannot start later.
      this.closeTransport();
      this.openTransport();
    }, START_TIMEOUT_MS);
    try {
      this.client.send(
        buildStartTurn({
          capability: 'chat',
          content: question,
          client_submission_id: messageId,
          ...(this.sessionId ? { session_id: this.sessionId } : {}),
        }),
      );
      return true;
    } catch {
      this.finishTurn('Unable to send this message. Check your connection.');
      this.closeTransport();
      this.openTransport();
      return false;
    }
  };

  cancel = async (): Promise<void> => {
    const active = this.active;
    if (!active || active.cancelRequested) return;
    active.cancelRequested = true;
    this.update({ phase: 'stopping', error: null });
    // If the user's request was just sent, wait for its first stream event
    // (which contains the turn ID) or the bounded admission timeout.
    if (active.turnId) await this.cancelAdmittedTurn(active);
  };

  reply = async (value: string): Promise<boolean> => {
    const text = value.trim();
    const active = this.active;
    if (
      !text ||
      !active?.turnId ||
      active.replying ||
      this.state.phase !== 'waiting' ||
      this.client?.state !== 'connected'
    ) {
      return false;
    }
    active.replying = true;
    const prompt = this.state.waitingPrompt;
    this.update({ phase: 'running', waitingPrompt: null, error: null });
    this.watchTurn(active);
    try {
      const accepted = await this.client.sendAwaitingAck(
        buildSubmitUserReply({ turnId: active.turnId, text }),
      );
      if (!accepted && this.active === active) {
        this.finishTurn('That question is no longer waiting for a reply.');
      }
      return accepted;
    } catch {
      if (
        this.active === active &&
        !active.cancelRequested &&
        this.getSnapshot().phase === 'running'
      ) {
        this.update({
          phase: 'waiting',
          waitingPrompt: prompt,
          error:
            'Could not confirm your reply. Check your connection and try again.',
        });
        this.watchTurn(active);
      }
      return false;
    } finally {
      active.replying = false;
    }
  };

  private async cancelAdmittedTurn(active: ActiveTurn) {
    const client = this.client;
    if (!client || !active.turnId || active.cancelSent) return;
    active.cancelSent = true;
    try {
      const accepted = await client.sendAwaitingAck(
        buildCancelTurn(active.turnId),
      );
      if (this.active !== active) return;
      if (accepted) {
        this.finishTurn(active.terminal?.error);
        return;
      }
    } catch {
      // Delivery can time out while the owner is still unwinding.
    }
    if (this.active === active) {
      if (active.terminal) {
        // The server observed a terminal frame, but ownership release is
        // unconfirmed. A subsequent question must use a new session.
        this.sessionId = undefined;
        this.finishTurn(active.terminal.error);
        return;
      }
      active.cancelRequested = false;
      active.cancelSent = false;
      this.update({
        phase: this.state.waitingPrompt ? 'waiting' : 'running',
        error: 'Could not confirm the stop request. Try Stop again.',
        canLeaveTurn: true,
      });
    }
  }

  private openTransport() {
    const factory = this.options.socketFactory ?? browserSocketFactory;
    const client = new TurnRuntimeClient({
      url: this.options.origin.replace(/^http/, 'ws') + '/ws?dt_workspace=',
      socketFactory: url => {
        const socket = factory(url);
        let opened = false;
        let closedByClient = false;
        let timedOut = false;
        let handleTimeout: ((event: SocketMessageEvent) => void) | undefined;
        const openDeadline = setTimeout(() => {
          timedOut = true;
          handleTimeout?.({ data: undefined });
          if (this.client === client) this.checkAuth();
          socket.close();
        }, SOCKET_OPEN_TIMEOUT_MS);
        // Keep the shared replay cursor from being changed by frames for a
        // retired turn, or by a second turn while another one is active.
        return {
          get readyState() {
            return socket.readyState;
          },
          send: data => socket.send(data),
          close: (code, reason) => {
            closedByClient = true;
            clearTimeout(openDeadline);
            socket.close(code, reason);
          },
          addEventListener: (type, listener) => {
            if (type === 'close') handleTimeout = listener;
            socket.addEventListener(type, event => {
              if (timedOut) {
                if (type === 'open') socket.close();
                return;
              }
              if (type === 'open' || type === 'close')
                clearTimeout(openDeadline);
              if (type === 'open') opened = true;
              if (type === 'message') {
                const parsed = parseTurnEvent(event.data);
                if (parsed.ok) {
                  if (this.acceptFrame(parsed.value))
                    listener({ data: parsed.value });
                  return;
                }
              }
              if (
                type === 'close' &&
                !closedByClient &&
                this.client === client
              ) {
                const close = event as typeof event & { code?: number };
                if (close.code === 4001 || close.code === 4401) {
                  this.options.onAuthExpired?.();
                } else if (!opened || close.code !== 1000) {
                  this.checkAuth();
                }
              }
              listener(event);
            });
          },
        };
      },
      commandAckTimeoutMs: ACK_TIMEOUT_MS,
      onEvent: event => {
        if (this.client === client) this.onEvent(event);
      },
      onStateChange: connection => {
        if (this.client === client) {
          this.update({
            connection,
            ...(connection === 'idle' && this.active?.turnId
              ? { canLeaveTurn: true }
              : {}),
          });
        }
      },
    });
    this.client = client;
    client.setPageVisible(this.visible);
    if (this.visible) client.connect();
  }

  private closeTransport() {
    const client = this.client;
    this.client = null;
    client?.stop();
  }

  private checkAuth() {
    if (
      !this.visible ||
      !this.options.refreshAuth ||
      this.authProbe ||
      Date.now() < this.nextAuthProbeAt
    )
      return;
    this.nextAuthProbeAt = Date.now() + AUTH_PROBE_INTERVAL_MS;
    const client = this.client;
    this.authProbe = Promise.resolve().then(() => {
      if (this.client !== client) return true;
      return this.options.refreshAuth?.() ?? true;
    });
    this.authProbe
      .catch(() => {})
      .finally(() => {
        this.authProbe = undefined;
      });
  }

  private acceptFrame(event: ServerEvent) {
    if (!('timestamp' in event)) return event.type !== 'active_turn_info';
    const active = this.active;
    const turnId = event.turn_id;
    return Boolean(
      active &&
        turnId &&
        !this.retiredTurnIds.has(turnId) &&
        (!active.turnId || active.turnId === turnId) &&
        (!this.sessionId ||
          !event.session_id ||
          this.sessionId === event.session_id),
    );
  }

  private onEvent(event: ServerEvent) {
    const active = this.active;
    if (!active) return;
    if (event.type === 'protocol_error') {
      if (
        (event.turn_id && event.turn_id !== active.turnId) ||
        (event.session_id &&
          this.sessionId &&
          event.session_id !== this.sessionId)
      ) {
        return;
      }
      if (
        event.error_code === 'subscription_failed' &&
        active.turnId &&
        event.turn_id === active.turnId
      ) {
        const error = 'The connection could not recover this response.';
        if (event.retryable) this.retryReplay(active, error);
        else this.finishTurn(error);
      } else if (START_ERRORS.has(event.error_code) && !active.turnId) {
        this.finishTurn(
          event.error_code === NO_LLM_ACCESS
            ? 'Your account does not have access to a model.'
            : 'The server rejected the request.',
        );
        // The shared runtime only drops the durable start when it observes a
        // stream event. Remove rejected commands by replacing the transport.
        this.closeTransport();
        this.openTransport();
      } else {
        this.update({
          error: 'The connection could not recover this response.',
        });
      }
      return;
    }
    if (!('timestamp' in event) || !event.turn_id || !this.acceptFrame(event))
      return;
    if (!active.turnId) {
      active.turnId = event.turn_id;
      this.clearStartTimeout();
    }
    if (event.session_id) this.sessionId = event.session_id;
    active.idleRecovery = false;
    if (this.state.canLeaveTurn)
      this.update({ canLeaveTurn: false, error: null });
    if (active.replayRetries || this.replayTimer !== undefined) {
      active.replayRetries = 0;
      this.clearReplayRetry();
      this.update({ connection: this.client?.state ?? 'idle', error: null });
    }
    switch (event.type) {
      case 'content':
        if (
          shouldAppendEventContent({
            ...event,
            source: event.source ?? '',
            stage: event.stage ?? '',
            content: event.content ?? '',
            metadata: event.metadata ?? {},
          })
        )
          this.updateAnswer(active, event.content ?? '', false);
        break;
      case 'result':
        if (typeof event.metadata?.response === 'string') {
          this.updateAnswer(active, event.metadata.response, true);
        }
        break;
      case 'wait_for_input':
        this.update({
          phase: active.cancelRequested ? 'stopping' : 'waiting',
          waitingPrompt:
            event.content || 'DeepTutor needs a reply to continue.',
        });
        break;
      case 'error':
        if (event.metadata?.turn_terminal === true) {
          this.observeTerminal(
            active,
            'The server could not finish the response.',
          );
          return;
        }
        this.update({
          error: 'The server reported an error.',
        });
        break;
      case 'done':
        this.observeTerminal(
          active,
          event.metadata?.status === 'failed' && !this.state.error
            ? 'The server could not finish the response.'
            : undefined,
        );
        return;
    }
    this.watchTurn(active);
    if (active.cancelRequested) this.cancelAdmittedTurn(active);
  }

  private observeTerminal(active: ActiveTurn, error?: string) {
    // DONE can arrive before the server releases the owner lease. Let the
    // Stop ACK confirm release before allowing another turn to start.
    if (active.cancelSent) {
      active.terminal = { error };
      this.clearIdleTimer();
      if (error) this.update({ error });
    } else {
      this.finishTurn(error);
    }
  }

  private retryReplay(active: ActiveTurn, error: string) {
    if (this.replayTimer !== undefined) return;
    if (active.replayRetries >= MAX_REPLAY_RETRIES) {
      this.update({
        connection: 'idle',
        error: error + ' Reconnect to continue.',
        canLeaveTurn: true,
      });
      return;
    }
    this.update({ error });
    this.replayTimer = setTimeout(() => {
      this.replayTimer = undefined;
      if (this.active !== active || !this.visible) return;
      active.replayRetries += 1;
      this.client?.manualRetry();
    }, 500 * 2 ** active.replayRetries);
  }

  private clearReplayRetry() {
    clearTimeout(this.replayTimer);
    this.replayTimer = undefined;
  }

  private clearIdleTimer() {
    clearTimeout(this.idleTimer);
    this.idleTimer = undefined;
  }

  private watchTurn(active: ActiveTurn) {
    this.clearIdleTimer();
    if (!this.visible || !active.turnId || this.state.phase !== 'running')
      return;
    this.idleTimer = setTimeout(
      () => {
        if (
          this.active !== active ||
          !this.visible ||
          this.state.phase !== 'running'
        )
          return;
        if (active.idleRecovery) {
          this.update({
            canLeaveTurn: true,
            error:
              'No updates from this response. Reconnect or start a new chat.',
          });
          return;
        }
        active.idleRecovery = true;
        this.client?.manualRetry();
        this.watchTurn(active);
      },
      active.idleRecovery ? TURN_RECOVERY_TIMEOUT_MS : TURN_IDLE_TIMEOUT_MS,
    );
  }

  private updateAnswer(active: ActiveTurn, answer: string, replace: boolean) {
    this.update({
      messages: this.state.messages.map(message =>
        message.id === active.messageId
          ? { ...message, answer: replace ? answer : message.answer + answer }
          : message,
      ),
    });
  }

  private finishTurn(error?: string) {
    const turnId = this.active?.turnId;
    this.active = null;
    this.clearStartTimeout();
    this.clearReplayRetry();
    this.clearIdleTimer();
    if (turnId) {
      this.retiredTurnIds.add(turnId);
      try {
        this.client?.send(buildUnsubscribe({ turnId }), { durable: false });
      } catch {
        // A socket can close as the turn finishes. The server also removes
        // its subscriptions when the socket disconnects.
      }
    }
    this.client?.setResumeCursor(null, 0);
    this.update({
      phase: 'ready',
      waitingPrompt: null,
      canLeaveTurn: false,
      error: error ?? this.state.error,
    });
  }

  private clearStartTimeout() {
    clearTimeout(this.timer);
    this.timer = undefined;
  }

  private update(patch: Partial<ChatState>) {
    this.state = { ...this.state, ...patch };
    for (const listener of this.listeners) listener();
  }
}

export type { ChatOptions };
