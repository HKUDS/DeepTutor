const NEXT_TYPE_INCLUDE = /^\.next[^/]*\/(?:dev\/)?types\/\*\*\/\*\.ts$/;

function rewriteTypeIncludes(contents, activeIncludes) {
  const config = JSON.parse(contents);
  const include = Array.isArray(config.include) ? config.include : [];
  config.include = [
    ...include.filter(
      (entry) =>
        typeof entry !== "string" || !NEXT_TYPE_INCLUDE.test(entry),
    ),
    ...activeIncludes,
  ];
  return `${JSON.stringify(config, null, 2)}\n`;
}

/** Restrict generated route types to the output tree used by this build. */
export function configureTypeIncludes(contents, distDir) {
  return rewriteTypeIncludes(contents, [
    `${distDir}/types/**/*.ts`,
    `${distDir}/dev/types/**/*.ts`,
  ]);
}

/** Type-check source without trusting an arbitrary historical Next cache. */
export function removeNextTypeIncludes(contents) {
  return rewriteTypeIncludes(contents, []);
}
