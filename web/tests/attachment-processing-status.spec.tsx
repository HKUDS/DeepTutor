import { render, screen } from "@testing-library/react";
import { expect, it } from "vitest";
import AttachmentProcessingStatus from "@/components/chat/home/AttachmentProcessingStatus";
import type { StreamEvent } from "@/features/chat/model/protocol";
import {
  selectAttachmentProcessing,
  type AttachmentProcessingItem,
} from "@/features/chat/selectors/attachment-processing";
import { initI18n } from "@/i18n/init";

initI18n("en");

function progress(
  attachmentId: string,
  filename: string,
  phase: string,
  content: string,
): StreamEvent {
  return {
    type: "progress",
    source: "attachment_parsing",
    stage: phase,
    content,
    timestamp: 1,
    metadata: {
      attachment_id: attachmentId,
      filename,
      phase,
    },
  } as StreamEvent;
}

it("keeps one latest parser stage per attachment during a live turn", () => {
  const items = selectAttachmentProcessing(
    [
      {
        role: "assistant",
        events: [
          progress("a", "notes.pdf", "received", "Uploaded"),
          progress("b", "scan.pdf", "submitting", "Submitting"),
          progress("a", "notes.pdf", "retrieving", "Retrieving"),
        ],
      },
    ],
    true,
  );

  expect(items).toEqual([
    {
      attachmentId: "a",
      filename: "notes.pdf",
      phase: "retrieving",
      detail: "Retrieving",
    },
    {
      attachmentId: "b",
      filename: "scan.pdf",
      phase: "submitting",
      detail: "Submitting",
    },
  ]);
});

it("hides settled success but preserves parser failure details", () => {
  const items = selectAttachmentProcessing(
    [
      {
        role: "assistant",
        events: [
          progress("a", "notes.pdf", "completed", "Done"),
          progress("b", "scan.pdf", "failed", "Document parsing failed: parser offline"),
        ],
      },
    ],
    false,
  );

  expect(items.map((item) => item.filename)).toEqual(["scan.pdf"]);
  render(<AttachmentProcessingStatus items={items} />);
  expect(screen.getByRole("status", { name: "Attachment processing" })).toBeVisible();
  expect(screen.getByText("scan.pdf")).toBeVisible();
  expect(screen.getByText("Document parsing failed")).toBeVisible();
  expect(screen.getByText("Failure details")).toBeVisible();
});

it("does not carry a previous turn failure into a later answer", () => {
  const items = selectAttachmentProcessing(
    [
      {
        role: "assistant",
        events: [
          progress("a", "notes.pdf", "failed", "Document parsing failed"),
        ],
      },
      { role: "user", events: [] },
      { role: "assistant", events: [] },
    ],
    false,
  );

  expect(items).toEqual([]);
});

it("labels successful completion clearly", () => {
  const item: AttachmentProcessingItem = {
    attachmentId: "a",
    filename: "notes.pdf",
    phase: "completed",
    detail: "Document parsing completed",
  };
  render(<AttachmentProcessingStatus items={[item]} />);
  expect(screen.getByText("Ready for this answer")).toBeVisible();
});
