import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it } from "vitest";

import { extractMessageSegments } from "@/components/chat/home/AskUserOptions";
import type { StreamEvent } from "@/features/chat/model/protocol";
import { TraceFlow } from "@/features/chat/trace/TracePresentation";
import { initI18n } from "@/i18n/init";

initI18n("en");

const event = (type: StreamEvent["type"], content: string): StreamEvent =>
  ({
    type,
    content,
    source: "chat",
    stage: "exploring",
    timestamp: 1,
    metadata: {
      call_id: "round-1",
      call_kind: "agent_loop_round",
      call_state: "running",
    },
  }) as StreamEvent;

it("folds reasoning when answer streaming starts and allows reopening", async () => {
  const thinking = event("thinking", "Let me consider the question.");
  const traceEvents = (events: StreamEvent[]) => {
    const trace = extractMessageSegments(events, "", { streaming: true }).find(
      (segment) => segment.kind === "trace",
    );
    return trace?.kind === "trace" ? trace.events : [];
  };
  const { rerender } = render(
    <TraceFlow events={traceEvents([thinking])} isStreaming />,
  );
  expect(screen.getByRole("button")).toHaveAttribute("aria-expanded", "true");

  const answering = [thinking, event("content", " ")];
  rerender(<TraceFlow events={traceEvents(answering)} isStreaming />);
  expect(screen.getByRole("button")).toHaveAttribute("aria-expanded", "false");

  await userEvent.click(screen.getByRole("button"));
  expect(screen.getByRole("button")).toHaveAttribute("aria-expanded", "true");

  answering.push(event("content", "Here is the answer."));
  rerender(<TraceFlow events={traceEvents(answering)} isStreaming />);
  expect(screen.getByRole("button")).toHaveAttribute("aria-expanded", "true");
  expect(traceEvents(answering)).toHaveLength(2);
});
