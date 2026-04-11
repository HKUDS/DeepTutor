export const runtime = 'nodejs';

import { readFile } from 'node:fs/promises';
import { homedir } from 'node:os';
import path from 'node:path';
import { NextResponse } from 'next/server';
import { serializeCodexCredential } from '@/lib/codexCredential';

export async function POST() {
  if (process.env.NODE_ENV === 'production') {
    return NextResponse.json(
      { error: 'Local session import is disabled in production' },
      { status: 403 },
    );
  }

  try {
    const authFilePath = path.join(homedir(), '.codex', 'auth.json');
    const raw = await readFile(authFilePath, 'utf-8');
    const parsed = JSON.parse(raw) as {
      tokens?: { access_token?: string; refresh_token?: string; expires_at?: number };
    };

    const accessToken = parsed?.tokens?.access_token;
    if (!accessToken) {
      return NextResponse.json(
        { error: 'No access_token found in ~/.codex/auth.json' },
        { status: 400 },
      );
    }

    const apiKey = serializeCodexCredential({
      accessToken,
      refreshToken: parsed.tokens?.refresh_token,
      // codex auth.json stores expires_at as a unix timestamp in seconds
      expiresAt: parsed.tokens?.expires_at ? parsed.tokens.expires_at * 1000 : undefined,
    });

    return NextResponse.json({ apiKey });
  } catch (err) {
    const message = err instanceof Error ? err.message : 'Could not read ~/.codex/auth.json';
    const notFound = message.includes('ENOENT');
    return NextResponse.json(
      {
        error: notFound
          ? 'Run `codex auth` first to create ~/.codex/auth.json'
          : message,
      },
      { status: 400 },
    );
  }
}
