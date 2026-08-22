import test from "node:test";
import assert from "node:assert/strict";

import {
  appendTaskLog,
  taskStateAfterProgress,
  type TaskState,
} from "../hooks/useKnowledgeProgress";

const running: TaskState = {
  taskId: "task-1",
  kind: "create",
  label: "Create KB",
  logs: ["Queued"],
  executing: true,
  error: null,
};

test("progress messages append once and complete the active task", () => {
  assert.deepEqual(appendTaskLog(["Queued"], "Indexing"), [
    "Queued",
    "Indexing",
  ]);
  assert.deepEqual(appendTaskLog(["Queued", "Indexing"], "Indexing"), [
    "Queued",
    "Indexing",
  ]);

  const completed = taskStateAfterProgress(running, "task-1", {
    task_id: "task-1",
    stage: "completed",
    message: "Index ready",
  });
  assert.equal(completed.executing, false);
  assert.equal(completed.error, null);
  assert.deepEqual(completed.logs, ["Queued", "Index ready"]);
});

test("progress from another task cannot overwrite current state", () => {
  assert.equal(
    taskStateAfterProgress(running, "task-2", {
      task_id: "task-2",
      stage: "error",
      error: "wrong task",
    }),
    running,
  );
});

test("translates a templated progress line and falls back without one", () => {
  const t = (key: string, options?: Record<string, unknown>) =>
    key === "Describing images: {{current}}/{{total}}"
      ? `图片描述：${options?.current}/${options?.total}`
      : key;

  const translated = taskStateAfterProgress(
    { ...running, logs: [] },
    "task-1",
    {
      task_id: "task-1",
      stage: "processing_documents",
      message: "Describing images: 3/7",
      message_key: "Describing images: {{current}}/{{total}}",
      message_params: { current: 3, total: 7 },
    },
    t,
  );
  assert.deepEqual(translated.logs, ["图片描述：3/7"]);

  // A producer that has not been converted still shows its rendered English.
  const legacy = taskStateAfterProgress(
    { ...running, logs: [] },
    "task-1",
    { task_id: "task-1", stage: "processing_documents", message: "Saving…" },
    t,
  );
  assert.deepEqual(legacy.logs, ["Saving…"]);
});
