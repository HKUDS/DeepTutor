// Compile a model-written Remotion lesson (Lesson.tsx + the shipped kit) into a browser player
// script. Before bundling, sample frames are rendered in a permission-restricted Node process so
// runtime errors come back to the model instead of reaching the learner.
//
//   node build.mjs <Lesson.tsx> <out.js>
//
// DEEPTUTOR_REMOTION_RUNTIME names the directory whose node_modules holds remotion, react and
// esbuild (see package.json next to this file). Prints one JSON line: {ok, stage, errors, frames}.

import {createRequire} from "node:module";
import {mkdtempSync, writeFileSync, rmSync} from "node:fs";
import {tmpdir} from "node:os";
import {dirname, join, resolve} from "node:path";
import {spawnSync} from "node:child_process";

const runtime = resolve(process.env.DEEPTUTOR_REMOTION_RUNTIME || ".");
const require = createRequire(join(runtime, "package.json"));
const esbuild = require("esbuild");
const [lessonArg, outArg] = process.argv.slice(2);
const lesson = resolve(lessonArg).replace(/\\/g, "/");
const nodePaths = [join(runtime, "node_modules")];

const report = (o) => { console.log(JSON.stringify(o)); process.exit(o.ok ? 0 : 1); };
const fmtErrors = (e) => (e.errors || [e]).slice(0, 12).map((x) =>
  x.location ? `${x.location.line}:${x.location.column} ${x.text}\n    ${x.location.lineText}` : String(x.text || x.message || x));

// The lesson may import only React, Remotion and its own kit; everything else is a compile error.
const ALLOWED = /^(react|react\/jsx-runtime|react-dom|react-dom\/server|react-dom\/client|remotion|@remotion\/player)$/;
const onlyAllowedImports = {
  name: "only-allowed-imports",
  setup(build) {
    const home = dirname(lesson);
    const inside = (p) => p.replace(/\\/g, "/").startsWith(home + "/");
    build.onResolve({filter: /.*/}, (args) => {
      if (args.kind === "entry-point" || ALLOWED.test(args.path)) return undefined;
      // packages pulling in their own dependencies are not the lesson's imports
      if (!args.importer || !inside(args.importer)) return undefined;
      const target = resolve(args.resolveDir, args.path).replace(/\\/g, "/");
      if (target === lesson || (args.path.startsWith(".") && inside(target))) return undefined;
      return {errors: [{text: `import "${args.path}" is not allowed; use react, remotion and ./kit only`}]};
    });
  },
};

const common = {bundle: true, jsx: "automatic", nodePaths, logLevel: "silent", plugins: [onlyAllowedImports],
  loader: {".tsx": "tsx", ".ts": "ts"}, define: {"process.env.NODE_ENV": '"production"'}};

// 1. Node check: render sample frames through @remotion/player's <Thumbnail>.
const tmp = mkdtempSync(join(tmpdir(), "dt-lesson-"));
const checkEntry = join(tmp, "check.tsx");
writeFileSync(checkEntry, `
import {renderToPipeableStream} from "react-dom/server";
import {Writable} from "node:stream";
import {Thumbnail} from "@remotion/player";
import {Lesson, LESSON} from ${JSON.stringify(lesson)};
// Streamed rendering reports errors thrown below a Suspense boundary through onError;
// renderToString would silently render the fallback instead.
const render = (element) => new Promise((done) => {
  let html = "";
  const thrown = [];
  const sink = new Writable({write(chunk, _enc, next) { html += chunk; next(); }});
  sink.on("finish", () => done({html, thrown}));
  const stream = renderToPipeableStream(element, {
    onError(error) { thrown.push(error); },
    onShellError(error) { thrown.push(error); done({html, thrown}); },
    onAllReady() { stream.pipe(sink); },
  });
});
const errors = [], frames = [];
const cfg = LESSON || {};
for (const k of ["durationInFrames", "fps", "width", "height"])
  if (!Number.isFinite(cfg[k]) || cfg[k] <= 0) errors.push("LESSON." + k + " must be a positive number");
if (!errors.length) {
  const n = cfg.durationInFrames, samples = 24;
  for (let i = 0; i <= samples; i++) {
    const f = Math.min(n - 1, Math.round((n - 1) * i / samples));
    const realError = console.error;
    const logged = [];
    console.error = (...a) => logged.push(a.map(String).join(" ").slice(0, 300));
    const {html, thrown} = await render(<Thumbnail component={Lesson} compositionWidth={cfg.width}
      compositionHeight={cfg.height} durationInFrames={n} fps={cfg.fps} frameToDisplay={f} />);
    console.error = realError;
    frames.push({frame: f, chars: html.length});
    for (const e of thrown) errors.push("frame " + f + ": " + ((e && e.message) || e));
    if (!thrown.length && html.length < 400) errors.push("frame " + f + ": almost nothing rendered");
    for (const l of logged) if (!/Warning: Each child|useLayoutEffect|The above error occurred/.test(l)) errors.push("frame " + f + " console.error: " + l);
  }
}
console.log(JSON.stringify({errors: [...new Set(errors)].slice(0, 20), frames}));
`);
try {
  await esbuild.build({...common, entryPoints: [checkEntry], outfile: join(tmp, "check.mjs"), platform: "node",
    format: "esm", banner: {js: "import {createRequire as __cr} from 'module'; const require = __cr(import.meta.url);"}});
} catch (e) {
  rmSync(tmp, {recursive: true, force: true});
  report({ok: false, stage: "compile", errors: fmtErrors(e)});
}
// Model code runs here: no file writes, child processes, workers or native addons.
const run = spawnSync(process.execPath, ["--permission", `--allow-fs-read=${tmp}`, join(tmp, "check.mjs")],
  {encoding: "utf8", timeout: 180000});
rmSync(tmp, {recursive: true, force: true});
let checked;
try { checked = JSON.parse(run.stdout.trim().split("\n").pop()); }
catch { report({ok: false, stage: "render", errors: [(run.stderr || run.stdout || "no output").slice(-1500)]}); }
if (checked.errors.length) report({ok: false, stage: "render", errors: checked.errors, frames: checked.frames});

// 2. Browser bundle: the composition inside a <Player> with controls; ?frame=N opens paused there.
const entry = join(dirname(resolve(outArg)), "_entry.tsx");
writeFileSync(entry, `
import {createRoot} from "react-dom/client";
import {Player} from "@remotion/player";
import {Lesson, LESSON} from ${JSON.stringify(lesson)};
const query = new URLSearchParams(location.search);
const still = query.has("frame") ? Math.max(0, Math.min(LESSON.durationInFrames - 1, Number(query.get("frame")) || 0)) : null;
createRoot(document.getElementById("player")).render(
  <Player component={Lesson} durationInFrames={LESSON.durationInFrames} fps={LESSON.fps}
    compositionWidth={LESSON.width} compositionHeight={LESSON.height} initialFrame={still ?? 0}
    controls autoPlay={false} loop clickToPlay showVolumeControls allowFullscreen
    style={{width: "100%", aspectRatio: LESSON.width + " / " + LESSON.height}} />);
`);
try {
  await esbuild.build({...common, entryPoints: [entry], outfile: resolve(outArg), platform: "browser",
    format: "iife", minify: true});
} catch (e) {
  report({ok: false, stage: "bundle", errors: fmtErrors(e)});
} finally {
  rmSync(entry, {force: true});
}
report({ok: true, stage: "done", errors: [], frames: checked.frames});
