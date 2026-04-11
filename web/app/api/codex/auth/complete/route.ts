export const runtime = 'nodejs';

import { cookies } from 'next/headers';
import { NextRequest, NextResponse } from 'next/server';
import { exchangeCodeForTokens, tokenSetToSerializedCredential } from '@/lib/server/codex';

export async function POST(req: NextRequest) {
  try {
    const { callbackUrl } = (await req.json()) as { callbackUrl?: string };
    if (!callbackUrl?.trim()) {
      return NextResponse.json({ error: 'callbackUrl is required' }, { status: 400 });
    }

    const cookieStore = await cookies();
    const ctxCookie = cookieStore.get('codex_oauth_ctx');
    if (!ctxCookie?.value) {
      return NextResponse.json(
        { error: 'OAuth context cookie missing — start the flow again' },
        { status: 400 },
      );
    }

    const { state: storedState, codeVerifier } = JSON.parse(ctxCookie.value) as {
      state: string;
      codeVerifier: string;
    };

    const url = new URL(callbackUrl.trim());
    const code = url.searchParams.get('code');
    const returnedState = url.searchParams.get('state');

    if (!code) {
      return NextResponse.json({ error: 'No auth code in callback URL' }, { status: 400 });
    }
    if (returnedState !== storedState) {
      return NextResponse.json({ error: 'OAuth state mismatch — possible CSRF' }, { status: 400 });
    }

    const tokens = await exchangeCodeForTokens(code, codeVerifier);
    const apiKey = tokenSetToSerializedCredential(tokens);

    // Clear the oauth context cookie
    cookieStore.delete('codex_oauth_ctx');

    return NextResponse.json({ apiKey });
  } catch (err) {
    const message = err instanceof Error ? err.message : 'Could not complete Codex auth';
    return NextResponse.json({ error: message }, { status: 500 });
  }
}
