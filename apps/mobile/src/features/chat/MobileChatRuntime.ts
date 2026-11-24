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
import { toExchanges, resolveTurn, type ChatExchange } from '../sessions/history';
import { shouldAppendEventContent } from '@/lib/stream';
import { ApiError } from '../../services/apiClient';
import type {
  SessionApi,
  SessionDetail,
  TurnStatus,
} from '../../services/sessionApi';
import type {
  LastSessionStore,
  RecoveryRecord,
  RecoveryScope,
  TurnRecoveryStore,
} from '../../storage/turnRecovery';

/**
 * The task's own state, named after what the server reports for a turn
 * (`turns.status`) rather than a parallel vocabulary. `submitting` and
 * `recovering` are the two client-only states: one is a send that the server
 * has not admitted yet, the other is a resume whose live state is still being
 * confirmed.
 */
export type ChatStatus =
  | 'idle'
  | 'submitting'
  | 'running'
  | 'waiting_for_input'
  | 'cancelling'
  | 'recovering'
  | 'completed'
  | 'failed'
  | 'cancelled';

/** How the transcript for the open conversation was obtained. */
export type HistoryState = 'idle' | 'loading' | 'ready' | 'failed';

/** What the app learned when it asked the server about a saved run. */
export interface RecoveryNotice {
  kind: 'resumed' | 'settled' | 'unavailable';
  message: string;
}

type ChatState = {
  connection: RuntimeConnectionState;
  status: ChatStatus;
  sessionId: string | null;
  sessionTitle: string;
  messages: ChatExchange[];
  history: HistoryState;
  waitingPrompt: string | null;
  canLeaveTurn: boolean;
  recovery: RecoveryNotice | null;
  error: string | null;
};

type ChatOptions = {
  origin: string;
  socketFactory?: TurnSocketFactory;
  onAuthExpired?: () => void;
  refreshAuth?: () => Promise<boolean>;
  /** Conversation history transport; absent in unit tests that only drive WS. */
  sessionApi?: SessionApi;
  recovery?: TurnRecoveryStore;
  /** Remembers the conversation to reopen on a later launch. */
  lastSession?: LastSessionStore;
  /** Null disables persistence entirely (nothing is written without an account). */
  scope?: RecoveryScope | null;
};

type ActiveTurn = {
  messageId: string;
  /** The id sent as `client_submission_id`; the server dedupes on it. */
  submissionId: string;
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
/** Streaming can emit events far faster than a disk write is worth. */
const PERSIST_INTERVAL_MS = 750;
const STATUSES_RUNNING: readonly ChatStatus[] = [
  'submitting',
  'running',
  'waiting_for_input',
  'cancelling',
  'recovering',
];
const START_ERRORS = new Set([
  'start_turn_rejected',
  NO_LLM_ACCESS,
  'invalid_command',
  'invalid_json',
  'unsupported_protocol_version',
  'unknown_message_type',
  'internal_error',
]);

/** A terminal state still accepts the next question. */
function isComposing(status: ChatStatus): boolean {
  return !STATUSES_RUNNING.includes(status);
}

function outcomeOf(status: TurnStatus): ChatStatus {
  switch (status) {
    case 'completed':
      return 'completed';
    case 'failed':
      return 'failed';
    case 'cancelled':
    case 'rejected':
      return 'cancelled';
    case 'running':
    case 'waiting_input':
    case 'queued':
      return 'recovering';
    default:
      return 'idle';
  }
}

function initialState(): ChatState {
  return {
    connection: 'idle',
    status: 'idle',
    sessionId: null,
    sessionTitle: '',
    messages: [],
    history: 'idle',
    waitingPrompt: null,
    canLeaveTurn: false,
    recovery: null,
    error: null,
  };
}

export class MobileChatRuntime {
  private state = initialState();
  private readonly listeners = new Set<() => void>();
  private readonly retiredTurnIds = new Set<string>();
  private client: TurnRuntimeClient | null = null;
  private active: ActiveTurn | null = null;
  private sessionId: string | null = null;
  private timer: Timer | undefined;
  private replayTimer: Timer | undefined;
  private idleTimer: Timer | undefined;
  private visible = true;
  private restored = false;
  private lastPersistedAt = 0;
  /** Bumped by every load or reset so a late reply cannot land in a new one. */
  private epoch = 0;
  /** Record read on cold start, consumed by the transcript load it triggered. */
  private pendingRecord: RecoveryRecord | null = null;
  /**
   * The last start command the server never confirmed. Reusing its id keeps a
   * retry idempotent server-side: `start_turn` returns the turn it already
   * reserved instead of running the question twice.
   */
  private unconfirmedSubmission: { id: string; text: string } | null = null;
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
    if (!this.restored) {
      this.restored = true;
      this.restore().catch(() => {});
    }
  }

  stop() {
    this.clearStartTimeout();
    this.clearReplayRetry();
    this.clearIdleTimer();
    this.epoch += 1;
    this.active = null;
    this.sessionId = null;
    this.retiredTurnIds.clear();
    this.closeTransport();
    this.update({ ...initialState(), connection: 'stopped' });
  }

  setVisible(visible: boolean) {
    const resumed = visible && !this.visible;
    this.visible = visible;
    if (!visible) {
      this.clearIdleTimer();
      // Record the exact sequence reached before the OS can suspend or kill
      // the process; this is the only reliable point to snapshot it.
      this.persist(true);
    }
    const client = this.client;
    if (!client) return;
    // A socket can still report OPEN after Android/iOS has suspended the app
    // and the route has changed. Reopen it and replay from the live cursor.
    if (resumed && client.state === 'connected') client.manualRetry();
    client.setPageVisible(visible);
    if (resumed && this.active) this.watchTurn(this.active);
    // Coming back with nothing in memory means the process was reclaimed.
    if (resumed && !this.active) this.restore().catch(() => {});
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

  /**
   * Re-open the server's record for a conversation.
   *
   * Always driven by the server: the local snapshot only says which turn to ask
   * about. A conversation the server no longer has is reported as such instead
   * of being shown as a run that is still going.
   */
  openSession = (sessionId: string): Promise<boolean> =>
    this.load(sessionId, false);

  private load = async (
    sessionId: string,
    silent: boolean,
  ): Promise<boolean> => {
    if (this.active) {
      if (!silent) {
        this.update({
          error: 'Stop the current response before switching conversations.',
        });
      }
      return false;
    }
    const api = this.options.sessionApi;
    if (!api) return false;
    const epoch = ++this.epoch;
    this.active = null;
    this.sessionId = sessionId;
    this.client?.setResumeCursor(null, 0);
    this.update({
      sessionId,
      sessionTitle: '',
      messages: [],
      history: 'loading',
      status: 'idle',
      waitingPrompt: null,
      canLeaveTurn: false,
      recovery: null,
      error: null,
    });
    try {
      const detail = await api.get(sessionId);
      if (epoch !== this.epoch) return false;
      this.applyDetail(detail);
      return true;
    } catch (error) {
      if (epoch !== this.epoch) return false;
      this.failLoad(error, silent);
      return false;
    }
  };

  /** Re-run the last failed transcript load. */
  retrySession = async (): Promise<boolean> => {
    const sessionId = this.sessionId;
    if (!sessionId) return false;
    return this.openSession(sessionId);
  };

  /** Start a fresh conversation; the server creates it on the next turn. */
  reset = () => {
    if (this.active && !this.state.canLeaveTurn) return;
    this.epoch += 1;
    this.active = null;
    this.clearIdleTimer();
    this.clearStartTimeout();
    this.clearReplayRetry();
    this.sessionId = null;
    this.unconfirmedSubmission = null;
    this.retiredTurnIds.clear();
    this.closeTransport();
    this.update(initialState());
    this.openTransport();
    this.clearPersisted();
    this.forgetSession();
  };

  dismissRecovery = () => this.update({ recovery: null });

  /**
   * A send needs a transcript the app can append to. Posting while it is still
   * loading would write into messages the server copy is about to replace;
   * posting after it failed to load would answer with history nobody can see.
   * A conversation this runtime created over the socket has no transcript load
   * at all (`idle`), which is a fine state to post from.
   */
  private canPost(): boolean {
    return this.state.history === 'idle' || this.state.history === 'ready';
  }

  send = (text: string): boolean => {
    const question = text.trim();
    if (
      !question ||
      this.active ||
      this.client?.state !== 'connected' ||
      !isComposing(this.state.status) ||
      !this.canPost()
    ) {
      return false;
    }
    const messageId = newCommandId();
    // Resending the same question after an unconfirmed start reuses the id the
    // server may already have reserved, so the retry cannot run it twice.
    const submissionId =
      this.unconfirmedSubmission?.text === question
        ? this.unconfirmedSubmission.id
        : newCommandId();
    this.unconfirmedSubmission = { id: submissionId, text: question };
    const active: ActiveTurn = {
      messageId,
      submissionId,
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
        { id: messageId, question, answer: '', failed: null, retryable: false },
      ],
      status: 'submitting',
      canLeaveTurn: false,
      recovery: null,
      error: null,
    });
    this.timer = setTimeout(() => {
      if (this.active !== active || active.turnId) return;
      this.finishTurn(
        'failed',
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
          client_submission_id: submissionId,
          ...(this.sessionId ? { session_id: this.sessionId } : {}),
        }),
      );
      return true;
    } catch {
      // Nothing reached the transport, so there is no reservation to reuse.
      this.unconfirmedSubmission = null;
      this.finishTurn(
        'failed',
        'Unable to send this message. Check your connection.',
      );
      this.closeTransport();
      this.openTransport();
      return false;
    }
  };

  cancel = async (): Promise<void> => {
    const active = this.active;
    if (!active || active.cancelRequested) return;
    active.cancelRequested = true;
    this.update({ status: 'cancelling', error: null });
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
      this.state.status !== 'waiting_for_input' ||
      this.client?.state !== 'connected'
    ) {
      return false;
    }
    active.replying = true;
    const prompt = this.state.waitingPrompt;
    this.update({ status: 'running', waitingPrompt: null, error: null });
    this.watchTurn(active);
    try {
      const accepted = await this.client.sendAwaitingAck(
        buildSubmitUserReply({ turnId: active.turnId, text }),
      );
      if (!accepted && this.active === active) {
        this.finishTurn(
          'failed',
          'That question is no longer waiting for a reply.',
        );
      }
      return accepted;
    } catch {
      if (
        this.active === active &&
        !active.cancelRequested &&
        this.getSnapshot().status === 'running'
      ) {
        this.update({
          status: 'waiting_for_input',
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

  /** Adopt a server transcript, resuming it only if the server says it is live. */
  private applyDetail(detail: SessionDetail) {
    // A record only describes the conversation it was written for.
    const record =
      this.pendingRecord?.sessionId === detail.id ? this.pendingRecord : null;
    this.pendingRecord = null;
    // The server's transcript settles whether anything is still pending.
    this.unconfirmedSubmission = null;
    const messages = toExchanges(detail.messages);
    const resolved = resolveTurn(detail, record?.turnId ?? '');
    const title = detail.title || '';
    if (resolved.kind === 'live') {
      const turn = resolved.turn;
      // Rebuild the in-flight answer from the replayed log rather than
      // trusting whatever local text survived: a persisted window can trail
      // the server, and appending the replay on top would duplicate it.
      const last = messages[messages.length - 1];
      let messageId: string;
      if (last && !last.answer && !last.failed) {
        messageId = last.id;
      } else {
        messageId = `turn:${turn.id}`;
        messages.push({
          id: messageId,
          question: '',
          answer: '',
          failed: null,
          retryable: false,
        });
      }
      const active: ActiveTurn = {
        messageId,
        submissionId: record?.clientSubmissionId ?? '',
        turnId: turn.id,
        replying: false,
        cancelRequested: false,
        cancelSent: false,
        replayRetries: 0,
      };
      this.active = active;
      this.sessionId = detail.id;
      this.update({
        sessionId: detail.id,
        sessionTitle: title,
        messages,
        history: 'ready',
        status: 'recovering',
        canLeaveTurn: false,
        error: null,
        recovery: {
          kind: 'resumed',
          message: 'Reconnected to a response that was still running.',
        },
      });
      // seq 0 makes the server replay the whole turn so the answer rebuilds
      // from its own log; the persisted sequence is kept for diagnostics only.
      this.rememberSession(detail.id);
      this.client?.setResumeCursor(turn.id, 0);
      this.client?.manualRetry();
      this.watchTurn(active);
      return;
    }
    const settled = resolved.kind === 'settled' ? resolved.status : 'idle';
    this.sessionId = detail.id;
    this.update({
      sessionId: detail.id,
      sessionTitle: title,
      messages,
      history: 'ready',
      status: outcomeOf(settled),
      waitingPrompt: null,
      canLeaveTurn: false,
      error: null,
      recovery: record
        ? {
            kind: 'settled',
            message: 'The response finished while the app was away.',
          }
        : null,
    });
    this.rememberSession(detail.id);
    this.clearPersisted();
  }

  private failLoad(error: unknown, silent = false) {
    const api = error instanceof ApiError ? error : null;
    if (api?.status === 404 && silent) {
      // A remembered conversation that is now gone is not an incident: forget
      // it and open a fresh chat rather than announcing a deletion.
      this.sessionId = null;
      this.update(initialState());
      this.forgetSession();
      return;
    }
    if (api?.status === 404) {
      // The conversation is gone on the server. Say so and fall back to a new
      // chat instead of leaving a dead transcript on screen.
      this.sessionId = null;
      this.update({
        sessionId: null,
        sessionTitle: '',
        messages: [],
        // No dead "try again": the banner explains it is gone and offers a new
        // chat, and the empty state is the honest screen behind it.
        history: 'idle',
        status: 'idle',
        recovery: {
          kind: 'unavailable',
          message: 'This conversation no longer exists on the server.',
        },
        error: null,
      });
      this.clearPersisted();
      return;
    }
    if (api?.kind === 'unauthorized') {
      this.options.onAuthExpired?.();
      this.update({
        history: 'failed',
        status: 'idle',
        error: 'Sign in again to load this conversation.',
      });
      return;
    }
    this.update({
      history: 'failed',
      status: 'idle',
      error:
        api?.kind === 'network' || api?.kind === 'timeout'
          ? 'Could not reach the server to load this conversation.'
          : 'Could not load this conversation.',
    });
  }

  private async restore() {
    const { recovery, lastSession, scope, sessionApi } = this.options;
    if (!scope || !sessionApi || this.active) return;
    let record: RecoveryRecord | null = null;
    try {
      record = recovery ? await recovery.read(scope) : null;
    } catch {
      record = null;
    }
    if (this.active) return;
    if (record) {
      this.pendingRecord = record;
      const opened = await this.load(record.sessionId, false);
      if (!opened) this.pendingRecord = null;
      return;
    }
    // Nothing was running: reopen the conversation the learner was reading,
    // quietly, so a relaunch does not look like the history was lost.
    let last: string | null = null;
    try {
      last = (await lastSession?.read(scope)) ?? null;
    } catch {
      last = null;
    }
    if (!last || this.active) return;
    await this.load(last, true);
  }

  private persist(force = false) {
    const { recovery, scope } = this.options;
    const active = this.active;
    const sessionId = this.sessionId;
    if (!recovery || !scope || !active?.turnId || !sessionId) return;
    const status = this.state.status;
    if (
      status !== 'submitting' &&
      status !== 'running' &&
      status !== 'waiting_for_input' &&
      status !== 'cancelling' &&
      status !== 'recovering'
    )
      return;
    const now = Date.now();
    if (!force && now - this.lastPersistedAt < PERSIST_INTERVAL_MS) return;
    this.lastPersistedAt = now;
    const record: RecoveryRecord = {
      version: 1,
      sessionId,
      turnId: active.turnId,
      clientSubmissionId: active.submissionId || active.messageId,
      lastSeq: this.client?.cursor.afterSeq ?? 0,
      status,
      updatedAt: now,
    };
    recovery.write(scope, record).catch(() => {});
  }

  private rememberSession(sessionId: string) {
    const { lastSession, scope } = this.options;
    if (!lastSession || !scope) return;
    lastSession.write(scope, sessionId).catch(() => {});
  }

  private forgetSession() {
    const { lastSession, scope } = this.options;
    if (!lastSession || !scope) return;
    lastSession.clear(scope).catch(() => {});
  }

  private clearPersisted() {
    const { recovery, scope } = this.options;
    if (!recovery || !scope) return Promise.resolve();
    return recovery.clear(scope).catch(() => {});
  }

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
        this.finishTurn('cancelled', active.terminal?.error);
        return;
      }
    } catch {
      // Delivery can time out while the owner is still unwinding.
    }
    if (this.active === active) {
      if (active.terminal) {
        // The server observed a terminal frame, but ownership release is
        // unconfirmed. A subsequent question must use a new session.
        this.sessionId = null;
        this.finishTurn('cancelled', active.terminal.error);
        return;
      }
      active.cancelRequested = false;
      active.cancelSent = false;
      this.update({
        status: this.state.waitingPrompt ? 'waiting_for_input' : 'running',
        error: 'Could not confirm the stop request. Try Stop again.',
        canLeaveTurn: true,
      });
      // The run is still the server's; keep the idle watchdog armed so a
      // connection that died during the stop still recovers.
      this.watchTurn(active);
    }
  }

  private openTransport() {
    const factory = this.options.socketFactory ?? browserSocketFactory;
    // The built-in workspace is addressed by an empty dt_workspace, which is
    // also what the conversation history request pins.
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
        else this.finishTurn('failed', error);
      } else if (START_ERRORS.has(event.error_code) && !active.turnId) {
        this.finishTurn(
          'failed',
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
      // Admitted: the id is spent and must not be reused for a later question.
      this.unconfirmedSubmission = null;
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
    if (this.state.status === 'submitting' || this.state.status === 'recovering') {
      this.update({ status: 'running' });
    }
    if (this.state.sessionId !== this.sessionId) {
      this.update({ sessionId: this.sessionId });
      if (this.sessionId) this.rememberSession(this.sessionId);
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
          status: active.cancelRequested ? 'cancelling' : 'waiting_for_input',
          waitingPrompt:
            event.content || 'DeepTutor needs a reply to continue.',
        });
        // A run parked on a question must survive a process death, so that
        // transition is always written rather than throttled.
        this.persist(true);
        break;
      case 'error':
        if (event.metadata?.turn_terminal === true) {
          this.observeTerminal(active, true);
          return;
        }
        this.update({
          error: 'The server reported an error.',
        });
        break;
      case 'done':
        this.observeTerminal(
          active,
          event.metadata?.status === 'failed' && !this.state.error,
        );
        return;
    }
    this.persist();
    this.watchTurn(active);
    if (active.cancelRequested) this.cancelAdmittedTurn(active);
  }

  private observeTerminal(active: ActiveTurn, failed = false) {
    const error = failed ? 'The server could not finish the response.' : undefined;
    // DONE can arrive before the server releases the owner lease. Let the
    // Stop ACK confirm release before allowing another turn to start.
    if (active.cancelSent) {
      active.terminal = { error };
      this.clearIdleTimer();
      if (error) this.update({ error });
    } else {
      this.finishTurn(failed ? 'failed' : 'completed', error);
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
    if (!this.visible || !active.turnId) return;
    const status = this.state.status;
    const waiting = status === 'running' || status === 'recovering';
    if (!waiting) return;
    this.idleTimer = setTimeout(
      () => {
        if (
          this.active !== active ||
          !this.visible ||
          (this.state.status !== 'running' &&
            this.state.status !== 'recovering')
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
    // A resumed turn replays from seq 0 into an exchange whose answer was
    // cleared first, so appending is correct there too — no duplicate text.
    this.update({
      messages: this.state.messages.map(message =>
        message.id === active.messageId
          ? { ...message, answer: replace ? answer : message.answer + answer }
          : message,
      ),
    });
  }

  private finishTurn(outcome: ChatStatus, error?: string) {
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
      status: outcome,
      waitingPrompt: null,
      canLeaveTurn: false,
      error: error ?? this.state.error,
    });
    this.clearPersisted();
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
