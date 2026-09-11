import assert from "node:assert/strict";
import test from "node:test";

import { selectAttachmentFiles } from "../features/chat/controllers/pending-attachments";

function file(name: string, size: number, type: string): File {
  return { name, size, type } as File;
}

test("attachment selection applies type, per-file, and total limits once", () => {
  const result = selectAttachmentFiles(
    [
      file("notes.txt", 4, "text/plain"),
      file("script.exe", 1, "application/x-msdownload"),
      file("large.pdf", 11, "application/pdf"),
      file("more.txt", 4, "text/plain"),
    ],
    3,
    { maxFileBytes: 10, maxTotalBytes: 10 },
  );

  assert.deepEqual(
    result.accepted.map((item) => item.name),
    ["notes.txt"],
  );
  assert.deepEqual(result.rejected, [
    { name: "script.exe", reason: "unsupported" },
    { name: "large.pdf", reason: "too_large" },
    { name: "more.txt", reason: "quota" },
  ]);
});
