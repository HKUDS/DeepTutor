import { spawn } from "node:child_process";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { compressGifs } from "./gif/compress-gifs.mjs";

const DOCS_ROOT = path.resolve(fileURLToPath(new URL("..", import.meta.url)));
const hook = path.join(DOCS_ROOT, "scripts", "gif", "webreel-react-type.mjs");
const names = process.argv.slice(2);

const child = spawn(
  path.join(DOCS_ROOT, "node_modules", ".bin", "webreel"),
  ["record", "-c", "webreel.config.json", ...names],
  {
    cwd: DOCS_ROOT,
    stdio: "inherit",
    env: {
      ...process.env,
      NODE_OPTIONS: [process.env.NODE_OPTIONS, `--import ${hook}`].filter(Boolean).join(" "),
    },
  },
);

child.on("close", (code) => {
  if (code !== 0) {
    process.exitCode = code ?? 1;
    return;
  }
  compressGifs().catch((error) => {
    console.error(error.message);
    process.exitCode = 1;
  });
});
