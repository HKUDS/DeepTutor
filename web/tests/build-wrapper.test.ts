import test from "node:test";
import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import { spawnSync } from "node:child_process";
import path from "node:path";

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
  assert.match(source, /node_modules.*pdfjs-dist.*wasm/);
  assert.match(source, /public.*pdfjs.*wasm/);
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
});

test("the reader gives PDF.js an absolute same-origin decoder URL", () => {
  const loader = read("lib", "pdfjs-loader.ts");
  const reader = read("components", "reading", "PdfDocumentView.tsx");
  assert.match(loader, /new URL\(PDFJS_WASM_PATH, window\.location\.origin\)/);
  assert.match(reader, /wasmUrl:\s*pdfjsWasmUrl\(\)/);
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

test("the standalone bundle is rooted where the Python launcher expects it", () => {
  const source = read("next.config.js");
  assert.match(source, /output:\s*"standalone"/);
  assert.match(source, /outputFileTracingRoot:\s*__dirname/);
  assert.match(source, /tsconfigPath:\s*process\.env\.DEEPTUTOR_NEXT_TSCONFIG/);
});
