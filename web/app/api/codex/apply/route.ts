export const runtime = 'nodejs';

import { NextRequest, NextResponse } from 'next/server';

const BACKEND_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8001';

/**
 * POST /api/codex/apply
 *
 * Accepts { apiKey, model } and writes an openai_codex binding profile
 * into the backend catalog, then applies it to .env.
 *
 * This bridges the frontend-only OAuth credential into the backend LLM pipeline.
 */
export async function POST(req: NextRequest) {
  try {
    const { apiKey, model } = (await req.json()) as {
      apiKey?: string;
      model?: string;
    };

    if (!apiKey?.trim()) {
      return NextResponse.json({ error: 'apiKey is required' }, { status: 400 });
    }

    const effectiveModel = model?.trim() || 'gpt-5.3-codex';

    // 1. Fetch current settings from backend
    const settingsRes = await fetch(`${BACKEND_URL}/api/v1/settings`);
    if (!settingsRes.ok) {
      return NextResponse.json(
        { error: 'Could not read current settings from backend' },
        { status: 502 },
      );
    }
    const settings = (await settingsRes.json()) as {
      catalog: {
        version: number;
        services: {
          llm: {
            active_profile_id: string | null;
            active_model_id?: string | null;
            profiles: Array<{
              id: string;
              name: string;
              binding?: string;
              base_url: string;
              api_key: string;
              api_version: string;
              models: Array<{ id: string; name: string; model: string }>;
            }>;
          };
          embedding: unknown;
          search: unknown;
        };
      };
    };

    const catalog = settings.catalog;
    const llmService = catalog.services.llm;

    // 2. Find or create the Codex profile
    const CODEX_PROFILE_ID = 'codex-session';
    const CODEX_MODEL_ID = 'codex-model';

    let codexProfile = llmService.profiles.find((p) => p.id === CODEX_PROFILE_ID);

    if (codexProfile) {
      // Update existing
      codexProfile.api_key = apiKey;
      codexProfile.binding = 'openai_codex';
      codexProfile.base_url = 'https://chatgpt.com/backend-api';
      const existingModel = codexProfile.models.find((m) => m.id === CODEX_MODEL_ID);
      if (existingModel) {
        existingModel.model = effectiveModel;
        existingModel.name = effectiveModel;
      } else {
        codexProfile.models = [
          { id: CODEX_MODEL_ID, name: effectiveModel, model: effectiveModel },
        ];
      }
    } else {
      // Create new
      codexProfile = {
        id: CODEX_PROFILE_ID,
        name: 'Codex Session',
        binding: 'openai_codex',
        base_url: 'https://chatgpt.com/backend-api',
        api_key: apiKey,
        api_version: '',
        models: [
          { id: CODEX_MODEL_ID, name: effectiveModel, model: effectiveModel },
        ],
      };
      llmService.profiles.push(codexProfile);
    }

    // 3. Set as active
    llmService.active_profile_id = CODEX_PROFILE_ID;
    llmService.active_model_id = CODEX_MODEL_ID;

    // 4. Apply to backend (.env + runtime)
    const applyRes = await fetch(`${BACKEND_URL}/api/v1/settings/apply`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ catalog }),
    });

    if (!applyRes.ok) {
      const errorText = await applyRes.text();
      return NextResponse.json(
        { error: `Backend apply failed: ${errorText}` },
        { status: 502 },
      );
    }

    const applied = await applyRes.json();
    return NextResponse.json({
      ok: true,
      catalog: applied.catalog,
      model: effectiveModel,
    });
  } catch (err) {
    const message = err instanceof Error ? err.message : 'Could not apply Codex config';
    return NextResponse.json({ error: message }, { status: 500 });
  }
}

/**
 * DELETE /api/codex/apply
 *
 * Remove the Codex profile and fall back to the first available profile.
 */
export async function DELETE() {
  try {
    const settingsRes = await fetch(`${BACKEND_URL}/api/v1/settings`);
    if (!settingsRes.ok) {
      return NextResponse.json(
        { error: 'Could not read current settings' },
        { status: 502 },
      );
    }
    const settings = (await settingsRes.json()) as {
      catalog: {
        version: number;
        services: {
          llm: {
            active_profile_id: string | null;
            active_model_id?: string | null;
            profiles: Array<{
              id: string;
              models: Array<{ id: string }>;
            }>;
          };
          embedding: unknown;
          search: unknown;
        };
      };
    };

    const catalog = settings.catalog;
    const llmService = catalog.services.llm;

    // Remove the codex profile
    llmService.profiles = llmService.profiles.filter(
      (p) => p.id !== 'codex-session',
    );

    // Fall back to first remaining profile
    if (llmService.active_profile_id === 'codex-session') {
      const fallback = llmService.profiles[0];
      llmService.active_profile_id = fallback?.id ?? null;
      llmService.active_model_id = fallback?.models?.[0]?.id ?? null;
    }

    const applyRes = await fetch(`${BACKEND_URL}/api/v1/settings/apply`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ catalog }),
    });

    if (!applyRes.ok) {
      const errorText = await applyRes.text();
      return NextResponse.json(
        { error: `Backend apply failed: ${errorText}` },
        { status: 502 },
      );
    }

    return NextResponse.json({ ok: true });
  } catch (err) {
    const message = err instanceof Error ? err.message : 'Could not remove Codex config';
    return NextResponse.json({ error: message }, { status: 500 });
  }
}
