import { ApiClient, ApiError } from '../../services/apiClient';

export interface AuthStatus {
  enabled: boolean;
  authenticated: boolean;
}

function parseStatus(value: unknown): AuthStatus {
  if (!value || typeof value !== 'object') {
    throw new Error('Expected an authentication status');
  }
  const record = value as Record<string, unknown>;
  if (
    typeof record.enabled !== 'boolean' ||
    typeof record.authenticated !== 'boolean' ||
    (record.enabled === false && record.authenticated === false)
  ) {
    throw new Error('Invalid authentication status');
  }
  return {
    enabled: record.enabled,
    authenticated: record.authenticated,
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
        return { enabled: true, authenticated: false };
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
