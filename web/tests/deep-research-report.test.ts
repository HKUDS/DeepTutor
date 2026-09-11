import test from "node:test";
import assert from "node:assert/strict";
import type { StreamEvent } from "../features/chat/model/protocol";
import {
  authoritativeResearchReport,
  isConfirmedResearchFollowup,
  normalizeDeepResearchReportFormatting,
  researchFollowupStatus,
  shouldReturnToChatAfterResearch,
} from "../lib/deep-research-report";

function event(
  type: StreamEvent["type"],
  options: Partial<StreamEvent> = {},
): StreamEvent {
  return { type, source: "deep_research", ...options } as StreamEvent;
}

test("repairs a legacy report title joined directly to its first section", () => {
  assert.equal(
    normalizeDeepResearchReportFormatting("# 报告标题## 1. 引言\n\n正文。"),
    "# 报告标题\n\n## 1. 引言\n\n正文。",
  );
  assert.equal(
    normalizeDeepResearchReportFormatting("# 报告标题\n\n## 1. 引言"),
    "# 报告标题\n\n## 1. 引言",
  );
});

test("only a confirmed research run may merge with an outline preview", () => {
  const reportEvents = [
    event("stage_start", { stage: "researching" }),
    event("result", { metadata: { response: "# Full report" } }),
  ];
  const regeneratedOutline = [
    event("stage_start", { stage: "decomposing" }),
    event("result", { metadata: { outline_preview: true } }),
  ];

  assert.equal(isConfirmedResearchFollowup(reportEvents), true);
  assert.equal(isConfirmedResearchFollowup(regeneratedOutline), false);
});

test("the normalized result response wins over malformed streamed content", () => {
  const events = [
    event("result", {
      metadata: { response: "# Report\n\n## 1. Introduction\n\nComplete." },
    }),
  ];
  assert.equal(
    authoritativeResearchReport(events, "# Report## 1. Introduction"),
    "# Report\n\n## 1. Introduction\n\nComplete.",
  );
});

test("a terminal confirmed research run returns the composer to chat", () => {
  const events = [
    event("stage_start", { stage: "reporting", turn_id: "turn_report" }),
    event("done", {
      turn_id: "turn_report",
      metadata: { status: "completed" },
    }),
  ];
  assert.equal(shouldReturnToChatAfterResearch(events), true);
  assert.equal(
    shouldReturnToChatAfterResearch([
      event("result", { metadata: { outline_preview: true } }),
      event("done", { metadata: { status: "completed" } }),
    ]),
    false,
  );
});

test("a completed turn with a structurally truncated report is shown as failed", () => {
  const incomplete = [
    event("stage_start", { stage: "reporting" }),
    event("result", {
      metadata: { response: "# Report\n\n## 1. Introduction\n\nThis cuts off" },
    }),
    event("done", { metadata: { status: "completed" } }),
  ];
  const complete = [
    event("stage_start", { stage: "reporting" }),
    event("result", {
      metadata: {
        response:
          "# Report\n\n## 1. Introduction\n\nIntro.\n\n## 2. Findings\n\nEvidence.\n\n## 3. Conclusion\n\nDone.",
      },
    }),
    event("done", { metadata: { status: "completed" } }),
  ];

  assert.equal(researchFollowupStatus(incomplete), "failed");
  assert.equal(researchFollowupStatus(complete), "done");
});
