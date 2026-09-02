import {
  expect,
  lifecycleStatus,
  multiWorkerFixtureAvailable,
  sendPrompt,
  test,
} from "./fixtures/runtime";

test.describe("four-worker v2 turn acceptance", () => {
  test.skip(
    !multiWorkerFixtureAvailable,
    "Set DEEPTUTOR_MULTI_WORKER_E2E=1 and connect the deterministic four-worker fixture.",
  );

  test.beforeEach(async ({ page }) => {
    await page.emulateMedia({ reducedMotion: "reduce" });
    await page.goto("/");
  });

  test("resumes through another worker without gaps or duplicates", async ({
    page,
    runtimeFixture,
  }) => {
    const scenario = await runtimeFixture.arm("cross_worker_resume", {
      owner_worker: "worker-a",
      reconnect_worker: "worker-b",
      disconnect_after_seq: 2,
    });
    await sendPrompt(page, scenario.prompt);

    await expect(lifecycleStatus(page)).toContainText(/Working/i);
    await runtimeFixture.act(scenario.scenario_id, "drop_socket");
    await expect(lifecycleStatus(page)).toContainText(/Reconnecting/i);
    await expect(lifecycleStatus(page)).toContainText(/Working|Completed/i);

    const evidence = await runtimeFixture.expectEvidence(
      scenario.scenario_id,
      (value) => value.terminal_status === "completed",
      "the resumed turn did not complete",
    );
    expect(evidence.connection_workers).toEqual(
      expect.arrayContaining(["worker-a", "worker-b"]),
    );
    expect(evidence.delivered_sequences).toEqual(evidence.emitted_sequences);
    expect(evidence.duplicate_count).toBe(0);
    expect(evidence.gap_count).toBe(0);
  });

  test("keeps cancellation pending until worker C acknowledges it", async ({
    page,
    runtimeFixture,
  }) => {
    const scenario = await runtimeFixture.arm("cross_worker_cancel", {
      owner_worker: "worker-a",
      command_worker: "worker-c",
    });
    await sendPrompt(page, scenario.prompt);
    await expect(lifecycleStatus(page)).toContainText(/Working/i);
    await page.getByRole("button", { name: /stop/i }).click();
    await expect(lifecycleStatus(page)).toContainText(/Stopping/i);

    const evidence = await runtimeFixture.expectEvidence(
      scenario.scenario_id,
      (value) => value.terminal_status === "cancelled",
      "the owner did not acknowledge cancellation",
    );
    expect(evidence.command_workers).toContain("worker-c");
    await expect(lifecycleStatus(page)).toContainText(/Stopped/i);
  });

  test("replies through worker D and completes the same waiting turn", async ({
    page,
    runtimeFixture,
  }) => {
    const scenario = await runtimeFixture.arm("cross_worker_reply", {
      owner_worker: "worker-a",
      command_worker: "worker-d",
    });
    await sendPrompt(page, scenario.prompt);
    await expect(lifecycleStatus(page)).toContainText(
      /Waiting for your answer/i,
    );

    const answer = page.getByRole("textbox", { name: /answer/i });
    await answer.fill("Continue on the same turn");
    await page.getByRole("button", { name: /answer|submit/i }).click();
    await expect(lifecycleStatus(page)).toContainText(/Working|Completed/i);

    const evidence = await runtimeFixture.expectEvidence(
      scenario.scenario_id,
      (value) => value.terminal_status === "completed",
      "the answered turn did not complete",
    );
    expect(evidence.command_workers).toContain("worker-d");
    expect(evidence.gap_count).toBe(0);
  });

  test("surfaces owner loss as retryable and regenerates elsewhere", async ({
    page,
    runtimeFixture,
  }) => {
    const scenario = await runtimeFixture.arm("owner_loss", {
      owner_worker: "worker-a",
      recovery_worker: "worker-b",
    });
    await sendPrompt(page, scenario.prompt);
    await expect(lifecycleStatus(page)).toContainText(/Working/i);
    await runtimeFixture.act(scenario.scenario_id, "kill_owner");
    await expect(lifecycleStatus(page)).toContainText(/Response interrupted/i, {
      timeout: 45_000,
    });

    const failed = await runtimeFixture.expectEvidence(
      scenario.scenario_id,
      (value) => value.failure_code === "worker_lost",
      "owner loss was not recovered into a stable failure",
    );
    expect(failed.retryable).toBe(true);
    await page.getByRole("button", { name: /retry|regenerate/i }).click();
    await expect(lifecycleStatus(page)).toContainText(/Working|Completed/i);
    await runtimeFixture.expectEvidence(
      scenario.scenario_id,
      (value) =>
        value.terminal_status === "completed" &&
        value.recovery_worker === "worker-b",
      "regeneration did not move to the recovery worker",
    );
  });

  test("reloads mid-stream and replays only events after the saved cursor", async ({
    page,
    runtimeFixture,
  }) => {
    const scenario = await runtimeFixture.arm("reload_replay", {
      owner_worker: "worker-a",
      reload_worker: "worker-b",
    });
    await sendPrompt(page, scenario.prompt);
    await expect(lifecycleStatus(page)).toContainText(/Working/i);
    await runtimeFixture.act(scenario.scenario_id, "pause_after_checkpoint");
    await page.reload();
    await expect(lifecycleStatus(page)).toContainText(
      /Reconnecting|Working|Completed/i,
    );

    const evidence = await runtimeFixture.expectEvidence(
      scenario.scenario_id,
      (value) => value.terminal_status === "completed",
      "the reloaded turn did not complete",
    );
    expect(evidence.delivered_sequences).toEqual(evidence.emitted_sequences);
    expect(evidence.duplicate_count).toBe(0);
    expect(evidence.gap_count).toBe(0);
  });

  test("observing a turn through a non-owner never marks it failed", async ({
    page,
    runtimeFixture,
  }) => {
    const scenario = await runtimeFixture.arm("foreign_observation", {
      owner_worker: "worker-a",
      observer_worker: "worker-d",
    });
    await sendPrompt(page, scenario.prompt);
    await runtimeFixture.act(scenario.scenario_id, "query_from_observer");
    await expect(lifecycleStatus(page)).not.toContainText(
      /Turn failed|Response interrupted/i,
    );

    const evidence = await runtimeFixture.expectEvidence(
      scenario.scenario_id,
      (value) => value.terminal_status === "completed",
      "foreign observation changed the turn lifecycle",
    );
    expect(evidence.observed_states).not.toContain("failed");
    expect(evidence.owner_worker).toBe("worker-a");
  });
});
