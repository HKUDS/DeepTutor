/**
 * Core Codex server library — Node-only (uses node:crypto).
 * Mark any route importing this as:  export const runtime = 'nodejs';
 */
import { createHash, randomBytes } from 'node:crypto';
import { parseCodexCredential, serializeCodexCredential, isCodexCredentialExpired } from '../codexCredential';

// ─── Constants ────────────────────────────────────────────────────────────────
// These match the openai/codex CLI — do NOT change them.
export const CODEX_API_ENDPOINT = 'https://chatgpt.com/backend-api/codex/responses';
const AUTH_URL = 'https://auth.openai.com/oauth/authorize';
const TOKEN_URL = 'https://auth.openai.com/oauth/token';
const CLIENT_ID = 'app_EMoamEEZ73f0CkXaXp7hrann';
export const REDIRECT_URI = 'http://localhost:1455/auth/callback';
const SCOPES = ['openid', 'profile', 'email', 'offline_access'];
export const DEFAULT_MODEL = 'gpt-5.3-codex';

// ─── Model normalisation ──────────────────────────────────────────────────────
const MODEL_ALIASES: Record<string, string> = {
  'codex': 'gpt-5.3-codex',
  'codex-mini': 'gpt-5-codex-mini',
  'codex-mini-latest': 'gpt-5-codex-mini',
};

export function normalizeModel(model: string): string {
  const stripped = model.replace(/^openai\//, '').trim();
  return MODEL_ALIASES[stripped] ?? stripped;
}

// ─── PKCE helpers ─────────────────────────────────────────────────────────────
export function generatePKCEPair(): { codeVerifier: string; codeChallenge: string } {
  const codeVerifier = randomBytes(32).toString('base64url');
  const codeChallenge = createHash('sha256').update(codeVerifier).digest('base64url');
  return { codeVerifier, codeChallenge };
}

export function generateState(): string {
  return randomBytes(16).toString('hex');
}

export function buildAuthUrl(state: string, codeChallenge: string): string {
  const params = new URLSearchParams({
    response_type: 'code',
    client_id: CLIENT_ID,
    redirect_uri: REDIRECT_URI,
    scope: SCOPES.join(' '),
    state,
    code_challenge: codeChallenge,
    code_challenge_method: 'S256',
  });
  return `${AUTH_URL}?${params.toString()}`;
}

// ─── Token exchange ───────────────────────────────────────────────────────────
export interface TokenSet {
  access_token: string;
  refresh_token?: string;
  expires_in?: number;
}

export async function exchangeCodeForTokens(
  code: string,
  codeVerifier: string,
): Promise<TokenSet> {
  const body = new URLSearchParams({
    grant_type: 'authorization_code',
    client_id: CLIENT_ID,
    code,
    redirect_uri: REDIRECT_URI,
    code_verifier: codeVerifier,
  });

  const res = await fetch(TOKEN_URL, {
    method: 'POST',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    body: body.toString(),
  });

  if (!res.ok) {
    const text = await res.text().catch(() => '');
    throw new Error(`Token exchange failed (${res.status}): ${text}`);
  }
  return res.json() as Promise<TokenSet>;
}

export async function refreshAccessToken(refreshToken: string): Promise<TokenSet> {
  const body = new URLSearchParams({
    grant_type: 'refresh_token',
    client_id: CLIENT_ID,
    refresh_token: refreshToken,
  });

  const res = await fetch(TOKEN_URL, {
    method: 'POST',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    body: body.toString(),
  });

  if (!res.ok) {
    const text = await res.text().catch(() => '');
    throw new Error(`Token refresh failed (${res.status}): ${text}`);
  }
  return res.json() as Promise<TokenSet>;
}

export function tokenSetToSerializedCredential(tokens: TokenSet): string {
  return serializeCodexCredential({
    accessToken: tokens.access_token,
    refreshToken: tokens.refresh_token,
    expiresAt: tokens.expires_in ? Date.now() + tokens.expires_in * 1000 : undefined,
  });
}

// ─── Input message types ──────────────────────────────────────────────────────
export type CodexContentPart =
  | { type: 'input_text'; text: string }
  | { type: 'output_text'; text: string }
  | { type: 'input_image'; image_url: string; detail?: 'low' | 'high' | 'auto' };

export type CodexInputMessage = {
  role: 'user' | 'assistant' | 'system';
  content: CodexContentPart[];
};

// ─── Core request function ────────────────────────────────────────────────────
const IDLE_TIMEOUT_MS = 60_000;

export async function requestCodexResponse(options: {
  apiKey: string;
  model: string;
  input: CodexInputMessage[];
  reasoningEffort?: 'low' | 'medium' | 'high';
  instructions?: string;
  debugLabel?: string;
}): Promise<{ text: string; tokenUpdate?: string }> {
  const {
    apiKey,
    model,
    input,
    reasoningEffort = 'high',
    instructions,
    debugLabel = 'codex',
  } = options;

  const credential = parseCodexCredential(apiKey);
  if (!credential) throw new Error(`[${debugLabel}] Invalid Codex credential`);

  // Auto-refresh if expired
  let currentCredential = credential;
  let tokenUpdate: string | undefined;

  if (isCodexCredentialExpired(currentCredential) && currentCredential.refreshToken) {
    console.log(`[${debugLabel}] Token expired, refreshing...`);
    const tokens = await refreshAccessToken(currentCredential.refreshToken);
    tokenUpdate = tokenSetToSerializedCredential(tokens);
    currentCredential = parseCodexCredential(tokenUpdate)!;
  }

  const doRequest = async (cred: typeof currentCredential) => {
    const body: Record<string, unknown> = {
      model: normalizeModel(model),
      input,
      reasoning: { effort: reasoningEffort },
      stream: true,
      store: false,
    };
    if (instructions) body.instructions = instructions;

    const res = await fetch(CODEX_API_ENDPOINT, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${cred.accessToken}`,
        'openai-beta': 'responses=v1',
      },
      body: JSON.stringify(body),
    });

    return res;
  };

  let res = await doRequest(currentCredential);

  // 401 → try token refresh once
  if (res.status === 401 && currentCredential.refreshToken) {
    console.log(`[${debugLabel}] 401, attempting token refresh...`);
    const tokens = await refreshAccessToken(currentCredential.refreshToken);
    tokenUpdate = tokenSetToSerializedCredential(tokens);
    currentCredential = parseCodexCredential(tokenUpdate)!;
    res = await doRequest(currentCredential);
  }

  if (!res.ok) {
    const body = await res.text().catch(() => '');
    throw new Error(`Codex API error (${res.status}): ${body}`);
  }

  // Stream SSE
  const reader = res.body?.getReader();
  if (!reader) throw new Error('No response body from Codex API');

  const decoder = new TextDecoder();
  let buffer = '';
  let lastChunkAt = Date.now();
  let fullText = '';

  while (true) {
    if (Date.now() - lastChunkAt > IDLE_TIMEOUT_MS) {
      reader.cancel();
      throw new Error(`[${debugLabel}] Codex stream idle timeout`);
    }

    const { done, value } = await reader.read();
    if (done) break;
    lastChunkAt = Date.now();
    buffer += decoder.decode(value, { stream: true });

    const lines = buffer.split('\n');
    buffer = lines.pop() ?? '';

    for (const raw of lines) {
      const line = raw.trim();
      if (!line.startsWith('data: ')) continue;
      const data = line.slice(6);
      if (data === '[DONE]') break;

      try {
        const event = JSON.parse(data) as {
          type?: string;
          delta?: { text?: string } | string;
          text?: string;
          response?: {
            output?: Array<{
              content?: Array<{ type?: string; text?: string }>;
            }>;
          };
        };
        if (event.type === 'response.output_text.delta') {
          if (typeof event.delta === 'string' && event.delta) {
            fullText += event.delta;
          } else if (event.delta && typeof event.delta === 'object' && event.delta.text) {
            fullText += event.delta.text;
          }
        } else if (event.type === 'response.output_text.done' && event.text) {
          fullText = event.text;
        } else if (event.type === 'response.completed' && event.response?.output) {
          const parts = event.response.output.flatMap((item) =>
            (item.content ?? [])
              .filter((block) => block.type === 'output_text' && block.text)
              .map((block) => block.text as string),
          );
          if (parts.length) {
            fullText = parts.join('');
          }
        }
      } catch {
        // ignore malformed events
      }
    }
  }

  return { text: fullText, tokenUpdate };
}
