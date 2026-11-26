import { spawn } from "node:child_process";
import { readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

import { compressGifs } from "./gif/compress-gifs.mjs";

const DOCS_ROOT = path.resolve(fileURLToPath(new URL("..", import.meta.url)));
const hook = path.join(DOCS_ROOT, "scripts", "gif", "webreel-react-type.mjs");
const names = process.argv.slice(2);

const config = JSON.parse(readFileSync(path.join(DOCS_ROOT, "webreel.config.json"), "utf8"));
const videos = config.videos ?? {};
const targets =
  names.length > 0
    ? names.map((name) => videos[name]?.output ?? `${name}.gif`)
    : Object.entries(videos).map(([name, spec]) => spec?.output ?? `${name}.gif`);

const child = spawn(
  path.join(DOCS_ROOT, "node_modules", ".bin", "webreel"),
  ["record", "-c", "webreel.config.json", ...names],
  {
    cwd: DOCS_ROOT,
    stdio: "inherit",
    env: {
      ...process.env,
      NODE_OPTIONS: [process.env.NODE_OPTIONS, `--import=${pathToFileURL(hook).href}`]
        .filter(Boolean)
        .join(" "),
    },
  },
);

child.on("close", (code) => {
  if (code !== 0) {
    process.exitCode = code ?? 1;
    return;
  }
  compressGifs(targets).catch((error) => {
    console.error(error.message);
    process.exitCode = 1;
  });
});
