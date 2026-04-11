export const runtime = 'nodejs';

import { cookies } from 'next/headers';
import { NextResponse } from 'next/server';
import { buildAuthUrl, generatePKCEPair, generateState } from '@/lib/server/codex';

export async function POST() {
  try {
    const { codeVerifier, codeChallenge } = generatePKCEPair();
    const state = generateState();

    const authUrl = buildAuthUrl(state, codeChallenge);

    // Store PKCE context in httpOnly cookie (10 min TTL)
    const cookieStore = await cookies();
    cookieStore.set('codex_oauth_ctx', JSON.stringify({ state, codeVerifier }), {
      httpOnly: true,
      secure: process.env.NODE_ENV === 'production',
      sameSite: 'lax',
      maxAge: 600,
      path: '/',
    });

    return NextResponse.json({ authUrl });
  } catch (err) {
    const message = err instanceof Error ? err.message : 'Could not start Codex auth';
    return NextResponse.json({ error: message }, { status: 500 });
  }
}
