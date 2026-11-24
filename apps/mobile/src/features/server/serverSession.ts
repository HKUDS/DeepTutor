import { ApiClient, ApiError } from '../../services/apiClient';
import { serverStorage, type ServerStorage } from '../../storage/serverStorage';
import { AuthService, type AuthStatus } from '../auth/authService';
import { clearNativeCookies } from '../auth/nativeCookies';
import { serverOrigin } from './serverAddress';

export interface ServerSessionState {
  phase: 'loading' | 'connect' | 'login' | 'chat';
  network: 'unknown' | 'checking' | 'online' | 'offline';
  origin: string | null;
  status: AuthStatus | null;
  busy: boolean;
  error: string | null;
}

type SessionDependencies = {
  storage: ServerStorage;
  clearCookies: () => Promise<void>;
  authFor: (origin: string) => Pick<AuthService, 'status' | 'login' | 'logout'>;
  normalizeOrigin: (address: string) => string;
};

const nativeDependencies: SessionDependencies = {
  storage: serverStorage,
  clearCookies: clearNativeCookies,
  authFor: origin => new AuthService(new ApiClient(origin)),
  normalizeOrigin: serverOrigin,
};

type Operation = { controller: AbortController; isCurrent: () => boolean };

export class ServerSession {
  private state: ServerSessionState = {
    phase: 'loading',
    network: 'unknown',
    origin: null,
    status: null,
    busy: false,
    error: null,
  };
  private readonly listeners = new Set<() => void>();
  private operation: AbortController | null = null;
  private refresh: {
    controller: AbortController;
    result: Promise<boolean>;
  } | null = null;

  constructor(private readonly dependencies = nativeDependencies) {}

  readonly getSnapshot = (): ServerSessionState => this.state;

  readonly subscribe = (listener: () => void): (() => void) => {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  };

  private update(next: Partial<ServerSessionState>): void {
    this.state = { ...this.state, ...next };
    this.listeners.forEach(listener => listener());
  }

  private applyStatus(origin: string, status: AuthStatus): void {
    this.update({
      origin,
      status,
      phase: status.authenticated ? 'chat' : 'login',
      network: 'online',
      error: null,
    });
  }

  private abortRefresh(): void {
    const refresh = this.refresh;
    this.refresh = null;
    refresh?.controller.abort();
  }

  private async run(
    task: (operation: Operation) => Promise<void>,
  ): Promise<void> {
    if (this.operation) return;
    this.abortRefresh();
    const controller = new AbortController();
    const isCurrent = () =>
      this.operation === controller && !controller.signal.aborted;
    this.operation = controller;
    this.update({ busy: true, error: null });
    try {
      await task({ controller, isCurrent });
    } catch (error) {
      if (isCurrent()) {
        this.update({
          ...(this.state.phase === 'loading'
            ? { phase: 'connect' as const }
            : {}),
          ...(this.state.network === 'checking' || isConnectionError(error)
            ? { network: 'offline' as const }
            : {}),
          error:
            error instanceof Error
              ? error.message
              : 'Could not connect to DeepTutor.',
        });
      }
    } finally {
      if (isCurrent()) {
        this.operation = null;
        this.update({ busy: false });
      }
    }
  }

  readonly restore = (): Promise<void> =>
    this.run(async ({ controller, isCurrent }) => {
      const saved = await this.dependencies.storage.read();
      if (!isCurrent()) return;
      if (!saved) {
        this.update({ phase: 'connect', network: 'unknown' });
        return;
      }
      const origin = this.dependencies.normalizeOrigin(saved);
      this.update({ origin, network: 'checking' });
      const status = await this.dependencies
        .authFor(origin)
        .status(controller.signal);
      if (isCurrent()) this.applyStatus(origin, status);
    });

  readonly connect = (address: string): Promise<void> =>
    this.run(async ({ controller, isCurrent }) => {
      const origin = this.dependencies.normalizeOrigin(address);
      const switching = origin !== this.state.origin;
      // Unmount the previous chat before touching its process-wide cookie store.
      this.update({
        phase: 'connect',
        network: 'checking',
        status: null,
        ...(switching ? { origin: null } : {}),
      });
      if (switching) {
        await this.discardCredentials();
      }
      if (!isCurrent()) return;
      const status = await this.dependencies
        .authFor(origin)
        .status(controller.signal);
      if (!isCurrent()) return;
      await this.dependencies.storage.write(origin);
      if (isCurrent()) this.applyStatus(origin, status);
    });

  readonly login = (username: string, password: string): Promise<void> =>
    this.run(async ({ controller, isCurrent }) => {
      const { origin, phase } = this.state;
      if (phase !== 'login' || !origin) return;
      if (!username.trim() || !password) {
        throw new Error('Enter your username and password.');
      }
      const status = await this.dependencies
        .authFor(origin)
        .login(username, password, controller.signal);
      if (isCurrent() && status.authenticated) this.applyStatus(origin, status);
    });

  readonly logout = (): Promise<void> =>
    this.run(async operation => {
      const { origin, phase } = this.state;
      if (!origin || phase !== 'chat' || !this.state.status?.enabled) return;
      await this.clearSession(origin, operation, true);
    });

  readonly invalidateAuth = (): void => {
    this.run(async operation => {
      const { origin, phase } = this.state;
      if (!origin || phase !== 'chat' || !this.state.status?.enabled) return;
      await this.clearSession(origin, operation, false);
    });
  };

  private async clearSession(
    origin: string,
    { controller, isCurrent }: Operation,
    logout: boolean,
  ): Promise<void> {
    this.applyStatus(origin, { enabled: true, authenticated: false });
    let logoutFailure: unknown;
    await this.discardCredentials(
      logout
        ? async () => {
            try {
              await this.dependencies.authFor(origin).logout(controller.signal);
            } catch (error) {
              logoutFailure = error;
            }
          }
        : undefined,
    );
    if (!isCurrent()) return;
    await this.dependencies.storage.write(origin);
    if (!isCurrent()) return;
    if (logoutFailure) throw logoutFailure;
    if (!logout)
      this.update({ error: 'Sign in again to reconnect to this server.' });
  }

  readonly disconnect = (): Promise<void> =>
    this.run(async () => {
      this.update({
        phase: 'connect',
        origin: null,
        status: null,
        network: 'unknown',
      });
      await this.discardCredentials();
    });

  private async discardCredentials(beforeClear?: () => Promise<void>) {
    // Cookies are the credential. A failed preference write must never skip
    // logout or native cleanup, and a failed cleanup must block new requests.
    const [saved, cookies] = await Promise.allSettled([
      Promise.resolve().then(() => this.dependencies.storage.write(null)),
      Promise.resolve().then(async () => {
        await beforeClear?.();
        await this.dependencies.clearCookies();
      }),
    ]);
    if (cookies.status === 'rejected') {
      throw new Error('Could not clear the saved session. Try again.');
    }
    if (saved.status === 'rejected') {
      throw new Error('Could not update the saved server address.');
    }
  }

  /**
   * Check an ambiguous transport failure without interpreting a network outage
   * as an expired account. Only an explicit authentication check changes routes.
   */
  readonly refreshAuth = (): Promise<boolean> => {
    const { origin, phase } = this.state;
    if (this.operation || phase !== 'chat' || !origin) {
      return Promise.resolve(phase === 'chat');
    }
    if (this.refresh) return this.refresh.result;
    const controller = new AbortController();
    const current = () => this.refresh?.controller === controller;
    const result = this.dependencies
      .authFor(origin)
      .status(controller.signal)
      .then(status => {
        if (current()) this.applyStatus(origin, status);
        return current() ? status.authenticated : this.state.phase === 'chat';
      })
      .catch(error => {
        if (current() && isConnectionError(error))
          this.update({ network: 'offline' });
        return this.state.phase === 'chat';
      })
      .finally(() => {
        if (current()) this.refresh = null;
      });
    this.refresh = { controller, result };
    return result;
  };

  readonly abortPending = (): void => {
    this.operation?.abort();
    this.operation = null;
    this.abortRefresh();
  };
}

function isConnectionError(error: unknown): boolean {
  return (
    error instanceof ApiError &&
    (error.kind === 'network' || error.kind === 'timeout')
  );
}
