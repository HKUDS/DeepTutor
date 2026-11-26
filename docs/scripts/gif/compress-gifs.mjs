import { spawn } from "node:child_process";
import { rename } from "node:fs/promises";
import { readdir } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const DOCS_ROOT = path.resolve(fileURLToPath(new URL("../..", import.meta.url)));
const GIF_DIR = path.join(DOCS_ROOT, "public", "gifs");

function run(command, args) {
  return new Promise((resolve, reject) => {
    const child = spawn(command, args, { stdio: "inherit" });
    child.on("error", reject);
    child.on("close", (code) => {
      if (code === 0) resolve();
      else reject(new Error(`${command} exited ${code}`));
    });
  });
}

export async function compressGifs(targetNames = null) {
  const requested =
    Array.isArray(targetNames) && targetNames.length > 0
      ? [...new Set(targetNames.map((name) => path.basename(name)).filter((name) => name.endsWith(".gif")))]
      : (await readdir(GIF_DIR)).filter((name) => name.endsWith(".gif"));
  for (const name of requested) {
    const input = path.join(GIF_DIR, name);
    const temp = path.join(GIF_DIR, `.${name}.tmp.gif`);
    await run("ffmpeg", [
      "-y",
      "-i",
      input,
      "-filter_complex",
      "[0:v]fps=8,setpts=0.62*PTS,split[s0][s1];[s0]palettegen=stats_mode=diff:max_colors=96[p];[s1][p]paletteuse=dither=bayer:bayer_scale=3",
      temp,
    ]);
    await rename(temp, input);
    console.log(`compressed ${name}`);
  }
}

if (process.argv[1] && fileURLToPath(import.meta.url) === path.resolve(process.argv[1])) {
  const cliTargets = process.argv.slice(2);
  compressGifs(cliTargets.length > 0 ? cliTargets : null).catch((error) => {
    console.error(error.message);
    process.exitCode = 1;
  });
}
