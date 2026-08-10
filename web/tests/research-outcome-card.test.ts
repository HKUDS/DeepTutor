import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";
import path from "node:path";
import { extractResearchOutcome, researchOutcomeAction, researchOutcomeSurface, researchOutlineStatus, selectResearchResults, shouldShowResearchBody, suppressTerminalErrorForResearch } from "@/lib/research-outcome";

const root = path.resolve(process.cwd());
const card = readFileSync(path.join(root, "components/chat/home/ChatMessages.tsx"), "utf8");
const en = JSON.parse(readFileSync(path.join(root, "locales/en/app.json"), "utf8"));
const zh = JSON.parse(readFileSync(path.join(root, "locales/zh/app.json"), "utf8"));
const keys = [
  "Research complete", "Partially complete", "Research failed", "Open model settings",
  "Retry report", "Retry failed parts", "Retry research", "failed parts",
  "Research did not produce a usable result.", "Model", "Protocol", "Failure stage",
  "Technical details",
];

test("research outcome copy has English and Chinese coverage", () => {
  for (const key of keys) {
    assert.equal(typeof en[key], "string", `missing en ${key}`);
    assert.equal(typeof zh[key], "string", `missing zh ${key}`);
  }
});

test("research outcome card retains completed, partial, failed tones and CTA routing", () => {
  assert.match(card, /border-emerald-500/);
  assert.match(card, /border-amber-500/);
  assert.match(card, /border-red-500/);
  assert.match(card, /researchOutcomeAction/);
});

test("research outcome extractor reads real nested result metadata and legacy flat envelopes", () => {
  const nestedEvent = {
    type: "result",
    metadata: {
      response: "", output_dir: "",
      metadata: { outcome: "partial", attempt_id: "attempt_1", failure: { code: "report_generation_failed" } },
    },
  };
  const nested = extractResearchOutcome(nestedEvent.metadata);
  assert.equal(nested?.attempt_id, "attempt_1");
  assert.equal(nested?.failure && (nested.failure as { code: string }).code, "report_generation_failed");
  assert.equal(researchOutlineStatus(nested), "partial");
  assert.equal(researchOutlineStatus(extractResearchOutcome({ outcome: "completed" })), "done");
  assert.equal(extractResearchOutcome({ response: "legacy" }), null);
});

test("merged research timeline keeps outline first and selects terminal outcomes from the end", () => {
  const outline = { type: "result", metadata: { outline_preview: true, sub_topics: [{ title: "A" }] } };
  for (const outcome of ["completed", "partial", "failed"] as const) {
    const terminal = {
      type: "result",
      metadata: {
        response: "report",
        metadata: {
          outcome,
          attempt_id: `attempt_${outcome}`,
          failure: outcome === "completed" ? null : { code: "report_generation_failed" },
        },
      },
    };
    const selected = selectResearchResults([outline, terminal]);
    assert.equal(selected.outlineResult, outline);
    const extracted = extractResearchOutcome(selected.terminalOutcomeResult?.metadata);
    assert.equal(extracted?.attempt_id, `attempt_${outcome}`);
    assert.equal(researchOutlineStatus(extracted), outcome === "completed" ? "done" : outcome);
  }
});

test("outline-only and legacy result timelines have no terminal outcome", () => {
  const outline = { type: "result", metadata: { outline_preview: true } };
  assert.equal(selectResearchResults([outline]).outlineResult, outline);
  assert.equal(selectResearchResults([outline]).terminalOutcomeResult, null);
  assert.equal(selectResearchResults([{ type: "result", metadata: { response: "legacy" } }]).terminalOutcomeResult, null);
});

test("failure codes map to deliberate retry, settings, or no action", () => {
  const action = (code: string, outcome: "failed" | "partial" = "failed") => researchOutcomeAction({ outcome, failure: { code } });
  assert.deepEqual(action("model_output_incomplete"), { kind: "retry", strategy: "full_research", label: "Retry with higher budget" });
  assert.equal(action("model_output_empty").kind, "settings");
  assert.deepEqual(action("tool_stage_failed"), { kind: "retry", strategy: "failed_blocks", label: "Retry failed parts" });
  assert.deepEqual(action("report_generation_failed"), { kind: "retry", strategy: "report_only", label: "Retry report" });
  assert.equal(action("unknown").kind, "none");
});

test("research report body remains visible for completed and partial outcomes", () => {
  const completed = extractResearchOutcome({ outcome: "completed" });
  const partial = extractResearchOutcome({ outcome: "partial" });
  const failed = extractResearchOutcome({ outcome: "failed" });
  assert.equal(shouldShowResearchBody(true, "done", completed, "# Report"), true);
  assert.equal(shouldShowResearchBody(true, "partial", partial, "# Partial report"), true);
  assert.equal(shouldShowResearchBody(true, "failed", failed, ""), false);
  assert.equal(shouldShowResearchBody(true, "failed", failed, "Recovered body"), true);
  assert.equal(shouldShowResearchBody(false, "partial", partial, "# Report"), false);
});

test("failure reason and CTA are visible while diagnostics remain optional", () => {
  assert.deepEqual(researchOutcomeSurface({ outcome: "completed" }), {
    showReason: false, showAction: false, showDiagnostics: false,
  });
  assert.deepEqual(
    researchOutcomeSurface({ outcome: "partial", failure: { code: "tool_stage_failed" } }),
    { showReason: true, showAction: true, showDiagnostics: true },
  );
  assert.deepEqual(
    researchOutcomeSurface({ outcome: "failed", failure: { code: "model_output_empty" } }),
    { showReason: true, showAction: true, showDiagnostics: true },
  );
});

test("research terminal outcome suppresses only its duplicate generic error", () => {
  const failed = { type: "result", metadata: { metadata: { outcome: "failed", attempt_id: "attempt_1", failure: { code: "report_generation_failed" } } } };
  const matching = { type: "error", metadata: { turn_terminal: true, error_type: "ResearchTerminalError", failure_code: "report_generation_failed", attempt_id: "attempt_1" } };
  assert.equal(suppressTerminalErrorForResearch([failed, matching]), true);
  assert.equal(suppressTerminalErrorForResearch([failed, { ...matching, metadata: { ...matching.metadata, attempt_id: "attempt_2" } }]), false);
  assert.equal(suppressTerminalErrorForResearch([failed, { ...matching, metadata: { ...matching.metadata, failure_code: "persistence_failed" } }]), false);
  assert.equal(suppressTerminalErrorForResearch([{ type: "result", metadata: { metadata: { outcome: "completed", attempt_id: "attempt_1" } } }, matching]), false);
  assert.equal(suppressTerminalErrorForResearch([{ type: "result", metadata: { metadata: { outcome: "partial", attempt_id: "attempt_1", failure: { code: "tool_stage_failed" } } } }, matching]), false);
  assert.equal(suppressTerminalErrorForResearch([failed, { ...matching, metadata: { ...matching.metadata, error_type: "PersistenceError" } }]), false);
});
