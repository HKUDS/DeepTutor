export const runtime = "nodejs";

import { NextResponse } from "next/server";

const BACKEND_URL =
  process.env.NEXT_PUBLIC_API_BASE ||
  process.env.NEXT_PUBLIC_API_URL ||
  "http://localhost:8001";

type BackendStatus = {
  backend?: { status?: string; timestamp?: string };
  llm?: { status?: string; model?: string; error?: string };
};

type LlmTestResponse = {
  success?: boolean;
  message?: string;
  model?: string | null;
  response_time_ms?: number | null;
  error?: string | null;
};

export async function POST() {
  try {
    const statusRes = await fetch(`${BACKEND_URL}/api/v1/system/status`);
    if (!statusRes.ok) {
      return NextResponse.json(
        {
          ok: false,
          message: `Backend responded with ${statusRes.status} while checking status.`,
          backendUrl: BACKEND_URL,
        },
        { status: 502 },
      );
    }

    const statusPayload = (await statusRes.json()) as BackendStatus;
    const testRes = await fetch(`${BACKEND_URL}/api/v1/system/test/llm`, {
      method: "POST",
    });
    const testPayload = (await testRes.json()) as LlmTestResponse;

    return NextResponse.json({
      ok: Boolean(testPayload.success),
      backendUrl: BACKEND_URL,
      backendStatus: statusPayload.backend?.status ?? "unknown",
      llmStatus: statusPayload.llm?.status ?? "unknown",
      model: testPayload.model ?? statusPayload.llm?.model ?? null,
      responseTimeMs: testPayload.response_time_ms ?? null,
      message:
        testPayload.message ??
        statusPayload.llm?.error ??
        "LLM test did not return a message.",
      error: testPayload.error ?? statusPayload.llm?.error ?? null,
    });
  } catch (error) {
    const message = error instanceof Error ? error.message : "Unknown error";
    return NextResponse.json(
      {
        ok: false,
        message: `Could not reach backend at ${BACKEND_URL}.`,
        error: message,
        backendUrl: BACKEND_URL,
      },
      { status: 502 },
    );
  }
}
