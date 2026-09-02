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
});
