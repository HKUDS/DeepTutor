import test from "node:test";
import assert from "node:assert/strict";

import {
  classifyFile,
  docIconFor,
  formatBytes,
  isSvgFilename,
  MAX_ATTACHMENT_BYTES,
} from "../lib/doc-attachments";

function makeFile(name: string, type = "", size = 0): File {
  // File constructor available in modern Node runtimes.
  return new File([new Uint8Array(size)], name, { type });
}

// classifyFile ---------------------------------------------------------------

test("classifyFile: image via MIME", () => {
  assert.equal(classifyFile(makeFile("x.png", "image/png")), "image");
  assert.equal(classifyFile(makeFile("x.jpg", "image/jpeg")), "image");
});

test("classifyFile: doc via MIME", () => {
  assert.equal(
    classifyFile(
      makeFile(
        "a.docx",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
      ),
    ),
    "doc",
  );
  assert.equal(classifyFile(makeFile("b.pdf", "application/pdf")), "doc");
});

test("classifyFile: doc via extension fallback when MIME empty", () => {
  assert.equal(classifyFile(makeFile("report.pptx")), "doc");
  assert.equal(classifyFile(makeFile("REPORT.XLSX")), "doc");
});

test("classifyFile: accepts text & code", () => {
  assert.equal(classifyFile(makeFile("notes.txt", "text/plain")), "doc");
  assert.equal(classifyFile(makeFile("README.md", "text/markdown")), "doc");
  assert.equal(classifyFile(makeFile("main.py", "text/x-python")), "doc");
  // Empty MIME (common for code files) still accepted via extension
  assert.equal(classifyFile(makeFile("script.js")), "doc");
  assert.equal(classifyFile(makeFile("config.yaml")), "doc");
  assert.equal(classifyFile(makeFile("data.csv")), "doc");
});

test("classifyFile: SVG classified as doc (not image)", () => {
  // SVG has an image/* MIME but we route it through text extraction so the
  // LLM gets its XML source. Thumbnail preview still renders via <img>.
  assert.equal(classifyFile(makeFile("logo.svg", "image/svg+xml")), "doc");
  assert.equal(classifyFile(makeFile("icon.SVG")), "doc");
});

test("isSvgFilename: case-insensitive extension check", () => {
  assert.equal(isSvgFilename("foo.svg"), true);
  assert.equal(isSvgFilename("FOO.SVG"), true);
  assert.equal(isSvgFilename("foo.svg.bak"), false);
  assert.equal(isSvgFilename("foo.png"), false);
});

test("docIconFor: SVG gets its own label", () => {
  assert.equal(docIconFor("logo.svg").label, "SVG");
  assert.ok(docIconFor("logo.svg").tint.includes("teal"));
});

test("classifyFile: rejects unsupported", () => {
  assert.equal(classifyFile(makeFile("a.zip", "application/zip")), null);
  assert.equal(
    classifyFile(makeFile("a.exe", "application/x-msdownload")),
    null,
  );
  assert.equal(classifyFile(makeFile("noext")), null);
});

// formatBytes ----------------------------------------------------------------

test("formatBytes: B / KB / MB", () => {
  assert.equal(formatBytes(0), "0 B");
  assert.equal(formatBytes(512), "512 B");
  assert.equal(formatBytes(1024), "1.0 KB");
  assert.equal(formatBytes(1024 * 1024), "1.0 MB");
  assert.equal(formatBytes(5 * 1024 * 1024), "5.0 MB");
});

test("formatBytes: negative / NaN returns empty string", () => {
  assert.equal(formatBytes(-1), "");
  assert.equal(formatBytes(Number.NaN), "");
});

// docIconFor -----------------------------------------------------------------

test("docIconFor: office labels & tints", () => {
  assert.equal(docIconFor("report.pdf").label, "PDF");
  assert.ok(docIconFor("report.pdf").tint.includes("red"));
  assert.equal(docIconFor("report.docx").label, "DOCX");
  assert.equal(docIconFor("report.xlsx").label, "XLSX");
  assert.equal(docIconFor("report.pptx").label, "PPTX");
});

test("docIconFor: code files share a code icon", () => {
  assert.ok(docIconFor("main.py").tint.includes("violet"));
  assert.ok(docIconFor("main.js").tint.includes("violet"));
  assert.ok(docIconFor("main.rs").tint.includes("violet"));
});

test("docIconFor: json/config/data/markup categories", () => {
  assert.ok(docIconFor("data.json").tint.includes("amber"));
  assert.ok(docIconFor("config.yaml").tint.includes("slate"));
  assert.ok(docIconFor("run.sh").tint.includes("slate"));
  assert.ok(docIconFor("table.csv").tint.includes("emerald"));
  assert.ok(docIconFor("doc.md").tint.includes("sky"));
  assert.ok(docIconFor("style.css").tint.includes("pink"));
});

test("docIconFor: fallback for unknown extension", () => {
  assert.equal(docIconFor("mystery.bin").label, "BIN");
  assert.equal(docIconFor("noext").label, "FILE");
});

// Limits sanity check -------------------------------------------------------

test("MAX_ATTACHMENT_BYTES is 10 MB", () => {
  assert.equal(MAX_ATTACHMENT_BYTES, 10 * 1024 * 1024);
});
