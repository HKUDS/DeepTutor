import assert from "node:assert/strict";
import test from "node:test";

import { previewKindFor } from "../components/chat/preview/previewerFor";

test("video attachments use the native video preview", () => {
  assert.equal(previewKindFor({ filename: "lesson.mp4" }), "video");
  assert.equal(
    previewKindFor({
      filename: "generated-file",
      mimeType: "video/webm",
    }),
    "video",
  );
  assert.equal(previewKindFor({ filename: "clip.MOV" }), "video");
});

test("Office attachments retain their format-specific fallback renderers", () => {
  assert.equal(previewKindFor({ filename: "report.DOCX" }), "docx");
  assert.equal(previewKindFor({ filename: "report.docm" }), "docx");
  assert.equal(
    previewKindFor({
      filename: "attachment",
      mimeType:
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    }),
    "docx",
  );

  assert.equal(previewKindFor({ filename: "slides.pptx" }), "office-text");
  assert.equal(previewKindFor({ filename: "slides.ppt" }), "office-text");
  assert.equal(previewKindFor({ filename: "legacy.doc" }), "office-text");

  assert.equal(previewKindFor({ filename: "budget.XLSX" }), "xlsx");
  assert.equal(previewKindFor({ filename: "budget.xlsm" }), "xlsx");
  assert.equal(previewKindFor({ filename: "legacy.xls" }), "office-text");
});
