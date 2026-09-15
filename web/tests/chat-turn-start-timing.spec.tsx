import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  ChatStateAdapterProvider,
  useChatStateAdapter,
} from "@/features/chat/ChatStateAdapter";
import { StreamingStatus } from "@/features/chat/trace";
import { initI18n } from "@/i18n/init";

initI18n("en");

const transport = vi.hoisted(() => {
  type MockEvent = Record<string, unknown>;
  type EventListener = (event: MockEvent) => void;

  class MockUnifiedTurnClient {
    connected = false;
    static instances: MockUnifiedTurnClient[] = [];

    constructor(private readonly onEvent: EventListener) {
      MockUnifiedTurnClient.instances.push(this);
    }

    connect(): void {
      this.connected = true;
    }

    setResumeState(): void {}

    disconnect(): void {
      this.connected = false;
    }

    send(): void {}

    sendAwaitingAck(): Promise<boolean> {
      return Promise.resolve(true);
    }

    emit(event: MockEvent): void {
      this.onEvent(event);
    }
  }

  return { MockUnifiedTurnClient };
});

vi.mock("@/features/chat/transport/UnifiedTurnClient", () => ({
  UnifiedTurnClient: transport.MockUnifiedTurnClient,
}));

function Harness() {
  const chat = useChatStateAdapter();
  const assistant = [...chat.state.messages]
    .reverse()
    .find((message) => message.role === "assistant");

  return (
    <div>
      <button type="button" onClick={() => void chat.sendMessage("hello")}>
        Start turn
      </button>
      <span data-testid="assistant-id">{assistant?.id ?? "none"}</span>
      <span data-testid="assistant-trace">
        {JSON.stringify(assistant?.trace ?? null)}
      </span>
      <StreamingStatus
        events={assistant?.events ?? []}
        isStreaming={chat.state.isStreaming}
        content={assistant?.content ?? ""}
        traceBounds={assistant?.trace}
      />
    </div>
  );
}

describe("chat turn timing", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("times a live turn from submission and keeps that start after events settle", () => {
    const submittedAtMs = 1_700_000_000_000;
    vi.setSystemTime(submittedAtMs);
    render(
      <ChatStateAdapterProvider>
        <Harness />
      </ChatStateAdapterProvider>,
    );

    fireEvent.click(screen.getByRole("button", { name: "Start turn" }));

    expect(JSON.parse(screen.getByTestId("assistant-trace").textContent ?? ""))
      .toEqual({ started_at: submittedAtMs / 1000 });
    expect(screen.getByRole("status")).toHaveTextContent("0s");

    act(() => {
      vi.advanceTimersByTime(90_000);
    });
    expect(screen.getByRole("status")).toHaveTextContent("1m 30s");

    const client =
      transport.MockUnifiedTurnClient.instances[
        transport.MockUnifiedTurnClient.instances.length - 1
      ];
    act(() => {
      client.emit({
        type: "stage_start",
        source: "chat",
        stage: "responding",
        content: "",
        turn_id: "turn-1435",
        seq: 1,
        timestamp: (submittedAtMs + 90_000) / 1000,
      });
    });

    expect(JSON.parse(screen.getByTestId("assistant-trace").textContent ?? ""))
      .toEqual({ started_at: submittedAtMs / 1000 });
    expect(screen.getByRole("status")).toHaveTextContent("1m 30s");

    act(() => {
      client.emit({
        type: "done",
        source: "chat",
        stage: "responding",
        content: "",
        metadata: { status: "completed", assistant_message_id: 501 },
        turn_id: "turn-1435",
        seq: 2,
        timestamp: (submittedAtMs + 100_000) / 1000,
      });
    });

    expect(screen.getByTestId("assistant-id")).toHaveTextContent("501");
    expect(
      JSON.parse(screen.getByTestId("assistant-trace").textContent ?? ""),
    ).toMatchObject({ started_at: submittedAtMs / 1000 });
  });
});
