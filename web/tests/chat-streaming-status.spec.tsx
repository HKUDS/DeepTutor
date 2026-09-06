import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { StreamEvent } from "@/features/chat/model/protocol";
import { StreamingStatus } from "@/features/chat/trace";
import { initI18n } from "@/i18n/init";

initI18n("en");

describe("chat activity status", () => {
  it("keeps answer streaming inside the existing exploration surface", () => {
    const events = [
      {
        type: "content",
        stage: "responding",
        content: "Partial answer",
        timestamp: Date.now() / 1000,
      },
    ] as StreamEvent[];

    render(
      <StreamingStatus
        events={events}
        isStreaming
        content="Partial answer"
      />,
    );

    const status = screen.getByRole("status");
    expect(status).toHaveTextContent("DeepTutor Exploring");
    expect(status).not.toHaveTextContent("Responding");
  });

  it("keeps the row on a finished turn that produced only a trace", () => {
    // A turn can run tools and end without a user-facing answer (a rejected
    // capability finish, for one). The row is the only way to open that
    // trace, so hiding it makes the whole turn look like it never ran.
    const events = [
      {
        type: "tool_call",
        stage: "exploring",
        content: "",
        timestamp: Date.now() / 1000,
      },
    ] as StreamEvent[];

    render(
      <StreamingStatus
        events={events}
        isStreaming={false}
        content=""
        expandable
        expanded={false}
        onToggle={() => {}}
      />,
    );

    // Expandable rows render as the disclosure button rather than a status
    // region, and carry the settled label.
    expect(screen.getByRole("button")).toHaveTextContent("Done");
  });
});
