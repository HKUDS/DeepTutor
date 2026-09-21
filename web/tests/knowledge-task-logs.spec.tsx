import React from "react";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import KnowledgeBaseDetail from "@/components/knowledge/KnowledgeBaseDetail";
import {
  DEFAULT_UPLOAD_POLICY,
  type KnowledgeBase,
} from "@/lib/knowledge-helpers";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));
vi.mock("@/components/knowledge/KbFilesTab", () => ({
  default: () => <div>File browser</div>,
}));
vi.mock("@/components/knowledge/KbDocumentsSection", () => ({
  default: () => <div>Upload form</div>,
}));
vi.mock("@/components/knowledge/KbIndexVersionsSection", () => ({
  default: () => <div>Stored versions</div>,
}));
vi.mock("@/components/knowledge/KbSettingsSection", () => ({
  default: () => null,
}));
vi.mock("@/components/knowledge/KbGitHubSourcesSection", () => ({
  default: () => null,
}));
vi.mock("@/components/knowledge/KbWebSourcesSection", () => ({
  default: () => null,
}));
vi.mock("@/components/knowledge/KbMarginNoteDevicesSection", () => ({
  default: () => null,
}));

afterEach(cleanup);
beforeEach(() => {
  HTMLElement.prototype.scrollTo = vi.fn();
});
const kb = {
  name: "papers",
  is_default: false,
  status: "processing",
  statistics: { raw_documents: 1 },
  progress: {
    stage: "processing_documents",
    task_id: "kb_init_test",
    message: "Parsing textbook.pdf",
    progress_percent: 35,
  },
} as KnowledgeBase;
const actions = {
  onCreate: vi.fn(),
  onUpload: vi.fn(),
  onReindex: vi.fn(),
  onUpdatePendingIndexingPolicy: vi.fn(),
  onRetry: vi.fn(),
  onSetDefault: vi.fn(),
  onDelete: vi.fn(),
  onClearHistory: vi.fn(),
};

it("shows live detailed logs on the default Files tab and keeps them visible when switching tabs", () => {
  render(
    <KnowledgeBaseDetail
      kb={kb}
      task={{
        taskId: "kb_init_test",
        kind: "create",
        label: "Create papers",
        logs: ["Extracted 12 pages from textbook.pdf"],
        executing: true,
        error: null,
      }}
      history={[]}
      uploadPolicy={DEFAULT_UPLOAD_POLICY}
      {...actions}
    />,
  );
  expect(screen.getByText("File browser")).toBeVisible();
  expect(
    screen.getByText("Extracted 12 pages from textbook.pdf"),
  ).toBeVisible();
  expect(screen.getByRole("progressbar")).toHaveAttribute(
    "aria-valuenow",
    "35",
  );
  fireEvent.click(screen.getByRole("button", { name: "Index versions" }));
  expect(screen.getByText("Stored versions")).toBeVisible();
  expect(
    screen.getByText("Extracted 12 pages from textbook.pdf"),
  ).toBeVisible();
  expect(screen.getAllByRole("region", { name: "Process Logs" })).toHaveLength(
    1,
  );
});

it("shows current processing progress before its detailed log stream reconnects", () => {
  render(
    <KnowledgeBaseDetail
      kb={kb}
      history={[]}
      uploadPolicy={DEFAULT_UPLOAD_POLICY}
      {...actions}
    />,
  );
  expect(screen.getByText("Parsing textbook.pdf")).toBeVisible();
  expect(screen.getByRole("region", { name: "Process Logs" })).toBeVisible();
});

it("does not show a log panel for an idle KB with no local task", () => {
  render(
    <KnowledgeBaseDetail
      kb={{ ...kb, status: "ready" }}
      history={[]}
      uploadPolicy={DEFAULT_UPLOAD_POLICY}
      {...actions}
    />,
  );
  expect(screen.queryByRole("region", { name: "Process Logs" })).toBeNull();
});
