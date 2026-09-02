import assert from "node:assert/strict";
import { readFileSync, readdirSync } from "node:fs";
import path from "node:path";
import test from "node:test";

const WORKSPACE_DIR = "components/reading/workspace";
const LIBRARY_DIR = "components/reading/library";

function source(file: string): string {
  return readFileSync(path.resolve(process.cwd(), file), "utf8");
}

/**
 * The workspace is a folder of collaborating modules, not one file. Product
 * invariants ("no browser prompts", "theme tokens only") hold over the whole
 * surface, so assert against the concatenation rather than letting a rule
 * quietly lapse the moment a component moves to a sibling file.
 */
function workspaceSurface(): string {
  return concat(WORKSPACE_DIR);
}

/** The two library views plus the dialog they share. */
function librarySurface(): string {
  return concat(LIBRARY_DIR);
}

function concat(dir: string): string {
  return readdirSync(path.resolve(process.cwd(), dir))
    .filter((name) => /\.tsx?$/.test(name))
    .map((name) => source(path.join(dir, name)))
    .join("\n");
}

test("Reading V2 uses in-product dialogs instead of blocking browser prompts", () => {
  const library = librarySurface();
  const workspace = workspaceSurface();

  assert.doesNotMatch(library, /window\.(?:prompt|confirm)\s*\(/);
  assert.doesNotMatch(workspace, /window\.(?:prompt|confirm)\s*\(/);
  assert.match(library, /DeleteCollectionDialog/);
  assert.match(library, /DeleteMaterialDialog/);
  assert.match(workspace, /WorkspaceValueDialog/);
});

test("the dedicated workspace owns exactly one source navigator", () => {
  const page = source(`${WORKSPACE_DIR}/ReadingWorkspace.tsx`);
  const navigator = source(`${WORKSPACE_DIR}/SourceNavigator.tsx`);
  const reader = source("components/reading/ReaderPane.tsx");

  assert.match(page, /<ReaderPane/);
  assert.match(page, /grid-rows-\[minmax\(0,1fr\)\]/);
  assert.match(navigator, /export function SourceNavigator/);
  // The reader renders one open document and nothing else: navigation, tabs
  // and the resize seam belong to the workspace shell. A second mode here is
  // what let the retired chat-embedded reader drift into a parallel product.
  assert.doesNotMatch(reader, /embedded/);
  assert.doesNotMatch(
    reader,
    /SourceNavigator|ReaderOutline|ReaderResizeHandle/,
  );
});

test("the workspace shell stays a view, with its network work in one hook", () => {
  const page = source(`${WORKSPACE_DIR}/ReadingWorkspace.tsx`);
  const hook = source(`${WORKSPACE_DIR}/useReadingWorkspace.ts`);

  // Hydration, polling and the source lifecycle have exactly one owner. When
  // they lived in the shell alongside the layout it grew past 2500 lines and
  // every effect had to be re-read to find which state it touched.
  assert.match(hook, /export function useReadingWorkspace/);
  assert.match(hook, /getReadingWorkspace|listReadingConversations/);
  assert.doesNotMatch(page, /getReadingWorkspace\(/);
  assert.doesNotMatch(page, /Promise\.allSettled/);
  assert.ok(
    page.split("\n").length < 900,
    "the workspace shell should stay a readable view component",
  );
});

test("reading is reachable only through its own workspace", () => {
  const chat = [
    source("app/(workspace)/chat/page.tsx"),
    source("app/(workspace)/chat/[sessionId]/page.tsx"),
  ].join("\n");
  const css = source("app/globals.css");

  // The composer must not offer reading as a chat capability, and the chat
  // shell must not carry the retired split-pane layout.
  assert.doesNotMatch(chat, /immersive_reading|ReaderPane/);
  assert.doesNotMatch(chat, /data-reader-open/);
  assert.doesNotMatch(css, /dt-reader-shell|--reader-width/);
});

test("reading reuses the workspace runtime without nesting another provider", () => {
  const layout = source("app/(workspace)/reading/layout.tsx");

  assert.doesNotMatch(layout, /UnifiedChatProvider|ChatRuntimeProvider/);
  assert.match(layout, /QuizFollowupProvider/);
  assert.match(layout, /GeogebraTabProvider/);
});

test("Reading V2 inherits product theme tokens instead of a fixed cream palette", () => {
  const library = librarySurface();
  const workspace = workspaceSurface();

  assert.match(library, /var\(--background\)/);
  assert.match(workspace, /var\(--primary\)/);
  assert.doesNotMatch(library, /#[0-9a-fA-F]{6}/);
  assert.doesNotMatch(workspace, /#[0-9a-fA-F]{6}/);
});

test("media relies on native player controls and PDF navigation is honest", () => {
  const page = source(`${WORKSPACE_DIR}/ReadingWorkspace.tsx`);
  const navigator = source(`${WORKSPACE_DIR}/SourceNavigator.tsx`);
  const workspace = workspaceSurface();
  const reader = source("components/reading/ReaderPane.tsx");

  assert.doesNotMatch(workspace, /function MediaTimeline/);
  assert.doesNotMatch(workspace, /aria-label=\{t\("Video timeline"\)\}/);
  assert.match(navigator, /material\?\.render_mode === "pdf"/);
  assert.match(navigator, /synthesised/);
  assert.match(navigator, /Page \{\{page\}\}/);
  assert.match(navigator, /aria-label=\{t\("Collapse contents"\)\}/);
  assert.match(page, /externalJump=\{documentJump\}/);
  assert.match(reader, /requestJump\(externalJump\.locator/);
});

test("narrow reading workspaces keep the source primary and use dismissible panels", () => {
  const page = source(`${WORKSPACE_DIR}/ReadingWorkspace.tsx`);
  const workspace = workspaceSurface();

  assert.match(page, /min-width: 1280px/);
  assert.match(page, /xl:grid-cols-/);
  assert.match(workspace, /mobileOpen/);
  // The companion is its own module now (`ReadingCompanion.tsx`), so these
  // two hold over the surface rather than over the shell — exactly the case
  // `workspaceSurface` exists for.
  assert.match(workspace, /xl:static xl:w-auto xl:shadow-none/);
  assert.match(workspace, /aria-label=\{t\("Close reading companion"\)\}/);
});

test("failed imports expose the durable retry endpoint in product UI", () => {
  const page = source(`${WORKSPACE_DIR}/ReadingWorkspace.tsx`);
  const chrome = source(`${WORKSPACE_DIR}/WorkspaceChrome.tsx`);
  const api = source("lib/reading-workspace-api.ts");

  assert.match(api, /export async function retryReadingMaterial/);
  assert.match(api, /\/materials\/\$\{materialId\}\/retry/);
  assert.match(page, /retryReadingMaterial/);
  assert.match(chrome, /retrying \? t\("Retrying…"\) : t\("Retry"\)/);
});

test("Markdown heading markers stay anchorable but are visually hidden", () => {
  const textReader = source("components/reading/TextUnitView.tsx");

  assert.match(textReader, /markerPrefix/);
  assert.match(textReader, /markerSuffix/);
  assert.match(textReader, /aria-hidden="true"/);
  assert.match(textReader, /text-\[0px\]/);
});

test("Immersive Reading speaks in collections and materials only", () => {
  const library = librarySurface();
  const api = source("lib/reading-workspace-api.ts");

  // Folders and tags were removed from the product: two organising schemes
  // that were always empty, on top of a hierarchy that already had five words
  // for three things.
  assert.doesNotMatch(
    library,
    /folder_id|tag_id|createReadingFolder|ReadingTag/,
  );
  assert.doesNotMatch(api, /folder_id|tag_id|ReadingFolder|ReadingTag/);

  // A material can live in several collections, and the library view is where
  // that membership — including "in none of them" — is visible.
  assert.match(library, /Material library/);
  assert.match(library, /Not in a collection/);
  assert.match(api, /collections\?: ReadingMaterialCollection\[\]/);
});

test("uploads are checked against the library before they land", () => {
  const dialog = source(`${LIBRARY_DIR}/AddMaterialsDialog.tsx`);
  const api = source("lib/reading-workspace-api.ts");

  // The browser hashes the file with the server's own content-id algorithm, so
  // "you already have this" is answered before the upload, while the user can
  // still choose to reuse it or keep a separate copy.
  assert.match(api, /export async function readingContentId/);
  assert.match(api, /SHA-256/);
  assert.match(api, /library\/duplicate-check/);
  assert.match(dialog, /checkReadingDuplicates/);
  assert.match(dialog, /same_name/);
  assert.match(dialog, /reuse: item\.decision === "reuse"/);
});
