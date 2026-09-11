import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import {
  RuntimeHealthCard,
  TurnCoordinationSettings,
} from "@/features/runtime-status";
import type { RuntimeStatusSnapshot } from "@/features/runtime-status/model";
import { initI18n } from "@/i18n/init";

initI18n("en");

const snapshot: RuntimeStatusSnapshot = {
  health: "healthy",
  loading: false,
  error: null,
  lastUpdated: 1,
  data: {
    workerId: "worker-a",
    workerCount: 4,
    coordinationMode: "redis",
    redisConfigured: true,
    redisStatus: "ok",
    leaderId: "worker-b",
    leaderHealthy: true,
    ownerTurnCount: 2,
    recoveryBacklog: 0,
    leaseTtlSeconds: 30,
    renewIntervalSeconds: 10,
    recoveryIntervalSeconds: 5,
    protocolVersion: "2.0",
    minimumWebProtocolVersion: "2.0",
  },
};

describe("runtime health UI", () => {
  it("shows aggregate health and gates operator details", () => {
    const { rerender } = render(<RuntimeHealthCard snapshot={snapshot} />);
    expect(screen.getByText("Healthy")).toBeVisible();
    expect(screen.queryByText("worker-a")).not.toBeInTheDocument();
    rerender(<RuntimeHealthCard snapshot={snapshot} showDetails />);
    expect(screen.getByText("worker-a")).toBeVisible();
    expect(screen.getByText("worker-b")).toBeVisible();
  });

  it("keeps stale safe data visible when refresh fails", () => {
    render(
      <RuntimeHealthCard
        snapshot={{ ...snapshot, error: "request failed" }}
        showDetails
      />,
    );
    expect(screen.getByRole("status")).toHaveTextContent("last safe snapshot");
    expect(screen.getByText("worker-a")).toBeVisible();
    expect(screen.queryByText("request failed")).not.toBeInTheDocument();
  });

  it("never echoes a saved Redis URL", async () => {
    const save = vi.fn(async () => undefined);
    const user = userEvent.setup();
    render(
      <TurnCoordinationSettings
        value={{
          backendWorkers: 1,
          coordinationMode: "memory",
          developmentReload: false,
          leaseTtlSeconds: 30,
          recoveryIntervalSeconds: 5,
        }}
        redisConfigured={false}
        onChange={() => undefined}
        onSaveRedisUrl={save}
      />,
    );
    const input = screen.getByLabelText("Redis URL");
    await user.type(input, "redis://user:password@host");
    await user.click(screen.getByRole("button", { name: "Save secret" }));
    expect(save).toHaveBeenCalledWith("redis://user:password@host");
    expect(input).toHaveValue("");
    expect(document.body).not.toHaveTextContent("redis://user:password@host");
  });
});
