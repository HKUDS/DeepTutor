import React from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import KbIndexingRun from "@/components/knowledge/KbIndexingRun";
import { apiFetch } from "@/shared/api/client";

vi.mock("react-i18next", () => ({ useTranslation: () => ({ t: (key: string) => key }) }));
vi.mock("@/shared/api/client", () => ({ apiFetch: vi.fn() }));
const run = { task_id: "owned", state: "running", phase: "embedding", started_at: 1, last_activity_at: 2,
  last_progress_at: 2, phase_current: 1, phase_total: 1, cancel_requested: false,
  documents: { "book.pdf": { status: "unknown", parse_reused: true }, "bad.pdf": { status: "failed", reason: "invalid_output" } } };
beforeEach(() => vi.clearAllMocks());
it("reads durable outcomes on demand and distinguishes phase completion from readiness", async () => {
  vi.mocked(apiFetch).mockResolvedValue(new Response(JSON.stringify({ run })));
  render(<KbIndexingRun kbName="kb" />);
  expect(apiFetch).not.toHaveBeenCalled();
  fireEvent.click(screen.getByText("Indexing recovery details"));
  await screen.findByText(/book.pdf/);
  expect(screen.getByText(/bad.pdf/)).toHaveTextContent("invalid_output");
  expect(screen.getByText(/Phase completion does not mean/)).toBeInTheDocument();
  expect(screen.queryByText(/Verified index version/)).not.toBeInTheDocument();
});
it("requests cancellation for the displayed owner and keeps it pending until a safe boundary", async () => {
  vi.mocked(apiFetch).mockResolvedValueOnce(new Response(JSON.stringify({ run }))).mockResolvedValueOnce(new Response("{}"));
  render(<KbIndexingRun kbName="kb" />);
  fireEvent.click(screen.getByText("Indexing recovery details"));
  fireEvent.click(await screen.findByRole("button", { name: "Cancel indexing" }));
  expect(await screen.findByRole("button", { name: "Cancellation pending at a safe boundary" })).toBeDisabled();
  expect(vi.mocked(apiFetch).mock.calls[1][0]).toContain("/indexing-run/owned/cancel");
});
it("read-only libraries have no cancellation action", async () => {
  vi.mocked(apiFetch).mockResolvedValue(new Response(JSON.stringify({ run })));
  render(<KbIndexingRun kbName="library:kb" readOnly />);
  fireEvent.click(screen.getByText("Indexing recovery details"));
  await screen.findByText(/book.pdf/);
  expect(screen.queryByRole("button", { name: "Cancel indexing" })).not.toBeInTheDocument();
});
