const Module = require("node:module");
const path = require("node:path");

const distRoot = process.env.DEEPTUTOR_NODE_TESTS_DIST_ROOT;
if (!distRoot) {
  throw new Error("DEEPTUTOR_NODE_TESTS_DIST_ROOT is required");
}
const originalResolveFilename = Module._resolveFilename;

Module._resolveFilename = function (request, parent, isMain, options) {
  if (typeof request === "string" && request.startsWith("@/")) {
    return originalResolveFilename.call(
      this,
      path.join(distRoot, request.slice(2)),
      parent,
      isMain,
      options,
    );
  }

  return originalResolveFilename.call(this, request, parent, isMain, options);
};
