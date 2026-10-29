import test from "node:test";
import assert from "node:assert/strict";
import {
  existsSync,
  mkdirSync,
  mkdtempSync,
  readFileSync,
  rmSync,
  writeFileSync,
} from "node:fs";
import { spawnSync } from "node:child_process";
import { tmpdir } from "node:os";
import path from "node:path";
import { pathToFileURL } from "node:url";

const webRoot = process.cwd();
const read = (...parts: string[]) =>
  readFileSync(path.join(webRoot, ...parts), "utf8");

test("npm build routes through the generated-file wrapper", () => {
  const scripts = JSON.parse(read("package.json")).scripts as Record<
    string,
    string
  >;
  assert.equal(scripts.build, "node ./scripts/build.mjs");
});

test("the build publishes PDF.js decoder assets for standalone deployments", () => {
  const scripts = JSON.parse(read("package.json")).scripts as Record<
    string,
    string
  >;
  assert.equal(scripts.predev, "node ./scripts/copy-pdfjs-assets.mjs");
  assert.equal(scripts["predev:turbo"], "node ./scripts/copy-pdfjs-assets.mjs");

  const source = read("scripts", "copy-pdfjs-assets.mjs");
  assert.match(source, /ASSET_DIRS = \["wasm", "cmaps"\]/);
  assert.match(source, /cpSync\(sourceDir, targetDir, \{ recursive: true \}\)/);

  const result = spawnSync(
    process.execPath,
    ["scripts/copy-pdfjs-assets.mjs"],
    { cwd: webRoot, encoding: "utf8" },
  );
  assert.equal(result.status, 0, result.stderr);
  for (const name of [
    "openjpeg.wasm",
    "openjpeg_nowasm_fallback.js",
    "jbig2.wasm",
    "qcms_bg.wasm",
  ]) {
    assert.ok(
      existsSync(path.join(webRoot, "public", "pdfjs", "wasm", name)),
      name,
    );
  }
  // Predefined CMaps back cMapUrl: without them PDF.js drops CID fonts, which
  // is most CJK documents' text. One Adobe-GB1 file is enough of a smoke test.
  for (const name of [
    "Adobe-GB1-UCS2.bcmap",
    "Adobe-Japan1-UCS2.bcmap",
    "Adobe-Korea1-UCS2.bcmap",
  ]) {
    assert.ok(
      existsSync(path.join(webRoot, "public", "pdfjs", "cmaps", name)),
      name,
    );
  }
});

test("the reader gives PDF.js absolute same-origin decoder and CMap URLs", () => {
  const loader = read("lib", "pdfjs-loader.ts");
  const reader = read("components", "reading", "PdfDocumentView.tsx");
  assert.match(loader, /new URL\(PDFJS_WASM_PATH, window\.location\.origin\)/);
  assert.match(loader, /new URL\(PDFJS_CMAP_PATH, window\.location\.origin\)/);
  assert.match(reader, /wasmUrl:\s*pdfjsWasmUrl\(\)/);
  assert.match(reader, /cMapUrl:\s*pdfjsCMapUrl\(\)/);
  assert.match(reader, /cMapPacked:\s*true/);
});

test("the reader loads the legacy PDF.js library and polyfilled worker", () => {
  const loader = read("lib", "pdfjs-loader.ts");
  const worker = read(
    "node_modules",
    "pdfjs-dist",
    "legacy",
    "build",
    "pdf.worker.mjs",
  );
  assert.doesNotMatch(loader, /import\("pdfjs-dist"\)/);
  assert.doesNotMatch(loader, /"pdfjs-dist\/build\//);
  assert.match(loader, /import\("pdfjs-dist\/legacy\/build\/pdf\.mjs"\)/);
  assert.match(loader, /"pdfjs-dist\/legacy\/build\/pdf\.worker\.min\.mjs"/);
  assert.match(worker, /getOrInsertComputed: function getOrInsertComputed\(/);
});

test("the build wrapper restores every generated checked-in input", () => {
  const source = read("scripts", "build.mjs");
  for (const name of ["next-env.d.ts", "tsconfig.json"]) {
    assert.match(
      source,
      new RegExp(`path\\.join\\(webRoot, "${name}"\\)`),
      `wrapper must snapshot ${name}`,
    );
  }
  assert.match(
    source,
    /restoreAll\(snapshots\)/,
    "wrapper must restore snapshots",
  );
  assert.match(
    source,
    /stdio: "inherit"/,
    "wrapper must preserve Next build diagnostics",
  );
  assert.match(
    source,
    /\[nextBin, "build", "--webpack", \.\.\.process\.argv\.slice\(2\)\]/,
    "source production builds must use Webpack so Next emits standalone/server.js",
  );
  assert.match(
    source,
    /restore\(buildTsconfigPath, configureTypeIncludes\(tsconfig\[1\], distDir\)\)/,
    "the build must isolate generated route types to its active dist directory",
  );
  assert.match(
    source,
    /DEEPTUTOR_NEXT_TSCONFIG:\s*path\.basename\(buildTsconfigPath\)/,
    "Next must consume the process-local build config rather than shared tsconfig.json",
  );
  assert.match(
    source,
    /finally\s*{\s*if \(buildTsconfigPath\) rmSync/,
    "generated inputs must be restored even when the build fails",
  );
});

test("a standalone build carries client chunks and public assets with a custom dist directory", () => {
  const fixture = mkdtempSync(path.join(tmpdir(), "deeptutor-standalone-"));
  const distDir = ".next-standalone-repro";
  const distRoot = path.join(fixture, distDir);
  const standalone = path.join(distRoot, "standalone");
  try {
    mkdirSync(path.join(distRoot, "static", "chunks"), { recursive: true });
    mkdirSync(path.join(fixture, "public", "images"), { recursive: true });
    mkdirSync(standalone, { recursive: true });
    writeFileSync(path.join(standalone, "server.js"), "// server");
    writeFileSync(path.join(distRoot, "static", "chunks", "app.js"), "// client");
    writeFileSync(path.join(fixture, "public", "images", "logo.svg"), "<svg />");

    const moduleUrl = pathToFileURL(
      path.join(webRoot, "scripts", "build.mjs"),
    ).href;
    const result = spawnSync(
      process.execPath,
      [
        "--input-type=module",
        "-e",
        `import { packageStandaloneAssets } from ${JSON.stringify(moduleUrl)};
packageStandaloneAssets(process.argv[1], process.argv[2]);`,
        fixture,
        distDir,
      ],
      { cwd: webRoot, encoding: "utf8" },
    );
    assert.equal(result.status, 0, result.stderr);
    assert.equal(
      readFileSync(
        path.join(standalone, distDir, "static", "chunks", "app.js"),
        "utf8",
      ),
      "// client",
    );
    assert.equal(
      readFileSync(
        path.join(standalone, "public", "images", "logo.svg"),
        "utf8",
      ),
      "<svg />",
    );
  } finally {
    rmSync(fixture, { recursive: true, force: true });
  }
});

test("the standalone bundle is rooted where the Python launcher expects it", () => {
  const source = read("next.config.js");
  assert.match(source, /output:\s*"standalone"/);
  assert.match(source, /outputFileTracingRoot:\s*__dirname/);
  assert.match(source, /tsconfigPath:\s*process\.env\.DEEPTUTOR_NEXT_TSCONFIG/);
});
