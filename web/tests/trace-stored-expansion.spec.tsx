import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type { StreamEvent } from "@/features/chat/model/protocol";
import { AssistantActivity } from "@/features/chat/trace";
import { initI18n } from "@/i18n/init";

initI18n("en");

/**
 * A finished turn keeps only a compact preview in memory, and that preview
 * drops ``thinking``. For a round that called no tools, thinking *is* the
 * whole trace — so the preview holds nothing renderable.
 *
 * That created a circle: no rows meant the header rendered as not expandable,
 * not expandable meant the click that fetches the full trace could never fire,
 * and so the rows could never arrive. A reasoning model's thinking was visible
 * while it streamed and gone the moment the turn finished, with the "已完成"
 * header refusing to open.
 */
const SETTLED_PREVIEW = [
  {
    type: "result",
    stage: "responding",
    content: "",
    metadata: {},
    timestamp: 1_000,
  },
] as unknown as StreamEvent[];

const FETCHED_TRACE = [
  {
    type: "thinking",
    stage: "responding",
    content: "weighing the two reducers",
    metadata: { call_id: "round-1", call_kind: "agent_loop_round" },
    timestamp: 1_000,
  },
] as unknown as StreamEvent[];

describe("opening a settled trace the preview dropped", () => {
  it("stays expandable when the server still holds the rows", async () => {
    const onTraceToggle = vi.fn();
    render(
      <AssistantActivity
        events={SETTLED_PREVIEW}
        content="The answer."
        hasStoredTrace
        onTraceToggle={onTraceToggle}
      />,
    );

    await userEvent.click(screen.getByRole("button"));

    expect(onTraceToggle).toHaveBeenCalledWith(true);
  });

  it("says it is loading rather than opening onto nothing", async () => {
    render(
      <AssistantActivity
        events={SETTLED_PREVIEW}
        content="The answer."
        hasStoredTrace
        onTraceToggle={() => {}}
      />,
    );

    await userEvent.click(screen.getByRole("button"));

    expect(screen.getByText(/Loading the full trace/)).toBeInTheDocument();
  });

  it("renders the reasoning once the fetch replaces the preview", () => {
    const { rerender } = render(
      <AssistantActivity
        events={SETTLED_PREVIEW}
        content="The answer."
        hasStoredTrace
        onTraceToggle={() => {}}
      />,
    );

    rerender(
      <AssistantActivity
        events={FETCHED_TRACE}
        content="The answer."
        hasStoredTrace={false}
        onTraceToggle={() => {}}
      />,
    );

    expect(screen.queryByText(/Loading the full trace/)).not.toBeInTheDocument();
  });

  it("is not expandable when the server has nothing more either", () => {
    const onTraceToggle = vi.fn();
    render(
      <AssistantActivity
        events={SETTLED_PREVIEW}
        content="The answer."
        hasStoredTrace={false}
        onTraceToggle={onTraceToggle}
      />,
    );

    expect(screen.queryByRole("button")).toBeNull();
    expect(screen.queryByRole("status")).not.toBeNull();
    expect(onTraceToggle).not.toHaveBeenCalled();
    expect(screen.queryByText(/Loading the full trace/)).not.toBeInTheDocument();
  });
});
