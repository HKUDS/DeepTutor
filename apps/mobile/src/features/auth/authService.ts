import { ApiClient, ApiError } from '../../services/apiClient';

export interface AuthStatus {
  enabled: boolean;
  authenticated: boolean;
  /**
   * Stable account identity from the server. Used only to namespace local
   * recovery state — it is never stored as a credential and never sent back.
   */
  accountId: string;
}

function parseStatus(value: unknown): AuthStatus {
  if (!value || typeof value !== 'object') {
    throw new Error('Expected an authentication status');
  }
  const record = value as Record<string, unknown>;
  if (
    typeof record.enabled !== 'boolean' || typeof record.authenticated !== 'boolean'
  ) {
    throw new Error('Invalid authentication status');
  }
  if (record.enabled === false && record.authenticated === false) {
    throw new Error('Invalid authentication status');
  }
  // `/api/auth/status` reports `user_id` for a signed-in account and
  // `local-admin` when auth is off. An authenticated response without one
  // cannot be namespaced safely, so it fails instead of sharing a namespace.
  const accountId =
    typeof record.user_id === 'string' ? record.user_id.trim() : '';
  if (record.authenticated && !accountId) {
    throw new Error('Authentication status has no account id');
  }
  return {
    enabled: record.enabled,
    authenticated: record.authenticated,
    accountId,
  };
}

function parseOk(value: unknown): void {
  if (
    !value ||
    typeof value !== 'object' ||
    (value as { ok?: unknown }).ok !== true
  ) {
    throw new Error('Expected an authentication acknowledgement');
  }
}

export class AuthService {
  constructor(private readonly api: ApiClient) {}

  async status(signal: AbortSignal): Promise<AuthStatus> {
    try {
      return await this.api.json('/api/auth/status', parseStatus, { signal });
    } catch (error) {
      if (error instanceof ApiError && error.kind === 'unauthorized') {
        return { enabled: true, authenticated: false, accountId: '' };
      }
      throw error;
    }
  }

  async login(
    username: string,
    password: string,
    signal: AbortSignal,
  ): Promise<AuthStatus> {
    try {
      await this.api.json('/api/auth/login', parseOk, {
        method: 'POST',
        body: { username: username.trim(), password },
        signal,
      });
    } catch (error) {
      if (error instanceof ApiError && error.kind === 'unauthorized') {
        throw new ApiError(
          'unauthorized',
          'Check your username and password.',
          401,
        );
      }
      throw error;
    }
    // Keep the HttpOnly cookie in the platform jar. Make a second API request
    // to ensure the OS accepted it before allowing the WebSocket route.
    const status = await this.status(signal);
    if (!status.authenticated) {
      throw new ApiError(
        'unauthorized',
        'The server could not establish a session.',
        401,
      );
    }
    return status;
  }

  logout(signal: AbortSignal): Promise<void> {
    return this.api.json('/api/auth/logout', parseOk, {
      method: 'POST',
      signal,
    });
  }
}
