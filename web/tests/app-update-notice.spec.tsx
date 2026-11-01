import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";

import AppUpdateNotice from "@/components/common/AppUpdateNotice";
import { initI18n } from "@/i18n/init";
import type { AppUpdateStatus } from "@/lib/app-update";

const lib = vi.hoisted(() => ({
  fetchAppUpdateStatus: vi.fn(),
  fetchAppUpdateJob: vi.fn(),
  requestAppUpdate: vi.fn(),
  subscribeAppUpdateStatus: vi.fn(() => () => undefined),
  updateJobIsActive: vi.fn((status: string) =>
    ["pending", "handoff", "running", "restarting"].includes(status),
  ),
}));

vi.mock("@/lib/app-update", () => lib);
vi.mock("@/lib/notifications", () => ({ notify: vi.fn() }));

initI18n("en");

function status(overrides: Partial<AppUpdateStatus> = {}): AppUpdateStatus {
  return {
    current_version: "1.7.1",
    check_enabled: true,
    checked_at: "2026-11-01T09:00:00Z",
    cached: false,
    check_error: "",
    update_available: true,
    release: {
      version: "1.7.2",
      name: "DeepTutor 1.7.2",
      published_at: "2026-11-02T00:00:00Z",
      url: "https://github.com/HKUDS/DeepTutor/releases/tag/1.7.2",
      excerpt: "Faster startup and a few fixes.",
      migration_warning: false,
    },
    installation: {
      mode: "pypi",
      automatic_update: true,
      command: "",
      reason: "",
    },
    launcher_managed: true,
    is_admin: true,
    job: null,
    ...overrides,
  };
}

afterEach(() => {
  vi.clearAllMocks();
  localStorage.clear();
});

it("checks on mount and offers the update action to an admin", async () => {
  lib.fetchAppUpdateStatus.mockResolvedValue(status());
  lib.requestAppUpdate.mockResolvedValue({
    id: "job-1",
    status: "pending",
    current_version: "1.7.1",
    target_version: "1.7.2",
    created_at: "2026-11-01T09:00:00Z",
    started_at: null,
    finished_at: null,
    error: null,
    restart_count: 0,
  });

  render(<AppUpdateNotice />);

  expect(await screen.findByText("Update available")).toBeTruthy();
  expect(screen.getByText("DeepTutor 1.7.2 is available.")).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "Update to 1.7.2" }));

  expect(screen.getByRole("alertdialog")).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "Update and restart" }));

  await waitFor(() => expect(lib.requestAppUpdate).toHaveBeenCalledTimes(1));
  expect(await screen.findByText("Updating DeepTutor…")).toBeTruthy();
});

it("lets the learner dismiss one release without hiding the next", async () => {
  lib.fetchAppUpdateStatus.mockResolvedValue(status());
  render(<AppUpdateNotice />);

  await screen.findByText("Update available");
  fireEvent.click(screen.getByRole("button", { name: "Dismiss" }));

  expect(screen.queryByText("Update available")).toBeNull();
  expect(localStorage.getItem("dt:app-update:dismissed-version")).toBe("1.7.2");
});

it("does not offer the install button to a non-admin", async () => {
  lib.fetchAppUpdateStatus.mockResolvedValue(status({ is_admin: false }));
  render(<AppUpdateNotice />);

  expect(await screen.findByText("Ask an administrator to update DeepTutor.")).toBeTruthy();
  expect(screen.queryByRole("button", { name: "Update to 1.7.2" })).toBeNull();
});

it("shows what changed once after the version changes", async () => {
  localStorage.setItem("dt:app-update:seen-version", "1.7.1");
  lib.fetchAppUpdateStatus.mockResolvedValue(
    status({
      current_version: "1.7.2",
      update_available: false,
      release: {
        version: "1.7.2",
        name: "DeepTutor 1.7.2",
        published_at: "2026-11-02T00:00:00Z",
        url: "https://github.com/HKUDS/DeepTutor/releases/tag/1.7.2",
        excerpt: "Faster startup and a few fixes.",
        migration_warning: false,
      },
    }),
  );

  render(<AppUpdateNotice />);

  expect(await screen.findByText("What's new in 1.7.2")).toBeTruthy();
  expect(screen.getByText("Faster startup and a few fixes.")).toBeTruthy();
  expect(localStorage.getItem("dt:app-update:seen-version")).toBe("1.7.2");
});
