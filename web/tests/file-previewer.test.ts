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
