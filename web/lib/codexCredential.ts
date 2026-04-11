export type CodexCredential = {
  accessToken: string;
  refreshToken?: string;
  expiresAt?: number; // ms epoch
};

/**
 * Accepts both a bare token string and a serialized JSON CodexCredential.
 */
export function parseCodexCredential(apiKey: string): CodexCredential | null {
  const trimmed = apiKey.trim();
  if (!trimmed) return null;

  if (!trimmed.startsWith('{')) {
    return { accessToken: trimmed };
  }

  try {
    const parsed = JSON.parse(trimmed) as Partial<CodexCredential>;
    if (!parsed || typeof parsed.accessToken !== 'string' || !parsed.accessToken.trim()) {
      return null;
    }
    return {
      accessToken: parsed.accessToken,
      refreshToken: typeof parsed.refreshToken === 'string' ? parsed.refreshToken : undefined,
      expiresAt: typeof parsed.expiresAt === 'number' ? parsed.expiresAt : undefined,
    };
  } catch {
    return null;
  }
}

export function serializeCodexCredential(credential: CodexCredential): string {
  return JSON.stringify({
    accessToken: credential.accessToken,
    refreshToken: credential.refreshToken,
    expiresAt: credential.expiresAt,
  });
}

export function isCodexCredentialExpired(credential: CodexCredential, skewMs = 30_000): boolean {
  if (!credential.expiresAt) return false;
  return Date.now() + skewMs >= credential.expiresAt;
}
