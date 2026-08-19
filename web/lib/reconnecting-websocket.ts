const CONNECTING = 0;
const OPEN = 1;

const DEFAULT_BASE_RETRY_MS = 250;
const DEFAULT_MAX_RETRY_MS = 8_000;
const DEFAULT_STALE_CONNECTING_MS = 10_000;

export function reconnectDelayMs(
  attempt: number,
  baseDelayMs = DEFAULT_BASE_RETRY_MS,
  maxDelayMs = DEFAULT_MAX_RETRY_MS,
): number {
  return Math.min(baseDelayMs * 2 ** Math.max(0, attempt), maxDelayMs);
}

interface RetryScheduler {
  set(callback: () => void, delayMs: number): unknown;
  clear(handle: unknown): void;
}

interface ReconnectingWebSocketHandlers {
  onOpen?: () => void;
  onMessage: (event: MessageEvent) => void;
  onDisconnect?: () => void;
  onError?: (error: unknown) => void;
}

interface ReconnectingWebSocketOptions {
  createSocket?: (url: string) => WebSocket;
  shouldReconnect?: () => boolean;
  scheduler?: RetryScheduler;
  now?: () => number;
  baseRetryMs?: number;
  maxRetryMs?: number;
  staleConnectingMs?: number;
}

const defaultScheduler: RetryScheduler = {
  set: (callback, delayMs) => setTimeout(callback, delayMs),
  clear: (handle) => clearTimeout(handle as ReturnType<typeof setTimeout>),
};

/**
 * Owns one browser WebSocket and keeps it alive across transient disconnects.
 *
 * The class deliberately knows nothing about React or the wire protocol. A
 * caller can pause retries while its page is hidden, then call `wake()` on
 * focus/visibility/online events for an immediate connection attempt.
 */
export class ReconnectingWebSocket {
  private socket: WebSocket | null = null;
  private retryHandle: unknown = null;
  private retryAttempt = 0;
  private connectingSince = 0;
  private stopped = true;

  private readonly createSocket: (url: string) => WebSocket;
  private readonly shouldReconnect: () => boolean;
  private readonly scheduler: RetryScheduler;
  private readonly now: () => number;
  private readonly baseRetryMs: number;
  private readonly maxRetryMs: number;
  private readonly staleConnectingMs: number;

  constructor(
    private readonly url: string,
    private readonly handlers: ReconnectingWebSocketHandlers,
    options: ReconnectingWebSocketOptions = {},
  ) {
    this.createSocket = options.createSocket ?? ((url) => new WebSocket(url));
    this.shouldReconnect = options.shouldReconnect ?? (() => true);
    this.scheduler = options.scheduler ?? defaultScheduler;
    this.now = options.now ?? Date.now;
    this.baseRetryMs = options.baseRetryMs ?? DEFAULT_BASE_RETRY_MS;
    this.maxRetryMs = options.maxRetryMs ?? DEFAULT_MAX_RETRY_MS;
    this.staleConnectingMs =
      options.staleConnectingMs ?? DEFAULT_STALE_CONNECTING_MS;
  }

  get connected(): boolean {
    return this.socket?.readyState === OPEN;
  }

  start(): void {
    if (!this.stopped) return;
    this.stopped = false;
    if (this.shouldReconnect()) this.open();
  }

  /** Try immediately after the browser becomes active or comes back online. */
  wake(): void {
    if (this.stopped || !this.shouldReconnect()) return;
    this.clearRetry();
    this.retryAttempt = 0;

    if (this.socket?.readyState === OPEN) return;
    if (
      this.socket?.readyState === CONNECTING &&
      this.now() - this.connectingSince < this.staleConnectingMs
    ) {
      return;
    }

    this.releaseSocket();
    this.open();
  }

  send(payload: string): boolean {
    if (!this.socket || this.socket.readyState !== OPEN) return false;
    try {
      this.socket.send(payload);
      return true;
    } catch (error) {
      this.handlers.onError?.(error);
      this.socket.close();
      return false;
    }
  }

  stop(): void {
    if (this.stopped) return;
    this.stopped = true;
    this.clearRetry();
    this.releaseSocket();
    this.retryAttempt = 0;
  }

  private open(): void {
    if (this.stopped || (this.socket && this.socket.readyState <= OPEN)) {
      return;
    }

    let socket: WebSocket;
    try {
      socket = this.createSocket(this.url);
    } catch (error) {
      this.handlers.onError?.(error);
      this.scheduleRetry();
      return;
    }

    this.socket = socket;
    this.connectingSince = this.now();
    socket.onopen = () => {
      if (this.socket !== socket || this.stopped) return;
      this.retryAttempt = 0;
      this.handlers.onOpen?.();
    };
    socket.onmessage = (event) => {
      if (this.socket === socket && !this.stopped) {
        this.handlers.onMessage(event);
      }
    };
    socket.onerror = (error) => {
      if (this.socket === socket && !this.stopped) {
        this.handlers.onError?.(error);
      }
    };
    socket.onclose = () => {
      if (this.socket !== socket) return;
      this.socket = null;
      this.handlers.onDisconnect?.();
      this.scheduleRetry();
    };
  }

  private scheduleRetry(): void {
    if (this.stopped || this.retryHandle !== null || !this.shouldReconnect()) {
      return;
    }
    const delayMs = reconnectDelayMs(
      this.retryAttempt,
      this.baseRetryMs,
      this.maxRetryMs,
    );
    this.retryAttempt += 1;
    this.retryHandle = this.scheduler.set(() => {
      this.retryHandle = null;
      if (this.shouldReconnect()) this.open();
    }, delayMs);
  }

  private clearRetry(): void {
    if (this.retryHandle === null) return;
    this.scheduler.clear(this.retryHandle);
    this.retryHandle = null;
  }

  private releaseSocket(): void {
    const socket = this.socket;
    this.socket = null;
    if (!socket) return;
    socket.onopen = null;
    socket.onmessage = null;
    socket.onerror = null;
    socket.onclose = null;
    if (socket.readyState <= OPEN) socket.close();
  }
}
