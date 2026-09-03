import assert from "node:assert/strict";

import type { APIRequestContext, Page } from "@playwright/test";
import { expect, test as base } from "@playwright/test";

export type MultiWorkerScenario =
  | "cross_worker_resume"
  | "cross_worker_cancel"
  | "cross_worker_reply"
  | "owner_loss"
  | "reload_replay"
  | "foreign_observation";

interface RuntimeStatus {
  worker_count?: number;
  coordination?: { backend?: string; healthy?: boolean };
  redis?: { configured?: boolean; healthy?: boolean };
}

interface ArmedScenario {
  scenario_id: string;
  prompt: string;
  expected_turn_id?: string;
}

export interface ScenarioEvidence {
  scenario_id: string;
  connection_workers: string[];
  command_workers?: string[];
  owner_worker?: string;
  recovery_worker?: string;
  observed_states?: string[];
  emitted_sequences: number[];
  delivered_sequences: number[];
  duplicate_count: number;
  gap_count: number;
  terminal_status?: string;
  failure_code?: string;
  retryable?: boolean;
}

const DEFAULT_CONTROL_PATH = "/__e2e__/v2-turn-runtime";

export const multiWorkerFixtureAvailable =
  process.env.DEEPTUTOR_MULTI_WORKER_E2E === "1";

function fixtureBaseUrl(): string {
  return (
    process.env.DEEPTUTOR_MULTI_WORKER_CONTROL_URL ||
    process.env.NEXT_PUBLIC_API_BASE ||
    process.env.WEB_BASE_URL ||
    "http://127.0.0.1:8001"
  ).replace(/\/$/, "");
}

export class MultiWorkerRuntimeFixture {
  private readonly baseUrl = fixtureBaseUrl();
  private readonly controlPath =
    process.env.DEEPTUTOR_MULTI_WORKER_CONTROL_PATH || DEFAULT_CONTROL_PATH;
  private legacyRequests: string[] = [];

  constructor(private readonly request: APIRequestContext) {}

  trackNetwork(page: Page): void {
    page.on("request", (request) => {
      const pathname = new URL(request.url()).pathname;
      if (pathname === "/api/chat" || pathname.startsWith("/api/chat/")) {
        this.legacyRequests.push(request.url());
      }
    });
  }

  async assertReady(): Promise<void> {
    const response = await this.request.get(
      `${this.baseUrl}/api/system/runtime`,
    );
    expect(
      response.ok(),
      "runtime status endpoint must be reachable",
    ).toBeTruthy();
    const status = (await response.json()) as RuntimeStatus;
    expect(
      status.worker_count,
      "browser acceptance requires exactly four workers",
    ).toBe(4);
    expect(
      status.coordination?.backend,
      "browser acceptance requires Redis coordination",
    ).toBe("redis");
    expect(
      status.coordination?.healthy ?? status.redis?.healthy,
      "Redis coordination must be healthy",
    ).toBe(true);

    const fixture = await this.request.get(this.controlUrl("health"));
    expect(
      fixture.ok(),
      "the deterministic failure-injection fixture must be enabled",
    ).toBeTruthy();
    const fixtureStatus = (await fixture.json()) as { worker_ids?: string[] };
    expect(fixtureStatus.worker_ids).toHaveLength(4);
  }

  async reset(): Promise<void> {
    this.legacyRequests = [];
    const response = await this.request.post(this.controlUrl("reset"));
    expect(response.ok(), "fixture reset failed").toBeTruthy();
  }

  async arm(
    scenario: MultiWorkerScenario,
    options: Record<string, unknown> = {},
  ): Promise<ArmedScenario> {
    const response = await this.request.post(this.controlUrl("scenarios"), {
      data: { scenario, ...options },
    });
    expect(response.ok(), `could not arm ${scenario}`).toBeTruthy();
    return (await response.json()) as ArmedScenario;
  }

  async act(scenarioId: string, action: string): Promise<void> {
    const response = await this.request.post(
      this.controlUrl(`scenarios/${encodeURIComponent(scenarioId)}/actions`),
      { data: { action } },
    );
    expect(response.ok(), `fixture action ${action} failed`).toBeTruthy();
  }

  async evidence(scenarioId: string): Promise<ScenarioEvidence> {
    const response = await this.request.get(
      this.controlUrl(`scenarios/${encodeURIComponent(scenarioId)}/evidence`),
    );
    expect(response.ok(), "fixture evidence is unavailable").toBeTruthy();
    return (await response.json()) as ScenarioEvidence;
  }

  async expectEvidence(
    scenarioId: string,
    predicate: (evidence: ScenarioEvidence) => boolean,
    description: string,
  ): Promise<ScenarioEvidence> {
    let latest: ScenarioEvidence | undefined;
    await expect
      .poll(
        async () => {
          latest = await this.evidence(scenarioId);
          return predicate(latest);
        },
        { message: description, timeout: 60_000 },
      )
      .toBe(true);
    assert(latest);
    return latest;
  }

  assertNoLegacyRequests(): void {
    assert.deepEqual(
      this.legacyRequests,
      [],
      `the browser requested retired chat endpoints: ${this.legacyRequests.join(", ")}`,
    );
  }

  private controlUrl(suffix: string): string {
    return `${this.baseUrl}${this.controlPath}/${suffix}`;
  }
}

export const test = base.extend<{ runtimeFixture: MultiWorkerRuntimeFixture }>({
  runtimeFixture: async ({ request, page }, provide) => {
    const fixture = new MultiWorkerRuntimeFixture(request);
    fixture.trackNetwork(page);
    await fixture.assertReady();
    await fixture.reset();
    await provide(fixture);
    fixture.assertNoLegacyRequests();
  },
});

export { expect };

export async function sendPrompt(page: Page, prompt: string): Promise<void> {
  const composer = page.getByRole("textbox").last();
  await expect(composer).toBeVisible();
  await composer.fill(prompt);
  await composer.press("Enter");
}

export function assistantActivity(page: Page) {
  return page.locator('[aria-live="polite"]').filter({
    hasText:
      /DeepTutor (?:Exploring|Reasoning|Planning|Quizzing|Reflecting|responded)|Tool Calling/i,
  });
}
